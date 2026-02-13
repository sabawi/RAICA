# Context-First Architecture for RAICA Skills

**Version:** 1.0
**Status:** Initial Implementation (v1.0.0.34)
**Last Updated:** 2026-02-06

## 🎯 Vision

Enable RAICA to accomplish user tasks by giving the LLM complete knowledge from the start, then letting it discover, innovate, and adapt until the task is done.

**Core Principle:** LLM knowledge leads the way. RAICA only provides guardrails and lights the path.

## 📊 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  PREPARATION PHASE (Before LLM Contact)                         │
│  ─────────────────────────────────────────────────────────────  │
│  1. Build System Profile (OS, tools, capabilities)              │
│     → Cached, rarely changes (~100-200 tokens)                  │
│                                                                  │
│  2. Build User Profile (name, email, preferences)               │
│     → Cached, updates occasionally (~50 tokens)                 │
│                                                                  │
│  3. Build Project Profile (architecture, HLD, LLD, specs)       │
│     → Per-request, context-heavy (~500-1500 tokens)             │
│                                                                  │
│  4. Parse Request Context (what user wants)                     │
│                                                                  │
│  Result: RICH, CLEAN, FOCUSED CONTEXT (~1500-2000 tokens)       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  FIRST LLM CONTACT - Full Introduction                          │
│  ─────────────────────────────────────────────────────────────  │
│  Prompt includes:                                                │
│  • System profile (what tools are available)                    │
│  • User profile (who they are, what they prefer)                │
│  • Project profile (architecture, design, code specs)           │
│  • Request (what they want to accomplish)                       │
│  • Decision framework (how to respond)                          │
│                                                                  │
│  LLM now has COMPLETE knowledge to make informed decisions      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  ITERATION LOOP [DECIDE → ACT → VERIFY]                         │
│  ─────────────────────────────────────────────────────────────  │
│  Much lighter prompts (~200-500 tokens):                        │
│  • What we tried last                                            │
│  • What happened (result)                                        │
│  • What we discovered                                            │
│  • What should we try next?                                      │
│                                                                  │
│  Context accumulates: LLM can innovate and adapt                │
└─────────────────────────────────────────────────────────────────┘
```

## 🏗️ Implementation Components

### 1. Context Builder (`context_builder.py`)

**Purpose:** Builds rich, focused context BEFORE first LLM contact.

**Key Classes:**
- `SystemProfile` - OS, shell, Python, available tools (cached)
- `UserProfile` - Name, email, preferences (cached)
- `ProjectProfile` - CLAUDE.md, README, architecture, HLD, LLD, file tree (per-request)
- `Context` - Complete context object

**Token Budget:**
- System Profile: ~100-200 tokens
- User Profile: ~50 tokens
- Project Profile: ~500-1500 tokens (varies by project)
- **Total Target: < 2000 tokens**

**Key Principle: RAW DATA, NOT PARSING**
```python
# ❌ DON'T parse markdown structure
def parse_claude_md(text):
    sections = extract_sections(text)  # Complex parsing
    return structured_data

# ✅ DO give LLM raw markdown
def read_claude_md(path):
    return path.read_text()  # LLM understands markdown!
```

### 2. Tool Discovery (Dynamic, Not Hardcoded)

**Current Implementation:**
```python
def _discover_critical_tools(self):
    """
    Check for COMMONLY NEEDED tools, but NOT limiting!

    This is NOT a hardcoded list of all possible tools.
    LLM can still request ANY command - this just gives it
    a quick reference of what's definitely available.
    """
    tools_to_check = {
        'mail': 'email',
        'curl': 'web',
        'git': 'vcs',
        # etc...
    }

    for tool_name, category in tools_to_check.items():
        if self._tool_exists(tool_name):  # Dynamic check with `which`
            discovered[tool_name] = ToolInfo(...)
```

**Key Principle:** DISCOVERY, not LIMITATION
- ✅ Check if tool exists
- ✅ Give LLM quick reference
- ❌ Don't dictate usage or parameters
- ❌ Don't prevent LLM from trying other tools

### 3. First Contact Template (`first_contact_template.py`)

**Purpose:** Rich first-contact prompt with complete context.

**Structure:**
1. **Header** - Task introduction
2. **System Profile** - What's available
3. **User Profile** - Who the user is
4. **Project Profile** - Architecture, design, code specs
5. **Decision Framework** - How to respond (JSON format)
6. **Guidelines** - Be specific, discover dynamically, keep trying

**Measured Token Usage:**
- Without project: ~772 tokens
- With project: ~1500-2000 tokens

**Key Feature: Subsequent iterations are MUCH lighter!**
- Iteration 1: Full context (~1500-2000 tokens)
- Iteration 2+: Only deltas (~200-500 tokens)

## 🎯 Benefits

1. **LLM Knowledge-Driven**
   - LLM has complete picture from the start
   - Can make informed decisions
   - Can innovate and discover

2. **Token-Efficient**
   - Full context ONCE (first contact)
   - Deltas only for iterations
   - Total cost is reasonable

3. **Project-Aware**
   - Understands architecture
   - Follows project directives (CLAUDE.md)
   - Respects code standards

4. **Dynamic Discovery**
   - No hardcoded tool lists
   - LLM can request any command
   - System capabilities discovered, not assumed

5. **Clean Separation**
   - RAICA: Prepares context, executes commands
   - LLM: Decides everything, interprets context

## ⚠️ Pitfalls to Avoid

### 1. Bloated Context
**Problem:** Including too much irrelevant information.

**Solution:**
- Measure token usage at every step
- Truncate docs if too long (CLAUDE.md: 2000 chars, README: 1000 chars)
- Only include what's relevant to the request

### 2. Over-Engineering Parsers
**Problem:** Writing complex parsers that violate MINIMAL SCAFFOLDING.

**Solution:**
- Give LLM raw data (markdown, tree output)
- Let LLM parse and understand
- RAICA only structures data, doesn't interpret it

### 3. Hardcoded Discovery
**Problem:** Falling back to hardcoded lists of tools.

**Solution:**
- Dynamic discovery with `which` command
- Categories are for ORGANIZATION, not LIMITATION
- LLM can request ANY tool, even if not in discovered list

### 4. Stale Cache
**Problem:** Cached profiles become outdated.

**Solution:**
- Cache system/user profiles (rarely change)
- Rebuild project profile per-request (often changes)
- Add cache invalidation if needed (future)

### 5. Token Explosion
**Problem:** Context grows too large with project docs.

**Solution:**
- Set hard limits per doc type
- Truncate with clear indicators
- Future: Smart summarization or chunking

## 📋 Implementation Roadmap

### ✅ Step 1: Core Context Builder (v1.0.0.34) - DONE
- [x] Data structures (SystemProfile, UserProfile, ProjectProfile, Context)
- [x] Context Builder module
- [x] System profile with tool discovery
- [x] User profile
- [x] Basic project profile (CLAUDE.md, README, file tree)
- [x] Token tracking
- [x] First contact template
- [x] Iteration template
- [x] Testing utilities

### 🔄 Step 2: Integration with Universal Handler (v1.0.0.34) - IN PROGRESS
- [ ] Update universal_handler.py to use ContextBuilder
- [ ] Replace GATHER phase with PREPARATION phase
- [ ] Use first_contact_template for initial DECIDE
- [ ] Use iteration template for subsequent DECIDE
- [ ] Add discovery extraction from ACT results
- [ ] Test end-to-end with SYSTEM_TASK

### 🔜 Step 3: Project Intelligence (v1.0.0.35)
- [ ] Architecture doc reading (docs/ARCHITECTURE.md)
- [ ] HLD reading (docs/HLD.md, docs/design/high_level.md)
- [ ] LLD reading (docs/LLD.md, docs/design/low_level.md)
- [ ] Code specs extraction (docs/CODE_STANDARDS.md)
- [ ] Enhanced code structure analysis
- [ ] Dependency mapping

### 🔜 Step 4: Iteration Context Manager (v1.0.0.36)
- [ ] IterationContext class
- [ ] Discovery extraction logic
- [ ] Context accumulation
- [ ] Context pruning (keep relevant, drop noise)
- [ ] Smart summarization for long iterations

### 🔜 Step 5: Coverage for Other Skills (v1.0.1.X)
- [ ] CODE_DEBUG skill context
- [ ] CODE_ENHANCE skill context
- [ ] PROJECT_CREATE skill context
- [ ] Each skill gets appropriate context preparation

### 🔜 Step 6: Advanced Features (v1.0.2.X)
- [ ] User preferences system (~/.raica/preferences.yaml)
- [ ] Recent context tracking (last 5 successful tasks)
- [ ] Working style detection (verbose vs. quick)
- [ ] Tool help text caching
- [ ] Smart context summarization

## 🧪 Testing Strategy

### Current Tests
1. **Context Builder Test** (`context_builder.py`)
   - Build context without project: ~152 tokens ✅
   - Build context with project: ~1091 tokens ✅
   - Cache working: 0.0ms on second call ✅
   - Tool discovery: 10 tools found ✅

2. **First Contact Template Test** (`first_contact_template.py`)
   - Without project: ~772 tokens ✅
   - Prompt structure: Clean and organized ✅

### Needed Tests
- [ ] End-to-end with actual LLM
- [ ] Token usage with large projects
- [ ] Cache invalidation
- [ ] Truncation behavior
- [ ] Discovery extraction
- [ ] Iteration context accumulation

## 📊 Metrics to Track

1. **Token Usage**
   - First contact: Target < 2000 tokens
   - Iterations: Target < 500 tokens
   - Total per task: Track average

2. **Context Build Time**
   - System profile (cached): < 5ms
   - User profile (cached): < 5ms
   - Project profile: < 100ms
   - Total: < 150ms

3. **Cache Hit Rate**
   - System profile: Should be 99%+
   - User profile: Should be 99%+

4. **Task Success Rate**
   - Before context-first: Baseline TBD
   - After context-first: Track improvement

## 🔑 Key Principles (Never Forget!)

1. **LLM Decides, RAICA Executes** - No hardcoded interpretation
2. **RAW DATA for LLM** - Don't parse, let LLM understand
3. **Discovery, Not Limitation** - Tool discovery is convenience, not constraint
4. **Measure Everything** - Token usage, timing, success rate
5. **Start Minimal, Expand Carefully** - Test before adding complexity
6. **Context is King** - Rich context enables LLM to innovate

## 📝 Next Steps

**Immediate (Step 2):**
1. Integrate ContextBuilder with universal_handler.py
2. Test with simple SYSTEM_TASK (send email)
3. Measure token usage and success rate
4. Refine based on results

**Short-term (Steps 3-4):**
1. Add HLD/LLD reading
2. Add iteration context manager
3. Test with CODE_DEBUG tasks

**Long-term (Steps 5-6):**
1. Coverage for all skills
2. Advanced features (preferences, history)
3. Optimization and performance tuning

---

**Remember:** The devil is in the details. Test incrementally, measure constantly, and don't lose sight of the core principle: **LLM knowledge leads the way, RAICA only provides guardrails and lights the path.**
