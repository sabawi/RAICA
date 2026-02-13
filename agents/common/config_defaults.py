"""
Configuration defaults for RAICA agents.
"""

# Default commands for running tests based on language
DEFAULT_TEST_COMMANDS = {
    'python': ['python', '-m', 'pytest', '-v', '--tb=short', '.'],
    'javascript': ['npm', 'test'],
    'typescript': ['npm', 'test'],
    'go': ['go', 'test', './...'],
    'rust': ['cargo', 'test'],
}

# Default commands for linting based on language
# Python: Exclude venv directories, only check for REAL errors that break code:
#   E9: Runtime errors (syntax errors, etc.)
#   F: PyFlakes errors (undefined names, unused imports that cause issues)
# Ignores style issues like blank lines (E3xx), whitespace (E2xx), etc.
DEFAULT_LINT_COMMANDS = {
    'python': [
        'python', '-m', 'flake8',
        '--max-line-length=120',
        '--exclude=venv,.venv,__pycache__,.git,build,dist,*.egg-info',
        '--select=E9,F',  # Only syntax errors (E9) and PyFlakes (F)
    ],
    'javascript': ['npx', 'eslint', '.'],
    'typescript': ['npx', 'eslint', '.'],
}

# Common stop words for semantic naming
SEMANTIC_NAMING_STOP_WORDS = {
    'create', 'a', 'an', 'the', 'make', 'build', 'write', 
    'project', 'for', 'with', 'in', 'and', 'to', 'of'
}

# Languages supported for preview in TUI
PREVIEW_LANGUAGES = {'python', 'html', 'css', 'js', 'json', 'yaml', 'md'}

# Keywords that indicate user wants to launch the project
LAUNCH_KEYWORDS = {
    'run', 'launch', 'open', 'execute', 'start', 'display',
    'show', 'preview', 'view', 'test it', 'try it', 'see it',
    'in browser', 'in the browser', 'open it', 'run it'
}

