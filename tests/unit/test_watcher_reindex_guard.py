"""SI-043 — the watchdog path must not re-index a file whose content did not change.

WHY THIS EXISTS. `FAISSDocumentStore.add_chunks` appends to FAISS and then reconciles SQLite by
PRIMARY KEY. `chunk_id` is `_generate_chunk_id(path, index)` — path+index, NOT content — so
re-indexing reuses the same ids: the row is UPDATEd to point at the new vector and the previous
vector is ORPHANED. FAISS `IndexFlat` has no removal, so that orphan is permanent until a full
rebuild. On prod this cycled every day or two: orphans climbed past the 5% count-mismatch
threshold, the run was declared CORRUPTED, and the auto-rebuild reset it to zero.

Every scan caller already guarded its call with `_file_needs_reindexing` (startup config scan,
smart indexing, periodic directory scan). The watchdog handlers alone called
`_process_single_file` directly, so a byte-identical rewrite — git pull/checkout, an editor save,
`touch` — re-embedded the whole file for nothing and orphaned its vectors. Two paths doing one
job, one guarded and one not.

DISCRIMINATION. The test does not hardcode the fixed method name. It reads the handler source to
find which method the watcher actually dispatches to, then exercises THAT. On the pre-fix code the
handler names `_process_single_file`, the second call grows `ntotal`, and the test FAILS — it does
not crash on a missing attribute.
"""
import asyncio
import inspect
import re
import tempfile
from pathlib import Path

import pytest

import document_interrogator as di
from tests.unit.shared_loop import run


def _handler_target_name() -> str:
    """The method the watchdog on_modified handler dispatches to."""
    src = inspect.getsource(di.DirectoryWatcher.on_modified)
    m = re.search(r"self\.interrogator\.(_\w+)\(", src)
    assert m, "could not determine what on_modified dispatches to"
    return m.group(1)


@pytest.mark.skipif(not getattr(di, "WATCHDOG_AVAILABLE", False), reason="watchdog not installed")
@pytest.mark.skipif(not getattr(di, "FAISS_AVAILABLE", False), reason="faiss not installed")
def test_unchanged_file_skipped_but_real_change_still_indexed():
    """Three steps in ONE event loop, because the second half is what keeps the first half honest.

    Step 2 asserts that an identical rewrite adds NO vectors — but "no vectors added" is also what
    a BROKEN embedding pipeline produces, so on its own that assertion can pass by failing. Step 3
    changes the content for real and requires growth, proving the pipeline was alive the whole
    time. (Written after exactly that trap: split across two tests, each passed alone and the pair
    failed together, because an embedding client stays bound to the first asyncio loop.)
    """

    async def main():
        work = Path(tempfile.mkdtemp(prefix="si043_"))
        doc = work / "note.md"
        doc.write_text("# Title\n\nSome indexable prose about earthquakes.\n" * 3)

        interro = di.DocumentInterrogator.__new__(di.DocumentInterrogator)
        interro.store = di.FAISSDocumentStore(storage_dir=str(work / "store"))
        interro.processor = di.DocumentProcessor()
        target = getattr(interro, _handler_target_name())

        # 1. first index
        await target(str(doc))
        indexed = interro.store.faiss_index.ntotal
        assert indexed > 0, "first index produced no vectors — the test cannot discriminate"

        # 2. same bytes, new mtime — what git pull / an editor save produces
        doc.write_text(doc.read_text())
        await target(str(doc))
        after_identical = interro.store.faiss_index.ntotal
        assert after_identical == indexed, (
            f"re-indexed an unchanged file: vectors {indexed} -> {after_identical}; "
            f"{after_identical - indexed} orphaned, unremovable until a full rebuild"
        )

        # 3. CONTROL — a genuine change must still be indexed, in this same loop.
        doc.write_text("# Title\n\nCOMPLETELY DIFFERENT prose about volcanoes and lava.\n" * 9)
        await target(str(doc))
        after_real = interro.store.faiss_index.ntotal
        assert after_real > after_identical, (
            f"a genuine content change was NOT indexed ({after_identical} -> {after_real}). "
            f"Either the guard over-blocks, or the embedding pipeline is dead — in which case "
            f"step 2 above passed for the wrong reason."
        )

    run(main())
