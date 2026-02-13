# Bug Fix: Wrong/Missing Attachment Files in Email Workflows

**Date:** 2026-02-07
**Version:** v1.0.0.37+
**Status:** Investigation Complete - Fix Design Ready

## Problem Summary

When RAICA agent delegates "research and email" workflows to the server:
- Server generates HTML file correctly
- Server sends email with correct attachment
- BUT: Agent doesn't know which file was created
- On retry or follow-up, agent uses fuzzy matching → picks WRONG file

**User observation:**
- Request: "Email latest news as HTML"
- Server creates: `latest_national_news_summary_2026-02-07_13-07.html`
- Server sends email with correct file ✅
- Agent retries (due to old verification bug)
- Agent looks for attachment, finds multiple HTML files in sandbox
- Fuzzy matching picks: `political_news_analysis_2026-02-07_13-14.html` (newer timestamp)
- User receives WRONG file ❌

## Root Causes

### 1. Server Returns Narrative, Not Structured Data

**Current behavior:**
```python
# raica_research_agent returns server response as plain text:
{
  "success": true,
  "result": "## Work Completed Summary\n\n...Email sent successfully...fortune message...",
  "source": "RAICA-Model1"
}
```

**Problem:** Agent cannot extract:
- Files created
- Filenames used
- What was attached to email

### 2. Fuzzy Matching Picks Wrong File

**Location:** `/home/sabawi/Development/RAICA/user_tools/secure_email_sender.py:312`

```python
# When exact filename not provided, fuzzy match looks at ALL files in sandbox:
candidates.sort(key=lambda x: (x[1], x[0].stat().st_mtime), reverse=True)
# Picks file with: highest priority score, then NEWEST timestamp
```

**Sandbox workspace pollution:**
```bash
-rw-rw-r-- political_news_analysis_2026-02-07_13-14.html  (13K) ← NEWEST
-rw-rw-r-- latest_national_news_summary_2026-02-07_13-07.html  (5.9K) ← WANTED
-rw-rw-r-- analysis_report_2026-02-07_11-42.html  (7.3K)
```

If agent looks for "news" + ".html", both files score 80 (contains "news"), so fuzzy match picks newest → WRONG file!

### 3. Agent Has No File Context

When agent asks server to "create report and email it":
1. Server executes full workflow
2. Server creates file with timestamped name
3. Server sends email with that file
4. Agent only sees: "✅ Email sent successfully"
5. Agent has NO IDEA what filename was used

If workflow needs to reference that file later (re-send, check existence, clean up), agent cannot do it.

## Solution Design

### Option 1: Structured Response Format (RECOMMENDED)

**Change:** Make server return structured JSON with metadata

**Server response format:**
```json
{
  "success": true,
  "result": "Research completed and email sent successfully.",
  "metadata": {
    "files_created": [
      {
        "path": "sandbox_workspace/latest_national_news_summary_2026-02-07_13-07.html",
        "type": "html",
        "size_bytes": 6048
      }
    ],
    "email_sent": {
      "to": ["sabawi@gmail.com"],
      "subject": "Latest National News Summary",
      "attachments": ["latest_national_news_summary_2026-02-07_13-07.html"],
      "timestamp": "2026-02-07T13:07:11"
    },
    "tools_used": ["raica_research_agent", "secure_email_sender"]
  }
}
```

**Agent parsing:**
```python
# In raica_research_agent.py or universal_handler.py
if result.get('metadata'):
    files = result['metadata'].get('files_created', [])
    email = result['metadata'].get('email_sent', {})

    # Now agent KNOWS exact filenames to reference
    if files:
        print(f"📄 Files created: {[f['path'] for f in files]}")
    if email and email.get('attachments'):
        print(f"📧 Email sent with attachments: {email['attachments']}")
```

### Option 2: Parse Narrative Text (FRAGILE)

Extract filenames from text using regex:
```python
# ❌ FRAGILE - breaks if narrative format changes
import re
match = re.search(r'created.*?([a-z_]+\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.html)', result, re.I)
if match:
    filename = match.group(1)
```

**Problems:**
- Hardcoded patterns
- Breaks on format changes
- Violates "LLM interprets, not RAICA" principle

### Option 3: Disable Fuzzy Matching (BREAKS USE CASE)

Remove fuzzy matching entirely - require exact filenames:
```python
# ❌ BREAKS legitimate use cases
def _resolve_attachment_path(self, file_path: str):
    path = Path(file_path)
    if path.exists():
        return path
    return None  # No fuzzy matching
```

**Problems:**
- User types "Resume.pdf", file is "resume_2024.pdf" → fails
- Valid use case for fuzzy matching
- Doesn't solve root issue (agent still doesn't know filename)

## Recommended Fix

### Phase 1: Add Structured Response to Server (HIGH PRIORITY)

**File:** Server's response generation (wherever it formats the final response)

**Change:** Return both narrative + structured metadata:
```python
response = {
    "result": llm_narrative_response,  # Keep existing narrative
    "metadata": {
        "files_created": extracted_files,
        "email_sent": extracted_email_info,
        "tools_used": tools_executed
    }
}
```

**How to extract metadata:**
- Server already tracks tool calls
- When `secure_email_sender` is called, capture its args
- When file tools are called, capture filenames
- Bundle into metadata dict

### Phase 2: Agent Extracts and Uses Metadata

**File:** `agents/coding_agent/orchestrator/universal_handler.py`

**Location:** After EXECUTE verification (line ~2250)

**Change:** Parse metadata from tool response:
```python
# After successful tool execution
if decision.tool_name == 'raica_research_agent':
    # Check if result has structured metadata
    if isinstance(act_result.get('output'), dict):
        metadata = act_result['output'].get('metadata', {})

        if metadata:
            # Store files created for potential re-use
            files_created = metadata.get('files_created', [])
            email_info = metadata.get('email_sent', {})

            # Log for debugging
            if files_created:
                logger.info(f"Files created by server: {[f['path'] for f in files_created]}")
            if email_info:
                logger.info(f"Email sent with attachments: {email_info.get('attachments', [])}")

            # TODO: Could store in context for follow-up actions
```

### Phase 3: Improve Fuzzy Matching (LOW PRIORITY)

**File:** `user_tools/secure_email_sender.py:312`

**Change:** Prefer files created recently (within last 5 minutes) over older files:
```python
import time
current_time = time.time()
five_minutes_ago = current_time - 300

# Filter candidates to recent files first
recent_candidates = [(f, score) for f, score in candidates
                     if f.stat().st_mtime > five_minutes_ago]

if recent_candidates:
    candidates = recent_candidates  # Prefer recent files

# Then sort by priority + timestamp
candidates.sort(key=lambda x: (x[1], x[0].stat().st_mtime), reverse=True)
```

**This is a BAND-AID** - doesn't fix root cause, just reduces wrong matches.

## Implementation Priority

1. **CRITICAL:** Add structured metadata to server responses
2. **HIGH:** Update agent to parse and log metadata
3. **MEDIUM:** Store metadata in context for follow-up actions
4. **LOW:** Improve fuzzy matching as safety net

## Test Case

### Before Fix:
```bash
# First request
raica -p "email latest news as HTML to sabawi@gmail.com"
# Creates: latest_national_news_summary_2026-02-07_13-07.html ✅

# Second request (minutes later)
raica -p "email political news analysis as HTML to sabawi@gmail.com"
# Creates: political_news_analysis_2026-02-07_13-14.html ✅

# Third request (retry of first due to old verification bug)
raica -p "email latest news as HTML to sabawi@gmail.com"
# Agent looks for "news*.html"
# Fuzzy match finds BOTH files, picks political_news (newer timestamp)
# User receives WRONG file ❌
```

### After Fix:
```bash
# Same sequence, but:
# Third request:
raica -p "email latest news as HTML to sabawi@gmail.com"
# Server returns: metadata: {"files_created": ["latest_national_news_summary_2026-02-07_13-19.html"]}
# Agent knows exact filename
# No fuzzy matching needed
# User receives CORRECT file ✅
```

## Related Issues

- Verification truncation (FIXED in v1.0.0.37)
- Email IPv6 slowness (FIXED earlier)
- Sandbox workspace cleanup (separate issue)

## Next Steps

1. Identify where server formats responses (likely in main chat completion handler)
2. Add metadata extraction from tool execution history
3. Update response format to include metadata dict
4. Update raica_research_agent to parse metadata
5. Update universal_handler to log/use metadata
6. Test with multi-step email workflow
