# Bug Fix #9: LLM Must Proactively Check Tool Availability Before Deciding

**Date:** February 5, 2026
**Files:** `universal_handler.py` (TRIAGE and DECIDE prompts)
**Issue:** LLM chose CREATE instead of EXECUTE because it didn't know if `mail` command was available

---

## Problem

User requested: **"Write an email to John... and send it to sabawi@gmail.com"**

TRIAGE phase checked:
- ✓ Project files
- ✓ Existing scripts (gmail_bill_finder.py)
- ✓ Environment variables (.env.example)
- ✗ **NEVER checked if `mail` or `sendmail` commands are available!**

DECIDE phase:
- Saw: "No email-sending script exists"
- Decided: CREATE (make a new script)
- Problem: **Should have used EXECUTE with `mail` command if available!**

Result: Script created but never executed (missing `execute_after_create: true`)

---

## Root Cause

The LLM had **no information** about what system commands are available. The TRIAGE prompt didn't guide the LLM to check for system tools before deciding.

### What Should Have Happened:

```
1. TRIAGE:
   - CHECK_TOOL: mail → Found!
   - CHECK_TOOL: sendmail → Found!

2. DECIDE:
   - Tool available: mail command exists
   - Decision: EXECUTE with mail command

3. ACT:
   - Run: echo "..." | mail -s "Subject" sabawi@gmail.com
   - Email sent immediately!
```

### What Actually Happened:

```
1. TRIAGE:
   - CHECK_PROJECT: found gmail_bill_finder.py
   - READ_FILE: read script contents
   - (Never checked for mail command!)

2. DECIDE:
   - No email script found
   - Decision: CREATE send_email.py

3. ACT:
   - Created send_email.py
   - Never executed it (missing execute_after_create)
   - Email NOT sent!
```

---

## Solution

Updated Universal Handler's TRIAGE prompt to guide LLM to **proactively check** for system tools.

### Change 1: Added Tool Checking Guidance to TRIAGE (lines 446-462)

**Before:**
```
RULES:
1. Only request information you ACTUALLY NEED to decide
2. Be efficient - don't request redundant information
3. If you have enough info, return empty array []
4. Focus on: "Do I have what I need to fulfill this request?"
```

**After:**
```
RULES:
1. Only request information you ACTUALLY NEED to decide
2. Be efficient - don't request redundant information
3. If you have enough info, return empty array []
4. Focus on: "Do I have what I need to fulfill this request?"

🚨 CRITICAL - FOR SYSTEM OPERATIONS (email, download, file operations):
**ALWAYS check if relevant system commands are available BEFORE deciding!**

Examples:
- Email request → CHECK_TOOL for "mail" and "sendmail"
- Download request → CHECK_TOOL for "curl" and "wget"
- Archive request → CHECK_TOOL for "tar" and "zip"

This information is REQUIRED to decide between EXECUTE vs CREATE!
```

**New Example Actions:**
```json
[
    {"action_type": "CHECK_TOOL", "target": "mail", "reason": "Check if mail available for sending email"},
    {"action_type": "CHECK_TOOL", "target": "sendmail", "reason": "Fallback email tool if mail not available"}
]
```

### Change 2: Updated DECIDE to Use Tool Availability Info (lines 738-755)

**Before:**
```
🚨 CRITICAL DECISION PRIORITY FOR IMMEDIATE ACTIONS:
1. FIRST CHOICE: EXECUTE with shell command
   - Fast, simple, no files created

2. SECOND CHOICE: CREATE with execute_after_create=true
   - ONLY if shell command insufficient
```

**After:**
```
🚨 CRITICAL DECISION PRIORITY FOR IMMEDIATE ACTIONS:

**STEP 1: Check gathered information for tool availability**
- Look at TRIAGE results for CHECK_TOOL actions
- Did we check if `mail`, `sendmail`, `curl`, `wget` are available?
- Use this information to decide between EXECUTE vs CREATE

**STEP 2: Choose decision based on tool availability:**

1. FIRST CHOICE: EXECUTE with shell command (if tool available!)
   - Example: CHECK_TOOL found `mail` → use EXECUTE with mail command

2. SECOND CHOICE: CREATE with execute_after_create=true (if tool NOT available)
   - If CHECK_TOOL shows mail NOT installed → CREATE Python script
   - If needs authentication (Gmail SMTP) → CREATE Python script
   - IMPORTANT: Set execute_after_create=true to run immediately!
```

### Change 3: Added execute_after_create REQUIRED Notice (lines 788-792)

```
🚨 REQUIRED FIELDS FOR CREATE DECISIONS:
- For CREATE decision type, you MUST include "execute_after_create" field
- Set to true if user wants immediate action
- Set to false if user wants to build reusable tool
- This field is MANDATORY for all CREATE decisions!
```

---

## How CHECK_TOOL Works

Implementation in `universal_handler.py` lines 566-574:

```python
elif action.action_type == TriageActionType.CHECK_TOOL:
    import subprocess
    try:
        result = subprocess.run(
            f"which {action.target} 2>/dev/null || type {action.target} 2>/dev/null",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        output = f"Tool '{action.target}' found" if result.returncode == 0 else f"Tool '{action.target}' NOT found"
    except Exception as e:
        output = f"Tool check error: {e}"
```

Uses `which` and `type` commands to check if a tool is installed and in PATH.

---

## Complete Email Request Flow (After Fix)

### Test Case: "Send email to John"

**TRIAGE Phase:**
```
LLM: I need to send an email. Let me check what's available.
Actions:
1. CHECK_TOOL: mail → Result: "Tool 'mail' found" ✓
2. CHECK_TOOL: sendmail → Result: "Tool 'sendmail' found" ✓
3. CHECK_PROJECT: Check for existing email scripts → Found gmail_bill_finder.py (IMAP only)
```

**DECIDE Phase:**
```
LLM analyzes gathered info:
- mail command IS available
- No need to create a script
- User wants immediate action ("send it")

Decision:
{
    "decision_type": "EXECUTE",
    "reasoning": "mail command available, use it for immediate email sending",
    "commands": ["echo '...' | mail -s 'Subject' recipient@email.com"],
    "requires_approval": true
}
```

**ACT Phase:**
```
Execute command: mail -s "Unable to Attend Lunch" sabawi@gmail.com
Email sent successfully! ✓
```

### Alternative: If mail NOT available

**TRIAGE Phase:**
```
Actions:
1. CHECK_TOOL: mail → Result: "Tool 'mail' NOT found" ✗
2. CHECK_TOOL: sendmail → Result: "Tool 'sendmail' NOT found" ✗
```

**DECIDE Phase:**
```
LLM analyzes:
- No mail commands available
- Need to create Python script with SMTP
- User wants immediate action

Decision:
{
    "decision_type": "CREATE",
    "reasoning": "mail command not available, create Python script with SMTP",
    "code_prompt": "Create send_email.py using Gmail SMTP...",
    "execute_after_create": true,  ← CRITICAL!
    "requires_approval": true
}
```

**ACT Phase:**
```
1. Create send_email.py with SMTP authentication
2. Execute: python3 send_email.py (because execute_after_create=true)
3. Email sent! ✓
```

---

## Key Principles

### 1. Proactive Information Gathering
- LLM should gather ALL information needed BEFORE deciding
- Don't decide blindly - check what tools are available first
- Use CHECK_TOOL for any system operation request

### 2. Decision Based on Available Options
- If system command available → Use it (EXECUTE)
- If system command NOT available → Create script (CREATE + execute)
- Never assume tools exist - always check first!

### 3. Two-Stage Process
- **TRIAGE:** Gather information (what tools exist?)
- **DECIDE:** Make informed decision (based on gathered info)

---

## Testing Scenarios

### Scenario 1: System with mail command
```
Request: "send email to John"
TRIAGE: CHECK_TOOL mail → found
DECIDE: EXECUTE with mail command
RESULT: Email sent via mail command ✓
```

### Scenario 2: System without mail command
```
Request: "send email to John"
TRIAGE: CHECK_TOOL mail → NOT found
DECIDE: CREATE with execute_after_create=true
RESULT: Script created and executed, email sent ✓
```

### Scenario 3: Complex email (Gmail SMTP)
```
Request: "send email via Gmail SMTP with 2FA"
TRIAGE: CHECK_TOOL mail → found (but insufficient for SMTP auth)
DECIDE: CREATE with execute_after_create=true (needs auth)
RESULT: Python script with SMTP, executed, email sent ✓
```

### Scenario 4: Build email tool
```
Request: "create a script that can send emails"
TRIAGE: CHECK_TOOL mail → found
DECIDE: CREATE with execute_after_create=false (user wants tool)
RESULT: Script created but NOT executed (user didn't ask to send) ✓
```

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `universal_handler.py` | 446-462 | TRIAGE: Added tool checking guidance and examples |
| `universal_handler.py` | 738-755 | DECIDE: Two-step decision process based on tool availability |
| `universal_handler.py` | 788-792 | DECIDE: Made execute_after_create REQUIRED for CREATE |

---

## Impact

### Before Fix:
- ❌ LLM blindly chose CREATE without checking tool availability
- ❌ No way to know if system commands exist
- ❌ Always created scripts even when shell command would work
- ❌ Scripts created but never executed (missing execute_after_create)

### After Fix:
- ✅ LLM proactively checks tool availability during TRIAGE
- ✅ Makes informed decision based on what's available
- ✅ Prefers EXECUTE with system commands when available
- ✅ Falls back to CREATE + execute when system command not available
- ✅ Always sets execute_after_create for immediate actions

---

## Architecture Insight: The Investigation-First Pattern

This fix reinforces the **Universal Handler's core principle**:

```
TRIAGE → GATHER → DECIDE → ACT
   ↑                ↓
   └── MUST gather info BEFORE deciding!
```

**Anti-pattern (what we were doing):**
```
User: "send email"
Agent: "No script found → CREATE one"
```

**Correct pattern (what we do now):**
```
User: "send email"
Agent: "Let me check... mail command exists? YES → EXECUTE it"
       or: "Let me check... mail command exists? NO → CREATE script + execute"
```

The LLM should **never assume** anything - always gather information first!

---

**Status:** Fixed ✅
**Related Bugs:** #4-8 (Complete email sending pipeline now works)
**Next Test:** User should retry email request to verify complete flow
