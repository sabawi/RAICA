"""SI-042 — DEGRADED must be surfaced, and automatic rebuilds must not loop.

TWO DEFECTS THIS COVERS.

1. DEGRADED was a dead branch. It appended `SCHEDULED_REBUILD_RECOMMENDED` — a string nothing in
   the codebase ever read — never set `rebuild_required`, and `check_and_repair` returned
   `status in ['HEALTHY','DEGRADED']`, so the startup log announced "system is healthy". A real
   finding was detected on every boot and actioned never.

2. The obvious fix (make DEGRADED set `rebuild_required`) would have been a control loop with no
   damper. Measurement showed why: `_check_embedding_consistency` embeds sample text TWICE through
   the LIVE API and compares — it never consults the index — so a rebuild, which re-embeds through
   that same API, cannot change the verdict. DEGRADED would have rebuilt ~2 minutes on every boot
   forever. The old `rtol=1e-10` also made that verdict a near-certain false positive: on real prod
   content 2 of 5 samples differed by ~1e-4 (cosine 0.999994+), ordinary batched-inference jitter.
"""
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

import document_interrogator as di
from tests.unit.shared_loop import run
from tools.faiss_integrity_monitor import FAISSIntegrityMonitor, check_and_repair_faiss_integrity

pytestmark = pytest.mark.skipif(not getattr(di, "FAISS_AVAILABLE", False),
                                reason="faiss not installed")


def _store():
    work = Path(tempfile.mkdtemp(prefix="si042_"))
    return di.FAISSDocumentStore(storage_dir=str(work / "store"))


class TestTheDamper:

    def test_a_rebuild_that_never_fixes_its_cause_stops_repeating(self):
        """THE POINT. A rebuild reacts to a detector; if it cannot fix what the detector sees, an
        undamped reaction repeats every boot forever. Here the rebuild always 'succeeds' and the
        condition always persists — the damper must cut it off at the configured limit."""
        from utils.config_loader import config_loader
        limit = (config_loader.load_config()['document_interrogator']['integrity']
                 ['auto_rebuild']['max_per_window'])
        store = _store()
        mon = FAISSIntegrityMonitor(store)
        verdict = {'rebuild_required': True, 'issues_found': ['COUNT_MISMATCH'], 'status': 'CORRUPTED'}

        async def never_fixes():
            return {'success': True, 'chunks_processed': 0, 'duration': 0}

        # Count ACTUAL rebuild executions, not the return value: on undamped code the rebuild
        # runs every single time even though it reports False, which is exactly the loop.
        fired = []

        async def counting_rebuild():
            fired.append(1)
            return await never_fixes()

        with patch.object(mon, '_perform_full_rebuild', side_effect=counting_rebuild), \
             patch.object(mon, 'comprehensive_integrity_check',
                          side_effect=lambda *a, **k: dict(verdict)):
            for _ in range(limit + 3):
                run(mon.automatic_rebuild_if_needed(dict(verdict)))

        assert len(fired) <= limit, (
            f"rebuild executed {len(fired)} times against a limit of {limit} — undamped, it "
            f"repeats on every boot forever (~2 min each)")

    def test_a_rebuild_that_CRASHES_still_counts_against_the_damper(self):
        """The attempt is recorded BEFORE the rebuild runs. If it were recorded after, a rebuild
        that throws would never be counted and would retry on every single boot — the exact loop
        the damper exists to prevent, reintroduced through the error path."""
        store = _store()
        mon = FAISSIntegrityMonitor(store)
        verdict = {'rebuild_required': True, 'issues_found': ['COUNT_MISMATCH'], 'status': 'CORRUPTED'}

        async def boom():
            raise RuntimeError("rebuild died halfway")

        before = mon._recent_auto_rebuilds()
        with patch.object(mon, '_perform_full_rebuild', side_effect=boom):
            run(mon.automatic_rebuild_if_needed(dict(verdict)))
        assert mon._recent_auto_rebuilds() == before + 1, (
            "a crashed rebuild was not counted — it would retry forever")

    def test_the_suppressed_branch_reports_why_and_does_not_rebuild(self):
        """Suppression must be loud: silently declining to repair is how a broken index would sit
        unnoticed. It must also not claim a rebuild happened."""
        store = _store()
        mon = FAISSIntegrityMonitor(store)
        mon._ensure_rebuild_log()
        from datetime import datetime
        for _ in range(mon.auto_rebuild_cfg['max_per_window']):
            store.metadata_db.execute(
                "INSERT INTO integrity_rebuilds (started_at, issues, outcome) VALUES (?,?,?)",
                (datetime.now().isoformat(), "['COUNT_MISMATCH']", 'started'))
        store.metadata_db.commit()

        called = []
        with patch.object(mon, '_perform_full_rebuild', side_effect=lambda: called.append(1)):
            out = run(mon.automatic_rebuild_if_needed(
                {'rebuild_required': True, 'issues_found': ['COUNT_MISMATCH'], 'status': 'CORRUPTED'}))
        assert out is False and not called, "suppressed path still attempted a rebuild"


class TestEmbeddingConsistency:

    def test_provider_jitter_is_NOT_called_inconsistent(self):
        """Real measurement on prod content: 2 of 5 samples differed by ~1e-4, cosine 0.999994+.
        Under the old element-wise rtol=1e-10 that was EMBEDDING_INCONSISTENCY on every boot."""
        store = _store()
        mon = FAISSIntegrityMonitor(store)
        store.metadata_db.execute(
            "INSERT INTO chunks (chunk_id, faiss_index, document_path, chunk_index, total_chunks,"
            " content, metadata, created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("c0", 0, "/tmp/d.md", 0, 1, "x" * 80, "{}", "now"))
        store.metadata_db.commit()

        base = np.random.rand(1024).astype(np.float32)
        jittered = (base + np.random.normal(0, 3e-5, 1024)).astype(np.float32)
        calls = [[base], [jittered]]
        with patch.object(store, '_generate_embeddings', side_effect=lambda *_: calls.pop(0)):
            res = run(mon._check_embedding_consistency())
        assert res['consistent'], f"benign jitter flagged as inconsistent: {res}"
        assert res['min_cosine'] > 0.999

    def test_a_GENUINELY_different_embedding_is_still_caught(self):
        """The loosened tolerance must not blind the check. A changed model or mismatched text
        collapses cosine far below the floor, and that must still register."""
        store = _store()
        mon = FAISSIntegrityMonitor(store)
        store.metadata_db.execute(
            "INSERT INTO chunks (chunk_id, faiss_index, document_path, chunk_index, total_chunks,"
            " content, metadata, created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("c0", 0, "/tmp/d.md", 0, 1, "y" * 80, "{}", "now"))
        store.metadata_db.commit()

        calls = [[np.random.rand(1024).astype(np.float32)],
                 [np.random.rand(1024).astype(np.float32)]]
        with patch.object(store, '_generate_embeddings', side_effect=lambda *_: calls.pop(0)):
            res = run(mon._check_embedding_consistency())
        assert not res['consistent'], f"unrelated embeddings passed as consistent: {res}"


class TestDegradedIsSurfaced:

    def test_degraded_is_no_longer_reported_as_healthy(self):
        """`check_and_repair` returned `status in ['HEALTHY','DEGRADED']`, so the caller logged
        'system is healthy' for a DEGRADED index and the finding vanished."""
        store = _store()
        degraded = {'status': 'DEGRADED', 'rebuild_required': False,
                    'issues_found': ['EMBEDDING_INCONSISTENCY'],
                    'metrics': {'embedding_consistency': {'consistent': False, 'min_cosine': 0.4}},
                    'recommendations': ['SCHEDULED_REBUILD_RECOMMENDED']}
        with patch.object(FAISSIntegrityMonitor, 'comprehensive_integrity_check',
                          side_effect=lambda *a, **k: degraded), \
             patch.object(FAISSIntegrityMonitor, 'get_integrity_report', return_value="report"):
            import tools.faiss_integrity_monitor as m
            records = []
            with patch.object(m.logger, 'warning', side_effect=lambda msg, *a: records.append(msg)):
                run(check_and_repair_faiss_integrity(store))
        assert any("DEGRADED" in str(r) for r in records), (
            f"DEGRADED was not surfaced to the operator: {records}")
