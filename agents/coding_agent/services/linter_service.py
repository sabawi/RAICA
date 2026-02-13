"""
Linter Service
=============

Provides static analysis and syntax checking for code files.
Acts as "Gate 1" in the modification pipeline.
"""

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .language_detector import LANGUAGE_DEFINITIONS

logger = logging.getLogger(__name__)

@dataclass
class LinterResult:
    """Result of a linting operation."""
    valid: bool
    errors: List[str]
    command_run: str = ""

class LinterService:
    """
    Service for running linters and syntax checkers.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self._available_tools = self._detect_tools()

    def _detect_tools(self) -> Dict[str, bool]:
        """Detect available linting tools in the environment."""
        tools = {
            'pylint': shutil.which('pylint') is not None,
            'flake8': shutil.which('flake8') is not None,
            'eslint': shutil.which('eslint') is not None,
            'mypy': shutil.which('mypy') is not None,
            'php': shutil.which('php') is not None,
        }
        return tools

    async def check_file(self, file_path: Path, strict: bool = True, baseline: Optional[LinterResult] = None) -> LinterResult:
        """
        Run appropriate checks on a file and optionally filter against a baseline.
        
        Args:
            file_path: Path to the file to check
            strict: Whether to run full linting/type checking (not just syntax)
            baseline: Optional previous result to filter out existing errors
        """
        if not file_path.exists():
            return LinterResult(False, [f"File {file_path} does not exist"])

        ext = file_path.suffix.lower()
        
        result = LinterResult(True, [])
        # Get extensions from language definitions for proper routing
        py_exts = LANGUAGE_DEFINITIONS.get('python', None)
        js_exts = LANGUAGE_DEFINITIONS.get('javascript', None)
        ts_exts = LANGUAGE_DEFINITIONS.get('typescript', None)
        php_exts = LANGUAGE_DEFINITIONS.get('php', None)

        if py_exts and ext in py_exts.file_extensions:
            result = await self._check_python(file_path, strict=strict)
        elif (js_exts and ext in js_exts.file_extensions) or (ts_exts and ext in ts_exts.file_extensions):
            result = await self._check_javascript(file_path)
        elif php_exts and ext in php_exts.file_extensions:
            result = await self._check_php(file_path)
        
        if baseline and not result.valid:
            # [NEW] Line-agnostic baseline filtering.
            # We strip line/column numbers because surgical fixes often shift code,
            # which changes linter output even for pre-existing errors.
            clean_baseline = {self._clean_error(e) for e in baseline.errors}
            
            new_errors = []
            for e in result.errors:
                cleaned = self._clean_error(e)
                if cleaned not in clean_baseline:
                    new_errors.append(e)
            
            if not new_errors:
                return LinterResult(True, [])
            else:
                return LinterResult(False, new_errors, result.command_run)

        return result

    def _clean_error(self, error_text: str) -> str:
        """
        Strip line and column numbers from linter output to allow line-agnostic matching.
        Example: 'file.py:123:10: F841 ...' -> 'file.py: F841 ...'
        """
        # 1. Match typical ":123:10:" or ":123:" pattern
        cleaned = re.sub(r':\d+(?::\d+)?(?::)?', ':', error_text)
        
        # 2. Match "line 123" pattern
        cleaned = re.sub(r'\bline \d+\b', 'line N', cleaned)
        
        # 3. Match "column \d+" pattern
        cleaned = re.sub(r'\bcolumn \d+\b', 'column N', cleaned)

        # 4. Remove actual line content if included (flake8 --show-source often includes it)
        # Typically indented lines after the error message
        lines = cleaned.splitlines()
        if lines:
            # Keep only the first line of the error message for comparison
            # Many linters output: "file:line:col: error_msg\n  offending_line\n    ^"
            return lines[0].strip()
            
        return cleaned.strip()

    async def _check_python(self, file_path: Path, strict: bool = True) -> LinterResult:
        """Check Python files."""
        errors = []
        
        # 1. Syntax Check (Fastest, built-in)
        try:
            # python -m py_compile checks syntax without executing
            cmd = ["python3", "-m", "py_compile", str(file_path)]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                err_msg = stderr.decode().strip()
                # Clean up error message to be more concise
                return LinterResult(False, [f"Syntax Error: {err_msg}"], "python -m py_compile")
                
        except Exception as e:
            return LinterResult(False, [f"Failed to run syntax check: {e}"])

        if not strict:
            return LinterResult(True, []) # Skip linting/type checking in non-strict mode

        # 2. Linter (if available) - Pylint or Flake8
        # We prefer Flake8 for speed, or Pylint for depth.
        # However, for "Gate 1", we mostly care about "Is broken?".
        # Let's check for undefined variables and errors, not style.
        
        lint_cmd = None
        if self._available_tools['flake8']:
            # Ignore style (E, W), look for functional errors (F) and syntax (E9)
            # Specifically ignore:
            # - F401: unused imports (common during surgical fixes)
            # - F541: f-string is missing placeholders (minor)
            lint_cmd = ["flake8", "--select=F,E9", "--extend-ignore=F401,F541", "--show-source", str(file_path)]
        elif self._available_tools['pylint']:
            # Errors only (-E)
            lint_cmd = ["pylint", "-E", "--output-format=text", str(file_path)]
            
        if lint_cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *lint_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.project_dir) # Run from project root for config
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode != 0:
                    output = stdout.decode().strip() + stderr.decode().strip()
                    if output:
                        errors.append(f"Linter detected issues:\n{output}")
                        return LinterResult(False, errors, " ".join(lint_cmd))
                        
            except Exception as e:
                logger.warning(f"Linter run failed: {e}")

        # 3. Type Checking (Mypy)
        if self._available_tools['mypy']:
            try:
                # --ignore-missing-imports: Don't fail if third-party libs aren't typed
                # --follow-imports=silent: Don't complain about other files
                # --show-column-numbers: Good for parsing
                cmd = ["mypy", "--ignore-missing-imports", "--follow-imports=silent", "--show-column-numbers", str(file_path)]
                
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.project_dir)
                )
                stdout, stderr = await proc.communicate()
                
                # Mypy returns non-zero on type errors
                if proc.returncode != 0:
                    output = stdout.decode().strip() + stderr.decode().strip()
                    # Filter out success messages if random
                    if output and "Success:" not in output:
                        errors.append(f"Type Check Failed:\n{output}")
                        return LinterResult(False, errors, " ".join(cmd))
                        
            except Exception as e:
                logger.warning(f"Mypy check failed: {e}")

        return LinterResult(True, [])

    async def _check_javascript(self, file_path: Path) -> LinterResult:
        """Check JS/TS files."""
        # Check if eslint is available locally or globally
        # Try local node_modules first
        local_eslint = self.project_dir / "node_modules" / ".bin" / "eslint"
        
        cmd = None
        if local_eslint.exists():
            cmd = [str(local_eslint), str(file_path)]
        elif self._available_tools['eslint']:
            cmd = ["eslint", str(file_path)]
            
        if cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.project_dir)
                )
                # Add timeout to prevent hanging
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    logger.warning(f"ESLint timed out after 30s for {file_path}")
                    return LinterResult(True, [])  # Assume OK if times out

                if proc.returncode != 0:
                    output = stdout.decode().strip()
                    if output:
                        return LinterResult(False, [output], " ".join(cmd))
            except Exception as e:
                logger.warning(f"ESLint failed: {e}")
                
        return LinterResult(True, [])

    async def _check_php(self, file_path: Path) -> LinterResult:
        """Check PHP syntax."""
        try:
            cmd = ["php", "-l", str(file_path)]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                output = stdout.decode().strip() or stderr.decode().strip()
                # filter out "No syntax errors detected" if return code is somehow wrong (rare)
                if "No syntax errors detected" not in output:
                     return LinterResult(False, [output], "php -l")
                     
        except Exception:
            pass
            
        return LinterResult(True, [])
