"""
Restore Manager - Checkpoint Recovery for RAICA
===============================================

Manages restoration of project to previous checkpoints.
Provides 'raica restore' command functionality.
"""

import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .git_state_tracker import GitStateTracker

logger = logging.getLogger(__name__)


class RestoreManager:
    """
    Manages restoration of project to previous checkpoints.
    
    Features:
    - List all RAICA checkpoints
    - Restore to specific checkpoint (by tag or commit hash)
    - Show changelog for restore point
    - Verify restore point exists before attempting
    """
    
    def __init__(self, project_dir: Path, git_tracker: GitStateTracker):
        self.project_dir = Path(project_dir)
        self.git_tracker = git_tracker
    
    def list_checkpoints(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        List all RAICA checkpoints.
        
        Args:
            limit: Maximum number of checkpoints to return (newest first)
            
        Returns:
            List of checkpoint dicts with 'tag', 'commit', 'message', 'date'
        """
        if not self.git_tracker.is_git_repo():
            logger.warning("Not a git repository")
            return []
        
        try:
            # Get all RAICA tags
            result = subprocess.run(
                ["git", "tag", "-l", "raica-*", "--sort=-creatordate"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]
            tags = tags[:limit]  # Limit results
            
            checkpoints = []
            
            for tag in tags:
                # Get commit hash for tag
                commit_result = subprocess.run(
                    ["git", "rev-list", "-n", "1", tag],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True
                )
                
                if commit_result.returncode != 0:
                    continue
                
                commit_hash = commit_result.stdout.strip()
                
                # Get commit info
                commit_info = self.git_tracker.get_commit_info(commit_hash)
                
                if commit_info:
                    checkpoints.append({
                        "tag": tag,
                        "commit": commit_hash[:8],
                        "commit_full": commit_hash,
                        "message": commit_info["message"],
                        "date": commit_info["date"],
                        "author": commit_info["author"]
                    })
            
            return checkpoints
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to list checkpoints: {e}")
            return []
    
    def restore_to_checkpoint(
        self,
        identifier: str,
        force: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Restore project to a specific checkpoint.
        
        Args:
            identifier: Tag name or commit hash
            force: If True, discard uncommitted changes
            
        Returns:
            (success, error_message)
        """
        if not self.git_tracker.is_git_repo():
            return False, "Not a git repository"
        
        try:
            # Verify identifier exists
            verify_result = subprocess.run(
                ["git", "rev-parse", identifier],
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            if verify_result.returncode != 0:
                return False, f"Invalid identifier: {identifier} not found"
            
            commit_hash = verify_result.stdout.strip()
            
            # Check for uncommitted changes
            if not force:
                status_result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True
                )
                
                if status_result.stdout.strip():
                    return False, (
                        "Uncommitted changes detected. "
                        "Commit them first or use --force to discard"
                    )
            
            # Reset to checkpoint
            reset_cmd = ["git", "reset", "--hard", identifier]
            reset_result = subprocess.run(
                reset_cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            if reset_result.returncode != 0:
                return False, f"Git reset failed: {reset_result.stderr}"
            
            logger.info(f"✓ Restored to checkpoint: {identifier} ({commit_hash[:8]})")
            return True, None
            
        except subprocess.CalledProcessError as e:
            return False, f"Restore failed: {e}"
    
    def get_checkpoint_info(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a checkpoint.
        
        Args:
            identifier: Tag name or commit hash
            
        Returns:
            Dict with checkpoint info or None if not found
        """
        try:
            # Resolve to commit hash
            resolve_result = subprocess.run(
                ["git", "rev-parse", identifier],
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            if resolve_result.returncode != 0:
                return None
            
            commit_hash = resolve_result.stdout.strip()
            
            # Get commit info
            commit_info = self.git_tracker.get_commit_info(commit_hash)
            
            if not commit_info:
                return None
            
            # Get files changed in this commit
            files_result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            files_changed = [f.strip() for f in files_result.stdout.splitlines() if f.strip()]
            
            return {
                "identifier": identifier,
                "commit": commit_hash[:8],
                "commit_full": commit_hash,
                "message": commit_info["message"],
                "date": commit_info["date"],
                "author": commit_info["author"],
                "files_changed": files_changed
            }
            
        except subprocess.CalledProcessError:
            return None
    
    def find_checkpoint_by_description(self, search_term: str) -> List[Dict[str, Any]]:
        """
        Find checkpoints matching a search term in their description.
        
        Args:
            search_term: Text to search for in commit messages
            
        Returns:
            List of matching checkpoints
        """
        all_checkpoints = self.list_checkpoints(limit=100)
        
        matches = []
        search_lower = search_term.lower()
        
        for cp in all_checkpoints:
            if search_lower in cp["message"].lower():
                matches.append(cp)
        
        return matches
