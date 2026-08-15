"""SI-043 — re-indexing must REPLACE a chunk's vector, not orphan it.

THE DEFECT THIS CLOSES. The store used a positional `IndexFlatIP`, which cannot remove a vector.
`add_chunks` appended new vectors and UPDATEd the SQLite row to point at them, so every re-index
of a file left its previous vectors in the index forever. On production those orphans climbed past
the 5% count-mismatch threshold every day or two, the run was declared CORRUPTED, and the
automatic rebuild reset them to zero — normal operation, permanently mislabelled as corruption.

The index is now `IndexIDMap2`, and each chunk keeps a STABLE id (its `chunks.faiss_index`), so the
superseded vector is removed before the replacement is added.
"""
import asyncio
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest

import document_interrogator as di
from tests.unit.shared_loop import run

pytestmark = pytest.mark.skipif(not getattr(di, "FAISS_AVAILABLE", False),
                                reason="faiss not installed")


def _store(work: Path):
    return di.FAISSDocumentStore(storage_dir=str(work / "store"))


def _chunks(n, text):
    return [di.DocumentChunk(chunk_id=f"/tmp/doc.md::{i}", document_path="/tmp/doc.md",
                             content=f"{text} paragraph {i}", chunk_index=i, total_chunks=n)
            for i in range(n)]


def _counts(store):
    cur = store.metadata_db.cursor()
    rows = cur.execute("SELECT COUNT(*) FROM chunks WHERE faiss_index IS NOT NULL").fetchone()[0]
    return rows, store.faiss_index.ntotal


def test_reindexing_replaces_vectors_instead_of_orphaning_them():
    """Three ingests of the same chunk_ids with DIFFERENT content each time. Vectors must track
    rows exactly. On the pre-fix positional index this went 5 -> 10 -> 15 against 5 rows."""

    async def main():
        work = Path(tempfile.mkdtemp(prefix="si043_id_"))
        store = _store(work)

        await store.add_chunks(_chunks(5, "original earthquake prose"))
        assert _counts(store) == (5, 5), f"first ingest: {_counts(store)}"

        await store.add_chunks(_chunks(5, "revised volcano prose"))
        rows, vectors = _counts(store)
        assert (rows, vectors) == (5, 5), (
            f"re-index orphaned vectors: {rows} rows vs {vectors} vectors "
            f"({vectors - rows} orphaned)")

        await store.add_chunks(_chunks(5, "third revision about tsunamis"))
        rows, vectors = _counts(store)
        assert (rows, vectors) == (5, 5), f"third pass: {rows} rows vs {vectors} vectors"

        # No duplicate ids: remove-before-add must hold, or the id map grows silently.
        import faiss
        ids = list(faiss.vector_to_array(store.faiss_index.id_map))
        assert len(ids) == len(set(ids)), f"duplicate ids in the index: {ids}"

    run(main())


def test_search_returns_the_NEW_content_after_a_reindex():
    """Removing the old vector is only correct if the new one is what search finds. A stale
    vector left behind could still win the similarity contest and serve deleted text."""

    async def main():
        work = Path(tempfile.mkdtemp(prefix="si043_search_"))
        store = _store(work)
        await store.add_chunks(_chunks(3, "alpaca husbandry in the andes"))
        await store.add_chunks(_chunks(3, "submarine volcano monitoring"))

        hits = await store.search_similar("submarine volcano monitoring", k=3)
        assert hits, "no search results at all — the test cannot discriminate"
        joined = " ".join(h.get('content', '') for h in hits).lower()
        assert "volcano" in joined, f"search did not return the new content: {joined[:200]}"
        assert "alpaca" not in joined, f"search returned SUPERSEDED content: {joined[:200]}"

    run(main())


def test_a_legacy_positional_index_is_migrated_without_re_embedding():
    """Production had 8.5k vectors in a positional index. Migration must carry them across by
    reconstruction (no embedding spend), keep every row valid, and DROP the accumulated orphans."""

    async def main():
        work = Path(tempfile.mkdtemp(prefix="si043_mig_"))
        store = _store(work)
        await store.add_chunks(_chunks(4, "seismic wave propagation"))

        # Rebuild the pre-fix situation: a positional index carrying 3 extra orphan vectors.
        import faiss
        dim = store.dimension
        legacy = faiss.IndexFlatIP(dim)
        for i in range(4):
            legacy.add(store.faiss_index.reconstruct(i).reshape(1, dim))
        legacy.add(np.random.rand(3, dim).astype('float32'))       # orphans
        assert legacy.ntotal == 7
        faiss.write_index(legacy, str(store.index_path))
        store.metadata_db.close()

        migrated = _store(work)          # re-open: triggers the migration on load
        rows, vectors = _counts(migrated)
        assert hasattr(migrated.faiss_index, "id_map"), "index was not migrated to IndexIDMap2"
        assert (rows, vectors) == (4, 4), (
            f"migration should carry 4 referenced vectors and drop 3 orphans, got "
            f"{rows} rows / {vectors} vectors")

        hits = await migrated.search_similar("seismic wave propagation", k=2)
        assert hits, "migrated index returns no search results"

        # A NEW chunk after migration must not collide with a carried-over id.
        await migrated.add_chunks([di.DocumentChunk(
            chunk_id="/tmp/other.md::0", document_path="/tmp/other.md",
            content="a brand new document about glaciers", chunk_index=0, total_chunks=1)])
        rows, vectors = _counts(migrated)
        assert (rows, vectors) == (5, 5), f"post-migration insert: {rows} rows / {vectors} vectors"
        ids = list(faiss.vector_to_array(migrated.faiss_index.id_map))
        assert len(ids) == len(set(ids)), f"id collision after migration: {ids}"

    run(main())


def test_the_integrity_monitor_accepts_non_contiguous_ids():
    """The old range check asserted `faiss_index < ntotal`, which is meaningless once ids are ids:
    after a removal they are deliberately non-contiguous. Left unchanged it would have reported a
    healthy migrated index as CORRUPTED on every boot."""

    async def main():
        work = Path(tempfile.mkdtemp(prefix="si043_mon_"))
        store = _store(work)
        await store.add_chunks(_chunks(6, "glacier retreat measurements"))

        # Delete a middle chunk's vector+row so the surviving ids have a hole.
        cur = store.metadata_db.cursor()
        victim = cur.execute("SELECT faiss_index FROM chunks LIMIT 1 OFFSET 2").fetchone()[0]
        store.faiss_index.remove_ids(np.array([int(victim)], dtype='int64'))
        cur.execute("DELETE FROM chunks WHERE faiss_index = ?", (int(victim),))
        store.metadata_db.commit()

        from tools.faiss_integrity_monitor import FAISSIntegrityMonitor
        result = await FAISSIntegrityMonitor(store).comprehensive_integrity_check()
        assert result['metrics']['range_validity']['valid'], (
            f"non-contiguous ids reported invalid: {result['metrics']['range_validity']}")
        assert result['status'] != 'CORRUPTED', f"healthy index reported {result['status']}"

    run(main())
