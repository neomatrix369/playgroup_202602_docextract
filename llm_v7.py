"""V7 Go API client — async entity create + poll, with checkpoint/resume (Doubleword-shaped surface).

V7 Go does not expose an OpenAI-style JSONL batch file. This module mirrors *llm_doubleword.py*
orchestration hooks (checkpoint, submit_batch, poll_batch, download_results) by mapping each TSV
row to one Entity on your Agent (project). See:

  https://docs.go.v7labs.com/reference/create-entities-programmatically
  https://docs.go.v7labs.com/reference/entity-get

Environment (see also config_models_v7.py per-model overrides):

  V7_GO_API_KEY           — API key (header X-API-KEY)
  V7_GO_WORKSPACE_ID      — workspace UUID
  V7_GO_AGENT_ID          — agent / project UUID
  V7_GO_INPUT_FIELD_SLUG  — property slug for pasted OCR text (default: document-text)
  V7_GO_FILE_FIELD_SLUG   — property slug/id for PDF upload when multimodal (default: document-pdf for
                            single-output agents only). For Go Agent v2, omit this unless you need to
                            override: the code uses the File property id from agent_template_json. The
                            legacy default document-pdf is not applied as an override when the template
                            defines a different File property (avoids start_file_upload 404). If your
                            V7_GO_AGENT_ID is a different project than the JSON export, set this or
                            file_field_slug to the File property id copied from the V7 UI.
  Go Agent v2 (multi-field): set agent_template_json in config_models_v7 to v7_go_agent_v2_template.json
  export — creates empty entities, uploads PDF to the File property, polls all tool fields, and merges
  values into one JSON blob for the extractor (see _V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY).
  V7_GO_PDF_DIR           — directory containing PDFs named like column 1 of playgroup_dev_in.tsv (default: data)
  V7_GO_OUTPUT_FIELD_SLUG — property slug the agent fills with model output (default: extracted-json)
  V7_GO_PARENT_ENTITY_ID  — required for collection (child) agents: parent entity UUID in the parent project
  V7_GO_BASE_URL          — default https://go.v7labs.com (OpenAPI server in official docs).
                            STUB: v7-go-cli sometimes uses https://api.go.v7labs.com — try either if you see DNS/404 errors.
  V7_GO_DEBUG_HTTP        — if 1/true: log each entity GET (field statuses); noisy during polling.
  V7_GO_PROPERTY_PREFLIGHT — if 1/true (default for Go Agent v2): before creating PDF entities, verify every
                            property in ``agent_template_json`` exists on the live agent (GET properties).
                            Set to 0/false to skip (faster, no extra API round-trip).
  V7_GO_PROPERTY_PREFLIGHT_EACH_PDF — if 1/true: run that check before **each** PDF row (iterative scans);
                            default 0 = once per batch (``submit_batch``) or per ``extract_one_row_async`` call.
  V7_GO_AUTO_ENSURE_PROPERTIES — if 1/true (default): when preflight fails, POST missing properties from the
                            template, re-sync ``agent_template_json`` from the API, then retry preflight once.

STUB points are marked inline: token accounting and advanced error taxonomy.

PDF upload (multimodal models): after entity create, see
  https://docs.go.v7labs.com/reference/entity-start-file-upload
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

import utils
from config_models_v7 import V7_MODELS
from utils import get_logger, add_file_logger

logger = get_logger(__name__)
add_file_logger("llm_v7_calls.log", name_filter=__name__)

load_dotenv()

# ── Persistence paths (separate from Doubleword to avoid collisions) ─────────
CHECKPOINT_FILE = "data/.v7_checkpoints.json"
FAILED_ROWS_FILE = "data/.v7_failed_rows.json"
UNAVAILABLE_MODELS_FILE = "data/.v7_unavailable_models.json"

# ── In-process cache: poll_batch → download_results without re-fetching entities ──
# Cleared after download_results consumes the batch (same contract as DW output file download).
_RESULT_CACHE: dict[str, dict[int, dict[str, Any]]] = {}

# Default HTTP concurrency for entity creation (avoid hammering API)
_DEFAULT_CREATE_CONCURRENCY = 5

# Property display names in v7_go_agent_v2_template.json → extractor ALL_FIELDS keys
_V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY: dict[str, str] = {
    "Charity number": "charity_number",
    "Charity name": "charity_name",
    "Report date": "report_date",
    "Income annually (GBP)": "income_annually_in_british_pounds",
    "Spending annually (GBP) copy": "spending_annually_in_british_pounds",
    "Postcode": "address__postcode",
    "Street line": "address__street_line",
    "Town": "address__post_town",
}

_GO_AGENT_TEMPLATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# v7_go_agent_v2_template.json uses this placeholder; replaced per model from ``v7_property_model``.
V7_GO_AGENT_TEMPLATE_MODEL_TOOL_PLACEHOLDER = "<model id>"


def apply_v7_template_tool_model_id(template: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Deep-copy ``template`` and set each property ``tool`` equal to the placeholder to ``model_id``."""
    mid = str(model_id).strip()
    if not mid:
        return copy.deepcopy(template)
    out = copy.deepcopy(template)
    projects = out.get("projects") or []
    if not projects:
        return out
    props = projects[0].get("properties")
    if not isinstance(props, list):
        return out
    for prop in props:
        if not isinstance(prop, dict):
            continue
        if prop.get("tool") == V7_GO_AGENT_TEMPLATE_MODEL_TOOL_PLACEHOLDER:
            prop["tool"] = mid
    return out


def invalidate_go_agent_template_cache(template_path: str | None = None) -> None:
    """Drop cached parsed template so the next ``load_go_agent_v2_specs`` reads disk again."""
    global _GO_AGENT_TEMPLATE_CACHE
    if template_path is None:
        _GO_AGENT_TEMPLATE_CACHE.clear()
        return
    want = os.path.abspath(template_path)
    for k in list(_GO_AGENT_TEMPLATE_CACHE.keys()):
        if os.path.abspath(k) == want:
            _GO_AGENT_TEMPLATE_CACHE.pop(k, None)


# Go Agent v2: optional list-properties preflight (see V7_GO_PROPERTY_PREFLIGHT*)
_GO_V2_PROPERTY_PREFLIGHT_LOCK = asyncio.Lock()
_GO_V2_PROPERTY_PREFLIGHT_DONE: set[tuple[str, str, str]] = set()


def _env_truthy(name: str, default: str = "1") -> bool:
    v = (os.getenv(name, default) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _run_go_v2_property_preflight_sync(
    template_abs: str,
    workspace_id: str,
    agent_id: str,
    tool_model_id: str | None = None,
) -> None:
    import v7_go_ensure

    base = os.getenv("V7_GO_BASE_URL", "https://go.v7labs.com").rstrip("/")
    key = _env_api_key()
    if not key:
        raise ValueError("V7_GO_API_KEY (or V7_API_KEY) is required for V7_GO_PROPERTY_PREFLIGHT")
    with httpx.Client(
        base_url=base,
        headers={"X-API-KEY": key, "Accept": "application/json"},
        timeout=httpx.Timeout(120.0, connect=30.0),
    ) as c:
        try:
            v7_go_ensure.preflight_template_against_remote(
                template_abs,
                c,
                workspace_id,
                agent_id,
                tool_model_id=tool_model_id,
            )
        except v7_go_ensure.V7GoPreflightError:
            if not _env_truthy("V7_GO_AUTO_ENSURE_PROPERTIES", "1"):
                raise
            logger.warning(
                "[V7] Go Agent v2 preflight failed (template vs agent); auto-ensuring properties from {!r}",
                template_abs,
            )
            rc = v7_go_ensure.ensure_properties(
                c,
                workspace_id,
                agent_id,
                template_abs,
                dry_run=False,
                tool_model_id=tool_model_id,
            )
            if rc != 0:
                raise RuntimeError(
                    f"v7_go_ensure.ensure_properties failed with exit code {rc} — fix the agent or template"
                )
            import sync_v7_go_agent_template as sync_tpl

            sync_tpl.sync_v7_go_agent_template_to_path(
                template_abs, validate_parse=True
            )
            invalidate_go_agent_template_cache(template_abs)
            v7_go_ensure.preflight_template_against_remote(
                template_abs,
                c,
                workspace_id,
                agent_id,
                tool_model_id=tool_model_id,
            )


async def _maybe_preflight_go_v2_properties(model_cfg: dict[str, Any]) -> None:
    """Verify template properties exist on the agent (Go Agent v2 only). No-op if disabled or no template."""
    if not _env_truthy("V7_GO_PROPERTY_PREFLIGHT", "1"):
        return
    rel = model_cfg.get("agent_template_json")
    if not rel:
        return
    path = _resolve_template_path(str(rel))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"V7 property preflight: agent_template_json not found: {path!r}")
    ws = _resolve_workspace_id(model_cfg)
    agent = _resolve_agent_id(model_cfg)
    key = (os.path.abspath(path), ws, agent)
    each_pdf = _env_truthy("V7_GO_PROPERTY_PREFLIGHT_EACH_PDF", "0")
    async with _GO_V2_PROPERTY_PREFLIGHT_LOCK:
        if not each_pdf and key in _GO_V2_PROPERTY_PREFLIGHT_DONE:
            return
        mid = str(model_cfg.get("v7_property_model") or "").strip() or None
        await asyncio.to_thread(_run_go_v2_property_preflight_sync, path, ws, agent, mid)
        if not each_pdf:
            _GO_V2_PROPERTY_PREFLIGHT_DONE.add(key)

# Same conservative truncation heuristic as extractor uses for Doubleword rows
_PROMPT_OVERHEAD_TOKENS = 500
_CHARS_PER_TOKEN = 3

# V7 OpenAPI PropertyIdOrSlug: UUID (lowercase hex) OR slug ^[a-z_-][a-z0-9_-]*$
# Project JSON exports use mixed-case ``property_*`` ids; path segments must be lowercased to match the API
# (otherwise start_file_upload returns 400 Invalid format).
_V7_PROPERTY_SLUG_RE = re.compile(r"^[a-z_-][a-z0-9_-]*$")
_V7_PROPERTY_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_V7_PROPERTY_EXPORT_ID_RE = re.compile(r"^property_[A-Za-z0-9_-]+$")


def _v7_property_display_name_to_entity_field_slug(name: str) -> str:
    """Map a V7 property display ``name`` to the kebab-case key used in entity ``fields`` JSON.

    REST paths accept property UUIDs, but entity GET responses key ``fields`` by slug (e.g.
    ``charity-number``), not by id. Export templates only carry ``id`` + ``name`` for tool fields.
    """
    s = str(name).strip().lower()
    if not s:
        return ""
    s = re.sub(r"\(([^)]+)\)", r" \1 ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _normalize_v7_property_id_or_slug(s: str) -> str:
    """Return a value valid for URL paths and entity ``fields`` keys (PropertyIdOrSlug)."""
    t = str(s).strip()
    if not t:
        raise ValueError("empty V7 property id or slug")
    lowered = t.lower()
    if _V7_PROPERTY_UUID_RE.match(lowered):
        return lowered
    if _V7_PROPERTY_EXPORT_ID_RE.match(t):
        low = t.lower()
        if _V7_PROPERTY_SLUG_RE.match(low):
            return low
        raise ValueError(
            f"invalid V7 export property id {t!r}: lowercased form {low!r} is not a valid PropertyIdOrSlug"
        )
    if _V7_PROPERTY_SLUG_RE.match(t):
        return t
    if _V7_PROPERTY_SLUG_RE.match(lowered):
        return lowered
    raise ValueError(
        f"invalid V7 property id or slug {t!r}: expected UUID or slug "
        r"matching ^[a-z_-][a-z0-9_-]*$ (see V7 UI → copy property slug)"
    )


def _env_api_key() -> str:
    return (os.getenv("V7_GO_API_KEY") or os.getenv("V7_API_KEY") or "").strip()


def _resolve_workspace_id(model_cfg: dict) -> str:
    w = model_cfg.get("workspace_id") or os.getenv("V7_GO_WORKSPACE_ID", "")
    return str(w).strip()


def _resolve_agent_id(model_cfg: dict) -> str:
    a = model_cfg.get("agent_id") or os.getenv("V7_GO_AGENT_ID", "")
    return str(a).strip()


def _resolve_input_slug(model_cfg: dict) -> str:
    s = model_cfg.get("input_field_slug") or os.getenv("V7_GO_INPUT_FIELD_SLUG", "document-text")
    return _normalize_v7_property_id_or_slug(str(s))


def _resolve_output_slug(model_cfg: dict) -> str:
    s = model_cfg.get("output_field_slug") or os.getenv("V7_GO_OUTPUT_FIELD_SLUG", "extracted-json")
    return _normalize_v7_property_id_or_slug(str(s))


_LEGACY_MULTIMODAL_FILE_SLUG_DEFAULT = "document-pdf"


def _resolve_file_field_slug(model_cfg: dict) -> str:
    s = model_cfg.get("file_field_slug") or os.getenv(
        "V7_GO_FILE_FIELD_SLUG", _LEGACY_MULTIMODAL_FILE_SLUG_DEFAULT
    )
    return _normalize_v7_property_id_or_slug(str(s))


def _resolve_go_v2_file_field_pair(model_cfg: dict, go_v2: dict) -> tuple[str, str]:
    """Return (file property id/slug for upload, short source label for operator logs).

    Precedence: per-model ``file_field_slug`` → ``V7_GO_FILE_FIELD_SLUG`` (unless it is only the
    legacy default *document-pdf* while the template names a different File property) →
    ``file_property_id`` parsed from ``agent_template_json``.

    Rationale: many .env files set ``V7_GO_FILE_FIELD_SLUG=document-pdf`` for non-v2 models; for
    Go Agent v2 the bundled export uses ids like ``property_…``, so treating *document-pdf* as a
    universal override causes start_file_upload 404.
    """
    cfg = model_cfg.get("file_field_slug")
    if cfg is not None and str(cfg).strip():
        return (
            _normalize_v7_property_id_or_slug(str(cfg)),
            "file_field_slug (config_models_v7)",
        )
    env_raw = (os.getenv("V7_GO_FILE_FIELD_SLUG") or "").strip()
    if env_raw:
        norm = _normalize_v7_property_id_or_slug(env_raw)
        tpl_id = go_v2["file_property_id"]
        if norm == _LEGACY_MULTIMODAL_FILE_SLUG_DEFAULT and tpl_id != norm:
            logger.warning(
                "[V7] V7_GO_FILE_FIELD_SLUG={!r} is the legacy multimodal default; for Go Agent v2 "
                "the File property from agent_template_json is usually {!r}. Using the template id. "
                "If uploads still 404, your V7_GO_AGENT_ID project may differ from the export — set "
                "file_field_slug on the model or V7_GO_FILE_FIELD_SLUG to the File property id from "
                "the V7 UI for this agent.",
                env_raw,
                tpl_id,
            )
            return (tpl_id, "agent_template_json (legacy default env ignored)")
        return (norm, "V7_GO_FILE_FIELD_SLUG")
    return (go_v2["file_property_id"], "agent_template_json")


def _resolve_go_v2_file_property(model_cfg: dict, go_v2: dict) -> str:
    return _resolve_go_v2_file_field_pair(model_cfg, go_v2)[0]


def _resolve_pdf_dir() -> str:
    d = (os.getenv("V7_GO_PDF_DIR") or "data").strip()
    return os.path.abspath(d)


def _resolve_parent_entity_id(model_cfg: dict) -> str | None:
    """Collection projects require parent_entity_id on create; standalone agents omit it.

    ``parent_entity_id`` must be an *entity* UUID from the *parent* project. A common mistake is
    copying ``V7_GO_AGENT_ID`` (the project id) into ``V7_GO_PARENT_ENTITY_ID``, which breaks
    entity create (often HTTP 500).
    """
    p = model_cfg.get("parent_entity_id") or os.getenv("V7_GO_PARENT_ENTITY_ID", "")
    p = str(p).strip()
    if not p:
        return None
    agent = str(model_cfg.get("agent_id") or os.getenv("V7_GO_AGENT_ID", "") or "").strip()
    if agent and p == agent:
        logger.warning(
            "[V7] parent_entity_id equals agent/project id {!r} — that is not a valid parent entity. "
            "Unset V7_GO_PARENT_ENTITY_ID for standalone agents; for collection agents use an entity id "
            "from the parent project (V7 UI). Ignoring parent_entity_id.",
            p,
        )
        return None
    return p


def _package_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_template_path(template_filename: str) -> str:
    p = template_filename.strip()
    if os.path.isabs(p):
        return p
    return os.path.join(_package_dir(), p)


def parse_go_agent_export_for_v2(template: dict[str, Any]) -> dict[str, Any]:
    """Read a V7 Go project export JSON (e.g. v7_go_agent_v2_template.json).

    Returns ``file_property_id`` and ``v2_output_specs`` with ``lookup_keys`` (uuid + name-derived slug)
    so entity ``fields`` can be resolved: API paths accept property UUIDs, but entity JSON keys fields
    by display-name slugs unless a nested field ``id`` matches the property uuid.
    """
    projects = template.get("projects") or []
    if not projects:
        raise ValueError("V7 template: no projects[]")
    props = projects[0].get("properties") or []
    file_id: str | None = None
    specs: list[dict[str, str]] = []
    unmapped_tool_text: list[str] = []

    for prop in props:
        pid = prop.get("id")
        if not pid:
            continue
        name = str(prop.get("name") or "").strip()
        ptype = prop.get("type")
        tool = prop.get("tool")
        if ptype == "file":
            file_id = _normalize_v7_property_id_or_slug(str(pid))
            continue
        key = _V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY.get(name)
        if key:
            pid_norm = _normalize_v7_property_id_or_slug(str(pid))
            name_slug = _v7_property_display_name_to_entity_field_slug(name)
            lookup_keys = [pid_norm]
            if name_slug and name_slug not in lookup_keys:
                lookup_keys.append(name_slug)
            tpl_slug = prop.get("slug")
            if tpl_slug and str(tpl_slug).strip():
                try:
                    sk = _normalize_v7_property_id_or_slug(str(tpl_slug))
                    if sk not in lookup_keys:
                        lookup_keys.insert(1, sk)
                except ValueError:
                    pass
            specs.append(
                {
                    "field_key": key,
                    "property_id": pid_norm,
                    "lookup_keys": lookup_keys,
                }
            )
            continue
        if ptype == "text" and tool and str(tool) != "manual":
            unmapped_tool_text.append(f"{name!r} ({pid})")

    if not file_id:
        raise ValueError("V7 template: no file-type property found")
    if unmapped_tool_text:
        logger.warning(
            "[V7] Go agent v2 template has unmapped tool text properties (add to _V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY): {}",
            ", ".join(unmapped_tool_text),
        )
    if len(specs) < len(_V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY):
        logger.warning(
            "[V7] Go agent v2: mapped {}/{} expected output fields by name",
            len(specs),
            len(_V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY),
        )
    return {"file_property_id": file_id, "v2_output_specs": specs}


def load_go_agent_v2_specs(model_cfg: dict) -> dict[str, Any] | None:
    """If model_cfg has agent_template_json, load and parse template; else None."""
    rel = model_cfg.get("agent_template_json")
    if not rel:
        return None
    path = _resolve_template_path(str(rel))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"V7 agent_template_json not found: {path!r}")
    mtime = os.path.getmtime(path)
    cached = _GO_AGENT_TEMPLATE_CACHE.get(path)
    if cached and cached[0] == mtime:
        data = cached[1]
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("V7 template root must be a JSON object")
        _GO_AGENT_TEMPLATE_CACHE[path] = (mtime, data)
    mid = str(model_cfg.get("v7_property_model") or "").strip()
    if mid:
        data = apply_v7_template_tool_model_id(data, mid)
    return parse_go_agent_export_for_v2(data)


def resolved_v7_settings_for_log(model_cfg: dict[str, Any]) -> dict[str, Any]:
    """Resolved workspace, agent, and property slugs for operator logs (no API keys)."""
    ws = _resolve_workspace_id(model_cfg)
    agent = _resolve_agent_id(model_cfg)
    base = os.getenv("V7_GO_BASE_URL", "https://go.v7labs.com").rstrip("/")
    out: dict[str, Any] = {
        "V7_GO_BASE_URL": base,
        "workspace_id": ws or "(unset — V7_GO_WORKSPACE_ID or workspace_id in model config)",
        "agent_id": agent or "(unset — V7_GO_AGENT_ID or agent_id in model config)",
        "multimodal": bool(model_cfg.get("multimodal")),
        "model": model_cfg.get("model", ""),
    }
    raw_template = model_cfg.get("agent_template_json")
    if raw_template:
        out["agent_template_json"] = str(raw_template)
        try:
            go_v2 = load_go_agent_v2_specs(model_cfg)
        except Exception as e:
            out["go_agent_v2_load_error"] = str(e)[:400]
            go_v2 = None
        if go_v2:
            out["mode"] = "go_agent_v2"
            try:
                slug, src = _resolve_go_v2_file_field_pair(model_cfg, go_v2)
                out["file_field_for_upload"] = slug
                out["file_field_source"] = src
            except Exception as e:
                out["file_field_for_upload"] = f"(resolve error: {e})"
            out["v2_output_field_keys"] = [s["field_key"] for s in go_v2["v2_output_specs"]]
        else:
            out["mode"] = "go_agent_v2_template_missing_or_invalid"
    else:
        out["agent_template_json"] = "(none)"
        out["mode"] = "single_output_field"
        try:
            out["input_field_slug"] = _resolve_input_slug(model_cfg)
            out["output_field_slug"] = _resolve_output_slug(model_cfg)
            if model_cfg.get("multimodal"):
                out["file_field_slug"] = _resolve_file_field_slug(model_cfg)
        except Exception as e:
            out["slug_resolve_error"] = str(e)[:400]
    pe = _resolve_parent_entity_id(model_cfg)
    if pe:
        out["parent_entity_id"] = pe
    env_f = (os.getenv("V7_GO_FILE_FIELD_SLUG") or "").strip()
    if env_f:
        out["env_V7_GO_FILE_FIELD_SLUG"] = env_f
    return out


def hints_for_v7_unavailable_reason(
    model_short_name: str, reason: str, model_cfg: dict[str, Any]
) -> list[str]:
    """Short actionable lines to log after a skip based on the stored failure reason."""
    lines: list[str] = []
    r = reason.lower()
    if "start_file_upload" in r and "invalid format" in r:
        lines.append(
            "start_file_upload 400 Invalid format: V7 expects property path segments as lowercase UUID or "
            "slug (^[a-z_-][a-z0-9_-]*$). Export ids like property_xAbC… are normalized to lowercase in "
            "llm_v7 — upgrade/re-run; if it persists, check V7_GO_FILE_FIELD_SLUG matches the UI slug."
        )
    elif "start_file_upload" in r or ("404" in reason and "not_found" in r):
        lines.append(
            "start_file_upload 404: the File property id in the URL does not exist on this project. "
            "For Go Agent v2, omit V7_GO_FILE_FIELD_SLUG (or remove document-pdf) so the template "
            "export id is used, unless your V7_GO_AGENT_ID is a different project — then copy the File "
            "property id from the V7 UI into V7_GO_FILE_FIELD_SLUG or file_field_slug in config_models_v7.py."
        )
    if "must be set" in r and ("workspace" in r or "agent" in r):
        lines.append("Set V7_GO_WORKSPACE_ID and V7_GO_AGENT_ID (or per-model workspace_id / agent_id).")
    if "nodename nor servname" in r or "errno 8" in r:
        lines.append(
            "DNS failed for V7_GO_BASE_URL: use https://go.v7labs.com (code default). "
            "https://api.go.v7labs.com often does not resolve; unset V7_GO_BASE_URL or fix the host."
        )
    if "internal_server_error" in r and "entities" in r:
        lines.append(
            "POST /entities 500: check V7_GO_PARENT_ENTITY_ID — it must be a parent *entity* UUID, "
            "not the same as V7_GO_AGENT_ID (project id). Leave it unset for standalone agents."
        )
    if "document-text" in r and "property_not_found" in r:
        tpl = str(model_cfg.get("agent_template_json") or "").strip()
        if not tpl:
            lines.append(
                "This error is the legacy multimodal path: the client POSTs OCR text into field "
                "'document-text'. Go Agent v2 (File + per-field tools) has no such property — add "
                "agent_template_json (e.g. v7_go_agent_v2_template.json) and multimodal: True so the "
                "client creates an empty entity and uploads the PDF only; do not add 'document-text' in V7."
            )
        else:
            lines.append(
                "If config already has agent_template_json, the failure may be stale: remove this model "
                f"from {UNAVAILABLE_MODELS_FILE} (or delete the file) so the run retries with the current "
                "registry; adding 'document-text' in V7 is not required for Go Agent v2."
            )
    lines.append(
        f"To retry after fixing config, remove the {model_short_name!r} entry from {UNAVAILABLE_MODELS_FILE} "
        "(or delete the file), then re-run."
    )
    return lines


def _v7_error_detail_from_response(response: httpx.Response) -> str:
    """Prefer V7 JSON {code, message, details}; else first ~2k of body (httpx default omits this)."""
    text = (response.text or "").strip()
    try:
        data = response.json()
    except Exception:
        return text[:2000] if text else response.reason_phrase
    if not isinstance(data, dict):
        return text[:2000] if text else str(data)[:500]
    parts: list[str] = []
    for key in ("code", "message"):
        v = data.get(key)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    if data.get("details") is not None:
        parts.append(f"details={data['details']!r}")
    return " — ".join(parts) if parts else (text[:2000] if text else f"HTTP {response.status_code}")


def _v7_elapsed_ms(response: httpx.Response) -> float | None:
    if response.elapsed is None:
        return None
    return round(response.elapsed.total_seconds() * 1000, 2)


def _v7_http_meta_line(response: httpx.Response) -> str:
    """Compact line: status, method, path, elapsed — for log correlation."""
    url = response.request.url
    path = url.path if hasattr(url, "path") else str(url)
    ms = _v7_elapsed_ms(response)
    ms_s = f"{ms}ms" if ms is not None else "?"
    return f"{response.status_code} {response.request.method} {path} ({ms_s})"


def _v7_json_preview(data: Any, max_len: int = 2000) -> str:
    """JSON or repr, truncated (avoid megabyte logs on entity payloads)."""
    try:
        s = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(data)
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}… (+{len(s) - max_len} chars)"


def _v7_preview_entity_create_response(data: Any, max_len: int = 1800) -> str:
    """Same as JSON preview but drop huge ``fields`` string values (memory + log safe)."""
    if not isinstance(data, dict):
        return _v7_json_preview(data, max_len=max_len)
    slim: dict[str, Any] = {k: v for k, v in data.items() if k != "fields"}
    raw_fields = data.get("fields")
    if isinstance(raw_fields, dict):
        slim_fields: dict[str, Any] = {}
        for k, v in raw_fields.items():
            if isinstance(v, dict):
                slim_fields[str(k)] = {
                    sk: v.get(sk)
                    for sk in ("status", "error_message", "id")
                    if sk in v and v.get(sk) is not None
                } or {"_keys": list(v.keys())[:12]}
            elif isinstance(v, str):
                slim_fields[str(k)] = f"<str len={len(v)}>"
            else:
                slim_fields[str(k)] = type(v).__name__
        slim["fields"] = slim_fields
    return _v7_json_preview(slim, max_len=max_len)


def _v7_redact_presigned_url(url: str) -> str:
    """Log scheme/host/path only (query often contains signatures)."""
    if not url or not isinstance(url, str):
        return repr(url)
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}"[:500]
    except Exception:
        return "<url>"


def _v7_summarize_entity_for_log(ent: dict[str, Any]) -> dict[str, Any]:
    """Field keys + status/error only — not tool output text."""
    out: dict[str, Any] = {
        "entity_id": ent.get("id"),
        "top_keys": sorted(ent.keys())[:40],
    }
    fields = ent.get("fields")
    if not isinstance(fields, dict):
        return out
    brief: dict[str, Any] = {}
    for k, fo in list(fields.items())[:50]:
        if isinstance(fo, dict):
            brief[str(k)] = {
                "status": fo.get("status"),
                "err": (str(fo.get("error_message"))[:200] if fo.get("error_message") else None),
            }
        else:
            brief[str(k)] = type(fo).__name__
    if len(fields) > 50:
        brief["_truncated_fields"] = len(fields) - 50
    out["fields"] = brief
    return out


def _v7_log_http_error(operation: str, response: httpx.Response) -> None:
    detail = _v7_error_detail_from_response(response)
    body_preview = _v7_json_preview(response.text, max_len=1500) if (response.text or "").strip() else ""
    logger.error(
        "[V7] {} failed — {} | detail={} | body_preview={!r}",
        operation,
        _v7_http_meta_line(response),
        detail,
        body_preview[:1600],
    )


def create_client() -> httpx.AsyncClient:
    """Async HTTP client for V7 Go REST API (ApiKeyAuth: X-API-KEY).

    Base URL matches OpenAPI server in official docs (https://go.v7labs.com).
    STUB: mTLS / enterprise proxy — not handled here.
    """
    base = os.getenv("V7_GO_BASE_URL", "https://go.v7labs.com").rstrip("/")
    key = _env_api_key()
    if not key:
        logger.warning("[V7] V7_GO_API_KEY (or V7_API_KEY) is not set — API calls will fail.")
    return httpx.AsyncClient(
        base_url=base,
        headers={"X-API-KEY": key, "Accept": "application/json"},
        timeout=httpx.Timeout(120.0, connect=30.0),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Checkpoint persistence (same pattern as llm_doubleword)
# ═══════════════════════════════════════════════════════════════════════════


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(data: dict) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def remove_checkpoint_entry(model_short_name: str) -> None:
    cp = load_checkpoint()
    cp.pop(model_short_name, None)
    save_checkpoint(cp)


def _checkpoint_entry_for_batch(batch_id: str) -> tuple[str | None, dict | None]:
    for name, entry in load_checkpoint().items():
        if entry.get("batch_id") == batch_id:
            return name, entry
    return None, None


# ═══════════════════════════════════════════════════════════════════════════
#  Failed rows / unavailable models (Doubleword parity)
# ═══════════════════════════════════════════════════════════════════════════


def load_failed_rows() -> dict:
    if os.path.exists(FAILED_ROWS_FILE):
        with open(FAILED_ROWS_FILE) as f:
            return json.load(f)
    return {}


def save_failed_rows(data: dict) -> None:
    with open(FAILED_ROWS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update_failed_rows_entry(model_short_name: str, row_nums: list) -> None:
    fr = load_failed_rows()
    fr[model_short_name] = row_nums
    save_failed_rows(fr)


def remove_failed_rows_entry(model_short_name: str) -> None:
    fr = load_failed_rows()
    fr.pop(model_short_name, None)
    save_failed_rows(fr)


def load_unavailable_models() -> dict:
    if os.path.exists(UNAVAILABLE_MODELS_FILE):
        with open(UNAVAILABLE_MODELS_FILE) as f:
            return json.load(f)
    return {}


def mark_model_unavailable(model_short_name: str, reason: str) -> None:
    data = load_unavailable_models()
    data[model_short_name] = reason
    with open(UNAVAILABLE_MODELS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    logger.warning(
        "[V7] Model '{}' marked unavailable: {} — recorded in {}",
        model_short_name,
        reason,
        UNAVAILABLE_MODELS_FILE,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Row body + field parsing
# ═══════════════════════════════════════════════════════════════════════════


def _truncate_text(text_combined: str, model_cfg: dict) -> str:
    ctx = int(model_cfg.get("ctx", 262_000))
    max_chars = (ctx - _PROMPT_OVERHEAD_TOKENS) * _CHARS_PER_TOKEN
    if len(text_combined) > max_chars:
        logger.warning("[V7] Truncating input text {} → {} chars (ctx≈{})", len(text_combined), max_chars, ctx)
        return text_combined[:max_chars]
    return text_combined


def _entity_fields_get(fields: dict[str, Any], key: str) -> Any:
    """Resolve field object; keys may be mixed-case in API JSON while paths require normalized slugs."""
    if key in fields:
        return fields[key]
    want = str(key).lower()
    for k, v in fields.items():
        if str(k).lower() == want:
            return v
    return None


def _go_v2_resolve_field_object(fields: dict[str, Any], spec: dict[str, Any]) -> Any | None:
    """Find the field blob for one Go Agent v2 output spec (uuid key, slug keys, or nested ``id``)."""
    for lk in spec.get("lookup_keys") or ():
        fo = _entity_fields_get(fields, str(lk))
        if fo is not None:
            return fo
    pid = str(spec.get("property_id") or spec.get("slug") or "").strip().lower()
    if pid and _V7_PROPERTY_UUID_RE.match(pid):
        for fo in fields.values():
            if isinstance(fo, dict):
                fid = str(fo.get("id") or "").strip().lower()
                if fid == pid:
                    return fo
    fk = spec.get("field_key")
    if fk:
        for display_name, dk in _V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY.items():
            if dk == fk:
                ns = _v7_property_display_name_to_entity_field_slug(display_name)
                if ns:
                    fo = _entity_fields_get(fields, ns)
                    if fo is not None:
                        return fo
                break
    leg = spec.get("slug")
    if leg and not spec.get("lookup_keys"):
        return _entity_fields_get(fields, str(leg))
    return None


def _field_blob(field_obj: Any) -> tuple[str, str | None, str | None]:
    """Return (status, text_value_or_none, error_message_or_none) for a field object from entity JSON."""
    if not isinstance(field_obj, dict):
        return "unknown", None, None
    status = str(field_obj.get("status", "unknown"))
    err = field_obj.get("error_message")
    err_s = str(err) if err is not None else None

    # Typical shape: manual_value / tool_value blocks with "value"
    for key in ("tool_value", "manual_value"):
        block = field_obj.get(key)
        if isinstance(block, dict) and block.get("value") is not None:
            val = block["value"]
            if isinstance(val, (dict, list)):
                return status, json.dumps(val), err_s
            return status, str(val), err_s

    # Flat text response shape (OpenAPI FieldTextResponse)
    if field_obj.get("value") is not None:
        val = field_obj["value"]
        if isinstance(val, (dict, list)):
            return status, json.dumps(val), err_s
        return status, str(val), err_s

    return status, None, err_s


async def _post_entity(
    client: httpx.AsyncClient,
    workspace_id: str,
    agent_id: str,
    fields: dict[str, Any],
    wait_for_slugs: list[str] | None = None,
    parent_entity_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/workspaces/{ws}/projects/{agent}/entities — optional wait_for (blocking, ≤~45s each).

    ``fields`` is the JSON ``fields`` object. When empty (Go Agent v2 file-first flow), the ``fields``
    key is omitted from the body so the payload matches V7's documented empty entity (``{}``);
    sending ``{"fields": {}}`` can trigger a 500 on some API versions.
    For collection (child) projects, pass parent_entity_id (see V7 Go API / env V7_GO_PARENT_ENTITY_ID).
    """
    params: dict[str, Any] = {}
    if wait_for_slugs:
        # httpx repeats query keys for wait_for[]=a&wait_for[]=b
        params = [("wait_for[]", s) for s in wait_for_slugs]
    url = f"/api/workspaces/{workspace_id}/projects/{agent_id}/entities"
    payload: dict[str, Any] = {}
    if fields:
        payload["fields"] = fields
    if parent_entity_id:
        payload["parent_entity_id"] = parent_entity_id
    r = await client.post(url, json=payload, params=params)
    if r.is_error:
        _fields_log = f"keys={list(fields.keys())!r}" if fields else "omitted (empty)"
        _v7_log_http_error(
            f"entity_create (fields {_fields_log})",
            r,
        )
        detail = _v7_error_detail_from_response(r)
        raise httpx.HTTPStatusError(
            f"{r.status_code} {r.reason_phrase} for url {r.request.url!r} — {detail}",
            request=r.request,
            response=r,
        )
    data = r.json()
    logger.info(
        "[V7] entity_create OK — {} | response id={} keys={} | body_preview={}",
        _v7_http_meta_line(r),
        data.get("id") if isinstance(data, dict) else None,
        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        _v7_preview_entity_create_response(data, max_len=1800),
    )
    return data


async def _upload_pdf_to_entity_field(
    api_client: httpx.AsyncClient,
    workspace_id: str,
    agent_id: str,
    entity_id: str,
    file_slug: str,
    pdf_path: str,
) -> None:
    """Start file upload → PUT bytes to storage URL → confirm (V7 Go entity property).

    https://docs.go.v7labs.com/reference/entity-start-file-upload
    """
    prop = _normalize_v7_property_id_or_slug(file_slug)
    start_path = (
        f"/api/workspaces/{workspace_id}/projects/{agent_id}/entities/{entity_id}/"
        f"properties/{prop}/start_file_upload"
    )
    filename = os.path.basename(pdf_path)
    r = await api_client.post(start_path, json={"filename": filename})
    if r.is_error:
        _v7_log_http_error(f"start_file_upload entity={entity_id!r} file={filename!r}", r)
        detail = _v7_error_detail_from_response(r)
        raise httpx.HTTPStatusError(
            f"{r.status_code} start_file_upload: {detail}",
            request=r.request,
            response=r,
        )
    data = r.json()
    put_url = data.get("file_upload_url")
    confirm_url = data.get("confirm_upload_url")
    logger.info(
        "[V7] start_file_upload OK — {} | entity_id={} filename={!r} | "
        "put_url={} confirm_url={} | extra_keys={} | body_preview={}",
        _v7_http_meta_line(r),
        entity_id,
        filename,
        _v7_redact_presigned_url(put_url) if put_url else None,
        _v7_redact_presigned_url(confirm_url) if confirm_url else None,
        sorted(k for k in data.keys() if k not in ("file_upload_url", "confirm_upload_url")),
        _v7_json_preview({k: v for k, v in data.items() if k not in ("file_upload_url", "confirm_upload_url")}, max_len=800),
    )
    if not put_url or not confirm_url:
        raise RuntimeError(f"start_file_upload missing URLs: {data!r}"[:500])

    content = await asyncio.to_thread(lambda: open(pdf_path, "rb").read())
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=60.0)) as storage_client:
        pr = await storage_client.put(
            put_url,
            content=content,
            headers={"Content-Type": "application/pdf"},
        )
    if pr.is_error:
        _v7_log_http_error(
            f"storage PUT pdf={filename!r} bytes={len(content)}",
            pr,
        )
        raise httpx.HTTPStatusError(
            f"{pr.status_code} storage PUT for {filename!r}: {(pr.text or '')[:500]}",
            request=pr.request,
            response=pr,
        )
    logger.info(
        "[V7] storage PUT OK — {} | file={!r} bytes={} | response_text_preview={!r}",
        _v7_http_meta_line(pr),
        filename,
        len(content),
        (pr.text or "")[:400],
    )

    cr = await api_client.post(confirm_url)
    if cr.is_error:
        _v7_log_http_error(f"confirm_upload entity={entity_id!r} file={filename!r}", cr)
        detail = _v7_error_detail_from_response(cr)
        raise httpx.HTTPStatusError(
            f"{cr.status_code} confirm_upload: {detail}",
            request=cr.request,
            response=cr,
        )
    try:
        confirm_body = cr.json()
    except Exception:
        confirm_body = None
    logger.info(
        "[V7] confirm_upload OK — {} | entity_id={} | body_preview={}",
        _v7_http_meta_line(cr),
        entity_id,
        _v7_json_preview(confirm_body if confirm_body is not None else (cr.text or ""), max_len=1200),
    )


async def _get_entity(
    client: httpx.AsyncClient,
    workspace_id: str,
    agent_id: str,
    entity_id: str,
) -> dict[str, Any]:
    url = f"/api/workspaces/{workspace_id}/projects/{agent_id}/entities/{entity_id}"
    r = await client.get(url)
    if r.is_error:
        _v7_log_http_error(f"entity_get id={entity_id!r}", r)
        r.raise_for_status()
    ent = r.json()
    if os.getenv("V7_GO_DEBUG_HTTP", "").strip().lower() in ("1", "true", "yes"):
        summ = _v7_summarize_entity_for_log(ent) if isinstance(ent, dict) else {"non_dict": type(ent).__name__}
        logger.info(
            "[V7] entity_get OK — {} | {}",
            _v7_http_meta_line(r),
            _v7_json_preview(summ, max_len=2500),
        )
    return ent


def _terminal_statuses() -> frozenset:
    # Adjust if V7 adds new terminal states — STUB: confirm against your agent's field traces
    return frozenset({"complete", "error", "failed", "cancelled"})


def _row_terminal(field_obj: Any) -> bool:
    st, _val, _err = _field_blob(field_obj)
    return st in _terminal_statuses()


def _v2_row_status(
    fields: dict[str, Any],
    v2_specs: list[dict[str, str]],
) -> tuple[bool, str | None, dict[str, Any]]:
    """Evaluate Go Agent v2 tool fields for one entity.

    Returns ``(pending, error, agg)``: if ``pending``, keep polling; if ``error``, row failed;
    if neither, ``agg`` holds field_key → raw string values to JSON-encode for the extractor.
    """
    terminal = _terminal_statuses()
    row_errors: list[str] = []
    agg: dict[str, Any] = {}
    any_pending = False

    for spec in v2_specs:
        field_key = spec["field_key"]
        fo = _go_v2_resolve_field_object(fields, spec)
        if fo is None:
            ref = spec.get("property_id") or spec.get("slug")
            tried = spec.get("lookup_keys") or ([spec["slug"]] if spec.get("slug") else [])
            row_errors.append(
                f"missing property for {field_key!r} (id={ref!r}; tried keys {tried!r})"
            )
            continue
        st, val, err = _field_blob(fo)
        if st in ("error", "failed", "cancelled"):
            row_errors.append(err or f"{field_key}={st}")
            continue
        if st not in terminal:
            any_pending = True
            continue
        if st == "complete" and val:
            raw = utils.extract_from_triple_backticks(val) or val
            agg[field_key] = raw
        elif st == "complete" and not val:
            pass
        else:
            row_errors.append(err or f"{field_key}={st}")

    if any_pending:
        return True, None, {}
    if row_errors:
        return False, "; ".join(row_errors), {}
    if not agg:
        return False, "no values extracted from v2 fields", {}
    return False, None, agg


async def _build_results_from_entities(
    client: httpx.AsyncClient,
    entry: dict,
    output_slug: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Fetch latest entity JSON per row and map to extractor row indices."""
    v2_specs = entry.get("v2_output_specs")
    if v2_specs:
        return await _build_v2_results_from_entities(client, entry)

    if not output_slug:
        raise ValueError("output_field_slug is required when not using agent_template_json (Go Agent v2)")

    ws = entry["workspace_id"]
    agent = entry["agent_id"]
    entity_map: dict[str, str] = entry["entity_ids"]
    results: dict[int, dict[str, Any]] = {}

    for row_key, entity_id in entity_map.items():
        row_num = int(row_key)
        try:
            ent = await _get_entity(client, ws, agent, entity_id)
        except httpx.HTTPStatusError as e:
            results[row_num] = {"error": f"entity_get_http_{e.response.status_code}: {e!s}"}
            continue
        except Exception as e:
            results[row_num] = {"error": f"entity_get_error: {e!s}"}
            continue

        fields = ent.get("fields") or {}
        out_field = fields.get(output_slug)
        if out_field is None:
            results[row_num] = {"error": f"output field {output_slug!r} missing on entity"}
            continue

        st, val, err = _field_blob(out_field)
        if st in ("error", "failed", "cancelled"):
            results[row_num] = {"error": err or f"field status={st}"}
            continue
        if st == "complete" and val:
            raw = val
            extracted = utils.extract_from_triple_backticks(raw) or raw
            # STUB: V7 does not expose token usage on entity JSON in public OpenAPI — keep zeros.
            results[row_num] = {
                "text": extracted,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
            continue
        if _row_terminal(out_field) and not val:
            results[row_num] = {"error": err or "empty output on terminal field"}
            continue
        # Still running
        results[row_num] = {"error": "__pending__"}

    return results


async def _build_v2_results_from_entities(
    client: httpx.AsyncClient,
    entry: dict,
) -> dict[int, dict[str, Any]]:
    """Aggregate per-property tool outputs into one JSON string per row (Go Agent v2 template)."""
    ws = entry["workspace_id"]
    agent = entry["agent_id"]
    entity_map: dict[str, str] = entry["entity_ids"]
    v2_specs: list[dict[str, Any]] = entry["v2_output_specs"]
    results: dict[int, dict[str, Any]] = {}

    for row_key, entity_id in entity_map.items():
        row_num = int(row_key)
        try:
            ent = await _get_entity(client, ws, agent, entity_id)
        except httpx.HTTPStatusError as e:
            results[row_num] = {"error": f"entity_get_http_{e.response.status_code}: {e!s}"}
            continue
        except Exception as e:
            results[row_num] = {"error": f"entity_get_error: {e!s}"}
            continue

        fields = ent.get("fields") or {}
        pending, err, agg = _v2_row_status(fields, v2_specs)
        if pending:
            results[row_num] = {"error": "__pending__"}
        elif err:
            results[row_num] = {"error": err}
        else:
            results[row_num] = {
                "text": json.dumps(agg),
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Batch-shaped API (mirrors llm_doubleword names)
# ═══════════════════════════════════════════════════════════════════════════


async def submit_batch(
    client: httpx.AsyncClient,
    model_short_name: str,
    model_full_name: str,
    prompt_template: str,
    rows: list[tuple[int, str, str]],
    extra_params: dict | None = None,
    model_cfg: dict[str, Any] | None = None,
) -> str:
    """Create one V7 entity per input row; save checkpoint; return synthetic batch_id (UUID).

    model_full_name is retained for signature parity with Doubleword — V7 uses the configured agent.

    extra_params: accepted for API compatibility; logged only (STUB: map to V7 limits).

    model_cfg: if set, use this dict instead of ``V7_MODELS[model_short_name]`` (e.g. CLI override
    for ``agent_template_json``).
    """
    _ = model_full_name
    model_cfg = model_cfg if model_cfg is not None else V7_MODELS[model_short_name]
    if extra_params:
        logger.debug("[V7] extra_params ignored for V7 backend (STUB): {}", extra_params)

    ws = _resolve_workspace_id(model_cfg)
    agent = _resolve_agent_id(model_cfg)
    parent_eid = _resolve_parent_entity_id(model_cfg)
    use_pdf = bool(model_cfg.get("multimodal"))
    go_v2 = load_go_agent_v2_specs(model_cfg)

    if go_v2:
        if not use_pdf:
            raise ValueError(
                f"V7 model {model_short_name!r} uses agent_template_json (Go Agent v2); "
                "set multimodal=True — each row must supply a PDF filename (OCR text is not sent)."
            )
        if not _env_truthy("V7_GO_PROPERTY_PREFLIGHT_EACH_PDF", "0"):
            await _maybe_preflight_go_v2_properties(model_cfg)
            go_v2 = load_go_agent_v2_specs(model_cfg)
            if not go_v2:
                raise RuntimeError("Go Agent v2 template missing after property preflight")
        file_slug, file_src = _resolve_go_v2_file_field_pair(model_cfg, go_v2)
        v2_output_specs = go_v2["v2_output_specs"]
        logger.debug("[V7] Go Agent v2 file property for upload: {!r} (source={})", file_slug, file_src)
        in_slug = ""
        out_slug = None
    else:
        in_slug = _resolve_input_slug(model_cfg)
        out_slug = _resolve_output_slug(model_cfg)
        file_slug = _resolve_file_field_slug(model_cfg) if use_pdf else ""
        v2_output_specs = None

    pdf_dir = _resolve_pdf_dir() if use_pdf else ""
    if not ws or not agent:
        raise ValueError("V7_GO_WORKSPACE_ID and V7_GO_AGENT_ID (or per-model workspace_id/agent_id) must be set")

    batch_id = str(uuid.uuid4())
    sem = asyncio.Semaphore(int(os.getenv("V7_GO_CREATE_CONCURRENCY", _DEFAULT_CREATE_CONCURRENCY)))

    entity_ids: dict[str, str] = {}

    async def _create_one(row_num: int, pdf_filename: str, text_combined: str) -> None:
        nonlocal file_slug, v2_output_specs
        if go_v2:
            if _env_truthy("V7_GO_PROPERTY_PREFLIGHT_EACH_PDF", "0"):
                await _maybe_preflight_go_v2_properties(model_cfg)
                gv2 = load_go_agent_v2_specs(model_cfg)
                if gv2:
                    file_slug, _fsrc = _resolve_go_v2_file_field_pair(model_cfg, gv2)
                    v2_output_specs = gv2["v2_output_specs"]
            pdf_path = os.path.join(pdf_dir, pdf_filename)
            if not os.path.isfile(pdf_path):
                raise FileNotFoundError(
                    f"V7 PDF upload: file not found {pdf_path!r} (V7_GO_PDF_DIR={pdf_dir!r}, row {row_num})"
                )
            async with sem:
                data = await _post_entity(
                    client, ws, agent, {}, wait_for_slugs=None, parent_entity_id=parent_eid
                )
                eid = data.get("id")
                if not eid:
                    raise RuntimeError(f"V7 entity create returned no id: {repr(data)[:500]}")
                await _upload_pdf_to_entity_field(client, ws, agent, str(eid), file_slug, pdf_path)
                entity_ids[str(row_num)] = str(eid)
            return

        if use_pdf:
            body = prompt_template
            pdf_path = os.path.join(pdf_dir, pdf_filename)
            if not os.path.isfile(pdf_path):
                raise FileNotFoundError(
                    f"V7 PDF upload: file not found {pdf_path!r} (V7_GO_PDF_DIR={pdf_dir!r}, row {row_num})"
                )
        else:
            body = prompt_template + _truncate_text(text_combined, model_cfg)
            pdf_path = ""
        async with sem:
            data = await _post_entity(
                client,
                ws,
                agent,
                {in_slug: body},
                wait_for_slugs=None,
                parent_entity_id=parent_eid,
            )
            eid = data.get("id")
            if not eid:
                raise RuntimeError(f"V7 entity create returned no id: {repr(data)[:500]}")
            if use_pdf:
                await _upload_pdf_to_entity_field(client, ws, agent, str(eid), file_slug, pdf_path)
            entity_ids[str(row_num)] = str(eid)

    await asyncio.gather(*(_create_one(rn, pdf, tx) for rn, pdf, tx in rows))

    cp = load_checkpoint()
    cp_entry: dict[str, Any] = {
        "batch_id": batch_id,
        "workspace_id": ws,
        "agent_id": agent,
        "output_field_slug": out_slug,
        "input_field_slug": in_slug,
        "file_field_slug": file_slug if use_pdf else None,
        "multimodal_pdf": use_pdf,
        "parent_entity_id": parent_eid,
        "entity_ids": entity_ids,
        "row_count": len(rows),
        "submitted_at": time.time(),
    }
    if v2_output_specs is not None:
        cp_entry["v2_output_specs"] = v2_output_specs
    cp[model_short_name] = cp_entry
    save_checkpoint(cp)
    logger.info("[V7] Submitted batch {} for {} ({} entities)", batch_id, model_short_name, len(rows))
    return batch_id


async def poll_batch(client: httpx.AsyncClient, batch_id: str):
    """Poll all entities for this batch once.

    Returns (status, output_file_id, error_file_id, counts_dict) — *Doubleword-compatible tuple*.

    For V7, when status == 'completed', output_file_id is the same batch_id string; pass it to
    download_results(). error_file_id is always None (no DW-style pre-processing error file).
    """
    _model_name, entry = _checkpoint_entry_for_batch(batch_id)
    if not entry:
        logger.warning("[V7] poll_batch: no checkpoint for batch_id={!r}", batch_id)
        return "failed", None, None, {"total": 0, "completed": 0, "failed": 0, "created_at": None, "completed_at": None}

    results = await _build_results_from_entities(client, entry, entry.get("output_field_slug"))

    total = len(entry["entity_ids"])
    pending = sum(1 for v in results.values() if v.get("error") == "__pending__")
    failed = sum(1 for v in results.values() if v.get("error") and v.get("error") != "__pending__")
    resolved = total - pending  # terminal rows (success, hard error, or empty terminal)

    counts = {
        "total": total,
        "completed": resolved,
        "failed": failed,
        "created_at": entry.get("submitted_at"),
        "completed_at": time.time() if pending == 0 else None,
    }

    if pending > 0:
        logger.info(
            "[V7] poll_batch in_progress batch_id={} pending={} failed={} total={} workspace={} agent={}",
            batch_id,
            pending,
            failed,
            total,
            entry.get("workspace_id"),
            entry.get("agent_id"),
        )
        return "in_progress", None, None, counts

    # Stash for download_results — avoids duplicate GETs in the happy path
    _RESULT_CACHE[batch_id] = {k: v for k, v in results.items() if v.get("error") != "__pending__"}
    logger.info(
        "[V7] poll_batch completed batch_id={} failed={} total={} workspace={} agent={} counts={}",
        batch_id,
        failed,
        total,
        entry.get("workspace_id"),
        entry.get("agent_id"),
        counts,
    )
    return "completed", batch_id, None, counts


async def download_results(client: httpx.AsyncClient, output_file_id: str) -> dict[int, dict]:
    """Return {row_num: {text, tokens...} or {error}}.

    For V7, output_file_id is the batch_id (see poll_batch). Doubleword passes a file id instead —
    this overload is intentional and documented at the call site in extractor.py.
    """
    cached = _RESULT_CACHE.pop(output_file_id, None)
    if cached is not None:
        return cached

    _name, entry = _checkpoint_entry_for_batch(output_file_id)
    if not entry:
        return {}
    return await _build_results_from_entities(client, entry, entry.get("output_field_slug"))


async def download_error_file(client: httpx.AsyncClient, error_file_id: str) -> dict:
    """Parity stub — V7 has no separate 'error file' like OpenAI batch; always empty."""
    _ = client
    _ = error_file_id
    return {}


# ═══════════════════════════════════════════════════════════════════════════
#  Optional: synchronous single-row helper for FastAPI / tests (STUB extension point)
# ═══════════════════════════════════════════════════════════════════════════


async def extract_one_row_async(
    model_short_name: str,
    prompt_template: str,
    text_combined: str,
    pdf_basename: str | None = None,
) -> dict[str, Any]:
    """Run a single entity end-to-end with wait_for on the output field (blocking HTTP).

    If the model has multimodal True, pass pdf_basename (TSV column 1); prompt uses template only and PDF is uploaded.
    Go Agent v2 (agent_template_json): empty entity + PDF on File property, then poll until all tool fields complete.
    """
    model_cfg = V7_MODELS[model_short_name]
    client = create_client()
    try:
        ws = _resolve_workspace_id(model_cfg)
        agent = _resolve_agent_id(model_cfg)
        parent_eid = _resolve_parent_entity_id(model_cfg)
        use_pdf = bool(model_cfg.get("multimodal"))
        go_v2 = load_go_agent_v2_specs(model_cfg)

        if go_v2:
            if not pdf_basename:
                return {"error": "Go Agent v2 requires pdf_basename", "raw": {}}
            pdf_path = os.path.join(_resolve_pdf_dir(), pdf_basename)
            if not os.path.isfile(pdf_path):
                return {"error": f"PDF not found: {pdf_path}", "raw": {}}
            try:
                await _maybe_preflight_go_v2_properties(model_cfg)
            except Exception as e:
                return {"error": f"property preflight failed: {e}", "raw": {}}
            go_v2 = load_go_agent_v2_specs(model_cfg)
            if not go_v2:
                return {"error": "Go Agent v2 template missing after preflight", "raw": {}}
            data = await _post_entity(
                client, ws, agent, {}, wait_for_slugs=None, parent_entity_id=parent_eid
            )
            eid = data.get("id")
            if not eid:
                return {"error": "entity create returned no id", "raw": data}
            try:
                await _upload_pdf_to_entity_field(
                    client,
                    ws,
                    agent,
                    str(eid),
                    _resolve_go_v2_file_field_pair(model_cfg, go_v2)[0],
                    pdf_path,
                )
            except httpx.HTTPStatusError as e:
                return {"error": _v7_error_detail_from_response(e.response), "raw": data}
            deadline = time.time() + float(os.getenv("V7_GO_WAIT_FOR_OUTPUT_SECS", "600"))
            specs = go_v2["v2_output_specs"]
            while time.time() < deadline:
                data = await _get_entity(client, ws, agent, str(eid))
                fields = data.get("fields") or {}
                pending, err, agg = _v2_row_status(fields, specs)
                if pending:
                    await asyncio.sleep(2.0)
                    continue
                if err:
                    return {"error": err, "raw": data}
                return {"text": json.dumps(agg), "prompt_tokens": 0, "completion_tokens": 0}
            return {"error": "timeout waiting for Go Agent v2 fields after PDF upload", "raw": data}

        in_slug = _resolve_input_slug(model_cfg)
        out_slug = _resolve_output_slug(model_cfg)
        if use_pdf:
            if not pdf_basename:
                return {"error": "multimodal model requires pdf_basename", "raw": {}}
            body = prompt_template
            pdf_path = os.path.join(_resolve_pdf_dir(), pdf_basename)
            if not os.path.isfile(pdf_path):
                return {"error": f"PDF not found: {pdf_path}", "raw": {}}
        else:
            body = prompt_template + _truncate_text(text_combined, model_cfg)
            pdf_path = ""
        wait_for = None if use_pdf else [out_slug]
        data = await _post_entity(
            client,
            ws,
            agent,
            {in_slug: body},
            wait_for_slugs=wait_for,
            parent_entity_id=parent_eid,
        )
        eid = data.get("id")
        if use_pdf and eid:
            try:
                await _upload_pdf_to_entity_field(
                    client, ws, agent, str(eid), _resolve_file_field_slug(model_cfg), pdf_path
                )
            except httpx.HTTPStatusError as e:
                return {"error": _v7_error_detail_from_response(e.response), "raw": data}
            deadline = time.time() + float(os.getenv("V7_GO_WAIT_FOR_OUTPUT_SECS", "600"))
            while time.time() < deadline:
                data = await _get_entity(client, ws, agent, str(eid))
                fields = data.get("fields") or {}
                out_field = fields.get(out_slug)
                if out_field is None:
                    await asyncio.sleep(2.0)
                    continue
                st, val, err = _field_blob(out_field)
                if st in ("error", "failed", "cancelled"):
                    return {"error": err or f"status={st}", "raw": data}
                if st == "complete" and val:
                    extracted = utils.extract_from_triple_backticks(val) or val
                    return {"text": extracted, "prompt_tokens": 0, "completion_tokens": 0}
                await asyncio.sleep(2.0)
            return {"error": "timeout waiting for output after PDF upload", "raw": data}

        fields = data.get("fields") or {}
        out_field = fields.get(out_slug)
        if not out_field:
            return {"error": "missing output field", "raw": data}
        st, val, err = _field_blob(out_field)
        if st != "complete" or not val:
            return {"error": err or f"status={st}", "raw": data}
        extracted = utils.extract_from_triple_backticks(val) or val
        return {"text": extracted, "prompt_tokens": 0, "completion_tokens": 0}
    finally:
        await client.aclose()
