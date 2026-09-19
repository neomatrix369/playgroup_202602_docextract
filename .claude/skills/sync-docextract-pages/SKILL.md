---
name: sync-docextract-pages
description: Sync the verified DocExtract playground and related metadata into neomatrix369.github.io while preserving immutable history and compatibility URLs.
---

# sync-docextract-pages

Synchronize the UK Charity Document Extraction benchmark into `neomatrix369.github.io`.

## Hard rules

1. Run from a clean, committed DocExtract source state. A snapshot name comes from the commit that owns `which-models-extracted-playground.html`.
2. Run the DocExtract Playground Data Integrity Gate before synchronization. Never publish a playground that has not passed it.
3. Historical snapshots are immutable. If a destination filename exists with different bytes, stop.
4. Preserve compatibility redirects, including `2026-08-22T2100Z-which-models-extracted-playground.html`; redirects are not canonical snapshots and are excluded from counts.
5. Publish no secrets, `.env` files, checkpoints, provider credentials, or local configuration.
6. Do not publish `docs/doubleword-learning-hub-v4.html`.
7. Do not commit or push unless the user explicitly asks.

## Locations

- DocExtract source: `$DOCEXTRACT_ROOT`
- Pages repository: `$PAGES_ROOT`
- Hosted destination: `$PAGES_ROOT/demos/playgroup-202602-docextract/`
- Stable latest URL: `https://neomatrix369.github.io/demos/playgroup-202602-docextract/latest/`

Defaults:

- `DOCEXTRACT_ROOT`: repository containing this skill
- `PAGES_ROOT`: `/Users/swami/git-repos/ai-ml-dl-stuff/tools-and-utilities/neomatrix369.github.io`

## Procedure

```bash
bash .devin/skills/sync-docextract-pages/scripts/sync.sh
```

The script:
1. Validates repositories and the committed playground source.
2. Copies the snapshot append-only, updates `versions.json`, writes the stable latest redirect, and checks archive invariants.
3. **Automatically updates all site pages** from live data (no manual edits required):
   - `demos/playgroup-202602-docextract/index.html` — scored-run count, stamp, historic count
   - `pages/playgroup-202602-docextract.html` — snapshot line, key findings, provider table, leaderboard, takeaways, latest snapshot row, footer date
   - `pages/manifest.json` — scored-run and historic counts
   - `assets/js/site.js` — FALLBACK_PAGES descriptions
   - root `index.html` — hero text
   - `README.md` (pages repo) — snapshot count
   - `README.md` (source repo) — archive and scored-run counts

The script imports `score.py`'s own `_load_stats` so time/cost figures in the project page exactly match `python score.py` Provider Summary output. It is idempotent — run it twice and the second run reports all files already current.

After synchronization, verify manually:

```bash
cd "$PAGES_ROOT"
python3 -m http.server 8080
```

Open home → project page → archive → stable latest → archive navigation → Doubleword guide and confirm counts and provider table match `python score.py` output.