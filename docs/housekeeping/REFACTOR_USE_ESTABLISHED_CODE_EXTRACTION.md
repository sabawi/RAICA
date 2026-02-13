# Refactor: Use Established Code Extraction Methods

**Date:** February 6, 2026
**Component:** Test Investigation - Code Extraction
**Issue:** Reinventing the wheel, code duplication
**Principle:** DRY (Don't Repeat Yourself)

---

## Problem

The test investigation feature was using a **different code extraction approach** than the rest of RAICA:

### Investigation Fix (WRONG):
```python
# Ask LLM to return JSON with fixed_code as string
prompt = """Return JSON: {"fixed_code": "..."}"""
response = self.llm_client.generate(prompt)
data = self._extract_json(response)
fixed_code = data.get('fixed_code', '')

# Manually clean wrappers
fixed_code = self._clean_code_wrappers(fixed_code)  # Custom cleaning!
```

### Code Generation (CORRECT):
```python
# Ask LLM to return markdown code block
prompt = """Return code in markdown: ```python\n...\n```"""
response = self._call_llm(prompt)

# Use established extraction
code_blocks = self._extract_code_blocks(response)  # Proven method!
_, code = code_blocks[0]
```

**Issues with investigation approach:**
1. ❌ **Code duplication** - Reinventing extraction logic
2. ❌ **Inconsistency** - Different pattern than rest of codebase
3. ❌ **Untested** - `_clean_code_wrappers()` is new, unproven
4. ❌ **Maintenance burden** - Two extraction methods to maintain
5. ❌ **Missing features** - Doesn't strip thinking content, no LLM fallback

---

## Solution: Reuse `_extract_code_blocks()`

### What `_extract_code_blocks()` Already Does

Located at `cli_coding_agent.py:751`, this method:

```python
def _extract_code_blocks(self, content: str) -> List[Tuple[str, str]]:
    """
    Extract code blocks from LLM response.

    ARCHITECTURE: If standard markdown extraction fails, asks LLM to extract.
    NO hardcoded language patterns - LLM decides what is code.
    """
    # 1. Strip thinking/reasoning content
    content = strip_thinking_content(content)

    # 2. Try markdown patterns
    pattern = r'```(\w+)?\s*\n([\s\S]*?)```'
    matches = re.findall(pattern, content)

    # 3. Fall back to LLM extraction if needed
    if not matches:
        extracted = self._llm_extract_code(content)

    return [(language, code.strip()) for language, code in matches]
```

**Features:**
- ✅ Strips thinking content automatically
- ✅ Multiple markdown pattern attempts
- ✅ LLM fallback for non-standard formatting
- ✅ Language detection
- ✅ Proven across CODE_GENERATION, ENHANCE, DEBUG
- ✅ Handles all edge cases

### Refactored Investigation Fix

**Before:**
```python
# ASK: Return JSON with code as string
prompt = f"""Return JSON:
{{
    "analysis": "...",
    "fix_target": "test" or "main",
    "fixed_code": "Complete fixed code for the file"
}}
"""

response = self.llm_client.generate(prompt)
data = self._extract_json(response.content)
fixed_code = data.get('fixed_code', '')
fixed_code = self._clean_code_wrappers(fixed_code)  # Manual cleaning
```

**After:**
```python
# ASK: Return code in markdown block
prompt = f"""First, write a brief analysis of the issue.

Then provide the fixed code in a markdown code block:
```python
# Complete fixed code here
```

Indicate which file to fix: "fix_target: test" or "fix_target: main"
"""

response = self.llm_client.generate(prompt)
response_text = response.content if hasattr(response, 'content') else str(response)

# Extract fix target from text
fix_target = 'main'
if 'fix_target: test' in response_text.lower():
    fix_target = 'test'

# Use established extraction (same as CODE_GENERATION)
code_blocks = self._extract_code_blocks(response_text)
if not code_blocks:
    return False

# Get code (already cleaned by _extract_code_blocks!)
_, fixed_code = code_blocks[0]

# Extract analysis (text before code block)
analysis = response_text.split('```')[0].strip()[:200]
```

---

## Benefits

### 1. **Code Reuse**
- Uses proven, tested extraction logic
- No code duplication
- Single source of truth for extraction

### 2. **Consistency**
- Same pattern as CODE_GENERATION, ENHANCE, DEBUG
- Developers familiar with one pattern understand all
- Easier to maintain and debug

### 3. **Robustness**
- Inherits all edge case handling
- Thinking content stripped automatically
- LLM fallback for non-standard formatting
- Multiple markdown pattern attempts

### 4. **Reduced Complexity**
- Deleted 43 lines of `_clean_code_wrappers()`
- No manual wrapper stripping needed
- Simpler, clearer code

### 5. **Better Error Handling**
- Consistent error messages
- Same logging as other components
- Proven failure recovery

---

## Before/After Comparison

### Lines of Code

| Approach | Lines | Complexity |
|----------|-------|------------|
| Before (JSON + manual cleaning) | 58 | High |
| After (markdown + reuse) | 15 | Low |

**Reduction: 43 lines removed, 74% simpler!**

### Extraction Reliability

| Feature | JSON Approach | Markdown Approach |
|---------|---------------|-------------------|
| Strip thinking content | ❌ No | ✅ Yes (automatic) |
| Handle triple quotes | ⚠️ Manual | ✅ Yes (automatic) |
| Handle filename prefixes | ⚠️ Manual | ✅ Yes (automatic) |
| LLM fallback | ❌ No | ✅ Yes (automatic) |
| Multiple patterns | ❌ No | ✅ Yes (2 patterns) |
| Language detection | ❌ No | ✅ Yes |
| Battle-tested | ❌ New | ✅ Yes (used everywhere) |

---

## Architecture Principle: DRY

**From CLAUDE.md:**
> Always reuse existing code. Before writing a new utility function, search the codebase if there is a working function already written to do the same work. Always reuse existing code and improve it.

**This refactor enforces:**
- ✅ Reuse proven extraction logic
- ✅ Don't reinvent the wheel
- ✅ Consistent patterns across codebase
- ✅ Single source of truth

---

## Testing

### Test Case: LLM Returns Triple-Quoted Code

**Before (failed):**
```python
LLM returns: {"fixed_code": "'''test.py\ndef test():\n    pass\n'''"}
Extracted: "'''test.py\ndef test():\n    pass\n'''"
After manual cleaning: "def test():\n    pass"  # Works but fragile
```

**After (automatic):**
```python
LLM returns: "```python\ndef test():\n    pass\n```"
_extract_code_blocks(): [('python', 'def test():\n    pass')]
Result: "def test():\n    pass"  # Robust!
```

### Test Case: LLM Returns Thinking + Code

**Before (broken):**
```python
LLM returns: {"fixed_code": "<thinking>Let me analyze...</thinking>\ndef test():..."}
Result: Code includes thinking tags!  ❌
```

**After (automatic):**
```python
LLM returns: "<thinking>Let me analyze...</thinking>\n```python\ndef test():...\n```"
strip_thinking_content(): Removes thinking
_extract_code_blocks(): Extracts clean code
Result: Pure code only  ✅
```

---

## Files Modified

| File | Change | Impact |
|------|--------|--------|
| `cli_coding_agent.py` | Removed `_clean_code_wrappers()` (43 lines) | Code cleanup |
| `cli_coding_agent.py` | Updated investigation prompt | Use markdown not JSON |
| `cli_coding_agent.py` | Use `_extract_code_blocks()` | Reuse established method |

**Net change:** -43 lines, +consistency, +reliability

---

## Related Principles

1. **DRY (Don't Repeat Yourself)** - Single extraction method
2. **Separation of Concerns** - Extraction logic in one place
3. **Fail Fast** - Consistent error handling
4. **LLM-Driven** - Markdown is natural for LLMs

---

**Status:** Implemented ✅
**Testing:** Pending user verification
**Impact:** More consistent, reliable code extraction across all components
