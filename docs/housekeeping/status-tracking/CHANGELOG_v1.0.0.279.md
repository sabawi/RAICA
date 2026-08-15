# CHANGELOG v1.0.0.279

**Date:** 2026-08-15
**Focus:** SI-043 structural fix — FAISS `IndexIDMap2` migration so re-indexing replaces vectors.

## The problem

`FAISSDocumentStore` used a positional `IndexFlatIP`, which **cannot remove a vector**.
`add_chunks` appended new vectors and UPDATEd the SQLite row to point at them — and since
`chunk_id` is `_generate_chunk_id(path, index)` (path+index, not content), re-indexing a file
reused ids and stranded the previous vectors permanently.

On production those orphans climbed past the 5% count-mismatch threshold every day or two, the run
was declared `CORRUPTED`, and the automatic rebuild reset them to zero. Normal operation, labelled
as corruption, with a ~2 minute rebuild as the only compaction mechanism.

## The change

- The index is now `faiss.IndexIDMap2(faiss.IndexFlatIP(d))`.
- Each chunk keeps a **stable id** — its existing `chunks.faiss_index` value.
- `add_chunks` calls `remove_ids` on superseded ids **before** `add_with_ids`, so re-indexing
  replaces. (Removing first also prevents a duplicate id, which `add_with_ids` would otherwise
  create silently.)
- Legacy indexes migrate **on load**: `reconstruct` pulls each existing vector out of the old
  positional index, so **no embeddings are regenerated and no API spend is incurred**. Only
  positions still referenced by a chunk row are carried over, so the migration also **compacts**.
- `search_similar` needed no change — it already looked up `WHERE faiss_index = ?`, and
  `IndexIDMap2.search` returns those same ids.

### Second defect, found during the rehearsal

The integrity monitor's `_check_index_range_validity` asserted `faiss_index < ntotal`. That is
meaningless once ids are ids: after removals they are deliberately non-contiguous. On the migrated
real index `max_index=8613` against `ntotal=8330` would have been reported INVALID — i.e. a healthy
index declared CORRUPTED **on every boot**, triggering a needless rebuild. It now checks membership
in the live id set. `_perform_full_rebuild` and `tools/rebuild_faiss_index.py` preserve ids rather
than renumbering by position.

## Verification against the REAL production index

A copy of prod's `document_store/` (8,614 vectors / 5.9 MB metadata.db) was migrated locally
through the real store load path:

```
BEFORE  IndexFlatIP   8614 vectors / 8330 rows ->  284 ORPHANED
AFTER   IndexIDMap2   8330 vectors / 8330 rows ->    0 orphaned    (0.3s)
        unique ids       8330 of 8330
        count_sync       synchronized=True, orphaned=0
        range_validity   valid (id_mapped=True, live_ids=8330)
        lookup_integrity HEALTHY (0/100 failed)
        search           relevant hits returned, ntotal unchanged
```

Status remains `DEGRADED` for `EMBEDDING_INCONSISTENCY` — a separate concern (SI-042), untouched.

## Tests

`tests/unit/test_faiss_id_mapped_index.py` (new, 4 tests):

| Test | On pre-fix code |
|---|---|
| re-indexing replaces instead of orphaning (3 passes, + no duplicate ids) | **FAILS** — `5 rows vs 10 vectors (5 orphaned)` |
| legacy positional index migrates, drops orphans, new inserts don't collide | **FAILS** — `index was not migrated` |
| monitor accepts non-contiguous ids | **FAILS** |
| search returns the NEW content, not the superseded text | passes both ways (correctness guard) |

`tests/unit/shared_loop.py` (new): the embedding client stays bound to the loop that first used
it, so `asyncio.run` per test gave later tests a dead client — and a test asserting "no new
vectors" PASSES when embedding is dead. All indexing tests now share one session loop.

Suite: **478 passed**, 4 pre-existing failures unchanged. Version sync 5/5. Tool smoke 6/6.

## Deployment note

The migration runs automatically on first load and rewrites `document_store/faiss.index`.
`document_store/` was backed up on the live host before the restart.

## Files

- `document_interrogator.py` — `IndexIDMap2`, `_migrate_flat_index_to_ids`, id-stable `add_chunks`
- `tools/faiss_integrity_monitor.py` — id-membership range check, id-preserving rebuild
- `tools/rebuild_faiss_index.py` — id-preserving rebuild
- `tests/unit/test_faiss_id_mapped_index.py`, `tests/unit/shared_loop.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-043
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.279
