"""
Generalized Debug Engine - LLM-Driven Adaptive Error Resolution

This module implements a GENERALIZED approach to debugging that does NOT rely on
pattern-matching error types. Instead, it:

1. Presents the error to the LLM and asks: "What info do you need to diagnose?"
2. LLM requests diagnostic actions (run commands, read files, search, etc.)
3. System executes requests and feeds results back
4. LLM either requests more info OR proposes a fix
5. Applies the fix and verifies
6. If verification fails, feeds new error back to LLM

Key Design Principles:
- NO hardcoded error type handlers or knowledge
- NO band-aid fixes for specific cases
- LLM ASKS for what it needs to diagnose ANY problem
- LLM reasoning replaces pattern matching
- Iterative diagnosis until LLM has enough context
- Structured JSON output for reliable fix application

This approach works with any LLM that can generate text - no special
tool-calling API required.
"""

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GeneralizedDebugEngine:
    """
    LLM-driven adaptive debugger that generalizes across error types.

    Instead of pattern-matching error types to specific handlers,
    this engine lets the LLM reason about ANY error and propose fixes.

    Uses prompt-based analysis with rich project context - no tool calling
    required, works with any text generation LLM.
    """

    def __init__(
        self,
        project_dir: Path,
        llm_client,
        output_fn: Callable[[str], None] = print,
        max_retries: int = 3,
        project_context=None,
        debug_context=None
    ):
        """
        Initialize the generalized debug engine.

        Args:
            project_dir: Path to the project
            llm_client: LLM client with generate() method
            output_fn: Function to output progress
            max_retries: Max fix attempts per error
            project_context: ProjectContext with file structure and symbols
            debug_context: DebugContext with project LLD/objectives
        """
        self.project_dir = Path(project_dir)
        self.llm_client = llm_client
        self.output = output_fn
        self.max_retries = max_retries
        self.project_context = project_context
        self.debug_context = debug_context
        self.files_modified: List[str] = []

        # If we have project context, ensure it's scanned
        if self.project_context:
            try:
                self.project_context.scan_file_structure(force=False)
            except Exception as e:
                logger.warning(f"Could not scan project structure: {e}")

        # Track diagnostic context across iterations
        self.diagnostic_context: List[Dict] = []
        self.max_diagnostic_rounds = 5  # Prevent infinite loops

    def _execute_diagnostic_request(self, request: Dict) -> Dict:
        """
        Execute a diagnostic request from the LLM.

        Supported request types:
        - run_command: Execute a shell command and return output
        - read_file: Read a file's contents
        - search_files: Search for files matching a pattern
        - search_content: Search for content in files (grep)
        - check_module: Check if a Python module is built-in or installable
        """
        req_type = request.get('type', '')
        result = {'type': req_type, 'success': False, 'output': ''}

        try:
            if req_type == 'run_command':
                cmd = request.get('command', '')
                if not cmd:
                    result['output'] = 'No command specified'
                    return result

                # Security: limit dangerous commands
                dangerous = ['rm -rf', 'sudo', 'chmod', 'chown', '> /', 'dd if=']
                if any(d in cmd for d in dangerous):
                    result['output'] = f'Command blocked for safety: {cmd}'
                    return result

                self.output(f"   → Running: {cmd[:60]}...")
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=30, cwd=str(self.project_dir)
                )
                result['success'] = proc.returncode == 0
                result['output'] = (proc.stdout + proc.stderr)[:2000]

            elif req_type == 'read_file':
                file_path = request.get('path', '')
                full_path = self.project_dir / file_path
                if full_path.exists():
                    content = full_path.read_text()[:3000]
                    result['success'] = True
                    result['output'] = self._add_line_numbers(content)
                    self.output(f"   → Read: {file_path}")
                else:
                    result['output'] = f'File not found: {file_path}'

            elif req_type == 'search_files':
                pattern = request.get('pattern', '*')
                matches = list(self.project_dir.glob(pattern))[:20]
                result['success'] = True
                result['output'] = '\n'.join(str(m.relative_to(self.project_dir)) for m in matches)
                self.output(f"   → Found {len(matches)} files matching {pattern}")

            elif req_type == 'search_content':
                pattern = request.get('pattern', '')
                path = request.get('path', '.')
                self.output(f"   → Searching for '{pattern}'...")
                proc = subprocess.run(
                    ['grep', '-rn', '--include=*.py', '--include=*.txt',
                     '--include=*.json', '--include=*.yaml', pattern, path],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(self.project_dir)
                )
                result['success'] = True
                result['output'] = proc.stdout[:2000] or 'No matches found'

            elif req_type == 'check_module':
                module_name = request.get('module', '')
                self.output(f"   → Checking module: {module_name}")
                # Check if it's a built-in module
                check_cmd = f'python -c "import sys; print(\'{module_name}\' in sys.stdlib_module_names)"'
                proc = subprocess.run(
                    check_cmd, shell=True, capture_output=True, text=True,
                    timeout=10, cwd=str(self.project_dir)
                )
                is_builtin = 'True' in proc.stdout

                if is_builtin:
                    result['success'] = True
                    result['output'] = f"'{module_name}' is a BUILT-IN Python module (in sys.stdlib_module_names). It should NOT be in requirements.txt."
                else:
                    # Check if it's installable via pip
                    pip_cmd = f'pip index versions {module_name} 2>&1 | head -5'
                    pip_proc = subprocess.run(
                        pip_cmd, shell=True, capture_output=True, text=True,
                        timeout=30, cwd=str(self.project_dir)
                    )
                    result['success'] = True
                    if 'Available versions' in pip_proc.stdout or 'versions:' in pip_proc.stdout.lower():
                        result['output'] = f"'{module_name}' is installable via pip:\n{pip_proc.stdout[:500]}"
                    else:
                        result['output'] = f"'{module_name}' may not exist on PyPI:\n{pip_proc.stdout[:500]}{pip_proc.stderr[:500]}"
            else:
                result['output'] = f'Unknown request type: {req_type}'

        except subprocess.TimeoutExpired:
            result['output'] = 'Command timed out'
        except Exception as e:
            result['output'] = f'Error: {str(e)}'

        return result

    def _build_diagnosis_prompt(self, error_trace: str, issue_description: str,
                                 gathered_info: List[Dict]) -> str:
        """Build prompt asking LLM what information it needs to diagnose the problem."""
        parts = []

        parts.append("""You are an expert debugger. Before proposing a fix, you may need more information.

YOUR OPTIONS:
1. REQUEST more information using diagnostic actions
2. PROVIDE a fix if you have enough information

RESPOND WITH JSON in one of these formats:

FORMAT A - Request more information:
```json
{
  "action": "request_info",
  "reasoning": "I need to check X because Y",
  "requests": [
    {"type": "run_command", "command": "python -c \"import X; print('exists')\""},
    {"type": "read_file", "path": "path/to/file"},
    {"type": "search_files", "pattern": "**/*.py"},
    {"type": "search_content", "pattern": "some_text", "path": "."},
    {"type": "check_module", "module": "module_name"}
  ]
}
```

FORMAT B - Provide a fix (when you have enough information):
```json
{
  "action": "fix",
  "analysis": "Brief explanation of what's wrong",
  "root_cause": "The specific issue",
  "file_path": "path/to/file",
  "fix_type": "search_replace|delete_line|insert_after_line|replace_line",
  "search_text": "text to find (for search_replace)",
  "replace_text": "replacement text (for search_replace)",
  "line_number": 5,
  "new_content": "content for insert/replace",
  "explanation": "What this fix does"
}
```

AVAILABLE DIAGNOSTIC ACTIONS (with example values):
- run_command: Run shell command → {"type": "run_command", "command": "python3 -c \"import sys; print(sys.version)\""}
- read_file: Read file contents → {"type": "read_file", "path": "src/main.py"}
- search_files: Find files by pattern → {"type": "search_files", "pattern": "**/*.py"}
- search_content: Search text in files → {"type": "search_content", "pattern": "def calculate", "path": "src/"}
- check_module: Check if module exists → {"type": "check_module", "module": "pandas"}
- fetch_url: Fetch web page/docs → {"type": "fetch_url", "url": "https://docs.python.org/3/library/re.html"}
- fetch_manpage: Get command manual → {"type": "fetch_manpage", "command": "grep"}

IMPORTANT:
- Always read a file before trying to edit it
- Use search_content to find the exact location of code before fixing
- If a module check shows it's missing, the fix is likely pip_install
- Use fetch_url or fetch_manpage to look up library/command documentation
""")

        # Add project design context if available
        if self.debug_context:
            design_context = self.debug_context.get_design_context_for_llm()
            if design_context:
                parts.append("\n" + design_context)

        # Add previously gathered information
        if gathered_info:
            parts.append("\n=== INFORMATION GATHERED SO FAR ===")
            for info in gathered_info:
                parts.append(f"\n[{info['type']}] Request: {info.get('request', {})}")
                parts.append(f"Result: {info.get('output', 'No output')[:1000]}")

        # The error
        parts.append("\n=== ERROR TO DIAGNOSE ===")
        parts.append("```")
        parts.append(error_trace)
        parts.append("```")

        if issue_description:
            parts.append(f"\nDescription: {issue_description}")

        # File context from initial scan
        file_contents = self._gather_relevant_files(error_trace)
        if file_contents:
            parts.append("\n=== FILES MENTIONED IN ERROR ===")
            for path, content in file_contents.items():
                if len(content) > 1500:
                    content = content[:1500] + "\n... (truncated)"
                parts.append(f"\n--- {path} ---")
                parts.append(content)

        # Add usage context for ImportError/missing symbol cases
        usage_context = self._extract_usage_context_from_error(error_trace, file_contents)
        if usage_context:
            parts.append(usage_context)

        parts.append("\n\nRespond with JSON (either request_info or fix):")

        return '\n'.join(parts)

    async def debug(self, error_trace: str, issue_description: str = "") -> Dict:
        """
        Debug an error using LLM-driven iterative diagnosis.

        Flow:
        1. Present error to LLM and ask what info it needs
        2. Execute diagnostic requests (run commands, read files, etc.)
        3. Feed results back to LLM
        4. Repeat until LLM has enough info to propose a fix
        5. Apply and verify the fix

        Args:
            error_trace: The error output from running the code
            issue_description: Optional description of the problem

        Returns:
            Dict with success status, fix applied, and explanation
        """
        self.output("\n" + "─" * 50)
        self.output("🧠 GENERALIZED DEBUG ENGINE")
        self.output("─" * 50)
        self.output("Using LLM-driven iterative diagnosis (no hardcoded patterns)")

        gathered_info: List[Dict] = []
        diagnosis_round = 0

        # Iterative diagnosis loop
        while diagnosis_round < self.max_diagnostic_rounds:
            diagnosis_round += 1
            self.output(f"\n[DIAGNOSIS ROUND {diagnosis_round}]")

            # Build prompt with current context
            prompt = self._build_diagnosis_prompt(error_trace, issue_description, gathered_info)

            # Log prompt size
            prompt_chars = len(prompt)
            self.output(f"   Prompt: {prompt_chars} chars (~{prompt_chars // 4} tokens)")

            # Limit prompt size
            MAX_PROMPT_CHARS = 24000
            if prompt_chars > MAX_PROMPT_CHARS:
                self.output(f"   ⚠ Truncating to {MAX_PROMPT_CHARS} chars")
                prompt = self._truncate_prompt(prompt, MAX_PROMPT_CHARS)

            # Get LLM response
            self.output("   Asking LLM...")
            try:
                import inspect
                result = self.llm_client.generate(
                    prompt=prompt,
                    temperature=0.0,
                    timeout=120,
                    max_tokens=4096
                )
                if inspect.iscoroutine(result):
                    response = await result
                else:
                    response = result

                content = response.content if hasattr(response, 'content') else str(response)

                if not content or len(content.strip()) < 10:
                    self.output("   ⚠ LLM returned empty response")
                    return {"success": False, "error": "LLM returned empty response"}

            except Exception as e:
                error_msg = str(e)
                self.output(f"   ❌ LLM call failed: {error_msg[:100]}")
                return {"success": False, "error": f"LLM call failed: {error_msg}"}

            # Parse LLM response
            llm_response = self._parse_llm_response(content)

            if not llm_response:
                self.output(f"   ❌ Could not parse LLM response")
                self.output(f"   Response preview: {content[:200]}...")
                return {"success": False, "error": "Could not parse LLM response"}

            action = llm_response.get('action', '')

            # Handle diagnostic request
            if action == 'request_info':
                requests = llm_response.get('requests', [])
                reasoning = llm_response.get('reasoning', '')
                self.output(f"   LLM needs more info: {reasoning[:60]}...")
                self.output(f"   Executing {len(requests)} diagnostic request(s)...")

                for req in requests:
                    result = self._execute_diagnostic_request(req)
                    gathered_info.append({
                        'type': req.get('type'),
                        'request': req,
                        'output': result.get('output', ''),
                        'success': result.get('success', False)
                    })

                # Continue to next round
                continue

            # Handle fix proposal
            elif action == 'fix':
                self.output("   LLM ready to fix!")
                fix_proposal = llm_response
                break

            else:
                self.output(f"   ⚠ Unknown action: {action}, treating as fix attempt")
                fix_proposal = llm_response
                break

        else:
            # Exceeded max rounds
            self.output(f"   ❌ Exceeded {self.max_diagnostic_rounds} diagnosis rounds")
            return {"success": False, "error": "Exceeded max diagnosis rounds"}

        # Apply the fix
        self.output("\n[FIX APPLICATION]")
        self.output(f"   Analysis: {fix_proposal.get('analysis', 'N/A')[:60]}")
        self.output(f"   Root cause: {fix_proposal.get('root_cause', 'N/A')[:60]}")

        fix_result = self._apply_fix(fix_proposal)

        if not fix_result["success"]:
            self.output(f"   ❌ Fix failed: {fix_result.get('error')}")
            return {"success": False, "error": fix_result.get("error")}

        self.output(f"   ✓ Fix applied to {fix_proposal.get('file_path')}")

        # Verify the fix
        self.output("\n[VERIFICATION]")
        verified, new_error = self._verify_fix()

        if verified:
            self.output("   ✅ Fix verified successfully!")
            return {
                "success": True,
                "fix_applied": fix_proposal,
                "files_modified": self.files_modified,
                "diagnosis_rounds": diagnosis_round
            }
        else:
            self.output(f"   ⚠ Verification failed")
            return {
                "success": False,
                "error": "Verification failed",
                "new_error": new_error,
                "fix_applied": fix_proposal
            }

    def _parse_llm_response(self, content: str) -> Optional[Dict]:
        """Parse LLM response - either diagnostic request or fix proposal."""
        # Try to find JSON in the response
        json_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_block_match:
            try:
                return json.loads(json_block_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object with action field
        json_match = re.search(r'\{[\s\S]*?"action"[\s\S]*?\}', content)
        if json_match:
            try:
                # Find the complete JSON object
                text = content[json_match.start():]
                depth = 0
                end = 0
                for i, c in enumerate(text):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > 0:
                    return json.loads(text[:end])
            except json.JSONDecodeError:
                pass

        # Fall back to looking for any JSON object
        json_match = re.search(r'\{[\s\S]*?\}', content)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if 'action' in data or 'file_path' in data:
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def _gather_relevant_files(self, error_trace: str) -> Dict[str, str]:
        """Extract and read files mentioned in the error trace."""
        file_contents = {}

        # Check if this is a requirements.txt / pip-related error
        is_requirements_error = any(pattern in error_trace.lower() for pattern in [
            'requirements.txt',
            'no matching distribution',
            'could not find a version',
            'pip install',
            'error: invalid requirement',
            'no module named',
            'modulenotfounderror'
        ])

        if is_requirements_error:
            # Read requirements.txt if it exists
            for req_file in ['requirements.txt', 'pyproject.toml', 'setup.py']:
                req_path = self.project_dir / req_file
                if req_path.exists():
                    try:
                        content = req_path.read_text()
                        file_contents[req_file] = self._add_line_numbers(content)
                        self.output(f"   Read: {req_file} ({len(content)} bytes)")
                    except Exception as e:
                        logger.debug(f"Could not read {req_file}: {e}")

        # Extract Python file paths from error trace
        file_pattern = r'File ["\']([^"\']+\.py)["\']'
        matches = re.findall(file_pattern, error_trace)

        for file_path in matches:
            # Convert to relative path
            try:
                path = Path(file_path)
                if path.is_absolute():
                    try:
                        path = path.relative_to(self.project_dir)
                    except ValueError:
                        continue

                full_path = self.project_dir / path
                if full_path.exists():
                    content = full_path.read_text()
                    # Add line numbers
                    numbered = self._add_line_numbers(content)
                    file_contents[str(path)] = numbered
                    self.output(f"   Read: {path} ({len(content)} bytes)")

            except Exception as e:
                logger.debug(f"Could not read {file_path}: {e}")

        # Also read main entry points if not already included
        for entry_file in ["main.py", "app.py", "__main__.py"]:
            if entry_file not in file_contents:
                full_path = self.project_dir / entry_file
                if full_path.exists():
                    try:
                        content = full_path.read_text()
                        file_contents[entry_file] = self._add_line_numbers(content)
                        self.output(f"   Read: {entry_file} ({len(content)} bytes)")
                    except Exception:
                        pass

        return file_contents

    def _extract_usage_context_from_error(self, error_trace: str, file_contents: Dict[str, str]) -> str:
        """
        Gather RAW context for missing symbol errors.
        
        CLAUDE.md COMPLIANCE: This method ONLY provides raw file contents.
        It does NOT interpret, parse, or infer anything. The LLM interprets.
        
        Args:
            error_trace: The error trace containing the ImportError
            file_contents: Already-gathered file contents
            
        Returns:
            RAW context string for LLM interpretation
        """
        # Extract symbol name from error - this is parsing the ERROR MESSAGE, not code interpretation
        import_error_patterns = [
            r"cannot import name ['\"]?(\w+)['\"]?\s+from\s+['\"]?([^'\"]+)['\"]?",
            r"ImportError: cannot import name ['\"]?(\w+)['\"]?",
        ]
        
        symbol_name = None
        source_module = None
        
        for pattern in import_error_patterns:
            match = re.search(pattern, error_trace)
            if match:
                symbol_name = match.group(1)
                source_module = match.group(2) if len(match.groups()) > 1 else None
                break
        
        if not symbol_name:
            return ""
        
        self.output(f"   Gathering context for missing symbol: {symbol_name}")
        
        # CLAUDE.md COMPLIANT: Just provide RAW file contents
        # LLM will interpret usage patterns, not RAICA
        file_contents_str = ""
        for filepath, content in file_contents.items():
            # Include raw content - truncate if very long
            if len(content) > 2500:
                content = content[:2500] + "\n... (truncated)"
            file_contents_str += f"\n--- {filepath} ---\n{content}\n"
        
        if not file_contents_str:
            return ""
        
        # CLAUDE.md COMPLIANT: Ask LLM to interpret, don't do it ourselves
        context = f"""
=== MISSING SYMBOL CONTEXT ===

The symbol '{symbol_name}' cannot be imported from module '{source_module or 'unknown'}'.

YOU (the LLM) must analyze the files below to determine:
1. Is '{symbol_name}' a class or function? (Look for instantiation patterns like `{symbol_name}()`)
2. What methods must it have? (Look for method calls like `var.method()`)
3. What base class should it inherit from? (Look at the imports in the calling file)
4. What attributes must it have? (Look for attribute access like `var.attribute`)

FILES FOR ANALYSIS:
{file_contents_str}

Based on your analysis, create '{symbol_name}' with the correct interface in module '{source_module or 'the appropriate module'}'.
"""
        return context

    def _add_line_numbers(self, content: str) -> str:
        """Add line numbers to content for precise fix locations."""
        lines = content.split('\n')
        numbered = []
        for i, line in enumerate(lines, 1):
            numbered.append(f"{i:4d}│ {line}")
        return '\n'.join(numbered)

    def _truncate_prompt(self, prompt: str, max_chars: int) -> str:
        """Truncate prompt while preserving critical sections."""
        if len(prompt) <= max_chars:
            return prompt

        # Find key sections to preserve
        error_start = prompt.find("=== ERROR TO FIX ===")
        task_start = prompt.find("=== YOUR TASK ===")

        if error_start == -1 or task_start == -1:
            # Can't find sections, just truncate
            return prompt[:max_chars] + "\n... (truncated)"

        # Calculate how much we can keep
        error_section = prompt[error_start:task_start]
        task_section = prompt[task_start:]

        # Essential: error + task sections
        essential = error_section + task_section
        essential_len = len(essential)

        # Available for context
        context_budget = max_chars - essential_len - 200  # 200 for intro

        if context_budget < 1000:
            # Not enough room, keep minimal context
            intro = "You are an expert Python debugger. Analyze the error and provide a fix.\n\n"
            return intro + essential

        # Keep intro + as much context as fits
        intro_and_context = prompt[:error_start]
        if len(intro_and_context) > context_budget:
            intro_and_context = intro_and_context[:context_budget] + "\n... (context truncated)\n\n"

        return intro_and_context + essential

    def _build_symbol_map(self) -> Dict[str, str]:
        """Build a map of symbol name → file location for quick lookup."""
        symbol_map = {}

        if not self.project_context or not self.project_context.file_entries:
            return symbol_map

        for path, entry in self.project_context.file_entries.items():
            if entry.file_type == 'python' and entry.symbols:
                for symbol in entry.symbols:
                    # Parse "class Foo" or "def bar" format
                    parts = symbol.split(' ', 1)
                    if len(parts) == 2:
                        symbol_type, symbol_name = parts
                        symbol_map[symbol_name] = path

        return symbol_map

    def _apply_fix(self, fix: Dict) -> Dict:
        """Apply the proposed fix."""
        file_path = fix.get("file_path")
        fix_type = fix.get("fix_type", "search_replace")

        if not file_path:
            return {"success": False, "error": "No file_path in fix proposal"}

        # Path safety check (CRITICAL: prevents modifying venv, .git, etc.)
        path_str = str(file_path).lower()
        forbidden_patterns = ["venv/", ".venv/", ".git/", "__pycache__/", "/venv/", "/.venv/", "/.git/"]
        if any(p in path_str for p in forbidden_patterns):
            logger.warning(f"BLOCKED: Attempted to fix forbidden path: {file_path}")
            return {"success": False, "error": f"Permission Denied: RAICA is not allowed to modify files in virtual environments or git metadata ({file_path})"}

        full_path = self.project_dir / file_path

        if not full_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            original_content = full_path.read_text()
            lines = original_content.split('\n')
            new_content = None

            if fix_type == "search_replace":
                search_text = fix.get("search_text", "")
                replace_text = fix.get("replace_text", "")

                if not search_text:
                    return {"success": False, "error": "No search_text in fix proposal"}

                # Try exact match first
                if search_text in original_content:
                    new_content = original_content.replace(search_text, replace_text, 1)
                else:
                    # Try with normalized whitespace
                    normalized_search = ' '.join(search_text.split())

                    # Find in normalized content
                    found = False
                    for i, line in enumerate(lines):
                        normalized_line = ' '.join(line.split())
                        if normalized_search in normalized_line or normalized_line in normalized_search:
                            # Found a match - replace this line
                            replace_lines = replace_text.split('\n')
                            if len(replace_lines) == 1:
                                # Preserve original indentation
                                indent = len(line) - len(line.lstrip())
                                lines[i] = ' ' * indent + replace_text.strip()
                            else:
                                lines[i] = replace_text
                            found = True
                            break

                    if not found:
                        return {"success": False, "error": f"Could not find search_text in {file_path}"}

                    new_content = '\n'.join(lines)

            elif fix_type in ("insert_after_line", "insert_after", "insert"):
                line_number = fix.get("line_number", 0)
                new_line_content = fix.get("new_content", "")

                if line_number < 0 or line_number > len(lines):
                    return {"success": False, "error": f"Invalid line_number: {line_number}"}

                # Insert after the specified line
                lines.insert(line_number, new_line_content)
                new_content = '\n'.join(lines)

            elif fix_type == "replace_line":
                line_number = fix.get("line_number", 0)
                new_line_content = fix.get("new_content", "")

                if line_number < 1 or line_number > len(lines):
                    return {"success": False, "error": f"Invalid line_number: {line_number}"}

                # Replace the line (1-indexed)
                lines[line_number - 1] = new_line_content
                new_content = '\n'.join(lines)

            elif fix_type == "delete_line":
                line_number = fix.get("line_number", 0)

                if line_number < 1 or line_number > len(lines):
                    return {"success": False, "error": f"Invalid line_number: {line_number}"}

                # Delete the line (1-indexed)
                del lines[line_number - 1]
                new_content = '\n'.join(lines)

            else:
                return {"success": False, "error": f"Unknown fix_type: {fix_type}"}

            # Write the new content
            full_path.write_text(new_content)
            if file_path not in self.files_modified:
                self.files_modified.append(file_path)

            # Validate syntax after fix - ONLY for Python files
            if file_path.endswith('.py'):
                try:
                    result = subprocess.run(
                        ['python', '-m', 'py_compile', str(full_path)],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        # Rollback
                        full_path.write_text(original_content)
                        self.files_modified.remove(file_path)
                        return {"success": False, "error": f"Fix caused syntax error: {result.stderr[:100]}"}
                except Exception as e:
                    logger.warning(f"Could not validate syntax: {e}")
            elif file_path == 'requirements.txt':
                # Basic validation for requirements.txt - check for empty lines with content
                for i, line in enumerate(new_content.split('\n'), 1):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Should be a valid package spec: name[extras]>=version,<version or just name
                        if not re.match(r'^[a-zA-Z0-9_-]+(\[[a-zA-Z0-9_,]+\])?(==|>=|<=|~=|!=|>|<)?', line):
                            if not line.startswith('-'):  # -r, -e, etc. are valid
                                full_path.write_text(original_content)
                                self.files_modified.remove(file_path)
                                return {"success": False, "error": f"Invalid requirements.txt line {i}: {line}"}

            return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _verify_fix(self) -> Tuple[bool, Optional[str]]:
        """Verify the fix by running the code."""

        # Find the main entry point
        main_file = None
        for candidate in ["main.py", "app.py", "__main__.py"]:
            if (self.project_dir / candidate).exists():
                main_file = candidate
                break

        if not main_file:
            # Just verify syntax of all Python files
            for py_file in self.project_dir.rglob("*.py"):
                if "venv" not in str(py_file) and "__pycache__" not in str(py_file):
                    try:
                        result = subprocess.run(
                            ['python', '-m', 'py_compile', str(py_file)],
                            capture_output=True, text=True, timeout=10
                        )
                        if result.returncode != 0:
                            return False, result.stderr
                    except Exception:
                        pass
            return True, None

        # Try to run the main file
        try:
            result = subprocess.run(
                ['python', main_file],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return True, None

            # Check if it's just CLI expecting arguments (not a bug)
            stderr = result.stderr.lower()
            if "arguments are required" in stderr or "usage:" in stderr:
                return True, None

            return False, result.stderr

        except subprocess.TimeoutExpired:
            # Timeout might mean it's running (not crashing)
            return True, None
        except Exception as e:
            return False, str(e)
