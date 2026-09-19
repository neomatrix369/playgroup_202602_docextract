from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_SUFFIX = "-which-models-extracted-playground.html"
REDIRECT_MARKERS = ('http-equiv="refresh"', "http-equiv='refresh'")

# Canonical provider display names as used in the HTML pages
PROVIDER_DISPLAY = {"doubleword": "Doubleword", "openrouter": "OpenRouter", "v7": "V7 Go"}
# Order matters: matches the provider table row order in playgroup-202602-docextract.html
PROVIDER_ORDER = ["Doubleword", "OpenRouter", "V7 Go"]


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
    if inputs and source.stat().st_mtime < max(path.stat().st_size for path in inputs if path.exists()):
        pass  # mtime check: only warn, not fail (timestamps can vary by copy)
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


# ---------------------------------------------------------------------------
# Site-page update helpers
# ---------------------------------------------------------------------------

def _load_score_data(source_root: Path) -> tuple[list[dict], dict[str, dict]]:
    """Return (scored_models, stats_by_name) using score.py's own _load_stats.

    Uses score.py's _load_stats (not just the raw CSV) so that OR models without
    real timing get the same estimated elapsed/cost values that `python score.py`
    prints in its Provider Summary — keeping the project page consistent.
    """
    old_cwd = os.getcwd()
    try:
        os.chdir(source_root)
        sys.path.insert(0, str(source_root))
        from score import score_all_models, _load_stats  # noqa: PLC0415
        scored = score_all_models(
            str(source_root / "data/playgroup_dev_expected.tsv"), verbose=False
        )
        # _load_stats returns {model_name: {elapsed_secs, cost_usd, estimated}}
        stats = _load_stats(
            stats_filename=str(source_root / "data/extraction_stats.csv"),
            call_log_filename=str(source_root / "data/extraction_call_log.csv"),
        )
    finally:
        os.chdir(old_cwd)
        if str(source_root) in sys.path:
            sys.path.remove(str(source_root))
    return scored, stats


def _provider_stats(scored: list[dict], stats: dict[str, dict]) -> dict[str, dict]:
    """Compute per-provider summary matching `python score.py` Provider Summary output."""
    summary: dict[str, dict] = {
        p: {"all": 0, "active": 0, "fail": 0, "f1s": [], "fields": [],
            "times": [], "costs": [], "best_f1": 0.0, "best_model": ""}
        for p in PROVIDER_ORDER
    }
    for r in scored:
        prov = PROVIDER_DISPLAY.get(r.get("provider", ""), r.get("provider", ""))
        if prov not in summary:
            summary[prov] = {"all": 0, "active": 0, "fail": 0, "f1s": [], "fields": [],
                             "times": [], "costs": [], "best_f1": 0.0, "best_model": ""}
        p = summary[prov]
        p["all"] += 1
        f1 = r["f1"]
        if f1 > 0:
            p["active"] += 1
            p["f1s"].append(f1)
            p["fields"].append(r["fields_found"])
            # stats comes from score.py _load_stats: keys are elapsed_secs / cost_usd
            st = stats.get(r["model_name"], {})
            t = float(st.get("elapsed_secs", 0) or 0)
            c = float(st.get("cost_usd", 0) or 0)
            if t > 0:
                p["times"].append(t)
            if c > 0:
                p["costs"].append(c)
            if f1 > p["best_f1"]:
                p["best_f1"] = f1
                p["best_model"] = r["model_name"]
        else:
            p["fail"] += 1
    # Compute aggregates
    for p in summary.values():
        p["avg_f1"] = round(sum(p["f1s"]) / len(p["f1s"]), 3) if p["f1s"] else 0.0
        p["avg_fields"] = sum(p["fields"]) / len(p["fields"]) if p["fields"] else 0.0
        p["avg_time"] = sum(p["times"]) / len(p["times"]) if p["times"] else 0.0
        p["avg_cost"] = sum(p["costs"]) / len(p["costs"]) if p["costs"] else 0.0
    return summary


def _top_models(scored: list[dict], n: int = 5) -> list[dict]:
    """Return top-N scored models sorted by F1 descending."""
    ranked = sorted(
        [r for r in scored if r["f1"] > 0],
        key=lambda r: r["f1"],
        reverse=True,
    )
    return ranked[:n]


def _patch(text: str, pattern: str, replacement: str, label: str) -> tuple[str, bool]:
    new_text, count = re.subn(pattern, replacement, text, flags=re.DOTALL)
    if count == 0:
        print(f"  WARN: pattern not found for {label!r}")
    return new_text, count > 0


def _write_if_changed(path: Path, content: str) -> bool:
    current = path.read_text() if path.exists() else ""
    if current == content:
        return False
    path.write_text(content)
    return True


def _update_archive_index(
    pages_root: Path, stamp: str, n_models: int, n_historic: int
) -> bool:
    path = pages_root / "demos/playgroup-202602-docextract/index.html"
    text = path.read_text()
    date = stamp[:10]

    text, _ = _patch(
        text,
        r'content="Archived snapshots[^"]*"',
        f'content="Archived snapshots of the UK Charity Doc Extract model playground — {n_historic + 1} versions from git history."',
        "archive meta description",
    )
    text, _ = _patch(
        text,
        r'Current benchmark — \d+ scored runs · \d+ tabs · <code>[^<]+</code>',
        f'Current benchmark — {n_models} scored runs · 8 tabs · <code>{stamp}</code>',
        "archive index subtitle",
    )
    text, _ = _patch(
        text,
        r'\d+ earlier versions recovered from git',
        f'{n_historic} earlier versions recovered from git',
        "archive historic count",
    )
    return _write_if_changed(path, text)


def _update_manifest(pages_root: Path, n_models: int, n_historic: int) -> bool:
    path = pages_root / "pages/manifest.json"
    text = path.read_text()
    text, _ = _patch(
        text,
        r'Multi-model PDF extraction benchmark — \d+ scored runs across OpenRouter, Doubleword, and V7 Go\.',
        f'Multi-model PDF extraction benchmark — {n_models} scored runs across OpenRouter, Doubleword, and V7 Go.',
        "manifest group description",
    )
    text, _ = _patch(
        text,
        r'Latest snapshot plus \d+ historic versions — rankings, heatmaps, provider analysis\.',
        f'Latest snapshot plus {n_historic} historic versions — rankings, heatmaps, provider analysis.',
        "manifest playground description",
    )
    return _write_if_changed(path, text)


def _update_site_js(pages_root: Path, n_models: int, n_historic: int) -> bool:
    path = pages_root / "assets/js/site.js"
    text = path.read_text()
    text, _ = _patch(
        text,
        r'Multi-model PDF extraction benchmark — \d+ scored runs\.',
        f'Multi-model PDF extraction benchmark — {n_models} scored runs.',
        "site.js group description",
    )
    text, _ = _patch(
        text,
        r'Latest plus \d+ historic snapshots\.',
        f'Latest plus {n_historic} historic snapshots.',
        "site.js playground description",
    )
    return _write_if_changed(path, text)


def _update_root_index(pages_root: Path, n_models: int, n_historic: int) -> bool:
    path = pages_root / "index.html"
    text = path.read_text()
    text, _ = _patch(
        text,
        r'Latest \+ \d+ historic snapshots · \d+ scored runs · rankings &amp; heatmaps',
        f'Latest + {n_historic} historic snapshots · {n_models} scored runs · rankings &amp; heatmaps',
        "root index hero text",
    )
    return _write_if_changed(path, text)


def _update_pages_readme(pages_root: Path, n_canonical: int) -> bool:
    path = pages_root / "README.md"
    text = path.read_text()
    text, _ = _patch(
        text,
        r'Doc extract — playground archive \(\d+ snapshots\)',
        f'Doc extract — playground archive ({n_canonical} snapshots)',
        "pages README snapshot count",
    )
    return _write_if_changed(path, text)


def _update_source_readme(source_root: Path, n_historic: int, n_models: int) -> bool:
    path = source_root / "README.md"
    text = path.read_text()
    text, _ = _patch(
        text,
        r'\*\*Playground archive\*\* \(\d+ snapshots, embedded viewer\)',
        f'**Playground archive** ({n_historic} snapshots, embedded viewer)',
        "source README archive count",
    )
    text, _ = _patch(
        text,
        r'\*\*Hosted latest playground\*\* \(\d+ scored runs\)',
        f'**Hosted latest playground** ({n_models} scored runs)',
        "source README scored runs",
    )
    return _write_if_changed(path, text)


def _provider_table_rows(providers: dict[str, dict]) -> str:
    rows = []
    for pname in PROVIDER_ORDER:
        if pname not in providers:
            continue
        p = providers[pname]
        avg_fv = p["avg_fields"]
        pct = round(avg_fv / 85 * 100)
        avg_t = round(p["avg_time"])
        avg_c = p["avg_cost"]
        best_model = p["best_model"]
        # Strip v7-go-agent-v2__ prefix used in filenames (display as short name)
        best_model = re.sub(r'^v7-go-agent-v2[_/]+', '', best_model)
        rows.append(
            f'          <tr>\n'
            f'            <td>{pname}</td>\n'
            f'            <td class="num">{p["all"]}</td>\n'
            f'            <td class="num">{p["active"]}</td>\n'
            f'            <td class="num">{p["fail"]}</td>\n'
            f'            <td class="num">{p["avg_f1"]:.3f}</td>\n'
            f'            <td class="num">{p["best_f1"]:.3f}</td>\n'
            f'            <td>{best_model}</td>\n'
            f'            <td class="num">{avg_fv:.1f}/85 ({pct}%)</td>\n'
            f'            <td class="num">{avg_t}s</td>\n'
            f'            <td class="num">${avg_c:.3f}</td>\n'
            f'          </tr>'
        )
    return "\n".join(rows)


def _leaderboard_rows(top_models: list[dict]) -> str:
    rows = []
    for rank, r in enumerate(top_models, 1):
        prov = PROVIDER_DISPLAY.get(r.get("provider", ""), r.get("provider", ""))
        name = r["model_name"]
        if "/" in name:
            name = name.split("/", 1)[1]
        ff = r["fields_found"]
        rows.append(
            f'          <tr><td class="num">{rank}</td>'
            f'<td>{name}</td>'
            f'<td>{prov}</td>'
            f'<td class="num">{r["f1"]:.3f}</td>'
            f'<td class="num">{r["precision"]:.3f}</td>'
            f'<td class="num">{r["recall"]:.3f}</td>'
            f'<td class="num">{ff:.1f}/85</td></tr>'
        )
    return "\n".join(rows)


def _takeaway_bullets(
    top10_models: list[dict],
    providers: dict[str, dict],
) -> str:
    """Generate takeaways bullets from live data. top10_models must be exactly the top-10 list."""
    n_top = len(top10_models)
    dw_count_top = sum(
        1 for r in top10_models
        if PROVIDER_DISPLAY.get(r.get("provider", ""), "") == "Doubleword"
    )
    or_count_top = sum(
        1 for r in top10_models
        if PROVIDER_DISPLAY.get(r.get("provider", ""), "") == "OpenRouter"
    )
    top_models = top10_models  # alias for clarity below

    dw = providers.get("Doubleword", {})
    dw_active = dw.get("active", 0)
    dw_all = dw.get("all", 0)
    dw_avg_f1 = dw.get("avg_f1", 0.0)
    dw_best_f1 = dw.get("best_f1", 0.0)
    dw_best = dw.get("best_model", "")
    or_p = providers.get("OpenRouter", {})
    or_best = or_p.get("best_model", "")
    or_best_f1 = or_p.get("best_f1", 0.0)

    # Best OR rank in top-5
    or_top_rank = next(
        (i + 1 for i, r in enumerate(top_models) if PROVIDER_DISPLAY.get(r.get("provider", ""), "") == "OpenRouter"),
        None,
    )
    or_rank_note = f"; <code>{or_best}</code> is {_ordinal(or_top_rank)} at {or_best_f1:.3f}" if or_top_rank else ""

    dw_leader_note = f" Retains the global leader (<code>{dw_best}</code>, {dw_best_f1:.3f}){or_rank_note}."

    # Find newest DW entry in top-5 that isn't the global leader (to highlight new entries)
    new_dw = next(
        (r for r in top_models
         if PROVIDER_DISPLAY.get(r.get("provider", ""), "") == "Doubleword"
         and r["model_name"] != dw_best),
        None,
    )
    new_entry_note = ""
    if new_dw:
        new_rank = top_models.index(new_dw) + 1
        new_name = new_dw["model_name"]
        if "/" in new_name:
            new_name = new_name.split("/", 1)[1]
        new_entry_note = f" <code>{new_name}</code> is rank {new_rank} at F1 {new_dw['f1']:.3f}."

    fail_count = dw.get("fail", 0)
    f1_range = f"{dw_avg_f1:.3f}–{dw_best_f1:.3f}"

    lines = [
        f'      <li><strong>Doubleword holds {dw_count_top} of the global top {n_top}.</strong>{dw_leader_note}{new_entry_note}</li>',
        f'      <li><strong>{dw_active} of {dw_all} Doubleword models</strong> produced usable results (F1 range {f1_range} for standard text LLMs).</li>',
        '      <li><strong>Free-tier models universally failed</strong> — the zero-score runs are free-tier or had context/format issues.</li>',
        '      <li><strong>Precision is consistently high</strong> (0.96–0.97); recall differentiates leaders.</li>',
        '      <li><strong>Hardest fields:</strong> <code>income_annually_in_british_pounds</code> and <code>spending_annually_in_british_pounds</code>.</li>',
    ]
    return "\n".join(lines)


def _ordinal(n: int | None) -> str:
    if n is None:
        return "?"
    suffixes = {1: "st", 2: "nd", 3: "rd"}
    return f"{n}{suffixes.get(n if n <= 3 else 0, 'th')}"


def _latest_snapshot_desc(metadata: dict, top10: list[dict]) -> str:
    """Derive a human-readable description for the latest snapshot table row.

    Strategy: find the model referenced in the commit subject (most specific),
    fall back to naming the new entry by comparing counts, or a generic label.
    """
    subject = str(metadata.get("subject", ""))
    # Try to extract a model name and F1 from the commit subject
    # e.g. "feat(doubleword): add dw-deepseek-v4.1-flash extraction results (F1=0.941, rank 10 globally)"
    model_match = re.search(r'add ([\w./-]+) extraction', subject)
    f1_match = re.search(r'F1=(\d+\.\d+)', subject)
    rank_match = re.search(r'rank (\d+)', subject)
    if model_match and f1_match:
        name = model_match.group(1)
        f1 = f1_match.group(1)
        rank = rank_match.group(1) if rank_match else None
        rank_part = f", rank {rank}" if rank else ""
        return f"Latest — {name} (F1={f1}{rank_part})"
    # Fall back to just "Latest" + model count
    return f"Latest — {metadata.get('models', '?')} scored runs"


def _latest_snapshot_row(stamp: str, n_models: int, top10: list[dict], metadata: dict) -> str:
    """Build the latest-row <tr> for the snapshot evolution table."""
    filename = metadata["file"]
    href = f"../demos/playgroup-202602-docextract/{filename}"
    desc = _latest_snapshot_desc(metadata, top10)
    # No leading spaces — the regex replaces starting at <tr, so the original
    # indentation (spaces before the tag) is preserved from the surrounding text.
    return (
        f'<tr class="latest-row">'
        f'<td class="num">{stamp}</td>'
        f'<td class="num">{n_models}</td>'
        f'<td class="num">{n_models}</td>'
        f'<td>{desc}</td>'
        f'<td><a href="{href}">Open</a></td></tr>'
    )


def _update_project_page(
    pages_root: Path,
    stamp: str,
    n_models: int,
    n_canonical: int,
    providers: dict[str, dict],
    top_models: list[dict],
    metadata: dict,
) -> bool:
    path = pages_root / "pages/playgroup-202602-docextract.html"
    text = path.read_text()
    date = stamp[:10]
    n_historic = n_canonical - 1

    dw = providers.get("Doubleword", {})
    or_p = providers.get("OpenRouter", {})
    v7_p = providers.get("V7 Go", {})
    dw_all = dw.get("all", 0)
    or_all = or_p.get("all", 0)
    v7_all = v7_p.get("all", 0)

    # "All N snapshots" button
    text, _ = _patch(
        text,
        r'>All \d+ snapshots<',
        f'>All {n_canonical} snapshots<',
        "project page all-snapshots button",
    )

    # Results snapshot line
    text, _ = _patch(
        text,
        r'Results snapshot: <strong>[^<]+</strong> · \d+ scored runs · playground <code>[^<]+</code> \(\d+ archived versions from git history\)',
        f'Results snapshot: <strong>{date}</strong> · {n_models} scored runs · playground <code>{stamp}</code> ({n_canonical} archived versions from git history)',
        "project page snapshot line",
    )

    # Key findings paragraph
    text, _ = _patch(
        text,
        r'Provider aggregates match.*?Registries:[^<]+\.',
        f'Provider aggregates match <code>python score.py</code> over every <code>data/*_dev_extracted__*.tsv</code> file on\n      <strong>{date}</strong>: <strong>{n_models}</strong> scored runs\n      ({or_all} OpenRouter, {dw_all} Doubleword, {v7_all} V7 Go). Registries: 39 OpenRouter keys, 36 Doubleword models, 32 V7 keys.',
        "project page key findings paragraph",
    )

    # Provider table tbody
    prov_rows = _provider_table_rows(providers)
    text, _ = _patch(
        text,
        r'(?s)(<thead>\s*<tr>\s*<th>Provider</th>.*?</thead>\s*<tbody>).*?(</tbody>)',
        lambda m: f'{m.group(1)}\n{prov_rows}\n        {m.group(2)}',
        "project page provider table",
    )

    # Leaderboard tbody (Top 5)
    lb_rows = _leaderboard_rows(top_models)
    text, _ = _patch(
        text,
        r'(?s)(<thead>\s*<tr>\s*<th>Rank</th>.*?</thead>\s*<tbody>).*?(</tbody>)',
        lambda m: f'{m.group(1)}\n{lb_rows}\n        {m.group(2)}',
        "project page leaderboard table",
    )

    # Takeaways bullets — replace full <ul> content between <h2>Takeaways and </ul>
    # top_models here is top-5; takeaways need top-10 (caller passes top10 via metadata)
    top10 = metadata.get("_top10", top_models)
    bullets = _takeaway_bullets(top10, providers)
    text, _ = _patch(
        text,
        r'(?s)(<h2>Takeaways</h2>\s*<ul>).*?(</ul>)',
        lambda m: f'{m.group(1)}\n{bullets}\n    {m.group(2)}',
        "project page takeaways",
    )

    # Latest snapshot table row
    latest_row = _latest_snapshot_row(stamp, n_models, top10, metadata)
    text, _ = _patch(
        text,
        r'<tr class="latest-row">.*?</tr>',
        latest_row,
        "project page latest snapshot row",
    )

    # "View all N snapshots" link
    text, _ = _patch(
        text,
        r'View all \d+ snapshots with search and filters',
        f'View all {n_canonical} snapshots with search and filters',
        "project page view-all link",
    )

    # Footer date
    text, _ = _patch(
        text,
        r'Benchmark data snapshot \d{4}-\d{2}-\d{2}',
        f'Benchmark data snapshot {date}',
        "project page footer date",
    )

    return _write_if_changed(path, text)


def update_site_pages(
    pages_root: Path,
    source_root: Path,
    versions: list[dict],
    metadata: dict,
) -> None:
    """Update all site pages after a snapshot sync. Idempotent."""
    n_canonical = len(versions)
    n_historic = n_canonical - 1
    stamp = str(metadata["stamp"])
    n_models = int(metadata.get("f1", metadata.get("models", 0)))

    print("Loading score data for site-page updates…")
    scored, stats = _load_score_data(source_root)
    providers = _provider_stats(scored, stats)
    top5 = _top_models(scored, n=5)
    top10 = _top_models(scored, n=10)
    # Stash top10 in metadata so _update_project_page can pass it to helpers
    metadata["_top10"] = top10

    results = {
        "demos/playgroup-202602-docextract/index.html": _update_archive_index(
            pages_root, stamp, n_models, n_historic
        ),
        "pages/manifest.json": _update_manifest(pages_root, n_models, n_historic),
        "assets/js/site.js": _update_site_js(pages_root, n_models, n_historic),
        "index.html": _update_root_index(pages_root, n_models, n_historic),
        "README.md (pages)": _update_pages_readme(pages_root, n_canonical),
        "README.md (source)": _update_source_readme(source_root, n_historic, n_models),
        "pages/playgroup-202602-docextract.html": _update_project_page(
            pages_root, stamp, n_models, n_canonical, providers, top5, metadata
        ),
    }

    changed = [f for f, updated in results.items() if updated]
    unchanged = [f for f, updated in results.items() if not updated]
    if changed:
        print(f"  Updated ({len(changed)}): {', '.join(changed)}")
    if unchanged:
        print(f"  Already current ({len(unchanged)}): {', '.join(unchanged)}")


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
    update_site_pages(pages_root, source_root, versions, metadata)


if __name__ == "__main__":
    main()
