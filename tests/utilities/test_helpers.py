import sys
import os
from pathlib import Path

def get_project_root(marker_files=None, marker_dirs=None):
    """
    Determines the project root by traversing up from the current file
    until a known marker file or directory is found.
    """
    if marker_files is None:
        marker_files = []
    if marker_dirs is None:
        # Use the directories identified in the original workflow analysis
        marker_dirs = ['user_tools', 'sandbox_workspace', 'agents']

    # Start from the directory of the file calling this function
    current_path = Path(__file__).resolve().parent

    # Traverse up
    for parent in [current_path] + list(current_path.parents):
        # Check if any marker directory exists in the current parent
        if any((parent / d).exists() for d in marker_dirs):
            return parent
        # Check if any marker file exists
        if any((parent / f).exists() for f in marker_files):
            return parent

    # Fallback if no markers found
    raise FileNotFoundError("Project root could not be determined using markers.")

def add_to_path(relative_path=None):
    """
    Adds a specific path relative to the project root to sys.path.
    If relative_path is None, adds the project root.
    """
    root = get_project_root()
    
    if relative_path:
        target_path = (root / relative_path).resolve()
    else:
        target_path = root

    path_str = str(target_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
        # Optional: Debug print
        # print(f"[Test Helpers] Added to sys.path: {path_str}")

def setup_test_paths():
    """
    Main entry point for test files.
    Ensures the project root is in the path.
    """
    add_to_path()