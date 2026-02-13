"""
Configuration Accessor for Coding Agent
=========================================

Provides a simple interface to access coding agent configuration from agents_config.yaml.
Replaces the deprecated agent_config.py with hardcoded values.

Usage:
    from .config_accessor import get_coding_agent_config

    # Get configuration value
    max_iterations = get_coding_agent_config('execution', 'max_iterations', default=10)
    threshold = get_coding_agent_config('verification', 'success_threshold', default=90)
    use_universal = get_coding_agent_config('orchestrator', 'use_universal_handler', default=True)

Author: RAICA Development Team
Compliance: PROJECT_CONFIGURATION_DIRECTIVE.md
"""

import sys
from pathlib import Path
from typing import Any, Optional

# Add agents/common to path to import config_loader
_common_path = Path(__file__).parent.parent / "common"
if str(_common_path) not in sys.path:
    sys.path.insert(0, str(_common_path))

from config_loader import AgentConfigLoader, AgentConfigError

# Cache the config instance
_cached_config: Optional[Any] = None


def get_coding_agent_config(*keys: str, default: Any = None, required: bool = False) -> Any:
    """
    Get a configuration value for the coding agent.

    Args:
        *keys: Configuration path (e.g., 'execution', 'max_iterations')
        default: Default value if not found
        required: If True, raise error when value is missing

    Returns:
        Configuration value from agents_config.yaml

    Raises:
        AgentConfigError: If required=True and value is missing

    Examples:
        >>> get_coding_agent_config('execution', 'max_iterations')
        10
        >>> get_coding_agent_config('verification', 'success_threshold')
        90
        >>> get_coding_agent_config('orchestrator', 'use_universal_handler')
        True
    """
    global _cached_config

    # Load config on first access
    if _cached_config is None:
        try:
            _cached_config = AgentConfigLoader.get_agent_config("coding_agent")
        except AgentConfigError as e:
            # If config loading fails, use default if provided
            if default is not None and not required:
                return default
            raise

    # Get the value
    return _cached_config.get(*keys, default=default, required=required)


def get_max_iterations(default: int = 10) -> int:
    """
    Get max iterations setting for coding agent.

    This replaces the deprecated AgentDefaults.MAX_ITERATIONS.

    Returns:
        Max iterations from config (defaults to 10)
    """
    return get_coding_agent_config('execution', 'max_iterations', default=default)


def get_success_threshold(default: float = 90.0) -> float:
    """
    Get success threshold for verification.

    Returns:
        Success threshold percentage (defaults to 90.0)
    """
    return get_coding_agent_config('verification', 'success_threshold', default=default)


def get_use_universal_handler(default: bool = True) -> bool:
    """
    Get whether to use universal handler in orchestrator.

    Returns:
        True to use universal handler, False for legacy routing
    """
    return get_coding_agent_config('orchestrator', 'use_universal_handler', default=default)


def reload_config() -> None:
    """
    Force reload of configuration from file.

    Useful for testing or when configuration changes.
    """
    global _cached_config
    _cached_config = None
    AgentConfigLoader.load_config(force_reload=True)
