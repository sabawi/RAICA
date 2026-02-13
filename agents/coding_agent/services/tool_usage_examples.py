"""
Tool Usage Examples for RAICA Coding Agent.

This module provides few-shot examples to guide the LLM in using tools correctly,
especially the new debug tools introduced in Phase 2.2.
"""

TOOL_USAGE_EXAMPLES = """
CRITICAL: YOUR RESPONSE MUST BE VALID JSON MATCHING THESE EXAMPLES.
DO NOT ADD ANY TEXT BEFORE OR AFTER THE JSON. NO "We'll do X" OR "Let me Y" PHRASES.

EXAMPLES OF CORRECT TOOL USAGE (COPY THIS FORMAT EXACTLY):

1. READ BEFORE EDIT (CRITICAL PATTERN)
Task: "Fix the typo on line 42 of main.py."
JSON (STEP 1 - Read first):
{
  "tool_calls": [
    {"tool": "read_file", "args": {"path": "main.py"}}
  ]
}
JSON (STEP 2 - After reading, edit with exact content):
{
  "tool_calls": [
    {"tool": "replace_line", "args": {"path": "main.py", "line_number": 42, "new_content": "corrected_line_content"}}
  ]
}

2. DEPENDENCY CHECK & INSTALL
Task: "Check why requests import is failing and fix it."
JSON:
{
  "tool_calls": [
    {"tool": "dependency_check", "args": {}},
    {"tool": "pip_install", "args": {"packages": ["requests"]}}
  ]
}

3. SEARCH THEN EDIT
Task: "Find where MAX_RETRIES is defined and change it to 5."
JSON (STEP 1 - Search first):
{
  "tool_calls": [
    {"tool": "grep_search", "args": {"pattern": "MAX_RETRIES", "scope": "*.py"}}
  ]
}
JSON (STEP 2 - After finding location):
{
  "tool_calls": [
    {"tool": "read_file", "args": {"path": "config.py"}},
    {"tool": "replace_line", "args": {"path": "config.py", "line_number": 8, "new_content": "MAX_RETRIES = 5"}}
  ]
}

4. LINTING & FIXING
Task: "Fix lint errors in main.py."
JSON:
{
  "tool_calls": [
    {"tool": "check_lint", "args": {"path": "main.py"}},
    {"tool": "format_file", "args": {"path": "main.py"}}
  ]
}

5. CREATING & RUNNING TESTS
Task: "Create a test for utils.py and run it."
JSON:
{
  "tool_calls": [
    {"tool": "create_test", "args": {"target_file": "utils.py"}},
    {"tool": "run_tests", "args": {"path": "tests/test_utils.py"}}
  ]
}

6. VERSION CONTROL & RESTORE
Task: "I messed up config.py, restore the last backup."
JSON:
{
  "tool_calls": [
    {"tool": "get_backups", "args": {}},
    {"tool": "restore_backup", "args": {"backup_name": "config.py.20230101_120000"}}
  ]
}

7. MULTI-FILE DIAGNOSIS
Task: "The app crashes on startup, find the cause."
JSON (STEP 1 - Gather context):
{
  "tool_calls": [
    {"tool": "analyze_project", "args": {}},
    {"tool": "read_file", "args": {"path": "main.py"}},
    {"tool": "dependency_check", "args": {}}
  ]
}

8. ERROR RECOVERY EXAMPLE
Task: "Edit line 50 of app.py" (but file has only 30 lines)
Tool returns: "Error: Line 50 does not exist, file has 30 lines"
JSON (Recovery - read file to understand structure):
{
  "tool_calls": [
    {"tool": "read_file", "args": {"path": "app.py"}}
  ]
}

9. FETCH REMOTE DOCUMENTATION
Task: "Read the grep manual to understand the -P flag."
JSON:
{
  "tool_calls": [
    {"tool": "fetch_manpage", "args": {"command": "grep"}}
  ]
}

10. FETCH WEB PAGE / API DOCS
Task: "Check the requests library documentation for session handling."
JSON:
{
  "tool_calls": [
    {"tool": "fetch_url", "args": {"url": "https://requests.readthedocs.io/en/latest/user/advanced/#session-objects"}}
  ]
}

11. FETCH SPECIFIC DOCUMENTATION
Task: "Get the numpy array documentation."
JSON:
{
  "tool_calls": [
    {"tool": "fetch_documentation", "args": {"url": "https://numpy.org/doc/stable/reference/generated/numpy.array.html"}}
  ]
}

12. RAICA SERVER - WEB SEARCH (if available)
Task: "Find the latest news about Python 3.12 features."
JSON:
{
  "tool_calls": [
    {"tool": "raica_search_web", "args": {"query": "Python 3.12 new features", "max_results": 5}}
  ]
}

13. RAICA SERVER - API DOCUMENTATION LOOKUP (if available)
Task: "Look up how to use the requests library for sessions."
JSON:
{
  "tool_calls": [
    {"tool": "raica_lookup_api", "args": {"api_name": "requests", "topic": "sessions"}}
  ]
}

14. RAICA SERVER - PATTERN SEARCH (if available)
Task: "Find best practices for implementing async/await in Python."
JSON:
{
  "tool_calls": [
    {"tool": "raica_search_patterns", "args": {"requirements": ["async/await", "error handling", "concurrency"], "language": "python"}}
  ]
}

15. WRITE ENTIRE FILE (for major rewrites or new files)
Task: "The HTML file is missing structure, rewrite it completely."
JSON:
{
  "tool_calls": [
    {"tool": "write_file", "args": {"path": "index.html", "content": "<!DOCTYPE html>\\n<html>\\n<head>...</head>\\n<body>...</body>\\n</html>"}}
  ]
}

16. EDIT FILE WITH SEARCH/REPLACE (for targeted changes)
Task: "Change the background color from red to blue in style.css."
JSON:
{
  "tool_calls": [
    {"tool": "edit_file", "args": {"path": "style.css", "search": "background: red;", "replace": "background: blue;"}}
  ]
}

IMPORTANT RULES:
- ALWAYS read a file before editing it
- ALWAYS search for a pattern before doing bulk replacements
- Use write_file for complete rewrites, edit_file for targeted changes
- If a tool fails, analyze the error and adjust your approach
- Do NOT repeat the same failing call - try a different strategy
- RAICA server tools (raica_*) may not be available - check error messages
- If RAICA server is unavailable, use fetch_url or fetch_documentation instead

RESPONSE FORMAT REMINDER:
Your response MUST be ONLY this JSON structure:
{"tool_calls": [{"tool": "...", "args": {...}}]}
OR
{"done": true}

NO OTHER TEXT ALLOWED.
"""
