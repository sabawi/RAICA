#!/usr/bin/env python3
"""Test Docker permission handling with virtual environments."""

import os
import tempfile
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.coding_agent.validation import DockerSandbox


def test_skip_venv_during_chmod():
    """Test that _ensure_readable_permissions skips venv directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create a mock project structure
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "test_main.py").write_text("import main")

        # Create a mock venv directory with a file we can't chmod
        venv_dir = project_dir / "venv" / "bin"
        venv_dir.mkdir(parents=True)
        python_link = venv_dir / "python3"

        # Create a regular file (simulating venv structure)
        python_link.write_text("#!/usr/bin/env python3")

        # Make it read-only to simulate permission issues
        os.chmod(python_link, 0o444)

        # Initialize DockerSandbox
        sandbox = DockerSandbox(
            project_dir=project_dir,
            language='python',
            timeout=10
        )

        # This should NOT raise PermissionError because venv is skipped
        try:
            sandbox._ensure_readable_permissions()
            print("✅ PASS: _ensure_readable_permissions skipped venv directory")
        except PermissionError as e:
            print(f"❌ FAIL: Got PermissionError even after skipping venv: {e}")
            raise

        # Verify main.py and test_main.py were made readable
        assert os.access(project_dir / "main.py", os.R_OK), "main.py should be readable"
        assert os.access(project_dir / "test_main.py", os.R_OK), "test_main.py should be readable"

        # Verify the venv file still has original permissions (wasn't touched)
        stat_result = os.stat(python_link)
        original_perms = stat_result.st_mode & 0o777
        assert original_perms == 0o444, f"venv file should have original permissions 0o444, got {oct(original_perms)}"

        print("✅ PASS: All checks passed")


def test_skip_multiple_ignored_dirs():
    """Test that all ignored directories are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create various directories that should be skipped
        ignored_dirs = ['venv', '.venv', 'env', '.git', 'node_modules', '__pycache__', '.raica']

        for ignored_dir in ignored_dirs:
            dir_path = project_dir / ignored_dir
            dir_path.mkdir(parents=True)
            # Create a file in each
            test_file = dir_path / "test_file.txt"
            test_file.write_text("test content")
            # Make it read-only
            os.chmod(test_file, 0o444)

        # Create a normal source file
        (project_dir / "source.py").write_text("print('test')")

        # Initialize DockerSandbox
        sandbox = DockerSandbox(
            project_dir=project_dir,
            language='python',
            timeout=10
        )

        # This should NOT raise PermissionError
        try:
            sandbox._ensure_readable_permissions()
            print(f"✅ PASS: Skipped all {len(ignored_dirs)} ignored directories")
        except PermissionError as e:
            print(f"❌ FAIL: Got PermissionError for ignored dirs: {e}")
            raise

        # Verify source file was processed
        assert os.access(project_dir / "source.py", os.R_OK), "source.py should be readable"

        # Verify ignored files still have original permissions
        for ignored_dir in ignored_dirs:
            test_file = project_dir / ignored_dir / "test_file.txt"
            stat_result = os.stat(test_file)
            perms = stat_result.st_mode & 0o777
            assert perms == 0o444, f"{ignored_dir}/test_file.txt should have original permissions"

        print("✅ PASS: All ignored directories were properly skipped")


if __name__ == '__main__':
    print("Testing Docker permission handling with venv directories...\n")
    test_skip_venv_during_chmod()
    print()
    test_skip_multiple_ignored_dirs()
    print("\n✅ All tests passed!")
