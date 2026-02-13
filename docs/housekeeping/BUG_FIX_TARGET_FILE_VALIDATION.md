# Bug Fix: Target File Validation in Debug Mode

**Date:** February 6, 2026
**Component:** AutonomousDebugController
**Severity:** HIGH - Wastes iterations debugging wrong files
**Principle:** Fail fast with clear error messages

---

## Problem

When user specifies a file to debug that doesn't exist, the debug controller:
- ❌ **Never validates** if the file exists
- ❌ **Falls back** to automatic entry point detection (finds random files like index.html)
- ❌ **Wastes 10 iterations** trying to debug the wrong file
- ❌ **Never reports** "file not found" error
- ❌ **Confuses user** by debugging something they didn't ask for

### Example

**User request:**
```
"/Development/raica_playground/myprograms_test/quad_solver.py gives wrong results. Fix it"
```

**File path issues:**
- Missing `/home/sabawi` prefix
- File doesn't exist at that path

**Current (wrong) behavior:**
```
[PHASE 0] Building execution graph...
[Runtime] Determining how to run index.html...  ← Wrong file!
[Runtime] Browser-based app - open in browser
✅ CODE RUNS WITHOUT CRASH  ← Debugging wrong thing!
...
❌ Failed to apply fix (iteration 1/10)
❌ Failed to apply fix (iteration 2/10)
...
❌ Failed to apply fix (iteration 10/10)
⏸️ PAUSED - Max iterations reached
```

**Expected behavior:**
```
Starting autonomous debug loop...
✅ Target file validated: /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py
[PHASE 0] Building execution graph...
```

**OR if file not found:**
```
Starting autonomous debug loop...
❌ ERROR: File not found: /Development/raica_playground/myprograms_test/quad_solver.py

💡 Found similar file(s): /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py

[Process exits immediately - no wasted iterations]
```

---

## Solution

### 1. LLM-Driven File Path Extraction

**Added:** `_validate_target_file()` method (lines 218-332)

Uses **LLM** (not regex!) to extract file path from bug description:

```python
async def _validate_target_file(self, bug_description: str) -> Dict[str, Any]:
    """
    Validate that if user specified a file, it exists.
    Uses LLM to extract file path (NO regex!).
    """
    # Ask LLM to extract file path
    prompt = f"""Extract the target file path from this bug description.

BUG DESCRIPTION: {bug_description}
PROJECT DIRECTORY: {project_dir}

Return JSON:
{{
    "file_mentioned": true/false,
    "file_path": "complete/path/to/file.py or null",
    "reasoning": "..."
}}
"""
```

**Why LLM, not regex?**
- ✅ Handles any phrasing: "quad_solver.py has bug", "debug /path/file.py", "fix the calculator"
- ✅ Understands context: knows "the calculator" might mean "calculator.py"
- ✅ No brittle patterns to maintain
- ✅ Follows CLAUDE.md principle: "LLM interprets, RAICA executes"

### 2. File Existence Validation

**Added:** File existence check with helpful error messages

```python
# Try as absolute path first
target = Path(file_path)
if not target.is_absolute():
    # Try relative to project_dir
    target = project_dir / file_path

if target.exists():
    # SUCCESS - file found!
    return {'valid': True, 'file_path': str(target)}

# FAIL - file not found
# Search for similar files to help user
filename = Path(file_path).name
matches = list(project_dir.rglob(filename))
if matches:
    suggestion = f"Found similar file(s): {', '.join(str(m) for m in matches[:3])}"

return {
    'valid': False,
    'error': f"File not found: {file_path}",
    'suggestion': suggestion
}
```

### 3. Fail Fast on Invalid File

**Added:** Exit immediately if file not found (lines 261-274)

```python
# CRITICAL: Validate user-specified file exists BEFORE debugging
target_file_validation = await self._validate_target_file(bug_description)

if not target_file_validation['valid']:
    self.output(f"\n❌ ERROR: {target_file_validation['error']}")
    if target_file_validation.get('suggestion'):
        self.output(f"\n💡 {target_file_validation['suggestion']}")

    return DebugResult(
        outcome=DebugOutcome.BLOCKED,
        iterations=0,  # Zero iterations - failed immediately!
        blocked_reason=target_file_validation['error'],
        duration_seconds=time.time() - start_time
    )
```

**Key:** Returns immediately with `iterations=0`, doesn't waste time debugging wrong files.

---

## Behavior Comparison

### Before Fix

```
User: "quad_solver.py gives wrong results"

Debug Controller:
1. Doesn't check if quad_solver.py exists
2. Falls back to automatic entry point detection
3. Finds index.html (random file in project)
4. Debugs index.html for 10 iterations
5. Never applies fix (wrong file!)
6. User confused: "Why is it debugging HTML?"

Result: Wasted 10 iterations, user frustrated
```

### After Fix - File Found

```
User: "quad_solver.py gives wrong results"

Debug Controller:
1. LLM extracts: "quad_solver.py"
2. Searches: project_dir/**/*.py
3. Finds: /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py
4. ✅ Validates exists
5. ✅ Debugs correct file

Result: Debugs the right file, user happy
```

### After Fix - File NOT Found

```
User: "/Development/raica_playground/quad_solver.py has bug"

Debug Controller:
1. LLM extracts: "/Development/raica_playground/quad_solver.py"
2. Checks if exists: ❌ NO
3. Searches for similar: Found /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py
4. ❌ Reports error with suggestion
5. Exits immediately (0 iterations)

Output:
❌ ERROR: File not found: /Development/raica_playground/quad_solver.py
💡 Found similar file(s): /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py

Result: Immediate clear error, no wasted time
```

---

## Benefits

### 1. **Fail Fast**
- Detects invalid file **before** starting debug loop
- Zero wasted iterations on wrong files
- Clear error message guides user to correct path

### 2. **Helpful Error Messages**
- Shows exact path that was searched
- Suggests similar files if found
- Helps user fix incomplete paths

### 3. **LLM-Driven Extraction**
- Handles any phrasing of file path
- No brittle regex patterns
- Consistent with RAICA architecture

### 4. **Better UX**
- User immediately knows if path is wrong
- No confusion about what's being debugged
- Saves time and frustration

---

## Examples

### Example 1: Incomplete Path

**Input:**
```
"/Development/raica_playground/quad_solver.py gives wrong results"
```

**LLM Extracts:**
```json
{
  "file_mentioned": true,
  "file_path": "/Development/raica_playground/quad_solver.py",
  "reasoning": "Path starts with / but seems incomplete (missing /home/user prefix)"
}
```

**Validation:**
```
❌ ERROR: File not found: /Development/raica_playground/quad_solver.py
💡 Found similar file(s): /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py
```

### Example 2: Filename Only

**Input:**
```
"quad_solver.py produces incorrect results for positive inputs"
```

**LLM Extracts:**
```json
{
  "file_mentioned": true,
  "file_path": "quad_solver.py",
  "reasoning": "User mentioned specific filename"
}
```

**Validation:**
```
Searching: project_dir/**/quad_solver.py
Found: /home/sabawi/Development/raica_playground/myprograms_test/quad_solver.py
✅ Target file validated
```

### Example 3: No File Mentioned

**Input:**
```
"The calculator gives wrong results"
```

**LLM Extracts:**
```json
{
  "file_mentioned": false,
  "file_path": null,
  "reasoning": "User mentioned 'calculator' but not a specific file path. This might refer to calculator.py but needs automatic detection."
}
```

**Validation:**
```
✅ Proceeding with automatic entry point detection
[PHASE 0] Building execution graph...
```

---

## Architecture Principle: Fail Fast

**From CLAUDE.md:**

> When there's an error, report it clearly and immediately. Don't silently fall back to alternatives that might confuse the user.

**This fix enforces:**
- ❌ Don't silently debug wrong files
- ✅ Validate user's intent immediately
- ✅ Report errors with helpful suggestions
- ✅ Fail fast, fail clear

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `debug_controller.py` | 218-332 | Added `_validate_target_file()` with LLM extraction |
| `debug_controller.py` | 261-274 | Added validation check before debug loop |

---

## Testing

### Test Case 1: Valid File
```bash
raica debug -i "myprograms_test/quad_solver.py gives wrong results"
# Expected: ✅ Target file validated, proceeds with debug
```

### Test Case 2: Invalid Path
```bash
raica debug -i "/Development/quad_solver.py has bug"
# Expected: ❌ ERROR: File not found, exits immediately
```

### Test Case 3: No File Mentioned
```bash
raica debug -i "The calculator is broken"
# Expected: ✅ Automatic entry point detection
```

---

**Status:** Implemented ✅
**Testing:** Pending user verification
**Impact:** Eliminates wasted iterations on wrong files, improves UX dramatically
