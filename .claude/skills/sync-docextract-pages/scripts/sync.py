from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_SUFFIX = "-which-models-extracted-playground.html"
REDIRECT_MARKERS = ('http-equiv="refresh"', "http-equiv='refresh'")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def committed_snapshot(root: Path, source: Path) -> tuple[str, str, str, str]:
    relative = source.relative_to(root)
    commit = git_output(root, "log", "-1", "--format=%H", "--", str(relative))
    if not commit:
        fail(f"no commit owns {relative}")
    changed = git_output(root, "status", "--short", "--", str(relative))
    if changed:
        fail(f"source playground has uncommitted changes: {changed}")
    iso = git_output(root, "show", "-s", "--format=%cI", commit)
    subject = git_output(root, "show", "-s", "--format=%s", commit)
    stamp = datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    return stamp, commit, iso, subject


def extract_raw(html: str) -> dict[str, object]:
    marker = html.find("const RAW = ")
    if marker < 0:
        fail("source playground has no RAW payload")
    start = html.find("{", marker)
    depth = 0
    for index, char in enumerate(html[start:], start=start):
        depth += char == "{"
        depth -= char == "}"
        if depth == 0:
            return json.loads(html[start : index + 1])
    fail("source playground RAW payload is unbalanced")


def snapshot_metadata(
    source: Path, filename: str, stamp: str, commit: str, iso: str, subject: str
) -> dict[str, object]:
    html = source.read_text()
    raw = extract_raw(html)
    models = raw.get("models", {})
    f1_scores = raw.get("f1_scores", {})
    providers: dict[str, int] = {}
    active_scores: dict[str, list[float]] = {}
    model_providers = raw.get("model_providers", {})
    for model in models:
        provider = str(model_providers.get(model, "?"))
        providers[provider] = providers.get(provider, 0) + 1
        score = float(f1_scores.get(model, {}).get("f1", 0))
        if score > 0:
            active_scores.setdefault(provider, []).append(score)
    tabs = re.findall(r'class="tab-btn[^"\n]*"[^>]*>([^<]+)</button>', html)
    metadata: dict[str, object] = {
        "stamp": stamp,
        "commit": commit[:8],
        "iso": iso,
        "subject": subject,
        "file": filename,
        "size_kb": round(source.stat().st_size / 1024),
        "models": len(models),
        "f1": len(f1_scores),
        "tabs": tabs,
        "docs": len(raw.get("doc_names", [])),
        "providers": providers,
        "tab_count": len(tabs),
    }
    if active_scores:
        metadata["avg_f1"] = {
            provider: round(sum(scores) / len(scores), 3)
            for provider, scores in active_scores.items()
        }
    return metadata


def verify_integrity(root: Path, source: Path) -> None:
    generator = (root / "playground.py").read_text()
    required = (
        "sizeCategoryChartWrap",
        "renderRankingsViews()",
        "renderErrorBreakdownViews()",
        "renderFieldTabViews()",
        "renderDocTabViews()",
        "providerAggRows()",
        "fieldDifficultyRows()",
        "docDifficultyRows()",
    )
    missing = [name for name in required if name not in generator]
    if missing:
        fail(f"playground integrity guards missing: {missing}")
    if any(pattern in generator for pattern in (
        'onchange="renderRankTable()"',
        'onchange="renderFieldHeatmap()"',
        'onchange="renderDocHeatmap()"',
    )):
        fail("one-sided playground renderer found")
    inputs = [root / "data/extraction_stats.csv", *root.glob("data/playgroup_dev_extracted__*.tsv")]
    if inputs and source.stat().st_mtime < max(path.stat().st_mtime for path in inputs):
        fail("source playground is older than extraction inputs")
    raw = extract_raw(source.read_text())
    if not raw.get("models") or not raw.get("f1_scores"):
        fail("source playground has empty model or F1 data")


def is_redirect(path: Path) -> bool:
    head = path.read_text(errors="ignore")[:2048].lower()
    return any(marker in head for marker in REDIRECT_MARKERS)


def hosted_snapshot(source: Path) -> bytes:
    html = source.read_text()
    script = '<script src="snapshot-chrome.js"></script>\n'
    if script not in html:
        html = html.replace("</head>", f"{script}</head>", 1)
    return html.encode()


def sync_snapshot(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.write_bytes(hosted_snapshot(source))


def write_latest(latest_dir: Path, filename: str) -> None:
    latest_dir.mkdir(parents=True, exist_ok=True)
    target = f"../{filename}"
    content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={target}">
  <link rel="canonical" href="{target}">
  <title>Latest DocExtract playground</title>
</head>
<body>
  <p>Opening the <a href="{target}">latest DocExtract playground</a>.</p>
</body>
</html>
'''
    (latest_dir / "index.html").write_text(content)


def validate_archive(destination: Path, versions: list[dict[str, object]]) -> None:
    listed = {str(version["file"]) for version in versions}
    canonical = {
        path.name
        for path in destination.glob(f"*{SNAPSHOT_SUFFIX}")
        if not is_redirect(path)
    }
    if listed != canonical:
        fail(f"versions.json mismatch: missing={canonical - listed}, stale={listed - canonical}")
    for filename in listed:
        if not (destination / filename).is_file():
            fail(f"manifest snapshot missing: {filename}")


def main() -> None:
    source_root = Path(os.environ["DOCEXTRACT_ROOT"]).resolve()
    pages_root = Path(os.environ["PAGES_ROOT"]).resolve()
    source = source_root / "which-models-extracted-playground.html"
    destination = pages_root / "demos/playgroup-202602-docextract"
    versions_path = destination / "versions.json"
    for required in (source, destination / "index.html", versions_path):
        if not required.exists():
            fail(f"required path missing: {required}")
    verify_integrity(source_root, source)
    stamp, commit, iso, subject = committed_snapshot(source_root, source)
    filename = f"{stamp}{SNAPSHOT_SUFFIX}"
    sync_snapshot(source, destination / filename)
    versions = json.loads(versions_path.read_text())
    metadata = snapshot_metadata(source, filename, stamp, commit, iso, subject)
    versions = [version for version in versions if version["file"] != filename]
    versions.append(metadata)
    versions.sort(key=lambda version: str(version["iso"]))
    versions_path.write_text(json.dumps(versions, indent=2) + "\n")
    validate_archive(destination, versions)
    write_latest(destination / "latest", str(versions[-1]["file"]))
    print(f"Synced {filename}; {len(versions)} canonical snapshots; latest/{versions[-1]['file']}")


if __name__ == "__main__":
    main()
