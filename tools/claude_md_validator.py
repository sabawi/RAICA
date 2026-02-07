#!/usr/bin/env python3
"""
CLAUDE.md Compliance Validator
==============================

Pre-commit hook that validates code changes against CLAUDE.md architectural rules.

CRITICAL: If this validator fails, the commit is REJECTED and any testing done
is INVALIDATED. The code must be redesigned and retested before committing.

Usage:
    python tools/claude_md_validator.py [files...]
    python tools/claude_md_validator.py --staged  # Check staged files only
    python tools/claude_md_validator.py --all     # Check all Python files

Exit codes:
    0 = All checks passed
    1 = Violations found (commit should be rejected)
    2 = Error running validator

Integration:
    Add to .git/hooks/pre-commit or use with pre-commit framework
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional


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
        return (
            f"\n{'='*70}\n"
            f"❌ {self.severity}: {self.rule}\n"
            f"   File: {self.file}:{self.line}\n"
            f"   Issue: {self.message}\n"
            f"   Code: {self.code_snippet[:100]}...\n" if self.code_snippet else ""
            f"   Fix: {self.suggestion}\n" if self.suggestion else ""
        )


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
    # Security guardrails are allowed (e.g., blocking rm -rf /)
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
# VIOLATION DETECTION RULES
# ═══════════════════════════════════════════════════════════════════════════════

class ClaudeMdValidator:
    """
    Validates Python code against CLAUDE.md architectural rules.

    The Cardinal Rule: LLM decides everything, RAICA executes blindly.
    """

    def __init__(self):
        self.violations: List[Violation] = []

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
        self._check_hardcoded_keyword_lists(filepath, content, lines)
        self._check_pattern_matching_on_text(filepath, content, lines)
        self._check_language_specific_detection(filepath, content, lines)
        self._check_special_case_handlers(filepath, content, lines)
        self._check_hardcoded_fallbacks(filepath, content, lines)

        return self.violations

    def _check_hardcoded_keyword_lists(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No hardcoded keyword lists for interpreting user intent.

        FORBIDDEN:
            KEYWORDS = ["fix", "debug", "install", ...]
            WEB_SEARCH_KEYWORDS = [...]
            if word in KEYWORDS:
        """
        # Pattern: Variable assignments that look like keyword lists
        patterns = [
            (r'(?:KEYWORDS|PATTERNS|TRIGGERS|COMMANDS)\s*=\s*[\[\{]',
             "Hardcoded keyword list detected"),
            (r'_(?:KEYWORDS|PATTERNS|WORDS|TERMS)\s*=\s*[\[\{]',
             "Hardcoded keyword list detected (private variable)"),
            (r'(?:keywords|patterns|triggers)\s*=\s*[\[\"\'].*[\"\']',
             "Inline keyword list detected"),
        ]

        for line_num, line in enumerate(lines, 1):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Check if it's in an excluded function
                    if self._is_in_excluded_function(lines, line_num):
                        continue

                    self.violations.append(Violation(
                        file=filepath,
                        line=line_num,
                        rule="NO_HARDCODED_KEYWORDS",
                        severity="ERROR",
                        message=message,
                        code_snippet=line.strip(),
                        suggestion="Let LLM classify/interpret instead of hardcoded keywords"
                    ))

    def _check_pattern_matching_on_text(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No pattern matching on user request text.

        FORBIDDEN:
            if "install" in request:
            if request.lower().startswith("fix"):
            if any(word in text for word in [...]):
        """
        patterns = [
            # Direct string matching on request/text/prompt variables
            (r'if\s+["\'][\w\s]+["\']\s+in\s+(?:request|text|prompt|user_input|message)',
             "Pattern matching on user text"),
            (r'if\s+(?:request|text|prompt|message).*\.(?:startswith|endswith|contains)\s*\(["\']',
             "String method pattern matching on user text"),
            (r'if\s+any\s*\(.*\s+in\s+(?:request|text|prompt|message)',
             "Any/all pattern matching on user text"),
            (r'for\s+\w+\s+in\s+(?:KEYWORDS|PATTERNS|WORDS).*if.*in\s+(?:request|text)',
             "Keyword iteration pattern matching"),
        ]

        for line_num, line in enumerate(lines, 1):
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
                        code_snippet=line.strip(),
                        suggestion="Use LLM to classify/interpret the text semantically"
                    ))

    def _check_language_specific_detection(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No hardcoded language/file type detection patterns.

        FORBIDDEN:
            if '<!DOCTYPE' in content:  # HTML detection
            if 'import ' in content:    # Python detection
            if 'function ' in content:  # JavaScript detection
        """
        patterns = [
            # HTML detection
            (r'if\s+["\']<!DOCTYPE["\'].*in\s+\w+',
             "Hardcoded HTML detection pattern"),
            (r'if\s+["\']<html["\'].*in\s+\w+',
             "Hardcoded HTML detection pattern"),
            # Python detection
            (r'if\s+["\']import\s+["\'].*in\s+\w+',
             "Hardcoded Python detection pattern"),
            (r'if\s+["\']def\s+["\'].*in\s+\w+',
             "Hardcoded Python detection pattern"),
            # JavaScript detection
            (r'if\s+["\']function\s+["\'].*in\s+\w+',
             "Hardcoded JavaScript detection pattern"),
            (r'if\s+["\']const\s+["\'].*in\s+\w+',
             "Hardcoded JavaScript detection pattern"),
            # File extension detection for classification
            (r'if\s+\w+\.endswith\s*\(\s*["\']\.(?:py|js|html|css)["\']',
             "Hardcoded file extension classification"),
        ]

        for line_num, line in enumerate(lines, 1):
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
                        code_snippet=line.strip(),
                        suggestion="Ask LLM to detect language/type instead"
                    ))

    def _check_special_case_handlers(self, filepath: str, content: str, lines: List[str]):
        """
        Rule: No special case handlers based on error types or request types.

        FORBIDDEN:
            if error_type == "ImportError":
            if request_type == "install":
            elif classification == "CODE_DEBUG":  # When used for hardcoded routing
        """
        patterns = [
            # Error type special handling
            (r'if\s+(?:error_type|error_name|exc_type)\s*==\s*["\']',
             "Special case handler for specific error type"),
            # Request type hardcoded routing (when not from LLM classification)
            (r'if\s+["\'](?:install|fix|debug|create|delete)["\']\s+in\s+',
             "Special case handler based on request keywords"),
        ]

        for line_num, line in enumerate(lines, 1):
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
                        code_snippet=line.strip(),
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
            # Returning hardcoded commands as fallback
            (r'return\s*\[\s*["\'](?:ls|cd|pwd|echo|cat)',
             "Hardcoded command fallback"),
            # Returning hardcoded classification
            (r'return\s+["\'](?:unknown|default|fallback)["\']',
             "Hardcoded classification fallback"),
        ]

        for line_num, line in enumerate(lines, 1):
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
                        code_snippet=line.strip(),
                        suggestion="Fail explicitly instead of guessing"
                    ))

    def _is_in_excluded_function(self, lines: List[str], line_num: int) -> bool:
        """Check if the line is inside an excluded function."""
        # Look backwards for function definition
        for i in range(line_num - 1, max(0, line_num - 50), -1):
            line = lines[i].strip()
            if line.startswith('def '):
                func_name = line.split('(')[0].replace('def ', '').strip()
                for excluded in EXCLUDED_FUNCTIONS:
                    if excluded in func_name:
                        return True
                return False
            if line.startswith('class '):
                return False  # Hit class definition, stop looking
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
        # Skip venv, __pycache__, etc.
        if any(skip in str(path) for skip in ['venv', '__pycache__', '.git', 'archive']):
            continue
        files.append(str(path))
    return files


def main():
    parser = argparse.ArgumentParser(
        description='CLAUDE.md Compliance Validator - Pre-commit Hook'
    )
    parser.add_argument('files', nargs='*', help='Files to validate')
    parser.add_argument('--staged', action='store_true', help='Check staged files only')
    parser.add_argument('--all', action='store_true', help='Check all Python files')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Determine files to check
    if args.staged:
        files = get_staged_files()
        print(f"🔍 Checking {len(files)} staged files...")
    elif args.all:
        files = get_all_python_files()
        print(f"🔍 Checking {len(files)} Python files...")
    elif args.files:
        files = args.files
        print(f"🔍 Checking {len(files)} specified files...")
    else:
        # Default: staged files
        files = get_staged_files()
        if not files:
            print("✅ No Python files staged for commit")
            return 0
        print(f"🔍 Checking {len(files)} staged files...")

    if not files:
        print("✅ No files to check")
        return 0

    # Run validation
    validator = ClaudeMdValidator()
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
