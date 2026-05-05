# CHANGELOG v1.0.0.61

**Date:** 2026-05-05  
**Previous:** v1.0.0.58  
**Trigger:** Deep Code Audit (docs/DEEP_CODE_AUDIT_2026-05-05.md)

---

## Summary

Remediated 14 issues from the deep code audit across 3 stages: credential exposure, unbounded memory growth, bare exception handling, path traversal, deprecated APIs, and configuration hardening.

---

## New Features

- `load_dotenv()` auto-loads `.env` file at server startup — no manual env var exports needed
- `_count_tokens()` uses `tiktoken` (cl100k_base) for accurate token counting in OpenAI-compatible responses; falls back to word count if unavailable
- `_get_ollama_health_url()` derives health check URL from `ServerConfig.OLLAMA_URL`
- `_cleanup_openai_conversations()` helper for TTL-based conversation memory cleanup

---

## Fixes

### CRITICAL
- **ISSUE #9-SECURITY:** Removed hardcoded `Down2earth!` database password fallback in `ServerConfig.DB_PASSWORD`. Server now fails fast with `RuntimeError` if `DB_PASSWORD` env var is not set.
- **ISSUE #1:** Added `MAX_CACHE_SIZE=1000` with LRU eviction (by oldest expiration) to `cache_set()` — prevents unbounded `simple_cache` memory growth.
- **ISSUE #2:** Added `OPENAI_CONVERSATION_TTL=3600` (1 hour) with `_cleanup_openai_conversations()` helper — prevents unbounded `openai_conversations` memory leak.
- **ISSUE #3:** Replaced all 19 bare `except:` clauses with `except Exception:` or `except Exception as e:` + logging — prevents silent swallowing of `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and `asyncio.CancelledError`.

### HIGH
- **ISSUE #5:** Removed duplicate `_apply_smart_file_decisions_for_sandboxed_executor()` call at line 8828 — copy-paste artifact was double-processing email attachments.
- **ISSUE #7:** Replaced hardcoded fake success `"Hello there! I'm working properly with tools enabled."` with real error response containing `finish_reason: "error"`, error message, and exception type.
- **ISSUE #8:** Replaced hardcoded `max_context_window=65536` byte limit with config-driven value (`context_window_size * 4`). Bumped primary model `context_window_size` from 16384 to 32768 tokens.
- **ISSUE #13:** Added `os.path.realpath()` containment check before file opens in image processing (line 7931) and `file://` URL handler (line 10991). Blocks reads outside project directory.

### MEDIUM
- **ISSUE #15:** Replaced all 10 deprecated `asyncio.get_event_loop()` calls with `asyncio.get_running_loop()` — prevents `RuntimeError` on Python 3.12+.
- **ISSUE #10:** Removed per-request `config_loader.load_config()` call from middleware; reuses module-level cached values loaded once at startup.

### LOW
- **ISSUE #18:** All 3 hardcoded `http://127.0.0.1:11434/api/tags` URLs now use `_get_ollama_health_url()` derived from `ServerConfig.OLLAMA_URL`.
- **ISSUE #14:** Added missing `__init__.py` files to `hooks/` and `integrations/` directories.
- **ISSUE #17:** Replaced naive `len(text.split())` token counting with `_count_tokens()` using tiktoken.

---

## Configuration Changes

| File | Change |
|------|--------|
| `config/llm_config.yaml` | `context_window_size: 16384` → `32768` (primary model) |
| `.env` | `DB_PASSWORD` is now **required** (no hardcoded fallback) |

---

## New Dependencies

- `tiktoken>=0.5.0` — accurate BPE token counting for OpenAI-compatible endpoint

---

## Deployment Notes

1. **CRITICAL:** Ensure `.env` file on target server has `DB_PASSWORD` set before deploying
2. Install updated dependencies: `pip install -r requirements.txt`
3. Deploy files: `fastapi_server_complete.py`, `config/llm_config.yaml`, `version.py`, `requirements.txt`, `hooks/__init__.py`, `integrations/__init__.py`
4. Restart server: `./stop_complete.sh && ./start_complete.sh`
5. Verify: `curl http://127.0.0.1:5000/health` should show `"version": "1.0.0.61"`

---

## Deferred Issues

| # | Issue | Reason |
|---|-------|--------|
| #6 | Duplicate tool execution code | Requires architectural refactor — two execution paths need unification |
| #11 | Double JSON serialization in non-streaming | HIGH effort — needs separate non-streaming implementation |
| #12 | Hardcoded keyword matches for tool injection | MEDIUM effort — needs LLM arbitrator redesign |
| #4 | Redundant ad-hoc executors | LOW severity, confirmed no thread leak exists |

---

## Breaking Changes

- **DB_PASSWORD env var is now mandatory.** Servers without it set will fail to start with `RuntimeError`. The `.env` file must include `DB_PASSWORD=<value>`.
