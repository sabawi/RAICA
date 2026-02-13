"""
State Verifier - Double Verification for Session State
======================================================

Verifies project state consistency before save and after load.
Prevents silent state drift and data loss.
"""

import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from .git_state_tracker import GitStateTracker

logger = logging.getLogger(__name__)


class StateVerifier:
    """
    Verifies project state consistency before/after operations.
    
    Features:
    - Capture state snapshots (file hashes + git commit)
    - Verify state on restart
    - Detect state drift
    - Block continuation if mismatch detected
    """
    
    def __init__(self, project_dir: Path, git_tracker: GitStateTracker):
        self.project_dir = Path(project_dir)
        self.git_tracker = git_tracker
    
    def capture_state_snapshot(self, files: List[str]) -> Dict[str, Any]:
        """
        Capture current state of specified files.
        
        Args:
            files: List of file paths to snapshot
            
        Returns:
            Snapshot dict with timestamp, git commit, and file hashes
        """
        snapshot = {
            "timestamp": time.time(),
            "git_commit": self.git_tracker.get_current_commit(),
            "files": {}
        }
        
        for file in files:
            file_path = self.project_dir / file
            snapshot["files"][file] = {
                "hash": self.git_tracker.get_file_state_hash(file),
                "size": file_path.stat().st_size if file_path.exists() else 0,
                "exists": file_path.exists()
            }
        
        return snapshot
    
    def verify_state_matches(
        self,
        expected_snapshot: Dict[str, Any],
        current_files: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify current state matches expected snapshot.
        
        Args:
            expected_snapshot: Previously captured snapshot
            current_files: Optional list of files to check (defaults to all from snapshot)
            
        Returns:
            (is_valid, error_message)
        """
        current_commit = self.git_tracker.get_current_commit()
        expected_commit = expected_snapshot.get("git_commit")
        
        # Verify git commit
        if current_commit != expected_commit:
            return False, (
                f"Git state mismatch: "
                f"expected {expected_commit[:8] if expected_commit else 'None'}, "
                f"got {current_commit[:8] if current_commit else 'None'}"
            )
        
        # Verify individual files
        files_to_check = current_files or list(expected_snapshot.get("files", {}).keys())
        
        for file in files_to_check:
            if file not in expected_snapshot.get("files", {}):
                continue
            
            expected_data = expected_snapshot["files"][file]
            current_hash = self.git_tracker.get_file_state_hash(file)
            expected_hash = expected_data["hash"]
            
            if current_hash != expected_hash:
                return False, f"File {file} content mismatch (hash differs)"
            
            # Also check existence
            file_path = self.project_dir / file
            expected_exists = expected_data.get("exists", True)
            current_exists = file_path.exists()
            
            if expected_exists != current_exists:
                return False, f"File {file} existence mismatch"
        
        return True, None
    
    def verify_on_restart(
        self,
        session_state_path: Path,
        strict: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify project state on restart matches session state.
        
        Args:
            session_state_path: Path to session state file
            strict: If True, block on mismatch; if False, just warn
            
        Returns:
            (is_valid, error_message)
        """
        if not session_state_path.exists():
            logger.warning("No session state file to verify")
            return True, None
        
        try:
            session_state = json.loads(session_state_path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.error(f"Failed to load session state: {e}")
            return False, f"Cannot load session state: {e}"
        
        expected_snapshot = session_state.get("state_snapshot")
        
        if not expected_snapshot:
            logger.warning("Session state missing snapshot (legacy session)")
            return True, None
        
        # Verify state
        is_valid, error = self.verify_state_matches(expected_snapshot)
        
        if not is_valid:
            error_msg = f"STATE VERIFICATION FAILED: {error}"
            logger.error(error_msg)
            
            if strict:
                # Print to console for user visibility
                print("\n" + "="*60)
                print("⚠️  PROJECT STATE MISMATCH DETECTED!")
                print("="*60)
                print(f"\n{error}")
                print("\nThis means the project files have changed outside of RAICA")
                print("since the last session.")
                print("\nOptions:")
                print("  1. Restore from last checkpoint:")
                print("     raica restore <checkpoint>")
                print("  2. Commit current state manually:")
                print("     cd <project>")
                print("     git add .")
                print("     git commit -m 'Manual changes'")
                print("  3. Continue anyway (⚠️  risky - may cause unexpected behavior)")
                print("="*60 + "\n")
            
            return False, error_msg
        
        logger.info("✓ State verification passed")
        return True, None
    
    def verify_before_save(
        self,
        modified_files: List[str],
        expected_snapshot: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify state before saving session.
        
        Ensures the files we're about to save match what we expect.
        
        Returns:
            (is_valid, error_message)
        """
        return self.verify_state_matches(expected_snapshot, modified_files)
    
    def generate_state_report(self, snapshot: Dict[str, Any]) -> str:
        """
        Generate human-readable state report.
        
        Args:
            snapshot: State snapshot
            
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("State Snapshot:")
        lines.append(f"  Timestamp: {time.ctime(snapshot['timestamp'])}")
        lines.append(f"  Git Commit: {snapshot.get('git_commit', 'None')[:8]}")
        lines.append(f"  Files Tracked: {len(snapshot.get('files', {}))}")
        
        for file, data in snapshot.get("files", {}).items():
            exists = "✓" if data.get("exists", True) else "✗"
            lines.append(f"    {exists} {file} ({data['size']} bytes, hash: {data['hash'][:8]})")
        
        return "\n".join(lines)
