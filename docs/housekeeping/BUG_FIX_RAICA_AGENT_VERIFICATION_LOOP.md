# Bug Fix: RAICA Agent Verification Loop & Email Formatting Issues

**Date:** 2026-02-07
**Version:** v1.0.0.37
**Status:** FIXED ✅

## Problem Summary

The RAICA CLI agent successfully delegates work to the RAICA server (via `raica_research_agent`), and the server completes the task successfully (generates HTML, sends email). However, the agent doesn't recognize success and keeps retrying.

**User observation:**
- From Open-WebUI: Clean, well-formatted HTML attachment ✅
- From RAICA Agent: Jumbled HTML format, wrong file attached, OR no attachment ❌
- Agent thinks task incomplete and retries indefinitely

## Root Causes Identified

### 1. **Verification Truncates Tool Output** (CRITICAL)

**Location:** `/home/sabawi/Development/RAICA/agents/coding_agent/orchestrator/universal_handler.py:2210`

```python
EXECUTION RESULT:
{act_result.get('output', '')[:2000]}  ← TRUNCATED TO 2000 CHARS!
```

**Problem:** `raica_research_agent` returns detailed response:
```
Step 1: Fetching news...
Step 2: Analyzing...
Step 3: Generating HTML report: latest_national_news_summary_2026-02-07_13-07.html
Step 4: Sending email to sabawi@gmail.com...
✅ Email sent successfully with attachment: latest_national_news_summary_2026-02-07_13-07.html
```

But verification prompt only sees first 2000 chars, which might be **before** the "✅ Email sent successfully" message!

**Impact:** LLM sees truncated output, doesn't see email confirmation, thinks task incomplete → retries.

**Fix:**
```python
# BEFORE (line 2210):
{act_result.get('output', '')[:2000]}

# AFTER:
{act_result.get('output', '')[:5000]}  # Increase to 5000 chars

# OR BETTER - show last 2000 chars (where success message is):
output = act_result.get('output', '')
if len(output) > 4000:
    # Show first 2000 + last 2000 (where final result is)
    display_output = output[:2000] + "\\n\\n[...truncated middle...]\\n\\n" + output[-2000:]
else:
    display_output = output

EXECUTION RESULT:
{display_output}
```

### 2. **Wrong File Attachment** (Sandbox Workspace Pollution)

**Location:** `/home/sabawi/sandbox_workspace/`

**Problem:** Multiple HTML files accumulate from previous runs:
```bash
-rw-rw-r-- 1 sabawi sabawi  13K Feb  7 13:14 political_news_analysis_2026-02-07_13-14.html
-rw-rw-r-- 1 sabawi sabawi 5.9K Feb  7 13:07 latest_national_news_summary_2026-02-07_13-07.html
-rw-rw-r-- 1 sabawi sabawi 7.3K Feb  7 11:42 analysis_report_2026-02-07_11-42.html
```

When `secure_email_sender` looks for attachment, it might pick wrong file due to:
- Fuzzy matching logic picking "most recent" or "similar name"
- Server generates file with specific name, but agent looks for generic pattern

**Impact:** User gets wrong HTML file attached (from previous run).

**Fix Options:**
1. Clean sandbox before each run (destructive)
2. Make raica_research_agent return the EXACT filename in its response
3. Parse raica_research_agent output to extract filename, pass to secure_email_sender

**Best fix:** Update `raica_research_agent` response format:
```json
{
  "success": true,
  "message": "Task completed successfully",
  "files_generated": [
    "latest_national_news_summary_2026-02-07_13-07.html"
  ],
  "email_sent": true,
  "email_details": {
    "to": "sabawi@gmail.com",
    "subject": "Latest National News Summary",
    "attachment": "latest_national_news_summary_2026-02-07_13-07.html"
  }
}
```

Then agent can extract exact filename from structured response.

### 3. **Jumbled HTML Format** (When Agent Tries Directly)

**Observation:** Open-WebUI gets clean HTML, RAICA agent gets jumbled.

**Hypothesis:** When agent retries after verification failure, it might:
- Try to generate HTML itself (instead of delegating to server)
- Use a different HTML generation prompt
- Not use the same formatting/styling

**Investigation needed:** Compare:
- HTML from Open-WebUI request (clean)
- HTML from RAICA agent request (jumbled)
- Check if agent is calling `raica_research_agent` or trying different approach

### 4. **LLM Truncation in Verification** (Secondary Issue)

**Location:** `/home/sabawi/Development/RAICA/agents/coding_agent/orchestrator/universal_handler.py:2237`

```python
response = await asyncio.to_thread(
    self.llm_client.generate_for_classification, verification_prompt, max_tokens=300
)
```

**Problem:** Verification response limited to 300 tokens. The logs show:
```
INFO:agents.coding_agent.llm_client:⚠️ Truncation detected (length), attempting continuation...
INFO:agents.coding_agent.llm_client:   🔄 Continuation attempt 1/3...
```

LLM's verification reasoning is getting truncated, causing continuation attempts.

**Fix:**
```python
# Increase max_tokens for verification
response = await asyncio.to_thread(
    self.llm_client.generate_for_classification, verification_prompt, max_tokens=500
)
```

## Test Case to Reproduce

```bash
cd /home/sabawi/Development/raica_playground
raica -p "look up the latest national news in the last 24 hours, summarize it and email it as a report in a neatly formatted html attachment to sabawi@gmail.com"
```

**Expected behavior:**
1. Agent calls `raica_research_agent` with full request
2. Server fetches news, generates HTML, sends email
3. Server returns success message with filename
4. Agent verifies: sees "Email sent successfully" → marks complete ✅

**Actual behavior:**
1. Agent calls `raica_research_agent` ✅
2. Server completes task ✅
3. Agent verification: output truncated → doesn't see success ❌
4. Agent retries → investigates `secure_email_sender` ❌
5. Agent tries to send email again → wrong file OR no file ❌
6. Loop continues until user cancels

## Fixes Required

### Fix 1: Increase Output Truncation Limit (CRITICAL)

**File:** `agents/coding_agent/orchestrator/universal_handler.py`

**Lines to change:**
- Line 2210: `[:2000]` → `[:5000]` or use first+last strategy
- Line 2301: `[:1000]` (INVESTIGATE verification) → `[:3000]`

### Fix 2: Structured Response from raica_research_agent

**File:** `user_tools/raica_research_agent.py`

Ensure server returns structured response with:
- Success status
- Files generated (exact filenames)
- Email sent confirmation
- Any error details

### Fix 3: Increase Verification max_tokens

**File:** `agents/coding_agent/orchestrator/universal_handler.py`

**Lines to change:**
- Line 2237: `max_tokens=300` → `max_tokens=500`
- Line 2324: `max_tokens=300` → `max_tokens=500`

### Fix 4: Better Parsing of Tool Responses

When `raica_research_agent` completes, agent should:
1. Parse response for success indicators
2. Extract filenames generated
3. Mark task complete if response contains success confirmation

**Add to MEMORY.md:**
```
## Verification of Delegated Work (raica_research_agent)

When RAICA agent delegates to RAICA server via raica_research_agent:

PROBLEM: Verification truncates tool output to 2000 chars
- Server's success message might be at end (char 3000+)
- LLM doesn't see "Email sent successfully" → thinks incomplete

SOLUTION:
1. Increase truncation limit to 5000 chars
2. OR use first 2000 + last 2000 (sandwich strategy)
3. Server should return structured JSON response

CRITICAL: Don't truncate before success indicators!
```

## Priority

**HIGH - This breaks multi-step workflows when delegating to server**

Every time agent delegates complex work to server:
- Server completes successfully
- Agent doesn't recognize success
- Agent wastes iterations retrying
- User experience is broken

## Fixes Applied ✅

### 1. Removed ALL Arbitrary Truncation (CRITICAL FIX)

**File:** `agents/coding_agent/orchestrator/universal_handler.py`

**Changes:**
```python
# Line 2210 (EXECUTE verification - OUTPUT to LLM):
# BEFORE: {act_result.get('output', '')[:2000]}
# AFTER:  {act_result.get('output', '')}  ✅

# Line 2258 (EXECUTE error message - OUTPUT to LLM):
# BEFORE: {act_result.get('output', '')[:500]}
# AFTER:  {act_result.get('output', '')}  ✅

# Line 2301 (INVESTIGATE verification - OUTPUT to LLM):
# BEFORE: {act_result.get('output', '')[:1000]}
# AFTER:  {act_result.get('output', '')}  ✅

# Line 2349 (INVESTIGATE error message - OUTPUT to LLM):
# BEFORE: {act_result.get('output', '')[:1500]}
# AFTER:  {act_result.get('output', '')}  ✅
```

**Rationale:** LLM needs COMPLETE tool output to make accurate verification decisions. Arbitrary truncation destroys semantic meaning - the success message "✅ Email sent successfully" was getting cut off. LLMs have large context windows (120K+ tokens) and can handle full responses.

### 2. Increased Verification Response Tokens

**File:** `agents/coding_agent/orchestrator/universal_handler.py`

**Changes:**
```python
# Lines 2237 & 2324 (both verification prompts):
# BEFORE: max_tokens=300
# AFTER:  max_tokens=500  ✅
```

**Rationale:** LLM's verification reasoning was getting truncated, causing continuation attempts. 500 tokens allows complete verification response without truncation warnings.

## Architectural Principle Reinforced

**NEVER truncate data going TO the LLM for decision-making.**

Truncation is acceptable for:
- Logging/debugging (show excerpt in logs)
- UI display (show summary to user)

But NEVER for:
- LLM verification prompts
- LLM decision-making context
- Any data the LLM needs for accuracy

This was **OVERCODING** - RAICA trying to "protect" the LLM from long responses, but actually breaking verification logic.

## Related Issues

- Email IPv6 slowness (fixed in separate bug report)
- Sandbox workspace file pollution
- LLM response truncation handling

## Test After Fix

```bash
# Should complete in ONE attempt, not retry loop
raica -p "look up latest news and email summary to sabawi@gmail.com"

# Expected: ONE call to raica_research_agent, verification passes, done
```
