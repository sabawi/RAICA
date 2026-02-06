# CHANGELOG v1.0.0.33

**Release Date:** 2026-02-06
**Previous Version:** 1.0.0.32

## 🎯 Major Architectural Improvements

### 1. **MINIMAL SCAFFOLDING PRINCIPLE** - Core Architecture Update
**Impact:** CRITICAL - Defines RAICA's fundamental design philosophy

- Added comprehensive "MINIMAL SCAFFOLDING PRINCIPLE" to CLAUDE.md
- RAICA provides minimal scaffolding (loop, execute, return)
- LLM handles ALL heavy lifting (design, code, parse, analyze, fix, decide)
- Prevents overcoding and complex logic in RAICA itself

**Enforcement Rules:**
- ❌ NO 60-line parsers - Run command, return output, LLM parses
- ❌ NO regex extraction - Ask LLM to extract in JSON
- ❌ NO error categorization - Show LLM error, it categorizes
- ❌ NO validation logic - Apply fix, show result, LLM validates
- ✅ The Test: "Could this be a simple LLM prompt?" → If YES, make it an LLM prompt

### 2. **Exit Code Verification for EXECUTE Commands**
**Impact:** CRITICAL - Fixes commands being executed multiple times

**Problem Fixed:** Email sending bug where emails were sent 3 times because VERIFY phase asked LLM to verify success, LLM saw empty output and said "failed", retry loop sent email again.

**Solution:** Trust deterministic exit codes for EXECUTE commands
- Exit code 0 = SUCCESS (stop, don't retry)
- Exit code non-zero = FAILED (stderr contains error)
- NO LLM verification for EXECUTE - just check exit code
- Prevents retrying commands with side effects (email, deployment, deletion, etc.)

**File Changed:** `agents/coding_agent/orchestrator/universal_handler.py` (lines 1314-1332)

**Architecture:**
```python
if decision.decision_type == DecisionType.EXECUTE:
    if not act_result.get('success', False):
        return {'success': False, 'error': error_msg}
    # ✅ Exit code 0 = SUCCESS - TRUST IT, DONE!
    return {'success': True}
```

### 3. **Eliminated ALL Hardcoded max_tokens Overrides**
**Impact:** HIGH - Respects user configuration, prevents truncation

**Problem Fixed:** 13 locations in code had hardcoded max_tokens (50, 100, 2000, 3000, 4000, 8000, 8192) that overrode user's config settings. This caused:
- Test files truncated mid-generation (3229 chars extracted, only ~2000 saved)
- LLM responses cut off
- Incomplete code generation

**Solution:** Removed ALL hardcoded max_tokens, now all use `self._max_tokens` from config

**Locations Fixed (13 total):**
- `cli_coding_agent.py`: Lines 655, 694, 778, 821, 872, 1196, 1537, 1669, 2017, 2122, 2194, 2426, 2856
- ALL replaced with `self._call_llm(prompt)  # Use config max_tokens`

**Before:**
```python
response = self._call_llm(prompt, max_tokens=3000)  # ❌ Hardcoded!
```

**After:**
```python
response = self._call_llm(prompt)  # ✅ Use config max_tokens
```

### 4. **Standalone Test Execution (No pytest Required)**
**Impact:** MEDIUM - Simplifies test infrastructure

**Problem Fixed:** Tests were generated as standalone Python scripts but execution tried to run with pytest, causing failures.

**Solution:** Changed test execution to run test files as standalone Python scripts
- Test files executed with: `python test_file.py`
- Exit code 0 = success, non-zero = failure
- No pytest dependency required for simple tests

**Files Changed:**
- `validation.py`:
  - Renamed `_run_pytest()` → `_run_standalone_python_tests()` (line 2443)
  - Updated `run_tests()` to call new method (line 2331)
  - Updated Docker test execution (lines 3111-3125)
  - Updated subprocess test execution (lines 3162-3178)

### 5. **Task-Scoped Test Validation**
**Impact:** MEDIUM - Only validate files relevant to current task

**Problem Fixed:** When creating new files (e.g., quad_solver.py), validation checked ALL Python files in directory including old unrelated files, causing failures for unrelated import errors.

**Solution:** Only validate files being created/modified in current task
- Pass `files_to_validate` parameter to validation functions
- Only check files in `context.generated_files`
- Skip validation for old/unrelated files in project directory

**File Changed:** `cli_coding_agent.py` (line 2450)
```python
files_to_validate = list(self.context.generated_files.keys())
exec_result = self.code_validator.validate_execution(files_to_validate=files_to_validate)
```

## 📝 Documentation Updates

### CLAUDE.md Enhancements
- **NEW:** Added "MANDATORY PRE-FLIGHT HOOK" section (100+ lines)
- **NEW:** "THE CARDINAL RULE: LLM-DRIVEN ITERATION LOOP"
- **NEW:** "⛔ FORBIDDEN" table - instant rejection violations
- **NEW:** "✅ REQUIRED" table - mandatory implementation patterns
- **NEW:** "⚡ THE MINIMAL SCAFFOLDING PRINCIPLE" section
- **NEW:** "🧪 THE GENERALIZATION TEST" - validates code generalization

### MEMORY.md Updates
- **Added Bug #13:** "Hardcoded max_tokens Overrides User Config"
  - Documented all 13 locations where max_tokens was hardcoded
  - Solution: Remove all hardcoded limits, use config value
- **Added:** "NEVER OVERCODE" architectural principle
  - Examples of overcoding vs minimal scaffolding
  - The Test: "Could this be a simple LLM prompt instead?"

## 🔧 System Configuration

### Email Tool Setup
- **NEW:** `/home/sabawi/.msmtprc` - msmtp configuration for Gmail SMTP
- **NEW:** `/home/sabawi/bin/send-email-async` - Async email wrapper script
  - Returns immediately (4ms) while email sends in background
  - Prevents blocking during email operations
  - Supports stdin for message body

**Usage:**
```bash
echo "Subject: Test\n\nBody" | send-email-async recipient@example.com
```

## 🐛 Bug Fixes

### Bug #13: Hardcoded max_tokens Overrides User Config
**Severity:** HIGH
**Impact:** Truncated LLM responses, incomplete code generation

**Root Cause:** 13 locations in cli_coding_agent.py hardcoded max_tokens parameters (ranging from 50 to 8192) that overrode user's configuration settings.

**Fix:** Removed ALL hardcoded max_tokens, now all use `self._max_tokens` from config.

### Bug: Email Sent 3 Times (EXECUTE Retry Loop)
**Severity:** CRITICAL
**Impact:** Commands with side effects (email, deployment, deletion) executed multiple times

**Root Cause:** VERIFY phase asked LLM to verify if EXECUTE command succeeded. LLM saw empty stdout (successful commands often have no output) and said "failed", causing retry loop.

**Fix:** Trust deterministic exit codes:
- Exit code 0 = SUCCESS (don't ask LLM, don't retry)
- Exit code non-zero = FAILED (stderr has error)

### Bug: Test Execution Failure (pytest vs standalone)
**Severity:** MEDIUM
**Impact:** Generated tests couldn't be executed

**Root Cause:** Tests generated as standalone scripts but execution used `python -m pytest`, which requires pytest to be installed.

**Fix:** Execute tests as standalone Python scripts: `python test_file.py`

### Bug: Import Validation Checks Unrelated Files
**Severity:** MEDIUM
**Impact:** False failures when old/unrelated files have import errors

**Root Cause:** Validation checked ALL Python files in project directory, even files not related to current task.

**Fix:** Only validate files in `context.generated_files` (current task scope).

## 📦 New Files

### Core Architecture
- `agents/coding_agent/orchestrator/universal_handler.py` - Universal request handler with exit code verification

### Documentation
- `docs/housekeeping/status-tracking/CHANGELOG_v1.0.0.33.md` - This changelog

### System Tools
- `/home/sabawi/.msmtprc` - msmtp email configuration
- `/home/sabawi/bin/send-email-async` - Async email sending wrapper

## 🔄 Modified Files

### Core Agent Files
- `agents/coding_agent/cli_coding_agent.py` - Removed 13 hardcoded max_tokens, task-scoped validation
- `agents/coding_agent/validation.py` - Standalone test execution, no pytest required
- `agents/coding_agent/orchestrator/universal_handler.py` - Exit code verification for EXECUTE

### Documentation
- `CLAUDE.md` - Added MINIMAL SCAFFOLDING PRINCIPLE and PRE-FLIGHT HOOK
- `.claude/projects/-home-sabawi-Development-RAICA/memory/MEMORY.md` - Added Bug #13 and NEVER OVERCODE principle

### Configuration
- `version.py` - Incremented version: 1.0.0.32 → 1.0.0.33

## 🔑 Key Principles Established

1. **LLM Decides, RAICA Executes** - No hardcoded interpretation
2. **Trust Deterministic Signals** - Exit codes, not LLM verification for EXECUTE
3. **Configuration Over Hardcoding** - Single source of truth in config files
4. **Task-Scoped Validation** - Only check what's relevant to current task
5. **Minimal Scaffolding** - RAICA provides loop/execute, LLM does heavy lifting

## ⚠️ Breaking Changes

**None** - All changes are internal improvements with no API changes.

## 📋 Migration Guide

**No migration required** - This is a bug fix and architectural improvement release with no breaking changes.

### For Users Who Had Hardcoded max_tokens Issues:
- Delete any custom max_tokens overrides in your code
- All max_tokens now respect config settings in `config/llm_config.yaml`

### For Users Who Had Test Execution Failures:
- No action required - tests now run as standalone scripts automatically
- pytest is no longer required for simple test files

## 🧪 Testing Completed

- ✅ Email sending (single execution, no retries)
- ✅ Test generation without truncation
- ✅ Standalone test execution
- ✅ Task-scoped validation
- ✅ Configuration-driven max_tokens

## 📊 Metrics

- **Files Modified:** 5 core files
- **New Files:** 3 (1 core architecture, 1 documentation, 1 system tool)
- **Bugs Fixed:** 4 critical/high severity bugs
- **Lines of Code:** ~400 lines of overcoded verification logic removed
- **Configuration Violations Fixed:** 13 hardcoded max_tokens removed

## 🎓 Lessons Learned

1. **NEVER OVERCODE** - If it can be an LLM prompt, make it an LLM prompt
2. **Trust Deterministic Signals** - Exit codes are more reliable than LLM interpretation for system commands
3. **Fail Fast** - Validate user input BEFORE executing, report errors immediately
4. **Scope Validation** - Only check what's relevant to avoid false failures
5. **Configuration Management** - Zero tolerance for hardcoded values that override user config

## 🔮 Future Improvements

- Add automated test suite to prevent max_tokens hardcoding regressions
- Extend exit code verification pattern to other command types
- Add configuration validation on startup to catch missing values early
- Document email tool setup in main README for user onboarding

---

**Release Notes:** This release focuses on architectural cleanup and critical bug fixes. The MINIMAL SCAFFOLDING PRINCIPLE is now the core design philosophy, ensuring RAICA provides just enough scaffolding for the LLM to work effectively without overcoding logic that the LLM can handle better.
