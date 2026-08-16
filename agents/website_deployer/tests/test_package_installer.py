#!/usr/bin/env python3
"""Unit tests for PackageInstaller module."""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path so we can import stages.deployment_modules.package_installer
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from stages.deployment_modules.package_installer import PackageInstaller


class TestPackageInstaller(unittest.TestCase):

    def setUp(self):
        self.ssh_manager = MagicMock()
        self.client = MagicMock()
        self.ssh_manager.get_client.return_value = self.client
        self.installer = PackageInstaller(self.ssh_manager)

    @patch("stages.deployment_modules.package_installer.SafeSSHExecutor")
    def test_install_python_postgres_nginx(self, mock_executor_class):
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        mock_result = MagicMock()
        mock_result.success = True
        mock_executor.execute.return_value = mock_result

        architecture = {
            "backend_language": "Python",
            "web_server": "nginx",
            "database_type": "postgresql",
        }

        success = self.installer.install(architecture)
        self.assertTrue(success)

        # Check executing commands
        self.assertEqual(mock_executor.execute.call_count, 2)
        update_call = mock_executor.execute.call_args_list[0][0][0]
        install_call = mock_executor.execute.call_args_list[1][0][0]

        self.assertIn("DEBIAN_FRONTEND=noninteractive apt-get update", update_call.command)
        self.assertIn("python3 python3-pip python3-venv nginx postgresql postgresql-contrib", install_call.command)

    @patch("stages.deployment_modules.package_installer.SafeSSHExecutor")
    def test_install_nodejs_mysql_apache(self, mock_executor_class):
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        mock_result = MagicMock()
        mock_result.success = True
        mock_executor.execute.return_value = mock_result

        architecture = {
            "backend_language": "nodejs",
            "web_server": "apache2",
            "database_type": "mysql",
            "workers": True,
            "additional_packages": ["git", "curl", "build-essential"]
        }

        success = self.installer.install(architecture)
        self.assertTrue(success)

        install_call = mock_executor.execute.call_args_list[1][0][0]
        cmd = install_call.command

        self.assertIn("nodejs", cmd)
        self.assertIn("npm", cmd)
        self.assertIn("apache2", cmd)
        self.assertIn("mysql-server", cmd)
        self.assertIn("redis-server", cmd)
        self.assertIn("build-essential", cmd)

    @patch("stages.deployment_modules.package_installer.SafeSSHExecutor")
    def test_empty_package_list_returns_true(self, mock_executor_class):
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor

        architecture = {
            "backend_language": "unknown_lang",
            "web_server": "custom_web_server",
            "database_type": "none",
        }

        success = self.installer.install(architecture)
        self.assertTrue(success)
        # Should not attempt apt execution if no packages needed
        mock_executor.execute.assert_not_called()

    @patch("stages.deployment_modules.package_installer.SafeSSHExecutor")
    def test_apt_update_retry_logic(self, mock_executor_class):
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor

        fail_result = MagicMock(success=False, stderr="Network error")
        success_result = MagicMock(success=True)

        # Fail twice on update, then succeed
        mock_executor.execute.side_effect = [fail_result, fail_result, success_result, success_result]

        architecture = {
            "backend_language": "python",
            "web_server": "nginx",
        }

        with patch("time.sleep", return_value=None):
            success = self.installer.install(architecture)

        self.assertTrue(success)
        # 3 update calls + 1 install call = 4 total executor calls
        self.assertEqual(mock_executor.execute.call_count, 4)

    @patch("stages.deployment_modules.package_installer.SafeSSHExecutor")
    def test_robust_against_none_values(self, mock_executor_class):
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        mock_result = MagicMock(success=True)
        mock_executor.execute.return_value = mock_result

        architecture = {
            "backend_language": None,
            "web_server": None,
            "database_type": None,
        }

        success = self.installer.install(architecture)
        self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
