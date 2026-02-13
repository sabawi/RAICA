# Bug Fix #8: Request Classifier Misinterprets Email Actions as Conversation

**Date:** February 5, 2026
**File:** `agents/coding_agent/orchestrator/request_classifier.py`
**Severity:** HIGH - Completely blocks immediate action requests

---

## Problem

User requested: **"Write an email to John... and send it to sabawi@gmail.com"**

Classifier incorrectly classified as: **CONVERSATION (confidence: 95%)**

Result: RAICA drafted email text instead of actually sending the email!

---

## Root Cause

The classification prompt had **no guidance** on distinguishing:

| Request Type | User Says | Should Be Classified As |
|--------------|-----------|------------------------|
| **Draft text only** | "Write an email", "Draft a message" | CONVERSATION |
| **Send email action** | "Write an email... **and send it to...**", "Email John" | SYSTEM_TASK |

The classifier saw "Write an email" and assumed it was a text generation request, completely ignoring the **"send it to sabawi@gmail.com"** action indicator.

### Why This Happened

CONVERSATION definition was too vague (line 235):
```
7. CONVERSATION - General questions, explanations, help WITHOUT code changes
   Examples: "what is Docker?", "explain async/await", "help me understand"
```

No mention of email requests or the distinction between "draft" vs "send".

---

## Solution

Updated `request_classifier.py` with three changes:

### Change 1: Added Email Examples to SYSTEM_TASK (lines 157-177)

**Before:**
```
2. SYSTEM_TASK - User wants to MODIFY/CHANGE/CREATE/DELETE or EXECUTE/RUN
   Examples:
   - File/directory MODIFICATIONS
   - Package management
   - Service control
   KEY: Any operation that CHANGES system state OR RUNS EXISTING SCRIPT
```

**After:**
```
2. SYSTEM_TASK - User wants to MODIFY/CHANGE/CREATE/DELETE or EXECUTE/RUN
   Examples:
   - File/directory MODIFICATIONS
   - Package management
   - Service control
   - SENDING/TRANSMITTING DATA: "send email to...", "email John", "download file from..."
   KEY: Any operation that CHANGES system state OR RUNS SCRIPT OR TRANSMITS/SENDS DATA

   🚨 CRITICAL - EMAIL REQUESTS:
   - "Write an email... and SEND it to..." → SYSTEM_TASK (action: actually send!)
   - "Email John saying..." → SYSTEM_TASK (implied send action)
   - "Send email to X" → SYSTEM_TASK (explicit send action)
   - "Draft an email" WITHOUT "send" → CONVERSATION (just text generation)
```

### Change 2: Clarified CONVERSATION Definition (lines 235-255)

**Before:**
```
7. CONVERSATION - General questions, explanations, help WITHOUT code changes
   Examples: "what is Docker?", "explain async/await", "help me understand"
```

**After:**
```
7. CONVERSATION - General questions, explanations, help, TEXT GENERATION WITHOUT actions
   Examples:
   - Questions: "what is Docker?", "explain async/await"
   - Text generation: "draft an email", "write a message" (WITHOUT sending)
   - Help: "how do I...", "what's the best way to..."

   🚨 CRITICAL DISTINCTION - Text Generation vs Action:
   - "Write an email" / "Draft a message" (NO send) → CONVERSATION (just generate text)
   - "Write an email... and SEND it" / "Email John" → SYSTEM_TASK (action!)

   KEY: If user wants you to GENERATE TEXT ONLY (no execution, no sending, no file creation),
   use CONVERSATION. If user wants text PLUS an ACTION, use appropriate action category.
```

### Change 3: Added Example Outputs (lines 263-287)

Added two contrasting examples:

**Email ACTION (send):**
```json
{
    "primary_type": "SYSTEM_TASK",
    "intent": "Send email to John about lunch cancellation",
    "reasoning": "User wants to SEND email (action). Request includes 'send it to...' which indicates execution."
}
```

**Email TEXT (draft only):**
```json
{
    "primary_type": "CONVERSATION",
    "intent": "Draft email text for user to copy",
    "reasoning": "User wants to DRAFT email text only, no sending action mentioned. Just text generation."
}
```

---

## Key Action Indicators

The classifier now recognizes these as **SYSTEM_TASK** (action) indicators:

### Explicit Send Indicators:
- "send it to..."
- "send email"
- "email X" (implies send)
- "mail this to..."
- "transmit"

### Implicit Send Indicators:
- "Email John saying..." (not "Write an email TO John" but "Email John" - action verb)
- "Notify X via email"
- "Message X about..."

### NOT Action Indicators (CONVERSATION):
- "Draft an email"
- "Write an email for me" (without send context)
- "Help me compose a message"
- "What should I say in an email to..."

---

## Testing

### Test Case 1: Send Email (Action)
**Input:** "Write an email to John... and send it to sabawi@gmail.com"
**Expected:** SYSTEM_TASK (confidence: 0.95)
**Reasoning:** Contains "send it to" - clear action indicator

### Test Case 2: Email Someone (Implied Send)
**Input:** "Email John saying I can't make lunch tomorrow"
**Expected:** SYSTEM_TASK (confidence: 0.95)
**Reasoning:** "Email John" is an action verb (not "Write an email about John")

### Test Case 3: Draft Only (Text Generation)
**Input:** "Draft an email to John about canceling lunch"
**Expected:** CONVERSATION (confidence: 0.90)
**Reasoning:** "Draft" indicates text generation only, no sending

### Test Case 4: Help with Wording (Text Generation)
**Input:** "Help me write an email to decline an invitation"
**Expected:** CONVERSATION (confidence: 0.90)
**Reasoning:** "Help me write" is asking for assistance with text, not action

---

## Impact

### Before Fix:
- ❌ "Send email to X" → Drafted text, never sent
- ❌ "Email John" → Drafted text, never sent
- ❌ Any email action request → Misclassified as CONVERSATION
- ❌ User frustration: "Why isn't RAICA sending my emails?!"

### After Fix:
- ✅ "Send email to X" → Classified as SYSTEM_TASK → Universal Handler → EXECUTE/CREATE decision
- ✅ "Email John" → Classified as SYSTEM_TASK → Actually sends email
- ✅ "Draft email" → Correctly classified as CONVERSATION → Just generates text
- ✅ Clear distinction between action requests and text generation

---

## Related Bugs

This bug is related to Bugs #4-#6 (Universal Handler issues), but occurs **earlier** in the pipeline:

```
Bug #8 (Classifier)          Bugs #4-6 (Universal Handler)
        ↓                              ↓
User Request                   Classified Request
    ↓                              ↓
Request Classifier            Universal Handler
    ↓                              ↓
WRONG: CONVERSATION           DECIDE: EXECUTE vs CREATE
    ↓                              ↓
_handle_conversation()        ACT: Run command/create script
    ↓                              ↓
Draft text only               Actually send email
```

**Order of Operations:**
1. **Bug #8 must be fixed first** - If classifier gets it wrong, request never reaches Universal Handler
2. **Then Bugs #4-6** - Once classified correctly, Universal Handler needs to EXECUTE or CREATE+EXECUTE

---

## Architecture Insight

This bug highlights the **two-stage intent interpretation** in RAICA:

### Stage 1: Request Classifier (THIS BUG)
- **Purpose:** Broad categorization (SYSTEM_TASK vs CONVERSATION vs CODE_GENERATION)
- **Granularity:** Coarse - just routes to the right handler
- **Decision:** "Is this an ACTION request or TEXT GENERATION?"

### Stage 2: Universal Handler (Bugs #4-6)
- **Purpose:** Fine-grained decision (EXECUTE vs CREATE, which command to use)
- **Granularity:** Fine - decides exact execution strategy
- **Decision:** "Should I use mail command, or create Python script with SMTP?"

**Both stages must work correctly** for email actions to succeed!

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `request_classifier.py` | 157-177 | Added email examples to SYSTEM_TASK, critical email request guidance |
| `request_classifier.py` | 235-255 | Clarified CONVERSATION definition, added text-vs-action distinction |
| `request_classifier.py` | 263-287 | Added example outputs for email ACTION and email TEXT |

---

## Rollout Notes

### Backward Compatibility
- **Safe to deploy:** Classification changes only affect how requests are routed
- **No breaking changes:** Existing prompts continue to work
- **Improved accuracy:** Reduces misclassifications

### Monitoring
After deployment, monitor classification decisions for:
- Email requests being classified as SYSTEM_TASK (not CONVERSATION)
- Download/upload requests being classified as SYSTEM_TASK
- Draft/compose requests being classified as CONVERSATION
- Log classification confidence scores for analysis

---

**Status:** Fixed ✅
**Testing:** Pending user verification with email send test
**Related:** Bugs #4-6 (Universal Handler EXECUTE/CREATE logic)
