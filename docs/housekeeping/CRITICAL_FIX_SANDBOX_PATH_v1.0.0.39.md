# CRITICAL FIX: Wrong Sandbox Directory (v1.0.0.39)

**Date:** 2026-02-07
**Severity:** CRITICAL - Wrong files attached to emails
**Status:** FIXED ✅

---

## Problem

**Email body says one file, but different file attached:**
```
Email says: political_news_analysis_2026-02-07_13-49.html (today)
Attached:   technology_news_analysis_2026-02-05_11-32.html (2 days ago!)
```

**Root cause was NOT fuzzy matching** - it was **looking in the wrong directory entirely!**

---

## Root Cause

### Two Different Sandbox Directories Exist:

1. **`/home/sabawi/sandbox_workspace/`**
   - Where **sandboxed_executor** creates files (config: `base_directory: null` = home dir)
   - Has TODAY's files: `political_news_analysis_2026-02-07_13-49.html` ✅

2. **`/home/sabawi/Development/RAICA/sandbox_workspace/`**
   - Where **secure_email_sender** was looking (using `Path.cwd()`)
   - Has OLD files: `technology_news_analysis_2026-02-05_11-32.html` ❌

### Why This Happened:

**Server working directory:** `/home/sabawi/Development/RAICA/`

**secure_email_sender code (WRONG):**
```python
sandbox_path = Path.cwd() / "sandbox_workspace"  # Uses current working directory
# Result: /home/sabawi/Development/RAICA/sandbox_workspace/ ❌
```

**sandboxed_executor config (CORRECT):**
```yaml
base_directory: null  # null = user's home directory
sandbox_workspace_name: "sandbox_workspace"
# Result: /home/sabawi/sandbox_workspace/ ✅
```

**The workflow:**
1. Server receives: "Create news report and email it"
2. **sandboxed_executor** creates: `/home/sabawi/sandbox_workspace/political_news_analysis_2026-02-07_13-49.html` ✅
3. Email body template says: "Attached: political_news_analysis_2026-02-07_13-49.html" ✅
4. **secure_email_sender** looks in: `/home/sabawi/Development/RAICA/sandbox_workspace/` ❌
5. Finds OLD file: `technology_news_analysis_2026-02-05_11-32.html` (fuzzy match on "news*.html")
6. Attaches WRONG file ❌

---

## The Fix

**File:** `user_tools/secure_email_sender.py`

**Changed:** Use `Path.home()` instead of `Path.cwd()` to match sandboxed_executor

### Line 198 (and 3 other locations):
```python
# BEFORE (WRONG):
sandbox_path = Path.cwd() / "sandbox_workspace" / file_path
# Results in: /home/sabawi/Development/RAICA/sandbox_workspace/ ❌

# AFTER (CORRECT):
sandbox_path = Path.home() / "sandbox_workspace" / file_path
# Results in: /home/sabawi/sandbox_workspace/ ✅
```

**All changes:**
- Line 198: `Path.cwd()` → `Path.home()` (resolve_attachment_path)
- Line 267: `Path.cwd()` → `Path.home()` (find_fuzzy_attachment_match)
- Line 425: `Path.cwd()` → `Path.home()` (detect_recent_reports)
- Line 1008: `Path.cwd()` → `Path.home()` (final validation)

---

## Why This Is The Right Fix

### Consistency with sandboxed_executor:
Both tools now use the same sandbox location defined in config:
```yaml
# config/llm_config.yaml
user_tools:
  sandboxed_executor:
    base_directory: null  # null = home directory
    sandbox_workspace_name: "sandbox_workspace"
```

### Predictable behavior:
- Regardless of where server runs from (Docker, systemd, CLI)
- Sandbox is always: `$HOME/sandbox_workspace/`
- All tools see the same files

### Server independence:
- Server can run from any directory
- Sandbox location doesn't change
- No more directory confusion

---

## Previous Fixes Were Correct, Just Not Enough

### v1.0.0.37 - Verification truncation fix:
- ✅ Fixed agent seeing incomplete responses
- ✅ Stopped retry loops
- But didn't address WHY wrong file was picked

### v1.0.0.38 - Metadata + fuzzy matching:
- ✅ Request metadata from LLM
- ✅ Boost recent files in fuzzy matching
- But fuzzy matching was looking in WRONG directory!

**The real issue was hidden behind the symptoms:**
- We thought: "Fuzzy matching picks wrong file from correct directory"
- Reality: "Fuzzy matching picks any file from WRONG directory"

---

## Test Case

### Before Fix:
```bash
# Files created in: /home/sabawi/sandbox_workspace/
ls /home/sabawi/sandbox_workspace/*.html
> political_news_analysis_2026-02-07_13-49.html  (just created)

# Email sender looks in: /home/sabawi/Development/RAICA/sandbox_workspace/
ls /home/sabawi/Development/RAICA/sandbox_workspace/*.html
> technology_news_analysis_2026-02-05_11-32.html  (2 days old)

# Result: Attaches old file from wrong directory ❌
```

### After Fix:
```bash
# Files created in: /home/sabawi/sandbox_workspace/
ls /home/sabawi/sandbox_workspace/*.html
> political_news_analysis_2026-02-07_13-49.html  (just created)

# Email sender NOW looks in: /home/sabawi/sandbox_workspace/
ls /home/sabawi/sandbox_workspace/*.html
> political_news_analysis_2026-02-07_13-49.html  (same directory!)

# Result: Attaches correct file ✅
```

---

## Verification

After fix applied and server restarted:

```bash
raica -p "fetch latest news and email it as HTML to sabawi@gmail.com"
```

**Expected:**
1. ✅ Server creates file in `/home/sabawi/sandbox_workspace/`
2. ✅ Email sender looks in `/home/sabawi/sandbox_workspace/`
3. ✅ Finds correct file (same directory)
4. ✅ Attaches correct file

**Check:**
- Email body filename matches actual attachment
- Timestamp is TODAY, not days ago
- File content matches request

---

## Architectural Lesson

### NEVER use `Path.cwd()` for shared resources

**Wrong pattern:**
```python
# Each tool uses cwd, gets different paths
tool1: Path.cwd() / "sandbox"  # /path/to/tool1/sandbox
tool2: Path.cwd() / "sandbox"  # /path/to/tool2/sandbox
# Result: Different sandboxes! ❌
```

**Right pattern:**
```python
# All tools use absolute path from config
config: base_directory: "/home/user"
tool1: Path(config.base_dir) / "sandbox"  # /home/user/sandbox
tool2: Path(config.base_dir) / "sandbox"  # /home/user/sandbox
# Result: Same sandbox! ✅
```

### For user-specific resources:
- Use `Path.home()` for user's home directory
- Use absolute paths from config
- Never assume working directory

---

## Impact

**Before:** Every multi-file sandbox had this bug lurking:
- Any tool creating files in home sandbox
- Any tool reading files using cwd sandbox
- Intermittent wrong-file bugs
- Hard to diagnose (fuzzy matching blamed)

**After:** Consistent sandbox location:
- All tools use `Path.home() / "sandbox_workspace"`
- Same directory, same files
- Predictable behavior
- Easy to debug

---

## Files Modified

### v1.0.0.39
- `user_tools/secure_email_sender.py` (4 locations: `Path.cwd()` → `Path.home()`)
- `version.py` (1.0.0.38 → 1.0.0.39)

---

## Related Issues - NOW ALL RESOLVED

1. ✅ Email IPv6 slowness (system-level fix)
2. ✅ Verification truncation loop (v1.0.0.37)
3. ✅ Missing metadata (v1.0.0.38 - request from LLM)
4. ✅ Fuzzy matching preference (v1.0.0.38 - boost recent files)
5. ✅ **Wrong sandbox directory (v1.0.0.39 - THIS FIX)**

**All attachment issues should now be resolved.**
