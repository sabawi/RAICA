"""
Communication Hub Tools - LLM-driven social media and communication operations.

This module provides tools for the LLM to interact with various communication
channels (Twitter, email, etc.) through the unified Communication Hub configuration.

Each tool:
- Has a defined schema for LLM tool-calling
- Takes structured parameters
- Returns structured ToolResult

Usage:
    tools = CommunicationHubTools(project_dir)
    result = tools.get_available_channels({})
    result = tools.execute_social_operation({
        "channel": "twitter",
        "operation": "get_user_tweets",
        "parameters": {"limit": 10}
    })
"""

import logging
import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Load .env file for credentials
try:
    from dotenv import load_dotenv
    # Load from current directory or parent
    env_file = Path.cwd() / '.env'
    if env_file.exists():
        load_dotenv(env_file)
    else:
        parent_env = Path.cwd().parent / '.env'
        if parent_env.exists():
            load_dotenv(parent_env)
except ImportError:
    pass  # dotenv not available, rely on system env vars

# Import ToolResult from debug_toolkit for consistent return types
try:
    from agents.coding_agent.services.debug_toolkit import ToolResult
except ImportError:
    # Fallback for direct module execution
    class ToolResult:
        """Structured result from a tool execution."""
        def __init__(self, success: bool, result: Any = None, error: Optional[str] = None, metadata: Optional[Dict] = None):
            self.success = success
            self.result = result
            self.error = error
            self.metadata = metadata or {}

        def to_dict(self) -> Dict:
            return {"success": self.success, "result": self.result, "error": self.error, "metadata": self.metadata}

# Import environment manager for credential resolution
try:
    from utils.platform import EnvironmentManager
except ImportError:
    # Fallback for direct module execution
    class EnvironmentManager:
        @staticmethod
        def expand_env_vars(text: str) -> str:
            return os.path.expandvars(text)

logger = logging.getLogger(__name__)


class CommunicationHubTools:
    """
    Tools for LLM-driven communication operations.

    Provides structured access to social media and communication channels
    configured in communication_hub.yaml.
    """

    # Capabilities for each channel type
    CHANNEL_CAPABILITIES = {
        "twitter": ["post", "get_user_tweets", "get_tweet_replies", "get_mentions"],
        "email": ["send", "read_inbox", "search"],
        "substack": ["post_article", "get_drafts"],
        "wordpress": ["post_article", "get_posts", "update_post"],
        "slack": ["send_message", "read_channel"],
        "discord": ["send_message", "read_channel"],
        "telegram": ["send_message", "read_messages"],
        "sms": ["send"],
    }

    def __init__(self, project_dir: Path, config_path: Optional[Path] = None):
        """
        Initialize the communication hub tools.

        Args:
            project_dir: Project directory for resolving relative paths
            config_path: Optional path to communication_hub.yaml (defaults to config/communication_hub.yaml)
        """
        self.project_dir = Path(project_dir)
        self._config_path = config_path or self._find_config_path()
        self._config: Optional[Dict] = None
        self._handlers_cache: Dict[str, Any] = {}

    def _find_config_path(self) -> Path:
        """Find the communication_hub.yaml config file."""
        # Try project-relative paths first
        candidates = [
            self.project_dir / "config" / "communication_hub.yaml",
            self.project_dir / "communication_hub.yaml",
            Path.cwd() / "config" / "communication_hub.yaml",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Default to project config path even if it doesn't exist yet
        return self.project_dir / "config" / "communication_hub.yaml"

    def _load_config(self) -> Dict:
        """
        Load and cache the communication hub configuration.

        Returns:
            Parsed configuration dictionary with env vars expanded
        """
        if self._config is not None:
            return self._config

        if not self._config_path.exists():
            logger.warning(f"Communication hub config not found at {self._config_path}")
            self._config = {"communication_hub": {"channels": {}}}
            return self._config

        try:
            with open(self._config_path, 'r') as f:
                raw_config = yaml.safe_load(f)

            # Expand environment variables in the config
            self._config = self._expand_env_vars_in_config(raw_config)
            return self._config

        except Exception as e:
            logger.error(f"Failed to load communication hub config: {e}")
            self._config = {"communication_hub": {"channels": {}}}
            return self._config

    def _expand_env_vars_in_config(self, config: Any) -> Any:
        """
        Recursively expand environment variables in config values.

        Supports ${VAR_NAME} and ${VAR_NAME:default_value} syntax.
        """
        if isinstance(config, dict):
            return {k: self._expand_env_vars_in_config(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._expand_env_vars_in_config(item) for item in config]
        elif isinstance(config, str):
            return self._expand_env_var_string(config)
        return config

    def _expand_env_var_string(self, text: str) -> str:
        """
        Expand environment variables in a string.

        Supports:
        - ${VAR_NAME} - replaced with env var value or empty string
        - ${VAR_NAME:default} - replaced with env var value or default
        """
        import re

        # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

        def replacer(match):
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ''
            return os.environ.get(var_name, default)

        return re.sub(pattern, replacer, text)

    def _check_credentials_configured(self, channel_config: Dict) -> bool:
        """
        Check if credentials are configured for a channel.

        Does NOT expose actual credential values, only returns True/False.
        """
        credentials = channel_config.get('credentials', {})

        if not credentials:
            return False

        # Check if any credential values are non-empty after env var expansion
        for key, value in credentials.items():
            if isinstance(value, str) and value and not value.startswith('${'):
                return True

        return False

    def get_available_channels(self, args: Dict) -> ToolResult:
        """
        List all configured communication channels with their status and capabilities.

        Args:
            args: Empty dict (no parameters required)

        Returns:
            ToolResult with list of channels, their enabled status, and capabilities
        """
        try:
            config = self._load_config()
            hub_config = config.get('communication_hub', {})
            channels_config = hub_config.get('channels', {})

            channels = []
            for channel_name, channel_cfg in channels_config.items():
                channel_info = {
                    "name": channel_name,
                    "enabled": channel_cfg.get('enabled', False),
                    "credentials_configured": self._check_credentials_configured(channel_cfg),
                    "capabilities": self.CHANNEL_CAPABILITIES.get(channel_name, []),
                    "rate_limits": channel_cfg.get('rate_limits', {}),
                }
                channels.append(channel_info)

            return ToolResult(
                success=True,
                result={
                    "channels": channels,
                    "global_rate_limits": hub_config.get('global', {}).get('rate_limits', {}),
                },
                metadata={"config_path": str(self._config_path)}
            )

        except Exception as e:
            logger.error(f"Failed to get available channels: {e}")
            return ToolResult(
                success=False,
                error=f"Failed to get available channels: {str(e)}"
            )

    def get_channel_config(self, args: Dict) -> ToolResult:
        """
        Get configuration for a specific channel (without exposing credentials).

        Args:
            args: {"channel": "twitter"} - channel name

        Returns:
            ToolResult with channel settings, rate limits, content limits
        """
        try:
            channel_name = args.get('channel')
            if not channel_name:
                return ToolResult(
                    success=False,
                    error="Missing required parameter: 'channel'"
                )

            config = self._load_config()
            channels = config.get('communication_hub', {}).get('channels', {})

            if channel_name not in channels:
                available = list(channels.keys())
                return ToolResult(
                    success=False,
                    error=f"Channel '{channel_name}' not found. Available: {available}"
                )

            channel_cfg = channels[channel_name]

            # Build safe config (no credentials exposed)
            safe_config = {
                "name": channel_name,
                "enabled": channel_cfg.get('enabled', False),
                "credentials_configured": self._check_credentials_configured(channel_cfg),
                "settings": channel_cfg.get('settings', {}),
                "rate_limits": channel_cfg.get('rate_limits', {}),
                "capabilities": self.CHANNEL_CAPABILITIES.get(channel_name, []),
            }

            # Include provider info for email if applicable
            if channel_name == 'email' and 'providers' in channel_cfg:
                safe_config['providers'] = list(channel_cfg['providers'].keys())
                safe_config['default_provider'] = channel_cfg.get('default_provider')

            return ToolResult(
                success=True,
                result=safe_config
            )

        except Exception as e:
            logger.error(f"Failed to get channel config: {e}")
            return ToolResult(
                success=False,
                error=f"Failed to get channel config: {str(e)}"
            )

    def execute_social_operation(self, args: Dict) -> ToolResult:
        """
        Execute a social media operation via the appropriate handler.

        Args:
            args: {
                "channel": "twitter",
                "operation": "get_user_tweets",
                "parameters": {"limit": 10}
            }

        Returns:
            ToolResult with operation result
        """
        try:
            channel = args.get('channel')
            operation = args.get('operation')
            parameters = args.get('parameters', {})

            # Validate required args
            if not channel:
                return ToolResult(success=False, error="Missing required parameter: 'channel'")
            if not operation:
                return ToolResult(success=False, error="Missing required parameter: 'operation'")

            # Check channel is enabled
            config = self._load_config()
            channels = config.get('communication_hub', {}).get('channels', {})

            if channel not in channels:
                return ToolResult(
                    success=False,
                    error=f"Channel '{channel}' not configured. Available: {list(channels.keys())}"
                )

            channel_cfg = channels[channel]
            if not channel_cfg.get('enabled', False):
                return ToolResult(
                    success=False,
                    error=f"Channel '{channel}' is disabled. Enable it in communication_hub.yaml"
                )

            # Check credentials are configured
            if not self._check_credentials_configured(channel_cfg):
                return ToolResult(
                    success=False,
                    error=f"Channel '{channel}' has no credentials configured. Set environment variables."
                )

            # Validate operation is supported
            capabilities = self.CHANNEL_CAPABILITIES.get(channel, [])
            if operation not in capabilities:
                return ToolResult(
                    success=False,
                    error=f"Operation '{operation}' not supported for channel '{channel}'. Available: {capabilities}"
                )

            # Dispatch to appropriate handler
            if channel == 'twitter':
                return self._execute_twitter_operation(operation, parameters, channel_cfg)
            else:
                return ToolResult(
                    success=False,
                    error=f"Handler for channel '{channel}' not yet implemented"
                )

        except Exception as e:
            logger.error(f"Failed to execute social operation: {e}")
            return ToolResult(
                success=False,
                error=f"Failed to execute social operation: {str(e)}"
            )

    def _execute_twitter_operation(self, operation: str, parameters: Dict, channel_cfg: Dict) -> ToolResult:
        """
        Execute a Twitter operation via the Twitter handler.

        Args:
            operation: Operation name (post, get_user_tweets, etc.)
            parameters: Operation-specific parameters
            channel_cfg: Channel configuration with credentials

        Returns:
            ToolResult with operation result
        """
        try:
            # Find the Twitter handler
            handler_path = self._find_handler_path('twitter')
            if not handler_path:
                return ToolResult(
                    success=False,
                    error="Twitter handler not found. Expected at plugins/handlers/social_media_twitter.py"
                )

            # Prepare environment with credentials
            credentials = channel_cfg.get('credentials', {})
            env = os.environ.copy()

            # Map credential config to handler expected env vars
            env['API_KEY_ENV'] = 'TWITTER_API_KEY'
            env['API_SECRET_ENV'] = 'TWITTER_API_SECRET'
            env['ACCESS_TOKEN_ENV'] = 'TWITTER_ACCESS_TOKEN'
            env['ACCESS_SECRET_ENV'] = 'TWITTER_ACCESS_TOKEN_SECRET'

            # Ensure the actual credential values are in env
            # (they should already be from communication_hub.yaml expansion)
            if 'api_key' in credentials:
                env['TWITTER_API_KEY'] = credentials['api_key']
            if 'api_secret' in credentials:
                env['TWITTER_API_SECRET'] = credentials['api_secret']
            if 'access_token' in credentials:
                env['TWITTER_ACCESS_TOKEN'] = credentials['access_token']
            if 'access_token_secret' in credentials:
                env['TWITTER_ACCESS_TOKEN_SECRET'] = credentials['access_token_secret']
            if 'bearer_token' in credentials:
                env['TWITTER_BEARER_TOKEN'] = credentials['bearer_token']

            # Build the operation request
            request = {
                "operation": operation,
                **parameters
            }

            # For 'post' operation, use existing handler via subprocess
            # For new operations, call handler functions directly
            if operation == 'post':
                # Use existing execute() function via subprocess
                request_json = json.dumps({"text": parameters.get("text", ""), **parameters})

                result = subprocess.run(
                    [sys.executable, str(handler_path)],
                    input=request_json,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=60
                )

                if result.returncode != 0 and not result.stdout:
                    return ToolResult(
                        success=False,
                        error=f"Twitter handler failed: {result.stderr}"
                    )

                try:
                    response = json.loads(result.stdout)
                    return ToolResult(
                        success=response.get('success', False),
                        result=response.get('result'),
                        error=response.get('error'),
                        metadata=response.get('metadata', {})
                    )
                except json.JSONDecodeError:
                    return ToolResult(
                        success=False,
                        error=f"Invalid JSON response from handler: {result.stdout[:200]}"
                    )

            else:
                # For read operations, call handler module directly
                return self._call_twitter_read_operation(operation, parameters, env, handler_path)

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="Twitter operation timed out after 60 seconds"
            )
        except Exception as e:
            logger.error(f"Twitter operation failed: {e}")
            return ToolResult(
                success=False,
                error=f"Twitter operation failed: {str(e)}"
            )

    def _call_twitter_read_operation(self, operation: str, parameters: Dict, env: Dict, handler_path: Path) -> ToolResult:
        """
        Call Twitter read operations (get_user_tweets, get_tweet_replies, get_mentions).

        These are new functions added to the Twitter handler.
        """
        try:
            # Import the handler module dynamically
            import importlib.util

            spec = importlib.util.spec_from_file_location("social_media_twitter", handler_path)
            if spec is None or spec.loader is None:
                return ToolResult(
                    success=False,
                    error="Failed to load Twitter handler module"
                )

            module = importlib.util.module_from_spec(spec)

            # Set up environment before loading module
            original_env = os.environ.copy()
            os.environ.update(env)

            try:
                spec.loader.exec_module(module)

                # Call the appropriate function
                if operation == 'get_user_tweets':
                    func = getattr(module, 'get_user_tweets', None)
                    if func:
                        result = asyncio.run(func(parameters.get('limit', 10)))
                        return ToolResult(**result) if isinstance(result, dict) else ToolResult(success=True, result=result)

                elif operation == 'get_tweet_replies':
                    func = getattr(module, 'get_tweet_replies', None)
                    if func:
                        tweet_id = parameters.get('tweet_id')
                        if not tweet_id:
                            return ToolResult(success=False, error="Missing required parameter: 'tweet_id'")
                        result = asyncio.run(func(tweet_id, parameters.get('limit', 10)))
                        return ToolResult(**result) if isinstance(result, dict) else ToolResult(success=True, result=result)

                elif operation == 'get_mentions':
                    func = getattr(module, 'get_mentions', None)
                    if func:
                        result = asyncio.run(func(parameters.get('limit', 10)))
                        return ToolResult(**result) if isinstance(result, dict) else ToolResult(success=True, result=result)

                return ToolResult(
                    success=False,
                    error=f"Operation '{operation}' not implemented in Twitter handler"
                )

            finally:
                # Restore original environment
                os.environ.clear()
                os.environ.update(original_env)

        except Exception as e:
            logger.error(f"Failed to call Twitter read operation: {e}")
            return ToolResult(
                success=False,
                error=f"Failed to call Twitter read operation: {str(e)}"
            )

    def _find_handler_path(self, channel: str) -> Optional[Path]:
        """Find the handler script path for a channel."""
        handler_map = {
            'twitter': 'plugins/handlers/social_media_twitter.py',
            'email': 'plugins/handlers/email_handler.py',
        }

        if channel not in handler_map:
            return None

        # Try project-relative path first
        candidates = [
            self.project_dir / handler_map[channel],
            Path.cwd() / handler_map[channel],
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None


# Convenience function for direct testing
def test_communication_hub():
    """Test the communication hub tools."""
    tools = CommunicationHubTools(Path.cwd())

    print("=== Available Channels ===")
    result = tools.get_available_channels({})
    print(json.dumps(result.to_dict(), indent=2))

    print("\n=== Twitter Channel Config ===")
    result = tools.get_channel_config({"channel": "twitter"})
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    test_communication_hub()
