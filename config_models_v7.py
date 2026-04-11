# V7 Go agents — one registry entry per agent-backed "model" short name.
# Configure your agent in V7 Go (https://go.v7labs.com) with:
#   - A text (or long-text) input property whose slug matches input_field_slug / V7_GO_INPUT_FIELD_SLUG
#     (must match "Copy property slug" in the UI; wrong slug → HTTP 400 on entity create)
#   - If multimodal: True — a **file** property whose slug matches file_field_slug / V7_GO_FILE_FIELD_SLUG
#     (PDFs are resolved as V7_GO_PDF_DIR / <pdf_filename from TSV>; see llm_v7.py upload flow)
#   - An output property (text / JSON) the agent fills with the same JSON shape as other backends
#   - Go Agent v2: set agent_template_json (e.g. v7_go_agent_v2_template.json) and multimodal True.
#     ``extractor.py --all-v7`` syncs that JSON from the API before submit; llm_v7 can auto-ensure missing
#     properties and re-sync per run. llm_v7 creates empty entities, uploads PDFs to the File property, and
#     merges tool-backed fields into one JSON object (property names mapped in llm_v7._V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY).
#   - If the project is a collection (child) agent, set V7_GO_PARENT_ENTITY_ID (or parent_entity_id below)
#
# Docs: https://docs.go.v7labs.com/reference/create-entities-programmatically

V7_MODELS = {
    # ── STUB: duplicate this block and set agent_id / slugs for your hackathon agent ──
    # PDF-only agent shaped like v7_go_agent_v2_template.json (File + one GPT field per ALL_FIELDS column).
    "v7-go-agent-v2": {
        "model": "V7 Go — v7_go_agent_v2 (PDF + per-property tools)",
        "multimodal": True,
        "modalities": ["pdf"],
        "tier": "v7",
        "price_in": 0.0,
        "price_out": 0.0,
        "ctx": 262_000,
        "notes": (
            "Set V7_GO_WORKSPACE_ID + V7_GO_AGENT_ID to your deployed project. "
            "Re-export agent_template_json from that same project (property ids are per-project), "
            "or set file_field_slug / V7_GO_FILE_FIELD_SLUG to your File property id from the UI. "
            "Do not set V7_GO_FILE_FIELD_SLUG=document-pdf for v2 unless that slug exists on the agent "
            "(the template File id is used when that env value would override incorrectly)."
        ),
        "agent_template_json": "v7_go_agent_v2_template.json",
        # Registry-only for non-v2 models; v2 PDF property = template unless overridden (see notes).
        "input_field_slug": "document-text",
        "output_field_slug": "extracted-json",
    },
}
