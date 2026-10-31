# Decision Ownership

This document defines the decision ownership boundary between Human and AI Agent for this project.

## Reference
- Portable always-on rule: `decision-ownership` (`~/.claude/rules/decision-ownership.md` / `~/.cursor/rules/decision-ownership.mdc`).

## Responsibility Matrix

| Area | Owner | Notes |
|---|---|---|
| **Scope, MoSCoW, YAGNI Demotions** | Human | Human decides what is in-scope vs deferred |
| **Model Selection & Provider API Keys** | Human | Human supplies keys and decides models to test |
| **Architecture Boundaries & Interfaces** | Shared | Agent proposes patterns matching existing codebase; Human approves |
| **Code Implementation & Unit Tests** | Agent | Agent authors code adhering to Simple Design, TDD, and project invariants |
| **Git Commit & Branch Protocol** | Agent | Agent creates branches and follows Conventional Commits |
| **Release & Merge to Main** | Human | Human triggers or approves merge to main |

