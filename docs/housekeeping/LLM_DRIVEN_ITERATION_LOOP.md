# LLM-Driven Iteration Loop Architecture

**Date:** February 5, 2026
**Component:** Universal Handler (SYSTEM_TASK requests)
**Pattern:** DECIDE → ACT → VERIFY (with intelligent retry)

---

## Overview

This document describes the **LLM-driven iteration loop** implemented in Universal Handler, following the same architectural pattern as CODE_DEBUG's debug loop.

### Core Principle

Just as CODE_DEBUG iterates with test-driven verification:
```
ANALYZE → APPLY FIX → RUN TEST → if failed, retry with new approach
```

Universal Handler iterates with LLM-driven verification:
```
DECIDE → EXECUTE COMMAND → VERIFY TASK COMPLETE → if failed, retry with new approach
```

---

## Architecture Pattern: Consistent Across All Classifications

### CODE_DEBUG Loop (for bug fixes)
```python
while iteration < max_iterations:
    # DECIDE: Analyze bug and generate fix
    analysis = await self._analyze_bug()
    fix = await self._generate_fix(analysis)

    # ACT: Apply the fix
    await self._apply_fix(fix)

    # VERIFY: Run test to check if bug is fixed
    test_result = await self._run_test()

    if test_result.passed:
        return SUCCESS
    else:
        # Rollback and retry with updated context
        await self._rollback()
        continue
```

### Universal Handler Loop (for system tasks)
```python
while iteration < max_iterations:
    # DECIDE: Choose action based on context
    decision = await self._decide(request, context_with_previous_error)

    # ACT: Execute the decision
    act_result = await self._act(decision)

    # VERIFY: Ask LLM if task accomplished
    verification = await self._verify(request, decision, act_result)

    if verification['success']:
        return SUCCESS
    else:
        # Retry with error context
        last_error = verification['error']
        continue
```

**Key Insight:** Both use the same DECIDE-ACT-VERIFY pattern, adapted to their domain.

---

## Implementation Details

### 1. Iteration Loop Structure

**File:** `universal_handler.py` lines 318-411

```python
act_iteration = 0
last_error = None

while act_iteration < self.max_act_iterations:
    act_iteration += 1

    # Include previous failure context
    decision_context = gathered_context
    if last_error:
        decision_context += f"\n\n🚨 PREVIOUS ATTEMPT FAILED:\n{last_error}"

    # PHASE 3: DECIDE
    decision = await self._decide(request, decision_context)

    # PHASE 4: ACT
    act_result = await self._act(decision)

    # PHASE 5: VERIFY
    verification = await self._verify(request, decision, act_result)

    if verification['success']:
        result.success = True
        break  # Exit loop - SUCCESS!
    else:
        last_error = verification.get('error')
        # Continue to next iteration with error context
```

**Parameters:**
- `max_act_iterations`: Default 3 (configurable via constructor)
- Same concept as CODE_DEBUG's `max_iterations`

### 2. LLM-Driven Verification

**File:** `universal_handler.py` lines 1251-1342

Unlike CODE_DEBUG which uses test results (deterministic), Universal Handler uses **LLM evaluation** to verify task completion.

**Why LLM-driven?**
- EXECUTE commands don't always have tests
- Need to distinguish between:
  - **Diagnostic commands:** "mail --help" (succeeded but task not done)
  - **Task completion:** "echo ... | mail" (succeeded AND task done)
  - **Failures:** Command errors, wrong syntax, etc.

**Verification Prompt:**
```python
verification_prompt = f"""Verify if the user's request was accomplished.

ORIGINAL USER REQUEST: {request}
COMMANDS EXECUTED: {commands}
EXECUTION OUTPUT: {output}

VERIFICATION QUESTIONS:
1. Was the user's request FULLY accomplished?
2. OR is this a diagnostic/learning step?
3. Did the execution produce an error?

Return JSON:
{{
    "task_complete": true/false,
    "is_diagnostic": true/false,
    "reasoning": "...",
    "suggestion": "..."
}}
"""
```

**Three Outcomes:**

1. **Task Complete** (`task_complete: true`)
   - Original request was accomplished
   - Exit iteration loop with SUCCESS
   - Example: Email was actually sent

2. **Diagnostic Step** (`is_diagnostic: true`)
   - Command succeeded but task not complete
   - Need another iteration to complete task
   - Example: "mail --help" ran successfully, now try actual mail command

3. **Task Failed** (`task_complete: false, is_diagnostic: false`)
   - Command failed or produced error
   - Retry with different approach
   - Example: "mail: invalid option" → need to learn correct syntax

### 3. Retry Strategies

**File:** `universal_handler.py` lines 862-908

When verification fails, the DECIDE prompt guides the LLM on three retry strategies:

#### Strategy 1: INVESTIGATE
**When:** Don't know how to proceed, need more information

```json
{
    "decision_type": "EXECUTE",
    "reasoning": "Previous mail command failed. Running mail --help to learn syntax.",
    "commands": ["mail --help"],
    "requires_approval": false
}
```

**Result:** Verification marks as `is_diagnostic: true`, continues to next iteration with help output.

#### Strategy 2: CORRECT
**When:** Learned what was wrong, retry with corrected approach

```json
{
    "decision_type": "EXECUTE",
    "reasoning": "After reviewing mail --help, I understand the format. Retrying with corrected syntax.",
    "commands": ["echo 'Body' | mail -s 'Subject' user@email.com"],
    "requires_approval": true
}
```

**Result:** If task complete, verification returns success. If still wrong, retry again.

#### Strategy 3: SWITCH
**When:** Current approach keeps failing, try completely different strategy

```json
{
    "decision_type": "CREATE",
    "reasoning": "EXECUTE with mail command failed multiple times. Switching to Python script.",
    "code_prompt": "Create email sender script using smtplib...",
    "execute_after_create": true,
    "requires_approval": true
}
```

**Result:** Creates and executes script, which may have better error handling.

---

## Complete Flow Example: Email Sending

### Scenario: "Send email to John about lunch cancellation"

#### Iteration 1: Initial EXECUTE attempt
```
TRIAGE:
  - CHECK_TOOL: mail → Found!

DECIDE:
  - decision_type: EXECUTE
  - commands: ["echo 'Subject: Lunch\n\nBody' | mail -s 'Lunch' john@email.com"]

ACT:
  - Execute command
  - Result: "mail: invalid option"

VERIFY:
  - LLM evaluates: task_complete=false, is_diagnostic=false
  - Reasoning: "Command failed with syntax error"
  - Suggestion: "Check mail --help for correct syntax"
  - Return: {'success': False, 'error': '...'}

→ RETRY (iteration 2)
```

#### Iteration 2: Diagnostic command
```
DECIDE (with previous error context):
  - decision_type: EXECUTE
  - commands: ["mail --help"]
  - reasoning: "Learning correct mail syntax"

ACT:
  - Execute: mail --help
  - Result: Shows -s flag usage

VERIFY:
  - LLM evaluates: task_complete=false, is_diagnostic=true
  - Reasoning: "This is a diagnostic command to learn syntax"
  - Suggestion: "Now try with correct format"
  - Return: {'success': False, 'error': 'Diagnostic step completed...', 'diagnostic_output': '...'}

→ RETRY (iteration 3)
```

#### Iteration 3: Corrected command
```
DECIDE (with diagnostic output):
  - decision_type: EXECUTE
  - commands: ["echo 'I cannot attend lunch tomorrow' | mail -s 'Lunch Cancellation' john@email.com"]
  - reasoning: "Using corrected format from --help"

ACT:
  - Execute command
  - Result: (no output - email sent)

VERIFY:
  - LLM evaluates: task_complete=true
  - Reasoning: "Email sent successfully (mail command succeeded with no errors)"
  - Return: {'success': True}

→ SUCCESS! Exit loop
```

---

## Comparison: Universal Handler vs CODE_DEBUG

| Aspect | CODE_DEBUG | Universal Handler |
|--------|-----------|------------------|
| **Domain** | Bug fixes in code | System tasks (commands, scripts) |
| **DECIDE** | Analyze bug → generate fix | Classify request → choose action |
| **ACT** | Apply code patches | Execute commands or create scripts |
| **VERIFY** | Run tests (deterministic) | Ask LLM (semantic evaluation) |
| **Retry** | Rollback + try different fix | Try diagnostic/corrected/switched approach |
| **Max Iterations** | `max_regression_attempts` | `max_act_iterations` |
| **Success Criteria** | Test passes | LLM confirms task complete |

**Common Pattern:**
- Both iterate until success or max iterations
- Both pass previous failure context to next iteration
- Both allow LLM to choose different approaches on retry
- Both follow DECIDE-ACT-VERIFY loop

---

## Benefits of This Architecture

### 1. **Consistency Across Classifications**
- CODE_DEBUG: test-driven verification
- Universal Handler: LLM-driven verification
- **Same pattern, different verification mechanism**

### 2. **No Hardcoded Recovery Logic**
- Don't hardcode "if mail fails, try sendmail"
- Don't hardcode "if syntax error, run --help"
- **LLM decides** based on error context

### 3. **Intelligent Learning**
- LLM can run diagnostic commands to learn
- Incorporates learned information into retry
- Can switch strategies if approach isn't working

### 4. **Handles Edge Cases Automatically**
- Novel error types → LLM figures out what to do
- Unfamiliar tools → LLM learns from --help
- Complex authentication → LLM switches to script

### 5. **Verifiable Actions**
- LLM chooses actions that can be verified
- Distinguishes diagnostic vs completion
- Provides clear success/failure criteria

---

## Configuration

**File:** `universal_handler.py` constructor

```python
handler = UniversalHandler(
    llm_client=llm_client,
    project_dir=project_dir,
    max_act_iterations=3,  # Max DECIDE-ACT-VERIFY cycles
    max_triage_iterations=3,  # Max TRIAGE-GATHER cycles
    ...
)
```

**Default:** 3 iterations (matching CODE_DEBUG default)

---

## Testing

### Test Case 1: Immediate Success
```
Request: "send email to john@email.com"
- Iteration 1: mail command works → SUCCESS
Total iterations: 1
```

### Test Case 2: Learn and Retry
```
Request: "send email to john@email.com"
- Iteration 1: mail command fails (wrong syntax)
- Iteration 2: mail --help (diagnostic)
- Iteration 3: corrected mail command → SUCCESS
Total iterations: 3
```

### Test Case 3: Switch Strategy
```
Request: "send email with Gmail SMTP"
- Iteration 1: mail command fails (needs auth)
- Iteration 2: Try different mail syntax
- Iteration 3: Switch to CREATE Python script → SUCCESS
Total iterations: 3
```

### Test Case 4: Max Iterations Reached
```
Request: "impossible task"
- Iteration 1: EXECUTE fails
- Iteration 2: Diagnostic command
- Iteration 3: Different approach fails
Max iterations reached → FAILURE (with error log)
```

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `universal_handler.py` | 224-248 | Added `max_act_iterations` parameter |
| `universal_handler.py` | 318-411 | Iteration loop structure (DECIDE-ACT-VERIFY) |
| `universal_handler.py` | 1251-1342 | LLM-driven EXECUTE verification |
| `universal_handler.py` | 862-908 | Retry strategy guidance in DECIDE prompt |
| `universal_handler.py` | 970-1000 | Retry decision examples (diagnostic, corrected, switched) |

---

## Related Documentation

- **Bug Fix #4-7:** Universal Handler decision types and execution
- **Bug Fix #8:** Request classification (SYSTEM_TASK routing)
- **Bug Fix #9:** Proactive tool checking in TRIAGE
- **CODE_DEBUG:** `autonomous/debug_controller.py` - Reference implementation

---

**Status:** Implemented ✅
**Testing:** Ready for end-to-end email sending test
**Next:** User verification with complete pipeline
