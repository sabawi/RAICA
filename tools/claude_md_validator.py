#!/usr/bin/env python3
"""
CLAUDE.md Compliance Validator
==============================

Pre-commit hook that validates code changes against CLAUDE.md architectural rules.

CRITICAL: If this validator fails, the commit is REJECTED and any testing done
is INVALIDATED. The code must be redesigned and retested before committing.

Usage:
    python tools/claude_md_validator.py [files...]
    python tools/claude_md_validator.py --staged  # Check staged (diff-only) lines
    python tools/claude_md_validator.py --all     # Check all Python files (full scan)

Exit codes:
    0 = All checks passed
    1 = Violations found (commit should be rejected)
    2 = Error running validator

Integration:
    Add to .git/hooks/pre-commit or use with pre-commit framework

Modes:
    --staged : Only checks NEWLY ADDED/MODIFIED lines in the git diff.
               Pre-existing code is not flagged, preventing false positives
               on large files where only a few lines changed.
    --all    : Full-file scan of every Python file (for auditing).
    [files]  : Full-file scan of specified files.
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Dict, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# VIOLATION TYPES - Based on CLAUDE.md Rules
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Violation:
    """A single CLAUDE.md violation."""
    file: str
    line: int
    rule: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    code_snippet: str = ""
    suggestion: str = ""

    def __str__(self) -> str:
        parts = [
            f"\n{'='*70}",
            f"❌ {self.severity}: {self.rule}",
            f"   File: {self.file}:{self.line}",
            f"   Issue: {self.message}",
        ]
        if self.code_snippet:
            parts.append(f"   Code: {self.code_snippet[:100]}...")
        if self.suggestion:
            parts.append(f"   Fix: {self.suggestion}")
        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# EXCLUDED PATHS - Files that are allowed to have "violations"
# ═══════════════════════════════════════════════════════════════════════════════

EXCLUDED_PATHS = {
    # This validator itself (meta-code)
    'tools/claude_md_validator.py',
    # Test files may have patterns for testing
    'tests/',
    # User tools (plugin-style code with legitimate file system operations)
    'user_tools/',
    # Configuration files
    'config/',
    # Archive/experimental
    'archive/',
}

EXCLUDED_FUNCTIONS = {
    # Security guardrails are allowed
    'is_blocked_command',
    'check_security',
    'validate_safety',
    # Pre-commit validation itself
    '_check_',
    # File system operations (legitimate file extension filtering)
    'discover_user_tools',
    'load_tool_from_file',
}


# ═══════════════════════════════════════════════════════════════════════════════
# GIT DIFF PARSING - Extract only changed lines for --staged mode
# ═══════════════════════════════════════════════════════════════════════════════

def get_staged_diff_lines() -> Dict[str, Set[int]]:
    """
    Parse `git diff --cached` to find which line numbers were added/modified
    in each staged Python file.

    Returns:
        Dict mapping filepath -> set of added/modified line numbers.
    """
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '-U0', '--diff-filter=ACM'],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        return {}

    changed: Dict[str, Set[int]] = {}
    current_file: Optional[str] = None

    for line in result.stdout.split('\n'):
        # Detect file header: +++ b/path/to/file.py
        if line.startswith('+++ b/'):
            path = line[6:]
            if path.endswith('.py'):
                current_file = path
                changed.setdefault(current_file, set())
            else:
                current_file = None
            continue

        # Detect hunk header: @@ -old,count +new,count @@
        if current_file and line.startswith('@@'):
            match = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) else 1
                for ln in range(start, start + count):
                    changed[current_file].add(ln)

    return changed


# ═══════════════════════════════════════════════════════════════════════════════
# VIOLATION DETECTION RULES
# ═══════════════════════════════════════════════════════════════════════════════

class ClaudeMdValidator:
    """
    Validates Python code against CLAUDE.md architectural rules.

    The Cardinal Rule: LLM decides everything, RAICA executes blindly.
    """

    def __init__(self, changed_lines: Optional[Dict[str, Set[int]]] = None):
        """
        Args:
            changed_lines: If provided, only flag violations on these line
                           numbers (diff-only mode). None = full-file scan.
        """
        self.violations: List[Violation] = []
        self.changed_lines = changed_lines

    def _should_check_line(self, filepath: str, line_num: int) -> bool:
        """Return True if this line should be checked (always True in full-scan mode)."""
        if self.changed_lines is None:
            return True
        file_lines = self.changed_lines.get(filepath, set())
        return line_num in file_lines

    def validate_file(self, filepath: str) -> List[Violation]:
        """Validate a single file against CLAUDE.md rules."""
        self.violations = []

        # Check exclusions
        for excluded in EXCLUDED_PATHS:
            if excluded in filepath:
                return []

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            return [Violation(
                file=filepath, line=0, rule="FILE_READ_ERROR",
                severity="ERROR", message=f"Could not read file: {e}"
            )]

        # Run all checks
        self._check_hardcoded_intent_routing(filepath, content, lines)
        self._check_pattern_matching_on_user_text(filepath, content, lines)
        self._check_language_specific_detection(filepath, content, lines)
        self._check_special_case_handlers(filepath, content, lines)
        self._check_hardcoded_fallbacks(filepath, content, lines)

        return self.violations

    def _check_hardcoded_intent_routing(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No hardcoded keyword lists for INTERPRETING USER INTENT or
        ROUTING REQUESTS. This is the core CLAUDE.md violation.

        FORBIDDEN (intent routing / request classification):
            WEB_SEARCH_KEYWORDS = ["latest news", "find", ...]
            CLASSIFICATION_KEYWORDS = {"debug": ..., "fix": ...}
            if word in REQUEST_KEYWORDS:

        ALLOWED (legitimate infrastructure code):
            stop_words = {"the", "a", "an"}       # NLP preprocessing
            date_patterns = [r"\\d{4}-\\d{2}"]    # Data parsing regex
            error_patterns = [...]                  # Log parsing
            json_patterns = [...]                   # Format detection
            email_keywords = [...]                  # Post-LLM content routing
        """
        # Targeted patterns: UPPER_CASE constants that route/classify user intent
        patterns = [
            # SCREAMING_CASE keyword lists for routing (the actual CLAUDE.md violation)
            (r'\b(?:SEARCH|ROUTING|CLASSIFICATION|INTENT|REQUEST|CATEGORY|COMMAND)_?(?:KEYWORDS|WORDS|TERMS|TRIGGERS)\s*=\s*[\[\{]',
             "Hardcoded intent-routing keyword list"),
            # Generic KEYWORDS/COMMANDS constant assignment (likely routing)
            (r'\b(?:KEYWORDS|COMMANDS)\s*=\s*\[',
             "Hardcoded keyword/command routing list"),
            # Keyword-based request routing: checking if user text contains action words
            (r'if\s+\w+\s+in\s+(?:KEYWORDS|SEARCH_KEYWORDS|ROUTING_KEYWORDS|COMMANDS)',
             "Keyword-based request routing"),
        ]

        for line_num, line in enumerate(lines, 1):
            if not self._should_check_line(filepath, line_num):
                continue

            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line):
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_HARDCODED_KEYWORDS",
                        severity="ERROR",
                        message=message,
                        code_snippet=stripped,
                        suggestion="Let LLM classify/interpret user intent instead of hardcoded keywords"
                    ))

    def _check_pattern_matching_on_user_text(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No pattern matching on user request text to determine intent.

        FORBIDDEN:
            if "install" in request:
            if request.lower().startswith("fix"):
            if any(word in user_prompt for word in [...]):

        ALLOWED:
            if "install" in llm_response:   # Parsing structured LLM output is fine
        """
        # Only flag variables that clearly represent user input
        user_text_vars = r'(?:request|user_input|user_prompt|user_message|user_text|user_query)'

        patterns = [
            (rf'if\s+["\'][\w\s]+["\']\s+in\s+{user_text_vars}',
             "Pattern matching on user text to determine intent"),
            (rf'if\s+{user_text_vars}.*\.(?:startswith|endswith)\s*\(["\']',
             "String method pattern matching on user text"),
            (rf'if\s+any\s*\(.*\s+in\s+{user_text_vars}',
             "Any/all pattern matching on user text"),
        ]

        for line_num, line in enumerate(lines, 1):
            if not self._should_check_line(filepath, line_num):
                continue

            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_PATTERN_MATCHING_ON_TEXT",
                        severity="ERROR",
                        message=message,
                        code_snippet=stripped,
                        suggestion="Use LLM to classify/interpret the text semantically"
                    ))

    def _check_language_specific_detection(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No hardcoded language/file type detection patterns for
        classification purposes (LLM should classify content type).

        FORBIDDEN:
            if '<!DOCTYPE' in content:  # HTML detection for routing
            if 'import ' in content:    # Python detection for routing

        ALLOWED:
            if filename.endswith('.py'):  # File extension for loading (infrastructure)
        """
        patterns = [
            (r'if\s+["\']<!DOCTYPE["\'].*in\s+\w+',
             "Hardcoded HTML detection pattern"),
            (r'if\s+["\']<html["\'].*in\s+\w+',
             "Hardcoded HTML detection pattern"),
            (r'if\s+["\']import\s+["\'].*in\s+\w+',
             "Hardcoded Python detection pattern"),
            (r'if\s+["\']def\s+["\'].*in\s+\w+',
             "Hardcoded Python detection pattern"),
            (r'if\s+["\']function\s+["\'].*in\s+\w+',
             "Hardcoded JavaScript detection pattern"),
            (r'if\s+["\']const\s+["\'].*in\s+\w+',
             "Hardcoded JavaScript detection pattern"),
        ]

        for line_num, line in enumerate(lines, 1):
            if not self._should_check_line(filepath, line_num):
                continue

            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_HARDCODED_LANGUAGE_DETECTION",
                        severity="ERROR",
                        message=message,
                        code_snippet=stripped,
                        suggestion="Ask LLM to detect language/type instead"
                    ))

    def _check_special_case_handlers(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No special case handlers based on error types or request types.

        FORBIDDEN:
            if error_type == "ImportError":
            if request_type == "install":
        """
        patterns = [
            (r'if\s+(?:error_type|error_name|exc_type)\s*==\s*["\']',
             "Special case handler for specific error type"),
            (r'if\s+["\'](?:install|fix|debug|create|delete)["\']\s+in\s+',
             "Special case handler based on request keywords"),
        ]

        for line_num, line in enumerate(lines, 1):
            if not self._should_check_line(filepath, line_num):
                continue

            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_SPECIAL_CASE_HANDLERS",
                        severity="WARNING",
                        message=message,
                        code_snippet=stripped,
                        suggestion="Use generic LLM-driven handling instead"
                    ))

    def _check_hardcoded_fallbacks(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No hardcoded fallback defaults when LLM fails.

        FORBIDDEN:
            return ['ls -la']  # Default command
            return "unknown"   # Default classification

        ALLOWED:
            raise RuntimeError("LLM failed")  # Fail explicitly
        """
        patterns = [
            (r'return\s*\[\s*["\'](?:ls|cd|pwd|echo|cat)',
             "Hardcoded command fallback"),
            (r'return\s+["\'](?:unknown|default|fallback)["\']',
             "Hardcoded classification fallback"),
        ]

        for line_num, line in enumerate(lines, 1):
            if not self._should_check_line(filepath, line_num):
                continue

            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_HARDCODED_FALLBACKS",
                        severity="WARNING",
                        message=message,
                        code_snippet=stripped,
                        suggestion="Fail explicitly instead of guessing"
                    ))

    def _is_in_excluded_function(self, lines: List[str], line_num: int) -> bool:
        """Check if the line is inside an excluded function."""
        for i in range(line_num - 1, max(0, line_num - 50), -1):
            line = lines[i].strip()
            if line.startswith('def '):
                func_name = line.split('(')[0].replace('def ', '').strip()
                for excluded in EXCLUDED_FUNCTIONS:
                    if excluded in func_name:
                        return True
                return False
            if line.startswith('class '):
                return False
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def get_staged_files() -> List[str]:
    """Get list of staged Python files."""
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
            capture_output=True, text=True, check=True
        )
        files = result.stdout.strip().split('\n')
        return [f for f in files if f.endswith('.py') and f]
    except subprocess.CalledProcessError:
        return []


def get_all_python_files(root: str = '.') -> List[str]:
    """Get all Python files in the project."""
    files = []
    for path in Path(root).rglob('*.py'):
        if any(skip in str(path) for skip in ['venv', '__pycache__', '.git', 'archive']):
            continue
        files.append(str(path))
    return files


def main():
    parser = argparse.ArgumentParser(
        description='CLAUDE.md Compliance Validator - Pre-commit Hook'
    )
    parser.add_argument('files', nargs='*', help='Files to validate')
    parser.add_argument('--staged', action='store_true',
                        help='Check only added/modified lines in staged diff')
    parser.add_argument('--all', action='store_true', help='Full-scan all Python files')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Determine files and mode
    changed_lines = None  # None = full-file scan

    if args.staged:
        changed_lines = get_staged_diff_lines()
        files = list(changed_lines.keys())
        total_lines = sum(len(v) for v in changed_lines.values())
        print(f"🔍 Checking {total_lines} changed lines across {len(files)} staged file(s)...")
    elif args.all:
        files = get_all_python_files()
        print(f"🔍 Full-scan checking {len(files)} Python files...")
    elif args.files:
        files = args.files
        print(f"🔍 Checking {len(files)} specified files...")
    else:
        changed_lines = get_staged_diff_lines()
        files = list(changed_lines.keys())
        if not files:
            print("✅ No Python files staged for commit")
            return 0
        total_lines = sum(len(v) for v in changed_lines.values())
        print(f"🔍 Checking {total_lines} changed lines across {len(files)} staged file(s)...")

    if not files:
        print("✅ No files to check")
        return 0

    # Run validation
    validator = ClaudeMdValidator(changed_lines=changed_lines)
    all_violations: List[Violation] = []

    for filepath in files:
        if not os.path.exists(filepath):
            continue
        violations = validator.validate_file(filepath)
        all_violations.extend(violations)

    # Report results
    errors = [v for v in all_violations if v.severity == "ERROR"]
    warnings = [v for v in all_violations if v.severity == "WARNING"]

    if all_violations:
        print("\n" + "="*70)
        print("🚨 CLAUDE.MD COMPLIANCE VIOLATIONS FOUND 🚨")
        print("="*70)

        for v in all_violations:
            print(v)

        print("\n" + "="*70)
        print(f"Summary: {len(errors)} ERROR(s), {len(warnings)} WARNING(s)")
        print("="*70)

        if errors:
            print("""
╔══════════════════════════════════════════════════════════════════════╗
║  ❌ COMMIT REJECTED - CLAUDE.MD VIOLATIONS FOUND                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  The code violates RAICA's architectural principles:                 ║
║  • LLM decides everything, RAICA executes blindly                    ║
║  • No hardcoded keywords, patterns, or special cases                 ║
║                                                                      ║
║  REQUIRED ACTIONS:                                                   ║
║  1. Fix all ERROR violations                                         ║
║  2. Re-run tests (previous tests are INVALIDATED)                    ║
║  3. Re-attempt commit                                                ║
║                                                                      ║
║  TIP: Run with --all for a full audit of all Python files.           ║
╚══════════════════════════════════════════════════════════════════════╝
""")
            return 1
        else:
            print("\n⚠️  Warnings found but commit allowed. Consider fixing.")
            return 0
    else:
        print("\n✅ All CLAUDE.MD compliance checks passed!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
