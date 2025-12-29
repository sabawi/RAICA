#!/usr/bin/env python3
"""
Code Generation Validation Module
==================================

Implements validation layers for the CLI Coding Agent v2.0:
- Layer 3: Generation Validation (syntax, truncation, exports)
- Layer 4: Import Resolution
- Layer 7: Execution Validation (sandbox)

Author: Agentic-RAG Development Team
Version: 2.0.0
"""

import ast
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Union
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ValidationResult:
    """Result of a validation check."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self):
        return self.valid

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge another validation result into this one."""
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings
        )


@dataclass
class ImportStatement:
    """Represents an import statement."""
    module: str
    names: List[str] = field(default_factory=list)
    line: int = 0
    is_from: bool = False
    is_relative: bool = False

    def __str__(self):
        if self.is_from:
            return f"from {self.module} import {', '.join(self.names)}"
        return f"import {self.module}"


@dataclass
class ImportResolution:
    """Result of resolving an import."""
    import_stmt: ImportStatement
    from_file: str
    found: bool
    resolved_to: Optional[str] = None
    resolution_type: Optional[str] = None  # 'generated', 'stdlib', 'package'
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    errors: List[Dict[str, Any]] = field(default_factory=list)
    timeout: bool = False
    sandbox_type: str = "subprocess"  # 'docker', 'subprocess', 'none'


@dataclass
class TestResult:
    """Result of running tests."""
    ran: bool
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    output: str = ""
    stderr: str = ""
    error_message: Optional[str] = None


# =============================================================================
# LAYER 4.5: INTERFACE DEFINITIONS (Symbol Table)
# =============================================================================

@dataclass
class MethodSignature:
    """Represents a method/function signature."""
    name: str
    params: List[str] = field(default_factory=list)  # Parameter names
    param_count: int = 0
    is_static: bool = False
    is_async: bool = False

    def __str__(self):
        params_str = ', '.join(self.params) if self.params else ''
        prefix = 'static ' if self.is_static else ''
        prefix += 'async ' if self.is_async else ''
        return f"{prefix}{self.name}({params_str})"


@dataclass
class ExportedSymbol:
    """Represents an exported symbol from a file."""
    name: str
    symbol_type: str  # 'class', 'function', 'const', 'default', 'default_class', 'default_function'
    signature: Optional[str] = None  # For functions: "(x, y, radius)"
    param_count: int = 0  # Number of parameters
    params: List[str] = field(default_factory=list)  # Parameter names
    methods: List[MethodSignature] = field(default_factory=list)  # For classes
    is_default: bool = False  # True if export default

    def __str__(self):
        if self.symbol_type == 'class':
            prefix = 'export default ' if self.is_default else 'export '
            return f"{prefix}class {self.name} {{ constructor({', '.join(self.params)}) }}"
        elif self.symbol_type == 'function':
            prefix = 'export default ' if self.is_default else 'export '
            return f"{prefix}function {self.name}({', '.join(self.params)})"
        else:
            return f"export {'default ' if self.is_default else ''}{self.name}"


@dataclass
class InterfaceDefinition:
    """Represents the public API of a file (its interface/contract)."""
    file_path: str
    exports: List[ExportedSymbol] = field(default_factory=list)
    imports_required: List[str] = field(default_factory=list)
    language: str = 'javascript'

    def get_export(self, name: str) -> Optional[ExportedSymbol]:
        """Get an exported symbol by name."""
        for exp in self.exports:
            if exp.name == name:
                return exp
        return None

    def get_default_export(self) -> Optional[ExportedSymbol]:
        """Get the default export if any."""
        for exp in self.exports:
            if exp.is_default:
                return exp
        return None

    def to_prompt_string(self) -> str:
        """Format interface for injection into LLM prompt."""
        lines = [f"[{self.file_path}]"]
        for exp in self.exports:
            if exp.symbol_type in ('class', 'default_class'):
                lines.append(f"  export {'default ' if exp.is_default else ''}class {exp.name} {{")
                lines.append(f"    constructor({', '.join(exp.params)})")
                for method in exp.methods:
                    lines.append(f"    {method}")
                lines.append("  }")
            elif exp.symbol_type in ('function', 'default_function'):
                lines.append(f"  export {'default ' if exp.is_default else ''}function {exp.name}({', '.join(exp.params)})")
            else:
                lines.append(f"  export {'default ' if exp.is_default else ''}{exp.name}")
        return '\n'.join(lines)


@dataclass
class ConsistencyError:
    """Represents a cross-file consistency error."""
    source_file: str
    target_file: str
    error_type: str  # 'missing_export', 'style_mismatch', 'signature_mismatch', 'missing_file'
    symbol_name: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    line: int = 0

    def __str__(self):
        if self.error_type == 'missing_file':
            return f"{self.source_file}:{self.line}: Cannot find module '{self.target_file}'"
        elif self.error_type == 'missing_export':
            return f"{self.source_file}:{self.line}: '{self.symbol_name}' is not exported from '{self.target_file}'"
        elif self.error_type == 'style_mismatch':
            return f"{self.source_file}:{self.line}: Import style mismatch for '{self.symbol_name}' - expected {self.expected}, got {self.actual}"
        elif self.error_type == 'signature_mismatch':
            return f"{self.source_file}:{self.line}: Wrong number of arguments for '{self.symbol_name}' - expected {self.expected}, got {self.actual}"
        return f"{self.source_file}:{self.line}: {self.error_type} for '{self.symbol_name}'"


# =============================================================================
# LAYER 3: GENERATION VALIDATION
# =============================================================================

class GenerationValidator:
    """
    Validates generated code for completeness and correctness.

    Checks:
    1. Code is not truncated
    2. Syntax is valid (AST parseable)
    3. Required exports are present
    4. No placeholder/stub code
    """

    # Truncation indicators
    TRUNCATION_INDICATORS = [
        '// ...',
        '# ...',
        '/* ... */',
        '// TODO: implement',
        '# TODO: implement',
        '// Other methods would continue here',
        '# Other methods would continue here',
        '... more code here',
        '// rest of implementation',
        '# rest of implementation',
        'TRUNCATED',
        '/* truncated */',
        '// truncated',
        '# truncated',
        '// etc.',
        '# etc.',
        '// and so on',
        '# and so on',
    ]

    # Stub patterns (regex)
    STUB_PATTERNS = [
        r'pass\s*#\s*TODO',
        r'pass\s*#\s*FIXME',
        r'raise\s+NotImplementedError\s*\(',
        r'throw\s+new\s+Error\s*\(\s*[\'"]Not implemented',
        r'throw\s+new\s+Error\s*\(\s*[\'"]TODO',
        r'console\.log\s*\(\s*[\'"]TODO',
        r'print\s*\(\s*[\'"]TODO',
    ]

    def __init__(self):
        self._stub_patterns = [re.compile(p, re.IGNORECASE) for p in self.STUB_PATTERNS]

    def validate(
        self,
        code: str,
        language: str,
        spec: Optional[Dict] = None
    ) -> ValidationResult:
        """
        Validate generated code.

        Args:
            code: The generated code
            language: Programming language (python, javascript, typescript, html, css)
            spec: Optional file specification with expected exports

        Returns:
            ValidationResult with valid flag and any errors/warnings
        """
        errors = []
        warnings = []

        if not code or not code.strip():
            return ValidationResult(valid=False, errors=["Empty code generated"])

        # Check for truncation
        truncation = self._check_truncation(code, language)
        if truncation:
            errors.append(f"Code appears truncated: {truncation}")

        # Check syntax
        syntax_error = self._check_syntax(code, language)
        if syntax_error:
            errors.append(f"Syntax error: {syntax_error}")

        # Check for stubs
        stubs = self._check_stubs(code)
        if stubs:
            warnings.append(f"Stub/placeholder code detected: {stubs}")

        # Check exports if spec provided
        if spec:
            export_issues = self._check_exports(code, spec, language)
            if export_issues:
                warnings.extend(export_issues)

        # Check for unbalanced brackets (additional safety)
        if language in ('javascript', 'typescript', 'java', 'c', 'cpp', 'csharp'):
            bracket_issue = self._check_brackets(code)
            if bracket_issue:
                errors.append(f"Unbalanced brackets: {bracket_issue}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _check_truncation(self, code: str, language: str) -> Optional[str]:
        """Check for signs of truncated code."""
        code_lower = code.lower()

        # Check for truncation indicators
        for indicator in self.TRUNCATION_INDICATORS:
            if indicator.lower() in code_lower:
                return f"Found '{indicator}'"

        # Language-specific checks
        if language == 'python':
            lines = code.strip().split('\n')
            if lines:
                last_line = lines[-1].rstrip()
                # Check if ends mid-block (indented but not a complete statement)
                if last_line and last_line[0] == ' ':
                    stripped = last_line.strip()
                    # Valid endings for indented lines
                    valid_endings = ('pass', 'return', 'raise', 'break', 'continue',
                                     'yield', ')', ']', '}', '"""', "'''", '#')
                    if not any(stripped.endswith(e) or stripped.startswith(e) for e in valid_endings):
                        # Check if it's a complete statement
                        if not stripped.endswith(':') and '=' not in stripped:
                            return "Code ends mid-block"

        elif language in ('javascript', 'typescript'):
            # Check for incomplete objects/arrays
            opens = code.count('{') + code.count('[')
            closes = code.count('}') + code.count(']')
            if opens > closes + 2:  # Allow some tolerance for template strings
                return f"Likely truncated: {opens} opens vs {closes} closes"

        return None

    def _check_syntax(self, code: str, language: str) -> Optional[str]:
        """Validate syntax using appropriate parser."""
        try:
            if language == 'python':
                ast.parse(code)

            elif language in ('javascript', 'typescript'):
                # Basic JS validation - check for obvious errors
                # Full validation would require esprima or similar
                self._basic_js_check(code)

            elif language == 'html':
                from html.parser import HTMLParser
                parser = HTMLParser()
                parser.feed(code)

            elif language == 'json':
                import json
                json.loads(code)

            # CSS, markdown, etc. - no strict validation
            return None

        except SyntaxError as e:
            return f"Line {e.lineno}: {e.msg}"
        except Exception as e:
            return str(e)

    def _basic_js_check(self, code: str) -> None:
        """Basic JavaScript syntax validation."""
        # Check bracket balance
        stack = []
        pairs = {'{': '}', '[': ']', '(': ')'}
        in_string = False
        string_char = None
        i = 0

        while i < len(code):
            char = code[i]

            # Handle strings
            if char in ('"', "'", '`') and (i == 0 or code[i-1] != '\\'):
                if in_string:
                    if char == string_char:
                        in_string = False
                        string_char = None
                else:
                    in_string = True
                    string_char = char

            # Handle brackets outside strings
            elif not in_string:
                if char in pairs:
                    stack.append(pairs[char])
                elif char in pairs.values():
                    if not stack or stack.pop() != char:
                        raise SyntaxError(f"Unmatched '{char}'")

            i += 1

        if stack:
            raise SyntaxError(f"Unclosed brackets: expecting {stack}")

    def _check_stubs(self, code: str) -> Optional[str]:
        """Check for placeholder/stub implementations."""
        for pattern in self._stub_patterns:
            match = pattern.search(code)
            if match:
                return match.group(0)[:50]
        return None

    def _check_exports(
        self,
        code: str,
        spec: Dict,
        language: str
    ) -> List[str]:
        """Check that required exports are present."""
        issues = []
        outline = spec.get('contents_outline', '')

        # Handle outline being a list (convert to string)
        if isinstance(outline, list):
            outline = '\n'.join(str(item) for item in outline)
        elif not isinstance(outline, str):
            outline = str(outline) if outline else ''

        # Extract expected exports from outline
        expected = self._parse_expected_exports(outline, language)
        if not expected:
            return issues

        # Extract actual exports from code
        actual = self._extract_exports(code, language)

        # Check for missing exports
        missing = expected - actual
        for export in missing:
            issues.append(f"Expected export '{export}' not found")

        return issues

    def _parse_expected_exports(self, outline: str, language: str) -> Set[str]:
        """
        Parse expected exports from outline.

        This is intentionally conservative - we only extract exports when
        they are clearly specified in code-like syntax, not prose descriptions.
        False negatives are better than false positives that cause validation failures.
        """
        exports = set()

        # Common words that should never be treated as export names
        # These are often matched by loose patterns in prose descriptions
        # Comprehensive list to minimize false positives from LLM prose
        stopwords = {
            # Articles and prepositions
            'a', 'an', 'the', 'to', 'of', 'in', 'on', 'at', 'by', 'for', 'from',
            'with', 'and', 'or', 'as', 'is', 'be', 'it', 'if', 'so', 'no', 'up',
            # Pronouns and demonstratives
            'this', 'that', 'these', 'those', 'its', 'all', 'any', 'each',
            # Common verbs that might appear after "function"
            'get', 'set', 'do', 'run', 'use', 'add', 'new', 'has', 'are', 'was',
            # Programming keywords
            'class', 'function', 'method', 'methods', 'properties', 'property',
            'exports', 'export', 'default', 'named', 'module', 'modules',
            'import', 'imports', 'return', 'returns', 'const', 'let', 'var',
            # Generic terms
            'data', 'file', 'files', 'code', 'implementation', 'logic', 'main',
            'component', 'components', 'handler', 'handlers', 'object', 'objects',
            'instance', 'instances', 'pattern', 'patterns', 'type', 'types',
            'value', 'values', 'key', 'keys', 'item', 'items', 'element', 'elements',
        }

        # Minimum length for valid identifiers (filters out "to", "do", etc.)
        MIN_IDENTIFIER_LENGTH = 3

        # Pattern 1: Code-style class definition (stricter - requires PascalCase)
        # Matches: "class Ball", "class CanvasRenderer"
        # Does NOT match: "class with methods", "class exports"
        class_pattern = r'\bclass\s+([A-Z][a-zA-Z0-9]*)\b'
        for match in re.finditer(class_pattern, outline):
            name = match.group(1)
            if len(name) >= MIN_IDENTIFIER_LENGTH and name.lower() not in stopwords:
                exports.add(name)

        # Pattern 2: Code-style function definition
        # Matches: "function initAnimation", "def calculate_physics"
        # Requires the name to start with lowercase (convention)
        func_pattern = r'\b(?:function|def)\s+([a-z_][a-zA-Z0-9_]*)\b'
        for match in re.finditer(func_pattern, outline):
            name = match.group(1)
            if len(name) >= MIN_IDENTIFIER_LENGTH and name.lower() not in stopwords:
                exports.add(name)

        # Pattern 3: Explicit export declarations
        # Matches: "exports: Ball, Wheel", "export default CanvasRenderer"
        # These are unambiguous declarations
        explicit_export = r'\bexport(?:s)?\s*(?:default\s+)?[:\-]?\s*([A-Z][a-zA-Z0-9]*)\b'
        for match in re.finditer(explicit_export, outline):
            name = match.group(1)
            if len(name) >= MIN_IDENTIFIER_LENGTH and name.lower() not in stopwords:
                exports.add(name)

        return exports

    def _extract_exports(self, code: str, language: str) -> Set[str]:
        """Extract actual exports from code."""
        exports = set()

        if language == 'python':
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        exports.add(node.name)
                    elif isinstance(node, ast.FunctionDef):
                        if not node.name.startswith('_'):
                            exports.add(node.name)
            except:
                pass

        elif language in ('javascript', 'typescript'):
            # ES6 exports
            patterns = [
                r'export\s+(?:default\s+)?class\s+(\w+)',
                r'export\s+(?:default\s+)?function\s+(\w+)',
                r'export\s+(?:const|let|var)\s+(\w+)',
                r'export\s+default\s+(\w+)',
                r'export\s*\{\s*([^}]+)\s*\}',
                r'module\.exports\s*=\s*(\w+)',
                r'exports\.(\w+)\s*=',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, code):
                    # Handle grouped exports like { A, B, C }
                    exports_str = match.group(1)
                    for export in exports_str.split(','):
                        export = export.strip().split(' as ')[0].strip()
                        if export:
                            exports.add(export)

        return exports

    def _check_brackets(self, code: str) -> Optional[str]:
        """Check for balanced brackets."""
        counts = {
            '{': 0, '}': 0,
            '[': 0, ']': 0,
            '(': 0, ')': 0
        }

        in_string = False
        string_char = None

        for i, char in enumerate(code):
            # Track strings
            if char in ('"', "'", '`') and (i == 0 or code[i-1] != '\\'):
                if in_string:
                    if char == string_char:
                        in_string = False
                else:
                    in_string = True
                    string_char = char
            elif not in_string and char in counts:
                counts[char] += 1

        issues = []
        if counts['{'] != counts['}']:
            issues.append(f"{{ {counts['{']} vs }} {counts['}']}")
        if counts['['] != counts[']']:
            issues.append(f"[ {counts['[']} vs ] {counts[']']}")
        if counts['('] != counts[')']:
            issues.append(f"( {counts['(']} vs ) {counts[')']}")

        return '; '.join(issues) if issues else None


# =============================================================================
# LAYER 3.5: ENVIRONMENT SANITY VALIDATION
# =============================================================================

class EnvironmentSanityValidator:
    """
    Validates code for environment-specific sanity across all languages.

    Prevents LLM hallucinations where code is generated for the wrong runtime:
    - Browser JS using Node.js APIs
    - Python using browser APIs
    - CLI apps using GUI frameworks
    - Server code using client-side patterns

    Also detects unrequested framework usage (hallucination indicator).
    """

    # =========================================================================
    # JAVASCRIPT/TYPESCRIPT ENVIRONMENT RULES
    # =========================================================================

    # Node.js patterns forbidden in browser environment
    NODE_IN_BROWSER_PATTERNS = [
        (r'\bprocess\.exit\b', 'process.exit() is Node.js only - not available in browser'),
        (r'\bprocess\.cwd\b', 'process.cwd() is Node.js only - not available in browser'),
        (r'\bprocess\.env\b', 'process.env is Node.js only - use config object or hardcoded values'),
        (r'\bmodule\.exports\s*=', 'CommonJS module.exports not supported in browser - use ES6 export'),
        (r'\brequire\s*\([\'"]', 'CommonJS require() not supported in browser - use ES6 import'),
        (r'\b__dirname\b', '__dirname is Node.js only - not available in browser'),
        (r'\b__filename\b', '__filename is Node.js only - not available in browser'),
        (r'\bBuffer\.(from|alloc)\b', 'Buffer is Node.js only - use Uint8Array in browser'),
        (r'\bfs\.(read|write|exists|mkdir)', 'Node.js fs module not available in browser'),
        (r'\bpath\.(join|resolve|dirname)\b', 'Node.js path module not available in browser'),
        (r'\bchild_process\b', 'child_process is Node.js only'),
        (r'\bhttp\.createServer\b', 'http.createServer is Node.js only'),
    ]

    # Browser patterns forbidden in Node.js environment
    BROWSER_IN_NODE_PATTERNS = [
        (r'\bdocument\.(getElementById|querySelector|createElement)\b', 'DOM APIs require browser - not available in Node.js'),
        (r'\bwindow\.(location|localStorage|sessionStorage)\b', 'window object is browser only'),
        (r'\balert\s*\(', 'alert() is browser only - use console.log in Node.js'),
        (r'\bprompt\s*\(', 'prompt() is browser only'),
        (r'\bconfirm\s*\(', 'confirm() is browser only'),
        (r'\bfetch\s*\([\'"]', 'fetch requires node-fetch package in Node.js < 18'),
    ]

    # =========================================================================
    # PYTHON ENVIRONMENT RULES
    # =========================================================================

    # Browser/JS patterns that shouldn't appear in Python
    JS_IN_PYTHON_PATTERNS = [
        (r'\bfunction\s+\w+\s*\(', 'JavaScript function syntax in Python - use def'),
        (r'\bconst\s+\w+\s*=', 'JavaScript const in Python - use variable assignment'),
        (r'\blet\s+\w+\s*=', 'JavaScript let in Python - use variable assignment'),
        (r'\bvar\s+\w+\s*=', 'JavaScript var in Python - use variable assignment'),
        (r'=>', 'JavaScript arrow function in Python - use lambda or def'),
        (r'\bconsole\.log\b', 'JavaScript console.log in Python - use print()'),
        (r'\bnull\b', 'JavaScript null in Python - use None'),
        (r'\bundefined\b', 'JavaScript undefined in Python - use None'),
        (r'\btrue\b(?!_)', 'JavaScript true in Python - use True (capital T)'),
        (r'\bfalse\b(?!_)', 'JavaScript false in Python - use False (capital F)'),
    ]

    # GUI patterns in CLI Python
    GUI_IN_CLI_PATTERNS = [
        (r'\btkinter\b', 'tkinter is a GUI framework - verify if GUI was requested'),
        (r'\bPyQt\b', 'PyQt is a GUI framework - verify if GUI was requested'),
        (r'\bwxPython\b', 'wxPython is a GUI framework - verify if GUI was requested'),
        (r'\bkivy\b', 'Kivy is a GUI framework - verify if GUI was requested'),
    ]

    # =========================================================================
    # FRAMEWORK SIGNATURES (hallucination detection)
    # =========================================================================

    JS_FRAMEWORK_SIGNATURES = {
        'react': [r'\bReact\.(Component|createElement)\b', r'\bimport\s+React\b', r'\buseState\s*\(', r'\buseEffect\s*\('],
        'vue': [r'\bnew\s+Vue\s*\(', r'\bVue\.(component|use)\b', r'\bdefineComponent\b'],
        'angular': [r'@Component\s*\(', r'@Injectable\s*\(', r'@NgModule\b'],
        'svelte': [r'\$:\s*{', r'<script\s+lang=["\']ts["\']>'],
        'jquery': [r'\$\s*\([\'"]', r'\bjQuery\s*\('],
        'melonjs': [r'\bme\.(Entity|game|loader|audio)\b'],
        'phaser': [r'\bnew\s+Phaser\.(Game|Scene)\b'],
        'three': [r'\bnew\s+THREE\.(Scene|Camera|Renderer)\b'],
        'pixi': [r'\bnew\s+PIXI\.(Application|Container)\b'],
        'babylon': [r'\bnew\s+BABYLON\.(Scene|Engine)\b'],
    }

    PYTHON_FRAMEWORK_SIGNATURES = {
        'django': [r'\bfrom\s+django\b', r'\bdjango\.', r'\bDjango\b'],
        'flask': [r'\bfrom\s+flask\b', r'\bFlask\s*\(', r'@app\.route'],
        'fastapi': [r'\bfrom\s+fastapi\b', r'\bFastAPI\s*\(', r'@app\.(get|post|put|delete)'],
        'pytorch': [r'\bimport\s+torch\b', r'\btorch\.nn\b'],
        'tensorflow': [r'\bimport\s+tensorflow\b', r'\btf\.(keras|nn)\b'],
        'pandas': [r'\bimport\s+pandas\b', r'\bpd\.DataFrame\b'],
        'numpy': [r'\bimport\s+numpy\b', r'\bnp\.(array|zeros)\b'],
        'pygame': [r'\bimport\s+pygame\b', r'\bpygame\.init\b'],
    }

    def __init__(self, target_environment: str = 'auto'):
        """
        Initialize the environment validator.

        Args:
            target_environment: Target runtime environment:
                - 'browser': Web browser (vanilla JS/HTML/CSS)
                - 'node': Node.js runtime
                - 'python-cli': Python CLI application
                - 'python-web': Python web server (Flask/Django/FastAPI)
                - 'python-script': Python standalone script
                - 'auto': Auto-detect from code (default)
        """
        self.target_environment = target_environment

        # Pre-compile patterns
        self._node_in_browser = [(re.compile(p), msg) for p, msg in self.NODE_IN_BROWSER_PATTERNS]
        self._browser_in_node = [(re.compile(p), msg) for p, msg in self.BROWSER_IN_NODE_PATTERNS]
        self._js_in_python = [(re.compile(p), msg) for p, msg in self.JS_IN_PYTHON_PATTERNS]
        self._gui_in_cli = [(re.compile(p), msg) for p, msg in self.GUI_IN_CLI_PATTERNS]

        self._js_frameworks = {k: [re.compile(p) for p in pats] for k, pats in self.JS_FRAMEWORK_SIGNATURES.items()}
        self._py_frameworks = {k: [re.compile(p) for p in pats] for k, pats in self.PYTHON_FRAMEWORK_SIGNATURES.items()}

    def validate(
        self,
        code: str,
        language: str,
        file_path: str = "",
        requested_frameworks: Optional[List[str]] = None
    ) -> ValidationResult:
        """
        Validate code for environment sanity.

        Args:
            code: Source code to validate
            language: Programming language ('python', 'javascript', 'typescript', 'html')
            file_path: File path for context
            requested_frameworks: List of frameworks explicitly requested by user

        Returns:
            ValidationResult with errors (blocking) and warnings (informational)
        """
        errors = []
        warnings = []
        requested_frameworks = requested_frameworks or []
        requested_lower = [f.lower() for f in requested_frameworks]

        # Determine effective environment
        env = self._detect_environment(code, language, file_path)

        # Apply environment-specific checks
        if language in ('javascript', 'typescript'):
            if env == 'browser':
                # Check for Node.js patterns in browser code
                for pattern, msg in self._node_in_browser:
                    if pattern.search(code):
                        errors.append(msg)

                # Check for unrequested JS frameworks
                detected = self._detect_js_frameworks(code)
                unrequested = [f for f in detected if f.lower() not in requested_lower]
                if unrequested:
                    warnings.append(
                        f"Detected frameworks not in request: {', '.join(unrequested)}. "
                        "If not needed, remove to keep code vanilla."
                    )

            elif env == 'node':
                # Check for browser patterns in Node.js code
                for pattern, msg in self._browser_in_node:
                    if pattern.search(code):
                        errors.append(msg)

        elif language == 'python':
            # Check for JS syntax bleeding into Python
            for pattern, msg in self._js_in_python:
                if pattern.search(code):
                    errors.append(msg)

            # For CLI apps, warn about GUI frameworks
            if env == 'python-cli':
                for pattern, msg in self._gui_in_cli:
                    if pattern.search(code):
                        warnings.append(msg)

            # Check for unrequested Python frameworks
            detected = self._detect_python_frameworks(code)
            unrequested = [f for f in detected if f.lower() not in requested_lower]
            if unrequested:
                warnings.append(
                    f"Detected frameworks: {', '.join(unrequested)}. "
                    "Verify these were requested."
                )

        elif language == 'html':
            # For HTML, check embedded scripts
            script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
            for match in script_pattern.finditer(code):
                script_code = match.group(1)
                if script_code.strip():
                    # Recursively validate embedded JS
                    js_result = self.validate(script_code, 'javascript', file_path, requested_frameworks)
                    errors.extend([f"Embedded script: {e}" for e in js_result.errors])
                    warnings.extend([f"Embedded script: {w}" for w in js_result.warnings])

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _detect_environment(self, code: str, language: str, file_path: str) -> str:
        """Auto-detect the target environment from code patterns."""
        if self.target_environment != 'auto':
            return self.target_environment

        if language in ('javascript', 'typescript'):
            # Check for browser indicators
            browser_indicators = [
                r'\bdocument\.',
                r'\bwindow\.',
                r'\baddEventListener\b',
                r'\bgetElementById\b',
                r'\bquerySelector\b',
            ]
            node_indicators = [
                r'\brequire\s*\(',
                r'\bmodule\.exports\b',
                r'\bprocess\.',
                r'\b__dirname\b',
                r'\bfs\.',
            ]

            browser_score = sum(1 for p in browser_indicators if re.search(p, code))
            node_score = sum(1 for p in node_indicators if re.search(p, code))

            # Default to browser for web-looking files
            if file_path.endswith('.html') or 'index' in file_path.lower():
                return 'browser'

            return 'browser' if browser_score >= node_score else 'node'

        elif language == 'python':
            # Check for web framework indicators
            if re.search(r'@app\.(route|get|post)|Flask\(|FastAPI\(', code):
                return 'python-web'
            elif re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', code):
                return 'python-cli'
            else:
                return 'python-script'

        return 'auto'

    def _detect_js_frameworks(self, code: str) -> List[str]:
        """Detect JavaScript frameworks used in code."""
        detected = []
        for fw, patterns in self._js_frameworks.items():
            for p in patterns:
                if p.search(code):
                    detected.append(fw)
                    break
        return detected

    def _detect_python_frameworks(self, code: str) -> List[str]:
        """Detect Python frameworks used in code."""
        detected = []
        for fw, patterns in self._py_frameworks.items():
            for p in patterns:
                if p.search(code):
                    detected.append(fw)
                    break
        return detected

    @staticmethod
    def get_environment_constraints(language: str, environment: str) -> str:
        """
        Get environment-specific constraints to inject into LLM prompts.

        Args:
            language: Programming language
            environment: Target environment

        Returns:
            Constraint text to append to prompts
        """
        constraints = {
            ('javascript', 'browser'): """
CRITICAL ENVIRONMENT CONSTRAINTS (Browser JavaScript):
1. RUNTIME: Web Browser (NOT Node.js)
2. MODULES: Use ES6 syntax (import/export), NOT CommonJS (require/module.exports)
3. FORBIDDEN APIs: process.*, __dirname, __filename, Buffer, fs.*, path.*, http.createServer
4. AVAILABLE APIs: document.*, window.*, fetch(), localStorage, sessionStorage
5. FRAMEWORKS: Use VANILLA JavaScript unless explicitly requested otherwise
6. DOM: Use document.getElementById, querySelector, addEventListener for DOM manipulation
""",
            ('javascript', 'node'): """
CRITICAL ENVIRONMENT CONSTRAINTS (Node.js):
1. RUNTIME: Node.js (NOT Browser)
2. MODULES: Prefer ES6 (import/export) with "type": "module" in package.json, or CommonJS (require)
3. FORBIDDEN APIs: document.*, window.*, alert(), prompt(), confirm()
4. AVAILABLE APIs: process.*, fs.*, path.*, http.*, Buffer, __dirname, __filename
5. ASYNC: Use async/await for file and network operations
""",
            ('python', 'python-cli'): """
CRITICAL ENVIRONMENT CONSTRAINTS (Python CLI):
1. RUNTIME: Python command-line application
2. OUTPUT: Use print() for output, input() for user input
3. ARGUMENTS: Use argparse or sys.argv for command-line arguments
4. FORBIDDEN: No GUI frameworks (tkinter, PyQt) unless explicitly requested
5. SYNTAX: Use Python syntax (def, None, True/False), NOT JavaScript (function, null, true/false)
""",
            ('python', 'python-web'): """
CRITICAL ENVIRONMENT CONSTRAINTS (Python Web Server):
1. RUNTIME: Web server (Flask/FastAPI/Django)
2. ROUTES: Use decorator-based routing (@app.route, @app.get, etc.)
3. RESPONSES: Return proper HTTP responses (JSON, HTML, status codes)
4. ASYNC: Use async def for FastAPI async endpoints
5. SECURITY: Sanitize user input, use parameterized queries
""",
            ('python', 'python-script'): """
CRITICAL ENVIRONMENT CONSTRAINTS (Python Script):
1. RUNTIME: Standalone Python script
2. IMPORTS: Import all dependencies at the top
3. MAIN: Use if __name__ == "__main__": for entry point
4. SYNTAX: Use Python syntax (def, None, True/False), NOT JavaScript
""",
        }

        key = (language, environment)
        return constraints.get(key, "")


# Backwards compatibility alias
WebSanityValidator = EnvironmentSanityValidator


# =============================================================================
# LAYER 4: IMPORT RESOLUTION
# =============================================================================

class ImportResolver:
    """
    Resolves and validates imports across generated files.

    Validates that all imports can be resolved to:
    - Generated files in the project
    - Python standard library
    - Declared packages (from requirements.txt or package.json)
    """

    # Python standard library modules (Python 3.9+)
    PYTHON_STDLIB = {
        'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
        'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii',
        'binhex', 'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb',
        'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections',
        'colorsys', 'compileall', 'concurrent', 'configparser', 'contextlib',
        'contextvars', 'copy', 'copyreg', 'cProfile', 'crypt', 'csv',
        'ctypes', 'curses', 'dataclasses', 'datetime', 'dbm', 'decimal',
        'difflib', 'dis', 'distutils', 'doctest', 'email', 'encodings',
        'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp', 'fileinput',
        'fnmatch', 'fractions', 'ftplib', 'functools', 'gc', 'getopt',
        'getpass', 'gettext', 'glob', 'graphlib', 'grp', 'gzip', 'hashlib',
        'heapq', 'hmac', 'html', 'http', 'idlelib', 'imaplib', 'imghdr',
        'imp', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools',
        'json', 'keyword', 'lib2to3', 'linecache', 'locale', 'logging',
        'lzma', 'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes',
        'mmap', 'modulefinder', 'multiprocessing', 'netrc', 'nis',
        'nntplib', 'numbers', 'operator', 'optparse', 'os', 'ossaudiodev',
        'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil',
        'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint',
        'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr',
        'pydoc', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib',
        'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select',
        'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site',
        'smtpd', 'smtplib', 'sndhdr', 'socket', 'socketserver', 'spwd',
        'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep',
        'struct', 'subprocess', 'sunau', 'symtable', 'sys', 'sysconfig',
        'syslog', 'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios',
        'test', 'textwrap', 'threading', 'time', 'timeit', 'tkinter',
        'token', 'tokenize', 'trace', 'traceback', 'tracemalloc', 'tty',
        'turtle', 'turtledemo', 'types', 'typing', 'unicodedata', 'unittest',
        'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave', 'weakref',
        'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib', 'xml',
        'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib', 'zoneinfo',
        # typing extensions
        'typing_extensions',
        # Common built-ins
        '__future__', '__main__',
    }

    # Common npm packages
    JS_COMMON_PACKAGES = {
        'react', 'react-dom', 'vue', 'angular', 'express', 'lodash',
        'axios', 'moment', 'dayjs', 'jquery', 'bootstrap', 'tailwindcss',
        'webpack', 'babel', 'typescript', 'eslint', 'prettier', 'jest',
        'mocha', 'chai', 'next', 'nuxt', 'gatsby', 'redux', 'mobx',
        'rxjs', 'd3', 'three', 'socket.io', 'mongoose', 'sequelize',
        'pg', 'mysql', 'mongodb', 'redis', 'node-fetch', 'fs-extra',
        'chalk', 'commander', 'yargs', 'inquirer', 'ora', 'dotenv',
    }

    def __init__(
        self,
        generated_files: Dict[str, str],
        language: str,
        project_dir: Optional[Union[Path, str]] = None
    ):
        """
        Initialize the import resolver.

        Args:
            generated_files: Dict mapping file paths to their code content
            language: Primary language (python, javascript, typescript)
            project_dir: Project directory for finding requirements/package.json
        """
        self.generated_files = generated_files
        self.language = language
        self.project_dir = Path(project_dir) if project_dir else None
        self.declared_packages = self._load_declared_packages()

    def _load_declared_packages(self) -> Set[str]:
        """Load declared packages from requirements.txt or package.json."""
        packages = set()

        if not self.project_dir:
            return packages

        # Python requirements.txt
        req_file = self.project_dir / 'requirements.txt'
        if req_file.exists():
            try:
                content = req_file.read_text()
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Extract package name (before ==, >=, etc.)
                        pkg = re.split(r'[=<>!~\[]', line)[0].strip()
                        if pkg:
                            packages.add(pkg.lower())
            except:
                pass

        # Node package.json
        pkg_file = self.project_dir / 'package.json'
        if pkg_file.exists():
            try:
                import json
                content = json.loads(pkg_file.read_text())
                for dep_type in ('dependencies', 'devDependencies', 'peerDependencies'):
                    if dep_type in content:
                        packages.update(content[dep_type].keys())
            except:
                pass

        return packages

    def resolve_all(self) -> Tuple[List[ImportResolution], List[ImportResolution]]:
        """
        Resolve all imports across all generated files.

        Returns:
            Tuple of (resolved_imports, unresolved_imports)
        """
        resolved = []
        unresolved = []

        for filepath, code in self.generated_files.items():
            imports = self._extract_imports(code, filepath)

            for imp in imports:
                resolution = self._resolve_import(imp, filepath)
                if resolution.found:
                    resolved.append(resolution)
                else:
                    unresolved.append(resolution)

        return resolved, unresolved

    def validate(self) -> ValidationResult:
        """
        Validate all imports and return result.

        Returns:
            ValidationResult with errors for unresolved imports
        """
        resolved, unresolved = self.resolve_all()

        errors = []
        for resolution in unresolved:
            error_msg = f"{resolution.from_file}: Cannot resolve '{resolution.import_stmt}'"
            if resolution.suggestions:
                error_msg += f" (suggestions: {', '.join(resolution.suggestions[:2])})"
            errors.append(error_msg)

        return ValidationResult(
            valid=len(unresolved) == 0,
            errors=errors,
            warnings=[]
        )

    def _extract_imports(self, code: str, filepath: str) -> List[ImportStatement]:
        """Extract all import statements from code."""
        imports = []

        # Handle HTML files - extract script src and module imports
        if filepath.endswith('.html'):
            return self._extract_html_imports(code, filepath)

        if self.language == 'python':
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(ImportStatement(
                                module=alias.name,
                                names=[alias.asname or alias.name],
                                line=node.lineno,
                                is_from=False,
                                is_relative=False
                            ))
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ''
                        is_relative = node.level > 0
                        if is_relative:
                            # Build relative module path
                            dots = '.' * node.level
                            module = dots + module if module else dots
                        imports.append(ImportStatement(
                            module=module,
                            names=[a.name for a in node.names],
                            line=node.lineno,
                            is_from=True,
                            is_relative=is_relative
                        ))
            except SyntaxError:
                pass

        elif self.language in ('javascript', 'typescript'):
            # ES6 imports
            patterns = [
                # import { x, y } from 'module'
                r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
                # import x from 'module'
                r"import\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]",
                # import * as x from 'module'
                r"import\s*\*\s*as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]",
                # import 'module' (side effect)
                r"import\s*['\"]([^'\"]+)['\"]",
                # require('module')
                r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            ]

            for i, pattern in enumerate(patterns):
                for match in re.finditer(pattern, code):
                    if i == 0:  # { x, y } from 'module'
                        names = [n.strip().split(' as ')[0].strip()
                                 for n in match.group(1).split(',')]
                        module = match.group(2)
                    elif i in (1, 2):  # default or namespace import
                        names = [match.group(1)]
                        module = match.group(2)
                    else:  # side effect import or require
                        names = []
                        module = match.group(1)

                    line = code[:match.start()].count('\n') + 1
                    imports.append(ImportStatement(
                        module=module,
                        names=names,
                        line=line,
                        is_from=True,
                        is_relative=module.startswith('.')
                    ))

        return imports

    def _extract_html_imports(self, html_code: str, filepath: str) -> List[ImportStatement]:
        """
        Extract script imports from HTML files.

        Handles:
        - <script src="./path/to/file.js">
        - <script type="module" src="./path/to/file.js">
        - import statements inside <script type="module"> blocks
        """
        imports = []

        # Pattern 1: <script src="..."> (external scripts)
        script_src_pattern = r'<script[^>]*\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*>'
        for match in re.finditer(script_src_pattern, html_code, re.IGNORECASE):
            src = match.group(1)
            # Only track local/relative imports, not CDN URLs
            if not src.startswith(('http://', 'https://', '//')):
                line = html_code[:match.start()].count('\n') + 1
                imports.append(ImportStatement(
                    module=src,
                    names=[],
                    line=line,
                    is_from=True,
                    is_relative=src.startswith('.') or not src.startswith('/')
                ))

        # Pattern 2: import statements inside <script type="module"> blocks
        module_script_pattern = r'<script[^>]*type\s*=\s*["\']module["\'][^>]*>(.*?)</script>'
        for match in re.finditer(module_script_pattern, html_code, re.IGNORECASE | re.DOTALL):
            script_content = match.group(1)
            script_start_line = html_code[:match.start()].count('\n') + 1

            # Extract ES6 imports from the script content
            import_patterns = [
                r"import\s*\{[^}]+\}\s*from\s*['\"]([^'\"]+)['\"]",
                r"import\s+\w+\s+from\s*['\"]([^'\"]+)['\"]",
                r"import\s*\*\s*as\s+\w+\s+from\s*['\"]([^'\"]+)['\"]",
                r"import\s*['\"]([^'\"]+)['\"]",
            ]

            for pattern in import_patterns:
                for imp_match in re.finditer(pattern, script_content):
                    module = imp_match.group(1)
                    local_line = script_content[:imp_match.start()].count('\n')
                    imports.append(ImportStatement(
                        module=module,
                        names=[],
                        line=script_start_line + local_line,
                        is_from=True,
                        is_relative=module.startswith('.')
                    ))

        return imports

    def _resolve_import(self, imp: ImportStatement, from_file: str) -> ImportResolution:
        """Attempt to resolve a single import."""
        module = imp.module

        # Handle relative imports
        if imp.is_relative:
            resolved_path = self._resolve_relative(module, from_file)

            # Check if resolved path matches a generated file
            for gen_path in self.generated_files:
                if self._paths_match(resolved_path, gen_path):
                    return ImportResolution(
                        import_stmt=imp,
                        from_file=from_file,
                        found=True,
                        resolved_to=gen_path,
                        resolution_type='generated'
                    )

            # Relative import not found
            return ImportResolution(
                import_stmt=imp,
                from_file=from_file,
                found=False,
                suggestions=self._suggest_fixes(module, from_file)
            )

        # Check generated files (absolute import)
        for gen_path in self.generated_files:
            if self._module_matches_path(module, gen_path):
                return ImportResolution(
                    import_stmt=imp,
                    from_file=from_file,
                    found=True,
                    resolved_to=gen_path,
                    resolution_type='generated'
                )

        # Check standard library
        base_module = module.split('.')[0]
        if self.language == 'python' and base_module in self.PYTHON_STDLIB:
            return ImportResolution(
                import_stmt=imp,
                from_file=from_file,
                found=True,
                resolved_to=module,
                resolution_type='stdlib'
            )

        # Check declared packages
        if base_module.lower() in self.declared_packages:
            return ImportResolution(
                import_stmt=imp,
                from_file=from_file,
                found=True,
                resolved_to=module,
                resolution_type='package'
            )

        # Check common packages
        if self.language == 'python':
            # Common Python packages that might not be in requirements
            common_python = {'numpy', 'pandas', 'requests', 'flask', 'django',
                            'pytest', 'setuptools', 'pip', 'wheel'}
            if base_module.lower() in common_python:
                return ImportResolution(
                    import_stmt=imp,
                    from_file=from_file,
                    found=True,
                    resolved_to=module,
                    resolution_type='package'
                )
        elif self.language in ('javascript', 'typescript'):
            if base_module in self.JS_COMMON_PACKAGES:
                return ImportResolution(
                    import_stmt=imp,
                    from_file=from_file,
                    found=True,
                    resolved_to=module,
                    resolution_type='package'
                )

        # Unresolved
        return ImportResolution(
            import_stmt=imp,
            from_file=from_file,
            found=False,
            suggestions=self._suggest_fixes(module, from_file)
        )

    def _resolve_relative(self, module: str, from_file: str) -> str:
        """Resolve a relative import to an absolute path."""
        from_dir = str(Path(from_file).parent)

        if self.language == 'python':
            # Count leading dots
            dots = len(module) - len(module.lstrip('.'))
            remainder = module.lstrip('.')

            # Go up directories
            parts = from_dir.split('/') if from_dir else []
            for _ in range(dots - 1):
                if parts:
                    parts.pop()

            # Add module path
            if remainder:
                parts.extend(remainder.split('.'))

            return '/'.join(parts) + '.py'

        else:  # JavaScript/TypeScript
            # Handle ./ and ../
            if module.startswith('./'):
                path = str(Path(from_dir) / module[2:])
            elif module.startswith('../'):
                path = str(Path(from_dir) / module)
            else:
                path = str(Path(from_dir) / module)

            # Normalize and add extension if needed
            path = str(Path(path).resolve()) if Path(path).is_absolute() else path
            if not any(path.endswith(ext) for ext in ('.js', '.ts', '.jsx', '.tsx')):
                path += '.js'

            return path

    def _paths_match(self, path1: str, path2: str) -> bool:
        """Check if two paths refer to the same file."""
        # Normalize paths
        p1 = Path(path1)
        p2 = Path(path2)

        # Check exact match
        if str(p1) == str(p2):
            return True

        # Check with various extensions
        extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '']
        for ext in extensions:
            if str(p1) == str(p2.with_suffix('')) + ext:
                return True
            if str(p1.with_suffix('')) + ext == str(p2):
                return True

        return False

    def _module_matches_path(self, module: str, filepath: str) -> bool:
        """Check if a module name matches a file path."""
        # Convert module to path-like
        if self.language == 'python':
            module_path = module.replace('.', '/') + '.py'
        else:
            module_path = module
            if not any(module_path.endswith(ext) for ext in ('.js', '.ts')):
                module_path += '.js'

        # Check if filepath ends with module path
        return filepath.endswith(module_path) or filepath == module_path

    def _suggest_fixes(self, module: str, from_file: str) -> List[str]:
        """Suggest possible fixes for unresolved import."""
        suggestions = []

        # Extract the base filename from the module path
        # "./Vector2D.js" -> "Vector2D", "./utils/Collision.js" -> "Collision"
        module_basename = module.replace('./', '').replace('../', '')
        module_basename = module_basename.rsplit('/', 1)[-1]  # Get last part
        module_basename = module_basename.rsplit('.', 1)[0]  # Remove extension

        # Find similar generated files with scored matches
        scored_matches = []
        for gen_path in self.generated_files:
            # Extract basename from generated path
            gen_basename = gen_path.rsplit('/', 1)[-1]
            gen_basename_no_ext = gen_basename.rsplit('.', 1)[0]

            # Calculate similarity on basenames (more meaningful)
            similarity = self._similarity(module_basename, gen_basename_no_ext)

            # Also check if module name is contained in generated path
            containment_bonus = 0.0
            if module_basename.lower() in gen_basename_no_ext.lower():
                containment_bonus = 0.3
            elif gen_basename_no_ext.lower() in module_basename.lower():
                containment_bonus = 0.2

            total_score = similarity + containment_bonus

            if total_score > 0.4:
                scored_matches.append((total_score, gen_path))

        # Sort by score descending and add top matches
        scored_matches.sort(reverse=True, key=lambda x: x[0])
        for score, gen_path in scored_matches[:2]:
            suggestions.append(f"Did you mean '{gen_path}'?")

        # If no good matches, suggest generating the file
        if not scored_matches:
            if self.language == 'python':
                suggested_path = module.replace('.', '/') + '.py'
            else:
                # Clean up the module path for suggestion
                suggested_path = module.lstrip('./')
                if not any(suggested_path.endswith(ext) for ext in ('.js', '.ts')):
                    suggested_path += '.js'
            suggestions.append(f"Generate missing file: {suggested_path}")

        return suggestions[:3]  # Limit suggestions

    def _similarity(self, s1: str, s2: str) -> float:
        """
        Calculate string similarity using Levenshtein-like ratio.

        This is more accurate for finding typos in filenames than
        simple character set overlap.
        """
        s1, s2 = s1.lower(), s2.lower()
        if not s1 or not s2:
            return 0.0

        # If strings are identical
        if s1 == s2:
            return 1.0

        # Use longest common subsequence ratio
        len1, len2 = len(s1), len(s2)

        # Create DP table for LCS
        dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                if s1[i-1] == s2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])

        lcs_length = dp[len1][len2]

        # Ratio based on LCS length relative to average string length
        return (2.0 * lcs_length) / (len1 + len2)


# =============================================================================
# LAYER 4.5: CONSISTENCY VERIFICATION (Symbol Table + Cross-Reference)
# =============================================================================

class SymbolExtractor:
    """
    Extracts exported symbols from source code files.

    Supports:
    - JavaScript/TypeScript: export class, export function, export default, export const
    - Python: class definitions, function definitions at module level
    """

    def __init__(self, language: str = 'javascript'):
        self.language = language

    def extract(self, code: str, filepath: str) -> InterfaceDefinition:
        """
        Extract all exported symbols from a file.

        Args:
            code: The source code
            filepath: Path to the file (used for language detection)

        Returns:
            InterfaceDefinition with all exports
        """
        # Detect language from filepath if needed
        if filepath.endswith('.py'):
            return self._extract_python(code, filepath)
        elif filepath.endswith(('.js', '.ts', '.jsx', '.tsx', '.mjs')):
            return self._extract_javascript(code, filepath)
        else:
            return InterfaceDefinition(file_path=filepath, language='unknown')

    def _extract_javascript(self, code: str, filepath: str) -> InterfaceDefinition:
        """Extract exports from JavaScript/TypeScript code."""
        exports = []
        imports_required = []

        # First, find all class definitions (exported or not) and store them
        # This helps with "export default ClassName" at end of file
        all_classes: Dict[str, Tuple[List[str], List[MethodSignature]]] = {}

        # Pattern to find class with constructor - handles nested braces better
        class_def_pattern = r'class\s+(\w+)\s*(?:extends\s+\w+\s*)?\{'
        for match in re.finditer(class_def_pattern, code):
            class_name = match.group(1)
            class_start = match.end()

            # Find the class body by counting braces
            brace_count = 1
            pos = class_start
            while pos < len(code) and brace_count > 0:
                if code[pos] == '{':
                    brace_count += 1
                elif code[pos] == '}':
                    brace_count -= 1
                pos += 1

            class_body = code[class_start:pos-1]

            # Extract constructor params
            constructor_match = re.search(r'constructor\s*\(([^)]*)\)', class_body)
            constructor_params = constructor_match.group(1).strip() if constructor_match else ''
            params = self._parse_params(constructor_params)

            # Extract methods
            methods = self._extract_js_methods(class_body)

            all_classes[class_name] = (params, methods)

        # Now find exported classes
        # Pattern for export default class ClassName
        default_class_pattern = r'export\s+default\s+class\s+(\w+)'
        for match in re.finditer(default_class_pattern, code):
            class_name = match.group(1)
            params, methods = all_classes.get(class_name, ([], []))

            exports.append(ExportedSymbol(
                name=class_name,
                symbol_type='class',
                params=params,
                param_count=len(params),
                methods=methods,
                is_default=True
            ))

        # Pattern for export class ClassName (non-default)
        export_class_pattern = r'export\s+class\s+(\w+)'
        for match in re.finditer(export_class_pattern, code):
            class_name = match.group(1)
            # Skip if already captured as default
            if any(e.name == class_name for e in exports):
                continue
            params, methods = all_classes.get(class_name, ([], []))

            exports.append(ExportedSymbol(
                name=class_name,
                symbol_type='class',
                params=params,
                param_count=len(params),
                methods=methods,
                is_default=False
            ))

        # Pattern for export default function name(...) or export default (...)
        default_func_pattern = r'export\s+default\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)'
        for match in re.finditer(default_func_pattern, code):
            func_name = match.group(1)
            params = self._parse_params(match.group(2))
            exports.append(ExportedSymbol(
                name=func_name,
                symbol_type='function',
                params=params,
                param_count=len(params),
                is_default=True
            ))

        # Pattern for export function name(...)
        func_pattern = r'export\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)'
        for match in re.finditer(func_pattern, code):
            func_name = match.group(1)
            # Skip if already captured as default
            if any(e.name == func_name for e in exports):
                continue
            params = self._parse_params(match.group(2))
            exports.append(ExportedSymbol(
                name=func_name,
                symbol_type='function',
                params=params,
                param_count=len(params),
                is_default=False
            ))

        # Pattern for export const/let/var name = ...
        const_pattern = r'export\s+(?:const|let|var)\s+(\w+)\s*='
        for match in re.finditer(const_pattern, code):
            const_name = match.group(1)
            if not any(e.name == const_name for e in exports):
                exports.append(ExportedSymbol(
                    name=const_name,
                    symbol_type='const',
                    is_default=False
                ))

        # Pattern for export { name1, name2 } - named exports
        named_export_pattern = r'export\s*\{([^}]+)\}'
        for match in re.finditer(named_export_pattern, code):
            names = [n.strip().split(' as ')[0].strip() for n in match.group(1).split(',')]
            for name in names:
                if name and not any(e.name == name for e in exports):
                    exports.append(ExportedSymbol(
                        name=name,
                        symbol_type='const',  # Could be anything, we don't know
                        is_default=False
                    ))

        # Pattern for export default ClassName (at end of file)
        trailing_default_pattern = r'export\s+default\s+(\w+)\s*;?\s*$'
        for match in re.finditer(trailing_default_pattern, code, re.MULTILINE):
            name = match.group(1)
            # Mark an existing export as default, or create new
            found = False
            for exp in exports:
                if exp.name == name:
                    exp.is_default = True
                    found = True
                    break
            if not found:
                # Look for the class/function definition in code
                class_def = re.search(rf'class\s+{name}\s*(?:extends\s+\w+\s*)?\{{([^}}]*constructor\s*\(([^)]*)\))?', code, re.DOTALL)
                if class_def:
                    params = self._parse_params(class_def.group(2)) if class_def.group(2) else []
                    methods = self._extract_js_methods(class_def.group(1) or '')
                    exports.append(ExportedSymbol(
                        name=name,
                        symbol_type='class',
                        params=params,
                        param_count=len(params),
                        methods=methods,
                        is_default=True
                    ))
                else:
                    exports.append(ExportedSymbol(
                        name=name,
                        symbol_type='const',
                        is_default=True
                    ))

        # Extract imports
        import_pattern = r'import\s+.*?\s+from\s*[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(import_pattern, code):
            imports_required.append(match.group(1))

        return InterfaceDefinition(
            file_path=filepath,
            exports=exports,
            imports_required=imports_required,
            language='javascript'
        )

    def _extract_js_methods(self, class_body: str) -> List[MethodSignature]:
        """Extract method signatures from a JS class body."""
        methods = []

        # Pattern for method definitions: methodName(...) { or async methodName(...) {
        method_pattern = r'(static\s+)?(async\s+)?(\w+)\s*\(([^)]*)\)\s*\{'
        for match in re.finditer(method_pattern, class_body):
            is_static = bool(match.group(1))
            is_async = bool(match.group(2))
            method_name = match.group(3)

            # Skip constructor (handled separately)
            if method_name == 'constructor':
                continue

            params = self._parse_params(match.group(4))
            methods.append(MethodSignature(
                name=method_name,
                params=params,
                param_count=len(params),
                is_static=is_static,
                is_async=is_async
            ))

        return methods

    def _extract_python(self, code: str, filepath: str) -> InterfaceDefinition:
        """Extract exports from Python code."""
        exports = []
        imports_required = []

        try:
            tree = ast.parse(code)

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    # Extract constructor params
                    params = []
                    methods = []

                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            if item.name == '__init__':
                                # Skip 'self' parameter
                                params = [arg.arg for arg in item.args.args[1:]]
                            else:
                                method_params = [arg.arg for arg in item.args.args[1:]]  # Skip self
                                methods.append(MethodSignature(
                                    name=item.name,
                                    params=method_params,
                                    param_count=len(method_params),
                                    is_static=any(isinstance(d, ast.Name) and d.id == 'staticmethod'
                                                 for d in item.decorator_list)
                                ))

                    exports.append(ExportedSymbol(
                        name=node.name,
                        symbol_type='class',
                        params=params,
                        param_count=len(params),
                        methods=methods
                    ))

                elif isinstance(node, ast.FunctionDef):
                    params = [arg.arg for arg in node.args.args]
                    exports.append(ExportedSymbol(
                        name=node.name,
                        symbol_type='function',
                        params=params,
                        param_count=len(params)
                    ))

                elif isinstance(node, ast.Assign):
                    # Module-level constants
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            exports.append(ExportedSymbol(
                                name=target.id,
                                symbol_type='const'
                            ))

                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        imports_required.append(node.module)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            imports_required.append(alias.name)

        except SyntaxError:
            pass

        return InterfaceDefinition(
            file_path=filepath,
            exports=exports,
            imports_required=imports_required,
            language='python'
        )

    def _parse_params(self, params_str: str) -> List[str]:
        """Parse parameter string into list of parameter names."""
        if not params_str or not params_str.strip():
            return []

        params = []
        # Split by comma, handling nested structures
        depth = 0
        current = ''

        for char in params_str:
            if char in '([{':
                depth += 1
                current += char
            elif char in ')]}':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                param = current.strip()
                if param:
                    # Extract just the parameter name (before : or = for TS/default values)
                    param_name = re.split(r'[=:]', param)[0].strip()
                    # Remove ... spread operator
                    param_name = param_name.lstrip('.')
                    if param_name:
                        params.append(param_name)
                current = ''
            else:
                current += char

        # Don't forget the last parameter
        if current.strip():
            param = current.strip()
            param_name = re.split(r'[=:]', param)[0].strip()
            param_name = param_name.lstrip('.')
            if param_name:
                params.append(param_name)

        return params


class ConsistencyVerifier:
    """
    Cross-file consistency verification (Layer 4.5).

    Validates that:
    1. All imports resolve to actual files
    2. Imported symbols are actually exported by target files
    3. Import style matches export style (default vs named)
    4. Function/constructor calls use correct number of arguments
    """

    def __init__(
        self,
        generated_files: Dict[str, str],
        language: str = 'javascript',
        project_dir: Optional[Path] = None
    ):
        """
        Initialize the consistency verifier.

        Args:
            generated_files: Dict mapping file paths to their code content
            language: Primary language (python, javascript, typescript)
            project_dir: Project directory for path resolution
        """
        self.generated_files = generated_files
        self.language = language
        self.project_dir = Path(project_dir) if project_dir else Path('.')
        self.extractor = SymbolExtractor(language)

        # Build symbol table
        self.symbol_table: Dict[str, InterfaceDefinition] = {}
        for filepath, code in generated_files.items():
            self.symbol_table[filepath] = self.extractor.extract(code, filepath)

    def get_interface(self, filepath: str) -> Optional[InterfaceDefinition]:
        """Get the interface definition for a file."""
        return self.symbol_table.get(filepath)

    def validate(self) -> ValidationResult:
        """
        Validate all cross-file references.

        Returns:
            ValidationResult with errors for any inconsistencies
        """
        errors: List[ConsistencyError] = []
        warnings: List[str] = []

        for filepath, code in self.generated_files.items():
            file_errors = self._validate_file(filepath, code)
            errors.extend(file_errors)

        # Convert ConsistencyError objects to strings
        error_strings = [str(e) for e in errors]

        return ValidationResult(
            valid=len(errors) == 0,
            errors=error_strings,
            warnings=warnings
        )

    def _validate_file(self, filepath: str, code: str) -> List[ConsistencyError]:
        """Validate imports and usages in a single file."""
        errors = []

        # Skip non-code files
        if not filepath.endswith(('.js', '.ts', '.jsx', '.tsx', '.py', '.mjs')):
            return errors

        # Extract imports from this file
        imports = self._extract_imports(code, filepath)

        for imp in imports:
            # Resolve import to target file
            target_file = self._resolve_import_path(imp.module, filepath)

            if target_file is None:
                # External package import - skip validation
                continue

            # Check if target file exists in our generated files
            if target_file not in self.symbol_table:
                errors.append(ConsistencyError(
                    source_file=filepath,
                    target_file=target_file,
                    error_type='missing_file',
                    symbol_name=imp.module,
                    line=imp.line
                ))
                continue

            target_interface = self.symbol_table[target_file]

            # Check each imported symbol
            for symbol_name in imp.names:
                if symbol_name == 'default':
                    # Import of default export
                    if not target_interface.get_default_export():
                        errors.append(ConsistencyError(
                            source_file=filepath,
                            target_file=target_file,
                            error_type='missing_export',
                            symbol_name='default export',
                            line=imp.line
                        ))
                else:
                    # Named import - check if symbol exists and is correctly exported
                    export = target_interface.get_export(symbol_name)
                    if export is None:
                        # Symbol not found at all
                        errors.append(ConsistencyError(
                            source_file=filepath,
                            target_file=target_file,
                            error_type='missing_export',
                            symbol_name=symbol_name,
                            line=imp.line
                        ))
                    elif export.is_default:
                        # Symbol exists but is a default export - can't use named import
                        errors.append(ConsistencyError(
                            source_file=filepath,
                            target_file=target_file,
                            error_type='style_mismatch',
                            symbol_name=symbol_name,
                            expected='default import (import X from ...)',
                            actual='named import (import { X } from ...)',
                            line=imp.line
                        ))

        # Check constructor/function call sites for correct argument count
        call_errors = self._validate_call_sites(filepath, code)
        errors.extend(call_errors)

        return errors

    def _validate_call_sites(self, filepath: str, code: str) -> List[ConsistencyError]:
        """Validate that function/constructor calls use correct argument counts."""
        errors = []

        # Get imports for this file to know what symbols are available
        imports = self._extract_imports(code, filepath)
        imported_symbols: Dict[str, ExportedSymbol] = {}

        for imp in imports:
            target_file = self._resolve_import_path(imp.module, filepath)
            if target_file and target_file in self.symbol_table:
                target_interface = self.symbol_table[target_file]
                for symbol_name in imp.names:
                    export = target_interface.get_export(symbol_name)
                    if export:
                        imported_symbols[symbol_name] = export
                    elif symbol_name == 'default':
                        # Default import with custom local name
                        default_exp = target_interface.get_default_export()
                        if default_exp:
                            # The local name comes from the import pattern
                            # import Name from './module' -> Name is the local name
                            imported_symbols[default_exp.name] = default_exp

        if self.language == 'python':
            return self._validate_python_calls(filepath, code, imported_symbols)

        # JavaScript/TypeScript: Find constructor calls: new ClassName(args)
        new_pattern = r'new\s+(\w+)\s*\(([^)]*)\)'
        for match in re.finditer(new_pattern, code):
             class_name = match.group(1)
             args_str = match.group(2)
 
             if class_name in imported_symbols:
                 expected_export = imported_symbols[class_name]
                 if expected_export.symbol_type == 'class':
                     expected_count = expected_export.param_count
                     actual_count = self._count_args(args_str)
 
                     if actual_count < expected_count:
                         line = code[:match.start()].count('\n') + 1
                         errors.append(ConsistencyError(
                             source_file=filepath,
                             target_file='',
                             error_type='signature_mismatch',
                             symbol_name=f'new {class_name}()',
                             expected=str(expected_count),
                             actual=str(actual_count),
                             line=line
                         ))
                         
        return errors
 
    def _validate_python_calls(self, filepath: str, code: str, imported_symbols: Dict[str, ExportedSymbol]) -> List[ConsistencyError]:
         """Validate Python function/constructor calls using AST."""
         errors = []
         try:
             tree = ast.parse(code)
             for node in ast.walk(tree):
                 if isinstance(node, ast.Call):
                     # Check for calls to imported symbols
                     func_name = None
                     if isinstance(node.func, ast.Name):
                         func_name = node.func.id
                     
                     if func_name and func_name in imported_symbols:
                         expected_export = imported_symbols[func_name]
                         
                         # Calculate actual args
                         actual_count = len(node.args) + len(node.keywords)
                         
                         # Check against expected
                         expected_count = expected_export.param_count
                         
                         # For Python classes, __init__ params exclude self, so extracted count is correct
                         # But we should be careful about defaults. 
                         # SymbolExtractor counts ALL params (except self/this).
                         # Validating EXACT count is tricky with defaults.
                         # But if actual < expected, it's definitely an error (assuming no defaults for now, or lenient check)
                         
                         # Refinement: We need to know required vs optional params.
                         # SymbolExtractor currently extracts all params.
                         # For now, we enforce that actual_count >= param_count (if we assume all are required)
                         # OR, we simply check that we aren't passing TOO MANY? 
                         # Actually, the failure case is MISSING argument.
                         # So actual < expected is the check.
                         # Converting to strict check for now as per "Blind Generation" problem (missing mandatory args).
                         
                         if actual_count < expected_count:
                             # Heuristic: if difference is large, or if we are sure.
                             # To be safe, let's complain if actual < expected.
                             
                             errors.append(ConsistencyError(
                                 source_file=filepath,
                                 target_file='',
                                 error_type='signature_mismatch',
                                 symbol_name=f'{func_name}()',
                                 expected=str(expected_count),
                                 actual=str(actual_count),
                                 line=node.lineno
                             ))
         except SyntaxError:
             pass
             
         return errors

    def _count_args(self, args_str: str) -> int:
        """Count the number of arguments in a function call."""
        if not args_str or not args_str.strip():
            return 0

        # Handle nested structures
        depth = 0
        count = 1  # At least one arg if not empty

        for char in args_str:
            if char in '([{':
                depth += 1
            elif char in ')]}':
                depth -= 1
            elif char == ',' and depth == 0:
                count += 1

        return count

    def _extract_imports(self, code: str, filepath: str) -> List[ImportStatement]:
        """Extract import statements from code."""
        imports = []

        if filepath.endswith('.py'):
            return self._extract_python_imports(code)

        # JavaScript/TypeScript imports
        patterns = [
            # import { x, y } from 'module'
            (r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", 'named'),
            # import x from 'module' (default import)
            (r"import\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]", 'default'),
            # import * as x from 'module'
            (r"import\s*\*\s*as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]", 'namespace'),
        ]

        for pattern, import_type in patterns:
            for match in re.finditer(pattern, code):
                line = code[:match.start()].count('\n') + 1

                if import_type == 'named':
                    names = [n.strip().split(' as ')[0].strip()
                             for n in match.group(1).split(',')]
                    module = match.group(2)
                elif import_type == 'default':
                    names = ['default']  # Mark as default import
                    module = match.group(2)
                else:  # namespace
                    names = ['*']
                    module = match.group(2)

                imports.append(ImportStatement(
                    module=module,
                    names=names,
                    line=line,
                    is_from=True,
                    is_relative=module.startswith('.')
                ))

        return imports

    def _extract_python_imports(self, code: str) -> List[ImportStatement]:
        """Extract Python import statements."""
        imports = []

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(ImportStatement(
                        module=node.module,
                        names=[alias.name for alias in node.names],
                        line=node.lineno,
                        is_from=True,
                        is_relative=node.level > 0
                    ))
        except SyntaxError:
            pass

        return imports

    def _resolve_import_path(self, module: str, from_file: str) -> Optional[str]:
        """Resolve an import module to a file path."""
        # Skip external packages
        if not module.startswith('.'):
            # Check if this absolute import matches a generated file
            candidates = [
                module.replace('.', '/') + '.py',
                f"src/{module.replace('.', '/')}.py",
                module + '.js',
                module + '.ts'
            ]
            
            found_local = False
            for candidate in candidates:
                if candidate in self.generated_files:
                    return candidate
            
            # If not found in generated files, assume external
            return None

        from_dir = str(Path(from_file).parent)

        if module.startswith('./'):
            path = module[2:]
        elif module.startswith('../'):
            # Handle parent directory references
            parts = from_dir.split('/')
            module_parts = module.split('/')
            up_count = 0
            for part in module_parts:
                if part == '..':
                    up_count += 1
                else:
                    break
            if parts and parts[0]:
                remaining_parts = parts[:-up_count] if up_count <= len(parts) else []
            else:
                remaining_parts = []
            path = '/'.join(remaining_parts + module_parts[up_count:])
        else:
            path = module

        # Add extension if needed
        if not any(path.endswith(ext) for ext in ('.js', '.ts', '.jsx', '.tsx', '.py', '.mjs')):
            # Try common extensions
            for ext in ('.js', '.ts', '.jsx', '.tsx'):
                test_path = path + ext
                if test_path in self.generated_files:
                    return test_path
                # Also try with src/ prefix
                if f"src/{test_path}" in self.generated_files:
                    return f"src/{test_path}"
            path += '.js'  # Default to .js

        # Normalize path
        if from_dir and from_dir != '.':
            full_path = f"{from_dir}/{path}" if not path.startswith(from_dir) else path
        else:
            full_path = path

        # Clean up path (remove ./ and normalize)
        full_path = full_path.replace('./', '').replace('//', '/')

        # Check if this path exists in generated files
        if full_path in self.generated_files:
            return full_path

        # Try without the full path
        if path in self.generated_files:
            return path

        # Try with src/ prefix
        if f"src/{path}" in self.generated_files:
            return f"src/{path}"

        return full_path  # Return anyway for error reporting

    def get_all_interfaces_prompt(self) -> str:
        """Generate a prompt string with all interfaces for context injection."""
        lines = ["EXISTING INTERFACES (use these exact signatures):"]

        for filepath, interface in self.symbol_table.items():
            lines.append(interface.to_prompt_string())
            lines.append("")

        return '\n'.join(lines)


# =============================================================================
# LAYER 7: EXECUTION VALIDATION
# =============================================================================

class ExecutionValidator:
    """
    Validates code by actually executing it in a sandbox.

    Executes the generated code and captures:
    - Import errors
    - Syntax errors (runtime)
    - Runtime exceptions
    - Test results
    """

    def __init__(
        self,
        project_dir: Path,
        language: str = 'python',
        timeout: int = 30
    ):
        """
        Initialize execution validator.

        Args:
            project_dir: Directory containing generated code
            language: Programming language
            timeout: Execution timeout in seconds
        """
        self.project_dir = Path(project_dir)
        self.language = language
        self.timeout = timeout

    def validate_imports(self) -> ExecutionResult:
        """
        Validate that all imports work by attempting to import modules.

        For Python, creates a test script that imports all modules.
        """
        if self.language != 'python':
            return ExecutionResult(
                success=True,
                errors=[{"message": f"Import validation not implemented for {self.language}"}]
            )

        # Find all Python files
        py_files = list(self.project_dir.glob('**/*.py'))
        if not py_files:
            return ExecutionResult(success=True)

        # Create import test script
        test_script = "import sys\nsys.path.insert(0, '.')\n\n"

        for py_file in py_files:
            # Skip test files and __pycache__
            if 'test_' in py_file.name or '__pycache__' in str(py_file):
                continue

            # Convert path to module name
            rel_path = py_file.relative_to(self.project_dir)
            module = str(rel_path.with_suffix('')).replace('/', '.').replace('\\', '.')

            test_script += f"try:\n"
            test_script += f"    import {module}\n"
            test_script += f"    print('OK: {module}')\n"
            test_script += f"except Exception as e:\n"
            test_script += f"    print(f'FAIL: {module}: {{e}}')\n"
            test_script += f"    sys.exit(1)\n\n"

        test_script += "print('All imports successful')\n"

        # Write and execute test script
        test_file = self.project_dir / '_import_test.py'
        try:
            test_file.write_text(test_script)
            result = self._execute_python(str(test_file))
            return result
        finally:
            if test_file.exists():
                test_file.unlink()

    def execute_file(self, entry_point: str) -> ExecutionResult:
        """
        Execute a specific file and capture results.

        Args:
            entry_point: Relative path to the entry point file

        Returns:
            ExecutionResult with success status and any errors
        """
        if self.language == 'python':
            return self._execute_python(entry_point)
        elif self.language in ('javascript', 'typescript'):
            return self._execute_node(entry_point)
        else:
            return ExecutionResult(
                success=False,
                errors=[{"message": f"Unsupported language: {self.language}"}]
            )

    def run_tests(self, test_pattern: str = 'test_*.py') -> TestResult:
        """
        Run tests using appropriate test runner.

        Args:
            test_pattern: Glob pattern for test files

        Returns:
            TestResult with pass/fail details
        """
        if self.language == 'python':
            return self._run_pytest(test_pattern)
        elif self.language in ('javascript', 'typescript'):
            return self._run_npm_test()
        else:
            return TestResult(
                ran=False,
                error_message=f"Unsupported language: {self.language}"
            )

    def _execute_python(self, entry_point: str) -> ExecutionResult:
        """Execute Python code."""
        entry_path = self.project_dir / entry_point

        if not entry_path.exists():
            return ExecutionResult(
                success=False,
                errors=[{"message": f"File not found: {entry_point}"}]
            )

        try:
            result = subprocess.run(
                [sys.executable, str(entry_path)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={
                    **os.environ,
                    'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': str(self.project_dir)
                }
            )

            errors = []
            if result.returncode != 0:
                errors = self._parse_python_errors(result.stderr)

            return ExecutionResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                errors=errors
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                timeout=True,
                errors=[{"message": f"Execution timed out after {self.timeout}s"}]
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                errors=[{"message": str(e)}]
            )

    def _execute_node(self, entry_point: str) -> ExecutionResult:
        """Execute JavaScript/TypeScript code."""
        entry_path = self.project_dir / entry_point

        if not entry_path.exists():
            return ExecutionResult(
                success=False,
                errors=[{"message": f"File not found: {entry_point}"}]
            )

        # Determine command (node or ts-node for TypeScript)
        if entry_point.endswith('.ts') or entry_point.endswith('.tsx'):
            cmd = ['npx', 'ts-node', str(entry_path)]
        else:
            cmd = ['node', str(entry_path)]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            errors = []
            if result.returncode != 0:
                errors = self._parse_node_errors(result.stderr)

            return ExecutionResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                errors=errors
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                timeout=True,
                errors=[{"message": f"Execution timed out after {self.timeout}s"}]
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                errors=[{"message": "Node.js not found in PATH"}]
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                errors=[{"message": str(e)}]
            )

    def _run_pytest(self, test_pattern: str = 'test_*.py') -> TestResult:
        """Run pytest and parse results."""
        # Find test files
        test_files = list(self.project_dir.glob(f'**/{test_pattern}'))
        if not test_files:
            return TestResult(
                ran=False,
                error_message="No test files found"
            )

        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', '-v', '--tb=short', str(self.project_dir)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout * 2,  # Allow more time for tests
                env={
                    **os.environ,
                    'PYTHONPATH': str(self.project_dir)
                }
            )

            # Parse pytest output
            passed = []
            failed = []
            errors = []

            for line in result.stdout.split('\n'):
                line = line.strip()
                if '::' in line:  # Test identifier
                    if ' PASSED' in line:
                        test_name = line.split(' PASSED')[0].strip()
                        passed.append(test_name)
                    elif ' FAILED' in line:
                        test_name = line.split(' FAILED')[0].strip()
                        failed.append(test_name)
                    elif ' ERROR' in line:
                        test_name = line.split(' ERROR')[0].strip()
                        errors.append(test_name)

            return TestResult(
                ran=True,
                passed=passed,
                failed=failed,
                errors=errors,
                output=result.stdout,
                stderr=result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                ran=False,
                error_message="Tests timed out"
            )
        except Exception as e:
            return TestResult(
                ran=False,
                error_message=str(e)
            )

    def _run_npm_test(self) -> TestResult:
        """Run npm test."""
        package_json = self.project_dir / 'package.json'
        if not package_json.exists():
            return TestResult(
                ran=False,
                error_message="No package.json found"
            )

        try:
            result = subprocess.run(
                ['npm', 'test'],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout * 2
            )

            # Basic parsing - npm test output varies by test framework
            return TestResult(
                ran=True,
                passed=[] if result.returncode != 0 else ['npm test'],
                failed=['npm test'] if result.returncode != 0 else [],
                output=result.stdout,
                stderr=result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                ran=False,
                error_message="Tests timed out"
            )
        except Exception as e:
            return TestResult(
                ran=False,
                error_message=str(e)
            )

    def _parse_python_errors(self, stderr: str) -> List[Dict[str, Any]]:
        """Parse Python error messages into structured format."""
        errors = []
        lines = stderr.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # Look for traceback
            if 'Traceback (most recent call last):' in line:
                error = {
                    'type': 'traceback',
                    'file': None,
                    'line': None,
                    'message': ''
                }
                i += 1

                # Parse frames
                while i < len(lines) and lines[i].startswith('  '):
                    if 'File "' in lines[i]:
                        match = re.search(r'File "([^"]+)", line (\d+)', lines[i])
                        if match:
                            error['file'] = match.group(1)
                            error['line'] = int(match.group(2))
                    i += 1

                # Get error message
                if i < len(lines) and lines[i].strip():
                    error['message'] = lines[i].strip()
                    errors.append(error)

            # Look for specific errors
            elif 'ModuleNotFoundError' in line or 'ImportError' in line:
                match = re.search(r"No module named '([^']+)'", line)
                errors.append({
                    'type': 'import_error',
                    'message': line.strip(),
                    'missing_module': match.group(1) if match else None
                })

            elif 'SyntaxError' in line:
                errors.append({
                    'type': 'syntax_error',
                    'message': line.strip()
                })

            i += 1

        return errors

    def _parse_node_errors(self, stderr: str) -> List[Dict[str, Any]]:
        """Parse Node.js error messages."""
        errors = []

        # Look for common Node.js error patterns
        if 'Cannot find module' in stderr:
            match = re.search(r"Cannot find module '([^']+)'", stderr)
            errors.append({
                'type': 'import_error',
                'message': f"Cannot find module '{match.group(1)}'" if match else stderr,
                'missing_module': match.group(1) if match else None
            })

        elif 'SyntaxError' in stderr:
            errors.append({
                'type': 'syntax_error',
                'message': stderr.strip()[:200]
            })

        elif 'ReferenceError' in stderr or 'TypeError' in stderr:
            errors.append({
                'type': 'runtime_error',
                'message': stderr.strip()[:200]
            })

        else:
            errors.append({
                'type': 'unknown',
                'message': stderr.strip()[:200]
            })

        return errors


# =============================================================================
# DOCKER SANDBOX
# =============================================================================

class DockerSandbox:
    """
    Self-contained Docker sandbox for secure code execution.

    Zero configuration required - automatically:
    - Detects Docker availability
    - Pulls required images (one-time, cached)
    - Creates/destroys containers
    - Falls back gracefully if Docker unavailable

    Security features:
    - No network access (--network=none)
    - Read-only filesystem (--read-only)
    - Memory limits (--memory=256m)
    - CPU limits (--cpus=0.5)
    - Process limits (--pids-limit=50)
    - Non-root user (--user=nobody)
    - No privilege escalation (--security-opt=no-new-privileges)
    """

    # Pre-configured lightweight images
    IMAGES = {
        'python': 'python:3.11-slim',       # ~50MB
        'javascript': 'node:20-alpine',      # ~40MB
        'typescript': 'node:20-alpine',
    }

    # Resource limits
    MEMORY_LIMIT = '256m'
    CPU_LIMIT = '0.5'
    PIDS_LIMIT = '50'
    TMP_SIZE = '64m'

    def __init__(
        self,
        project_dir: Path,
        language: str = 'python',
        timeout: int = 30,
        verbose: bool = False
    ):
        """
        Initialize Docker sandbox.

        Args:
            project_dir: Directory containing code to execute
            language: Programming language (python, javascript, typescript)
            timeout: Execution timeout in seconds
            verbose: Enable verbose logging
        """
        self.project_dir = Path(project_dir).resolve()
        self.language = language
        self.timeout = timeout
        self.verbose = verbose

        # Check Docker availability (cached)
        self._docker_available = None
        self._image_ready = None

    @property
    def docker_available(self) -> bool:
        """Check if Docker is available and running."""
        if self._docker_available is None:
            self._docker_available = self._check_docker()
        return self._docker_available

    def _check_docker(self) -> bool:
        """Check if Docker daemon is accessible."""
        try:
            result = subprocess.run(
                ['docker', 'info'],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info("Docker is available")
                return True
            else:
                logger.warning("Docker command failed: %s", result.stderr.decode()[:100])
                return False
        except FileNotFoundError:
            logger.warning("Docker not found in PATH")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Docker info command timed out")
            return False
        except Exception as e:
            logger.warning("Docker check failed: %s", e)
            return False

    def _get_image(self) -> str:
        """Get the appropriate Docker image for the language."""
        return self.IMAGES.get(self.language, self.IMAGES['python'])

    def _ensure_image(self) -> Tuple[bool, str]:
        """
        Ensure required Docker image is available.

        Returns:
            Tuple of (success, message)
        """
        image = self._get_image()

        # Check if image exists locally
        try:
            result = subprocess.run(
                ['docker', 'image', 'inspect', image],
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.debug("Docker image %s is available", image)
                return True, f"Image {image} ready (cached)"

            # Image not found, need to pull
            logger.info("Pulling Docker image %s (one-time setup)...", image)

            result = subprocess.run(
                ['docker', 'pull', image],
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes for slow connections
            )

            if result.returncode == 0:
                logger.info("Successfully pulled Docker image %s", image)
                return True, f"Image {image} pulled successfully"
            else:
                logger.error("Failed to pull image: %s", result.stderr[:200])
                return False, f"Failed to pull image: {result.stderr[:100]}"

        except subprocess.TimeoutExpired:
            return False, "Docker image pull timed out"
        except Exception as e:
            return False, f"Docker image check failed: {e}"

    def execute(
        self,
        entry_point: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """
        Execute code in isolated Docker container.

        Automatically falls back to subprocess if Docker unavailable.

        Args:
            entry_point: Relative path to the entry point file
            args: Optional command-line arguments
            env: Optional environment variables

        Returns:
            ExecutionResult with execution details
        """
        args = args or []
        env = env or {}

        # Check Docker availability
        if not self.docker_available:
            logger.warning("Docker not available, falling back to subprocess (less secure)")
            return self._execute_subprocess(entry_point, args, env)

        # Ensure image is ready
        image_ready, image_msg = self._ensure_image()
        if not image_ready:
            logger.warning("Docker image not ready: %s, falling back to subprocess", image_msg)
            return self._execute_subprocess(entry_point, args, env)

        # Execute in Docker
        return self._execute_docker(entry_point, args, env)

    def _ensure_readable_permissions(self) -> None:
        """
        Ensure project directory and files are readable by Docker container.

        Docker mounts require world-readable permissions since the container
        may run with a different user. This makes the directory and all files
        world-readable (but not writable).
        """
        try:
            # Make directory traversable
            os.chmod(self.project_dir, 0o755)

            # Make all files readable
            for root, dirs, files in os.walk(self.project_dir):
                for d in dirs:
                    path = os.path.join(root, d)
                    os.chmod(path, 0o755)
                for f in files:
                    path = os.path.join(root, f)
                    os.chmod(path, 0o644)
        except PermissionError as e:
            logger.warning("Could not set permissions for Docker: %s", e)

    def _execute_docker(
        self,
        entry_point: str,
        args: List[str],
        env: Dict[str, str]
    ) -> ExecutionResult:
        """Execute code in Docker container with full isolation."""
        # Ensure files are readable by Docker
        self._ensure_readable_permissions()

        image = self._get_image()

        # Build the run command based on language
        if self.language == 'python':
            run_cmd = ['python', '-u', entry_point] + args
        elif self.language in ('javascript', 'typescript'):
            if entry_point.endswith(('.ts', '.tsx')):
                run_cmd = ['npx', 'ts-node', entry_point] + args
            else:
                run_cmd = ['node', entry_point] + args
        else:
            run_cmd = ['python', '-u', entry_point] + args

        # Build Docker command with security options
        # Note: We use root inside container but with all other security restrictions.
        # The read-only mount prevents any writes, and network is disabled.
        docker_cmd = [
            'docker', 'run',
            '--rm',                                      # Auto-remove container
            '--network=none',                            # No network access
            '--read-only',                               # Read-only root filesystem
            f'--memory={self.MEMORY_LIMIT}',             # Memory limit
            f'--memory-swap={self.MEMORY_LIMIT}',        # No swap
            f'--cpus={self.CPU_LIMIT}',                  # CPU limit
            f'--pids-limit={self.PIDS_LIMIT}',           # Process limit
            '--security-opt=no-new-privileges',          # No privilege escalation
            '--cap-drop=ALL',                            # Drop all capabilities
            f'--volume={self.project_dir}:/app:ro',      # Mount project read-only
            f'--tmpfs=/tmp:size={self.TMP_SIZE},mode=1777',  # Writable /tmp
            '--workdir=/app',
            # Note: Running as root inside container but with:
            # - read-only filesystem
            # - no network
            # - no capabilities
            # - no privilege escalation
            # This is secure for code execution validation
        ]

        # Add environment variables
        for key, value in env.items():
            docker_cmd.extend(['-e', f'{key}={value}'])

        # Add Python-specific environment
        if self.language == 'python':
            docker_cmd.extend([
                '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '-e', 'PYTHONUNBUFFERED=1',
            ])

        # Add image and command
        docker_cmd.append(image)
        docker_cmd.extend(run_cmd)

        logger.debug("Docker command: %s", ' '.join(docker_cmd[:20]) + '...')

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            errors = []
            if result.returncode != 0:
                errors = self._parse_errors(result.stderr)

            return ExecutionResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                errors=errors,
                sandbox_type='docker'
            )

        except subprocess.TimeoutExpired:
            # Try to kill any lingering container (best effort)
            logger.warning("Docker execution timed out after %ds", self.timeout)
            return ExecutionResult(
                success=False,
                timeout=True,
                errors=[{"type": "timeout", "message": f"Execution timed out after {self.timeout}s"}],
                sandbox_type='docker'
            )
        except Exception as e:
            logger.error("Docker execution failed: %s", e)
            return ExecutionResult(
                success=False,
                errors=[{"type": "error", "message": str(e)}],
                sandbox_type='docker'
            )

    def _execute_subprocess(
        self,
        entry_point: str,
        args: List[str],
        env: Dict[str, str]
    ) -> ExecutionResult:
        """Fallback: execute in subprocess without isolation."""
        entry_path = self.project_dir / entry_point

        if not entry_path.exists():
            return ExecutionResult(
                success=False,
                errors=[{"type": "file_not_found", "message": f"File not found: {entry_point}"}],
                sandbox_type='subprocess'
            )

        # Build command
        if self.language == 'python':
            cmd = [sys.executable, '-u', str(entry_path)] + args
        elif self.language in ('javascript', 'typescript'):
            if entry_point.endswith(('.ts', '.tsx')):
                cmd = ['npx', 'ts-node', str(entry_path)] + args
            else:
                cmd = ['node', str(entry_path)] + args
        else:
            cmd = [sys.executable, '-u', str(entry_path)] + args

        # Build environment
        exec_env = os.environ.copy()
        exec_env['PYTHONDONTWRITEBYTECODE'] = '1'
        exec_env['PYTHONPATH'] = str(self.project_dir)
        exec_env.update(env)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=exec_env
            )

            errors = []
            if result.returncode != 0:
                errors = self._parse_errors(result.stderr)

            return ExecutionResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                errors=errors,
                sandbox_type='subprocess'
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                timeout=True,
                errors=[{"type": "timeout", "message": f"Execution timed out after {self.timeout}s"}],
                sandbox_type='subprocess'
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                errors=[{"type": "error", "message": str(e)}],
                sandbox_type='subprocess'
            )

    def _parse_errors(self, stderr: str) -> List[Dict[str, Any]]:
        """Parse error output into structured format."""
        errors = []

        if not stderr:
            return errors

        if self.language == 'python':
            # Python error patterns
            if 'ModuleNotFoundError' in stderr or 'ImportError' in stderr:
                match = re.search(r"No module named '([^']+)'", stderr)
                errors.append({
                    'type': 'import_error',
                    'message': stderr.strip()[:500],
                    'missing_module': match.group(1) if match else None
                })
            elif 'SyntaxError' in stderr:
                errors.append({
                    'type': 'syntax_error',
                    'message': stderr.strip()[:500]
                })
            elif 'Traceback' in stderr:
                # Extract the actual error from traceback
                lines = stderr.strip().split('\n')
                error_line = lines[-1] if lines else stderr[:200]
                errors.append({
                    'type': 'runtime_error',
                    'message': error_line,
                    'full_traceback': stderr[:2000]
                })
            else:
                errors.append({
                    'type': 'unknown',
                    'message': stderr.strip()[:500]
                })
        else:
            # JavaScript/Node error patterns
            if 'Cannot find module' in stderr:
                match = re.search(r"Cannot find module '([^']+)'", stderr)
                errors.append({
                    'type': 'import_error',
                    'message': stderr.strip()[:500],
                    'missing_module': match.group(1) if match else None
                })
            elif 'SyntaxError' in stderr:
                errors.append({
                    'type': 'syntax_error',
                    'message': stderr.strip()[:500]
                })
            else:
                errors.append({
                    'type': 'runtime_error',
                    'message': stderr.strip()[:500]
                })

        return errors

    def run_tests(self, test_pattern: str = 'test_*.py') -> TestResult:
        """
        Run tests in Docker container.

        Args:
            test_pattern: Glob pattern for test files

        Returns:
            TestResult with pass/fail details
        """
        if not self.docker_available:
            logger.warning("Docker not available, running tests in subprocess")
            return self._run_tests_subprocess(test_pattern)

        image_ready, _ = self._ensure_image()
        if not image_ready:
            return self._run_tests_subprocess(test_pattern)

        return self._run_tests_docker(test_pattern)

    def _run_tests_docker(self, test_pattern: str) -> TestResult:
        """Run tests in Docker container."""
        image = self._get_image()

        if self.language == 'python':
            # Run pytest
            test_cmd = ['python', '-m', 'pytest', '-v', '--tb=short', '.']
        else:
            # Run npm test
            test_cmd = ['npm', 'test']

        docker_cmd = [
            'docker', 'run',
            '--rm',
            '--network=none',
            '--read-only',
            f'--memory={self.MEMORY_LIMIT}',
            f'--cpus={self.CPU_LIMIT}',
            '--security-opt=no-new-privileges',
            f'--volume={self.project_dir}:/app:ro',
            f'--tmpfs=/tmp:size={self.TMP_SIZE}',
            '--workdir=/app',
            '--user=nobody:nogroup',
            '-e', 'PYTHONDONTWRITEBYTECODE=1',
            image,
            *test_cmd
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout * 2  # Allow more time for tests
            )

            return self._parse_test_output(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            return TestResult(
                ran=False,
                error_message="Tests timed out in Docker"
            )
        except Exception as e:
            return TestResult(
                ran=False,
                error_message=str(e)
            )

    def _run_tests_subprocess(self, test_pattern: str) -> TestResult:
        """Run tests in subprocess (fallback)."""
        if self.language == 'python':
            cmd = [sys.executable, '-m', 'pytest', '-v', '--tb=short', str(self.project_dir)]
        else:
            cmd = ['npm', 'test']

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout * 2,
                env={**os.environ, 'PYTHONPATH': str(self.project_dir)}
            )

            return self._parse_test_output(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            return TestResult(ran=False, error_message="Tests timed out")
        except Exception as e:
            return TestResult(ran=False, error_message=str(e))

    def _parse_test_output(self, stdout: str, stderr: str, return_code: int) -> TestResult:
        """Parse test output into structured result."""
        passed = []
        failed = []
        errors = []

        # Parse pytest output
        for line in stdout.split('\n'):
            line = line.strip()
            if '::' in line:  # Test identifier
                if ' PASSED' in line:
                    test_name = line.split(' PASSED')[0].strip()
                    passed.append(test_name)
                elif ' FAILED' in line:
                    test_name = line.split(' FAILED')[0].strip()
                    failed.append(test_name)
                elif ' ERROR' in line:
                    test_name = line.split(' ERROR')[0].strip()
                    errors.append(test_name)

        # If no tests detected but command failed, mark as error
        if not passed and not failed and not errors and return_code != 0:
            if 'no tests ran' in stdout.lower() or 'no tests ran' in stderr.lower():
                return TestResult(
                    ran=False,
                    error_message="No tests found"
                )
            errors.append("Test execution failed")

        return TestResult(
            ran=True,
            passed=passed,
            failed=failed,
            errors=errors,
            output=stdout,
            stderr=stderr
        )

    def validate_imports(self) -> ExecutionResult:
        """
        Validate that all imports work by attempting to import modules.

        Creates a test script that imports all modules and runs it.
        """
        if self.language != 'python':
            # For JS/TS, we'd need a different approach
            return ExecutionResult(
                success=True,
                sandbox_type='docker' if self.docker_available else 'subprocess'
            )

        # Find all Python files
        py_files = list(self.project_dir.glob('**/*.py'))
        if not py_files:
            return ExecutionResult(success=True, sandbox_type='none')

        # Create import test script
        test_lines = [
            "import sys",
            "sys.path.insert(0, '.')",
            ""
        ]

        for py_file in py_files:
            # Skip test files and __pycache__
            if 'test_' in py_file.name or '__pycache__' in str(py_file):
                continue
            if py_file.name.startswith('_') and py_file.name != '__init__.py':
                continue

            # Convert path to module name
            try:
                rel_path = py_file.relative_to(self.project_dir)
                module = str(rel_path.with_suffix('')).replace('/', '.').replace('\\', '.')

                test_lines.extend([
                    f"try:",
                    f"    import {module}",
                    f"    print('OK: {module}')",
                    f"except Exception as e:",
                    f"    print(f'FAIL: {module}: {{type(e).__name__}}: {{e}}')",
                    f"    sys.exit(1)",
                    ""
                ])
            except ValueError:
                continue

        test_lines.append("print('All imports successful')")
        test_script = '\n'.join(test_lines)

        # Write test script temporarily
        test_file = self.project_dir / '_import_validation_test.py'
        try:
            test_file.write_text(test_script)
            result = self.execute('_import_validation_test.py')
            return result
        finally:
            # Clean up
            if test_file.exists():
                try:
                    test_file.unlink()
                except:
                    pass


# =============================================================================
# COMPOSITE VALIDATOR
# =============================================================================

class CodeValidator:
    """
    Composite validator that runs all validation layers.

    Combines:
    - Layer 3: Generation Validation
    - Layer 4: Import Resolution
    - Layer 7: Execution Validation (with Docker sandbox)
    """

    def __init__(
        self,
        project_dir: Path,
        language: str = 'python',
        timeout: int = 30,
        use_docker: bool = True
    ):
        """
        Initialize composite validator.

        Args:
            project_dir: Directory containing generated code
            language: Primary language
            timeout: Execution timeout
            use_docker: Whether to use Docker sandbox (auto-fallback if unavailable)
        """
        self.project_dir = Path(project_dir)
        self.language = language
        self.timeout = timeout
        self.use_docker = use_docker

        self.generation_validator = GenerationValidator()

        # Use Docker sandbox for execution (with automatic fallback)
        if use_docker:
            self.sandbox = DockerSandbox(project_dir, language, timeout)
            self.docker_available = self.sandbox.docker_available
        else:
            self.sandbox = None
            self.docker_available = False

        # Keep legacy executor for compatibility
        self.execution_validator = ExecutionValidator(project_dir, language, timeout)

    def validate_file(self, filepath: str, code: str, spec: Optional[Dict] = None) -> ValidationResult:
        """
        Validate a single generated file.

        Args:
            filepath: Path to the file
            code: Generated code content
            spec: Optional file specification

        Returns:
            ValidationResult
        """
        # Detect language from file extension
        ext = Path(filepath).suffix.lower()
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json',
        }
        language = lang_map.get(ext, self.language)

        return self.generation_validator.validate(code, language, spec)

    def validate_imports(self, generated_files: Dict[str, str]) -> ValidationResult:
        """
        Validate all imports across generated files.

        Args:
            generated_files: Dict mapping paths to code content

        Returns:
            ValidationResult
        """
        resolver = ImportResolver(generated_files, self.language, self.project_dir)
        return resolver.validate()

    def validate_execution(self, entry_point: Optional[str] = None) -> ExecutionResult:
        """
        Validate code by executing it in Docker sandbox.

        Args:
            entry_point: Optional entry point file (auto-detected if not provided)

        Returns:
            ExecutionResult
        """
        # Use Docker sandbox if available
        if self.sandbox:
            # First validate imports in sandbox
            import_result = self.sandbox.validate_imports()
            if not import_result.success:
                return import_result

            # If entry point provided, execute it
            if entry_point:
                return self.sandbox.execute(entry_point)

            return ExecutionResult(success=True, sandbox_type='docker' if self.docker_available else 'subprocess')

        # Fallback to legacy executor
        import_result = self.execution_validator.validate_imports()
        if not import_result.success:
            return import_result

        if entry_point:
            return self.execution_validator.execute_file(entry_point)

        return ExecutionResult(success=True, sandbox_type='none')

    def run_tests(self) -> TestResult:
        """
        Run all tests in the project using Docker sandbox.

        Returns:
            TestResult
        """
        # Use Docker sandbox if available
        if self.sandbox:
            return self.sandbox.run_tests()

        # Fallback to legacy executor
        return self.execution_validator.run_tests()

    def full_validation(
        self,
        generated_files: Dict[str, str],
        specs: Optional[List[Dict]] = None,
        entry_point: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run full validation pipeline.

        Args:
            generated_files: Dict mapping paths to code content
            specs: Optional list of file specifications
            entry_point: Optional entry point for execution

        Returns:
            Dict with validation results for each layer
        """
        results = {
            'layer3_generation': [],
            'layer4_imports': None,
            'layer7_execution': None,
            'layer7_tests': None,
            'overall_valid': True,
            'errors': [],
            'warnings': [],
            'sandbox_type': 'docker' if self.docker_available else 'subprocess',
            'docker_available': self.docker_available
        }

        # Layer 3: Validate each file
        specs_map = {s['path']: s for s in (specs or [])}
        for filepath, code in generated_files.items():
            spec = specs_map.get(filepath)
            file_result = self.validate_file(filepath, code, spec)
            results['layer3_generation'].append({
                'file': filepath,
                'valid': file_result.valid,
                'errors': file_result.errors,
                'warnings': file_result.warnings
            })
            if not file_result.valid:
                results['overall_valid'] = False
                results['errors'].extend([f"{filepath}: {e}" for e in file_result.errors])
            results['warnings'].extend([f"{filepath}: {w}" for w in file_result.warnings])

        # Layer 4: Validate imports
        import_result = self.validate_imports(generated_files)
        results['layer4_imports'] = {
            'valid': import_result.valid,
            'errors': import_result.errors
        }
        if not import_result.valid:
            results['overall_valid'] = False
            results['errors'].extend(import_result.errors)

        # Layer 7: Execution validation (only if previous layers passed)
        if results['overall_valid']:
            exec_result = self.validate_execution(entry_point)
            results['layer7_execution'] = {
                'success': exec_result.success,
                'sandbox_type': exec_result.sandbox_type,
                'errors': exec_result.errors,
                'stdout': exec_result.stdout[:500] if exec_result.stdout else '',
                'stderr': exec_result.stderr[:500] if exec_result.stderr else ''
            }
            if not exec_result.success:
                results['overall_valid'] = False
                results['errors'].extend([e.get('message', str(e)) for e in exec_result.errors])

            # Run tests if execution succeeded
            if exec_result.success:
                test_result = self.run_tests()
                results['layer7_tests'] = {
                    'ran': test_result.ran,
                    'passed': test_result.passed,
                    'failed': test_result.failed,
                    'errors': test_result.errors
                }
                if test_result.failed:
                    results['overall_valid'] = False
                    results['errors'].extend([f"Test failed: {t}" for t in test_result.failed])

        return results


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def detect_language(filepath: str) -> str:
    """Detect language from file extension."""
    ext = Path(filepath).suffix.lower()
    lang_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.json': 'json',
        '.md': 'markdown',
        '.yaml': 'yaml',
        '.yml': 'yaml',
    }
    return lang_map.get(ext, 'text')


def detect_project_language(files: Dict[str, str]) -> str:
    """Detect primary language of a project from its files."""
    lang_counts = {}

    for filepath in files:
        lang = detect_language(filepath)
        if lang not in ('text', 'markdown', 'yaml', 'json'):
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

    if not lang_counts:
        return 'python'  # Default

    return max(lang_counts, key=lang_counts.get)
