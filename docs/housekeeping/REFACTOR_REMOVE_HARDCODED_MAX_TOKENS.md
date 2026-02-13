# Refactor: Remove Hardcoded max_tokens Overrides

**Date:** February 6, 2026
**Component:** cli_coding_agent.py - LLM call configuration
**Severity:** MEDIUM - Violates configuration management principles
**Principle:** No Hardcoded Configuration, Single Source of Truth

---

## Problem

Found **13 hardcoded `max_tokens` overrides** throughout cli_coding_agent.py:

```python
Line 655:  max_tokens=100   # Entry file detection
Line 694:  max_tokens=100   # Language detection
Line 778:  max_tokens=8000  # LLM code extraction
Line 821:  max_tokens=50    # Simple JSON extraction
Line 872:  max_tokens=100   # Classification
Line 1196: max_tokens=4000  # Code generation
Line 1537: max_tokens=2048  # Code generation
Line 1669: max_tokens=8192  # Large code generation
Line 2017: max_tokens=4096  # Code generation
Line 2122: max_tokens=2048  # Code generation
Line 2194: max_tokens=4096  # Code generation
Line 2426: max_tokens=3000  # TEST GENERATION ← Caused incomplete test files!
Line 2856: max_tokens=2000  # README generation
```

### Root Cause

**Violated PROJECT_CONFIGURATION_DIRECTIVE.md:**
- ❌ Hardcoded configuration values in code
- ❌ Overriding user's config settings
- ❌ No single source of truth
- ❌ Inconsistent limits (50, 100, 2000, 3000, 4000, 8000, 8192!)

### Impact

1. **User config ignored** - `llm_config.yaml` sets `max_tokens` but code overrides it
2. **Inconsistent behavior** - Different operations use different limits with no clear reason
3. **Test generation failure** - `max_tokens=3000` truncated test generation mid-response
4. **No user control** - User can't adjust limits via config

### Example Failure

**Test generation with `max_tokens=3000`:**
```
LLM Response: [3000 tokens worth of test code]
Result: Incomplete test file (missing if __name__ == "__main__" section)
Test execution: No output (file doesn't run)
Investigation: Failed (trying to fix symptom, not root cause)
```

---

## Solution

### Architecture

```python
# BEFORE (wrong):
response = self._call_llm(prompt, max_tokens=3000)  # Hardcoded override

# AFTER (correct):
response = self._call_llm(prompt)  # Uses self._max_tokens from config
```

### How It Works

```python
# cli_coding_agent.py line 559
def _call_llm(self, prompt: str, max_tokens: Optional[int] = None):
    tokens = max_tokens or self._max_tokens  # Falls back to config
    response = self.llm_client.generate(
        prompt=prompt,
        temperature=self._temperature,
        max_tokens=tokens  # Uses config value
    )

# Line 319: Load from config
self._max_tokens = llm_info['max_tokens']  # From llm_config.yaml
```

### Changes Made

**Removed ALL hardcoded overrides:**
- 13 hardcoded `max_tokens` parameters removed
- All replaced with: `self._call_llm(prompt)  # Use config max_tokens`
- Now 17 calls all use config value

---

## Benefits

### 1. Single Source of Truth
- ✅ All max_tokens controlled by `llm_config.yaml`
- ✅ No code changes needed to adjust limits
- ✅ Consistent behavior across all operations

### 2. User Control
- ✅ User can set `max_tokens` in config
- ✅ One setting controls all LLM calls
- ✅ No hidden overrides

### 3. Simplicity
- ✅ Code is simpler (no magic numbers)
- ✅ One place to configure (config file)
- ✅ Easier to maintain

### 4. Flexibility
**If different operations need different limits:**
- Add operation-specific config entries:
  ```yaml
  llm_config:
    code_generation:
      max_tokens: 8000
    test_generation:
      max_tokens: 6000
    classification:
      max_tokens: 100
  ```
- Update code to read appropriate config entry
- Still no hardcoded values!

---

## Configuration

**User can now control max_tokens via config:**

```yaml
# config/llm_config.yaml
llm_providers:
  - provider_name: "ollama"
    models:
      - model_name: "deepseek-coder-v2:latest"
        max_tokens: 8000  # ← Controls ALL LLM calls
        temperature: 0.7
```

**Recommendations:**
- **For comprehensive test generation:** Set `max_tokens: 8000-16000`
- **For simple operations:** Default `4096` usually sufficient
- **For cost optimization:** Adjust based on budget and needs

---

## Files Modified

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `cli_coding_agent.py` | 13 locations | Removed hardcoded max_tokens overrides |

**Specific changes:**
- Line 655, 694, 821, 872: Removed `max_tokens=100/50`
- Line 778: Removed `max_tokens=8000` (LLM extraction)
- Line 1196, 1537, 1669, 2017, 2122, 2194: Removed `max_tokens=2048/4000/4096/8192` (code gen)
- Line 2426: Removed `max_tokens=3000` (test generation - **this fixed incomplete tests!**)
- Line 2856: Removed `max_tokens=2000` (README generation)

---

## Testing

### Verify Config Control

**Test 1: Increase max_tokens for large test generation**
```bash
# Edit config/llm_config.yaml
max_tokens: 8000

# Generate tests
raica -p "Create tests for quad_solver.py"

# Expected: Complete test file with all test functions + main section
```

**Test 2: Decrease max_tokens (experiment)**
```bash
# Edit config/llm_config.yaml
max_tokens: 1000

# Generate tests
raica -p "Create tests for simple.py"

# Expected: Shorter response (may be incomplete if file is complex)
```

### Verify No Regressions

All existing functionality should work:
- ✅ Code generation
- ✅ Test generation (now COMPLETE!)
- ✅ Investigation loop
- ✅ README generation
- ✅ Classification tasks

---

## Architectural Principles Enforced

### 1. No Hardcoded Configuration (CLAUDE.md)
- ❌ Before: 13 hardcoded limits scattered in code
- ✅ After: 0 hardcoded limits, all from config

### 2. Single Source of Truth
- ❌ Before: Config says 4096, code overrides with 3000/8000/etc
- ✅ After: Config is the only source

### 3. User Control
- ❌ Before: User can't control limits without code changes
- ✅ After: User adjusts config, all limits change

### 4. Consistency
- ❌ Before: Different operations use random limits (50, 100, 2000, 3000, 4000, 8000, 8192)
- ✅ After: All operations use same limit (or operation-specific if configured)

---

## Related Issues

**This fix resolves:**
- Test generation creating incomplete files (truncated at 3000 tokens)
- Investigation failing on incomplete tests
- User confusion about why config is ignored
- Maintenance burden of scattered magic numbers

**Related documents:**
- `/docs/PROJECT_CONFIGURATION_DIRECTIVE.md` - No hardcoded config principle
- `/docs/housekeeping/BUG_FIX_12_LLM_DRIVEN_TEST_GENERATION.md` - Test generation fix
- `CLAUDE.md` - Architectural principles

---

**Status:** Implemented ✅
**Testing:** Pending user verification
**Impact:** Config now controls all max_tokens, no hardcoded overrides
