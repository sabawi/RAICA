# Codebase Audit Checklist

## Purpose
This document defines the patterns to search for during codebase audits to ensure CLAUDE.md compliance.

## Lessons Learned (2026-02-02)

The previous audit missed several hardcoded keyword patterns because the search was not comprehensive. Future audits must include ALL patterns listed below.

### Patterns That Were Missed

1. **Keyword-based routing patterns** - `if any(kw in request for kw in [...])`
2. **Hardcoded extension lists** - `['*.py', '*.js', '*.ts', ...]`
3. **Technology detection from text** - `if 'webapp' in request.lower()`

---

## MANDATORY Audit Search Patterns

### 1. Hardcoded Keyword Lists (CLAUDE.md Violation)

Search for patterns where RAICA interprets text instead of LLM:

```bash
# Keyword matching in conditionals
grep -rn "if any(kw in" agents/
grep -rn "for kw in \[" agents/

# Hardcoded keyword lists
grep -rn "KEYWORDS\s*=" agents/
grep -rn "keywords\s*=\s*\[" agents/

# Text interpretation patterns
grep -rn "in request.lower()" agents/
grep -rn "in request_lower" agents/
grep -rn "\.lower().*in\s*\[" agents/
```

### 2. Hardcoded Extension Lists (Should Use LANGUAGE_DEFINITIONS)

```bash
# Hardcoded file extension lists
grep -rn "\['\\*\\.py'.*'\\*\\.js'" agents/
grep -rn "\.py.*\.js.*\.ts" agents/
grep -rn "endswith.*\\.py.*or.*endswith" agents/

# Extension lists that should use LANGUAGE_DEFINITIONS
grep -rn "extensions\s*=\s*\[" agents/
grep -rn "valid_extensions\s*=" agents/
grep -rn "SOURCE_EXTENSIONS" agents/
```

### 3. Hardcoded Fallback Values (Should Fail Fast)

```bash
# Default/fallback patterns
grep -rn "else:.*=.*\"main\.py\"" agents/
grep -rn "else:.*=.*\"index\.html\"" agents/
grep -rn "default.*=.*\[" agents/

# Fallback language detection
grep -rn "language\s*=\s*['\"]python['\"]" agents/
```

### 4. Pattern Matching for Intent Classification

```bash
# Text-based classification
grep -rn "if.*\"fix\".*in" agents/
grep -rn "if.*\"debug\".*in" agents/
grep -rn "if.*\"create\".*in" agents/
grep -rn "if.*\"enhance\".*in" agents/
```

### 5. Hardcoded Error Type Handlers

```bash
# Specific error handling
grep -rn "if error_type ==" agents/
grep -rn "if.*ImportError" agents/
grep -rn "if.*SyntaxError" agents/
```

---

## Audit Verification Checklist

After running searches, verify each finding against:

- [ ] Does this code let LLM decide, or does RAICA interpret?
- [ ] Does this use `LANGUAGE_DEFINITIONS` for extensions?
- [ ] Does this fail fast when config is missing?
- [ ] Would a new, never-seen-before case work?

## Files That Were Fixed (2026-02-02)

| File | Issue | Fix |
|------|-------|-----|
| `cli_coding_agent.py:999` | Keyword matching for language | Added `_llm_classify_language()` |
| `cli_coding_agent.py:1451` | Keyword matching for entry file | Added `_llm_classify_entry_file()` |
| `agent_runner.py:2525` | Keyword matching for technology | Use `agent._llm_classify_entry_file()` |
| `agent_runner.py:2551` | Fallback keyword matching | Use LLM classification |
| `agent_runner.py:3352` | Hardcoded extension list | Use `LANGUAGE_DEFINITIONS` |
| `debug_controller.py:3050` | Hardcoded extension list | Use `LANGUAGE_DEFINITIONS` |
| `universal_handler.py:972` | Missing .log exclusion | Added artifact exclusions |

---

## Automated Audit Script

Create this script to run all audit checks:

```bash
#!/bin/bash
# audit_claude_compliance.sh

echo "=== CLAUDE.md Compliance Audit ==="
echo ""

echo "1. Checking for keyword-based routing..."
grep -rn "if any(kw in" agents/ --include="*.py" || echo "   None found"
grep -rn "for kw in \[" agents/ --include="*.py" || echo "   None found"

echo ""
echo "2. Checking for hardcoded extension lists..."
grep -rn "extensions\s*=\s*\[" agents/ --include="*.py" | grep -v "LANGUAGE_DEFINITIONS" || echo "   None found"

echo ""
echo "3. Checking for text interpretation..."
grep -rn "in request.lower()" agents/ --include="*.py" || echo "   None found"
grep -rn "in request_lower" agents/ --include="*.py" || echo "   None found"

echo ""
echo "=== Audit Complete ==="
```

---

## Next Audit Schedule

Run a full audit before each major release or after significant refactoring.
