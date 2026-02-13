# Bug Fix: Test Error Investigation Not Triggering

**Date:** February 6, 2026
**Component:** cli_coding_agent.py - Testing Phase
**Severity:** HIGH - Test errors not investigated, wastes iterations
**Issue:** Test retry loop missing error case handling

---

## Problem

Test retry loop wasn't triggering investigation when tests had ERRORS (as opposed to FAILURES).

### Three Types of Test Results

1. **Tests FAILED** - Tests ran but assertions failed → Investigation triggered ✅
2. **Tests didn't RUN** - `test_result.ran = False` → Investigation triggered ✅
3. **Tests had ERRORS** - `test_result.ran = True` but `test_result.errors` not empty → **Investigation NOT triggered** ❌

### User's Scenario

```
🧪 Running tests in sandbox...
❌ ERROR: Test execution failed
❌ ERROR: Test execution failed
❌ ERROR: Test execution failed

✅ Testing phase complete  ← Wrong! Tests had errors!
   Tests passed: 0
   Tests failed: 0
```

**What happened:**
1. Test file generated with wrong path: `../myprograms_test/quad_solver.py`
2. Actual path should be: `./myprograms_test/quad_solver.py`
3. pytest collection error: `FileNotFoundError`
4. Error stored in `test_result.errors`
5. Loop printed error 3 times but never investigated
6. No fix applied, same error every iteration

### Root Cause

**cli_coding_agent.py lines 2439-2450 (before fix):**

```python
if test_result.errors:
    for e in test_result.errors[:3]:
        print(f"   ❌ ERROR: {e}")
    # ❌ NO INVESTIGATION TRIGGERED!

# Check if tests passed
total = len(test_result.passed) + len(test_result.failed)
if total > 0:
    # Handle results
else:
    # No tests ran, but loop just continues without investigation
```

The code handled two cases:
1. `if test_result.failed:` → Investigation triggered
2. `else:` (when `test_result.ran = False`) → Investigation triggered

But missed the third case:
3. `test_result.ran = True` AND `test_result.errors` not empty → **No investigation!**

---

## Solution

Add investigation trigger for test errors case.

### Changes Made

**cli_coding_agent.py lines 2439-2458 (after fix):**

```python
if test_result.errors:
    for e in test_result.errors[:3]:
        print(f"   ❌ ERROR: {e}")

    # ✅ TRIGGER INVESTIGATION for errors
    if test_iteration < max_test_retries:
        print(f"\n   🔍 Investigating test errors (attempt {test_iteration}/{max_test_retries})...")

        # DECIDE-ACT-VERIFY: Ask LLM to investigate and fix
        fix_applied = await self._investigate_and_fix_test_failure(
            test_file=test_file,
            main_file=main_file,
            test_result=test_result
        )

        if fix_applied:
            print(f"   ✅ Fix applied, retrying tests...")
            continue  # Retry tests
        else:
            print(f"   ⚠️ Could not determine fix, skipping retry")
            break
```

Also added safety check for edge case (no tests, no errors, no failures):

```python
# Check if tests passed
total = len(test_result.passed) + len(test_result.failed)
if total > 0:
    # Handle passed/failed tests
else:
    # No tests ran - break to avoid infinite loop
    if test_iteration >= max_test_retries or not test_result.errors:
        print(f"   ⚠️ No tests executed")
        break
```

---

## Behavior Comparison

### Before Fix

```
🧪 Running tests in sandbox...
❌ ERROR: Test execution failed
❌ ERROR: Test execution failed
❌ ERROR: Test execution failed

✅ Testing phase complete
   Tests passed: 0
   Tests failed: 0
```

**Loop ran 3 times:**
- Iteration 1: Print error, no investigation, continue
- Iteration 2: Print error, no investigation, continue
- Iteration 3: Print error, no investigation, exit
- Result: Same error every time, no fix applied

### After Fix

```
🧪 Running tests in sandbox...
❌ ERROR: FileNotFoundError: [Errno 2] No such file or directory: '/home/sabawi/Development/myprograms_test/quad_solver.py'

🔍 Investigating test errors (attempt 1/3)...
📝 Analysis: Test file has wrong import path - uses '../myprograms_test' but should use './myprograms_test'
🔧 Fixing: test file
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

**Loop behavior:**
- Iteration 1: Error detected → Investigation triggered → LLM analyzes → Fix applied
- Iteration 2: Tests run successfully → All pass → Loop exits
- Result: Self-healing! Test file fixed automatically

---

## All Three Cases Now Handled

| Case | `test_result.ran` | Condition | Investigation | Status |
|------|-------------------|-----------|---------------|---------|
| **Tests FAILED** | True | `test_result.failed` not empty | ✅ Triggered (line 2412) | Working |
| **Tests had ERRORS** | True | `test_result.errors` not empty | ✅ Triggered (line 2445) | **FIXED** |
| **Tests didn't RUN** | False | - | ✅ Triggered (line 2475) | Working |

---

## Testing

### Test Case: Path Error in Generated Test

**Setup:**
```bash
cd /home/sabawi/Development/raica_playground
raica -p "Create myprograms_test/quad_solver.py"
```

**Expected behavior:**
1. Test generated with path error
2. First run: FileNotFoundError
3. Investigation triggered
4. LLM fixes test file path
5. Second run: Tests pass

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `cli_coding_agent.py` | 2445-2460 | Add investigation for `test_result.errors` case |
| `cli_coding_agent.py` | 2476-2480 | Add safety check for no tests case |
| `cli_coding_agent.py` | 2581-2582 | Fix LLM client call - use `generate()` not `send_message()` |

## Additional Fix: Correct LLM Client Method

**Issue Found During Testing:**
```
ERROR - Error in test failure investigation: 'CodeGenLLMClient' object has no attribute 'send_message'
```

**Problem:** Used wrong method name `send_message()` instead of `generate()`

**Fix:**
```python
# Before (wrong):
response = await self.llm_client.send_message(prompt, model="primary")
data = self._extract_json(response)

# After (correct):
response = self.llm_client.generate(prompt)
data = self._extract_json(response.content if hasattr(response, 'content') else response)
```

---

**Status:** Implemented ✅
**Related:** BUG_FIX_10_IMPORT_VALIDATION_AND_TEST_RETRY.md
**Impact:** Test retry loop now handles all three test result cases
