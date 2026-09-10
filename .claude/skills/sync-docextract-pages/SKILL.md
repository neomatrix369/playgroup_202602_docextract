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

The script validates repositories, identifies the committed playground snapshot, copies it append-only, updates `versions.json`, writes the stable latest redirect, and checks archive invariants.

Then reconcile the current snapshot metadata from the source README and generated playground across:

- `demos/playgroup-202602-docextract/index.html`
- `pages/playgroup-202602-docextract.html`
- `pages/manifest.json`
- `assets/js/site.js`
- root `index.html`
- `pages/projects.html`
- both repository READMEs

Verify scored-run, provider, canonical-snapshot, historic-snapshot, latest-stamp, leaderboard, and provider-summary values. Historical prose remains historical. Run the script a second time and require no additional diff.

After synchronization:

```bash
cd "$PAGES_ROOT"
python3 -m http.server 8080
```

Verify home → project page → archive → stable latest → archive navigation → Doubleword guide. Run the sync a second time and require an empty diff from the second run.