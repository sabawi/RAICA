"""
requirements_validator.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Utility to validate and fix requirements.txt files that LLMs may generate
incorrectly as PRD documents instead of pip-installable package lists.
"""

import re
from typing import Tuple, List


# Pattern for valid pip package specifications
# Matches: package, package>=1.0, package==1.0.0, package[extra]>=1.0, etc.
PACKAGE_PATTERN = re.compile(
    r'^[a-zA-Z0-9][a-zA-Z0-9._-]*'  # Package name
    r'(?:\[[a-zA-Z0-9,_-]+\])?'     # Optional extras [extra1,extra2]
    r'(?:[<>=!~]+[a-zA-Z0-9.*]+)?'  # Optional version specifier
    r'$'
)

# Patterns that indicate a document rather than requirements
DOCUMENT_PATTERNS = [
    r'^##\s',           # Markdown headers
    r'^###\s',
    r'^\*\s',           # Bullet points
    r'^-\s+\w+\s+\w+',  # Bullet with sentence (not just package)
    r'^\d+\.\s',        # Numbered lists
    r'^\*\*',           # Bold markdown
    r'^\|',             # Tables
]


def is_valid_package_line(line: str) -> bool:
    """Check if a line is a valid pip package specification."""
    line = line.strip()
    
    # Empty lines and comments are valid
    if not line or line.startswith('#'):
        return True
    
    # Check against package pattern
    return bool(PACKAGE_PATTERN.match(line))


def is_document_format(content: str) -> bool:
    """Detect if content looks like a document rather than requirements."""
    lines = content.split('\n')
    
    document_indicators = 0
    package_lines = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check for document patterns
        for pattern in DOCUMENT_PATTERNS:
            if re.match(pattern, line):
                document_indicators += 1
                break
        
        # Check for package patterns
        if PACKAGE_PATTERN.match(line):
            package_lines += 1
    
    # If more document indicators than packages, it's probably a document
    return document_indicators > package_lines


def extract_packages_from_document(content: str) -> List[str]:
    """Extract valid package specifications from a document-style requirements."""
    packages = []
    
    # First, try to find packages in the format: package>=version
    for match in re.finditer(r'([a-zA-Z0-9][a-zA-Z0-9._-]*(?:\[[a-zA-Z0-9,_-]+\])?[<>=]+[a-zA-Z0-9.*]+)', content):
        pkg = match.group(1).strip()
        if pkg not in packages:
            packages.append(pkg)
    
    # Also try to find bare package names on their own lines
    for line in content.split('\n'):
        line = line.strip()
        # Skip obvious prose
        if ' ' in line and not line.startswith('#'):
            continue
        if PACKAGE_PATTERN.match(line) and line not in packages:
            packages.append(line)
    
    return packages


def validate_requirements(content: str) -> Tuple[bool, str]:
    """
    Validate requirements.txt content and fix if needed.
    
    Args:
        content: The content of requirements.txt
        
    Returns:
        Tuple of (is_valid, fixed_or_original_content)
        - If valid: (True, original_content)
        - If invalid but fixable: (False, fixed_content)
        - If invalid and unfixable: (False, error_message)
    """
    if not content or not content.strip():
        return (False, "# Empty requirements file\n")
    
    # Check if it's a document
    if is_document_format(content):
        packages = extract_packages_from_document(content)
        if packages:
            fixed = "# Auto-extracted from document\n" + '\n'.join(packages) + '\n'
            return (False, fixed)
        return (False, "# Error: Could not extract packages from document\n")
    
    # Validate each line
    lines = content.split('\n')
    valid_lines = []
    has_error = False
    
    for line in lines:
        if is_valid_package_line(line):
            valid_lines.append(line)
        else:
            # Try to salvage the line
            has_error = True
            # Remove markdown formatting
            cleaned = re.sub(r'[\*_`]', '', line).strip()
            if is_valid_package_line(cleaned):
                valid_lines.append(cleaned)
    
    if has_error:
        return (False, '\n'.join(valid_lines))
    
    return (True, content)


def generate_requirements_from_imports(py_files_content: List[str]) -> str:
    """
    Generate requirements.txt from Python import statements.
    
    Args:
        py_files_content: List of Python file contents
        
    Returns:
        Generated requirements.txt content
    """
    # Common stdlib modules to exclude
    STDLIB = {
        'os', 'sys', 're', 'json', 'logging', 'pathlib', 'typing', 'collections',
        'datetime', 'time', 'math', 'random', 'itertools', 'functools', 'copy',
        'subprocess', 'threading', 'multiprocessing', 'asyncio', 'io', 'string',
        'hashlib', 'base64', 'pickle', 'sqlite3', 'csv', 'configparser', 'argparse',
        'unittest', 'dataclasses', 'abc', 'contextlib', 'traceback', 'warnings',
        'tempfile', 'shutil', 'glob', 'fnmatch', 'stat', 'platform', 'socket',
        'http', 'urllib', 'email', 'html', 'xml', 'enum', 'weakref', 'types',
        'inspect', 'dis', 'codecs', 'locale', 'textwrap', 'difflib', 'struct',
        'operator', 'array', 'heapq', 'bisect', 'queue', 'pprint', 'reprlib',
        '__future__',
    }
    
    # Mapping of import names to pip package names
    IMPORT_TO_PACKAGE = {
        'PIL': 'Pillow',
        'cv2': 'opencv-python',
        'sklearn': 'scikit-learn',
        'yaml': 'PyYAML',
        'bs4': 'beautifulsoup4',
        'dotenv': 'python-dotenv',
        'gi': 'PyGObject',
        'cairo': 'pycairo',
        'Xlib': 'python-xlib',
    }
    
    imports = set()
    import_pattern = re.compile(r'^(?:from|import)\s+([a-zA-Z0-9_]+)')
    
    for content in py_files_content:
        for line in content.split('\n'):
            match = import_pattern.match(line.strip())
            if match:
                module = match.group(1)
                if module not in STDLIB:
                    # Map to correct package name if needed
                    package = IMPORT_TO_PACKAGE.get(module, module)
                    imports.add(package)
    
    if not imports:
        return "# No third-party dependencies detected\n"
    
    return '\n'.join(sorted(imports)) + '\n'
