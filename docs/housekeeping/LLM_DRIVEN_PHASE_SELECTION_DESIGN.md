# LLM-Driven Phase Selection Architecture

**Version:** 1.0.0.35
**Date:** 2026-02-06
**Purpose:** Fix hardcoded phase flow that violates "LLM decides, RAICA executes" principle

---

## Problem: Hardcoded Phase Flow

### Current (WRONG) - Violates Architecture:
```
❌ HARDCODED: ALL requests forced through:
   TRIAGE → GATHER → DECIDE → ACT → VERIFY (with retry loop)
```

**Example Bug - Send Email:**
1. ACT: Execute mail command → **Email SENT** 📧
2. Command hangs waiting for SMTP → **Timeout after 120s**
3. VERIFY: Sees timeout → Returns **False**
4. RETRY triggered → DECIDE → ACT again
5. ACT: Execute mail command → **Email sent 2nd time** 📧📧
6. Timeout again → RETRY
7. ACT: Execute mail command → **Email sent 3rd time** 📧📧📧

**Root Cause:** Hardcoded phase flow doesn't consider:
- Side effects (email, post, publish, delete)
- Request complexity (one-shot vs multi-step)
- Verification needs (some commands are fire-and-forget)

### Architectural Violation

From `CLAUDE.md`:
```
⛔ FORBIDDEN:
❌ Hardcoded lists
❌ Pattern matching
❌ Special case handlers

✅ REQUIRED:
✅ LLM decides, RAICA executes
```

**Hardcoded phase flow is exactly this violation!**

---

## Solution: LLM-Driven Execution Strategy

### New Architecture:

```
User Request
    ↓
STRATEGY (Phase 0): LLM analyzes request and decides execution strategy
    ↓
    Returns JSON:
    {
      "execution_type": "ONE_SHOT_ACTION",
      "phases_needed": ["EXECUTE"],
      "retry_policy": {
        "enabled": false,
        "reason": "Side effects - action will happen multiple times if retried"
      },
      "verification_strategy": "TRUST_EXIT_CODE"
    }
    ↓
RAICA executes according to LLM's strategy (NOT hardcoded flow!)
    ↓
For ONE_SHOT_ACTION:
    EXECUTE → Done (no retry, no verification)

For INVESTIGATIVE_TASK:
    TRIAGE → GATHER → DECIDE → ACT → VERIFY (with retries)

For CODE_MODIFICATION:
    TRIAGE → GATHER → DECIDE → ACT → VERIFY → TEST (with retries)
```

---

## Execution Types (LLM Decides)

### 1. ONE_SHOT_ACTION
**Examples:** Send email, post tweet, delete file, download file, curl POST

**Strategy:**
```json
{
  "execution_type": "ONE_SHOT_ACTION",
  "phases_needed": ["EXECUTE"],
  "retry_policy": {
    "enabled": false,
    "reason": "Side effects - will send email multiple times if retried"
  },
  "verification_strategy": "TRUST_EXIT_CODE",
  "failure_handling": "REPORT_AND_STOP"
}
```

**Characteristics:**
- ✅ Execute once immediately
- ❌ No retry loop (side effects!)
- ❌ No verification phase (trust exit code)
- Fire and forget

### 2. INVESTIGATIVE_TASK
**Examples:** Check system status, read files, search for info, diagnose issue

**Strategy:**
```json
{
  "execution_type": "INVESTIGATIVE_TASK",
  "phases_needed": ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"],
  "retry_policy": {
    "enabled": true,
    "max_retries": 3,
    "reason": "Read-only operations safe to retry"
  },
  "verification_strategy": "LLM_SEMANTIC",
  "failure_handling": "RETRY_WITH_DIFFERENT_APPROACH"
}
```

**Characteristics:**
- ✅ Full diagnostic flow
- ✅ Retry allowed (no side effects)
- ✅ LLM verification (semantic - did we get the info?)
- Gather → Analyze → Report

### 3. CODE_MODIFICATION
**Examples:** Fix bug, add feature, improve code, refactor

**Strategy:**
```json
{
  "execution_type": "CODE_MODIFICATION",
  "phases_needed": ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY", "TEST"],
  "retry_policy": {
    "enabled": true,
    "max_retries": 3,
    "reason": "Can rollback changes if tests fail"
  },
  "verification_strategy": "TEST_DRIVEN",
  "failure_handling": "ROLLBACK_AND_RETRY"
}
```

**Characteristics:**
- ✅ Full flow with testing
- ✅ Retry with rollback
- ✅ Test-driven verification
- Modify → Test → Rollback if failed → Retry

### 4. RESOURCE_CREATION
**Examples:** Create project, install packages, setup environment

**Strategy:**
```json
{
  "execution_type": "RESOURCE_CREATION",
  "phases_needed": ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"],
  "retry_policy": {
    "enabled": true,
    "max_retries": 2,
    "reason": "Can verify creation and retry if missing"
  },
  "verification_strategy": "EXISTENCE_CHECK",
  "failure_handling": "RETRY_IF_MISSING"
}
```

**Characteristics:**
- ✅ Verify files/resources created
- ✅ Retry if creation failed
- ✅ Idempotent operations
- Create → Check exists → Retry if missing

### 5. CONVERSATION
**Examples:** Answer question, explain concept, provide guidance

**Strategy:**
```json
{
  "execution_type": "CONVERSATION",
  "phases_needed": ["RESPOND"],
  "retry_policy": {
    "enabled": false,
    "reason": "No action needed, just response"
  },
  "verification_strategy": "NONE",
  "failure_handling": "N/A"
}
```

**Characteristics:**
- ✅ Just respond, no execution
- ❌ No phases, no verification
- Direct answer

---

## Implementation: Execution Strategy Selector

### Phase 0: STRATEGY (Before TRIAGE)

```python
async def _select_execution_strategy(self, request: str) -> ExecutionStrategy:
    """
    Ask LLM to analyze request and decide execution strategy.

    This replaces the hardcoded phase flow with LLM-driven decisions.
    """

    prompt = f"""Analyze this user request and decide the execution strategy.

USER REQUEST: {request}

Your task: Determine what type of execution this request requires.

EXECUTION TYPES:

1. ONE_SHOT_ACTION - Actions with SIDE EFFECTS that should execute ONCE:
   - Send email, post message, publish content
   - Delete file, drop database, kill process
   - Download file, upload file, transfer data
   - curl POST, API calls that create/modify resources

   KEY: If action has SIDE EFFECTS (changes state outside local system), it's ONE_SHOT!

   Phases needed: ["EXECUTE"]
   Retry: NO (will cause duplicates!)
   Verification: TRUST_EXIT_CODE (exit 0 = success)

2. INVESTIGATIVE_TASK - Read-only information gathering:
   - Check system status, read files, search for info
   - Diagnose issue, analyze logs, inspect config
   - Research, lookup, query (no state changes)

   KEY: Read-only operations safe to retry.

   Phases needed: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"]
   Retry: YES (no side effects)
   Verification: LLM_SEMANTIC (did we get the info?)

3. CODE_MODIFICATION - Modify existing code:
   - Fix bug, add feature, improve code, refactor
   - Change configuration, update dependencies

   KEY: Changes code files, needs testing.

   Phases needed: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY", "TEST"]
   Retry: YES (can rollback)
   Verification: TEST_DRIVEN (run tests)

4. RESOURCE_CREATION - Create new files/resources:
   - Create project, generate files, build artifacts
   - Install packages, setup environment

   KEY: Creates new resources, can verify existence.

   Phases needed: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"]
   Retry: YES (idempotent)
   Verification: EXISTENCE_CHECK (files created?)

5. CONVERSATION - No action, just respond:
   - Answer question, explain concept, provide help

   KEY: No execution needed.

   Phases needed: ["RESPOND"]
   Retry: NO
   Verification: NONE

🚨 CRITICAL - SIDE EFFECTS DETECTION:

Does this request involve ANY of these?
- Sending/transmitting data (email, message, post, publish)
- Deleting/destroying (rm, drop, delete, kill)
- Creating external state (API POST, database INSERT, publish)
- Financial transactions
- User notifications

If YES → ONE_SHOT_ACTION (no retry!)
If NO → Choose based on read/write nature

EXAMPLES:

Request: "Send email to John"
Type: ONE_SHOT_ACTION
Reason: Sending email has side effects, will send multiple times if retried

Request: "Check if nginx is running"
Type: INVESTIGATIVE_TASK
Reason: Read-only status check, safe to retry

Request: "Fix the bug in login.py"
Type: CODE_MODIFICATION
Reason: Modifies code, needs testing

Request: "Create a new Python project"
Type: RESOURCE_CREATION
Reason: Creates files, can verify creation

Request: "What is Docker?"
Type: CONVERSATION
Reason: Just answering a question

Return JSON:
{{
  "execution_type": "ONE_SHOT_ACTION",
  "phases_needed": ["EXECUTE"],
  "retry_policy": {{
    "enabled": false,
    "max_retries": 0,
    "reason": "Side effects - will send email multiple times if retried"
  }},
  "verification_strategy": "TRUST_EXIT_CODE",
  "failure_handling": "REPORT_AND_STOP",
  "reasoning": "User wants to send an email. This is a one-shot action with side effects."
}}

Return ONLY the JSON object."""

    # Call LLM
    response = await self.llm_client.generate(prompt, max_tokens=500)

    # Parse JSON
    data = extract_json_from_llm_response(response.content)

    return ExecutionStrategy(
        execution_type=data['execution_type'],
        phases_needed=data['phases_needed'],
        retry_policy=RetryPolicy(**data['retry_policy']),
        verification_strategy=data['verification_strategy'],
        failure_handling=data['failure_handling'],
        reasoning=data['reasoning']
    )
```

### Execution Based on Strategy

```python
async def handle(self, request: str) -> HandlerResult:
    """Execute request according to LLM-decided strategy."""

    # PHASE 0: STRATEGY - Ask LLM what execution strategy to use
    strategy = await self._select_execution_strategy(request)

    # Execute according to LLM's strategy (NOT hardcoded flow!)
    if strategy.execution_type == "ONE_SHOT_ACTION":
        # Execute once, no retry, trust exit code
        decision = await self._decide_one_shot(request)
        result = await self._act(decision)

        # Trust exit code (no verification phase)
        if result.get('success'):
            return HandlerResult(success=True, output=result['output'])
        else:
            # Failed - report and stop (no retry!)
            return HandlerResult(
                success=False,
                error=f"One-shot action failed: {result['output']}"
            )

    elif strategy.execution_type == "INVESTIGATIVE_TASK":
        # Full flow with retries
        return await self._execute_investigative_task(request, strategy)

    elif strategy.execution_type == "CODE_MODIFICATION":
        # Full flow with testing
        return await self._execute_code_modification(request, strategy)

    elif strategy.execution_type == "RESOURCE_CREATION":
        # Create with verification
        return await self._execute_resource_creation(request, strategy)

    elif strategy.execution_type == "CONVERSATION":
        # Just respond
        response = await self._llm_respond(request)
        return HandlerResult(success=True, output=response)
```

---

## Benefits

### 1. Architectural Compliance ✅
- **LLM decides** execution strategy
- **RAICA executes** according to LLM's decision
- No hardcoded patterns or flows

### 2. Handles Edge Cases Naturally ✅
- LLM understands side effects (email, post, delete)
- LLM chooses appropriate verification
- LLM decides retry policy

### 3. Scalable ✅
- New request types? LLM handles them
- New verification strategies? LLM chooses
- No code changes needed

### 4. Prevents Bugs ✅
- Email sent once (not 3 times!)
- No retries for destructive operations
- Appropriate verification for each type

---

## Migration Plan

### Phase 1: Add Strategy Selection (This Release)
1. Create `ExecutionStrategy` dataclass
2. Add `_select_execution_strategy()` method
3. Update `handle()` to use strategy

### Phase 2: Implement Execution Types (Next Release)
1. Implement `_execute_one_shot_action()`
2. Implement `_execute_investigative_task()`
3. Implement `_execute_code_modification()`
4. Implement `_execute_resource_creation()`

### Phase 3: Remove Hardcoded Flow (Final)
1. Remove old hardcoded TRIAGE → GATHER → DECIDE → ACT → VERIFY
2. All execution driven by LLM strategy
3. Update tests

---

## Testing Strategy

### Test Cases:

**ONE_SHOT_ACTION:**
```python
request = "Send email to John"
strategy = await selector.select_strategy(request)
assert strategy.execution_type == "ONE_SHOT_ACTION"
assert strategy.retry_policy.enabled == False
assert strategy.phases_needed == ["EXECUTE"]
```

**INVESTIGATIVE_TASK:**
```python
request = "Check if nginx is running"
strategy = await selector.select_strategy(request)
assert strategy.execution_type == "INVESTIGATIVE_TASK"
assert strategy.retry_policy.enabled == True
```

**Verify email sent ONCE:**
```python
request = "Send email to test@example.com"
result = await handler.handle(request)
# Check email inbox - should have exactly 1 email
assert email_count == 1  # NOT 3!
```

---

## Success Criteria

- [x] Architecture compliant (LLM decides, RAICA executes)
- [x] No hardcoded phase flows
- [ ] Email sent exactly once (bug fixed)
- [ ] LLM chooses execution strategy
- [ ] Strategy-driven execution implemented
- [ ] Tests pass
- [ ] Documentation updated

---

**Next:** Implement in `universal_handler.py`
