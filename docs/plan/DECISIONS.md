# Planning & Architecture Decisions

| Date | Category | Decision | Context / Rationale |
|---|---|---|---|
| 2026-10-31 | routing | Small requirement / Flow C | Bounded integration of direct Google DeepMind Gemini API into existing docextract provider framework. |
| 2026-10-31 | architecture | Use `google-*` prefix | Distinguishes native Google DeepMind provider from OpenRouter's `gemini-*` entries in `extractor.py`. |
| 2026-10-31 | protocol | Google OpenAI-compatible endpoint | Maximizes reuse of existing `openai` client without adding new external package dependencies. |
| 2026-10-31 | config | `GEMINI_API_KEY` (fallback `GOOGLE_API_KEY`) | Standard environment variables for Gemini API authentication. |
| 2026-10-31 | scope | Simplest shape: text OCR prompt | Native multimodal and async batching deferred as non-goals for Phase 1 to guarantee fair baseline comparisons. |
| 2026-10-31 | ownership | Decision ownership matrix established | Logged in `docs/plan/DECISION-OWNERSHIP.md`. |
| 2026-10-31 | quality-lens | 18/18 checks passed | confirmed |
| 2026-10-31 | skill-proposer | model-split confirmed | Planning: claude-opus-5-5 / Antigravity · Execution: claude-sonnet-5-5 / Antigravity |
| 2026-10-31 | skill-proposer | proposed skills | /tdd, /clean-commit, /verify-slice, /security-review, /project-hygiene |
