#!/usr/bin/env python3
"""Check or create V7 Go **project properties** and **entities** against a template or id list.

V7 does not let clients choose property or entity UUIDs at creation time. This module therefore:

- **Properties**: Matches template rows to the live project by ``(name, type, tool)`` as well as by id
  (when ids match). Missing properties are created via
  ``POST /api/workspaces/{workspace_id}/projects/{project_id}/properties``
  (`project-add-property <https://docs.go.v7labs.com/reference/project-add-property>`_).
  Tool-field inputs that pointed at the template file property id are rewired to the **live** file
  property UUID before POST.

- **Entities**: ``GET .../entities/{id}`` to test existence; for each id that returns 404, creates a
  new empty entity via
  ``POST .../entities``
  (`create entities <https://docs.go.v7labs.com/reference/create-entities-programmatically>`_).
  New ids are printed (you cannot force a specific entity id).

Environment: same as ``llm_v7`` / ``sync_v7_go_agent_template`` — ``V7_GO_API_KEY`` or ``V7_API_KEY``,
``V7_GO_WORKSPACE_ID``, ``V7_GO_AGENT_ID``, optional ``V7_GO_BASE_URL``, ``V7_GO_PARENT_ENTITY_ID``
(for collection agents when creating entities).

**Iterative PDF runs:** each scanned PDF is one V7 **entity** (empty create + file upload + poll). That
happens inside ``llm_v7`` per row. **Project properties** are shared by all entities; use
``preflight_template_against_remote`` (or ``V7_GO_PROPERTY_PREFLIGHT`` in ``llm_v7``) so the agent still
matches ``agent_template_json`` before each batch or — optionally — before every PDF.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

# Import after load_dotenv; avoid pulling llm_v7 during normalization in isolation tests
def _normalize_property_id(s: str) -> str:
    from llm_v7 import _normalize_v7_property_id_or_slug

    return _normalize_v7_property_id_or_slug(s)


def _unwrap(obj: Any) -> Any:
    if isinstance(obj, dict) and "data" in obj:
        return obj["data"]
    return obj


def _env_api_key() -> str:
    return (os.getenv("V7_GO_API_KEY") or os.getenv("V7_API_KEY") or "").strip()


def fetch_project_and_properties(
    client: httpx.Client, workspace_id: str, project_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Shared with ``sync_v7_go_agent_template`` — GET project (best-effort) + list properties."""
    proj_body: dict[str, Any] = {}
    try:
        pr = client.get(f"/api/workspaces/{workspace_id}/projects/{project_id}")
        pr.raise_for_status()
        raw = pr.json()
        unwrapped = _unwrap(raw)
        if isinstance(unwrapped, dict):
            proj_body = unwrapped
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
    pl = client.get(f"/api/workspaces/{workspace_id}/projects/{project_id}/properties")
    pl.raise_for_status()
    props_raw = _unwrap(pl.json())
    if not isinstance(props_raw, list):
        raise ValueError(f"Unexpected properties payload: {type(props_raw).__name__}")
    return proj_body, props_raw


def _norm_id(s: Any) -> str:
    return str(s).strip() if s is not None else ""


def _property_key(name: str, ptype: Any, tool: Any) -> tuple[str, str, str]:
    return (name.strip().lower(), str(ptype or ""), str(tool or ""))


@dataclass
class RemotePropertyIndex:
    """``by_id`` keys are lowercased so template ``property_*`` and UUID ids match API ids."""

    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_ntt: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def build(cls, props: list[dict[str, Any]]) -> RemotePropertyIndex:
        idx = cls()
        for p in props:
            if not isinstance(p, dict):
                continue
            pid = _norm_id(p.get("id"))
            if not pid:
                continue
            idx.by_id[pid.lower()] = p
            name = str(p.get("name") or "")
            key = _property_key(name, p.get("type"), p.get("tool"))
            idx.by_ntt[key] = p
        return idx


def _load_template(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        raise ValueError("template root must be a JSON object")
    projects = doc.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("template: missing projects[]")
    return doc


def _template_properties(doc: dict[str, Any]) -> list[dict[str, Any]]:
    props = (doc.get("projects") or [{}])[0].get("properties")
    if not isinstance(props, list):
        return []
    return [p for p in props if isinstance(p, dict) and p.get("id")]


def _first_template_file_property_id(rows: list[dict[str, Any]]) -> str | None:
    for r in rows:
        if r.get("type") == "file":
            return _norm_id(r.get("id"))
    return None


def _export_row_to_add_property_body(
    row: dict[str, Any],
    *,
    template_file_property_id: str | None,
    resolved_file_uuid: str,
) -> dict[str, Any]:
    """Map a template ``properties[]`` row to ``Projects.AddPropertyRequest`` (basic / file)."""
    name = str(row.get("name") or "").strip()
    ptype = row.get("type")
    tool = row.get("tool")
    desc = row.get("description")
    if desc is None:
        desc = ""

    body: dict[str, Any] = {
        "name": name,
        "type": ptype,
        "tool": tool,
        "description": desc,
        "is_grounded": bool(row.get("is_grounded", False)),
        "skip_behaviour": row.get("skip_behaviour") or "never",
        "incomplete_collection_input_rows_behaviour": row.get(
            "incomplete_collection_input_rows_behaviour"
        )
        or "never",
        "visible_in_entity_sidebar": bool(row.get("visible_in_entity_sidebar", True)),
    }
    grp = row.get("group")
    if grp is not None:
        body["group"] = grp
    tc = row.get("tool_config")
    if isinstance(tc, dict) and tc:
        body["tool_config"] = tc
    skills = row.get("enabled_skills")
    if isinstance(skills, list) and skills:
        body["enabled_skills"] = skills

    inputs_out: list[dict[str, Any]] = []
    for inp in row.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        pid = inp.get("property_id")
        if (
            template_file_property_id
            and pid is not None
            and _norm_id(pid) == _norm_id(template_file_property_id)
        ):
            pid = resolved_file_uuid
        if pid is None:
            continue
        # Add API expects UUID for property inputs; skip invalid until file is resolved
        try:
            pid_norm = _normalize_property_id(str(pid))
        except ValueError:
            continue
        gi: dict[str, Any] = {"property_id": pid_norm, "target": inp.get("target") or "value"}
        if inp.get("entity_id") is not None:
            gi["entity_id"] = inp["entity_id"]
        if inp.get("via_property_id") is not None:
            gi["via_property_id"] = inp["via_property_id"]
        if inp.get("entities_filter") is not None:
            gi["entities_filter"] = inp["entities_filter"]
        if inp.get("hub_filters") is not None:
            gi["hub_filters"] = inp["hub_filters"]
        tf = inp.get("target_filter")
        gi["target_filter"] = tf if isinstance(tf, dict) else {}
        inputs_out.append(gi)

    if inputs_out:
        body["inputs"] = inputs_out
    return body


def _resolve_remote_row(
    idx: RemotePropertyIndex, row: dict[str, Any]
) -> dict[str, Any] | None:
    tid = _norm_id(row.get("id"))
    if tid:
        hit = idx.by_id.get(tid.lower())
        if hit:
            return hit
    name = str(row.get("name") or "")
    typ = row.get("type")
    tool = row.get("tool")
    key = _property_key(name, typ, tool)
    hit = idx.by_ntt.get(key)
    if hit:
        return hit
    # Template may use literal "<model id>" while the server stores v7_property_model (e.g. claude_4_6_opus).
    if str(tool or "").strip() == "<model id>":
        n_low = name.strip().lower()
        t_str = str(typ or "")
        for (nn, tt, _ttool), prop in idx.by_ntt.items():
            if nn == n_low and tt == t_str:
                return prop
    return None


def _load_template_resolved(template_path: str, tool_model_id: str | None) -> dict[str, Any]:
    doc = _load_template(template_path)
    mid = str(tool_model_id or "").strip()
    if not mid:
        return doc
    from llm_v7 import apply_v7_template_tool_model_id

    return apply_v7_template_tool_model_id(doc, mid)


def check_properties(
    template_path: str,
    remote: list[dict[str, Any]],
    *,
    tool_model_id: str | None = None,
) -> int:
    """Print status per template property. Returns 0 if every row exists on the server (by id or NTT)."""
    doc = _load_template_resolved(template_path, tool_model_id)
    rows = _template_properties(doc)
    idx = RemotePropertyIndex.build(remote)
    missing = 0
    drift = 0
    for row in rows:
        name = row.get("name")
        remote_row = _resolve_remote_row(idx, row)
        tid = _norm_id(row.get("id"))
        if not remote_row:
            print(f"missing\tname={name!r}\ttemplate_id={tid!r}")
            missing += 1
            continue
        rid = _norm_id(remote_row.get("id"))
        if tid and rid and tid.lower() != rid.lower():
            print(f"id_drift\tname={name!r}\ttemplate_id={tid!r}\tserver_id={rid!r}")
            drift += 1
        else:
            print(f"ok\tname={name!r}\tid={rid or tid!r}")
    if missing:
        print(f"\n{missing} missing (use: python v7_go_ensure.py properties ensure --template ...)", file=sys.stderr)
        return 1
    if drift:
        print(f"\n{drift} id drift — re-run sync_v7_go_agent_template.py to refresh JSON", file=sys.stderr)
    return 0


class V7GoPreflightError(RuntimeError):
    """Raised when ``agent_template_json`` fields are not all present on the live agent."""


def preflight_template_against_remote(
    template_path: str,
    client: httpx.Client,
    workspace_id: str,
    project_id: str,
    *,
    tool_model_id: str | None = None,
) -> None:
    """Raise ``V7GoPreflightError`` if any template property row is missing on the server (by id or NTT).

    Used by ``llm_v7`` before each PDF batch / optional per-PDF iteration. Id drift (same name, new uuid)
    does not fail — only **missing** properties fail.
    """
    _, remote = fetch_project_and_properties(client, workspace_id, project_id)
    doc = _load_template_resolved(template_path, tool_model_id)
    rows = _template_properties(doc)
    idx = RemotePropertyIndex.build(remote)
    missing: list[str] = []
    for row in rows:
        if not _resolve_remote_row(idx, row):
            label = str(row.get("name") or row.get("id") or "?")
            missing.append(label)
    if missing:
        raise V7GoPreflightError(
            f"Agent {project_id!r} is missing template properties {missing!r} "
            f"(template {template_path!r}). Fix the agent in V7 or run:\n"
            f"  python v7_go_ensure.py properties ensure -t {template_path}"
        )


def ensure_properties(
    client: httpx.Client,
    workspace_id: str,
    project_id: str,
    template_path: str,
    *,
    dry_run: bool,
    tool_model_id: str | None = None,
) -> int:
    """Create template properties that are absent on the server (matched by id then NTT)."""
    doc = _load_template_resolved(template_path, tool_model_id)
    rows = _template_properties(doc)
    # File property must be created first so tool inputs can reference its UUID.
    files = [r for r in rows if r.get("type") == "file"]
    rest = [r for r in rows if r.get("type") != "file"]
    ordered = files + rest

    _, remote = fetch_project_and_properties(client, workspace_id, project_id)
    idx = RemotePropertyIndex.build(remote)
    template_file_id = _first_template_file_property_id(rows)

    file_remote = _resolve_remote_row(idx, files[0]) if files else None
    resolved_file_uuid = _norm_id(file_remote.get("id")) if file_remote else ""

    created = 0
    for row in ordered:
        remote_hit = _resolve_remote_row(idx, row)
        if remote_hit:
            continue
        if row.get("type") != "file" and not resolved_file_uuid:
            print(
                f"skip\tcannot create {row.get('name')!r} — file property must exist first on the server",
                file=sys.stderr,
            )
            return 2

        body = _export_row_to_add_property_body(
            row,
            template_file_property_id=template_file_id,
            resolved_file_uuid=resolved_file_uuid,
        )
        pname = row.get("name")
        if dry_run:
            preview = json.dumps(body, sort_keys=True)
            print(f"dry_run\twould POST property\t{pname!r}\t{preview[:800]}{'...' if len(preview) > 800 else ''}")
            if row.get("type") == "file":
                resolved_file_uuid = "00000000-0000-4000-8000-000000000000"
            created += 1
            continue
        url = f"/api/workspaces/{workspace_id}/projects/{project_id}/properties"
        r = client.post(url, json=body)
        if r.is_error:
            print(f"error\t{pname!r}\t{r.status_code}\t{(r.text or '')[:800]}", file=sys.stderr)
            return 3
        new_prop = r.json()
        if isinstance(new_prop, dict) and "data" in new_prop:
            new_prop = new_prop["data"]
        if not isinstance(new_prop, dict):
            print(f"error\tunexpected response for {pname!r}", file=sys.stderr)
            return 3
        new_id = _norm_id(new_prop.get("id"))
        print(f"created\tname={pname!r}\tid={new_id!r}")
        if row.get("type") == "file":
            resolved_file_uuid = new_id
        _, remote = fetch_project_and_properties(client, workspace_id, project_id)
        idx = RemotePropertyIndex.build(remote)
        created += 1

    if dry_run:
        print("dry_run: no POST performed")
    elif created == 0:
        print("all template properties already present (by id or name/type/tool)")
    return 0


def _get_entity(
    client: httpx.Client, workspace_id: str, project_id: str, entity_id: str
) -> tuple[bool, dict[str, Any] | None]:
    url = f"/api/workspaces/{workspace_id}/projects/{project_id}/entities/{entity_id.strip()}"
    r = client.get(url)
    if r.status_code == 404:
        return False, None
    if r.is_error:
        r.raise_for_status()
    return True, r.json() if isinstance(r.json(), dict) else None


def _post_empty_entity(
    client: httpx.Client,
    workspace_id: str,
    project_id: str,
    parent_entity_id: str | None,
) -> dict[str, Any]:
    url = f"/api/workspaces/{workspace_id}/projects/{project_id}/entities"
    payload: dict[str, Any] = {}
    if parent_entity_id:
        payload["parent_entity_id"] = parent_entity_id.strip()
    r = client.post(url, json=payload)
    if r.is_error:
        print(f"entity_create failed: {r.status_code} {(r.text or '')[:600]}", file=sys.stderr)
        r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected entity create response: {type(data).__name__}")
    return data


def check_entities(
    client: httpx.Client,
    workspace_id: str,
    project_id: str,
    entity_ids: list[str],
) -> int:
    missing = 0
    for eid in entity_ids:
        eid = eid.strip()
        if not eid:
            continue
        ok, _ = _get_entity(client, workspace_id, project_id, eid)
        if ok:
            print(f"ok\t{eid}")
        else:
            print(f"missing\t{eid}")
            missing += 1
    return 1 if missing else 0


def ensure_entities(
    client: httpx.Client,
    workspace_id: str,
    project_id: str,
    entity_ids: list[str],
    *,
    parent_entity_id: str | None,
    dry_run: bool,
) -> int:
    for eid in entity_ids:
        eid = eid.strip()
        if not eid:
            continue
        ok, _ = _get_entity(client, workspace_id, project_id, eid)
        if ok:
            print(f"ok\t{eid}")
            continue
        if dry_run:
            print(f"dry_run\twould create entity (replacement for missing {eid!r})")
            continue
        new_ent = _post_empty_entity(client, workspace_id, project_id, parent_entity_id)
        new_id = new_ent.get("id")
        print(f"created\trequested={eid!r}\tnew_id={new_id!r}")
    return 0


def _parse_ids(s: str) -> list[str]:
    return [x.strip() for x in s.replace(",", " ").split() if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description="V7 Go — check/ensure properties (from template) and entities (by id).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("properties", help="Template property check / create on current agent")
    pc_sub = pc.add_subparsers(dest="p_cmd", required=True)
    p_check = pc_sub.add_parser("check", help="Report ok / id_drift / missing")
    p_check.add_argument("--template", "-t", required=True, help="Path to v7_go_agent_v2_template.json")
    p_check.add_argument(
        "--tool-model-id",
        default="",
        help="Replace template tool placeholder <model id> (same as v7_property_model in config_models_v7.py)",
    )
    p_ensure = pc_sub.add_parser("ensure", help="POST missing properties from template")
    p_ensure.add_argument("--template", "-t", required=True)
    p_ensure.add_argument("--dry-run", action="store_true")
    p_ensure.add_argument(
        "--tool-model-id",
        default="",
        help="Replace template tool placeholder <model id> before POST (required if template uses placeholder)",
    )

    ec = sub.add_parser("entities", help="Entity existence check / create replacements for missing ids")
    ec_sub = ec.add_subparsers(dest="e_cmd", required=True)
    e_check = ec_sub.add_parser("check", help="GET each entity id")
    e_check.add_argument("--ids", required=True, help="Comma-separated entity UUIDs")
    e_ensure = ec_sub.add_parser("ensure", help="GET each id; POST empty entity when 404")
    e_ensure.add_argument("--ids", required=True)
    e_ensure.add_argument("--dry-run", action="store_true")

    args = p.parse_args()

    key = _env_api_key()
    workspace_id = (os.getenv("V7_GO_WORKSPACE_ID") or "").strip()
    project_id = (os.getenv("V7_GO_AGENT_ID") or "").strip()
    base = os.getenv("V7_GO_BASE_URL", "https://go.v7labs.com").rstrip("/")
    parent_entity_id = (os.getenv("V7_GO_PARENT_ENTITY_ID") or "").strip() or None

    if not key:
        print("error: set V7_GO_API_KEY or V7_API_KEY", file=sys.stderr)
        return 2
    if not workspace_id or not project_id:
        print("error: set V7_GO_WORKSPACE_ID and V7_GO_AGENT_ID", file=sys.stderr)
        return 2

    with httpx.Client(
        base_url=base,
        headers={"X-API-KEY": key, "Accept": "application/json"},
        timeout=httpx.Timeout(120.0, connect=30.0),
    ) as client:
        if args.cmd == "properties":
            _, remote = fetch_project_and_properties(client, workspace_id, project_id)
            tm = (args.tool_model_id or "").strip() or None
            if args.p_cmd == "check":
                return check_properties(args.template, remote, tool_model_id=tm)
            return ensure_properties(
                client,
                workspace_id,
                project_id,
                args.template,
                dry_run=args.dry_run,
                tool_model_id=tm,
            )
        if args.cmd == "entities":
            ids = _parse_ids(args.ids)
            if args.e_cmd == "check":
                return check_entities(client, workspace_id, project_id, ids)
            return ensure_entities(
                client,
                workspace_id,
                project_id,
                ids,
                parent_entity_id=parent_entity_id,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
