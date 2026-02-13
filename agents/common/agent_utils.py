#!/usr/bin/env python3
"""
Core agent utilities for server communication and common operations.

All configuration values are loaded from config/agents_config.yaml.
No hardcoded configuration values allowed per PROJECT_CONFIGURATION_DIRECTIVE.

Author: RAICA Development Team
Version: 1.1.0
"""

import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

import openai

if TYPE_CHECKING:
    from .config_loader import AgentConfig


def create_openai_client(server_url: str, api_key: str = "not-required") -> openai.OpenAI:
    """
    Create and configure an OpenAI client for the RAICA server.

    Args:
        server_url: URL of the RAICA server (e.g., 'http://localhost:5000/v1')
        api_key: API key for authentication (default: 'not-required' for local server)

    Returns:
        Configured OpenAI client instance
    """
    return openai.OpenAI(
        base_url=server_url,
        api_key=api_key
    )


def create_client_from_config(config: 'AgentConfig') -> openai.OpenAI:
    """
    Create an OpenAI client using agent configuration.

    This is the preferred method for creating clients as it uses the
    centralized configuration system.

    Args:
        config: AgentConfig object from get_agent_config()

    Returns:
        Configured OpenAI client instance
    """
    return openai.OpenAI(
        base_url=config.get_server_url(),
        api_key=config.get_api_key()
    )


def test_server_connection(
    client: openai.OpenAI,
    logger: Optional[logging.Logger] = None,
    model: Optional[str] = None,
    config: Optional['AgentConfig'] = None
) -> bool:
    """
    Test connection to the RAICA server.

    Args:
        client: OpenAI client instance
        logger: Optional logger for output
        model: Model name to use (if not provided, uses config or defaults)
        config: Optional AgentConfig to get model from

    Returns:
        True if connection successful, False otherwise
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Get model from config if available
    if model is None:
        if config is not None:
            model = config.get_llm_model()
        else:
            # Fail-fast: require explicit model or config
            from .config_loader import AgentConfigLoader
            try:
                defaults = AgentConfigLoader.get_defaults()
                model = defaults.get('llm', {}).get('model')
                if not model:
                    raise ValueError("No default model configured")
            except Exception as e:
                logger.error(f"❌ No model specified and could not load default: {e}")
                return False

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello, are you working?"}],
            max_tokens=50
        )
        logger.info("✅ Server connection successful")
        return True
    except Exception as e:
        logger.error(f"❌ Server connection failed: {e}")
        return False


def execute_with_retry(
    client: openai.OpenAI,
    prompt: str,
    max_retries: Optional[int] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    task_description: str = "Task",
    model: Optional[str] = None,
    config: Optional['AgentConfig'] = None,
    retry_base_delay: float = 2.0
) -> Optional[str]:
    """
    Execute a prompt with retry logic and exponential backoff.

    All parameters can be provided explicitly or loaded from config.
    Config values are used as defaults when explicit values are not provided.

    Args:
        client: OpenAI client instance
        prompt: The prompt to send to the server
        max_retries: Maximum number of retry attempts
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
        logger: Optional logger for output
        task_description: Description of the task for logging
        model: Model name to use
        config: Optional AgentConfig to get defaults from
        retry_base_delay: Base delay for exponential backoff

    Returns:
        Response content as string or None if all retries failed
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Load defaults from config if provided
    if config is not None:
        if model is None:
            model = config.get_llm_model()
        if temperature is None:
            temperature = config.get_llm_setting('temperature', 0.7)
        if max_tokens is None:
            max_tokens = config.get_llm_setting('max_tokens', 4096)
        if max_retries is None:
            max_retries = config.get_execution_setting('max_retries', 3)
        retry_base_delay = config.get_execution_setting('retry_base_delay', 2.0)
    else:
        # Use provided values or sensible defaults
        if model is None:
            # Try to load from global defaults
            from .config_loader import AgentConfigLoader
            try:
                defaults = AgentConfigLoader.get_defaults()
                model = defaults.get('llm', {}).get('model')
            except Exception:
                pass
            if not model:
                logger.error("❌ No model specified and could not load default")
                return None
        if temperature is None:
            temperature = 0.7
        if max_tokens is None:
            max_tokens = 4096
        if max_retries is None:
            max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"{task_description} (attempt {attempt}/{max_retries})...")

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )

            content = response.choices[0].message.content

            if not content:
                raise ValueError("Response content is empty")

            logger.info(f"✅ {task_description} completed ({len(content)} chars)")
            return content

        except Exception as e:
            logger.error(f"❌ Attempt {attempt} failed: {e}")

            if attempt < max_retries:
                wait_time = retry_base_delay * (2 ** (attempt - 1))  # Exponential backoff
                logger.info(f"Retrying in {wait_time:.1f} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"All retry attempts exhausted for {task_description}")
                return None


def setup_agent_logging(
    agent_name: str,
    log_file: Optional[str] = None,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Setup standardized logging for an agent.

    Args:
        agent_name: Name of the agent (used for logger name)
        log_file: Optional log file path (default: {agent_name}.log)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    if log_file is None:
        log_file = f"{agent_name}.log"

    # Create logger
    logger = logging.getLogger(agent_name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers = []

    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def create_output_directory(output_dir: str) -> Path:
    """
    Create output directory if it doesn't exist.

    Args:
        output_dir: Path to output directory

    Returns:
        Path object for the directory
    """
    path = Path(output_dir)
    path.mkdir(exist_ok=True, parents=True)
    return path


def extract_target_path(request: str) -> Optional[Path]:
    """
    Extract a user-specified target path from a request string.

    Looks for patterns like:
    - "in ~/Development/myproject"
    - "to /home/user/project"
    - "at ~/projects/chess"
    - "save in ~/code/game"
    - "create in /tmp/test"

    Args:
        request: The user's request string

    Returns:
        Resolved Path if found, None otherwise
    """
    import re

    # Patterns to match directory specifications
    # Match: "in/to/at/save in/create in" followed by a path
    path_patterns = [
        # "in ~/path" or "in /path" or "in ./path"
        r'(?:^|\s)(?:in|to|at|into)\s+((?:~|/|\.)[^\s,]+)',
        # "save in ~/path"
        r'(?:save|create|put|store|generate|write)\s+(?:it\s+)?(?:in|to|at)\s+((?:~|/|\.)[^\s,]+)',
        # "files in ~/path"
        r'files?\s+(?:in|to|at)\s+((?:~|/|\.)[^\s,]+)',
        # "directory ~/path" or "folder ~/path"
        r'(?:directory|folder|dir)\s+((?:~|/|\.)[^\s,]+)',
        # "path: ~/path" or "location: ~/path"
        r'(?:path|location|output):\s*((?:~|/|\.)[^\s,]+)',
    ]

    for pattern in path_patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            path_str = match.group(1).strip()

            # Remove trailing punctuation
            path_str = path_str.rstrip('.,;:!?)')

            # Expand ~ to home directory
            if path_str.startswith('~'):
                path_str = str(Path.home()) + path_str[1:]

            try:
                path = Path(path_str).resolve()
                # Validate it looks like a reasonable path
                # (not just a word that happened to match)
                if len(path.parts) > 1:  # Has at least one directory component
                    return path
            except Exception:
                continue

    return None


def generate_semantic_name(request: str) -> str:
    """
    Generate a semantic project name from a request string.

    Args:
        request: The user's request string

    Returns:
        A snake_case project name with timestamp suffix
    """
    import re
    from datetime import datetime
    from .config_defaults import SEMANTIC_NAMING_STOP_WORDS

    # Basic cleaning
    clean = re.sub(r'[^\w\s]', '', request).lower()
    words = clean.split()

    # Remove common stop words
    keywords = [w for w in words if w not in SEMANTIC_NAMING_STOP_WORDS][:5]

    if not keywords:
        keywords = ["project"]

    name = "_".join(keywords)
    timestamp = datetime.now().strftime("%H%M")
    return f"{name}_{timestamp}"


def get_patched_logger(logger: logging.Logger) -> logging.Logger:
    """
    Patch a logger to remove console handlers.
    
    Useful when running in TUI mode where stdout is captured/interferes.
    
    Args:
        logger: The logger to patch
        
    Returns:
        The patched logger
    """
    new_handlers = []
    for handler in logger.handlers:
        is_console = (isinstance(handler, logging.StreamHandler) and 
                     (getattr(handler, 'stream', None) == sys.stdout or 
                      getattr(handler, 'stream', None) == sys.stderr))
        if not is_console:
            new_handlers.append(handler)
    logger.handlers = new_handlers
    return logger

import subprocess


class ClipboardHelper:
    """Cross-platform clipboard helper for terminal applications."""

    @staticmethod
    def copy(text: str) -> bool:
        """Copy text to clipboard. Returns True on success."""
        # Try xclip first (most common on Linux)
        if shutil.which('xclip'):
            try:
                proc = subprocess.Popen(
                    ['xclip', '-selection', 'clipboard'],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                proc.communicate(text.encode('utf-8'))
                return proc.returncode == 0
            except Exception:
                pass

        # Try xsel as fallback
        if shutil.which('xsel'):
            try:
                proc = subprocess.Popen(
                    ['xsel', '--clipboard', '--input'],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                proc.communicate(text.encode('utf-8'))
                return proc.returncode == 0
            except Exception:
                pass

        # Try wl-copy for Wayland
        if shutil.which('wl-copy'):
            try:
                proc = subprocess.Popen(
                    ['wl-copy'],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                proc.communicate(text.encode('utf-8'))
                return proc.returncode == 0
            except Exception:
                pass

        return False

    @staticmethod
    def paste() -> Optional[str]:
        """Paste text from clipboard. Returns None on failure."""
        # Try xclip first
        if shutil.which('xclip'):
            try:
                result = subprocess.run(
                    ['xclip', '-selection', 'clipboard', '-o'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass

        # Try xsel as fallback
        if shutil.which('xsel'):
            try:
                result = subprocess.run(
                    ['xsel', '--clipboard', '--output'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass

        # Try wl-paste for Wayland
        if shutil.which('wl-paste'):
            try:
                result = subprocess.run(
                    ['wl-paste'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass

        return None


