#!/usr/bin/env python3
"""Build or refresh ``v7_go_agent_v2_template.json`` from the live V7 Go project (idempotent).

The bundled template is a **project export** shape consumed by ``llm_v7.parse_go_agent_export_for_v2``
(property ids, names, types, tools). Runtime **entity** creation (empty entity + PDF upload + poll) is
handled elsewhere via:

  https://docs.go.v7labs.com/reference/create-entities-programmatically

This script pulls **project metadata** from the API (shared helper in ``v7_go_ensure``):

  GET /api/workspaces/{workspace_id}/projects/{project_id}
  GET /api/workspaces/{workspace_id}/projects/{project_id}/properties

  https://docs.go.v7labs.com/reference/project-list-properties

To verify or create properties / entities against a template or id list, use ``v7_go_ensure.py``.

Idempotency: after building the document, the file is only written when the normalized JSON text
differs from the existing file (stable key order, sorted properties, volatile API fields stripped).

Non-``file`` properties whose API ``tool`` is not ``manual`` are written as
``\"tool\": \"<model id>\"`` so one template works with every ``v7_property_model`` in
``config_models_v7.py`` (see ``llm_v7.apply_v7_template_tool_model_id``). ``file`` rows keep the API tool
(e.g. ``manual``).

Environment (same as ``llm_v7``): ``V7_GO_API_KEY`` or ``V7_API_KEY``, ``V7_GO_WORKSPACE_ID``,
``V7_GO_AGENT_ID`` (project id), optional ``V7_GO_BASE_URL``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

from llm_v7 import V7_GO_AGENT_TEMPLATE_MODEL_TOOL_PLACEHOLDER
from v7_go_ensure import fetch_project_and_properties

load_dotenv()

_INPUT_KEYS = (
    "target",
    "entity_id",
    "property_id",
    "via_property_id",
    "entities_filter",
    "hub_filters",
    "target_filter",
)


def _env_api_key() -> str:
    return (os.getenv("V7_GO_API_KEY") or os.getenv("V7_API_KEY") or "").strip()


def _normalize_input_row(inp: Any) -> dict[str, Any]:
    if not isinstance(inp, dict):
        return {
            "target": "value",
            "entity_id": None,
            "property_id": None,
            "via_property_id": None,
            "entities_filter": None,
            "hub_filters": None,
            "target_filter": {},
        }
    out: dict[str, Any] = {}
    for k in _INPUT_KEYS:
        v = inp.get(k)
        if k == "target_filter" and v is None:
            v = {}
        out[k] = v
    return out


def _api_property_to_export_row(prop: dict[str, Any]) -> dict[str, Any]:
    """Map ``Projects.PropertyResponse``-shaped JSON to the subset used in UI export templates."""
    inputs_raw = prop.get("inputs")
    inputs: list[dict[str, Any]] = []
    if isinstance(inputs_raw, list):
        inputs = [_normalize_input_row(x) for x in inputs_raw]

    tool_cfg = prop.get("tool_config")
    if tool_cfg is None or not isinstance(tool_cfg, dict):
        tool_cfg = {}

    skills = prop.get("enabled_skills")
    if not isinstance(skills, list):
        skills = []

    ptype = prop.get("type")
    api_tool = prop.get("tool")
    if ptype == "file":
        export_tool = api_tool
    else:
        t = str(api_tool or "").strip()
        export_tool = (
            V7_GO_AGENT_TEMPLATE_MODEL_TOOL_PLACEHOLDER
            if t and t != "manual"
            else api_tool
        )

    row: dict[str, Any] = {
        "id": prop.get("id"),
        "name": prop.get("name"),
        "type": ptype,
        "description": prop.get("description"),
        "group": prop.get("group"),
        "tool": export_tool,
        "inputs": inputs,
        "is_grounded": bool(prop.get("is_grounded", False)),
        "tool_config": tool_cfg,
        "enabled_skills": skills,
        "skip_behaviour": prop.get("skip_behaviour") or "never",
        "incomplete_collection_input_rows_behaviour": prop.get(
            "incomplete_collection_input_rows_behaviour"
        )
        or "never",
        "visible_in_entity_sidebar": bool(prop.get("visible_in_entity_sidebar", True)),
    }
    return row


def _sort_properties_export_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """File field first (matches typical export), then other properties by id."""
    files = [r for r in rows if r.get("type") == "file"]
    rest = sorted(
        [r for r in rows if r.get("type") != "file"],
        key=lambda r: str(r.get("id") or ""),
    )
    return files + rest


def _default_main_view(property_ids: list[str]) -> dict[str, Any]:
    return {
        "id": "view_synced_from_api",
        "filters": [],
        "property_ids": list(property_ids),
        "property_layouts": [],
        "num_pinned_properties": 0,
        "property_options": [{"property_id": pid, "block_workers_edits": False} for pid in property_ids],
    }


def _maybe_preserve_main_view(
    old_doc: dict[str, Any],
    new_property_ids: set[str],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    projects = old_doc.get("projects")
    if not isinstance(projects, list) or not projects:
        return fallback
    mv = projects[0].get("main_view")
    if not isinstance(mv, dict):
        return fallback
    pids = mv.get("property_ids")
    if not isinstance(pids, list):
        return fallback
    old_ids = {str(x) for x in pids if x is not None}
    if not old_ids <= new_property_ids:
        return fallback
    if old_ids != new_property_ids:
        # Properties were added/removed — layout refs may be stale.
        return fallback
    return mv


def build_template_document(
    workspace_id: str,
    project_id: str,
    proj_meta: dict[str, Any],
    props_api: list[dict[str, Any]],
    *,
    preserve_main_view: bool,
    previous_file: str | None,
) -> dict[str, Any]:
    rows = [_api_property_to_export_row(p) for p in props_api if isinstance(p, dict)]
    rows = [r for r in rows if r.get("id")]
    rows = _sort_properties_export_order(rows)
    property_ids = [str(r["id"]) for r in rows]

    fallback_mv = _default_main_view(property_ids)
    main_view = fallback_mv
    if preserve_main_view and previous_file and os.path.isfile(previous_file):
        try:
            with open(previous_file, encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, dict):
                main_view = _maybe_preserve_main_view(old, set(property_ids), fallback_mv)
        except (OSError, json.JSONDecodeError):
            pass

    name = str(proj_meta.get("name") or "").strip() or "v7_go_agent_v2"
    desc = proj_meta.get("description")
    ptype = proj_meta.get("type") or "regular"

    project = {
        "id": str(proj_meta.get("id") or project_id),
        "name": name,
        "type": ptype,
        "description": desc,
        "properties": rows,
        "views": [],
        "triggers": [],
        "main_view": main_view,
    }
    return {"projects": [project], "external_objects": {}}


def _canonical_file_text(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_idempotent(path: str, doc: dict[str, Any], *, force: bool) -> bool:
    text = _canonical_file_text(doc)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                old_doc = json.load(f)
            if isinstance(old_doc, dict) and _canonical_file_text(old_doc) == text:
                return False
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def sync_v7_go_agent_template_to_path(
    output_path: str,
    *,
    force: bool = False,
    preserve_main_view: bool = True,
    validate_parse: bool = False,
) -> bool:
    """Fetch live project properties and write export-shaped JSON to ``output_path`` (idempotent).

    Used by ``extractor.py --all-v7`` and by ``llm_v7`` after auto-ensuring missing properties.

    Returns True if the file was written or replaced, False if content was already up to date.

    Raises:
        ValueError: missing API credentials or workspace / agent env.
        httpx.HTTPError: API failure.
    """
    key = _env_api_key()
    workspace_id = (os.getenv("V7_GO_WORKSPACE_ID") or "").strip()
    project_id = (os.getenv("V7_GO_AGENT_ID") or "").strip()
    base = os.getenv("V7_GO_BASE_URL", "https://go.v7labs.com").rstrip("/")
    if not key:
        raise ValueError("V7_GO_API_KEY or V7_API_KEY must be set to sync the agent template")
    if not workspace_id or not project_id:
        raise ValueError("V7_GO_WORKSPACE_ID and V7_GO_AGENT_ID must be set to sync the agent template")

    out_path = os.path.abspath(output_path)
    with httpx.Client(
        base_url=base,
        headers={"X-API-KEY": key, "Accept": "application/json"},
        timeout=httpx.Timeout(120.0, connect=30.0),
    ) as client:
        proj_meta, props_api = fetch_project_and_properties(client, workspace_id, project_id)
    if not proj_meta.get("id"):
        proj_meta = {**proj_meta, "id": project_id}

    doc = build_template_document(
        workspace_id,
        project_id,
        proj_meta,
        props_api,
        preserve_main_view=preserve_main_view,
        previous_file=out_path,
    )
    if validate_parse:
        from llm_v7 import parse_go_agent_export_for_v2

        parse_go_agent_export_for_v2(doc)
    return write_idempotent(out_path, doc, force=force)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync V7 Go agent project export JSON from the live API (idempotent write)."
    )
    parser.add_argument(
        "-o",
        "--output",
        default="v7_go_agent_v2_template.json",
        help="Output path (default: ./v7_go_agent_v2_template.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even when content is unchanged (still uses canonical formatting).",
    )
    parser.add_argument(
        "--no-preserve-main-view",
        action="store_true",
        help="Do not reuse main_view from an existing output file when property ids match.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="After building, run llm_v7.parse_go_agent_export_for_v2 and fail on error.",
    )
    args = parser.parse_args()

    out_path = os.path.abspath(args.output)
    try:
        changed = sync_v7_go_agent_template_to_path(
            out_path,
            force=args.force,
            preserve_main_view=not args.no_preserve_main_view,
            validate_parse=args.validate,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except httpx.HTTPError as e:
        print(f"error: HTTP {e}", file=sys.stderr)
        return 3
    if changed:
        print(f"wrote {out_path}")
    else:
        print(f"unchanged {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
