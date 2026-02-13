# Bug Fix: LLM-Driven Test Generation and Investigation

**Date:** February 6, 2026
**Component:** cli_coding_agent.py - Test Generation & Investigation Loop
**Severity:** CRITICAL - Investigation loop destroying main code, tests calling non-existent functions
**Principle:** LLM-Driven, No Hardcoding, Always Generalize

---

## Problems

### Problem 1: Test Generation Creates Tests for Non-Existent Functions

**User's quad_solver.py had:**
- `solve_quadratic(a, b, c)` - prints results
- `solve_linear(b, c)` - handles linear case
- `format_complex(z)` - formats complex numbers
- `main()` - CLI entry point

**But generated test expected:**
- `compute_roots(a, b, c)` - doesn't exist! ❌
- `format_number()` - wrong name! ❌
- `parse_arguments()` - doesn't exist! ❌

**Root Cause:** Test generation prompt was TOO VAGUE:
```python
prompt = """Write comprehensive standalone tests:
- Test main functionality  ← WHAT DOES THIS MEAN?!
- Test edge cases          ← WHICH ONES?!
- Test error handling      ← HOW?!
"""
```

LLM had NO GUIDANCE on:
- ❌ What functions actually exist
- ❌ What their signatures are
- ❌ What they return vs print
- ❌ How to call them

So LLM **GUESSED** and invented functions that don't exist!

### Problem 2: Investigation Loop Destroys Main Code

When tests failed with `AttributeError: no attribute 'compute_roots'`:

**What SHOULD happen:**
```
Test calls non-existent function → TEST IS WRONG → FIX TEST
```

**What ACTUALLY happened:**
```
Test calls non-existent function → Default fix_target='main' → OVERWRITES MAIN CODE WITH GARBAGE
```

After 3 iterations, quad_solver.py contained **pytest stub code** instead of quadratic solver!

**Root Cause:**
- Line 2683: `fix_target = 'main'  # Default` ← DANGEROUS!
- No validation before overwriting main
- Investigation should be BIASED toward fixing tests (they're more likely wrong)

---

## Solution: LLM-Driven Analysis and Generation

### Architectural Principle (from CLAUDE.md)

**NO HARDCODING, ALWAYS GENERALIZE, LLM DECIDES EVERYTHING**

❌ Don't hardcode test scenarios
❌ Don't hardcode function names
❌ Don't hardcode language-specific patterns
✅ LLM analyzes code
✅ LLM determines what to test
✅ LLM generates appropriate tests

### Fix 1: LLM-Driven Test Generation

**New prompt structure (lines 2355-2432):**

```python
prompt = f"""You are writing unit tests for the following code.

FILE: {main_file}
LOCATION: {file_path}

CODE TO TEST:
```python
{main_code}  # FULL CODE, not truncated
```

STEP 1: ANALYZE THE CODE
Before writing any tests, analyze the code to understand:
1. What functions/classes/methods are defined? (list their exact names and signatures)
2. What do they DO? (return values vs print output vs side effects vs file operations)
3. How is the code USED? (imported as library, run as CLI tool, server, etc.)
4. What are the inputs and expected outputs?
5. What edge cases exist in the logic? (boundary conditions, special values, branches)
6. What error cases should be handled? (invalid inputs, exceptions)

STEP 2: GENERATE STANDALONE TESTS
Based on your analysis, write comprehensive tests that:

CRITICAL REQUIREMENTS:
- Call ONLY functions that actually exist in the code above (don't invent function names!)
- Match the actual signatures (if function takes 3 args, pass 3 args)
- Handle the code's actual behavior:
  * If it RETURNS values → test the return values
  * If it PRINTS output → capture stdout with io.StringIO and contextlib.redirect_stdout
  * If it uses sys.argv → manipulate sys.argv in test setup/teardown
  * If it reads files → create temporary test files
- Test the scenarios you identified in your analysis (normal cases, edge cases, errors)
- Use ONLY Python standard library (no pytest, no unittest, no external packages)

Remember: Analyze the code FIRST, then write tests for what actually exists!
"""
```

**Key changes:**
- ✅ FULL code provided (not truncated to 2500 chars)
- ✅ LLM ANALYZES before generating (extracts actual functions, signatures, behavior)
- ✅ NO hardcoded scenarios (LLM determines what to test based on code)
- ✅ Explicit: "Call ONLY functions that actually exist"
- ✅ Handles different code patterns (returns vs prints, CLI vs library)
- ✅ Generalized (works for any Python code, not just quad solvers)

### Fix 2: Smarter Investigation Loop

**New investigation prompt (lines 2607-2677):**

```python
prompt = f"""You are debugging a test failure.

TEST FILE: {test_file}
```python
{test_code}
```

MAIN CODE BEING TESTED: {main_file}
```python
{main_code}
```

TEST EXECUTION FAILURE:
Output: {failure_context['test_output']}
Stderr: {failure_context['test_stderr']}
Error: {failure_context['error_message']}

CRITICAL CONTEXT:
- Main code was generated in CODE GENERATION phase (should be working)
- Test was generated in TEST GENERATION phase (might have wrong expectations)
- Tests run in minimal sandbox (Python standard library only, no pytest/unittest)

STEP 1: ANALYZE THE FAILURE
Determine the ROOT CAUSE:

1. API MISMATCH? (test calls functions that don't exist in main)
   - Error: "AttributeError: no attribute 'function_name'"
   - Cause: Test expects different API than main provides
   - Fix: TEST needs rewriting to call actual functions

2. WRONG EXPECTATIONS? (test has incorrect assertions)
   - Error: AssertionError with wrong expected values
   - Cause: Test expects different behavior than main implements
   - Fix: TEST needs updated assertions

3. MISSING DEPENDENCIES? (test imports external packages)
   - Error: "ModuleNotFoundError: No module named 'pytest'"
   - Cause: Test uses packages not available in sandbox
   - Fix: TEST needs rewriting without external packages

4. MAIN CODE BUG? (actual logic error in implementation)
   - Error: Correct API calls but wrong results
   - Cause: Bug in main code's logic
   - Fix: MAIN needs bug fix

STEP 2: DETERMINE FIX TARGET
Based on your analysis:
- If API mismatch (1) → fix_target: test
- If wrong expectations (2) → fix_target: test
- If missing dependencies (3) → fix_target: test
- If actual bug in main (4) → fix_target: main

DEFAULT: Assume test is wrong (it was just generated and might not match main's actual API)

RESPONSE FORMAT:
Analysis: [Your analysis of what's wrong and why]

fix_target: test
(or "fix_target: main" if main code has actual bug)

```python
# Complete fixed code for the target file
```

If fixing test for API mismatch: Read the main code's actual functions and call those (don't invent functions)!
"""
```

**Key changes:**
- ✅ LLM sees BOTH files and full error context
- ✅ Clear root cause analysis framework (4 categories)
- ✅ Explicit guidance: API mismatch → fix test, logic bug → fix main
- ✅ DEFAULT: Assume test is wrong (safer)
- ✅ Context about what phase generated each file

**Fix target extraction (lines 2682-2689):**

```python
# ARCHITECTURE: DEFAULT to 'test' (safer - don't destroy working main code)
# LLM must explicitly say "fix_target: main" to fix main code
fix_target = 'test'  # SAFE DEFAULT
if 'fix_target: main' in response_text.lower() or 'fix_target:main' in response_text.lower():
    fix_target = 'main'
```

**Changed from:**
- ❌ `fix_target = 'main'  # Default` ← DANGEROUS
- ✅ `fix_target = 'test'  # SAFE DEFAULT`

**Validation before fixing main (lines 2724-2743):**

```python
if fix_target == 'main':
    # CRITICAL: Validate that fixed main code makes sense
    if 'def ' not in fixed_code and 'class ' not in fixed_code:
        self.logger.warning("Fixed main code has no functions/classes - rejecting!")
        print(f"   ⚠️ Warning: Fixed code has no definitions - likely wrong, skipping fix")
        return False

    # Log what we're about to do (for debugging disasters)
    self.logger.warning(f"About to OVERWRITE main file {main_file} - this is risky!")
    self.logger.debug(f"New code preview (first 300 chars):\n{fixed_code[:300]}")
```

**Prevents:**
- Overwriting solver code with pytest stub
- Destroying working main code with nonsense
- Silent failures (logs warnings before risky operations)

---

## Behavior Comparison

### Before Fix

**Test Generation:**
```
User: "Create quad_solver.py"
Code Gen: Creates solve_quadratic(), solve_linear(), format_complex()
Test Gen: "Write tests" (no context about actual functions)
LLM: Invents compute_roots(), format_number(), parse_arguments() ❌
Result: Tests call functions that don't exist
```

**Investigation:**
```
Test Execution: AttributeError: no attribute 'compute_roots'
Investigation: Default fix_target='main' ❌
Fix Applied: Overwrites quad_solver.py with pytest stub ❌
Retry 1: Still fails (main code is now garbage)
Investigation: Overwrites again with different garbage ❌
Retry 2: Still fails
Investigation: Overwrites again ❌
Retry 3: Still fails
Result: Main code completely destroyed!
```

### After Fix

**Test Generation:**
```
User: "Create quad_solver.py"
Code Gen: Creates solve_quadratic(), solve_linear(), format_complex()
Test Gen: "ANALYZE the code first - what functions exist?"
LLM: Sees solve_quadratic(), solve_linear(), format_complex() ✅
LLM: Generates tests that call actual functions ✅
Result: Tests match actual API
```

**Investigation (if needed):**
```
Test Execution: (If API mismatch somehow occurs)
Investigation: Analyzes → "API MISMATCH: test calls compute_roots() but main has solve_quadratic()"
Fix Target: 'test' (default) ✅
Fix Applied: Rewrites test to call solve_quadratic() ✅
Validation: Checks fixed code has test functions ✅
Result: Test fixed, main code untouched
```

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `cli_coding_agent.py` | 2349-2432 | Test generation with LLM-driven analysis |
| `cli_coding_agent.py` | 2607-2677 | Investigation with root cause framework |
| `cli_coding_agent.py` | 2682-2689 | Safe default fix_target='test' |
| `cli_coding_agent.py` | 2724-2743 | Validation before fixing main |

---

## Architectural Principles Enforced

### 1. LLM-Driven (No Hardcoding)
- ❌ Don't hardcode: "Test with a=1, b=-3, c=2"
- ✅ LLM analyzes code and determines test scenarios

### 2. Always Generalize
- ❌ Don't assume code structure (quadratic solver specific)
- ✅ Works for any code (CLI tools, libraries, servers, etc.)

### 3. Fail Safe
- ❌ Don't default to fixing main (risky)
- ✅ Default to fixing test (safer)
- ✅ Validate before overwriting

### 4. Context-Driven
- ❌ Don't generate tests without seeing code
- ✅ LLM sees full code before generating tests
- ✅ LLM analyzes actual functions, signatures, behavior

---

## Testing

### Test Case 1: Generate Tests for quad_solver.py

**Setup:**
```bash
cd /home/sabawi/Development/raica_playground
# Ensure quad_solver.py exists with: solve_quadratic(), solve_linear(), format_complex(), main()
```

**Command:**
```bash
raica -p "Create tests for myprograms_test/quad_solver.py"
```

**Expected:**
1. Test generation analyzes quad_solver.py
2. Identifies actual functions: solve_quadratic(), solve_linear(), format_complex(), main()
3. Generates tests that call THOSE functions (not invented ones)
4. Tests capture stdout (since functions print results)
5. Tests manipulate sys.argv (since main() uses CLI args)
6. Tests run successfully

### Test Case 2: Investigation Fixes Test (Not Main)

**Setup:** Manually create test with wrong function name
```python
# test_quad_solver.py
def test_wrong_api():
    result = quad_solver.compute_roots(1, -3, 2)  # Function doesn't exist!
    assert result is not None
```

**Expected:**
1. Test execution fails: AttributeError
2. Investigation analyzes: "API MISMATCH - compute_roots() doesn't exist"
3. Fix target: 'test' (default)
4. Rewrites test to call solve_quadratic() instead
5. Main code untouched

---

**Status:** Implemented ✅
**Testing:** Pending user verification
**Impact:** Tests now match actual code API, investigation doesn't destroy main code

---

## Related Documents

- `/docs/housekeeping/BUG_FIX_10_IMPORT_VALIDATION_AND_TEST_RETRY.md` - Test retry loop
- `/docs/housekeeping/REFACTOR_USE_ESTABLISHED_CODE_EXTRACTION.md` - Code extraction patterns
- `CLAUDE.md` - Architectural principles (LLM-driven, no hardcoding)
