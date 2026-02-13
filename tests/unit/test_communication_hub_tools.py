"""
Unit tests for Communication Hub Tools.

Tests the CommunicationHubTools class which provides LLM-driven
access to social media and communication channels.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.coding_agent.services.communication_hub_tools import CommunicationHubTools


class TestCommunicationHubConfig(unittest.TestCase):
    """Test configuration loading and environment variable expansion."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_config_loading_basic(self):
        """Test basic config loading without env vars."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      settings:
        max_content_length: 280
      rate_limits:
        per_minute: 1
        per_hour: 50
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        config = tools._load_config()

        self.assertIn('communication_hub', config)
        self.assertIn('twitter', config['communication_hub']['channels'])
        self.assertTrue(config['communication_hub']['channels']['twitter']['enabled'])

    def test_env_var_expansion(self):
        """Test environment variable expansion in config values."""
        # Set test env vars
        os.environ['TEST_API_KEY'] = 'test_key_12345'
        os.environ['TEST_SECRET'] = 'test_secret_67890'

        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: ${TEST_API_KEY}
        api_secret: ${TEST_SECRET}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        config = tools._load_config()

        creds = config['communication_hub']['channels']['twitter']['credentials']
        self.assertEqual(creds['api_key'], 'test_key_12345')
        self.assertEqual(creds['api_secret'], 'test_secret_67890')

        # Clean up
        del os.environ['TEST_API_KEY']
        del os.environ['TEST_SECRET']

    def test_env_var_with_default(self):
        """Test environment variable expansion with default values."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: ${NONEXISTENT_VAR:default_value}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        config = tools._load_config()

        creds = config['communication_hub']['channels']['twitter']['credentials']
        self.assertEqual(creds['api_key'], 'default_value')

    def test_missing_config_file(self):
        """Test behavior when config file doesn't exist."""
        tools = CommunicationHubTools(
            Path(self.test_dir),
            Path(self.test_dir) / "nonexistent.yaml"
        )
        config = tools._load_config()

        self.assertIn('communication_hub', config)
        self.assertEqual(config['communication_hub']['channels'], {})


class TestGetAvailableChannels(unittest.TestCase):
    """Test get_available_channels tool."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_available_channels_success(self):
        """Test listing available channels."""
        os.environ['TEST_TWITTER_KEY'] = 'key123'

        config_content = """
communication_hub:
  global:
    rate_limits:
      per_minute: 10
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: ${TEST_TWITTER_KEY}
      rate_limits:
        per_minute: 1
    email:
      enabled: false
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.get_available_channels({})

        self.assertTrue(result.success)
        self.assertIn('channels', result.result)

        channels = {c['name']: c for c in result.result['channels']}
        self.assertIn('twitter', channels)
        self.assertTrue(channels['twitter']['enabled'])
        self.assertTrue(channels['twitter']['credentials_configured'])
        self.assertIn('post', channels['twitter']['capabilities'])

        self.assertIn('email', channels)
        self.assertFalse(channels['email']['enabled'])

        del os.environ['TEST_TWITTER_KEY']

    def test_empty_channels(self):
        """Test when no channels are configured."""
        config_content = """
communication_hub:
  channels: {}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.get_available_channels({})

        self.assertTrue(result.success)
        self.assertEqual(result.result['channels'], [])


class TestGetChannelConfig(unittest.TestCase):
    """Test get_channel_config tool."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_channel_config_success(self):
        """Test getting config for a specific channel."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: secret_key
      settings:
        max_content_length: 280
        supports_attachments: true
      rate_limits:
        per_minute: 1
        per_hour: 50
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.get_channel_config({"channel": "twitter"})

        self.assertTrue(result.success)
        self.assertEqual(result.result['name'], 'twitter')
        self.assertTrue(result.result['enabled'])
        self.assertTrue(result.result['credentials_configured'])
        self.assertEqual(result.result['settings']['max_content_length'], 280)
        self.assertIn('post', result.result['capabilities'])

    def test_get_channel_config_missing_channel(self):
        """Test error when channel parameter is missing."""
        tools = CommunicationHubTools(Path(self.test_dir))
        result = tools.get_channel_config({})

        self.assertFalse(result.success)
        self.assertIn("Missing required parameter", result.error)

    def test_get_channel_config_unknown_channel(self):
        """Test error when channel doesn't exist."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.get_channel_config({"channel": "instagram"})

        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_credentials_not_exposed(self):
        """Test that actual credential values are never returned."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: super_secret_key_12345
        api_secret: another_secret_67890
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.get_channel_config({"channel": "twitter"})

        self.assertTrue(result.success)
        # Result should only contain credentials_configured: bool, not actual values
        self.assertIn('credentials_configured', result.result)
        self.assertTrue(result.result['credentials_configured'])
        # Ensure no credential values in result
        result_str = json.dumps(result.result)
        self.assertNotIn('super_secret_key', result_str)
        self.assertNotIn('another_secret', result_str)


class TestExecuteSocialOperation(unittest.TestCase):
    """Test execute_social_operation tool."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_execute_missing_channel(self):
        """Test error when channel is missing."""
        tools = CommunicationHubTools(Path(self.test_dir))
        result = tools.execute_social_operation({
            "operation": "get_user_tweets"
        })

        self.assertFalse(result.success)
        self.assertIn("Missing required parameter", result.error)
        self.assertIn("channel", result.error)

    def test_execute_missing_operation(self):
        """Test error when operation is missing."""
        tools = CommunicationHubTools(Path(self.test_dir))
        result = tools.execute_social_operation({
            "channel": "twitter"
        })

        self.assertFalse(result.success)
        self.assertIn("Missing required parameter", result.error)
        self.assertIn("operation", result.error)

    def test_execute_channel_not_configured(self):
        """Test error when channel is not configured."""
        config_content = """
communication_hub:
  channels: {}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.execute_social_operation({
            "channel": "twitter",
            "operation": "get_user_tweets"
        })

        self.assertFalse(result.success)
        self.assertIn("not configured", result.error)

    def test_execute_channel_disabled(self):
        """Test error when channel is disabled."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: false
      credentials:
        api_key: test
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.execute_social_operation({
            "channel": "twitter",
            "operation": "get_user_tweets"
        })

        self.assertFalse(result.success)
        self.assertIn("disabled", result.error)

    def test_execute_no_credentials(self):
        """Test error when credentials are not configured."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials: {}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.execute_social_operation({
            "channel": "twitter",
            "operation": "get_user_tweets"
        })

        self.assertFalse(result.success)
        self.assertIn("no credentials", result.error.lower())

    def test_execute_unsupported_operation(self):
        """Test error when operation is not supported."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: test_key
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.execute_social_operation({
            "channel": "twitter",
            "operation": "unsupported_operation"
        })

        self.assertFalse(result.success)
        self.assertIn("not supported", result.error)


class TestTwitterOperations(unittest.TestCase):
    """Test Twitter-specific operations with mocked API responses."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Create plugins directory with mock handler
        self.plugins_dir = Path(self.test_dir) / "plugins" / "handlers"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        # Set up environment variables
        os.environ['TWITTER_API_KEY'] = 'test_api_key'
        os.environ['TWITTER_API_SECRET'] = 'test_api_secret'
        os.environ['TWITTER_ACCESS_TOKEN'] = 'test_access_token'
        os.environ['TWITTER_ACCESS_TOKEN_SECRET'] = 'test_access_secret'

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

        # Clean up env vars
        for key in ['TWITTER_API_KEY', 'TWITTER_API_SECRET',
                    'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN_SECRET']:
            if key in os.environ:
                del os.environ[key]

    def test_twitter_operation_with_invalid_credentials(self):
        """Test Twitter operation with invalid credentials returns an error."""
        config_content = """
communication_hub:
  channels:
    twitter:
      enabled: true
      credentials:
        api_key: ${TWITTER_API_KEY}
        api_secret: ${TWITTER_API_SECRET}
        access_token: ${TWITTER_ACCESS_TOKEN}
        access_token_secret: ${TWITTER_ACCESS_TOKEN_SECRET}
"""
        config_path = self.config_dir / "communication_hub.yaml"
        config_path.write_text(config_content)

        tools = CommunicationHubTools(Path(self.test_dir), config_path)
        result = tools.execute_social_operation({
            "channel": "twitter",
            "operation": "get_user_tweets",
            "parameters": {"limit": 10}
        })

        # Should fail because credentials are invalid (test values)
        # The error could be about handler not found OR authentication failure
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        # Error should indicate some kind of failure (handler not found, auth failure, etc.)
        self.assertTrue(
            "handler not found" in result.error.lower() or
            "failed" in result.error.lower() or
            "unauthorized" in result.error.lower() or
            "authentication" in result.error.lower(),
            f"Expected meaningful error message, got: {result.error}"
        )


class TestDebugToolkitIntegration(unittest.TestCase):
    """Test integration with DebugToolkit."""

    def test_communication_hub_tools_available(self):
        """Test that communication hub tools are registered in DebugToolkit."""
        from agents.coding_agent.services.debug_toolkit import DebugToolkit

        toolkit = DebugToolkit(Path.cwd())
        available_tools = toolkit.get_available_tools()

        self.assertIn('get_available_channels', available_tools)
        self.assertIn('get_channel_config', available_tools)
        self.assertIn('execute_social_operation', available_tools)

    def test_tool_schema_includes_comm_hub(self):
        """Test that tool schemas include communication hub tools."""
        from agents.coding_agent.services.debug_toolkit import DebugToolkit

        toolkit = DebugToolkit(Path.cwd())
        schemas = toolkit.get_tool_schema()

        tool_names = [s['function']['name'] for s in schemas]

        self.assertIn('get_available_channels', tool_names)
        self.assertIn('get_channel_config', tool_names)
        self.assertIn('execute_social_operation', tool_names)


if __name__ == '__main__':
    unittest.main()
