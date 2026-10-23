# CHANGELOG v1.0.0.339 — 2026-10-23

## Docs: indexing local documents is optional

**Why:** owner, 2026-10-23: "Indexing local documents by RAICA requires OpenAI compatible API to a local or cloud LLM via
Ollama or other providers. It is not required for the operations of NewX. so it should be documented as optional!"

### Documentation
- `docs/production/INSTALLATION_GUIDE.md` — new **§9 Optional: Indexing Local Documents**: what it needs (an embedding
  API under `document_interrogator.embedding` — OpenAI, an OpenAI-compatible service, or a local/cloud model through
  Ollama or another provider — and at least one folder to index); that a fresh install indexes nothing; how to turn
  it on (`POST /documents/index-directory` or `watched_directories.json`); what is off without it (`document_search`;
  in NewX only the HelpTips bot, which answers only from its indexed help documentation); and that the same provider
  also serves `POST /v1/embeddings`, which is separate from indexing.
- `README.md` — the Document Intelligence feature and the Smart Document Search example are marked optional, with a
  pointer to §9. Version 1.0.0.339.

### Checked in the code (not run-tested in this release)
- Startup creates the indexer inside a `try` (`fastapi_server_complete.py` lifespan); a failure is a warning and the
  server continues. Creating it calls no embedding provider (`DocumentInterrogator.__init__`).
- With no `watched_directories.json`, RAICA writes one with `"directories": []`; `_safe_startup_config_scan` logs
  `No directories configured for watching` and returns; the background scan (on by default) has nothing to scan.
- HelpTips (`NewX newx/ai_plugins/HelpTips.yaml`) allows only `document_search` and answers only from what it returns.

### Code, configuration, dependencies
- None changed. No migration.
