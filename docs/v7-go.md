# V7 Go — extraction backend (short reference)

This repo can run the charity PDF benchmark through **[V7 Go](https://go.v7labs.com)** (entity + file API) in addition to OpenRouter and Doubleword. Full detail lives in [README.md — V7 Go (optional backend)](../README.md#v7-go-optional-backend) and in `config_models_v7.py` / `llm_v7.py`.

---

## When to use V7 here

- You already have (or can deploy) a **Go Agent** whose outputs match the same JSON field names as the OpenRouter path (`charity_number`, `report_date`, nested `address__*`, etc.).
- You want **PDF-native** runs via **Go Agent v2** (empty entity, upload PDF, poll tool-backed properties) using the shared template `v7_go_agent_v2_template.json`.

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `V7_GO_API_KEY` or `V7_API_KEY` | Yes | `X-API-KEY` for the Go API |
| `V7_GO_WORKSPACE_ID` | Yes | Workspace UUID |
| `V7_GO_AGENT_ID` | Yes | Agent (project) UUID |
| `V7_GO_BASE_URL` | No | Default `https://go.v7labs.com` (avoid broken `api.go.v7labs.com` DNS) |
| `V7_GO_INPUT_FIELD_SLUG` / `V7_GO_OUTPUT_FIELD_SLUG` | No | Defaults `document-text` / `extracted-json` (single-output agents) |
| `V7_GO_FILE_FIELD_SLUG` | No | File property for PDFs; for Go Agent v2 often **omit** so the template export’s File id wins — see README |
| `V7_GO_PARENT_ENTITY_ID` | No | **Only** for collection (child) agents — parent **entity** id, not the project id |

---

## Typical commands

```bash
# Refresh the bundled Go Agent v2 template from your live project (after UI property changes)
python sync_v7_go_agent_template.py

# One V7 registry key (see config_models_v7.py)
python extractor.py v7-go-agent-v2/claude-sonnet

# All V7 keys in one run
python extractor.py --all-v7

# Override template JSON for this run only
python extractor.py --all-v7 --v7-agent-template ./path/to/project_export.json

# Resume / merge after failures
python extractor.py v7-go-agent-v2/claude-sonnet --retry-failed
```

Registry keys with a **`/`** become **`__`** in output filenames, for example:

`v7-go-agent-v2/claude-sonnet` → `data/playgroup_dev_extracted__v7__v7-go-agent-v2__claude-sonnet.tsv`

---

## Registry layout (`config_models_v7.py`)

There are **32** entries, all `multimodal` with PDF for this benchmark. Most keys look like `v7-go-agent-v2/<variant>` and share `agent_template_json: v7_go_agent_v2_template.json`; they differ by `v7_property_model` (concrete provider id or a V7 abstraction such as `ai_fast`, `ai_default`, `auto_llm`).

List keys:

```bash
python -c "from config_models_v7 import V7_MODELS; print('\n'.join(sorted(V7_MODELS)))"
```

---

## State and scoring

| Path | Role |
|------|------|
| `data/.v7_checkpoints.json` | Resume map for in-flight runs |
| `data/.v7_failed_rows.json` | Row indices for `--retry-failed` |
| `data/.v7_unavailable_models.json` | Submit failures; trim or delete to retry after fixing config |

`python score.py` and `python playground.py` include any `playgroup_dev_extracted__v7__*.tsv` files under `data/` automatically. Token/cost lines in stats may stay at zero until you add pricing on each registry row.

---

## Related files

| File | Role |
|------|------|
| `llm_v7.py` | HTTP client: entities, uploads, polling, v2 merge |
| `extractor.py` | Chooses V7 when the model key is in `V7_MODELS` |
| `sync_v7_go_agent_template.py` | Rebuild `v7_go_agent_v2_template.json` from the API |
| `v7_go_agent_v2_template.json` | Project export shape consumed by the runner |

For Doubleword-only platform notes, see [doubleword-platform-knowledge.md](doubleword-platform-knowledge.md).
