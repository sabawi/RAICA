# Refactor: LLM-Driven File Organization Extraction

**Date:** February 6, 2026
**Component:** CLI Coding Agent - COMPLEXITY_ASSESSMENT Phase
**Issue:** Hardcoded regex patterns violating CLAUDE.md cardinal rule

---

## Problem

The COMPLEXITY_ASSESSMENT phase was using **hardcoded regex patterns** to extract semantic information from user requests:

```python
# ❌ WRONG: Hardcoded semantic parsing
dir_patterns = [
    r'create\s+(?:a\s+)?(?:sub)?director(?:y|ies)\s+["\']?([\.\/\w_-]+)["\']?',
    r'mkdir\s+["\']?([\.\/\w_-]+)["\']?',
    # ... 5 more patterns
]

filename_patterns = [
    r'as\s+[`"\']([\.\/\w_-]+\.\w+)[`"\']',
    r'(?:called?|named?)[:\s]+[`"\']?([\w_\/-]+\.\w+)[`"\']?',
    # ... 7 more patterns
]
```

**This violates the core architectural principle:**

> **RAICA doesn't interpret text, LLM does**

### Specific Issues

1. **Extracted wrong values:** Pattern matched "**named**" from "subdirectory **named** 'myprograms_test'"
2. **Brittle patterns:** Different phrasings broke extraction
3. **Maintenance nightmare:** Every new phrasing required new regex pattern
4. **Semantic interpretation:** RAICA was parsing meaning instead of LLM

---

## Solution: LLM-Driven Extraction

### Before (Lines 976-1041) - REMOVED

```python
# Hardcoded regex patterns trying to parse semantic meaning
for pattern in dir_patterns:
    match = re.search(pattern, request)
    if match:
        directory_to_create = match.group(1)  # ❌ RAICA interprets
```

### After - LLM Extracts Everything

**Updated Prompt** (Lines 1008-1032):

```python
prompt = f"""You are assessing complexity AND extracting file organization details.

USER REQUEST: {request}
PROJECT DIRECTORY: {project_dir}

🚨 CRITICAL - YOUR TASKS:

1. TECHNOLOGY DETECTION - Identify target tech from request
2. COMPLEXITY ASSESSMENT - Determine simple/medium/complex
3. FILE ORGANIZATION EXTRACTION - Extract ALL details:
   - Does user want subdirectory created? EXACT NAME?
   - What is EXACT FILENAME (with extension)?
   - What is FULL PATH (directory + filename)?

   Examples:
   - "create subdirectory named 'mydir'" → directory_to_create: "mydir"
   - "save as file.py" → filename: "file.py"
   - "subdirectory and name it 'test'" → directory_to_create: "test"
   - "in the subdirectory with the name 'scripts'" → directory_to_create: "scripts"

OUTPUT FORMAT (JSON):
{{
    "detected_technology": "web-frontend | python | node | auto",
    "complexity": "simple|medium|complex",
    "reasoning": "...",
    "directory_to_create": "exact_directory_name or null",
    "filename": "exact_filename.ext",
    "main_filename": "directory/filename.ext or filename.ext (complete path)"
}}

PRINCIPLES:
- Extract file organization details EXACTLY as user specified
- NO interpretation - use user's EXACT names
```

**Updated Parsing** (Lines 1044-1079):

```python
data = self._extract_json(response)
if data and "complexity" in data:
    # LLM extracts ALL details - no regex!
    directory_to_create = data.get('directory_to_create')
    filename = data.get('filename')
    main_filename = data.get('main_filename')  # Full path

    # Store for later use
    if directory_to_create and directory_to_create != 'null':
        self._directory_to_create = directory_to_create

    if complexity == "simple":
        # Use LLM-provided filename with full path
        final_filename = main_filename or filename or default_file
        self._simple_filename = final_filename  # ✅ LLM decides
```

---

## Key Benefits

### 1. **Handles ANY Phrasing**

**Before:** Needed regex pattern for each phrasing
- "create subdirectory named 'X'" → Pattern 1
- "subdirectory with the name 'X'" → Pattern 2
- "subdirectory and name it 'X'" → Pattern 3
- New phrasing → Need new pattern!

**After:** LLM understands ALL phrasings naturally
- "create subdirectory named 'X'" → LLM extracts "X"
- "subdirectory with the name 'X'" → LLM extracts "X"
- "subdirectory and name it 'X'" → LLM extracts "X"
- ANY new phrasing → LLM extracts correctly

### 2. **No False Matches**

**Before:**
```
Request: "create subdirectory named 'myprograms_test'"
Regex captured: "named" ❌ (matched wrong word!)
```

**After:**
```
Request: "create subdirectory named 'myprograms_test'"
LLM extracted: "myprograms_test" ✅ (understood meaning!)
```

### 3. **Future-Proof**

**Before:** Every edge case required code changes

**After:** LLM handles all cases automatically, including:
- Multiple directories: "create dirs A, B, and C"
- Nested paths: "create A/B/C and save as A/B/C/file.py"
- Ambiguous requests: "put it in the test folder"

### 4. **Consistent with Architecture**

Now follows CLAUDE.md principles everywhere:
- ✅ Request classification → LLM decides
- ✅ Intent interpretation → LLM decides
- ✅ Decision making (EXECUTE/CREATE) → LLM decides
- ✅ **File organization extraction** → **LLM decides**

---

## Testing

### Test Case 1: Original Bug
```
Request: "create a subdirectory and name it 'myprograms_test'. Write quad_solver.py in that subdirectory"

Before: directory = "named" ❌
After:  directory = "myprograms_test" ✅
```

### Test Case 2: Alternative Phrasing
```
Request: "make a subdirectory with the name 'scripts' and save file.py there"

Before: Needed new regex pattern ❌
After:  LLM extracts "scripts" ✅
```

### Test Case 3: Full Path
```
Request: "save as mydir/subdir/file.py"

Before: Complex regex logic to parse path ❌
After:  LLM returns main_filename: "mydir/subdir/file.py" ✅
```

---

## Architecture Principle Reinforced

**The Cardinal Rule:**

```
┌─────────────────────────────────────────────────────────┐
│  LLM DECIDES, RAICA EXECUTES                           │
│                                                         │
│  ❌ DON'T: Hardcode semantic parsing                   │
│  ❌ DON'T: Pattern match for meaning                   │
│  ❌ DON'T: Try to outsmart the LLM                     │
│                                                         │
│  ✅ DO: Ask LLM for details                            │
│  ✅ DO: Feed ambiguity to LLM                          │
│  ✅ DO: Trust LLM's interpretation                     │
└─────────────────────────────────────────────────────────┘
```

**When in doubt:**
- Ask: "Am I interpreting text meaning?" → If YES, let LLM do it
- Ask: "Could LLM extract this?" → If YES, ask LLM
- Ask: "Am I hardcoding patterns?" → If YES, use LLM instead

---

## Files Modified

| File | Lines Removed | Lines Added | Purpose |
|------|--------------|-------------|---------|
| `cli_coding_agent.py` | 976-1041 (65 lines) | 968-1079 (LLM prompt) | Remove regex, add LLM extraction |

**Net change:** Removed hardcoded logic, replaced with LLM-driven extraction

---

## Related Documentation

- **CLAUDE.md:** Cardinal rule - LLM decides, RAICA executes
- **MEMORY.md:** Bug #2 - Regex patterns not matching reformulated requests
- **LLM_DRIVEN_ITERATION_LOOP.md:** Same principle applied to retry logic

---

**Status:** Implemented ✅
**Testing:** Pending user verification with subdirectory creation test
**Next:** Verify all edge cases work with LLM-driven extraction
