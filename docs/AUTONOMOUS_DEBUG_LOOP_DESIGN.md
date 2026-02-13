# RAICA Autonomous Debug Loop Architecture

## Design Principles

1. **Project Context is King** - All context saved IN the project directory
2. **No Approvals Until Stuck** - Work autonomously, ask only when genuinely blocked
3. **Iterate Until Fixed** - Not a 1-shot, loop until bug eliminated
4. **Test-Driven Verification** - Generate bug-specific test, use it to verify fix
5. **Minimal Changes** - Fix the bug, don't refactor the world
6. **Incremental Fix-Verify** - For multi-file bugs, fix one unit at a time with verification
7. **Functional over Visual** - For GUI apps, test logic/state, leave visual to human

---

## Incremental Debug Mode (v1.0.0.5+)

For complex bugs spanning multiple files, the system uses **incremental decomposition**:

### Bug Decomposition Flow

```
Bug Description
       ↓
[ANALYSIS] Identify affected files
       ↓
[DECOMPOSITION] If multiple files affected:
       ↓
┌─────────────────────────────────────────────────┐
│  Break into TESTABLE UNITS:                     │
│  • Unit 1: "Validation logic fails" (FUNCTIONAL)│
│  • Unit 2: "API returns wrong status" (FUNCTIONAL)│
│  • Unit 3: "Button color incorrect" (VISUAL)    │
└─────────────────────────────────────────────────┘
       ↓
FOR EACH FUNCTIONAL UNIT (respecting dependencies):
  ┌───────────────────────────────────────────┐
  │ 1. Generate TARGETED unit test            │
  │ 2. Verify test FAILS (bug exists)         │
  │ 3. Apply MINIMAL fix for this unit        │
  │ 4. Verify test PASSES (unit fixed)        │
  │ 5. Quick regression check                 │
  │ 6. ✓ Continue to next unit                │
  └───────────────────────────────────────────┘
       ↓
[FINAL] Full regression test suite
       ↓
[VISUAL CHECKPOINT] List visual items for human verification
```

### Unit Types

| Type        | Description                        | Testing                     |
| ----------- | ---------------------------------- | --------------------------- |
| FUNCTIONAL  | Logic, state, data flow, API calls | Automated pytest/jest tests |
| VISUAL      | Colors, fonts, layout, appearance  | Human verification required |
| INTEGRATION | Multiple components together       | End-to-end tests            |

### Key Components

- **DebugDecomposer** (`debug_decomposer.py`) - Breaks bugs into testable units
- **generate_unit_test()** (`bug_test_generator.py`) - Creates targeted unit tests
- **DependencyResolver** (`dependency_resolver.py`) - Resolves missing packages using LLM heuristics
- **\_run_incremental_debug_loop()** (`debug_controller.py`) - Processes units one by one

### GUI/Web App Functional Testing

For GUI applications, we separate:

**Testable (Automated):**

- Function return values
- State changes after operations
- Event handler logic
- Data validation
- API calls and responses
- Error handling paths

**Not Testable (Human Verification):**

- Colors, fonts, sizes
- Layout and positioning
- Animation smoothness
- Overall appearance

---

## Storage: Project-Local Context

```
{project_dir}/
  .raica/
    debug_session.json      # Current debug session state
    conversation.json       # All user interactions for this project
    iterations/
      001_analysis.json     # Each debug iteration preserved
      002_fix_attempt.json
      003_test_result.json
    test_cases/
      bug_specific_test.py  # Auto-generated test for THIS bug
    decisions.json          # Key decisions made
    root_cause.json         # Identified root cause (when found)
```

### Session State Schema

```python
DebugSession:
  session_id: str
  started_at: datetime
  bug_description: str           # User's original description
  error_trace: Optional[str]     # Stack trace if provided

  # Iterative State
  current_iteration: int
  iterations: List[DebugIteration]

  # Root Cause Tracking
  root_cause_identified: bool
  root_cause: Optional[RootCause]
  confidence: float              # 0.0 - 1.0

  # Fix Tracking
  fix_applied: bool
  fix_verified: bool
  files_modified: List[str]

  # Test State
  bug_test_path: Optional[str]   # Path to generated test
  bug_test_passes: bool          # Does test pass now?

  # Status
  status: Enum[ANALYZING, FIXING, TESTING, BLOCKED, COMPLETE]
  blocked_reason: Optional[str]  # Why we're stuck (if BLOCKED)
```

---

## The Autonomous Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS DEBUG LOOP                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  START: User provides bug description + optional stack trace    │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: UNDERSTAND                                      │   │
│  │  - Read error trace                                       │   │
│  │  - Identify affected files                                │   │
│  │  - Analyze code paths                                     │   │
│  │  - Formulate hypothesis                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: GENERATE BUG-SPECIFIC TEST                      │   │
│  │  - Create test that REPRODUCES the bug                    │   │
│  │  - Test MUST FAIL before fix                              │   │
│  │  - Save to .raica/test_cases/bug_test_xxx.py              │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: VERIFY TEST FAILS (confirms bug exists)         │   │
│  │  - Run the bug-specific test                              │   │
│  │  - If PASSES: hypothesis wrong → back to UNDERSTAND       │   │
│  │  - If FAILS: bug confirmed → proceed to FIX               │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: APPLY MINIMAL FIX                               │   │
│  │  - Generate smallest change to fix root cause             │   │
│  │  - Apply changes (baseline captured automatically)        │   │
│  │  - NO approval needed (protected by baseline)             │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 5: VERIFY FIX                                      │   │
│  │  - Run bug-specific test again                            │   │
│  │  - If FAILS: fix didn't work → back to UNDERSTAND         │   │
│  │  - If PASSES: proceed to regression check                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PHASE 6: CHECK FOR REGRESSIONS                           │   │
│  │  - Run all existing project tests                         │   │
│  │  - If new failures: rollback → try alternative fix        │   │
│  │  - If no regressions: FIX COMPLETE                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ↓                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  COMPLETE: Report to User                                 │   │
│  │  - What was the root cause                                │   │
│  │  - What was changed (minimal diff)                        │   │
│  │  - Test results (bug test + regression tests)             │   │
│  │  - Iteration count                                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  BLOCKED STATE (only time we ask user):                         │
│  - Cannot reproduce bug with any test                           │
│  - Cannot identify root cause after N iterations                │
│  - Multiple conflicting hypotheses                              │
│  - Need clarification on expected behavior                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Changes from Current Architecture

### 1. REMOVE These Approval Points

| Current Approval                                | Replace With                                               |
| ----------------------------------------------- | ---------------------------------------------------------- |
| Early clarifications (scope, tests, confidence) | **Auto-select**: minimal scope, run tests, high confidence |
| Complex fix confirmation                        | **Auto-proceed**: protected by baseline                    |
| Orchestrator command approval                   | **Auto-approve**: for read/analysis commands               |
| Plan approval                                   | **Skip**: just execute                                     |

### 2. ADD These Components

#### A. Bug-Specific Test Generator

```python
class BugTestGenerator:
    """Generate a test that reproduces the specific bug."""

    async def generate_bug_test(
        self,
        bug_description: str,
        error_trace: Optional[str],
        affected_files: List[str]
    ) -> str:
        """
        Generate a pytest test that:
        1. Sets up the conditions that trigger the bug
        2. Calls the code path that fails
        3. Asserts the INCORRECT behavior (will fail after fix)

        Returns: Path to generated test file
        """

    async def verify_test_fails(self, test_path: str) -> bool:
        """Run test, confirm it FAILS (bug exists)."""

    async def verify_test_passes(self, test_path: str) -> bool:
        """Run test, confirm it PASSES (bug fixed)."""
```

#### B. Autonomous Debug Controller

```python
class AutonomousDebugController:
    """Controls the autonomous debug loop."""

    MAX_ITERATIONS = 10

    async def debug_until_fixed(
        self,
        bug_description: str,
        error_trace: Optional[str] = None
    ) -> DebugResult:
        """
        Main loop - iterate until bug is fixed or we're stuck.

        NO approvals requested unless truly blocked.
        """
        session = self._load_or_create_session()

        while session.current_iteration < self.MAX_ITERATIONS:
            session.current_iteration += 1

            # Phase 1: Understand
            hypothesis = await self._analyze_bug(session)
            if not hypothesis:
                return self._report_blocked("Cannot identify root cause")

            # Phase 2: Generate bug-specific test
            test_path = await self._generate_bug_test(session, hypothesis)

            # Phase 3: Verify test fails (confirms hypothesis)
            if await self._test_passes(test_path):
                # Hypothesis wrong - test doesn't reproduce bug
                session.log("Hypothesis incorrect - test passes. Retrying.")
                continue

            # Phase 4: Apply minimal fix
            await self._apply_fix(session, hypothesis)

            # Phase 5: Verify fix works
            if not await self._test_passes(test_path):
                # Fix didn't work
                await self._rollback()
                session.log("Fix didn't work. Retrying with new approach.")
                continue

            # Phase 6: Check regressions
            regressions = await self._check_regressions(session)
            if regressions:
                await self._rollback()
                session.log(f"Fix caused regressions: {regressions}. Retrying.")
                continue

            # SUCCESS!
            return self._report_success(session)

        return self._report_blocked(f"Exceeded {self.MAX_ITERATIONS} iterations")
```

#### C. Project Context Manager

```python
class ProjectDebugContext:
    """Manages persistent debug context for a project."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.context_dir = project_dir / ".raica"
        self._ensure_dirs()

    def load_session(self) -> Optional[DebugSession]:
        """Load existing debug session if any."""

    def save_session(self, session: DebugSession) -> None:
        """Save session state to project directory."""

    def add_iteration(self, iteration: DebugIteration) -> None:
        """Record an iteration attempt."""

    def get_conversation_history(self) -> List[Message]:
        """Get all user interactions for this project."""

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
```

---

## Implementation Priority

### Phase 1: Core Loop (High Priority)

1. Create `AutonomousDebugController` class
2. Create `BugTestGenerator` class
3. Create `ProjectDebugContext` for persistence
4. Remove approval points in debug flow

### Phase 2: Test Integration (Medium Priority)

1. Bug-specific test generation via LLM
2. Test execution and result parsing
3. Test result storage in session

### Phase 3: Intelligence (Lower Priority)

1. Multi-hypothesis tracking
2. Learning from failed attempts
3. Cross-project pattern recognition

---

## Entry Point Changes

### Current (agent_runner.py)

```python
# Current: Multiple approval points
result = await self._handle_code_debug_request(request, classification)
```

### Proposed

```python
# New: Autonomous loop
controller = AutonomousDebugController(
    project_dir=self._project_dir,
    llm_client=self._llm_client
)

# No approvals - runs until fixed or blocked
result = await controller.debug_until_fixed(
    bug_description=request,
    error_trace=self._extract_error_trace(request)
)

# Only interact with user at the END
if result.status == DebugStatus.COMPLETE:
    self.output.add_success(f"Bug fixed in {result.iterations} iterations")
    self.output.add_info(f"Root cause: {result.root_cause}")
    self.output.add_info(f"Files modified: {result.files_modified}")
elif result.status == DebugStatus.BLOCKED:
    self.output.add_warning(f"Need help: {result.blocked_reason}")
    # NOW we ask user
```

---

## Configuration

```yaml
# config/agents_config.yaml

autonomous_debug:
  enabled: true
  max_iterations: 10

  # When to ask user (only these cases)
  ask_user_when:
    - cannot_reproduce_bug
    - cannot_identify_root_cause
    - conflicting_hypotheses
    - need_expected_behavior

  # Auto-approve everything else
  auto_approve:
    - file_reads
    - code_analysis
    - test_execution
    - fix_application # Protected by baseline
    - rollback # Safety mechanism

  # Test generation
  generate_bug_test: true
  require_test_fails_first: true # Confirm bug exists
  require_test_passes_after: true # Confirm bug fixed
```

---

## Summary: What Changes

| Component | Current | New |
| Component | Current | New |
| -------------------- | ---------------------------- | --------------------------------------------------------- |
| **Approvals** | 5+ interruptions | 0 unless truly blocked |
| **Persistence** | Single state file | Full project context in `.raica/` |
| **Iterations** | 1-shot + retry on regression | Loop until fixed (max 10) |
| **Testing** | Run existing tests | Generate bug-specific test first |
| **User Interaction** | Throughout process | Only at end (success or blocked) |
| **Fix Strategy** | Apply and hope | Test fails → fix → test passes (incl. LLM-driven dependency resolution) |

This design transforms RAICA from an "assistant that asks permission" to an "autonomous debugger that reports results."
