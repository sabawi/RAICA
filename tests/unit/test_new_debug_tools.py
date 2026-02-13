import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from agents.coding_agent.services.debug_toolkit import DebugToolkit, ToolResult

class TestNewDebugTools(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path('/tmp/fake_project')
        self.toolkit = DebugToolkit(self.project_dir)
        # Mock backup dir creation
        self.toolkit._backup_dir = MagicMock()
        self.toolkit._backup_dir.exists.return_value = True

    @patch('pathlib.Path.rglob')
    def test_analyze_project(self, mock_rglob):
        # Setup mocks
        file1 = MagicMock()
        file1.name = 'script.py'
        file1.suffix = '.py'
        file1.is_file.return_value = True
        file1.stat.return_value.st_size = 100
        
        file2 = MagicMock()
        file2.name = 'requirements.txt'
        file2.suffix = '.txt'
        file2.is_file.return_value = True
        file2.stat.return_value.st_size = 100
        
        mock_rglob.return_value = [file1, file2]
        
        result = self.toolkit.analyze_project()
        
        self.assertTrue(result.success)
        self.assertEqual(result.result['total_files'], 2)
        self.assertEqual(result.result['total_size_bytes'], 200)
        self.assertIn('requirements.txt', result.result['vital_files_found'])
        self.assertEqual(result.result['extensions']['.py'], 1)

    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_check_lint(self, mock_exists, mock_run):
        mock_exists.return_value = True
        
        # Mock flake8 check
        mock_run.side_effect = [
            MagicMock(returncode=0), # flake8 --version
            MagicMock(returncode=0, stdout="No issues", stderr="") # lint run
        ]
        
        result = self.toolkit.check_lint("test.py")
        
        self.assertTrue(result.success)
        self.assertEqual(result.result['linter'], 'flake8')
        mock_run.assert_called()

    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_format_file(self, mock_exists, mock_run):
        mock_exists.return_value = True
        
        # Mock black check
        mock_run.side_effect = [
            MagicMock(returncode=0), # black --version
            MagicMock(returncode=0, stdout="All done", stderr="") # format run
        ]
        
        result = self.toolkit.format_file("test.py")
        
        self.assertTrue(result.success)
        self.assertIn("Formatted test.py using black", result.result)

    @patch('pathlib.Path.rglob')
    @patch('pkg_resources.working_set', new_callable=set)
    def test_dependency_check(self, mock_working_set, mock_rglob):
        # Setup mocks
        mock_file = MagicMock()
        mock_file.read_text.return_value = "import requests\nimport os\nimport unknown_pkg"
        mock_rglob.return_value = [mock_file]
        
        # Mock installed packages
        pkg = MagicMock()
        pkg.key = 'requests'
        mock_working_set.add(pkg)
        
        result = self.toolkit.dependency_check()
        
        self.assertTrue(result.success)
        self.assertIn('unknown_pkg', result.result['missing_packages'])
        self.assertNotIn('requests', result.result['missing_packages'])
        self.assertNotIn('os', result.result['missing_packages']) # stdlib

    def test_get_backups(self):
        backup = MagicMock()
        backup.name = "test.py.20230101_120000"
        backup.stat.return_value.st_mtime = 1000
        backup.stat.return_value.st_size = 50
        
        # _backup_dir is already a mock from setUp
        self.toolkit._backup_dir.glob.return_value = [backup]
        
        result = self.toolkit.get_backups()
        
        self.assertTrue(result.success, f"Failed with error: {result.error}")
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0]['original_file'], 'test.py')

    @patch('shutil.copy2')
    @patch('pathlib.Path.exists')
    def test_restore_backup(self, mock_exists, mock_copy):
        mock_exists.return_value = True # Backup exists
        
        result = self.toolkit.restore_backup("test.py.20230101_120000")
        
        self.assertTrue(result.success)
        mock_copy.assert_called()
        self.assertIn("Restored test.py", result.result)

    @patch('subprocess.run')
    def test_git_diff(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="diff content", stderr="")
        
        result = self.toolkit.git_diff()
        
        self.assertTrue(result.success)
        self.assertEqual(result.result['working_tree'], "diff content")
        self.assertEqual(result.result['staged'], "diff content")

    @patch('pathlib.Path.iterdir')
    def test_get_project_tree(self, mock_iterdir):
        # Setup directory structure
        file1 = MagicMock()
        file1.name = "main.py"
        file1.is_dir.return_value = False
        
        dir1 = MagicMock()
        dir1.name = "utils"
        dir1.is_dir.return_value = True
        
        # Mock recursive call simulation (simplified)
        mock_iterdir.side_effect = [[file1, dir1], []] # Root has 2, utils has 0
        
        result = self.toolkit.get_project_tree()
        
        self.assertTrue(result.success)
        self.assertIn("main.py", result.result)
        self.assertIn("utils", result.result)

    @patch('pathlib.Path.write_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    def test_create_test(self, mock_mkdir, mock_exists, mock_write):
        # Target exists, test doesn't exist
        mock_exists.side_effect = [True, False] 
        
        result = self.toolkit.create_test("app.py")
        
        self.assertTrue(result.success)
        mock_write.assert_called()
        self.assertIn("tests/test_app.py", result.result)

    @patch('subprocess.run')
    def test_run_tests(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        
        result = self.toolkit.run_tests()
        
        self.assertTrue(result.success)
        self.assertEqual(result.result['returncode'], 0)

if __name__ == '__main__':
    unittest.main()
