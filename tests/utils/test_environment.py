import sys
from pathlib import Path

# Define markers that indicate the project root
PROJECT_ROOT_MARKERS = [
    'user_tools',
    'sandbox_workspace',
    'config',
    'fastapi_server_complete.py'
]

def find_project_root() -> Path:
    """
    Find the project root directory by searching for marker files/directories.

    This function traverses up the directory tree from the current file's location
    until it finds a directory containing a sufficient number of project markers.

    Returns:
        Path: The absolute path to the project root directory.

    Raises:
        FileNotFoundError: If the project root cannot be determined based on markers.
    """
    current_path = Path(__file__).resolve().parent

    for parent in [current_path] + list(current_path.parents):
        markers_found = sum(1 for marker in PROJECT_ROOT_MARKERS if (parent / marker).exists())
        if markers_found >= 3:
            return parent

    raise FileNotFoundError(
        "Project root could not be determined. "
        f"Looked for markers: {PROJECT_ROOT_MARKERS}. "
        "Ensure you are running tests from within the project repository."
    )

def setup_test_environment():
    """
    Configures the Python environment for running tests.

    This function ensures the project root is in sys.path, allowing for
    consistent imports regardless of where the test script is executed from.
    """
    try:
        project_root = find_project_root()
        root_str = str(project_root)

        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    except FileNotFoundError as e:
        print(f"Warning: {e}")
        print("Attempting to proceed, but imports may fail.")

# Allow running this module directly to verify path setup
if __name__ == "__main__":
    print("Testing Test Environment Setup...")
    print("-" * 40)
    
    try:
        root = find_project_root()
        print(f"✅ Project Root Found: {root}")
        
        print("\n🔍 Verifying Markers:")
        for marker in PROJECT_ROOT_MARKERS:
            exists = (root / marker).exists()
            status = "✅" if exists else "❌"
            print(f"   {status} {marker}")
            
        setup_test_environment()
        print("\n✅ Environment Setup Complete.")
        print(f"sys.path[0]: {sys.path[0]}")
        
    except Exception as e:
        print(f"❌ Error: {e}")