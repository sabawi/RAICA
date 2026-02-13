"""
Debug Toolkit - Collection of tools for LLM-driven debugging.

This module provides structured tools that can be called by an LLM
in tool-calling mode. Each tool has:
- A well-defined schema
- Structured input parameters
- Structured output responses
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import json

# Import CommunicationHubTools for social media operations
try:
    from agents.coding_agent.services.communication_hub_tools import CommunicationHubTools
    _COMMUNICATION_HUB_AVAILABLE = True
except ImportError:
    _COMMUNICATION_HUB_AVAILABLE = False

logger = logging.getLogger(__name__)


class ToolResult:
    """Structured result from a tool execution."""
    
    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        self.success = success
        self.result = result
        self.error = error
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata
        }
    
    def __repr__(self):
        if self.success:
            return f"ToolResult(success=True, result={str(self.result)[:100]}...)"
        return f"ToolResult(success=False, error={self.error})"


class DebugToolkit:
    """
    Collection of tools available to the LLM for debugging.
    
    Each tool:
    - Has a defined schema for LLM tool-calling
    - Takes structured parameters
    - Returns structured ToolResult
    
    Usage:
        toolkit = DebugToolkit(project_dir)
        schema = toolkit.get_tool_schema()  # For LLM system prompt
        result = toolkit.execute("read_file", {"path": "config.py"})
    """
    
    # Standard library modules - detected at runtime for Python version compatibility
    # Uses sys.stdlib_module_names (Python 3.10+) with fallback
    @staticmethod
    def _get_stdlib_modules() -> set:
        """Get standard library modules using runtime detection.

        Uses sys.stdlib_module_names (Python 3.10+) for accurate detection
        rather than hardcoded lists that become outdated.
        """
        import sys
        try:
            # Python 3.10+ has this attribute
            return set(sys.stdlib_module_names)
        except AttributeError:
            # Fallback for Python < 3.10: use pkgutil to discover stdlib
            import pkgutil
            import sysconfig
            stdlib_path = sysconfig.get_paths()['stdlib']
            stdlib_modules = set()
            for importer, modname, ispkg in pkgutil.iter_modules([stdlib_path]):
                stdlib_modules.add(modname)
            # Add builtin modules
            stdlib_modules.update(sys.builtin_module_names)
            return stdlib_modules

    @property
    def STDLIB_MODULES(self) -> set:
        """Runtime-detected standard library modules."""
        if not hasattr(self, '_stdlib_modules_cache'):
            self._stdlib_modules_cache = self._get_stdlib_modules()
        return self._stdlib_modules_cache

    def __init__(self, project_dir: Path, raica_server_url: Optional[str] = None):
        """
        Initialize the debug toolkit.

        Args:
            project_dir: Project directory for file operations
            raica_server_url: Optional RAICA server URL for knowledge services
        """
        self.project_dir = Path(project_dir)
        self._backup_dir = self.project_dir / '.raica' / 'backups'
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # RAICA Server integration (optional)
        self._raica_server_url = raica_server_url or "http://localhost:5000"
        self._raica_available: Optional[bool] = None  # None = not checked yet
        self._raica_client = None

        # Communication Hub integration (optional)
        self._comm_hub: Optional[CommunicationHubTools] = None
        if _COMMUNICATION_HUB_AVAILABLE:
            try:
                self._comm_hub = CommunicationHubTools(self.project_dir)
            except Exception as e:
                logger.warning(f"Failed to initialize CommunicationHubTools: {e}")

        # Register tools (includes conditional RAICA tools)
        self._tools: Dict[str, Callable] = self._register_tools()
    
    
    # Mapping of common synonyms to canonical argument names
    ARGUMENT_MAPPINGS = {
        "path": ["filename", "file", "filepath", "target_file", "source_file"],
        "content": ["code", "text", "body", "data", "new_content", "file_content"],
        "search": ["old_content", "find", "pattern", "original", "match", "old_text", "search_text"],
        "replace": ["replacement", "substitute", "new_text", "replace_text", "replacement_text"],
        "command": ["cmd", "script", "execution", "cli"],
        "packages": ["libs", "libraries", "modules", "extensions", "pkg"],
    }
    
    def _register_tools(self) -> Dict[str, Callable]:
        """Register all available tools."""
        return {
            # File reading/writing
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            
            # Surgical line-based editing
            "get_line": self.get_line,
            "get_lines_range": self.get_lines_range,
            "replace_line": self.replace_line,
            "insert_line": self.insert_line,
            "search_with_context": self.search_with_context,
            
            # File management
            "find_file": self.find_file,
            "copy_file": self.copy_file,
            "move_file": self.move_file,
            "delete_file": self.delete_file,
            "change_permissions": self.change_permissions,
            
            # Search and navigation
            "grep_search": self.grep_search,
            "list_files": self.list_files,
            
            # Execution
            "run_command": self.run_command,
            "pip_install": self.pip_install,
            "validate_syntax": self.validate_syntax,
            "run_python": self.run_python,
            
            # Analysis
            "get_symbols": self.get_symbols,
            "sanitize_requirements": self.sanitize_requirements,
            "analyze_project": self.analyze_project,
            "check_lint": self.check_lint,
            "format_file": self.format_file,
            "dependency_check": self.dependency_check,
            
            # Version Control & Backups
            "get_backups": self.get_backups,
            "restore_backup": self.restore_backup,
            "git_diff": self.git_diff,
            
            # [IMPROVEMENT] Aliases for common LLM hallucinations
            "modify_file": self.edit_file,
            "change_file": self.edit_file,
            "update_file": self.edit_file,
            "create_file": self.write_file,
            "make_file": self.write_file,
            "read_code": self.read_file,
            "ls": self.list_files,
            "grep": self.grep_search,
            "search": self.grep_search,
            "execute_command": self.run_command,
            "run_cmd": self.run_command,
            "install_package": self.pip_install,
            
            # Project Structure
            "get_project_tree": self.get_project_tree,

            # Testing
            "create_test": self.create_test,
            "run_tests": self.run_tests,

            # Web/Remote Document Fetching
            "fetch_url": self.fetch_url,
            "fetch_documentation": self.fetch_documentation,
            "fetch_manpage": self.fetch_manpage,

            # Aliases for common LLM variations
            "read_url": self.fetch_url,
            "get_url": self.fetch_url,
            "http_get": self.fetch_url,
            "read_webpage": self.fetch_url,
            "read_manual": self.fetch_manpage,
            "man": self.fetch_manpage,

            # RAICA Server Tools (conditionally available)
            # These will return "not available" if server is down
            "raica_search_web": self.raica_search_web,
            "raica_search_docs": self.raica_search_docs,
            "raica_lookup_api": self.raica_lookup_api,
            "raica_search_patterns": self.raica_search_patterns,

            # Aliases
            "search_web": self.raica_search_web,
            "search_news": self.raica_search_web,
            "research": self.raica_search_web,

            # Communication Hub Tools
            "get_available_channels": self.get_available_channels,
            "get_channel_config": self.get_channel_config,
            "execute_social_operation": self.execute_social_operation,

            # Communication Hub Aliases
            "list_channels": self.get_available_channels,
            "social_media": self.execute_social_operation,
            "twitter": self.execute_social_operation,
        }
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return list(self._tools.keys())
    
    def get_tool_schema(self) -> List[Dict]:
        """
        Returns OpenAI-compatible tool schema for LLM.
        
        This schema can be included in the system prompt to tell
        the LLM what tools are available and how to call them.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file from project root"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file (creates or overwrites)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file"
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to write to the file"
                            }
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit a file by replacing specific text (SEARCH/REPLACE)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file"
                            },
                            "search": {
                                "type": "string",
                                "description": "Exact text to search for in the file"
                            },
                            "replace": {
                                "type": "string",
                                "description": "Text to replace the search text with"
                            }
                        },
                        "required": ["path", "search", "replace"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "replace_line",
                    "description": "Replace a specific line in a file by line number (SURGICAL EDIT)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file"
                            },
                            "line_number": {
                                "type": "integer",
                                "description": "Line number to replace (1-indexed)"
                            },
                            "new_content": {
                                "type": "string",
                                "description": "New content for the line"
                            }
                        },
                        "required": ["path", "line_number", "new_content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "insert_line",
                    "description": "Insert a line at a specific line number (SURGICAL EDIT)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file"
                            },
                            "line_number": {
                                "type": "integer",
                                "description": "Line number to insert AT (shifts existing lines down)"
                            },
                            "new_content": {
                                "type": "string",
                                "description": "Content to insert"
                            }
                        },
                        "required": ["path", "line_number", "new_content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_search",
                    "description": "Search for a pattern in files",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Text or regex pattern to search for"
                            },
                            "scope": {
                                "type": "string",
                                "description": "Glob pattern for files to search (e.g., '*.py', '**/*.txt')"
                            },
                            "regex": {
                                "type": "boolean",
                                "description": "Whether to treat pattern as regex (default: false)"
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files in a directory matching a pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Directory to list (default: project root)"
                            },
                            "pattern": {
                                "type": "string",
                                "description": "Glob pattern to match (e.g., '*.py')"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Execute a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Command to execute"
                            },
                            "cwd": {
                                "type": "string",
                                "description": "Working directory (default: project root)"
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "pip_install",
                    "description": "Install Python packages using pip",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "packages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of package names to install"
                            }
                        },
                        "required": ["packages"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "validate_syntax",
                    "description": "Check if a Python file has valid syntax",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to Python file to validate"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "Run a Python script and capture output",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script": {
                                "type": "string",
                                "description": "Path to Python script to run"
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds (default: 30)"
                            }
                        },
                        "required": ["script"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_symbols",
                    "description": "Extract function and class names from a Python file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to Python file"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sanitize_requirements",
                    "description": "Clean requirements.txt by removing invalid entries (stdlib, local modules)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            # ─────────────────────────────────────────────────────
            # SURGICAL LINE-BASED EDITING TOOLS
            # ─────────────────────────────────────────────────────
            {
                "type": "function",
                "function": {
                    "name": "get_line",
                    "description": "Get a specific line from a file by line number (1-indexed)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "line_number": {"type": "integer", "description": "Line number (1-indexed)"}
                        },
                        "required": ["path", "line_number"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_lines_range",
                    "description": "Get a range of lines with line numbers. Returns 10 lines before and after the target by default.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "start_line": {"type": "integer", "description": "Starting line number"},
                            "end_line": {"type": "integer", "description": "Ending line number (optional)"},
                            "context": {"type": "integer", "description": "Lines of context before/after (default: 10)"}
                        },
                        "required": ["path", "start_line"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "replace_line",
                    "description": "Replace a specific line by line number. Example: replace_line(path='config.py', line_number=42, new_content='    if a > b:  # fixed comparison')",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "line_number": {"type": "integer", "description": "Line number to replace (1-indexed)"},
                            "new_content": {"type": "string", "description": "New content for the line"}
                        },
                        "required": ["path", "line_number", "new_content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "insert_line",
                    "description": "Insert a new line after a specific line number (0 = beginning of file)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "after_line": {"type": "integer", "description": "Line number after which to insert"},
                            "content": {"type": "string", "description": "Content of the new line"}
                        },
                        "required": ["path", "after_line", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_with_context",
                    "description": "Search for a pattern in a file and return 10 lines before and after each match",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "pattern": {"type": "string", "description": "Text or regex to search for"},
                            "context_lines": {"type": "integer", "description": "Lines of context (default: 10)"},
                            "regex": {"type": "boolean", "description": "Treat pattern as regex (default: false)"}
                        },
                        "required": ["path", "pattern"]
                    }
                }
            },
            # ─────────────────────────────────────────────────────
            # FILE MANAGEMENT TOOLS
            # ─────────────────────────────────────────────────────
            {
                "type": "function",
                "function": {
                    "name": "find_file",
                    "description": "Find files by name or pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Filename or pattern to search for"},
                            "directory": {"type": "string", "description": "Starting directory (default: project root)"},
                            "exact": {"type": "boolean", "description": "Match exact filename (default: false)"}
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "copy_file",
                    "description": "Copy a file or directory",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "Source path"},
                            "destination": {"type": "string", "description": "Destination path"}
                        },
                        "required": ["source", "destination"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "move_file",
                    "description": "Move or rename a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "Source path"},
                            "destination": {"type": "string", "description": "Destination path"}
                        },
                        "required": ["source", "destination"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_file",
                    "description": "Delete a file (backs up by default)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to delete"},
                            "create_backup": {"type": "boolean", "description": "Backup instead of permanent delete (default: true)"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "change_permissions",
                    "description": "Change file permissions",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "mode": {"type": "string", "description": "Permission mode (e.g., '755', '644', 'u+x')"}
                        },
                        "required": ["path", "mode"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_project",
                    "description": "Analyze project structure, size, and vital files",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_lint",
                    "description": "Run linter (flake8/pylint) on a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to lint"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "format_file",
                    "description": "Format a file using standard formatters (black/autopep8)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to format"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "dependency_check",
                    "description": "Check if imported modules are installed",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_backups",
                    "description": "List available backups",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "restore_backup",
                    "description": "Restore a file from a specific backup",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "backup_name": {"type": "string", "description": "Name of the backup file to restore"}
                        },
                        "required": ["backup_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "git_diff",
                    "description": "Show uncommitted changes (git diff)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_project_tree",
                    "description": "Get a hierarchical tree view of the project files",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_test",
                    "description": "Create a unit test file for a target file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_file": {"type": "string", "description": "Path to the file to create tests for"},
                            "test_content": {"type": "string", "description": "Optional content for the test file"}
                        },
                        "required": ["target_file"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_tests",
                    "description": "Run project tests (pytest)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Specific test path to run (optional)"}
                        },
                        "required": []
                    }
                }
            },
            # Web/Remote Document Fetching Tools
            {
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "description": "Fetch content from a URL (web page, documentation, API docs). Returns text content extracted from HTML.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Full URL to fetch (e.g., https://example.com/docs)"},
                            "max_length": {"type": "integer", "description": "Maximum content length to return (default: 10000)"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_documentation",
                    "description": "Fetch documentation from common sources (PyPI, npm, MDN, etc.). Optimized for technical docs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Documentation URL"},
                            "selector": {"type": "string", "description": "CSS selector to extract specific content (optional)"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_manpage",
                    "description": "Fetch a Unix/Linux man page. Can use local 'man' command or fetch from online sources like man7.org.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Command name (e.g., 'grep', 'awk', 'sed')"},
                            "section": {"type": "string", "description": "Man page section (1=commands, 2=syscalls, 3=library, etc.)"},
                            "url": {"type": "string", "description": "Direct URL to man page (optional, overrides command lookup)"}
                        },
                        "required": ["command"]
                    }
                }
            },
            # RAICA Server Tools (conditionally available)
            {
                "type": "function",
                "function": {
                    "name": "raica_search_web",
                    "description": "Search the web for information via RAICA server. Use for news, documentation, tutorials, etc. Returns structured search results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query (e.g., 'Python asyncio best practices')"},
                            "max_results": {"type": "integer", "description": "Maximum results to return (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "raica_search_docs",
                    "description": "Search documentation and technical documents via RAICA server. Optimized for finding library/framework documentation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Documentation search query"},
                            "max_results": {"type": "integer", "description": "Maximum results to return (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "raica_lookup_api",
                    "description": "Look up API documentation via RAICA server. Get endpoints, parameters, usage examples for libraries and services.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "api_name": {"type": "string", "description": "Name of the API or library (e.g., 'requests', 'pandas', 'OpenAI')"},
                            "topic": {"type": "string", "description": "Specific topic to focus on (optional)"}
                        },
                        "required": ["api_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "raica_search_patterns",
                    "description": "Search for implementation patterns and best practices via RAICA server. Get design patterns, code structure suggestions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "requirements": {"type": "array", "items": {"type": "string"}, "description": "List of requirements to find patterns for"},
                            "language": {"type": "string", "description": "Programming language (default: python)"}
                        },
                        "required": ["requirements"]
                    }
                }
            },
            # Communication Hub Tools
            {
                "type": "function",
                "function": {
                    "name": "get_available_channels",
                    "description": "List all configured communication channels (Twitter, email, etc.) with their status and capabilities. Use this to check what social media channels are available.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_channel_config",
                    "description": "Get configuration for a specific communication channel (Twitter, email, etc.). Returns settings, rate limits, and content limits - but NOT credentials.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel name (e.g., 'twitter', 'email', 'slack')"}
                        },
                        "required": ["channel"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_social_operation",
                    "description": "Execute a social media operation. Supported operations: Twitter (post, get_user_tweets, get_tweet_replies, get_mentions). Use get_available_channels to see what's enabled.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel name (e.g., 'twitter')"},
                            "operation": {"type": "string", "description": "Operation type: 'post', 'get_user_tweets', 'get_tweet_replies', 'get_mentions'"},
                            "parameters": {
                                "type": "object",
                                "description": "Operation-specific parameters. For post: {text, media_urls, reply_to_tweet_id}. For get_user_tweets: {limit}. For get_tweet_replies: {tweet_id, limit}. For get_mentions: {limit}."
                            }
                        },
                        "required": ["channel", "operation"]
                    }
                }
            }
        ]
    
    # Required arguments for each tool
    TOOL_REQUIRED_ARGS = {
        "read_file": ["path"],
        "write_file": ["path", "content"],
        "edit_file": ["path", "search", "replace"],
        "grep_search": ["pattern"],
        "list_files": [],
        "run_command": ["command"],
        "pip_install": ["packages"],
        "validate_syntax": ["path"],
        "run_python": ["script"],
        "get_symbols": ["path"],
        "sanitize_requirements": [],
        "get_line": ["path", "line_number"],
        "get_lines_range": ["path", "start_line"],
        "replace_line": ["path", "line_number", "new_content"],
        "insert_line": ["path", "after_line", "content"],
        "search_with_context": ["path", "pattern"],
        "find_file": ["name"],
        "copy_file": ["source", "destination"],
        "move_file": ["source", "destination"],
        "delete_file": ["path"],
        "change_permissions": ["path", "mode"],
        "analyze_project": [],
        "create_test": ["target_file"],
        "run_tests": [],
        "git_diff": [],
        "get_backups": [],
        "restore_backup": ["backup_name"],
        "check_lint": ["path"],
        "format_file": ["path"],
        "dependency_check": [],
        "get_project_tree": [],
        # Web/Remote Document Fetching
        "fetch_url": ["url"],
        "fetch_documentation": ["url"],
        "fetch_manpage": ["command"],
        # RAICA Server Tools
        "raica_search_web": ["query"],
        "raica_search_docs": ["query"],
        "raica_lookup_api": ["api_name"],
        "raica_search_patterns": ["requirements"],
        # Communication Hub Tools
        "get_available_channels": [],
        "get_channel_config": ["channel"],
        "execute_social_operation": ["channel", "operation"],
    }

    
    def _normalize_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize arguments by mapping synonyms to canonical names.
        
        Args:
            tool_name: Name of the tool
            args: Raw arguments dictionary
            
        Returns:
            Normalized arguments dictionary
        """
        normalized = args.copy()
        
        # Get required args for this tool to know what we are looking for
        required_args = self.TOOL_REQUIRED_ARGS.get(tool_name, [])
        
        for canon, synonyms in self.ARGUMENT_MAPPINGS.items():
            # Only try to map if:
            # 1. The canonical arg is missing
            # 2. It IS a required arg for satisfy this tool (or commonly used)
            if canon not in normalized:
                # Check all synonyms
                for syn in synonyms:
                    if syn in normalized:
                        # Found a match! Move the value to the canonical key
                        logger.info(f"Normalizing argument for {tool_name}: {syn} -> {canon}")
                        normalized[canon] = normalized.pop(syn)
                        break
        
        return normalized

    def validate_args(self, tool_name: str, args: Dict[str, Any]) -> tuple:
        """
        Validate that required arguments are present for a tool.

        Args:
            tool_name: Name of the tool
            args: Arguments dictionary

        Returns:
            Tuple of (is_valid: bool, error_message: str or None)
        """
        if tool_name not in self.TOOL_REQUIRED_ARGS:
            # Unknown tool, let execute() handle it
            return True, None

        required = self.TOOL_REQUIRED_ARGS[tool_name]
        missing = []

        for arg in required:
            if arg not in args or args[arg] is None:
                missing.append(arg)
            elif arg == "packages" and isinstance(args[arg], list) and len(args[arg]) == 0:
                missing.append(arg + " (empty list)")

        if missing:
            return False, f"Missing required arguments for {tool_name}: {missing}"

        return True, None

    def execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name with given arguments.

        Args:
            tool_name: Name of the tool to execute
            args: Dictionary of arguments for the tool

        Returns:
            ToolResult with success status and result/error
        """
        # Check for skip flag (from _step_to_args)
        if args.get("_skip"):
            reason = args.get("_reason", "Skipped")
            return ToolResult(success=False, error=f"Skipped: {reason}")

        # Remove internal flags before execution
        clean_args = {k: v for k, v in args.items() if not k.startswith("_")}

        if tool_name not in self._tools:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}. Available: {list(self._tools.keys())}"
            )

        # Validate arguments before execution
        # Normalize synonyms first
        clean_args = self._normalize_args(tool_name, clean_args)
        
        # [IMPROVEMENT] Smart heuristics for tool confusion
        if tool_name == "edit_file":
             # Case 1: LLM wants to overwrite file (uses path + content, no search)
             if "search" not in clean_args and "content" in clean_args:
                 logger.warning(f"Redirecting edit_file to write_file (missing 'search', found 'content')")
                 tool_name = "write_file"
             # Case 2: LLM uses 'content' instead of 'replace' (uses path + search + content)
             elif "search" in clean_args and "content" in clean_args and "replace" not in clean_args:
                 logger.warning(f"Mapping 'content' to 'replace' for edit_file")
                 clean_args["replace"] = clean_args.pop("content")
        
        is_valid, error_msg = self.validate_args(tool_name, clean_args)
        if not is_valid:
            return ToolResult(success=False, error=error_msg)

        try:
            logger.info(f"Executing tool: {tool_name}({clean_args})")
            result = self._tools[tool_name](**clean_args)
            return result if isinstance(result, ToolResult) else ToolResult(success=True, result=result)
        except TypeError as e:
            # Provide more helpful error for argument mismatches
            error_msg = str(e)
            if "got an unexpected keyword argument" in error_msg:
                # Extract the bad argument name
                import re
                match = re.search(r"'(\w+)'", error_msg)
                bad_arg = match.group(1) if match else "unknown"
                return ToolResult(
                    success=False,
                    error=f"Invalid argument '{bad_arg}' for {tool_name}. Check the tool schema for valid arguments.",
                    metadata={"invalid_arg": bad_arg}
                )
            elif "missing" in error_msg.lower() and "required" in error_msg.lower():
                return ToolResult(
                    success=False,
                    error=f"Missing required argument for {tool_name}: {e}",
                    metadata={"missing_args": True}
                )
            return ToolResult(success=False, error=f"Invalid arguments for {tool_name}: {e}")
        except FileNotFoundError as e:
            return ToolResult(
                success=False,
                error=f"File not found: {e}",
                metadata={"file_not_found": True}
            )
        except PermissionError as e:
            return ToolResult(
                success=False,
                error=f"Permission denied: {e}",
                metadata={"permission_error": True}
            )
        except TimeoutError as e:
            return ToolResult(
                success=False,
                error=f"Operation timed out: {e}",
                metadata={"timeout": True}
            )
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {type(e).__name__}: {e}",
                metadata={"exception_type": type(e).__name__}
            )
    
    # =========================================================================
    # TOOL IMPLEMENTATIONS
    # =========================================================================
    
    def read_file(self, path: str) -> ToolResult:
        """Read the contents of a file."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            if not file_path.is_file():
                return ToolResult(success=False, error=f"Not a file: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            return ToolResult(
                success=True,
                result=content,
                metadata={"path": path, "size": len(content), "lines": content.count('\n') + 1}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read {path}: {e}")
    
    def write_file(self, path: str, content: str) -> ToolResult:
        """Write content to a file, creating backup first."""
        try:
            file_path = self.project_dir / path
            
            # Create backup if file exists
            if file_path.exists():
                import shutil
                from datetime import datetime
                backup_name = f"{file_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_path = self._backup_dir / backup_name
                shutil.copy2(file_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write content
            file_path.write_text(content, encoding='utf-8')
            
            return ToolResult(
                success=True,
                result=f"Written {len(content)} bytes to {path}",
                metadata={"path": path, "size": len(content)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write {path}: {e}")
    
    def edit_file(self, path: str, search: str, replace: str) -> ToolResult:
        """Edit a file by replacing search text with replace text."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            # Read current content
            content = file_path.read_text(encoding='utf-8', errors='replace')
            
            # Check if search text exists
            if search not in content:
                return ToolResult(
                    success=False,
                    error=f"Search text not found in {path}. Make sure to match exact whitespace.",
                    metadata={"file_preview": content[:500]}
                )
            
            # Count occurrences
            count = content.count(search)
            if count > 1:
                return ToolResult(
                    success=False,
                    error=f"Search text found {count} times. Please provide more context to match exactly one occurrence."
                )
            
            # Create backup
            from datetime import datetime
            backup_name = f"{file_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_path = self._backup_dir / backup_name
            file_path.rename(backup_path)
            
            # Write new content
            new_content = content.replace(search, replace, 1)
            file_path.write_text(new_content, encoding='utf-8')
            
            return ToolResult(
                success=True,
                result=f"Edited {path}: replaced {len(search)} chars with {len(replace)} chars",
                metadata={"path": path, "backup": str(backup_path)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to edit {path}: {e}")
    
    def grep_search(self, pattern: str, scope: str = "**/*.py", regex: bool = False) -> ToolResult:
        """Search for a pattern in files."""
        try:
            matches = []
            
            for file_path in self.project_dir.glob(scope):
                if not file_path.is_file():
                    continue
                if '.raica' in str(file_path) or 'venv' in str(file_path):
                    continue
                
                try:
                    content = file_path.read_text(encoding='utf-8', errors='replace')
                    for lineno, line in enumerate(content.splitlines(), 1):
                        if regex:
                            if re.search(pattern, line):
                                matches.append({
                                    "file": str(file_path.relative_to(self.project_dir)),
                                    "line": lineno,
                                    "content": line.strip()[:200]
                                })
                        else:
                            if pattern in line:
                                matches.append({
                                    "file": str(file_path.relative_to(self.project_dir)),
                                    "line": lineno,
                                    "content": line.strip()[:200]
                                })
                except Exception:
                    continue
            
            return ToolResult(
                success=True,
                result=matches[:50],  # Limit results
                metadata={"total_matches": len(matches), "pattern": pattern, "scope": scope}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")
    
    def list_files(self, directory: str = ".", pattern: str = "*") -> ToolResult:
        """List files in a directory matching a pattern."""
        try:
            dir_path = self.project_dir / directory
            if not dir_path.exists():
                return ToolResult(success=False, error=f"Directory not found: {directory}")
            
            files = []
            for file_path in dir_path.glob(pattern):
                if '.raica' in str(file_path) or 'venv' in str(file_path):
                    continue
                files.append({
                    "path": str(file_path.relative_to(self.project_dir)),
                    "is_dir": file_path.is_dir(),
                    "size": file_path.stat().st_size if file_path.is_file() else None
                })
            
            return ToolResult(
                success=True,
                result=files[:100],
                metadata={"directory": directory, "pattern": pattern, "count": len(files)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"List failed: {e}")
    
    def run_command(self, command: str, cwd: str = None) -> ToolResult:
        """Execute a shell command."""
        try:
            work_dir = self.project_dir / cwd if cwd else self.project_dir
            
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(work_dir)
            )
            
            return ToolResult(
                success=result.returncode == 0,
                result={
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "returncode": result.returncode
                },
                metadata={"command": command}
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Command timed out after 60 seconds")
        except Exception as e:
            return ToolResult(success=False, error=f"Command failed: {e}")
    
    def pip_install(self, packages: List[str]) -> ToolResult:
        """Install Python packages using pip."""
        try:
            if not packages:
                return ToolResult(success=False, error="No packages specified")
            
            # Filter out invalid packages
            valid_packages = [p for p in packages if p.lower().replace('-', '_') not in self.STDLIB_MODULES]
            
            if not valid_packages:
                return ToolResult(success=True, result="No packages to install (all were stdlib)")
            
            result = subprocess.run(
                ['pip', 'install'] + valid_packages,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            return ToolResult(
                success=result.returncode == 0,
                result={
                    "installed": valid_packages if result.returncode == 0 else [],
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:1000]
                }
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="pip install timed out")
        except Exception as e:
            return ToolResult(success=False, error=f"pip install failed: {e}")
    
    def validate_syntax(self, path: str) -> ToolResult:
        """Check if a Python file has valid syntax."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            result = subprocess.run(
                ['python', '-m', 'py_compile', str(file_path)],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return ToolResult(success=True, result=f"{path} has valid syntax")
            else:
                return ToolResult(
                    success=False,
                    error=f"Syntax error in {path}",
                    metadata={"stderr": result.stderr}
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Validation failed: {e}")
    
    def run_python(self, script: str, timeout: int = 30) -> ToolResult:
        """Run a Python script and capture output."""
        try:
            script_path = self.project_dir / script
            if not script_path.exists():
                return ToolResult(success=False, error=f"Script not found: {script}")
            
            result = subprocess.run(
                ['python', str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.project_dir)
            )
            
            return ToolResult(
                success=result.returncode == 0,
                result={
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "returncode": result.returncode
                }
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Script timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to run script: {e}")
    
    def get_symbols(self, path: str) -> ToolResult:
        """Extract function and class names from a Python file."""
        try:
            import ast
            
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(content)
            
            symbols = {
                "functions": [],
                "classes": [],
                "constants": []
            }
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols["functions"].append(node.name)
                elif isinstance(node, ast.ClassDef):
                    symbols["classes"].append(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            symbols["constants"].append(target.id)
            
            return ToolResult(success=True, result=symbols, metadata={"path": path})
        except SyntaxError as e:
            return ToolResult(success=False, error=f"Syntax error in {path}: {e}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to parse {path}: {e}")
    
    def sanitize_requirements(self) -> ToolResult:
        """Clean requirements.txt by removing invalid entries."""
        try:
            req_path = self.project_dir / 'requirements.txt'
            if not req_path.exists():
                return ToolResult(success=False, error="requirements.txt not found")
            
            # Get local project modules
            local_modules = set()
            for f in self.project_dir.rglob('*.py'):
                local_modules.add(f.stem.lower())
            for d in self.project_dir.iterdir():
                if d.is_dir() and (d / '__init__.py').exists():
                    local_modules.add(d.name.lower())
            
            # Read and clean
            content = req_path.read_text()
            cleaned_lines = []
            removed = []
            
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    cleaned_lines.append(line)
                    continue
                
                match = re.match(r'^([a-zA-Z0-9_-]+)', stripped)
                if match:
                    pkg_name = match.group(1).lower().replace('-', '_')
                    if pkg_name in self.STDLIB_MODULES or pkg_name in local_modules:
                        removed.append(stripped)
                        continue
                
                cleaned_lines.append(line)
            
            if removed:
                req_path.write_text('\n'.join(cleaned_lines) + '\n')
            
            return ToolResult(
                success=True,
                result={"removed": removed, "remaining_lines": len(cleaned_lines)},
                metadata={"cleaned": len(removed) > 0}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Sanitization failed: {e}")
    
    # =========================================================================
    # SURGICAL LINE-BASED EDITING TOOLS
    # =========================================================================
    
    def get_line(self, path: str, line_number: int) -> ToolResult:
        """Get a specific line from a file by line number (1-indexed)."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = content.splitlines()
            
            if line_number < 1 or line_number > len(lines):
                return ToolResult(
                    success=False,
                    error=f"Line {line_number} out of range. File has {len(lines)} lines."
                )
            
            return ToolResult(
                success=True,
                result={
                    "line_number": line_number,
                    "content": lines[line_number - 1],
                    "total_lines": len(lines)
                },
                metadata={"path": path}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to get line: {e}")
    
    def get_lines_range(
        self, path: str, start_line: int, end_line: int = None, context: int = 10
    ) -> ToolResult:
        """
        Get a range of lines from a file with line numbers.
        
        Args:
            path: File path
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (inclusive). If None, uses start_line + context*2
            context: Default number of lines before/after if end_line not specified
        """
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = content.splitlines()
            total = len(lines)
            
            # Calculate range
            if end_line is None:
                end_line = min(start_line + context, total)
                start_line = max(1, start_line - context)
            
            start_line = max(1, start_line)
            end_line = min(end_line, total)
            
            # Extract lines with numbers
            result_lines = []
            for i in range(start_line - 1, end_line):
                result_lines.append({
                    "line_number": i + 1,
                    "content": lines[i]
                })
            
            return ToolResult(
                success=True,
                result={
                    "lines": result_lines,
                    "start": start_line,
                    "end": end_line,
                    "total_lines": total
                },
                metadata={"path": path}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to get lines: {e}")
    
    def replace_line(self, path: str, line_number: int, new_content: str) -> ToolResult:
        """
        Replace a specific line in a file by line number.
        
        Args:
            path: File path
            line_number: Line number to replace (1-indexed)
            new_content: New content for the line
        """
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = content.splitlines()
            
            if line_number < 1 or line_number > len(lines):
                return ToolResult(
                    success=False,
                    error=f"Line {line_number} out of range. File has {len(lines)} lines."
                )
            
            # Create backup
            from datetime import datetime
            backup_name = f"{file_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_path = self._backup_dir / backup_name
            import shutil
            shutil.copy2(file_path, backup_path)
            
            # Store old line for result
            old_content = lines[line_number - 1]
            
            # Replace the line
            lines[line_number - 1] = new_content
            
            # Write back
            file_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            
            return ToolResult(
                success=True,
                result={
                    "line_number": line_number,
                    "old_content": old_content,
                    "new_content": new_content
                },
                metadata={"path": path, "backup": str(backup_path)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to replace line: {e}")
    
    def insert_line(self, path: str, line_number: int, new_content: str) -> ToolResult:
        """
        Insert a new line AT a specific line number (shifting existing lines down).
        
        Args:
            path: File path
            line_number: Line number where new content should appear (1-indexed)
            new_content: Content of the new line
        """
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            file_content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = file_content.splitlines()
            
            # Allow inserting at end (len(lines) + 1)
            if line_number < 1 or line_number > len(lines) + 1:
                return ToolResult(
                    success=False,
                    error=f"Line {line_number} out of range. File has {len(lines)} lines (max insert index {len(lines)+1})."
                )
            
            # Create backup
            from datetime import datetime
            backup_name = f"{file_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_path = self._backup_dir / backup_name
            import shutil
            shutil.copy2(file_path, backup_path)
            
            # Insert the line (1-based to 0-based conversion)
            insert_index = line_number - 1
            lines.insert(insert_index, new_content)
            
            # Write back
            file_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            
            return ToolResult(
                success=True,
                result={
                    "inserted_at_line": line_number,
                    "content": new_content,
                    "new_total_lines": len(lines)
                },
                metadata={"path": path, "backup": str(backup_path)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to insert line: {e}")
    
    def search_with_context(
        self, path: str, pattern: str, context_lines: int = 10, regex: bool = False
    ) -> ToolResult:
        """
        Search for a pattern in a file and return matches with surrounding context.
        
        Args:
            path: File path
            pattern: Text or regex pattern to search
            context_lines: Number of lines before and after each match
            regex: Whether to treat pattern as regex
        """
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8', errors='replace')
            lines = content.splitlines()
            total = len(lines)
            
            matches = []
            for i, line in enumerate(lines, 1):
                found = False
                if regex:
                    if re.search(pattern, line):
                        found = True
                else:
                    if pattern in line:
                        found = True
                
                if found:
                    # Get context
                    start = max(1, i - context_lines)
                    end = min(total, i + context_lines)
                    
                    context = []
                    for j in range(start, end + 1):
                        context.append({
                            "line_number": j,
                            "content": lines[j - 1],
                            "is_match": (j == i)
                        })
                    
                    matches.append({
                        "match_line": i,
                        "match_content": line,
                        "context": context
                    })
            
            return ToolResult(
                success=True,
                result={
                    "matches": matches[:20],  # Limit results
                    "total_matches": len(matches),
                    "pattern": pattern
                },
                metadata={"path": path, "total_lines": total}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")
    
    # =========================================================================
    # FILE MANAGEMENT TOOLS
    # =========================================================================
    
    def find_file(self, name: str, directory: str = ".", exact: bool = False) -> ToolResult:
        """
        Find files by name pattern.
        
        Args:
            name: Filename or pattern to search for
            directory: Starting directory
            exact: If True, match exact filename. If False, use glob pattern.
        """
        try:
            dir_path = self.project_dir / directory
            if not dir_path.exists():
                return ToolResult(success=False, error=f"Directory not found: {directory}")
            
            found = []
            if exact:
                # Exact match - walk directories
                for f in dir_path.rglob(name):
                    if '.raica' not in str(f) and 'venv' not in str(f):
                        found.append({
                            "path": str(f.relative_to(self.project_dir)),
                            "size": f.stat().st_size if f.is_file() else None,
                            "is_dir": f.is_dir()
                        })
            else:
                # Pattern match
                pattern = f"**/*{name}*" if '*' not in name else f"**/{name}"
                for f in dir_path.glob(pattern):
                    if '.raica' not in str(f) and 'venv' not in str(f):
                        found.append({
                            "path": str(f.relative_to(self.project_dir)),
                            "size": f.stat().st_size if f.is_file() else None,
                            "is_dir": f.is_dir()
                        })
            
            return ToolResult(
                success=True,
                result=found[:50],
                metadata={"name": name, "total_found": len(found)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Find failed: {e}")
    
    def copy_file(self, source: str, destination: str) -> ToolResult:
        """Copy a file to a new location."""
        try:
            import shutil
            
            src_path = self.project_dir / source
            dst_path = self.project_dir / destination
            
            if not src_path.exists():
                return ToolResult(success=False, error=f"Source not found: {source}")
            
            # Create destination directory if needed
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
            
            return ToolResult(
                success=True,
                result=f"Copied {source} to {destination}",
                metadata={"source": source, "destination": destination}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Copy failed: {e}")
    
    def move_file(self, source: str, destination: str) -> ToolResult:
        """Move/rename a file."""
        try:
            import shutil
            
            src_path = self.project_dir / source
            dst_path = self.project_dir / destination
            
            if not src_path.exists():
                return ToolResult(success=False, error=f"Source not found: {source}")
            
            # Create destination directory if needed
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.move(str(src_path), str(dst_path))
            
            return ToolResult(
                success=True,
                result=f"Moved {source} to {destination}",
                metadata={"source": source, "destination": destination}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Move failed: {e}")
    
    def delete_file(self, path: str, create_backup: bool = True) -> ToolResult:
        """
        Delete a file (with backup by default).
        
        Args:
            path: File path to delete
            create_backup: If True, move to backup dir instead of permanent delete
        """
        try:
            import shutil
            from datetime import datetime
            
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            if create_backup:
                backup_name = f"{file_path.name}.deleted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_path = self._backup_dir / backup_name
                shutil.move(str(file_path), str(backup_path))
                return ToolResult(
                    success=True,
                    result=f"Deleted {path} (backed up to {backup_name})",
                    metadata={"path": path, "backup": str(backup_path)}
                )
            else:
                if file_path.is_dir():
                    shutil.rmtree(file_path)
                else:
                    file_path.unlink()
                return ToolResult(
                    success=True,
                    result=f"Permanently deleted {path}",
                    metadata={"path": path}
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Delete failed: {e}")
    
    def change_permissions(self, path: str, mode: str) -> ToolResult:
        """
        Change file permissions.
        
        Args:
            path: File path
            mode: Permission mode (e.g., "755", "644", "u+x")
        """
        try:
            import os
            import stat
            
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            
            # Parse mode
            if mode.isdigit() and len(mode) == 3:
                # Octal mode like "755"
                new_mode = int(mode, 8)
                os.chmod(file_path, new_mode)
            elif '+' in mode or '-' in mode:
                # Symbolic mode like "u+x"
                current = file_path.stat().st_mode
                
                if 'x' in mode:
                    if '+x' in mode:
                        new_mode = current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    else:
                        new_mode = current & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    os.chmod(file_path, new_mode)
                else:
                    return ToolResult(success=False, error=f"Unsupported symbolic mode: {mode}")
            else:
                return ToolResult(success=False, error=f"Invalid mode: {mode}. Use octal (755) or symbolic (u+x)")
            
            # Get new permissions
            new_perms = oct(file_path.stat().st_mode)[-3:]
            
            return ToolResult(
                success=True,
                result=f"Changed permissions of {path} to {new_perms}",
                metadata={"path": path, "mode": new_perms}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Permission change failed: {e}")


    # =========================================================================
    # NEW DEBUG TOOLS (PHASE 2.2)
    # =========================================================================

    def analyze_project(self) -> ToolResult:
        """Analyze project structure, size, and vital files."""
        try:
            total_size = 0
            file_count = 0
            extensions = {}
            structure = []
            
            # Vital files check
            vital_files = ['requirements.txt', 'setup.py', 'pyproject.toml', 'README.md', '.gitignore']
            found_vitals = []
            
            for path in self.project_dir.rglob('*'):
                if '.raica' in str(path) or 'venv' in str(path) or '__pycache__' in str(path) or '.git' in str(path):
                    continue
                
                if path.is_file():
                    size = path.stat().st_size
                    total_size += size
                    file_count += 1
                    ext = path.suffix
                    extensions[ext] = extensions.get(ext, 0) + 1
                    
                    if path.name in vital_files:
                        found_vitals.append(path.name)
                        
            return ToolResult(
                success=True,
                result={
                    "total_files": file_count,
                    "total_size_bytes": total_size,
                    "extensions": extensions,
                    "vital_files_found": found_vitals,
                    "missing_vitals": list(set(vital_files) - set(found_vitals))
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Analysis failed: {e}")

    def check_lint(self, path: str) -> ToolResult:
        """Run linter (pylint/flake8) on a file."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")

            # Try flake8 first, then pylint
            linter = 'flake8'
            cmd = ['flake8', str(file_path)]
            
            # Check if flake8 is installed
            try:
                subprocess.run(['flake8', '--version'], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                linter = 'pylint'
                cmd = ['pylint', str(file_path)]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=60
            )
            
            return ToolResult(
                success=True, # Always success to return the output
                result={
                    "linter": linter,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Linting failed: {e}")
            
    def format_file(self, path: str) -> ToolResult:
        """Format a file using black or autopep8."""
        try:
            file_path = self.project_dir / path
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
                
            formatter = 'black'
            cmd = ['black', str(file_path)]
            
            try:
                subprocess.run(['black', '--version'], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                formatter = 'autopep8'
                cmd = ['autopep8', '--in-place', str(file_path)]
                
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=60
            )
            
            if result.returncode != 0:
                 return ToolResult(success=False, error=f"Formatter failed: {result.stderr}")

            return ToolResult(
                success=True,
                result=f"Formatted {path} using {formatter}"
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Formatting failed: {e}")

    def dependency_check(self) -> ToolResult:
        """Check if imported modules are installed."""
        try:
            # 1. Gather all imports
            imports = set()
            for path in self.project_dir.rglob('*.py'):
                if 'venv' in str(path) or '.raica' in str(path):
                    continue
                try:
                    content = path.read_text(encoding='utf-8', errors='replace')
                    # Simple regex for imports
                    for match in re.finditer(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE):
                        imports.add(match.group(1))
                except Exception:
                    pass
            
            # 2. Check installed packages
            import pkg_resources
            installed = {pkg.key for pkg in pkg_resources.working_set}
            
            # Add stdlib
            installed.update(self.STDLIB_MODULES)
            
            missing = []
            for imp in imports:
                if imp.lower() not in installed and imp != self.project_dir.name:
                     # Check if it's a local module
                     if not (self.project_dir / f"{imp}.py").exists() and not (self.project_dir / imp).is_dir():
                        missing.append(imp)
            
            return ToolResult(
                success=True,
                result={
                    "checked_imports": list(imports),
                    "missing_packages": missing
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Dependency check failed: {e}")

    def get_backups(self) -> ToolResult:
        """List available backups."""
        try:
            backups = []
            if self._backup_dir.exists():
                for path in self._backup_dir.glob('*'):
                    backups.append({
                        "name": path.name,
                        "original_file": path.name.split('.20')[0], # Rough guess
                        "timestamp": path.stat().st_mtime,
                        "size": path.stat().st_size
                    })
            
            return ToolResult(success=True, result=backups)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list backups: {e}")

    def restore_backup(self, backup_name: str) -> ToolResult:
        """Restore a file from a backup."""
        try:
            backup_path = self._backup_dir / backup_name
            if not backup_path.exists():
                return ToolResult(success=False, error=f"Backup not found: {backup_name}")
            
            # Infer original filename (remove timestamp suffix)
            # Format: filename.ext.YYYYMMDD_HHMMSS
            # Split by '.' and remove last part if it looks like timestamp
            parts = backup_name.split('.')
            if len(parts) > 2 and '_' in parts[-1]:
                 original_name = '.'.join(parts[:-1])
            else:
                 return ToolResult(success=False, error=f"Cannot infer original filename from {backup_name}")
            
            dest_path = self.project_dir / original_name
            
            import shutil
            shutil.copy2(backup_path, dest_path)
            
            return ToolResult(
                success=True, 
                result=f"Restored {original_name} from {backup_name}",
                metadata={"destination": str(dest_path)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Restore failed: {e}")

    def git_diff(self) -> ToolResult:
        """Show uncommitted changes."""
        try:
            result = subprocess.run(
                ['git', 'diff'],
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=10
            )
            
            if result.returncode != 0:
                 # Try to check if git repo exists
                 if not (self.project_dir / '.git').exists():
                     return ToolResult(success=False, error="Not a git repository")
                 return ToolResult(success=False, error=result.stderr)

            # Also get staged changes
            staged = subprocess.run(
                ['git', 'diff', '--cached'],
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=10
            )

            return ToolResult(
                success=True,
                result={
                    "working_tree": result.stdout[:5000],
                    "staged": staged.stdout[:5000]
                }
            )
        except FileNotFoundError:
             return ToolResult(success=False, error="git command not found")
        except Exception as e:
            return ToolResult(success=False, error=f"Git diff failed: {e}")

    def get_project_tree(self) -> ToolResult:
        """Get a hierarchical tree view of the project files."""
        try:
            def build_tree(dir_path: Path, prefix: str = "") -> List[str]:
                lines = []
                # Get files and verify permissions/existence
                try:
                    contents = list(dir_path.iterdir())
                except PermissionError:
                    return [prefix + "└── <Permission Denied>"]
                
                # Sort: directories first, then files
                contents.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
                
                pointers = [("├── ", "│   ")] * (len(contents) - 1) + [("└── ", "    ")]
                
                for pointer, entry in zip(pointers, contents):
                    if entry.name.startswith('.') or entry.name == 'venv' or entry.name == '__pycache__':
                        continue
                        
                    lines.append(f"{prefix}{pointer[0]}{entry.name}")
                    
                    if entry.is_dir():
                        lines.extend(build_tree(entry, prefix + pointer[1]))
                        
                return lines

            tree_lines = [self.project_dir.name + "/"] + build_tree(self.project_dir)
            
            return ToolResult(
                success=True,
                result="\n".join(tree_lines[:200]) # Limit output
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Tree generation failed: {e}")

    def create_test(self, target_file: str, test_content: str = None) -> ToolResult:
        """Create a unit test file for a target file."""
        try:
            target_path = self.project_dir / target_file
            if not target_path.exists():
                return ToolResult(success=False, error=f"Target file not found: {target_file}")
                
            # Determine test path
            test_dir = self.project_dir / 'tests'
            test_dir.mkdir(exist_ok=True)
            
            test_name = f"test_{target_path.stem}.py"
            test_path = test_dir / test_name
            
            if test_content:
                content = test_content
            else:
                # Generate basic stub
                content = f'''import unittest
from {target_path.stem} import *

class Test{target_path.stem.capitalize()}(unittest.TestCase):
    def test_example(self):
        """Placeholder test."""
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
'''
            if test_path.exists():
                return ToolResult(success=False, error=f"Test file already exists: {test_path}")
                
            test_path.write_text(content)
            
            return ToolResult(
                success=True,
                result=f"Created test file: tests/{test_name}",
                metadata={"path": str(test_path)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Create test failed: {e}")

    def run_tests(self, path: str = None) -> ToolResult:
        """Run project tests (pytest)."""
        try:
            cmd = ['pytest']
            if path:
                cmd.append(path)
                
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=60
            ) 
            
            return ToolResult(
                success=result.returncode == 0,
                result={
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "returncode": result.returncode
                }
            )
        except FileNotFoundError:
            return ToolResult(success=False, error="pytest not found")
        except Exception as e:
            return ToolResult(success=False, error=f"Run tests failed: {e}")

    # ==================== Web/Remote Document Fetching Tools ====================

    def fetch_url(self, url: str, max_length: int = 10000) -> ToolResult:
        """
        Fetch content from a URL and extract text.

        Supports HTML pages, plain text, and common documentation formats.
        Converts HTML to readable text.

        Args:
            url: Full URL to fetch
            max_length: Maximum content length to return (default: 10000)

        Returns:
            ToolResult with extracted text content
        """
        try:
            import urllib.request
            import urllib.error
            import ssl

            # Validate URL
            if not url.startswith(('http://', 'https://')):
                return ToolResult(success=False, error=f"Invalid URL scheme. URL must start with http:// or https://")

            # Create SSL context that doesn't verify (for self-signed certs)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Set up request with user agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; RAICA/1.0; +https://github.com/anthropics/raica)',
                'Accept': 'text/html,text/plain,application/json,*/*'
            }
            req = urllib.request.Request(url, headers=headers)

            # Fetch with timeout
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                content_type = response.headers.get('Content-Type', '')
                raw_content = response.read()

                # Detect encoding
                encoding = 'utf-8'
                if 'charset=' in content_type:
                    encoding = content_type.split('charset=')[-1].split(';')[0].strip()

                try:
                    content = raw_content.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    content = raw_content.decode('utf-8', errors='replace')

                # Convert HTML to text
                if 'text/html' in content_type or content.strip().startswith('<!'):
                    content = self._html_to_text(content)

                # Truncate if needed
                if len(content) > max_length:
                    content = content[:max_length] + f"\n\n... [Truncated, showing {max_length} of {len(content)} chars]"

                return ToolResult(
                    success=True,
                    result=content,
                    metadata={
                        "url": url,
                        "content_type": content_type,
                        "length": len(content)
                    }
                )

        except urllib.error.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP Error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            return ToolResult(success=False, error=f"URL Error: {e.reason}")
        except TimeoutError:
            return ToolResult(success=False, error="Request timed out (30s)")
        except Exception as e:
            return ToolResult(success=False, error=f"Fetch failed: {e}")

    def fetch_documentation(self, url: str, selector: str = None) -> ToolResult:
        """
        Fetch documentation from a URL, optimized for technical docs.

        Handles common documentation sites (PyPI, npm, MDN, ReadTheDocs, etc.)
        and extracts the main content.

        Args:
            url: Documentation URL
            selector: CSS selector to extract specific content (optional)

        Returns:
            ToolResult with documentation text
        """
        # First fetch the raw content
        result = self.fetch_url(url, max_length=50000)

        if not result.success:
            return result

        content = result.result

        # If a selector was provided, try to extract just that part
        if selector:
            try:
                # Simple CSS selector extraction (basic support)
                extracted = self._extract_by_selector(content, selector)
                if extracted:
                    content = extracted
            except Exception as e:
                logger.warning(f"Selector extraction failed: {e}")

        # Clean up documentation-specific noise
        content = self._clean_documentation(content, url)

        return ToolResult(
            success=True,
            result=content,
            metadata={
                "url": url,
                "selector": selector,
                "length": len(content)
            }
        )

    def fetch_manpage(self, command: str, section: str = None, url: str = None) -> ToolResult:
        """
        Fetch a Unix/Linux man page.

        Tries in order:
        1. Direct URL if provided
        2. Local 'man' command
        3. Online man page sources (man7.org, linux.die.net)

        Args:
            command: Command name (e.g., 'grep', 'awk')
            section: Man page section (optional, e.g., '1' for commands)
            url: Direct URL to man page (optional, overrides other methods)

        Returns:
            ToolResult with man page content
        """
        # If URL provided, fetch directly
        if url:
            return self.fetch_url(url, max_length=30000)

        # Try local man command first
        try:
            cmd = ['man']
            if section:
                cmd.append(section)
            cmd.append(command)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env={**subprocess.os.environ, 'MANWIDTH': '120'}  # Set width for better formatting
            )

            if result.returncode == 0 and result.stdout.strip():
                # Clean up man page output
                content = self._clean_manpage(result.stdout)
                return ToolResult(
                    success=True,
                    result=content,
                    metadata={
                        "command": command,
                        "section": section,
                        "source": "local"
                    }
                )
        except FileNotFoundError:
            logger.debug("Local 'man' command not available")
        except subprocess.TimeoutExpired:
            logger.debug("Local 'man' command timed out")
        except Exception as e:
            logger.debug(f"Local man lookup failed: {e}")

        # Fall back to online sources
        section_num = section or "1"
        online_sources = [
            f"https://man7.org/linux/man-pages/man{section_num}/{command}.{section_num}.html",
            f"https://linux.die.net/man/{section_num}/{command}",
            f"https://www.man7.org/linux/man-pages/man{section_num}/{command}.{section_num}.html",
        ]

        for source_url in online_sources:
            result = self.fetch_url(source_url, max_length=30000)
            if result.success:
                result.metadata["command"] = command
                result.metadata["section"] = section_num
                result.metadata["source"] = "online"
                return result

        return ToolResult(
            success=False,
            error=f"Could not find man page for '{command}'. Tried local man command and online sources."
        )

    def _html_to_text(self, html: str) -> str:
        """
        Convert HTML to readable plain text.

        Removes tags, scripts, styles, and extracts text content.
        """
        import re

        # Remove script and style elements
        html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.IGNORECASE)

        # Remove HTML comments
        html = re.sub(r'<!--[\s\S]*?-->', '', html)

        # Convert common block elements to newlines
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</(p|div|h[1-6]|li|tr|pre|blockquote)>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<(p|div|h[1-6]|li|tr|pre|blockquote)[^>]*>', '\n', html, flags=re.IGNORECASE)

        # Handle lists
        html = re.sub(r'<li[^>]*>', '\n• ', html, flags=re.IGNORECASE)

        # Handle code blocks - preserve content
        html = re.sub(r'<code[^>]*>([\s\S]*?)</code>', r'`\1`', html, flags=re.IGNORECASE)
        html = re.sub(r'<pre[^>]*>([\s\S]*?)</pre>', r'\n```\n\1\n```\n', html, flags=re.IGNORECASE)

        # Remove all remaining tags
        html = re.sub(r'<[^>]+>', '', html)

        # Decode HTML entities
        html = self._decode_html_entities(html)

        # Clean up whitespace
        lines = [line.strip() for line in html.split('\n')]
        lines = [line for line in lines if line]  # Remove empty lines

        # Collapse multiple blank lines
        text = '\n'.join(lines)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def _decode_html_entities(self, text: str) -> str:
        """Decode common HTML entities."""
        import html
        try:
            return html.unescape(text)
        except Exception:
            # Manual fallback for common entities
            entities = {
                '&nbsp;': ' ', '&lt;': '<', '&gt;': '>',
                '&amp;': '&', '&quot;': '"', '&#39;': "'",
                '&mdash;': '—', '&ndash;': '–', '&copy;': '©',
                '&reg;': '®', '&trade;': '™', '&hellip;': '…',
            }
            for entity, char in entities.items():
                text = text.replace(entity, char)
            return text

    def _clean_manpage(self, content: str) -> str:
        """Clean up man page output for readability."""
        import re

        # Remove backspace-based formatting (bold/underline)
        content = re.sub(r'.\x08', '', content)

        # Remove form feeds
        content = content.replace('\x0c', '\n')

        # Collapse multiple spaces
        content = re.sub(r' {2,}', '  ', content)

        return content.strip()

    def _clean_documentation(self, content: str, url: str) -> str:
        """Clean documentation content based on source."""
        import re

        # Remove common navigation elements that made it through
        noise_patterns = [
            r'Skip to [\w\s]+',
            r'Table of Contents',
            r'Previous\s*\|\s*Next',
            r'Edit on GitHub',
            r'Show Source',
            r'Quick search',
            r'\[edit\]',
        ]

        for pattern in noise_patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)

        # Clean up excessive whitespace
        content = re.sub(r'\n{4,}', '\n\n\n', content)

        return content.strip()

    def _extract_by_selector(self, html: str, selector: str) -> Optional[str]:
        """
        Extract content by CSS selector (basic support).

        Supports simple selectors: tag, .class, #id
        """
        import re

        # Handle ID selector
        if selector.startswith('#'):
            id_name = selector[1:]
            match = re.search(
                rf'<[^>]+id=["\']?{re.escape(id_name)}["\']?[^>]*>([\s\S]*?)</[^>]+>',
                html, re.IGNORECASE
            )
            if match:
                return self._html_to_text(match.group(0))

        # Handle class selector
        if selector.startswith('.'):
            class_name = selector[1:]
            match = re.search(
                rf'<[^>]+class=["\'][^"\']*{re.escape(class_name)}[^"\']*["\'][^>]*>([\s\S]*?)</[^>]+>',
                html, re.IGNORECASE
            )
            if match:
                return self._html_to_text(match.group(0))

        # Handle tag selector
        match = re.search(
            rf'<{re.escape(selector)}[^>]*>([\s\S]*?)</{re.escape(selector)}>',
            html, re.IGNORECASE
        )
        if match:
            return self._html_to_text(match.group(0))

        return None

    # ==================== RAICA Server Tools ====================

    def _check_raica_server(self) -> bool:
        """
        Check if RAICA server is available.

        Performs a health check and caches the result.
        Returns True if server is healthy and responding.
        """
        if self._raica_available is not None:
            return self._raica_available

        try:
            import urllib.request
            import urllib.error

            health_url = f"{self._raica_server_url}/health"
            req = urllib.request.Request(health_url, method='GET')
            req.add_header('User-Agent', 'RAICA-Agent/1.0')

            with urllib.request.urlopen(req, timeout=5) as response:
                self._raica_available = response.status == 200
                if self._raica_available:
                    logger.info(f"RAICA server is available at {self._raica_server_url}")
                return self._raica_available

        except Exception as e:
            logger.debug(f"RAICA server not available: {e}")
            self._raica_available = False
            return False

    def _get_raica_client(self):
        """Get or create RAICA knowledge client."""
        if self._raica_client is None:
            try:
                from ..knowledge.raica_client import RAICAKnowledgeClient
                self._raica_client = RAICAKnowledgeClient(
                    base_url=self._raica_server_url,
                    timeout=30.0,
                    enable_cache=True
                )
            except ImportError:
                logger.warning("RAICAKnowledgeClient not available")
                return None
        return self._raica_client

    def is_raica_available(self) -> bool:
        """
        Public method to check RAICA server availability.

        Returns True if server is healthy, False otherwise.
        """
        return self._check_raica_server()

    def raica_search_web(self, query: str, max_results: int = 5) -> ToolResult:
        """
        Search the web via RAICA server.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            ToolResult with search results or error
        """
        if not self._check_raica_server():
            return ToolResult(
                success=False,
                error="RAICA server is not available. Use 'fetch_url' for direct web access instead.",
                metadata={"raica_unavailable": True}
            )

        client = self._get_raica_client()
        if not client:
            return ToolResult(
                success=False,
                error="RAICA client not initialized"
            )

        try:
            import asyncio

            # Run async method synchronously
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(client.search_web(query, max_results))
            finally:
                loop.close()

            if not result.success:
                return ToolResult(
                    success=False,
                    error=result.error or "Search failed"
                )

            # Format results for LLM
            formatted_results = []
            for r in result.results:
                formatted_results.append({
                    "title": r.title,
                    "content": r.content[:500],  # Truncate long content
                    "source": r.source,
                    "relevance": r.relevance
                })

            return ToolResult(
                success=True,
                result={
                    "query": query,
                    "results": formatted_results,
                    "count": len(formatted_results),
                    "cached": result.cached
                },
                metadata={"source": "raica_server"}
            )

        except Exception as e:
            logger.error(f"RAICA web search failed: {e}")
            return ToolResult(
                success=False,
                error=f"RAICA search failed: {e}"
            )

    def raica_search_docs(self, query: str, max_results: int = 5) -> ToolResult:
        """
        Search documentation via RAICA server.

        Args:
            query: Documentation search query
            max_results: Maximum results to return

        Returns:
            ToolResult with documentation results or error
        """
        if not self._check_raica_server():
            return ToolResult(
                success=False,
                error="RAICA server is not available. Use 'fetch_documentation' for direct access instead.",
                metadata={"raica_unavailable": True}
            )

        client = self._get_raica_client()
        if not client:
            return ToolResult(
                success=False,
                error="RAICA client not initialized"
            )

        try:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(client.search_documents(query, max_results))
            finally:
                loop.close()

            if not result.success:
                return ToolResult(
                    success=False,
                    error=result.error or "Document search failed"
                )

            formatted_results = []
            for r in result.results:
                formatted_results.append({
                    "title": r.title,
                    "content": r.content[:1000],
                    "source": r.source
                })

            return ToolResult(
                success=True,
                result={
                    "query": query,
                    "results": formatted_results,
                    "count": len(formatted_results)
                },
                metadata={"source": "raica_server"}
            )

        except Exception as e:
            logger.error(f"RAICA doc search failed: {e}")
            return ToolResult(
                success=False,
                error=f"RAICA document search failed: {e}"
            )

    def raica_lookup_api(self, api_name: str, topic: str = None) -> ToolResult:
        """
        Look up API documentation via RAICA server.

        Args:
            api_name: Name of the API or library
            topic: Specific topic to focus on (optional)

        Returns:
            ToolResult with API documentation or error
        """
        if not self._check_raica_server():
            return ToolResult(
                success=False,
                error="RAICA server is not available. Use 'fetch_url' with the official documentation URL instead.",
                metadata={"raica_unavailable": True}
            )

        client = self._get_raica_client()
        if not client:
            return ToolResult(
                success=False,
                error="RAICA client not initialized"
            )

        try:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(client.lookup_api_docs(api_name, topic))
            finally:
                loop.close()

            if not result.success:
                return ToolResult(
                    success=False,
                    error=result.error or "API lookup failed"
                )

            formatted_results = []
            for r in result.results:
                formatted_results.append({
                    "title": r.title,
                    "content": r.content,
                    "source": r.source
                })

            return ToolResult(
                success=True,
                result={
                    "api": api_name,
                    "topic": topic,
                    "documentation": formatted_results
                },
                metadata={"source": "raica_server"}
            )

        except Exception as e:
            logger.error(f"RAICA API lookup failed: {e}")
            return ToolResult(
                success=False,
                error=f"RAICA API lookup failed: {e}"
            )

    def raica_search_patterns(
        self,
        requirements: List[str],
        language: str = "python"
    ) -> ToolResult:
        """
        Search for implementation patterns via RAICA server.

        Args:
            requirements: List of requirements to find patterns for
            language: Programming language (default: python)

        Returns:
            ToolResult with pattern suggestions or error
        """
        if not self._check_raica_server():
            return ToolResult(
                success=False,
                error="RAICA server is not available for pattern search.",
                metadata={"raica_unavailable": True}
            )

        client = self._get_raica_client()
        if not client:
            return ToolResult(
                success=False,
                error="RAICA client not initialized"
            )

        # Ensure requirements is a list
        if isinstance(requirements, str):
            requirements = [requirements]

        try:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    client.search_patterns(requirements, language)
                )
            finally:
                loop.close()

            if not result.success:
                return ToolResult(
                    success=False,
                    error=result.error or "Pattern search failed"
                )

            formatted_results = []
            for r in result.results:
                formatted_results.append({
                    "title": r.title,
                    "content": r.content,
                    "source": r.source
                })

            return ToolResult(
                success=True,
                result={
                    "requirements": requirements,
                    "language": language,
                    "patterns": formatted_results
                },
                metadata={"source": "raica_server"}
            )

        except Exception as e:
            logger.error(f"RAICA pattern search failed: {e}")
            return ToolResult(
                success=False,
                error=f"RAICA pattern search failed: {e}"
            )

    # =========================================================================
    # COMMUNICATION HUB TOOLS
    # =========================================================================

    def get_available_channels(self) -> ToolResult:
        """
        List all configured communication channels with their status and capabilities.

        Returns:
            ToolResult with list of channels, enabled status, and capabilities
        """
        if not self._comm_hub:
            return ToolResult(
                success=False,
                error="Communication Hub not available. Check if communication_hub_tools module is installed.",
                metadata={"comm_hub_unavailable": True}
            )

        return self._comm_hub.get_available_channels({})

    def get_channel_config(self, channel: str) -> ToolResult:
        """
        Get configuration for a specific communication channel.

        Args:
            channel: Channel name (e.g., 'twitter', 'email')

        Returns:
            ToolResult with channel settings (credentials NOT exposed)
        """
        if not self._comm_hub:
            return ToolResult(
                success=False,
                error="Communication Hub not available. Check if communication_hub_tools module is installed.",
                metadata={"comm_hub_unavailable": True}
            )

        return self._comm_hub.get_channel_config({"channel": channel})

    def execute_social_operation(
        self,
        channel: str,
        operation: str,
        parameters: Optional[Dict] = None
    ) -> ToolResult:
        """
        Execute a social media operation via the appropriate handler.

        Args:
            channel: Channel name (e.g., 'twitter')
            operation: Operation type (e.g., 'post', 'get_user_tweets', 'get_tweet_replies', 'get_mentions')
            parameters: Operation-specific parameters

        Returns:
            ToolResult with operation result
        """
        if not self._comm_hub:
            return ToolResult(
                success=False,
                error="Communication Hub not available. Check if communication_hub_tools module is installed.",
                metadata={"comm_hub_unavailable": True}
            )

        return self._comm_hub.execute_social_operation({
            "channel": channel,
            "operation": operation,
            "parameters": parameters or {}
        })
