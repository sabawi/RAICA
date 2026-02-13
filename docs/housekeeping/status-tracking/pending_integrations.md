# Pending Integrations & Technical Debt

**Date:** 2026-01-29
**Status:** Open

The following items were implemented as standalone components in Phases 2.2 and 3 and require integration into the main agent orchestration logic in subsequent phases (Phase 4: Tool Usage & Reasoning, Phase 5: Orchestration).

## From Phase 2.2 (Debug Tools)

- [ ] **Integration Test with Executor**: The 10 new debug tools (`analyze_project`, `create_test`, `run_tests`, etc.) were unit tested but have not been tested within the `ToolExecutor` loop or `InteractiveAgent`.
  - _Action_: Verify end-to-end tool execution in Phase 6 (Integration Testing).

## From Phase 3.1 (Context Manager)

- [ ] **Integration with ToolCallingClient**: The `ContextManager` class is implemented but not instantiated or used in `ToolCallingClient` or the main system prompt generation logic.
  - _Action_: Modify `ToolCallingClient` to use `ContextManager` for compiling prompts instead of raw string concatenation.
- [ ] **Integration with GeneralizedDebugEngine**: Similarly, the debug engine needs to push context (tool outputs, error traces) into the `ContextManager`.

## From Phase 3.2 (Phase Transition)

- [ ] **Integration with DebugOrchestrator**: The `validate_phase_transition()` method exists in `GuidancePlanner`, but the `DebugOrchestrator` (or `AgentRunner`) loop does not yet call it to determine when to switch from Diagnosis to Fix mode.
  - _Action_: Update the main loop to await `validate_phase_transition` after diagnosis steps and branch logic accordingly.
- [ ] **PhaseGate Class**: Originally planned as a separate class, the logic was implemented directly in `GuidancePlanner`. Evaluate if a separate class is needed during refactoring.

## From Phase 4 (Tool Usage & Reasoning)

- [ ] **Reasoning / Chain-of-Thought**: Phase 4.2 (adding explicit reasoning fields to JSON output) was skipped to prioritize stability.
  - _Action_: Revisit in Phase 6. Consider adding a `"reasoning"` field to the tool call schema or a separate `"thought"` step.
- [ ] **End-to-End LLM Verification**: Prompt injection was verified via unit tests, but actual LLM performance with the new examples needs empirical validation.

## Summary

The core logic for tools, context management, and phase transition checks is **complete and unit-tested**. The **wiring** of these components into the active agent loop is **deferred** to the Orchestration phase to ensure a stable migration from the legacy loop.
