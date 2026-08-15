#!/usr/bin/env python3
"""
FAISS-SQLite Integrity Monitor
Detects corruption and automatically rebuilds indices in production
"""

import asyncio
import logging
import json
import hashlib
import time
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import sqlite3
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class FAISSIntegrityMonitor:
    """
    Production-grade integrity monitoring for FAISS-SQLite synchronization
    """
    
    def __init__(self, document_store):
        self.store = document_store
        self.metadata_db = document_store.metadata_db
        self.faiss_index = document_store.faiss_index
        # SI-042 — thresholds are configuration, not literals. Fail fast if absent.
        from utils.config_loader import config_loader
        cfg = (config_loader.load_config().get('document_interrogator', {}) or {}).get('integrity')
        if not cfg:
            raise ValueError("Missing config: document_interrogator.integrity in llm_config.yaml")
        self.corruption_threshold = cfg['corruption_threshold']
        self.min_consistency_cosine = cfg['embedding_consistency_min_cosine']
        self.auto_rebuild_cfg = cfg['auto_rebuild']
        self.max_sample_size = 100  # Sample size for integrity checks
        
    async def comprehensive_integrity_check(self) -> Dict[str, any]:
        """
        Comprehensive integrity check between FAISS and SQLite
        Returns detailed status and corruption indicators
        """
        start_time = time.time()
        logger.info("🔍 Starting comprehensive FAISS-SQLite integrity check")
        
        result = {
            'timestamp': time.time(),
            'status': 'HEALTHY',
            'issues_found': [],
            'metrics': {},
            'recommendations': [],
            'corruption_detected': False,
            'rebuild_required': False
        }
        
        try:
            # Check 1: Basic count synchronization
            count_check = await self._check_count_synchronization()
            result['metrics']['count_sync'] = count_check
            
            if not count_check['synchronized']:
                result['issues_found'].append('COUNT_MISMATCH')
                result['status'] = 'CORRUPTED'
                result['corruption_detected'] = True
                
            # Check 2: Index range validation
            range_check = await self._check_index_range_validity()
            result['metrics']['range_validity'] = range_check
            
            if not range_check['valid']:
                result['issues_found'].append('INDEX_RANGE_INVALID')
                result['status'] = 'CORRUPTED'
                result['corruption_detected'] = True
                
            # Check 3: Sample-based lookup verification
            lookup_check = await self._check_sample_lookup_integrity()
            result['metrics']['lookup_integrity'] = lookup_check
            
            if lookup_check['corruption_rate'] > self.corruption_threshold:
                result['issues_found'].append('LOOKUP_CORRUPTION')
                result['status'] = 'CORRUPTED'
                result['corruption_detected'] = True
                
            # Check 4: Embedding consistency validation
            if result['status'] != 'CORRUPTED':  # Only if basic checks pass
                embedding_check = await self._check_embedding_consistency()
                result['metrics']['embedding_consistency'] = embedding_check
                
                if not embedding_check['consistent']:
                    result['issues_found'].append('EMBEDDING_INCONSISTENCY')
                    result['status'] = 'DEGRADED'
            
            # Determine if rebuild is required
            if result['corruption_detected']:
                result['rebuild_required'] = True
                result['recommendations'].append('IMMEDIATE_REBUILD_REQUIRED')
                
            elif result['status'] == 'DEGRADED':
                result['recommendations'].append('SCHEDULED_REBUILD_RECOMMENDED')
                
            else:
                result['recommendations'].append('NO_ACTION_REQUIRED')
                
        except Exception as e:
            logger.error(f"❌ Integrity check failed: {e}")
            result['status'] = 'ERROR'
            result['error'] = str(e)
            result['rebuild_required'] = True
            
        result['check_duration'] = time.time() - start_time
        logger.info(f"✅ Integrity check complete: {result['status']} ({result['check_duration']:.2f}s)")
        
        return result
    
    async def _check_count_synchronization(self) -> Dict[str, any]:
        """Check if FAISS and SQLite have matching record counts"""
        cursor = self.metadata_db.cursor()
        
        # Get SQLite counts
        cursor.execute("SELECT COUNT(*) FROM chunks")
        sqlite_total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE faiss_index IS NOT NULL")
        sqlite_indexed = cursor.fetchone()[0]
        
        # Get FAISS count
        faiss_total = self.faiss_index.ntotal
        
        # Calculate count mismatch percentage (use max to avoid division by zero)
        total_count = max(sqlite_indexed, faiss_total, 1)
        mismatch_percentage = abs(sqlite_indexed - faiss_total) / total_count
        
        # Consider synchronized if mismatch is within tolerance (5%)
        synchronized = mismatch_percentage <= self.corruption_threshold
        
        return {
            'sqlite_total_chunks': sqlite_total,
            'sqlite_indexed_chunks': sqlite_indexed,
            'faiss_total_vectors': faiss_total,
            'synchronized': synchronized,
            'mismatch_percentage': mismatch_percentage,
            'missing_in_faiss': max(0, sqlite_indexed - faiss_total),
            'orphaned_in_faiss': max(0, faiss_total - sqlite_indexed)
        }
    
    async def _check_index_range_validity(self) -> Dict[str, any]:
        """Verify FAISS indices in SQLite are within valid range"""
        cursor = self.metadata_db.cursor()
        
        cursor.execute("""
            SELECT MIN(faiss_index), MAX(faiss_index), COUNT(DISTINCT faiss_index)
            FROM chunks WHERE faiss_index IS NOT NULL
        """)
        min_idx, max_idx, unique_count = cursor.fetchone()

        # SI-043 — with IndexIDMap2 a chunk's faiss_index is an ID, not a POSITION, so
        # "< ntotal" is meaningless: ids are stable and arbitrary, and after removals they are
        # deliberately non-contiguous. Validity is now membership — is each id actually present?
        if hasattr(self.faiss_index, "id_map"):
            import faiss as _faiss
            live_ids = set(int(i) for i in _faiss.vector_to_array(self.faiss_index.id_map))
            rows = cursor.execute(
                "SELECT faiss_index FROM chunks WHERE faiss_index IS NOT NULL").fetchall()
            invalid_indices = sum(1 for (i,) in rows if int(i) not in live_ids)
            return {
                'min_index': min_idx,
                'max_index': max_idx,
                'unique_indices': unique_count,
                'id_mapped': True,
                'live_ids': len(live_ids),
                'invalid_indices_count': invalid_indices,
                'valid': invalid_indices == 0
            }

        # Legacy positional index (pre-migration): ids ARE positions.
        faiss_max_valid = self.faiss_index.ntotal - 1
        cursor.execute("""
            SELECT COUNT(*) FROM chunks 
            WHERE faiss_index IS NOT NULL AND faiss_index >= ?
        """, (self.faiss_index.ntotal,))
        invalid_indices = cursor.fetchone()[0]
        
        return {
            'min_index': min_idx,
            'max_index': max_idx,
            'unique_indices': unique_count,
            'id_mapped': False,
            'faiss_max_valid': faiss_max_valid,
            'invalid_indices_count': invalid_indices,
            'valid': invalid_indices == 0 and (max_idx is None or max_idx <= faiss_max_valid)
        }
    
    async def _check_sample_lookup_integrity(self) -> Dict[str, any]:
        """Sample random FAISS indices and verify SQLite lookups work"""
        cursor = self.metadata_db.cursor()
        
        # Get sample of FAISS indices from SQLite
        cursor.execute("""
            SELECT faiss_index, chunk_id FROM chunks 
            WHERE faiss_index IS NOT NULL 
            ORDER BY RANDOM() 
            LIMIT ?
        """, (self.max_sample_size,))
        
        sample_indices = cursor.fetchall()
        
        if not sample_indices:
            return {'corruption_rate': 1.0, 'sample_size': 0, 'lookups_failed': 0}
        
        failed_lookups = 0
        
        for faiss_idx, expected_chunk_id in sample_indices:
            # Verify reverse lookup works
            cursor.execute("""
                SELECT chunk_id FROM chunks WHERE faiss_index = ?
            """, (faiss_idx,))
            
            result = cursor.fetchone()
            if not result or result[0] != expected_chunk_id:
                failed_lookups += 1
        
        corruption_rate = failed_lookups / len(sample_indices)
        
        return {
            'sample_size': len(sample_indices),
            'lookups_failed': failed_lookups,
            'corruption_rate': corruption_rate,
            'status': 'HEALTHY' if corruption_rate == 0 else 'CORRUPTED'
        }
    
    async def _check_embedding_consistency(self) -> Dict[str, any]:
        """Verify embedding generation produces consistent results"""
        cursor = self.metadata_db.cursor()
        
        # Get a small sample for embedding consistency check
        cursor.execute("""
            SELECT content FROM chunks 
            WHERE LENGTH(content) > 50 
            ORDER BY RANDOM() 
            LIMIT 5
        """)
        
        sample_content = [row[0] for row in cursor.fetchall()]
        
        if not sample_content:
            return {'consistent': True, 'sample_size': 0}
        
        try:
            # Generate embeddings twice and compare
            embeddings1 = await self.store._generate_embeddings(sample_content)
            await asyncio.sleep(0.1)  # Small delay
            embeddings2 = await self.store._generate_embeddings(sample_content)
            
            if not embeddings1 or not embeddings2:
                return {'consistent': False, 'error': 'Embedding generation failed'}
            
            # SI-042 — judge SEMANTIC equivalence, not bit equality.
            # The old test was `np.allclose(rtol=1e-10)`, which is far tighter than float32
            # carries and much tighter than a remote embedding API guarantees. Measured on real
            # prod content (text-embedding-3-small): 3 of 5 samples bit-identical, 2 differing by
            # ~1e-4 with cosine 0.999994+ — ordinary batched-inference jitter between replicas,
            # semantically identical for retrieval. That flagged EMBEDDING_INCONSISTENCY on every
            # boot, and because a rebuild re-embeds through the SAME API it could never clear it.
            # Cosine still catches what actually matters: a changed model, a wrong dimension, or
            # mismatched text all collapse the similarity far below this floor.
            worst_cosine, dimension_mismatch = 1.0, False
            for emb1, emb2 in zip(embeddings1, embeddings2):
                a = np.asarray(emb1, dtype=np.float64)
                b = np.asarray(emb2, dtype=np.float64)
                if a.shape != b.shape:
                    dimension_mismatch = True
                    worst_cosine = 0.0
                    break
                denom = float(np.linalg.norm(a) * np.linalg.norm(b))
                cos = float(a @ b / denom) if denom else 0.0
                worst_cosine = min(worst_cosine, cos)

            return {
                'consistent': (not dimension_mismatch) and worst_cosine >= self.min_consistency_cosine,
                'min_cosine': round(worst_cosine, 8),
                'min_cosine_required': self.min_consistency_cosine,
                'dimension_mismatch': dimension_mismatch,
                'sample_size': len(sample_content),
                'embedding_dimension': len(embeddings1[0]) if embeddings1 else 0
            }
            
        except Exception as e:
            return {'consistent': False, 'error': str(e)}
    
    def _record_rebuild_outcome(self, outcome: str):
        """Stamp the most recent attempt with what it achieved — evidence for the damper."""
        try:
            self.metadata_db.execute(
                "UPDATE integrity_rebuilds SET outcome = ? WHERE id = (SELECT MAX(id) FROM "
                "integrity_rebuilds)", (outcome,))
            self.metadata_db.commit()
        except Exception as e:  # noqa: BLE001 — bookkeeping must never fail a rebuild
            logger.debug(f"could not record rebuild outcome: {e}")

    def _ensure_rebuild_log(self):
        """Persistent record of automatic rebuilds — the damper's memory (SI-042)."""
        self.metadata_db.execute("""
            CREATE TABLE IF NOT EXISTS integrity_rebuilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                issues TEXT,
                outcome TEXT
            )
        """)
        self.metadata_db.commit()

    def _recent_auto_rebuilds(self) -> int:
        """How many automatic rebuilds started inside the configured window."""
        self._ensure_rebuild_log()
        window_hours = self.auto_rebuild_cfg['window_hours']
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        row = self.metadata_db.execute(
            "SELECT COUNT(*) FROM integrity_rebuilds WHERE started_at >= ?", (cutoff,)).fetchone()
        return int(row[0]) if row else 0

    async def automatic_rebuild_if_needed(self, integrity_result: Dict[str, any]) -> bool:
        """
        Automatically rebuild FAISS index if corruption is detected
        Returns True if rebuild was performed
        """
        if not integrity_result.get('rebuild_required', False):
            logger.info(f"✅ No rebuild required (status: {integrity_result.get('status')})")
            return False

        # ── THE DAMPER (SI-042) ────────────────────────────────────────────────────────
        # A rebuild is a REACTION to a detected condition, and a reaction that cannot fix
        # its trigger repeats forever: detect → rebuild (~2 min) → detect again → rebuild…
        # on every boot. THIS IS THE LINE THAT MAKES CYCLE N+1 IMPOSSIBLE — once the window
        # is full the branch cannot re-fire, whatever the detector says, until a human acts
        # or the window rolls off.
        recent = self._recent_auto_rebuilds()
        limit = self.auto_rebuild_cfg['max_per_window']
        window = self.auto_rebuild_cfg['window_hours']
        if recent >= limit:
            logger.error(
                f"🛑 AUTOMATIC REBUILD SUPPRESSED — {recent} rebuild(s) already in the last "
                f"{window}h (limit {limit}). Repeated rebuilds mean the rebuild is NOT fixing "
                f"the cause: {integrity_result['issues_found']}. Investigate before forcing "
                f"another; search still works on the current index.")
            return False

        # Recorded BEFORE the attempt: a rebuild that crashes mid-way must still count
        # against the damper, or a crashing rebuild would retry on every boot indefinitely.
        self._ensure_rebuild_log()
        self.metadata_db.execute(
            "INSERT INTO integrity_rebuilds (started_at, issues, outcome) VALUES (?, ?, ?)",
            (datetime.now().isoformat(), str(integrity_result.get('issues_found')), 'started'))
        self.metadata_db.commit()

        logger.warning(f"🚨 CORRUPTION DETECTED - Starting automatic rebuild "
                       f"({recent + 1}/{limit} within {window}h)")
        logger.warning(f"Issues found: {integrity_result['issues_found']}")
        
        try:
            rebuild_result = await self._perform_full_rebuild()
            
            if rebuild_result['success']:
                logger.info("✅ Automatic rebuild completed successfully")
                
                # Verify rebuild worked
                post_rebuild_check = await self.comprehensive_integrity_check()
                self._record_rebuild_outcome(post_rebuild_check['status'])
                if post_rebuild_check['status'] == 'HEALTHY':
                    logger.info("✅ Post-rebuild integrity check passed")
                    return True
                else:
                    logger.error("❌ Post-rebuild integrity check failed - manual intervention required")
                    return False
            else:
                logger.error(f"❌ Automatic rebuild failed: {rebuild_result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Critical error during automatic rebuild: {e}")
            return False
    
    async def _perform_full_rebuild(self) -> Dict[str, any]:
        """Perform complete FAISS index rebuild from SQLite data"""
        start_time = time.time()
        logger.info("🔄 Starting full FAISS index rebuild")
        
        try:
            # Step 1: Clear existing FAISS index
            logger.info("🧹 Clearing existing FAISS index")
            self.faiss_index.reset()
            
            # Step 2: Get all chunks needing indexing
            cursor = self.metadata_db.cursor()
            cursor.execute("""
                SELECT chunk_id, content 
                FROM chunks 
                ORDER BY chunk_id
            """)
            
            all_chunks = cursor.fetchall()
            total_chunks = len(all_chunks)
            
            if total_chunks == 0:
                return {'success': True, 'chunks_processed': 0, 'duration': 0}
            
            logger.info(f"📊 Rebuilding index for {total_chunks} chunks")
            
            # Step 3: Process in batches
            batch_size = 50  # Smaller batches for stability
            processed = 0
            
            for i in range(0, total_chunks, batch_size):
                batch = all_chunks[i:i + batch_size]
                batch_content = [chunk[1] for chunk in batch]
                
                # Generate embeddings
                embeddings = await self.store._generate_embeddings(batch_content)
                
                if not embeddings or len(embeddings) != len(batch):
                    raise Exception(f"Embedding generation failed for batch {i//batch_size + 1}")
                
                # Add to FAISS index. SI-043 — keep each chunk's EXISTING id so the rebuild
                # does not renumber the whole table; with IndexIDMap2 ids need not be
                # contiguous, and rewriting them would invalidate every row mid-rebuild.
                embeddings_array = np.array(embeddings).astype('float32')
                if hasattr(self.faiss_index, "id_map"):
                    batch_ids = []
                    for chunk_id, _content in batch:
                        row = cursor.execute(
                            "SELECT faiss_index FROM chunks WHERE chunk_id = ?",
                            (chunk_id,)).fetchone()
                        batch_ids.append(int(row[0]) if row and row[0] is not None else -1)
                    if any(i < 0 for i in batch_ids):   # assign ids to any that lack one
                        next_id = (cursor.execute(
                            "SELECT COALESCE(MAX(faiss_index), -1) FROM chunks").fetchone()[0]) + 1
                        for k, i in enumerate(batch_ids):
                            if i < 0:
                                batch_ids[k] = next_id
                                cursor.execute("UPDATE chunks SET faiss_index = ? WHERE chunk_id = ?",
                                               (next_id, batch[k][0]))
                                next_id += 1
                    self.faiss_index.add_with_ids(embeddings_array,
                                                  np.array(batch_ids, dtype='int64'))
                else:
                    start_idx = self.faiss_index.ntotal
                    self.faiss_index.add(embeddings_array)
                    for j, (chunk_id, content) in enumerate(batch):
                        cursor.execute("""
                            UPDATE chunks 
                            SET faiss_index = ? 
                            WHERE chunk_id = ?
                        """, (start_idx + j, chunk_id))
                
                self.metadata_db.commit()
                processed += len(batch)
                
                if processed % 200 == 0:  # Progress logging
                    logger.info(f"📊 Rebuild progress: {processed}/{total_chunks} ({100*processed/total_chunks:.1f}%)")
            
            # Step 4: Save the rebuilt index
            await self.store._save_index()
            
            duration = time.time() - start_time
            logger.info(f"✅ Rebuild complete: {processed} chunks in {duration:.2f}s")
            
            return {
                'success': True,
                'chunks_processed': processed,
                'final_index_size': self.faiss_index.ntotal,
                'duration': duration
            }
            
        except Exception as e:
            logger.error(f"❌ Rebuild failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_integrity_report(self, check_result: Dict[str, any]) -> str:
        """Generate human-readable integrity report"""
        status_emoji = {
            'HEALTHY': '✅',
            'DEGRADED': '⚠️',
            'CORRUPTED': '🚨',
            'ERROR': '❌'
        }
        
        emoji = status_emoji.get(check_result['status'], '❓')
        
        report = [
            f"{emoji} FAISS-SQLite Integrity Report",
            "=" * 40,
            f"Status: {check_result['status']}",
            f"Check Duration: {check_result.get('check_duration', 0):.2f}s",
            ""
        ]
        
        if check_result.get('metrics'):
            report.append("📊 Metrics:")
            for check_name, metrics in check_result['metrics'].items():
                report.append(f"  {check_name}: {metrics}")
            report.append("")
        
        if check_result.get('issues_found'):
            report.append("🚨 Issues Found:")
            for issue in check_result['issues_found']:
                report.append(f"  - {issue}")
            report.append("")
        
        if check_result.get('recommendations'):
            report.append("💡 Recommendations:")
            for rec in check_result['recommendations']:
                report.append(f"  - {rec}")
        
        return "\\n".join(report)

# Integration function for document_interrogator.py
async def check_and_repair_faiss_integrity(document_store) -> bool:
    """
    Main function to check and repair FAISS integrity
    Returns True if system is healthy after check/repair
    """
    monitor = FAISSIntegrityMonitor(document_store)
    
    # Run comprehensive check
    integrity_result = await monitor.comprehensive_integrity_check()
    
    # Log the report
    report = monitor.get_integrity_report(integrity_result)
    logger.info(f"\\n{report}")
    
    # Auto-repair if needed
    if integrity_result.get('rebuild_required', False):
        rebuild_success = await monitor.automatic_rebuild_if_needed(integrity_result)
        return rebuild_success

    # SI-042 — DEGRADED used to be folded silently into "healthy" and its
    # SCHEDULED_REBUILD_RECOMMENDED read by nobody, so a real finding was detected on every
    # boot and actioned never. It is surfaced here instead. It deliberately does NOT trigger a
    # rebuild: the only DEGRADED source is the embedding-consistency check, which compares two
    # LIVE API calls and never consults the index — a rebuild re-embeds through that same API
    # and so cannot change the outcome. Reacting to it would be an undamped loop, not a fix.
    if integrity_result['status'] == 'DEGRADED':
        logger.warning(
            f"⚠️ FAISS integrity DEGRADED — {integrity_result['issues_found']}. "
            f"Search still works; the index is not corrupt. This is NOT auto-repaired: a "
            f"rebuild cannot address it. Metrics: "
            f"{integrity_result['metrics'].get('embedding_consistency')}")
        return True

    return integrity_result['status'] == 'HEALTHY'