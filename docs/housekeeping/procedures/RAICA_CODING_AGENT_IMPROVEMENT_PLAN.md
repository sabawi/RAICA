# RAICA Coding Agent Improvement Plan

## System Prompts, Tools & Architecture Enhancement

**Version:** 1.0.0
**Date:** 2026-01-29
**Status:** Planning Phase
**Estimated Duration:** 2-3 weeks
**Priority:** Critical

---

## Executive Summary

This plan addresses 8 critical and high-priority issues identified in the RAICA coding agent's system prompts, tool architecture, and LLM instruction design. The improvements will enable the LLM to better interpret user requests, utilize available tools comprehensively, and follow clear reasoning chains.

---

## Issues Summary

| ID  | Issue                                      | Severity     | Effort | Status         |
| --- | ------------------------------------------ | ------------ | ------ | -------------- |
| 1   | Missing Request Interpreter Prompt         | **Critical** | 4 hrs  | 🔴 Not Started |
| 2   | Incomplete Tool Set (24 tools, need 34)    | **High**     | 6 hrs  | 🔴 Not Started |
| 3   | Poor Context Management (naive truncation) | **High**     | 4 hrs  | 🔴 Not Started |
| 4   | Phase Ambiguity (diagnosis vs fix)         | Medium       | 2 hrs  | 🔴 Not Started |
| 5   | Missing Tool Usage Examples                | Medium       | 1 hr   | 🔴 Not Started |
| 6   | MAX_ITERATIONS Bug (3 vs 10)               | **Critical** | 1 min  | 🔴 Not Started |
| 7   | Duplicate Code (logger/imports)            | Low          | 1 min  | 🔴 Not Started |
| 8   | Keyword Over-Reliance in Classifier        | Medium       | 2 hrs  | 🔴 Not Started |

---

## Phase 1: Critical Quick Fixes (Day 1)

### Task 1.1: Fix MAX_ITERATIONS Bug

**File:** `agents/coding_agent/agent_config.py`
**Change:** Line 11, `MAX_ITERATIONS = 3` → `MAX_ITERATIONS = 10`
**Rationale:** Aligns with AUTONOMOUS_DEBUG_LOOP_DESIGN.md specification
**Testing:** Verify debug controller uses 10 iterations max
**Estimated Time:** 5 minutes
**Status:** 🔴 Not Started

### Task 1.2: Remove Duplicate Code

**File:** `agents/coding_agent/autonomous/debug_controller.py`
**Changes:**

- Remove duplicate logger initialization (lines 41-42 and 57)
- Remove duplicate LanguageDetector import (lines 47-48)
  **Rationale:** Code quality improvement
  **Testing:** Verify file imports and runs without error
  **Estimated Time:** 5 minutes
  **Status:** 🔴 Not Started

---

## Phase 2: Core Architecture Improvements (Days 2-4)

### Task 2.1: Create Request Interpreter Module with User Feedback Loop

**New File:** `agents/coding_agent/prompts/request_interpreter.py`
**Purpose:** Centralized user request interpretation with validation and iterative refinement

**Components:**

1. `REQUEST_INTERPRETER_PROMPT` - System prompt template
2. `RequestInterpreter` class - Main interpreter logic
3. `interpret_request()` method - Convert natural language to structured plan
4. `validate_interpretation()` method - Check interpretation quality
5. **`UserFeedbackHandler`** - NEW: Present interpretation and capture user feedback
6. **`interpretation_iteration_loop()`** - NEW: Iterate until user confirms understanding

**Key Features:**

- Intent analysis with confidence scoring
- Explicit TO-DO list generation
- Tool mapping for each step
- Risk assessment and mitigation
- Dependency mapping
- **User Validation Questionnaire** (NEW)
- **Iterative Clarification Loop** (NEW)

**User Feedback Questionnaire Features:**

```python
class UserFeedbackHandler:
    def present_interpretation(self, interpretation: dict) -> str:
        # Format a clear, readable summary for the user
        # Include: intent, todo_list, tool suggestions, risks

    def capture_feedback(self) -> UserFeedback:
        # Ask user:
        # 1. "Is this what you meant? (yes/no/partly)"
        # 2. "What's missing or incorrect?"
        # 3. "Any additional requirements?"
        # 4. Priority: high/medium/low

    def should_iterate(self, feedback: UserFeedback) -> bool:
        # Return True if user wants changes

    def build_iteration_prompt(self, original: str, interpretation: dict,
                               feedback: UserFeedback) -> str:
        # Build prompt for LLM to revise interpretation based on feedback
```

**Interpretation Iteration Loop:**

```
User Request → LLM Interpretation → Present to User → Get Feedback
                                      ↓ (if not confirmed)
                           Revise Interpretation ← User Feedback
                                      ↓
                            User Confirms → Proceed to Execution
```

**Integration Points:**

- Called by `orchestrator.py` before classification
- Results feed into `task_decomposer.py`
- Stores interpretation in `DebugContext`
- **NEW:** Interacts with TUI for user feedback (or CLI prompts)

**Testing:**

- Unit tests for 20+ request types
- Unit tests for feedback handling
- Integration with orchestrator
- Verify JSON output structure
- Test iteration scenarios (user corrections)
  **Estimated Time:** 6 hours (increased from 4 due to feedback loop)
  **Status:** 🔴 Not Started

### Task 2.2: Add Missing Tools to DebugToolkit

**File:** `agents/coding_agent/services/debug_toolkit.py`
**Current Tools:** 24
**Target Tools:** 34
**New Tools to Add:**

| Tool Name          | Purpose                         | Schema Definition | Implementation |
| ------------------ | ------------------------------- | ----------------- | -------------- |
| `analyze_project`  | Full project health check       | Required          | Required       |
| `create_test`      | Generate test file for bug      | Required          | Required       |
| `run_tests`        | Execute pytest/jest             | Required          | Required       |
| `git_diff`         | Show uncommitted changes        | Required          | Required       |
| `get_backups`      | List available backups          | Required          | Required       |
| `restore_backup`   | Restore file from backup        | Required          | Required       |
| `check_lint`       | Run pylint/eslint               | Required          | Required       |
| `format_file`      | Auto-format with black/prettier | Required          | Required       |
| `dependency_check` | Verify imports vs requirements  | 🟢 Complete       | 🟢 Complete    |
| `get_project_tree` | Hierarchical file structure     | Required          | Required       |

**Implementation Note (v2.2):** `dependency_check` and broader resolution logic implemented via `DependencyResolver` service.

**Status:** 🟡 In Progress (Core components starting to land)
**Implementation Steps:**

1. Add tool schema to `get_tool_schema()` for each new tool
2. Implement tool method for each (following existing patterns)
3. Add required args to `TOOL_REQUIRED_ARGS`
4. Add validation logic to `validate_args()`
5. Write unit tests for each tool
6. Update documentation
   **Integration Points:**

- Available to `ToolCallingClient`
- Used by `GeneralizedDebugEngine`
- Referenced in tool-calling prompts
  **Testing:**
- Each tool tested independently
- Integration test with executor
- Schema validation test
  **Estimated Time:** 6 hours
  **Status:** 🔴 Not Started

---

## Phase 3: Context & Prompt Improvements (Days 5-7)

### Task 3.1: Implement Intelligent Context Manager

**New File:** `agents/coding_agent/services/context_manager.py`
**Purpose:** Replace naive truncation with priority-based context assembly
**Components:**

1. `ContextPriority` enum - Priority levels for context components
2. `TokenBudget` class - Track and manage token allocation
3. `ContextManager` class - Main context assembly logic
   **Priority System:**

```python
priority_scores = {
    'error_trace': 10,           # Critical - always include
    'user_request': 9,           # Critical - always include
    'recent_tool_results': 8,    # High - last 3 iterations
    'file_being_edited': 7,      # High - current focus
    'project_structure': 6,      # Medium - summarize if large
    'interpretation': 5,         # Medium - LLM's reasoning
    'conversation_history': 3,   # Low - recent only
    'general_context': 1,        # Lowest - truncate first
}
```

**Features:**

- Token-based calculation (not character-based)
- Smart truncation (preserve structure)
- Context compression strategies
- Dynamic reallocation based on phase
  **Integration Points:**
- Used by `ToolCallingClient._build_context()`
- Used by `GeneralizedDebugEngine._build_diagnosis_prompt()`
- Replaces manual context building
  **Testing:**
- Unit tests with various context sizes
- Verify high-priority items preserved
- Measure token efficiency
  **Estimated Time:** 4 hours
  **Status:** 🔴 Not Started

### Task 3.2: Add Phase Transition Prompt

**File:** `agents/coding_agent/services/guidance_planner.py`
**Purpose:** Define clear boundary between diagnosis and fix phases
**Components:**

1. `PHASE_TRANSITION_PROMPT` - System prompt constant
2. `validate_phase_transition()` method - Check if diagnosis is complete
3. `PhaseGate` class - Enforce phase rules
   **Content Requirements:**

- Checklist for diagnosis completion
- Explicit "ready_to_fix" boolean
- Additional info request capability
- Fix plan structure specification
  **Integration Points:**
- Called before fix phase in `DebugOrchestrator`
- Results stored in `DebugContext`
- Affects tool availability (read-only vs read-write)
  **Testing:**
- Test with incomplete diagnosis (should block)
- Test with complete diagnosis (should allow)
- Verify clear reasoning provided
  **Estimated Time:** 2 hours
  **Status:** 🔴 Not Started

---

## Phase 4: Tool Usage & Reasoning (Days 8-9)

### Task 4.1: Add Tool Usage Examples to System Prompt

**File:** `agents/coding_agent/services/tool_calling_client.py`
**Purpose:** Provide concrete examples of tool usage patterns
**Changes:**

1. Expand `SYSTEM_PROMPT_TEMPLATE` with examples section
2. Add 5-7 realistic usage scenarios
3. Include multi-step tool sequences
4. Show error handling patterns
   **Example Scenarios:**

- Fix a NameError
- Install missing dependency
- Debug import error
- Create and verify test
- Multi-file refactoring
  **Integration Points:**
- Loaded by `ToolCallingClient.__init__()`
- Used in every tool-calling request
  **Testing:**
- Verify examples render correctly
- Test with actual LLM calls
- Measure improvement in tool selection
  **Estimated Time:** 1 hour
  **Status:** 🔴 Not Started

### Task 4.2: Add "Show Your Work" Instruction

**Files:**

- `tool_calling_client.py`
- `guidance_planner.py`
- `generalized_debug_engine.py`
- `request_classifier.py`
  **Purpose:** Require LLM to show reasoning before providing JSON
  **Changes:**
  Add to each prompt template:

```
## REASONING REQUIREMENT
Before providing your final JSON response:
1. Think step-by-step about the problem
2. Consider what information you have and what you need
3. Explain your reasoning in the "reasoning" field
4. Only then provide the action/fix
```

**Integration Points:**

- All LLM prompts in the system
- Parsed and stored in context
  **Testing:**
- Verify reasoning field present in responses
- Check reasoning quality
- Ensure JSON still parseable
  **Estimated Time:** 30 minutes
  **Status:** 🔴 Not Started

---

## Phase 5: Classifier Improvements (Day 10)

### Task 5.1: Reduce Keyword Reliance in Request Classifier

**File:** `agents/coding_agent/orchestrator/request_classifier.py`
**Purpose:** Move from keyword-heavy to semantic understanding
**Changes:**

1. Reduce keyword lists by 70% (keep only 5-10 definitive indicators)
2. Increase LLM classification confidence threshold to 0.85
3. Add "semantic_analysis" field to classification result
4. Remove hardcoded pattern templates
   **Rationale:** Per CLAUDE.md Generalization Directive
   **Integration Points:**

- Used by `Orchestrator.handle_request()`
- Feeds into `TaskDecomposer`
  **Testing:**
- Test with 50+ sample requests
- Verify accuracy maintained or improved
- Measure classification time
  **Estimated Time:** 2 hours
  **Status:** 🔴 Not Started

---

## Phase 6: Testing & Validation (Days 11-14)

### Task 6.1: Unit Tests for New Components

**Files:**

- `tests/unit/test_request_interpreter.py`
- `tests/unit/test_context_manager.py`
- `tests/unit/test_new_debug_tools.py`
- `tests/unit/test_phase_transition.py`
  **Coverage Requirements:**
- 90%+ code coverage for new modules
- All edge cases tested
- Mock LLM responses for consistency
  **Estimated Time:** 4 hours
  **Status:** 🔴 Not Started

### Task 6.2: Integration Tests

**Files:**

- `tests/integration/test_enhanced_debug_flow.py`
- `tests/integration/test_tool_usage.py`
  **Scenarios:**
- End-to-end bug fix with new tools
- Context manager stress test
- Phase transition verification
- New tool integration
  **Estimated Time:** 3 hours
  **Status:** 🔴 Not Started

### Task 6.3: Documentation Updates

**Files:**

- `docs/AUTONOMOUS_DEBUG_LOOP_DESIGN.md` - Update for new components
- `docs/housekeeping/status-tracking/CHECKLIST_CODING_AGENT_IMPROVEMENTS.md` - Track completion
- `agents/coding_agent/prompts/README.md` - New prompt documentation
  **Estimated Time:** 2 hours
  **Status:** 🔴 Not Started

---

## Dependencies & Ordering

```
Phase 1 (Quick Fixes)
    ↓
Phase 2.2 (New Tools) ─→ Phase 3.1 (Context Manager)
    ↓                        ↓
Phase 2.1 (Interpreter) ←──┘
    ↓
Phase 3.2 (Phase Transition)
    ↓
Phase 4 (Prompt Improvements)
    ↓
Phase 5 (Classifier)
    ↓
Phase 6 (Testing)
```

---

## Risk Assessment

| Risk                                  | Impact | Mitigation                           |
| ------------------------------------- | ------ | ------------------------------------ |
| LLM behavior changes with new prompts | High   | A/B testing, gradual rollout         |
| Tool schema too large for context     | Medium | Tool categorization, dynamic loading |
| Context manager complexity            | Low    | Extensive unit testing               |
| Breaking existing workflows           | High   | Comprehensive integration tests      |

---

## Success Criteria

1. ✅ MAX_ITERATIONS = 10 (verified in config)
2. ✅ No duplicate code in debug_controller.py
3. ✅ Request Interpreter generates valid TO-DO lists for 95%+ of requests
4. ✅ All 34 tools have working implementations and tests
5. ✅ Context Manager preserves high-priority items in 100% of cases
6. ✅ Phase Transition correctly identifies incomplete diagnosis
7. ✅ LLM provides reasoning in 90%+ of responses
8. ✅ Classifier accuracy maintained with fewer keywords
9. ✅ All unit tests pass (90%+ coverage)
10. ✅ All integration tests pass

---

## Approval Required Before Proceeding

This plan requires approval before implementation begins. Please review:

1. Is the scope appropriate?
2. Is the timeline realistic?
3. Are there additional requirements?
4. Should any items be deprioritized?

---

## Version History

| Version | Date       | Changes      | Author |
| ------- | ---------- | ------------ | ------ |
| 1.0.0   | 2026-01-29 | Initial plan | Claude |

---

**END OF PLAN**
