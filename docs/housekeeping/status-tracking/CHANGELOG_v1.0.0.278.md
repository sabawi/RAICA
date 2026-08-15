# CHANGELOG v1.0.0.278

**Date:** 2026-08-15
**Focus:** SI-043 — two latent re-indexing defects that orphan FAISS vectors.

## Read this first: what this release does NOT fix

The prod symptom that started this — FAISS integrity cycling HEALTHY → CORRUPTED → rebuild every
day or two — is **not fixed here, and these changes would not have prevented any of it.**

I recommended fixing the watcher guard on the grounds that it "removes the avoidable share of the
leak". Measurement refuted that twice:

| Claim | Measurement | Verdict |
|---|---|---|
| The unguarded watchdog path re-ingests files | `📝 File modified` = **0**, `📄 New file detected` = **0** across all retained prod logs; no observers ever started | **Refuted** — path never runs |
| mtime-only re-index wastes work on `git pull` | prod `Change detected (hash)` = **14**, `(mtime)` = **0** | **Refuted** — branch never fires |

Every observed re-index was a genuine content change, through the periodic scan at `:1925`, which
**already** guarded correctly. The leak is therefore **100% structural**: re-indexing changed
content orphans its old vectors because FAISS `IndexFlat` cannot remove them. That remains open.

## What this release does fix (latent hardening)

Both defects are real but currently unreachable. They are closed so that enabling the watcher —
there is a `start_watching` endpoint at `fastapi_server_complete.py:14204` — does not immediately
begin orphaning vectors on every editor save.

1. **Watchdog parity.** `on_created` / `on_modified` called `_process_single_file` directly, while
   every scan caller (`:1534`, `:1751`, `:1925`) guarded with `_file_needs_reindexing`. They now
   route through a new `_process_file_if_changed`, which applies that same guard. Fails open: if
   the check errors, the file is processed, preserving old behaviour.

2. **mtime-only re-index.** `_file_needs_reindexing` returned `True` when mtime changed even if the
   content hash was **identical** — the `git pull` / `checkout` / editor-save / `touch` case. It
   now refreshes the stored mtime and skips. Content is what is worth re-embedding.

Why this matters when it is reachable: `add_chunks` appends vectors then UPDATEs rows to point at
them (`chunk_id` is path+index, so re-indexing reuses ids). The superseded vectors are orphaned
permanently. Embeddings are also a paid OpenAI `text-embedding-3-small` call.

## Tests

`tests/unit/test_watcher_reindex_guard.py` — one test, three steps, one event loop:

1. index a file → vectors > 0
2. rewrite identical bytes → vector count must be **unchanged**
3. **control:** change the content for real → count must **grow**

Step 3 exists because step 2's assertion ("no vectors added") is also what a dead embedding
pipeline produces. An earlier two-test split passed individually and failed as a pair, because an
embedding client stays bound to the first `asyncio.run` loop — step 2 was passing for the wrong
reason. The test discovers the handler's dispatch target from source rather than hardcoding it, so
on pre-fix code it **fails** (`vectors 1 -> 2`) instead of erroring on a missing attribute.

Suite: **474 passed**, 4 pre-existing failures unchanged. Version sync 5/5.

## Still open

The structural cause. Choose between `IndexIDMap2` + `remove_ids` on update, or keeping the
rebuild as compaction but scheduling it honestly rather than letting normal operation cross a 5%
threshold and be reported as `CORRUPTED`. Related: SI-042 (DEGRADED never triggers the rebuild and
is logged as "integrity check passed").

## Files

- `document_interrogator.py` — `_process_file_if_changed`; watchdog handlers; mtime branch
- `tests/unit/test_watcher_reindex_guard.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-043 corrected
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.278
