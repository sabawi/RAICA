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
DEFAULT_LINT_COMMANDS = {
    'python': ['python', '-m', 'flake8', '--max-line-length=120'],
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

