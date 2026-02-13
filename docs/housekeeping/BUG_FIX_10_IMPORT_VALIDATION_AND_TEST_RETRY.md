# Bug Fix: Import Validation & Test Retry Loop

**Date:** February 6, 2026
**Components:** validation.py, cli_coding_agent.py
**Severity:** HIGH - Wastes iterations, misleading errors
**Principle:** LLM-driven iteration loops everywhere

---

## Problem 1: Import Validation Checks Unrelated Files

### Issue

When validating imports during TESTING phase, the sandbox checked **ALL** Python files in the project directory, including:
- Files created by user previously (gmail_bill_finder.py)
- Old experimental files
- Unrelated scripts

This caused validation to fail with errors like:
```
❌ Import validation failed:
   - FAIL: gmail_bill_finder: ModuleNotFoundError: No module named 'dotenv'
```

Even though the user was only testing `quad_solver.py` which had nothing to do with `gmail_bill_finder.py`.

### Root Cause

**validation.py lines 3212-3213:**
```python
# Find all Python files
py_files = list(self.project_dir.glob('**/*.py'))
```

Scanned entire directory, no filtering for task-specific files.

**cli_coding_agent.py line 2261:**
```python
exec_result = self.code_validator.validate_execution()
```

Didn't pass any information about which files to validate.

### Example

User working in `/home/sabawi/Development/raica_playground` with this structure:
```
raica_playground/
├── gmail_bill_finder.py          # Old file, imports dotenv
├── generate_twitter_html.py      # Old file
├── myprograms_test/
│   └── quad_solver.py            # NEW - being tested
└── test_quad_solver.py           # NEW - generated test
```

Validation checked **ALL** files, failed on gmail_bill_finder.py even though user only cares about quad_solver.py.

---

## Solution 1: Validate Only Task-Related Files

### Changes Made

**1. Modified `DockerSandbox.validate_imports()` (validation.py lines 3199-3289)**

Added `files_to_validate` parameter:

```python
def validate_imports(self, files_to_validate: Optional[List[str]] = None) -> ExecutionResult:
    """
    Args:
        files_to_validate: Optional list of specific files to validate.
                         If None, validates ALL files (legacy behavior).
                         If provided, ONLY validates these files (ignores unrelated files).
    """
    # ...

    # If specific files to validate provided, convert to Path objects
    files_filter = None
    if files_to_validate:
        files_filter = {self.project_dir / f for f in files_to_validate}

    validated_count = 0
    for py_file in py_files:
        # If specific files provided, ONLY validate those files
        if files_filter and py_file not in files_filter:
            continue  # ✅ Skip unrelated files!
```

**2. Modified `CodeValidator.validate_execution()` (validation.py line 3371)**

Pass through `files_to_validate`:

```python
def validate_execution(
    self,
    entry_point: Optional[str] = None,
    files_to_validate: Optional[List[str]] = None
) -> ExecutionResult:
    # ...
    import_result = self.sandbox.validate_imports(files_to_validate=files_to_validate)
```

**3. Modified CLI agent to pass generated files (cli_coding_agent.py lines 2262-2264)**

```python
# ONLY validate files we generated (skip unrelated files in project dir)
print("\n   🧪 Validating imports...")
files_to_validate = list(self.context.generated_files.keys())
exec_result = self.code_validator.validate_execution(files_to_validate=files_to_validate)
```

### Behavior After Fix

**Before:**
```
Validating imports...
❌ Import validation failed:
   - FAIL: gmail_bill_finder: ModuleNotFoundError: No module named 'dotenv'
   - FAIL: generate_twitter_html: ...
   (fails even though user only working on quad_solver.py)
```

**After:**
```
Validating imports...
   Checking: myprograms_test/quad_solver.py
✅ Import validation passed (docker)
```

Only validates files being created/modified in current task!

---

## Problem 2: Test Execution Failures Don't Trigger Investigation

### Issue

When tests failed or didn't execute, the testing phase would:
- ❌ Log the failure with ⚠️ warning
- ❌ Continue to next phase immediately
- ❌ Never investigate WHY tests failed
- ❌ Never retry with a fix

User's output showed:
```
🧪 Running tests in sandbox...
❌ ERROR: Test execution failed

✅ Testing phase complete  ← Wrong! Tests failed but phase says "complete"
   Tests passed: 0
   Tests failed: 0
```

### Root Cause

**cli_coding_agent.py lines 2415-2419 (old code):**

```python
else:
    if test_result.error_message:
        print(f"   ⚠️ Could not run tests: {test_result.error_message}")
    else:
        print("   ⚠️ Tests did not run")
# No retry, no investigation, just continue!
```

**Violates CLAUDE.md principle:**
> Every solution MUST follow DECIDE-ACT-VERIFY loop pattern

---

## Solution 2: Add DECIDE-ACT-VERIFY Loop for Test Failures

### Architecture

Same pattern as autonomous debug loop:

```
TESTING PHASE
    ↓
RUN TESTS (iteration 1)
    ↓
VERIFY: Did tests pass?
    ├─ YES → Success, exit loop
    └─ NO → INVESTIGATE
            ↓
         DECIDE: Ask LLM to analyze failure
            ↓
         ACT: Apply LLM's fix (test or main code)
            ↓
         VERIFY: Re-run tests (iteration 2)
            ↓
         (Repeat up to max_iterations = 3)
```

### Changes Made

**1. Convert testing phase to async (cli_coding_agent.py line 2225)**

```python
async def _phase_testing(self) -> bool:
    """
    Phase 7: Generate and run tests with Docker sandbox execution.

    Includes DECIDE-ACT-VERIFY loop for test failures (max 3 retries).
    """
```

**2. Add retry loop (cli_coding_agent.py lines 2388-2476)**

```python
max_test_retries = 3
test_iteration = 0
test_success = False

while test_iteration < max_test_retries and not test_success:
    test_iteration += 1
    test_result = self.code_validator.run_tests()

    if test_result.ran:
        if test_result.failed:
            # If tests failed and we have retries left, trigger investigation
            if test_iteration < max_test_retries:
                print(f"\n   🔍 Investigating test failures (attempt {test_iteration}/{max_test_retries})...")

                # DECIDE-ACT-VERIFY: Ask LLM to investigate and fix
                fix_applied = await self._investigate_and_fix_test_failure(
                    test_file=test_file,
                    main_file=main_file,
                    test_result=test_result
                )

                if fix_applied:
                    print(f"   ✅ Fix applied, retrying tests...")
                    continue  # Retry tests
```

**3. Add investigation method (cli_coding_agent.py lines 2483-2575)**

```python
async def _investigate_and_fix_test_failure(
    self,
    test_file: str,
    main_file: str,
    test_result
) -> bool:
    """
    DECIDE-ACT-VERIFY loop for test failures.

    When tests fail, LLM investigates the failure and proposes a fix.
    """
    # Read current files
    test_code = test_path.read_text()
    main_code = main_path.read_text()

    # Build failure context
    failure_context = {
        "test_output": test_result.output,
        "test_stderr": test_result.stderr,
        "failed_tests": test_result.failed,
        "error_message": test_result.error_message
    }

    # DECIDE: Ask LLM to analyze failure and propose fix
    prompt = f"""You are debugging a test failure.

TEST FILE: {test_file}
```python
{test_code}
```

MAIN FILE: {main_file}
```python
{main_code}
```

TEST OUTPUT:
{failure_context['test_output']}

ANALYZE the test failure and determine:
1. Is the TEST incorrect (wrong expectations/assertions)?
2. Is the MAIN CODE incorrect (bug in implementation)?
3. What specific fix is needed?

Return JSON:
{{
    "analysis": "Brief explanation of what's wrong",
    "fix_target": "test" or "main",
    "fix_description": "What to change",
    "fixed_code": "Complete fixed code for the file"
}}
"""

    response = await self.llm_client.send_message(prompt, model="primary")
    data = self._extract_json(response)

    # ACT: Apply the fix
    fix_target = data.get('fix_target', 'main')
    fixed_code = data.get('fixed_code', '')

    if fix_target == 'test':
        test_path.write_text(fixed_code)
    else:
        main_path.write_text(fixed_code)

    return True
```

**4. Handle async phase execution (cli_coding_agent.py lines 2991-2998)**

```python
# Check if handler is async and await it if needed
import inspect
import asyncio
if inspect.iscoroutinefunction(handler):
    success = asyncio.run(handler())
else:
    success = handler()
```

### Behavior After Fix

**Before:**
```
🧪 Running tests in sandbox...
❌ ERROR: Test execution failed

✅ Testing phase complete  ← Wrong!
   Tests passed: 0
   Tests failed: 0
```

**After:**
```
🧪 Running tests in sandbox...
   ❌ FAILED: test_quad_solver::test_positive_discriminant

   🔍 Investigating test failures (attempt 1/3)...
   📝 Analysis: The test expects two roots but function returns wrong order
   🔧 Fixing: main file
   ✅ Fix applied, retrying tests...

   🧪 Running tests in sandbox...
   ✅ PASSED: test_quad_solver::test_positive_discriminant
   ✅ PASSED: test_quad_solver::test_zero_discriminant
   ✅ PASSED: test_quad_solver::test_negative_discriminant

   📊 Test Results: 3/3 passed ✅

✅ Testing phase complete
   Tests passed: 3
   Tests failed: 0
```

---

## Benefits

### 1. **Focused Validation**
- Only validates files being worked on
- No false failures from unrelated files
- Faster validation (fewer files to check)

### 2. **Self-Healing Tests**
- Automatically investigates test failures
- Fixes bugs in code OR tests
- Up to 3 retry attempts
- LLM decides what's wrong and how to fix

### 3. **Consistent Architecture**
- Same DECIDE-ACT-VERIFY pattern everywhere
- Testing phase now matches debug loop pattern
- Follows CLAUDE.md principles

### 4. **Better UX**
- Clear error messages with investigation steps
- Shows what's being fixed
- Automatic retry instead of giving up
- Accurate success/failure reporting

---

## Testing

### Test Case 1: Validate Only Generated Files

**Setup:**
```bash
cd /home/sabawi/Development/raica_playground
# Has old files: gmail_bill_finder.py (imports dotenv)
```

**Command:**
```bash
raica -p "Create myprograms_test/quad_solver.py"
```

**Expected:**
- Validation only checks myprograms_test/quad_solver.py
- Ignores gmail_bill_finder.py
- No false import errors

### Test Case 2: Test Failure Auto-Fix

**Setup:** Create a test that will initially fail

**Command:**
```bash
raica -p "Write quad_solver.py that returns wrong root order"
```

**Expected:**
1. Tests generated and run
2. Tests fail (wrong root order)
3. Investigation triggered
4. LLM analyzes failure
5. Fix applied to main code
6. Tests re-run and pass

### Test Case 3: Test Execution Failure

**Setup:** Test file has syntax error

**Expected:**
1. Test execution fails
2. Investigation triggered
3. LLM identifies syntax error in test
4. Fix applied to test file
5. Tests re-run successfully

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `validation.py` | 3199-3289 | Added `files_to_validate` param to `DockerSandbox.validate_imports()` |
| `validation.py` | 3371-3402 | Added `files_to_validate` param to `CodeValidator.validate_execution()` |
| `cli_coding_agent.py` | 2262-2264 | Pass generated files to validation |
| `cli_coding_agent.py` | 2225 | Made `_phase_testing()` async |
| `cli_coding_agent.py` | 2388-2476 | Added retry loop with investigation |
| `cli_coding_agent.py` | 2483-2575 | Added `_investigate_and_fix_test_failure()` method |
| `cli_coding_agent.py` | 2991-2998 | Handle async phase execution |

---

**Status:** Implemented ✅
**Testing:** Pending user verification
**Impact:** Eliminates false validation errors, enables self-healing tests
