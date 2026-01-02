"""
State Manager
=============

Handles persistence of agent state to disk, allowing recovery from crashes
or resuming sessions.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class StateManager:
    """Manages saving and loading of agent state."""

    STATE_FILENAME = "raica_state.json"

    @staticmethod
    def save_state(project_path: Path, state_data: Dict[str, Any]) -> bool:
        """
        Save state to the project directory.
        
        Args:
            project_path: Directory to save state file in
            state_data: Dictionary containing state to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure timestamp is added
            state_data['_meta'] = {
                'timestamp': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            file_path = project_path / StateManager.STATE_FILENAME
            
            # Write to temporary file first to prevent corruption
            temp_path = file_path.with_suffix('.tmp')
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, default=str)
                
            # atomic rename
            temp_path.replace(file_path)
            
            logger.info(f"State saved to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False

    @staticmethod
    def load_state(project_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load state from the project directory.
        
        Args:
            project_path: Directory to load state from
            
        Returns:
            State dictionary or None if not found/error
        """
        file_path = project_path / StateManager.STATE_FILENAME
        
        if not file_path.exists():
            return None
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None
