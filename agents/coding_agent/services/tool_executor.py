"""
Tool Executor - Executes tool calls from LLM responses.

This module parses and executes tool calls from LLM responses,
handling validation, batching, and result collection.

Enhanced with:
- Intelligent tool suggestion for unknown tools
- Argument validation before execution
- Pre-flight checks (file exists, etc.)
- Error recovery suggestions
- Tool call deduplication
- Call history tracking
- Timeout handling
"""

import json
import logging
import time
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from collections import deque

from .debug_toolkit import DebugToolkit, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a single tool call."""
    tool: str
    args: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        return {"tool": self.tool, "args": self.args}


@dataclass
class ExecutionResult:
    """Result of executing a batch of tool calls."""
    success: bool
    results: List[ToolResult]
    errors: List[str]
    recovery_suggestions: List[str] = field(default_factory=list)
    skipped_calls: List[Dict] = field(default_factory=list)  # Calls that were deduplicated
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "recovery_suggestions": self.recovery_suggestions,
            "skipped_calls": self.skipped_calls,
            "execution_time_ms": self.execution_time_ms
        }

    def has_recoverable_errors(self) -> bool:
        """Check if any errors are potentially recoverable."""
        recoverable_patterns = [
            "file not found", "no such file", "does not exist",
            "permission denied", "timeout", "connection",
            "module not found", "import error"
        ]
        for err in self.errors:
            err_lower = err.lower()
            if any(p in err_lower for p in recoverable_patterns):
                return True
        return False


class ToolExecutor:
    """
    Executes tool calls parsed from LLM responses.

    Enhanced with intelligent features:
    - Tool name suggestion for typos/unknown tools
    - Argument validation before execution
    - Pre-flight checks (file exists, etc.)
    - Error recovery suggestions
    - Call deduplication to prevent loops
    - History tracking for debugging

    Usage:
        executor = ToolExecutor(toolkit)
        tool_calls = executor.parse_response(llm_response)
        result = executor.execute_batch(tool_calls)
    """

    # Common error patterns and their recovery suggestions
    ERROR_RECOVERY_MAP = {
        "file not found": "Use 'find_file' or 'list_files' to locate the file first",
        "no such file": "Use 'find_file' or 'list_files' to locate the file first",
        "does not exist": "Check the path with 'list_files' or create the file with 'write_file'",
        "permission denied": "Check file permissions or try a different approach",
        "syntax error": "Use 'read_file' to examine the file content first",
        "module not found": "Use 'dependency_check' then 'pip_install' to install missing module",
        "import error": "Check imports with 'grep_search' pattern='import' then 'pip_install'",
        "connection": "Check network connectivity or try 'fetch_url' with a different URL",
        "timeout": "The operation took too long - try with smaller scope or retry",
        "line number": "Use 'read_file' to check actual line count first",
        "not unique": "Use 'grep_search' to find the exact location, then use line-based editing",
    }

    # Tools that should check file existence first
    FILE_READ_TOOLS = {"read_file", "edit_file", "get_line", "get_lines_range",
                       "replace_line", "get_symbols", "validate_syntax", "check_lint"}

    def __init__(self, toolkit: DebugToolkit, max_history: int = 100):
        self.toolkit = toolkit
        self._available_tools = toolkit.get_available_tools()
        self._call_history: deque = deque(maxlen=max_history)
        self._recent_calls: Dict[str, float] = {}  # For deduplication: hash -> timestamp
        self._dedup_window_seconds: float = 2.0  # Don't repeat same call within 2 seconds
    
    def parse_response(self, response: str) -> List[ToolCall]:
        """
        Parse tool calls from LLM response.
        
        Supports multiple formats:
        1. JSON object with "tool_calls" array
        2. JSON array of tool calls
        3. Single JSON tool call object
        
        Args:
            response: Raw LLM response string
            
        Returns:
            List of ToolCall objects
        """
        # Clean the response - extract JSON
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning("No JSON found in response")
            return []
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            return []
        
        # Handle different formats
        tool_calls = []
        raw_calls = []
        
        # Format 1: {"tool_calls": [...]}
        if isinstance(data, dict) and "tool_calls" in data:
            raw_calls = data["tool_calls"]
        # Format 2: [{"tool": "...", "args": {...}}, ...]
        elif isinstance(data, list):
            raw_calls = data
        # Format 3: {"tool": "...", "args": {...}} or {"operation": "...", "path": "..."}
        elif isinstance(data, dict) and any(k in data for k in ["tool", "action", "name", "function", "operation"]):
            # If it has "operation" key, convert to standard format
            if "operation" in data:
                tool_name = data.get("operation")
                args = {k: v for k, v in data.items() if k != "operation"}
                raw_calls = [{"tool": tool_name, "args": args}]
            else:
                raw_calls = [data]
        # Format 4: Nested tool_calls (sometimes LLMs wrap it)
        elif isinstance(data, dict):
             # Search for tool_calls key recursively in the first level
             for k, v in data.items():
                  if k == "tool_calls" and isinstance(v, list):
                       raw_calls = v
                       break
                  if isinstance(v, dict) and "tool_calls" in v:
                       raw_calls = v["tool_calls"]
                       break

        # Format 5: operations array with flat args (e.g., {"operations": [{"operation": "edit_file", "path": "..."}]})
        if not raw_calls and isinstance(data, dict) and "operations" in data:
            ops = data["operations"]
            if isinstance(ops, list):
                for op in ops:
                    if isinstance(op, dict) and "operation" in op:
                        # Convert flat format to tool_calls format
                        tool_name = op.get("operation")
                        # All other keys become args
                        args = {k: v for k, v in op.items() if k != "operation"}
                        raw_calls.append({"tool": tool_name, "args": args})
        
        if not raw_calls:
            logger.warning(f"Unknown response format: {type(data)}")
            # Last ditch: check if it's just a dict that looks like it has tools
            if isinstance(data, dict) and len(data) > 0:
                 # If it has a key that is a valid tool name
                 for k, v in data.items():
                      if k in self._available_tools:
                           raw_calls = [{"tool": k, "args": v if isinstance(v, dict) else {}}]
                           break
            
            if not raw_calls:
                 # [IMPROVEMENT] Deep recursive search for any tool-like object
                 # This helps if the LLM wrapped the tool in arbitrary keys like {"response": {"command": {"tool": "edit_file"}}}
                 found_tools = self._find_deep_tool_calls(data)
                 if found_tools:
                     raw_calls = found_tools
            
            if not raw_calls:
                 # Debugging: log the keys we saw
                 keys = list(data.keys()) if isinstance(data, dict) else "not_dict"
                 logger.warning(f"Unknown response format: {type(data)} Keys: {keys}")
                 return []
        
        # Validate and create ToolCall objects
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            
            # Normalize field names
            tool_name = raw.get("tool") or raw.get("name") or raw.get("function") or raw.get("action")
            args = raw.get("args") or raw.get("arguments") or raw.get("parameters") or raw.get("params") or {}
            
            # [IMPROVEMENT] Handle nested tool definitions (e.g., {"tool": {"name": "foo", "args": ...}})
            # If tool_name is a dict, it means we extracted the whole object instead of just the name.
            if isinstance(tool_name, dict):
                 unnested = tool_name
                 tool_name = unnested.get("tool") or unnested.get("name") or unnested.get("function") or unnested.get("action")
                 # If we found args inside the nested object, use them
                 nested_args = unnested.get("args") or unnested.get("arguments") or unnested.get("parameters") or unnested.get("params")
                 if nested_args:
                     args = nested_args

            # [IMPROVEMENT] Handle flattened arguments (when args are at top level)
            if not args and tool_name:
                # If 'args' container is empty, assume other keys in 'raw' are the arguments
                # Filter out reserved keys (tool/name/action/etc)
                reserved_keys = {'tool', 'name', 'function', 'action', 'type', 'tool_calls', 'args', 'arguments', 'parameters', 'params'}
                potential_args = {k: v for k, v in raw.items() if k not in reserved_keys}
                if potential_args:
                    args = potential_args

            # Handle OpenAI-style string arguments
            if isinstance(args, str):
                 try:
                      args = json.loads(args)
                 except:
                      pass
            
            # Ensure tool_name is a string now
            if not isinstance(tool_name, str):
                logger.warning(f"Tool name is not a string: {tool_name} (raw: {raw})")
                continue

            if not tool_name:
                logger.warning(f"Tool call missing name: {raw}")
                continue
            
            if tool_name not in self._available_tools:
                # Try to find a similar tool (typo correction)
                suggested = self._suggest_similar_tool(tool_name)
                if suggested:
                    logger.info(f"Unknown tool '{tool_name}' -> using suggested '{suggested}'")
                    tool_name = suggested
                else:
                    logger.warning(f"Unknown tool: {tool_name} (no similar tool found)")
                    continue

            tool_calls.append(ToolCall(tool=tool_name, args=args))

        return tool_calls

    def _suggest_similar_tool(self, unknown_tool: str, threshold: float = 0.6) -> Optional[str]:
        """
        Suggest a similar tool name for typos or variations.

        Uses difflib to find close matches.

        Args:
            unknown_tool: The unknown tool name
            threshold: Minimum similarity ratio (0.0 to 1.0)

        Returns:
            Best matching tool name, or None if no good match
        """
        # First check common aliases/variations not in the toolkit
        common_aliases = {
            "readfile": "read_file",
            "read": "read_file",
            "writefile": "write_file",
            "write": "write_file",
            "editfile": "edit_file",
            "edit": "edit_file",
            "searchfile": "grep_search",
            "grepfile": "grep_search",
            "findfile": "find_file",
            "find": "find_file",
            "listdir": "list_files",
            "dir": "list_files",
            "runcommand": "run_command",
            "run": "run_command",
            "exec": "run_command",
            "execute": "run_command",
            "install": "pip_install",
            "pipinstall": "pip_install",
            "fetchpage": "fetch_url",
            "geturl": "fetch_url",
            "manpage": "fetch_manpage",
            "getman": "fetch_manpage",
        }

        lower_name = unknown_tool.lower().replace("-", "_").replace(" ", "_")
        if lower_name in common_aliases:
            return common_aliases[lower_name]

        # Use difflib to find close matches
        matches = difflib.get_close_matches(
            unknown_tool.lower(),
            [t.lower() for t in self._available_tools],
            n=1,
            cutoff=threshold
        )

        if matches:
            # Find the original case version
            for tool in self._available_tools:
                if tool.lower() == matches[0]:
                    return tool

        return None
    
    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON from mixed text/JSON response.

        Uses multiple strategies to find valid JSON:
        1. Markdown code blocks (regex based)
        2. tool_calls pattern matching
        3. Balanced brace/bracket parsing
        4. Common LLM output cleanup
        """
        if not text:
            return None

        text = text.strip()
        import re

        # Strategy 1: Markdown code block (```json ... ```) - ROBUST REGEX
        # Prioritize blocks explicitly marked as json
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if code_block:
            extracted = code_block.group(1).strip()
            if extracted:
                 # Check if it parses
                 try:
                     json.loads(extracted)
                     return extracted
                 except:
                     pass

        # Strategy 2: Find {"tool_calls": [...]} pattern specifically
        # This is the expected format from our prompts
        # Use DOTALL to match across lines
        tool_calls_match = re.search(
            r'\{\s*"tool_calls"\s*:\s*\[[\s\S]*?\]\s*\}',
            text, re.DOTALL
        )
        if tool_calls_match:
            return tool_calls_match.group(0)

        # Strategy 3: Find {"done": true} pattern (completion marker)
        done_match = re.search(r'\{\s*"done"\s*:\s*true[^}]*\}', text, re.DOTALL)
        if done_match:
            return done_match.group(0)

        # Strategy 4: Find any JSON object with "tool" key (single tool call)
        single_tool = re.search(r'\{\s*"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^}]*\}\s*\}', text, re.DOTALL)
        if single_tool:
            # Wrap in tool_calls array
            return '{"tool_calls": [' + single_tool.group(0) + ']}'

        # Strategy 5: Remove common LLM prefixes and try again
        # LLMs often say "Here's the JSON:" or "Based on the analysis:"
        prefixes_to_remove = [
            r'^(?:Here(?:\'s| is) (?:the |my )?(?:JSON|response|fix|solution)[:\s]*)+',
            r'^(?:Based on (?:the |my )?(?:analysis|context|results)[,:\s]*)+',
            r'^(?:I\'ll |Let me |I will )[^{]*',
            r'^(?:The (?:fix|issue|error|traceback) is)[:\s]*',
            r'^Okay, (?:the |I see |it seems )[^{]*',
            r'^I apologize, [^{]*',
            r'^Based on the tool results, [^{]*',
        ]
        cleaned = text
        for prefix in prefixes_to_remove:
            cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()

        # Strategy 6: Balanced brace/bracket parsing on cleaned text
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = cleaned.find(start_char)
            if start == -1:
                continue

            # Find matching end using proper parsing
            depth = 0
            in_string = False
            escape = False

            for i, char in enumerate(cleaned[start:], start):
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == start_char:
                    depth += 1
                elif char == end_char:
                    depth -= 1
                    if depth == 0:
                        extracted = cleaned[start:i+1]
                        # Validate it's actually JSON
                        try:
                            json.loads(extracted)
                            return extracted
                        except json.JSONDecodeError:
                            # Keep trying other strategies
                            break

        # Strategy 7: Last resort - if text starts with { or [, try to parse as-is
        if cleaned.startswith('{') or cleaned.startswith('['):
            try:
                json.loads(cleaned)
                return cleaned
            except json.JSONDecodeError:
                pass

        # Strategy 8: Try to find JSON array of objects (tool calls format)
        array_match = re.search(r'\[\s*\{[\s\S]*?\}\s*\]', text)
        if array_match:
            try:
                json.loads(array_match.group(0))
                return '{"tool_calls": ' + array_match.group(0) + '}'
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not extract JSON from response: {text[:200]}...")
        return None
    
    def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a single tool call with pre-flight checks.

        Includes:
        - Argument validation
        - Pre-flight checks (file existence, etc.)
        - History tracking
        - Error enhancement with recovery suggestions
        """
        logger.info(f"Executing: {tool_call.tool}({tool_call.args})")

        # Pre-flight validation
        validation_error = self._validate_tool_call(tool_call)
        if validation_error:
            return ToolResult(
                success=False,
                error=validation_error,
                metadata={"validation_failed": True}
            )

        # Pre-flight checks for file operations
        preflight_error = self._preflight_check(tool_call)
        if preflight_error:
            return ToolResult(
                success=False,
                error=preflight_error,
                metadata={"preflight_failed": True}
            )

        # Execute the tool
        start_time = time.time()
        result = self.toolkit.execute(tool_call.tool, tool_call.args)
        execution_time = (time.time() - start_time) * 1000

        # Record in history
        self._call_history.append({
            "tool": tool_call.tool,
            "args": tool_call.args,
            "success": result.success,
            "error": result.error,
            "time_ms": execution_time,
            "timestamp": time.time()
        })

        # Enhance error with recovery suggestion
        if not result.success and result.error:
            suggestion = self._get_recovery_suggestion(result.error)
            if suggestion:
                result.metadata = result.metadata or {}
                result.metadata["recovery_suggestion"] = suggestion

        return result

    def _validate_tool_call(self, tool_call: ToolCall) -> Optional[str]:
        """
        Validate tool call arguments before execution.

        Returns error message if validation fails, None if valid.
        """
        tool_name = tool_call.tool
        args = tool_call.args

        # Get required arguments from toolkit
        required_args = self.toolkit.TOOL_REQUIRED_ARGS.get(tool_name, [])

        # Check for missing required arguments
        missing = [arg for arg in required_args if arg not in args or args[arg] is None]
        if missing:
            return f"Missing required arguments for {tool_name}: {', '.join(missing)}"

        # Tool-specific validation
        if tool_name in ("replace_line", "insert_line", "get_line", "get_lines_range"):
            # Check for line number in any of the possible argument names
            # Use explicit None check because 0 is a valid (but invalid) value
            line_num = None
            for key in ("line_number", "after_line", "start_line"):
                if key in args and args[key] is not None:
                    line_num = args[key]
                    break

            if line_num is not None:
                try:
                    if int(line_num) < 1:
                        return f"Line number must be >= 1, got {line_num}"
                except (ValueError, TypeError):
                    return f"Invalid line number: {line_num}"

        if tool_name == "pip_install":
            packages = args.get("packages", [])
            if isinstance(packages, str):
                packages = [packages]
            if not packages:
                return "pip_install requires at least one package name"

        return None

    def _preflight_check(self, tool_call: ToolCall) -> Optional[str]:
        """
        Perform pre-flight checks before tool execution.

        For file operations, checks if file exists and enforces safety rules.
        Returns error message if check fails, None if OK.
        """
        tool_name = tool_call.tool
        args = tool_call.args

        # 1. Path safety check (CRITICAL: prevents modifying venv, .git, etc.)
        path = args.get("path") or args.get("target") or args.get("target_path")
        if path and tool_name in ("write_file", "edit_file", "replace_line", "insert_line", "delete_line", "rename_file", "delete_file"):
            path_str = str(path).lower()
            forbidden_patterns = ["venv/", ".venv/", ".git/", "__pycache__/", "/venv/", "/.venv/", "/.git/"]
            if any(p in path_str for p in forbidden_patterns):
                logger.warning(f"BLOCKED: Attempted to modify forbidden path: {path}")
                return f"Permission Denied: RAICA is not allowed to modify files in virtual environments, git metadata, or caches ({path})"

        # Skip preflight for tools that don't need it
        if tool_name not in self.FILE_READ_TOOLS:
            return None

        # Check file existence for read operations
        path = args.get("path") or args.get("target")
        if path:
            full_path = self.toolkit.project_dir / path
            if not full_path.exists():
                # Don't fail immediately - let the tool handle it
                # But log a warning
                logger.debug(f"Pre-flight: File '{path}' does not exist")
                # We don't return error here - let the tool give a proper error
                # This is just for early detection

        return None

    def _get_recovery_suggestion(self, error: str) -> Optional[str]:
        """Get a recovery suggestion for an error."""
        error_lower = error.lower()
        for pattern, suggestion in self.ERROR_RECOVERY_MAP.items():
            if pattern in error_lower:
                return suggestion
        return None

    def _is_duplicate_call(self, tool_call: ToolCall) -> bool:
        """Check if this is a duplicate of a recent call."""
        call_hash = f"{tool_call.tool}:{json.dumps(tool_call.args, sort_keys=True)}"
        now = time.time()

        # Clean old entries
        old_keys = [k for k, v in self._recent_calls.items()
                    if now - v > self._dedup_window_seconds]
        for k in old_keys:
            del self._recent_calls[k]

        # Check if duplicate
        if call_hash in self._recent_calls:
            return True

        # Record this call
        self._recent_calls[call_hash] = now
        return False

    def execute_batch(self, tool_calls: List[ToolCall], skip_duplicates: bool = True) -> ExecutionResult:
        """
        Execute a batch of tool calls in sequence.

        Enhanced with:
        - Duplicate detection and skipping
        - Recovery suggestions for errors
        - Execution timing

        Args:
            tool_calls: List of ToolCall objects
            skip_duplicates: Skip calls that were just executed

        Returns:
            ExecutionResult with all results, errors, and suggestions
        """
        start_time = time.time()
        results = []
        errors = []
        recovery_suggestions = []
        skipped_calls = []
        all_success = True

        for call in tool_calls:
            # Check for duplicates
            if skip_duplicates and self._is_duplicate_call(call):
                logger.info(f"Skipping duplicate call: {call.tool}")
                skipped_calls.append(call.to_dict())
                continue

            result = self.execute(call)
            results.append(result)

            if not result.success:
                all_success = False
                errors.append(f"{call.tool}: {result.error}")

                # Collect recovery suggestion
                suggestion = result.metadata.get("recovery_suggestion") if result.metadata else None
                if suggestion and suggestion not in recovery_suggestions:
                    recovery_suggestions.append(f"{call.tool}: {suggestion}")

        execution_time = (time.time() - start_time) * 1000

        return ExecutionResult(
            success=all_success,
            results=results,
            errors=errors,
            recovery_suggestions=recovery_suggestions,
            skipped_calls=skipped_calls,
            execution_time_ms=execution_time
        )

    def get_call_history(self, last_n: int = 10) -> List[Dict]:
        """Get recent tool call history for debugging."""
        return list(self._call_history)[-last_n:]

    def clear_history(self):
        """Clear call history and deduplication cache."""
        self._call_history.clear()
        self._recent_calls.clear()
    
    def format_results_for_llm(self, execution_result: ExecutionResult) -> str:
        """
        Format execution results for LLM consumption.

        Creates a structured summary that the LLM can use to
        decide next steps. Includes recovery suggestions for errors.
        """
        lines = ["TOOL EXECUTION RESULTS:", ""]

        for i, result in enumerate(execution_result.results, 1):
            status = "✓" if result.success else "✗"
            lines.append(f"{i}. {status} Result:")

            if result.success:
                # Truncate long results
                result_str = str(result.result)
                if len(result_str) > 2000:
                    result_str = result_str[:2000] + "... (truncated)"
                lines.append(f"   {result_str}")
            else:
                lines.append(f"   ERROR: {result.error}")
                # Add recovery suggestion if available
                if result.metadata and result.metadata.get("recovery_suggestion"):
                    lines.append(f"   SUGGESTION: {result.metadata['recovery_suggestion']}")
            
            lines.append("")

        if execution_result.errors:
            lines.append("ERRORS ENCOUNTERED:")
            for err in execution_result.errors:
                lines.append(f"- {err}")
            lines.append("")

        # Include recovery suggestions if any
        if execution_result.recovery_suggestions:
            lines.append("RECOVERY SUGGESTIONS:")
            for suggestion in execution_result.recovery_suggestions:
                lines.append(f"- {suggestion}")
            lines.append("")

        # Note skipped duplicates
        if execution_result.skipped_calls:
            lines.append(f"NOTE: {len(execution_result.skipped_calls)} duplicate call(s) were skipped.")
            lines.append("")

        # Include timing info
        if execution_result.execution_time_ms > 0:
            lines.append(f"Execution time: {execution_result.execution_time_ms:.1f}ms")

        return "\n".join(lines)

    def _find_deep_tool_calls(self, data: Any, depth: int = 0) -> List[Dict]:
        """
        Recursively search for objects that look like tool calls.
        Limit depth to avoid performance issues.
        """
        if depth > 5:
            return []
            
        found = []
        
        if isinstance(data, dict):
            # Check if this dict itself is a tool call
            # keys that strongly suggest a tool call
            keys = set(data.keys())
            # We look for explicit tool identifiers
            tool_identifiers = {'tool', 'function', 'action', 'name'}
            
            # If it has a tool identifier AND matches an available tool (or alias)
            for tid in tool_identifiers:
                if tid in keys and data[tid] in self._available_tools:
                     return [data] # Found one! Return it.

            # If not a tool call itself, search values
            for v in data.values():
                if isinstance(v, (dict, list)):
                    found.extend(self._find_deep_tool_calls(v, depth + 1))
                    
        elif isinstance(data, list):
            for item in data:
                found.extend(self._find_deep_tool_calls(item, depth + 1))
                
        return found
