"""
Git State Tracker - Mandatory Git Workflow for RAICA
=====================================================

Ensures every approved change is committed to git with a changelog.
Provides restore points and prevents state loss.
"""

import subprocess
import hashlib
import time
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class GitStateTracker:
    """
    Manages git-based state tracking for autonomous debugging.
    
    Features:
    - Auto-initialize git repo
    - Mandatory commit after every approved change
    - Tagged commits with session IDs
    - Human-readable commit messages with changelogs
    - File state hashing for verification
    """
    
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.git_dir = project_dir / ".git"
    
    def ensure_git_initialized(self) -> bool:
        """
        Initialize git repo if not already initialized.
        
        Returns:
            True if repo was just initialized, False if already existed
        """
        if self.git_dir.exists():
            logger.debug("Git repository already initialized")
            return False
        
        try:
            # Init repo
            subprocess.run(
                ["git", "init"],
                cwd=self.project_dir,
                check=True,
                capture_output=True
            )
            
            # Configure user (for automated commits)
            subprocess.run(
                ["git", "config", "user.name", "RAICA Agent"],
                cwd=self.project_dir,
                check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "raica@localhost"],
                cwd=self.project_dir,
                check=True
            )
            
            # Create initial commit
            subprocess.run(
                ["git", "add", "."],
                cwd=self.project_dir
            )
            
            result = subprocess.run(
                ["git", "commit", "-m", "[RAICA] Initial project state"],
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("✓ Git repository initialized with initial commit")
            else:
                logger.info("✓ Git repository initialized (no files to commit)")
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to initialize git: {e}")
            return False
    
    def create_checkpoint(
        self,
        modified_files: List[str],
        session_id: str,
        change_type: str,  # "BUG_FIX" | "ENHANCEMENT" | "REFACTOR"
        description: str,
        changelog: str
    ) -> Optional[str]:
        """
        Create a git commit checkpoint after approved changes.
        
        Args:
            modified_files: List of files that were modified
            session_id: Unique session identifier
            change_type: Type of change (BUG_FIX, ENHANCEMENT, etc.)
            description: Brief description of the change
            changelog: Detailed changelog
            
        Returns:
            commit_hash: SHA of the created commit, or None if failed
        """
        if not self.git_dir.exists():
            logger.error("Git not initialized - cannot create checkpoint")
            return None
        
        try:
            # Stage modified files
            for file in modified_files:
                file_path = self.project_dir / file
                if file_path.exists():
                    subprocess.run(
                        ["git", "add", str(file)],
                        cwd=self.project_dir,
                        check=True
                    )
            
            # Create commit message
            commit_msg = self._generate_commit_message(
                session_id, change_type, description, changelog
            )
            
            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.project_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Check if no changes to commit (idempotent)
                if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                    logger.info("No changes to commit (idempotent - already committed)")
                    return self.get_current_commit()
                else:
                    logger.error(f"Git commit failed: {result.stderr}")
                    return None
            
            # Get commit hash
            commit_hash = self.get_current_commit()
            
            # Tag with session ID for easy restore
            tag_name = f"raica-{session_id}-{int(time.time())}"
            subprocess.run(
                ["git", "tag", "-a", tag_name, "-m", description[:100]],
                cwd=self.project_dir,
                capture_output=True
            )
            
            logger.info(f"✓ Created checkpoint: {commit_hash[:8]} (tag: {tag_name})")
            return commit_hash
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create checkpoint: {e}")
            return None
    
    def get_current_commit(self) -> Optional[str]:
        """
        Get current commit hash.
        
        Returns:
            commit_hash or None if not in a git repo
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
    
    def get_file_state_hash(self, file_path: str) -> str:
        """
        Get hash of file content for verification.
        
        Args:
            file_path: Relative path to file
            
        Returns:
            SHA256 hash of file content, or "NOT_EXIST" if file doesn't exist
        """
        full_path = self.project_dir / file_path
        if not full_path.exists():
            return "NOT_EXIST"
        
        try:
            content = full_path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash {file_path}: {e}")
            return "ERROR"
    
    def get_commit_info(self, commit_hash: str) -> Optional[Dict[str, str]]:
        """
        Get information about a specific commit.
        
        Returns:
            Dict with 'hash', 'message', 'author', 'date' or None if invalid
        """
        try:
            # Get commit message
            msg_result = subprocess.run(
                ["git", "log", "--format=%B", "-n", "1", commit_hash],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Get commit metadata
            meta_result = subprocess.run(
                ["git", "log", "--format=%an|%ae|%ai", "-n", "1", commit_hash],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            author, email, date = meta_result.stdout.strip().split("|")
            
            return {
                "hash": commit_hash,
                "message": msg_result.stdout.strip(),
                "author": author,
                "email": email,
                "date": date
            }
        except subprocess.CalledProcessError:
            return None
    
    def _generate_commit_message(
        self,
        session_id: str,
        change_type: str,
        description: str,
        changelog: str
    ) -> str:
        """Generate structured commit message with changelog."""
        # Truncate description to avoid overly long first line
        desc_short = description[:80] + "..." if len(description) > 80 else description
        
        return f"""[RAICA] {change_type}: {desc_short}

Session: {session_id}

CHANGELOG:
{changelog}

Generated by RAICA Autonomous Coding Agent
"""
    
    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        return self.git_dir.exists()
    
    def get_modified_files_since(self, commit_hash: str) -> List[str]:
        """
        Get list of files modified since a specific commit.
        
        Returns:
            List of relative file paths
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", commit_hash, "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
            return files
        except subprocess.CalledProcessError:
            return []

    def get_dirty_files(self) -> List[str]:
        """
        Get list of currently modified (dirty) files in working directory.
        
        Returns:
            List of relative file paths that have uncommitted changes
        """
        # Paths that should never be considered as "our" changes
        FORBIDDEN_PATTERNS = ["venv/", ".venv/", ".git/", "__pycache__/", "node_modules/"]
        
        try:
            # git status --porcelain returns "XY filename"
            # XY status codes: M=modified, A=added, D=deleted, ??=untracked
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            files = []
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                # Extract filename (after status code)
                # handle filenames with spaces (encapsulated in quotes usually, but --porcelain v1 is simple)
                parts = line.strip().split(" ", 1)
                if len(parts) >= 2:
                    filepath = parts[1].strip('"')
                    # Filter out forbidden paths
                    if not any(p in filepath for p in FORBIDDEN_PATTERNS):
                        files.append(filepath)
            return files
        except subprocess.CalledProcessError:
            return []
