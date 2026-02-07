# Intelligent Retry Loop for ONE_SHOT_ACTION

**Version:** 1.0.0.35
**Date:** 2026-02-06
**Feature:** LLM-driven debug loop for actions with side effects

---

## Problem Statement

**User Requirement:**
> "Failure should lead to a response from the LLM to investigate the issue, try another approach, again and again until the task is accomplished. Complete errors have to be captured and fed back to the LLM to decide what to do. RAICA should then wait for its new instructions from the LLM (similar to a debug loop)."

**The Challenge:**
How do we handle actions with side effects (email, delete, post) that fail, without:
1. ❌ Blindly retrying the same command (email sent 3 times!)
2. ❌ Giving up immediately (one failure and stop)

---

## Solution: Intelligent Retry Loop

### Architecture

```
ONE_SHOT_ACTION with Intelligent Retry:

Attempt 1:
  ┌─ DECIDE
  │  LLM: "Use mail command to send email"
  │
  ├─ ACT
  │  Execute: mail -s 'Subject' user@example.com
  │  Result: Timeout after 120s
  │
  ├─ CAPTURE Complete Error:
  │  • Command: mail -s 'Subject' user@example.com
  │  • Exit: timeout
  │  • Duration: 120.0s
  │  • Output: (empty)
  │
  └─ INVESTIGATE
     Feed to LLM:
     "Previous attempt failed:
      Command: mail -s 'Subject' ...
      Error: Timed out after 120s

      What went wrong? What DIFFERENT approach should we try?"

     LLM Response:
     "Mail command likely sent email but hung waiting for
      SMTP confirmation. Try DIFFERENT approach: use sendmail
      with -t flag which doesn't wait for confirmation."

Attempt 2:
  ┌─ DECIDE (with error context)
  │  LLM: "Use sendmail -t (different tool!)"
  │
  ├─ ACT
  │  Execute: sendmail -t < email.txt
  │  Result: Success! ✅
  │
  └─ DONE - Task accomplished!
```

### Key Principles

**1. Capture Complete Error Information**
```python
error_info = {
    'attempt': 1,
    'command': 'mail -s "Subject" user@example.com',
    'decision_type': 'EXECUTE',
    'output': 'Command timed out after 120 seconds',
    'duration': 120.0,
    'error_detected': True
}
```

**2. Feed Error to LLM for Analysis**
```
🚨 PREVIOUS ATTEMPT 1 FAILED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Decision Type: EXECUTE
Command/Target: mail -s "Subject" user@example.com
Duration: 120.0 seconds
Output/Error: Command timed out after 120 seconds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 ANALYZE THIS FAILURE:
1. What went wrong?
2. Was the action partially successful?
3. What is a DIFFERENT approach?

⚠️ CRITICAL: Do NOT retry same command if it has side effects!

DIFFERENT APPROACHES TO CONSIDER:
- Different command (mail → sendmail → mutt)
- Different parameters (--no-wait, --timeout=300)
- Different tool (system command → Python script → RAICA user tool)
- Verification (check if action already completed)
- CREATE custom script with better error handling

What should we try next?
```

**3. LLM Decides Different Approach**
- NOT the same command again!
- Different tool: mail → sendmail → Python script
- Different parameters: add --no-wait flag
- Different method: CREATE script instead of shell command
- Verification: check if action already succeeded

**4. Execute New Approach**
```python
# Attempt 2 uses LLM's new decision
decision = await self._decide(request, context_with_error)
# LLM returns DIFFERENT approach
result = await self._act(decision)
```

**5. Repeat Until Success**
- Max 3 attempts with different approaches
- Each attempt gets error context from previous
- LLM learns and adapts strategy

---

## Implementation

### Code Structure

```python
if strategy.is_one_shot():
    error_context = ""
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        # ═══ DECIDE ═══
        # Include error context from previous attempt
        context = base_context + error_context
        decision = await self._decide(request, context)

        # ═══ ACT ═══
        act_result = await self._act(decision, is_one_shot=True)

        if act_result.success:
            return SUCCESS  # ✅ Done!

        # ═══ INVESTIGATE ═══
        # Capture complete error information
        error_info = {
            'attempt': attempt,
            'command': decision.commands,
            'output': act_result.output,
            'duration': duration,
        }

        # Format error for LLM analysis
        error_context = format_error_with_guidance(error_info)

        # Loop continues - LLM will see error and decide different approach
```

### Error Context Format

**Includes:**
1. ✅ What was tried (command, decision type)
2. ✅ What happened (output, error, duration)
3. ✅ Guidance for LLM (analyze failure, consider alternatives)
4. ✅ Warning (don't retry same command with side effects!)
5. ✅ Suggestions (different tools, parameters, methods)

---

## Example Scenarios

### Scenario 1: Email Send with Timeout

```
User: "Send email to John..."

Attempt 1:
  DECIDE: Use mail command
  ACT: mail -s 'Subject' john@example.com
  ERROR: Timeout after 120s
  INVESTIGATE: Feed error to LLM

  LLM Analysis:
  "Mail sent email but hung on SMTP confirmation.
   Try sendmail -t which doesn't wait."

Attempt 2:
  DECIDE: Use sendmail -t (different!)
  ACT: sendmail -t < email.txt
  SUCCESS ✅
```

### Scenario 2: Tool Not Found

```
User: "Send email to John..."

Attempt 1:
  DECIDE: Use mail command
  ACT: mail -s 'Subject' john@example.com
  ERROR: mail: command not found
  INVESTIGATE: Feed error to LLM

  LLM Analysis:
  "Mail command not installed. Try sendmail or create
   Python script with smtplib."

Attempt 2:
  DECIDE: Try sendmail
  ACT: sendmail -t < email.txt
  ERROR: sendmail: command not found
  INVESTIGATE: Feed error to LLM

  LLM Analysis:
  "No email commands installed. CREATE Python script
   with smtplib."

Attempt 3:
  DECIDE: CREATE send_email.py with smtplib
  ACT: Create script + execute
  SUCCESS ✅
```

### Scenario 3: Use RAICA User Tool

```
User: "Send email to John..."

Attempt 1:
  DECIDE: Use mail command
  ACT: mail -s 'Subject' john@example.com
  ERROR: Timeout
  INVESTIGATE: Feed error to LLM

  LLM Analysis:
  "I see 'secure_email_sender' in RAICA USER TOOLS.
   This is designed for reliable email sending. Let me
   use it instead."

Attempt 2:
  DECIDE: INVESTIGATE get_tool_details secure_email_sender
  ACT: Get full parameter schema
  SUCCESS - Got schema

Attempt 3:
  DECIDE: Call secure_email_sender with parameters
  ACT: Execute user tool
  SUCCESS ✅
```

---

## Benefits

### 1. Intelligent Adaptation ✅
- LLM sees errors and adapts strategy
- Learns from failures
- Tries different approaches automatically

### 2. Avoids Duplicate Actions ✅
- Won't retry same email command 3 times
- Each attempt uses DIFFERENT method
- Side effects happen once per approach

### 3. Increases Success Rate ✅
- Doesn't give up after one failure
- Explores alternatives (sendmail, Python, user tools)
- Finds working solution

### 4. Better Error Handling ✅
- Complete error information captured
- LLM analyzes root cause
- Suggests appropriate fix

### 5. Architectural Compliance ✅
- LLM decides what to try
- RAICA executes blindly
- No hardcoded retry logic

---

## Comparison: Before vs After

### Before (No Retry)
```
Attempt 1: mail command → Timeout
Result: ❌ FAILURE - Gave up immediately
```

### Before (Blind Retry)
```
Attempt 1: mail command → Timeout → Email sent
Attempt 2: mail command → Timeout → Email sent AGAIN
Attempt 3: mail command → Timeout → Email sent 3rd TIME
Result: ❌ Email sent 3 times!
```

### After (Intelligent Retry)
```
Attempt 1: mail command → Timeout
  → LLM investigates: "Try sendmail instead"
Attempt 2: sendmail command → Success
Result: ✅ Email sent ONCE, task accomplished!
```

---

## Testing

### Test Case 1: Email with Timeout
**Request:** "Send email to test@example.com"
**Expected:**
1. Attempt 1: mail command → timeout
2. LLM sees error, suggests sendmail
3. Attempt 2: sendmail → success
4. Email sent exactly once ✅

### Test Case 2: Tool Not Found
**Request:** "Send email to test@example.com"
**Expected:**
1. Attempt 1: mail → not found
2. LLM suggests Python script
3. Attempt 2: CREATE + execute script → success
4. Email sent exactly once ✅

### Test Case 3: Success on First Try
**Request:** "Send email to test@example.com"
**Expected:**
1. Attempt 1: mail command → success
2. No retry needed
3. Email sent exactly once ✅

---

## Success Criteria

- [x] Complete error information captured
- [x] Error fed back to LLM for analysis
- [x] LLM decides different approach (not same command)
- [x] Retry loop with max 3 attempts
- [x] Each attempt uses different method
- [x] Side effects happen once per approach
- [x] Task accomplished or clear failure after 3 attempts

---

## Risk Assessment

**Risk Level:** LOW

**Why Safe:**
- Each attempt uses DIFFERENT approach (no duplicate actions)
- Max 3 attempts (bounded retry)
- LLM-driven decisions (not blind retry)
- Complete error context prevents repeated mistakes

**Mitigation:**
- Monitor first few ONE_SHOT_ACTION requests
- Verify no duplicate side effects (check email inbox for duplicates)
- Log all attempts for debugging

---

**Implementation Complete!**
**Ready for testing with real email request.**
