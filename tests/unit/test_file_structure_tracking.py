"""
Unit Tests for File Structure Tracking (v2.3)
==============================================

Tests for the enhanced ProjectContext with file structure tracking:
- FileEntry and DirectoryTree dataclasses
- scan_file_structure() method
- Symbol extraction from Python files
- Serialization/deserialization

Tests for DocumentationGenerator:
- Planning doc generation
- Architecture doc generation
- Design doc generation
- README enhancement
"""

import tempfile
import pytest
from pathlib import Path

# Import the classes we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.common.context.project_context import (
    FileEntry,
    DirectoryTree,
    ProjectContext,
)


class TestFileEntry:
    """Tests for FileEntry dataclass."""

    def test_create_file_entry(self):
        """Test creating a FileEntry."""
        entry = FileEntry(
            path="src/main.py",
            file_type="python",
            size=1024,
            symbols=["class MyClass", "def main"],
            imports=["os", "sys"]
        )
        assert entry.path == "src/main.py"
        assert entry.file_type == "python"
        assert entry.size == 1024
        assert len(entry.symbols) == 2
        assert len(entry.imports) == 2

    def test_file_entry_to_dict(self):
        """Test FileEntry serialization."""
        entry = FileEntry(
            path="test.py",
            file_type="python",
            size=512,
            symbols=["def test"],
            imports=["pytest"]
        )
        data = entry.to_dict()
        assert data['path'] == "test.py"
        assert data['file_type'] == "python"
        assert data['size'] == 512

    def test_file_entry_from_dict(self):
        """Test FileEntry deserialization."""
        data = {
            'path': 'module.py',
            'file_type': 'python',
            'size': 2048,
            'symbols': ['class Widget'],
            'imports': ['tkinter'],
            'last_modified': 1234567890.0
        }
        entry = FileEntry.from_dict(data)
        assert entry.path == 'module.py'
        assert entry.file_type == 'python'
        assert entry.size == 2048
        assert entry.last_modified == 1234567890.0


class TestDirectoryTree:
    """Tests for DirectoryTree dataclass."""

    def test_create_directory_tree(self):
        """Test creating a DirectoryTree."""
        tree = DirectoryTree(
            root_name="my_project",
            tree_string="my_project/\n├── src/\n└── README.md",
            file_count=5,
            directory_count=2,
            total_size=10240
        )
        assert tree.root_name == "my_project"
        assert tree.file_count == 5
        assert tree.directory_count == 2

    def test_generate_tree(self):
        """Test generating a tree from a real directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create some files and directories
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "main.py").write_text("print('hello')")
            (tmp_path / "tests").mkdir()
            (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")
            (tmp_path / "README.md").write_text("# Project")
            (tmp_path / "requirements.txt").write_text("pytest")

            tree = DirectoryTree.generate_tree(tmp_path, max_depth=3)

            assert tree.file_count >= 4
            assert tree.directory_count >= 2
            assert "src/" in tree.tree_string
            assert "tests/" in tree.tree_string
            assert "README.md" in tree.tree_string

    def test_tree_excludes_git(self):
        """Test that .git directory is excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create a .git directory (should be excluded)
            (tmp_path / ".git").mkdir()
            (tmp_path / ".git" / "config").write_text("test")
            (tmp_path / "main.py").write_text("print('hello')")

            tree = DirectoryTree.generate_tree(tmp_path)

            assert ".git" not in tree.tree_string
            assert "main.py" in tree.tree_string

    def test_tree_to_dict(self):
        """Test DirectoryTree serialization."""
        tree = DirectoryTree(
            root_name="project",
            tree_string="project/\n└── file.py",
            file_count=1,
            directory_count=0,
            total_size=100,
            scanned_at="2025-01-16T10:00:00"
        )
        data = tree.to_dict()
        assert data['root_name'] == "project"
        assert data['file_count'] == 1
        assert data['scanned_at'] == "2025-01-16T10:00:00"


class TestProjectContextFileStructure:
    """Tests for ProjectContext file structure methods."""

    def test_scan_file_structure(self):
        """Test scanning a project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create a simple project structure
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "main.py").write_text("""
class Calculator:
    def add(self, a, b):
        return a + b

def main():
    calc = Calculator()
    print(calc.add(1, 2))
""")
            (tmp_path / "README.md").write_text("# Calculator Project")
            (tmp_path / "requirements.txt").write_text("pytest>=7.0")

            # Create context and scan
            context = ProjectContext(project_dir=tmp_path)
            context.scan_file_structure(extract_symbols=True, force=True)

            # Verify results
            assert context.directory_tree is not None
            assert context.directory_tree.file_count >= 3
            assert len(context.file_entries) >= 3

            # Check Python symbols were extracted
            main_entry = context.file_entries.get("src/main.py")
            assert main_entry is not None
            assert main_entry.file_type == "python"
            assert any("Calculator" in s for s in main_entry.symbols)
            assert any("main" in s for s in main_entry.symbols)

            # Check key files were loaded
            assert "README.md" in context.key_file_contents
            assert "requirements.txt" in context.key_file_contents

    def test_get_file_structure_context(self):
        """Test getting formatted context for LLM."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            (tmp_path / "app.py").write_text("def hello(): pass")
            (tmp_path / "config.yaml").write_text("key: value")

            context = ProjectContext(project_dir=tmp_path)
            context.scan_file_structure(force=True)

            formatted = context.get_file_structure_context()

            assert "PROJECT FILE STRUCTURE" in formatted
            assert "app.py" in formatted
            assert "python" in formatted.lower()

    def test_needs_rescan(self):
        """Test stale detection."""
        context = ProjectContext()

        # Should need rescan if never scanned
        assert context.needs_rescan() is True

        # Simulate a recent scan
        import time
        context.last_scan_time = time.time()
        assert context.needs_rescan() is False

        # Simulate an old scan
        context.last_scan_time = time.time() - 600  # 10 minutes ago
        assert context.needs_rescan() is True

    def test_persistence(self):
        """Test that file structure is persisted correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            (tmp_path / "module.py").write_text("class Test: pass")

            # Create and scan
            context1 = ProjectContext(project_dir=tmp_path)
            context1.scan_file_structure(force=True)
            context1.save()

            # Load in new context
            context2 = ProjectContext(project_dir=tmp_path)
            loaded = context2.load()

            assert loaded is True
            assert context2.directory_tree is not None
            assert len(context2.file_entries) > 0
            assert context2.last_scan_time is not None


class TestDocumentationGenerator:
    """Tests for DocumentationGenerator."""

    def test_generate_planning(self):
        """Test PLANNING.md generation."""
        from agents.coding_agent.hooks.doc_generator import DocumentationGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            context = {
                'original_request': 'Create a calculator app',
                'refined_requirements': [
                    'R1: Support addition',
                    'R2: Support subtraction'
                ],
                'implementation_plan': [
                    'Step 1: Create calculator class',
                    'Step 2: Add operations'
                ]
            }

            generator = DocumentationGenerator(tmp_path, context)
            success = generator._generate_planning()

            assert success is True
            planning_path = tmp_path / "docs" / "PLANNING.md"
            assert planning_path.exists()

            content = planning_path.read_text()
            assert "calculator" in content.lower()
            assert "R1" in content
            assert "Step 1" in content

    def test_generate_architecture(self):
        """Test ARCHITECTURE.md generation."""
        from agents.coding_agent.hooks.doc_generator import DocumentationGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            context = {
                'architecture_decisions': {
                    'type': 'modular',
                    'patterns': ['MVC', 'Factory'],
                    'data_flow': 'Input -> Process -> Output'
                },
                'components': [
                    {'name': 'Calculator', 'purpose': 'Core calculations'},
                    {'name': 'UI', 'purpose': 'User interface'}
                ]
            }

            generator = DocumentationGenerator(tmp_path, context)
            success = generator._generate_architecture()

            assert success is True
            arch_path = tmp_path / "docs" / "ARCHITECTURE.md"
            assert arch_path.exists()

            content = arch_path.read_text()
            assert "modular" in content.lower()
            assert "Calculator" in content
            assert "MVC" in content

    def test_generate_all(self):
        """Test generating all documentation."""
        from agents.coding_agent.hooks.doc_generator import DocumentationGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            context = {
                'original_request': 'Build a web app',
                'refined_requirements': ['R1: Be fast'],
                'implementation_plan': ['Step 1: Build it'],
                'architecture_decisions': {'type': 'layered'},
                'components': [{'name': 'Server', 'purpose': 'Handle requests'}],
                'file_specifications': [{'path': 'app.py', 'purpose': 'Main app'}],
                'generated_files': {'app.py': 'print("hi")'}
            }

            generator = DocumentationGenerator(tmp_path, context)
            results = generator.generate_all()

            # All should succeed
            assert results['PLANNING.md'] is True
            assert results['ARCHITECTURE.md'] is True
            assert results['DESIGN.md'] is True
            assert results['README.md'] is True

            # Check all files exist
            assert (tmp_path / "docs" / "PLANNING.md").exists()
            assert (tmp_path / "docs" / "ARCHITECTURE.md").exists()
            assert (tmp_path / "docs" / "DESIGN.md").exists()
            assert (tmp_path / "README.md").exists()

    def test_enhance_readme_adds_continuation(self):
        """Test that README enhancement adds continuation section."""
        from agents.coding_agent.hooks.doc_generator import DocumentationGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create initial README
            (tmp_path / "README.md").write_text("# My Project\n\nA simple project.")

            generator = DocumentationGenerator(tmp_path, {'original_request': 'test'})

            # Create docs directory so continuation section references valid files
            (tmp_path / "docs").mkdir()
            (tmp_path / "docs" / "PLANNING.md").write_text("# Planning")

            success = generator._enhance_readme()
            assert success is True

            content = (tmp_path / "README.md").read_text()
            assert "How to Continue Development" in content
            assert "RAICA" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
