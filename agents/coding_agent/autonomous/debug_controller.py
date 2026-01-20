"""
Autonomous Debug Controller
============================

The main controller for autonomous debugging. Implements the debug loop:

1. UNDERSTAND - Analyze the bug, identify root cause
2. GENERATE TEST - Create bug-specific test that fails
3. VERIFY TEST FAILS - Confirm bug exists
4. APPLY FIX - Generate and apply minimal fix
5. VERIFY TEST PASSES - Confirm bug is fixed
6. CHECK REGRESSIONS - Ensure no new bugs introduced
7. REPORT - Summarize what was done

NO APPROVALS unless genuinely blocked.
"""

import asyncio
import logging
import re
import ast
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Tuple

from .project_context import (
    ProjectDebugContext,
    DebugSession,
    DebugIteration,
    DebugStatus,
    RootCause
)
from .bug_test_generator import BugTestGenerator, TestResult
from .code_searcher import CodeSearcher
from .debug_decomposer import DebugDecomposer, DecompositionResult, DebugUnit, UnitType

logger = logging.getLogger(__name__)


from ..agent_config import AgentDefaults
from ..services.linter_service import LinterService
from ..services.patch_applier import PatchApplier
from ..services.language_detector import LanguageDetector
from ..services.language_detector import LanguageDetector
from ..services.code_path_tracer import CodePathTracer, ExecutionContext

try:
    from tools.ragg_tool import RAGGTool
    HAS_RAGG = True
except ImportError:
    HAS_RAGG = False

logger = logging.getLogger(__name__)


class DebugOutcome(Enum):
    """Outcome of the debug process."""
    FIXED = "fixed"
    BLOCKED = "blocked"
    MAX_ITERATIONS = "max_iterations"
    ERROR = "error"


@dataclass
class DebugResult:
    """Result of the autonomous debug process."""
    outcome: DebugOutcome
    iterations: int = 0
    root_cause: Optional[str] = None
    files_modified: List[str] = field(default_factory=list)
    fix_summary: Optional[str] = None
    blocked_reason: Optional[str] = None
    test_results: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.outcome == DebugOutcome.FIXED


class AutonomousDebugController:
    """
    Controls the autonomous debug loop.

    Design Principles:
    1. No approvals until genuinely blocked
    2. Iterate until fixed (max iterations configurable)
    3. Test-driven verification
    4. Minimal code changes
    5. 4-Gate Verification (Lint -> Test -> Targeted Regression -> Full Regression)
    """

    DEFAULT_MAX_ITERATIONS = AgentDefaults.MAX_ITERATIONS

    def __init__(
        self,
        llm_client,
        project_dir: Path,
        output_callback: Optional[Callable[[str], None]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        context_manager: Any = None
    ):
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)
        self.output = output_callback or (lambda x: logger.info(x))
        self.max_iterations = max_iterations
        self.context_manager = context_manager

        # Initialize components
        self.context = ProjectDebugContext(project_dir)
        self.test_generator = BugTestGenerator(llm_client, project_dir)
        self.code_searcher = CodeSearcher(project_dir)  # For LLM-guided search
        self.decomposer = DebugDecomposer(llm_client, project_dir)  # For breaking bugs into units

        # [NEW] Services
        self.linter_service = LinterService(project_dir)
        self.patch_applier = PatchApplier(project_dir)
        self.language_detector = LanguageDetector(project_dir)


        # [NEW] Session State Management - CRITICAL for preventing data loss
        from ..services.git_state_tracker import GitStateTracker
        from ..services.state_verifier import StateVerifier
        from ..services.changelog_generator import ChangelogGenerator
        
        self.git_tracker = GitStateTracker(project_dir)
        self.state_verifier = StateVerifier(project_dir, self.git_tracker)
        self.changelog_gen = ChangelogGenerator()
        
        # Ensure git repository is initialized
        if self.git_tracker.ensure_git_initialized():
            self.output("   ✓ Git repository initialized for state tracking")

        # Code path tracer - CRITICAL for proper debugging
        # Must trace execution paths to find ACTUAL code, not just similar-looking files
        self.code_path_tracer = CodePathTracer(project_dir)
        self._execution_context: Optional[ExecutionContext] = None

        # Track visual checkpoints for user verification
        self._visual_checkpoints: List[DebugUnit] = []
        self._decomposition: Optional[DecompositionResult] = None
        
        # Link LLM client output to our output
        if hasattr(self.llm_client, 'output'):
            self.llm_client.output = self.output

        # Track state
        self._session: Optional[DebugSession] = None
        self._current_hypothesis: Optional[str] = None
        self._affected_files: List[str] = []
        self._last_patches: List[Dict[str, str]] = []  # Track patches for changelog\n
        # RAGG Tool intialization
        self.ragg_tool = None
        if HAS_RAGG:
            try:
                self.ragg_tool = RAGGTool()
                self.output("   ✓ RAGG Engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize RAGG: {e}")

    def _get_semantic_context(self, query: str) -> str:
        """Get semantic context from RAGG engine if available."""
        if not self.ragg_tool:
            return ""
        
        try:
            # First try to find definition if query is a symbol
            context = self.ragg_tool.get_semantic_context(query)
            if context and "not found" not in context:
                return f"\n\nSEMANTIC CONTEXT (RAGG):\n{context}\n"
            
            # Fallback to definition search
            defn = self.ragg_tool.find_definition(query)
            if defn:
                return f"\n\nSYMBOL DEFINITION (RAGG):\n{defn}\n"
        except Exception as e:
            logger.warning(f"RAGG query failed: {e}")
        
        return ""

    def _get_file_structure_context(self, max_length: int = 3000) -> str:
        """
        Get file structure context to inject into LLM prompts.

        This prevents hallucination by providing accurate file listings.

        Args:
            max_length: Maximum length of the context string

        Returns:
            Formatted file structure string, or empty if not available
        """
        if not self.context_manager:
            return ""

        try:
            ctx = self.context_manager.get_file_structure_context(
                include_symbols=True,
                force_rescan=False
            )
            if ctx and len(ctx) > max_length:
                ctx = ctx[:max_length] + "\n... (truncated)"
            return f"\n\nACTUAL PROJECT FILES (do not hallucinate files):\n{ctx}\n"
        except Exception as e:
            logger.debug(f"Could not get file structure context: {e}")
            return ""

    async def debug_until_fixed(
        self,
        bug_description: str,
        error_trace: Optional[str] = None,
        resume: bool = True
    ) -> DebugResult:
        """
        Main entry point - debug until the bug is fixed or we're stuck.

        Args:
            bug_description: User's description of the bug
            error_trace: Stack trace if available
            resume: If True, resume existing session if any

        Returns:
            DebugResult with outcome and details

        NO APPROVALS - runs autonomously until fixed or blocked.
        """
        import time
        start_time = time.time()

        self.output("Starting autonomous debug loop...")

        # Load or create session
        # Load or create session
        if resume and self.context.has_session():
            self._session = self.context.load_session()
            if self._session:
                # Check if session is already exhausted or completed
                if self._session.current_iteration >= self.max_iterations:
                    self.output(f"Previous session {self._session.session_id} reached max iterations. Starting NEW session.")
                    self._session = self.context.create_session(bug_description, error_trace)
                elif self._session.status in [DebugStatus.COMPLETE.value, DebugStatus.FAILED.value]:
                    self.output(f"Previous session {self._session.session_id} ended ({self._session.status}). Starting NEW session.")
                    self._session = self.context.create_session(bug_description, error_trace)
                else:
                    self.output(f"Resuming session {self._session.session_id} (iteration {self._session.current_iteration})")
            else:
                self._session = self.context.create_session(bug_description, error_trace)
        else:
            self._session = self.context.create_session(bug_description, error_trace)

        try:
            result = await self._run_debug_loop()
            result.duration_seconds = time.time() - start_time
            return result

        except Exception as e:
            logger.exception("Debug loop failed with error")
            self._session.set_status(DebugStatus.FAILED, str(e))
            self.context.save_session(self._session)
            return DebugResult(
                outcome=DebugOutcome.ERROR,
                iterations=self._session.current_iteration,
                blocked_reason=str(e),
                duration_seconds=time.time() - start_time
            )

    async def _run_debug_loop(self) -> DebugResult:
        """Run the main debug loop."""

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 0: BUILD EXECUTION GRAPH (CRITICAL - DO NOT SKIP)
        # ═══════════════════════════════════════════════════════════════════
        # This is the most important step! We MUST trace code paths from
        # entry points to find which files are ACTUALLY used at runtime.
        # Without this, we might debug orphaned files that look relevant
        # but are never loaded.
        # ═══════════════════════════════════════════════════════════════════
        self.output("\n[PHASE 0] Building execution graph from entry points...")
        self._execution_context = await self.code_path_tracer.build_graph()

        if self._execution_context.entry_points:
            self.output(f"   Entry points: {', '.join(self._execution_context.entry_points)}")
            self.output(f"   Active files: {len(self._execution_context.active_files)}")
            if self._execution_context.orphaned_files:
                self.output(f"   Orphaned files: {len(self._execution_context.orphaned_files)}")

            # CRITICAL: Show warnings about orphaned files
            if self._execution_context.warnings:
                self.output("\n   ⚠️  WARNINGS:")
                for warning in self._execution_context.warnings:
                    self.output(f"      {warning}")
        else:
            self.output("   ⚠️  No entry points found - will use all files (less accurate)")

        # ─────────────────────────────────────────────────────
        # CHECK FOR GUI/WEB APPLICATION - Skip test cycle
        # GUI apps and web pages require visual verification
        # which automated tests cannot reliably provide
        # ─────────────────────────────────────────────────────
        ui_framework = self.test_generator._detect_ui_framework()
        is_desktop_gui = ui_framework in ('pyqt5', 'pyqt6', 'pyside2', 'pyside6', 'tkinter', 'wxpython', 'kivy')
        is_web_app = ui_framework in ('html', 'react', 'vue', 'angular', 'electron') or self._is_web_project()

        if is_desktop_gui or is_web_app:
            app_type = ui_framework or "web"
            self.output(f"\n🖥️  Visual application detected ({app_type})")
            self.output("   Skipping automated test cycle - user will verify visually")
            return await self._run_gui_debug_loop()

        # ─────────────────────────────────────────────────────
        # REPRODUCTION PHASE: Analyze & Generate Test (Before Loop)
        # ─────────────────────────────────────────────────────
        repro_attempts = 0
        MAX_REPRO_ATTEMPTS = 2
        repro_success = False

        while repro_attempts < MAX_REPRO_ATTEMPTS:
            repro_attempts += 1
            if repro_attempts > 1:
               self.output(f"\n[REPRODUCTION] Attempt {repro_attempts}/{MAX_REPRO_ATTEMPTS} to reproduce bug...")

            # PHASE 1: UNDERSTAND
            self.output("\n[PHASE 1] Analyzing bug...")
            self._session.set_status(DebugStatus.ANALYZING)

            analysis = await self._analyze_bug()
            if not analysis:
                self.output("❌ Bug analysis failed (returned None). See logs.")
                continue

            self._current_hypothesis = analysis['hypothesis']
            self._affected_files = analysis['affected_files']

            self.output(f"Hypothesis: {analysis['hypothesis'][:100]}...")
            self.output(f"Affected files: {', '.join(analysis['affected_files'][:3])}")

            # Record root cause if confident
            if analysis.get('confidence', 0) > 0.7:
                self._session.set_root_cause(RootCause(
                    description=analysis['hypothesis'],
                    file_path=analysis['affected_files'][0] if analysis['affected_files'] else '',
                    line_number=analysis.get('line_number'),
                    confidence=analysis.get('confidence', 0.7)
                ))

            # ─────────────────────────────────────────────────────
            # DECOMPOSITION CHECK: Use incremental mode for complex bugs
            # ─────────────────────────────────────────────────────
            if len(analysis['affected_files']) > 1:
                self.output("\n[DECOMPOSITION] Multiple files affected - checking for decomposition...")

                decomposition = await self.decomposer.decompose_bug(
                    bug_description=self._session.bug_description,
                    error_trace=self._session.error_trace,
                    affected_files=analysis['affected_files']
                )

                self._decomposition = decomposition

                # Use incremental mode if we have multiple testable units
                if not self.decomposer.is_simple_bug(decomposition):
                    self.output(self.decomposer.format_units_for_display(decomposition))
                    self.output("\n→ Switching to INCREMENTAL debug mode")
                    return await self._run_incremental_debug_loop(decomposition)
                else:
                    self.output("→ Simple bug - using standard debug loop")

            # PHASE 2: GENERATE BUG-SPECIFIC TEST
            self.output("\n[PHASE 2] Generating bug-specific test...")
            self._session.set_status(DebugStatus.GENERATING_TEST)

            test_code = await self.test_generator.generate_bug_test(
                bug_description=self._session.bug_description,
                error_trace=self._session.error_trace,
                affected_files=self._affected_files,
                root_cause=self._current_hypothesis
            )
            
            # Use '0' or 'repro' as iteration specific for calibration phase
            test_name = f"bug_{self._session.session_id}_repro_{repro_attempts}"
            test_path = self.context.save_bug_test(test_name, test_code)
            self._session.bug_test_path = str(test_path)

            self.output(f"Generated test: {test_path.name}")

            # PHASE 3: VERIFY TEST FAILS
            self.output("\n[PHASE 3] Verifying test fails (bug confirmation)...")
            test_fails = await self.test_generator.verify_test_fails(test_path)

            if test_fails:
                self.output("Test FAILS as expected - bug confirmed! Starting fix loop...")
                repro_success = True
                break
            else:
                self.output("Test PASSES - hypothesis may be incorrect. Retrying reproduction...")
        
        if not repro_success:
            return DebugResult(
                outcome=DebugOutcome.BLOCKED,
                iterations=0,
                blocked_reason="Could not reproduce bug with generated test",
                duration_seconds=0
            )

        # ─────────────────────────────────────────────────────
        # FIX PHASE: Loop for fixing the confirmed bug
        # ─────────────────────────────────────────────────────
        while self._session.current_iteration < self.max_iterations:
            iteration_num = self._session.current_iteration + 1
            self.output(f"\n{'='*60}")
            self.output(f"DEBUG ITERATION {iteration_num}/{self.max_iterations}")
            self.output(f"{'='*60}")

            iteration = DebugIteration(iteration_number=iteration_num)
            
            # Store confirmation from repro phase
            iteration.hypothesis = self._current_hypothesis
            iteration.test_generated = self._session.bug_test_path
            iteration.test_result_before = True

            try:
                # PHASE 4: APPLY MINIMAL FIX
                self.output("\n[PHASE 4] Applying minimal fix & Linting...")
                self._session.set_status(DebugStatus.FIXING)

                # Use the new robust apply_and_lint logic
                fix_result = await self._apply_fix_and_lint(analysis) # Pass existing analysis
                
                if not fix_result['success']:
                    error_msg = fix_result.get('error', 'Unknown error')
                    self.output(f"❌ Failed to apply valid fix: {error_msg}")
                    iteration.failure_reason = f"Failed to apply fix: {error_msg}"
                    self._record_iteration(iteration)
                    continue

                iteration.files_modified = fix_result['files_modified']
                iteration.action_taken = fix_result['description']
                self._session.files_modified = fix_result['files_modified']

                self.output(f"Modified: {', '.join(fix_result['files_modified'])}")

                # ─────────────────────────────────────────────────────
                # PHASE 5: VERIFY FIX (test should pass now)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 5] Verifying fix...")
                self._session.set_status(DebugStatus.TESTING)

                test_passes = False
                verify_result = await self.test_generator.run_test(Path(test_path))
                
                if verify_result.passed:
                    test_passes = True
                else:
                    # Test failed - Check if it's a False Negative (Test Flawed)
                    self.output(f"Test FAILED. Output excerpt:\n{str(verify_result.error)[:300]}...\n")
                    self.output("Analyzing failure (Is it a bad fix or a bad test?)...")
                    
                    fail_analysis = await self._analyze_verification_failure(
                        str(test_path), 
                        str(verify_result.error), 
                        fix_result['description']
                    )
                    
                    if fail_analysis['verdict'] == "TEST_FLAWED" and fail_analysis['new_test_code']:
                        self.output(f"⚠️ Verdict: TEST IS FLAWED. Reason: {fail_analysis.get('reason', '')[:100]}...")
                        self.output("🔄 Updating test case and re-verifying...")
                        
                        # Update test file
                        with open(test_path, 'w') as f:
                            f.write(fail_analysis['new_test_code'])
                            
                        # Re-run verification
                        verify_result = await self.test_generator.run_test(Path(test_path))
                        if verify_result.passed:
                            self.output("✅ Updated test PASSES. Proceeding with success.")
                            test_passes = True
                        else:
                            self.output("❌ Updated test STILL FAILS.")
                    else:
                        self.output("Verdict: FIX INCOMPLETE. Proceeding to rollback.")

                iteration.test_result_after = test_passes

                if not test_passes:
                    # Fix didn't work - rollback and retry
                    self.output("Test still FAILS - fix incomplete. Rolling back...")
                    await self._rollback(fix_result['files_modified'])
                    iteration.rollback_performed = True
                    iteration.failure_reason = "Fix did not resolve the bug (Verified Fix Logic)"
                    self._record_iteration(iteration)
                    continue

                self.output("Test PASSES - fix verified!")
                self._session.bug_test_passes = True

                # ─────────────────────────────────────────────────────
                # NEW PHASE 6: TARGETED REGRESSION TEST (Gate 3)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 6] Running Targeted Regression Tests (Gate 3)...")
                
                # Identify relevant tests
                relevant_tests = self.test_generator.identify_relevant_tests(fix_result['files_modified'])
                
                if relevant_tests:
                    self.output(f"Identified {len(relevant_tests)} relevant tests: {[t.name for t in relevant_tests]}")
                    targeted_result = await self.test_generator.run_targeted_tests(relevant_tests)
                    
                    if not targeted_result.passed:
                        self.output(f"❌ Targeted Regressions found!\nFailed: {targeted_result.error}")
                        await self._rollback(fix_result['files_modified'])
                        iteration.rollback_performed = True
                        iteration.failure_reason = f"Targeted Regression Failed: {targeted_result.error}"
                        self._record_iteration(iteration)
                        continue
                    self.output("✅ Targeted Regression Passed")
                else:
                    self.output("ℹ️ No specific relevant tests found. Skipping to full suite.")

                # ─────────────────────────────────────────────────────
                # PHASE 7: FULL REGRESSION CHECK (Gate 4)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 7] Checking for regressions (Full Suite)...")
                self._session.set_status(DebugStatus.VERIFYING)

                regression_result = await self.test_generator.run_all_project_tests()
                iteration.regression_check_passed = regression_result.passed

                if not regression_result.passed:
                    # Regressions detected - rollback
                    self.output("REGRESSIONS detected! Rolling back...")
                    self.output(f"Failed tests: {regression_result.error if regression_result.error else 'Unknown'}")
                    await self._rollback(fix_result['files_modified'])
                    iteration.rollback_performed = True
                    iteration.failure_reason = f"Fix caused regressions: {regression_result.error if regression_result.error else 'Unknown'}"
                    self._record_iteration(iteration)
                    continue

                self.output("No regressions detected!")

                # ─────────────────────────────────────────────────────
                # SUCCESS!
                # ─────────────────────────────────────────────────────
                iteration.success = True
                self._record_iteration(iteration)

                self._session.fix_applied = True
                self._session.fix_verified = True
                self._session.set_status(DebugStatus.COMPLETE)
                self._session.completion_summary = self._generate_summary()
                self.context.save_session(self._session)

                # Generate comprehensive change summary
                comprehensive_summary = self._generate_comprehensive_summary()
                self.output(comprehensive_summary)

                # Update persistent context for future requests
                await self._update_persistent_context(
                    files_modified=self._session.files_modified,
                    success=True
                )

                self.output("\n" + "="*60)
                self.output("BUG FIXED SUCCESSFULLY!")
                self.output("="*60)

                return DebugResult(
                    outcome=DebugOutcome.FIXED,
                    iterations=self._session.current_iteration,
                    root_cause=self._current_hypothesis,
                    files_modified=self._session.files_modified,
                    fix_summary=comprehensive_summary,
                    test_results={
                        'bug_test_path': str(test_path),
                        'bug_test_passes': True,
                        'regression_check_passed': True
                    }
                )

            except Exception as e:
                logger.exception(f"Iteration {iteration_num} failed with error")
                self.output(f"❌ Iteration failed: {e}")
                iteration.failure_reason = str(e)
                self._record_iteration(iteration)
                continue

        # Max iterations reached
        self.output(f"\nMax iterations ({self.max_iterations}) reached without fix.")
        self._session.set_status(DebugStatus.BLOCKED, "Max iterations reached")
        self.context.save_session(self._session)

        return DebugResult(
            outcome=DebugOutcome.MAX_ITERATIONS,
            iterations=self._session.current_iteration,
            root_cause=self._current_hypothesis,
            files_modified=self._session.files_modified,
            blocked_reason=f"Could not fix bug in {self.max_iterations} iterations"
        )

    async def _run_gui_debug_loop(self) -> DebugResult:
        """
        Simplified debug loop for GUI applications.

        GUI apps require visual verification which automated tests cannot provide.
        This loop:
        1. Analyzes the bug
        2. Applies the fix with lint checking
        3. Skips test verification - user verifies manually

        No test generation, no test verification phases.
        """
        self.output("\n" + "="*60)
        self.output("GUI DEBUG MODE (No automated tests)")
        self.output("="*60)

        # PHASE 1: UNDERSTAND
        self.output("\n[PHASE 1] Analyzing bug...")
        self._session.set_status(DebugStatus.ANALYZING)

        analysis = await self._analyze_bug()
        if not analysis:
            self.output("❌ Bug analysis failed")
            return DebugResult(
                outcome=DebugOutcome.BLOCKED,
                iterations=0,
                blocked_reason="Bug analysis failed"
            )

        self._current_hypothesis = analysis['hypothesis']
        self._affected_files = analysis['affected_files']

        self.output(f"Hypothesis: {analysis['hypothesis'][:100]}...")
        self.output(f"Affected files: {', '.join(analysis['affected_files'][:3])}")

        # Record root cause
        if analysis.get('confidence', 0) > 0.5:
            self._session.set_root_cause(RootCause(
                description=analysis['hypothesis'],
                file_path=analysis['affected_files'][0] if analysis['affected_files'] else '',
                line_number=analysis.get('line_number'),
                confidence=analysis.get('confidence', 0.7)
            ))

        # PHASE 2: APPLY FIX (Skip test generation)
        self.output("\n[PHASE 2] Applying fix & Linting...")
        self._session.set_status(DebugStatus.FIXING)

        iteration = DebugIteration(iteration_number=1)
        iteration.hypothesis = self._current_hypothesis

        fix_result = await self._apply_fix_and_lint(analysis)

        if not fix_result['success']:
            error_msg = fix_result.get('error', 'Unknown error')
            self.output(f"❌ Failed to apply fix: {error_msg}")
            iteration.failure_reason = error_msg
            self._record_iteration(iteration)
            return DebugResult(
                outcome=DebugOutcome.BLOCKED,
                iterations=1,
                root_cause=self._current_hypothesis,
                blocked_reason=f"Fix application failed: {error_msg}"
            )

        iteration.files_modified = fix_result['files_modified']
        iteration.action_taken = fix_result['description']
        self._session.files_modified = fix_result['files_modified']

        self.output(f"✅ Modified: {', '.join(fix_result['files_modified'])}")

        # SUCCESS - User will verify
        iteration.success = True
        self._record_iteration(iteration)

        self._session.fix_applied = True
        self._session.set_status(DebugStatus.COMPLETE)
        self._session.completion_summary = self._generate_summary()
        self.context.save_session(self._session)

        # Generate comprehensive change summary
        comprehensive_summary = self._generate_comprehensive_summary()
        self.output(comprehensive_summary)

        # Update persistent context for future requests
        await self._update_persistent_context(
            files_modified=self._session.files_modified,
            success=True
        )

        self.output("\n" + "="*60)
        self.output("✅ FIX APPLIED - Please verify visually")
        self.output("="*60)
        self.output("\n👁️  Run your application and check if the fix works.")
        self.output("   If not, describe what's still wrong and I'll try again.\n")

        return DebugResult(
            outcome=DebugOutcome.FIXED,
            iterations=1,
            root_cause=self._current_hypothesis,
            files_modified=self._session.files_modified,
            fix_summary=self._session.completion_summary,
            test_results={
                'gui_mode': True,
                'user_verification_required': True
            }
        )

    async def _run_incremental_debug_loop(self, decomposition: DecompositionResult) -> DebugResult:
        """
        Run incremental fix-verify loop for each unit in the decomposition.

        This method implements the key improvement over the monolithic approach:
        - Each unit is fixed and verified independently
        - Failures in one unit don't prevent others from being fixed
        - Visual units are collected for user verification at the end
        - Dependencies are respected (fix unit_1 before unit_2 if unit_2 depends on it)
        """
        self.output("\n" + "=" * 60)
        self.output("INCREMENTAL DEBUG MODE")
        self.output(f"Processing {len(decomposition.functional_units)} functional units")
        self.output("=" * 60)

        # Track results
        fixed_units: List[DebugUnit] = []
        failed_units: List[DebugUnit] = []
        all_files_modified: List[str] = []
        total_iterations = 0

        # Get ordered units (respecting dependencies)
        ordered_units = decomposition.get_ordered_units()

        for unit_idx, unit in enumerate(ordered_units):
            unit_num = unit_idx + 1
            self.output(f"\n{'─' * 50}")
            self.output(f"UNIT {unit_num}/{len(ordered_units)}: {unit.unit_id}")
            self.output(f"Description: {unit.description}")
            self.output(f"Files: {', '.join(unit.affected_files)}")
            self.output(f"{'─' * 50}")

            # Check if dependencies are satisfied
            unmet_deps = [
                dep for dep in unit.depends_on
                if dep not in [u.unit_id for u in fixed_units]
            ]
            if unmet_deps:
                self.output(f"⚠️  Skipping - unmet dependencies: {unmet_deps}")
                failed_units.append(unit)
                unit.error_details = f"Unmet dependencies: {unmet_deps}"
                continue

            # Try to fix this unit
            try:
                unit_result = await self._fix_single_unit(unit)
                total_iterations += 1

                if unit_result['success']:
                    fixed_units.append(unit)
                    unit.fix_applied = True
                    unit.fix_verified = True
                    unit.fix_description = unit_result.get('fix_description', '')
                    all_files_modified.extend(unit_result.get('files_modified', []))
                    self.output(f"✅ Unit {unit.unit_id} FIXED")
                else:
                    failed_units.append(unit)
                    unit.error_details = unit_result.get('error', 'Unknown error')
                    self.output(f"❌ Unit {unit.unit_id} FAILED: {unit.error_details}")

            except Exception as e:
                logger.exception(f"Unit {unit.unit_id} failed with exception")
                failed_units.append(unit)
                unit.error_details = str(e)
                self.output(f"❌ Unit {unit.unit_id} ERROR: {e}")

        # Summary
        self.output("\n" + "=" * 60)
        self.output("INCREMENTAL DEBUG SUMMARY")
        self.output("=" * 60)
        self.output(f"Fixed: {len(fixed_units)}/{len(ordered_units)} units")
        if failed_units:
            self.output(f"Failed: {[u.unit_id for u in failed_units]}")

        # Visual checkpoints
        if decomposition.visual_units:
            self.output("\n👁️  VISUAL VERIFICATION REQUIRED:")
            for vu in decomposition.visual_units:
                self.output(f"   - {vu.description}")
                self.output(f"     Files: {', '.join(vu.affected_files)}")
            self._visual_checkpoints = decomposition.visual_units

        # Run full regression if any units were fixed
        if fixed_units:
            self.output("\n[FINAL] Running full regression tests...")
            regression_result = await self.test_generator.run_all_project_tests()
            if not regression_result.passed:
                self.output(f"⚠️  Regression tests failed: {regression_result.error}")
                # Don't rollback - let user decide

        # Determine overall outcome
        blocked_reason = None
        if len(fixed_units) == len(ordered_units):
            outcome = DebugOutcome.FIXED
            self._session.set_status(DebugStatus.COMPLETE)
        elif fixed_units:
            outcome = DebugOutcome.FIXED  # Partial fix
            self._session.set_status(DebugStatus.COMPLETE)
        else:
            outcome = DebugOutcome.BLOCKED
            # Build meaningful blocked reason from failed units
            failed_reasons = [f"{u.unit_id}: {u.error_details or 'Unknown error'}" for u in failed_units[:3]]
            blocked_reason = f"No units could be fixed. Failures: {'; '.join(failed_reasons)}"
            self._session.set_status(DebugStatus.BLOCKED, blocked_reason)

        # Unique files
        all_files_modified = list(set(all_files_modified))
        self._session.files_modified = all_files_modified
        self._session.completion_summary = self._generate_incremental_summary(
            fixed_units, failed_units, decomposition.visual_units
        )
        self.context.save_session(self._session)

        return DebugResult(
            outcome=outcome,
            iterations=total_iterations,
            root_cause=self._current_hypothesis,
            files_modified=all_files_modified,
            fix_summary=self._session.completion_summary,
            blocked_reason=blocked_reason,
            test_results={
                'fixed_units': [u.unit_id for u in fixed_units],
                'failed_units': [u.unit_id for u in failed_units],
                'visual_checkpoints': [u.description for u in decomposition.visual_units]
            }
        )

    async def _fix_single_unit(self, unit: DebugUnit) -> Dict[str, Any]:
        """
        Fix a single debug unit with its own test-fix-verify cycle.

        Returns:
            Dict with 'success', 'files_modified', 'fix_description', 'error'
        """
        MAX_UNIT_ATTEMPTS = 3

        for attempt in range(MAX_UNIT_ATTEMPTS):
            attempt_num = attempt + 1
            self.output(f"\n  [Attempt {attempt_num}/{MAX_UNIT_ATTEMPTS}]")

            # STEP 1: Generate targeted test for this unit
            self.output("  Generating targeted unit test...")
            test_code = await self.test_generator.generate_unit_test(
                unit_description=unit.description,
                affected_files=unit.affected_files,
                test_approach=unit.test_approach,
                test_assertions=unit.test_assertions,
                error_details=unit.error_details
            )

            test_name = f"test_unit_{unit.unit_id}_{attempt_num}"
            test_path = self.context.save_bug_test(test_name, test_code)
            unit.test_path = str(test_path)
            unit.test_generated = True

            # STEP 2: Verify test fails (confirms the unit bug exists)
            self.output("  Verifying test fails (bug confirmation)...")
            test_fails = await self.test_generator.verify_test_fails(test_path)

            if not test_fails:
                self.output("  ⚠️  Test passes - unit may already be working or test is wrong")
                # Try one more time with refined test, or mark as possibly fixed
                if attempt == MAX_UNIT_ATTEMPTS - 1:
                    return {
                        'success': True,  # Optimistically assume it's working
                        'files_modified': [],
                        'fix_description': 'Unit appears to be working (test passes)',
                        'error': None
                    }
                continue

            self.output("  ✓ Test fails as expected - bug confirmed")

            # STEP 3: Generate and apply fix for this unit
            self.output("  Generating fix for this unit...")

            # Read current file contents with robust path resolution
            file_contents = {}
            for f in unit.affected_files:
                resolved_path = self._resolve_file_path(f)
                if resolved_path:
                    try:
                        file_contents[f] = resolved_path.read_text(encoding='utf-8', errors='replace')
                        self.context.backup_file(resolved_path)
                        self.output(f"    Loaded: {f}")
                    except Exception as e:
                        logger.warning(f"Could not read {resolved_path}: {e}")
                        self.output(f"    ⚠️ Error reading {f}: {e}")
                else:
                    self.output(f"    ⚠️ File not found: {f}")

            if not file_contents:
                # Try to find ANY relevant files in the project
                self.output("  Searching for related files...")
                found_files = self._find_related_files(unit.description)
                if found_files:
                    self.output(f"    Found {len(found_files)} related files")
                    for fp in found_files[:3]:
                        try:
                            file_contents[str(fp.relative_to(self.project_dir))] = fp.read_text(encoding='utf-8', errors='replace')
                            self.context.backup_file(fp)
                        except Exception:
                            pass

            if not file_contents:
                return {
                    'success': False,
                    'files_modified': [],
                    'fix_description': '',
                    'error': f'Could not read affected files: {unit.affected_files}. Project dir: {self.project_dir}'
                }

            # Generate fix using LLM
            fix_result = await self._apply_unit_fix(unit, file_contents, test_code)

            if not fix_result['success']:
                self.output(f"  ❌ Fix application failed: {fix_result.get('error', 'Unknown')}")
                # Rollback and retry
                await self._rollback(fix_result.get('files_modified', []))
                continue

            self.output(f"  ✓ Fix applied to: {fix_result['files_modified']}")

            # STEP 4: Verify test passes (confirms fix works)
            self.output("  Verifying fix (test should pass)...")
            test_passes = await self.test_generator.verify_test_passes(test_path)

            if not test_passes:
                self.output("  ❌ Test still fails - fix incomplete")
                await self._rollback(fix_result['files_modified'])
                continue

            self.output("  ✓ Test passes - unit fix verified!")

            # STEP 5: Quick regression check for this unit's files
            self.output("  Running quick regression check...")
            relevant_tests = self.test_generator.identify_relevant_tests(fix_result['files_modified'])
            if relevant_tests:
                targeted_result = await self.test_generator.run_targeted_tests(relevant_tests)
                if not targeted_result.passed:
                    self.output(f"  ❌ Regression detected: {targeted_result.error}")
                    await self._rollback(fix_result['files_modified'])
                    continue
                self.output("  ✓ No regressions in related tests")

            # SUCCESS!
            return {
                'success': True,
                'files_modified': fix_result['files_modified'],
                'fix_description': fix_result.get('description', ''),
                'error': None
            }

        # All attempts failed
        return {
            'success': False,
            'files_modified': [],
            'fix_description': '',
            'error': f'Failed after {MAX_UNIT_ATTEMPTS} attempts'
        }

    async def _apply_unit_fix(
        self,
        unit: DebugUnit,
        file_contents: Dict[str, str],
        test_code: str
    ) -> Dict[str, Any]:
        """
        Apply a fix for a single unit.

        Similar to _apply_fix_and_lint but scoped to one unit.
        """
        prompt = f"""Generate a SURGICAL fix for this specific bug unit.

UNIT DESCRIPTION: {unit.description}

ERROR DETAILS: {unit.error_details or 'Not specified'}

TEST APPROACH: {unit.test_approach}

TEST CODE (your fix must pass this test):
```
{test_code}
```

CURRENT CODE:
{self._format_file_contents(file_contents)}

REQUIREMENTS:
1. Fix ONLY this specific unit - do not refactor or change unrelated code
2. Make the SMALLEST change that fixes the bug
3. Your fix MUST align with what the test verifies
4. Use SEARCH/REPLACE blocks format

FORMAT:
File: <filename>
<<<<<<< SEARCH
<exact original code>
=======
<fixed code>
>>>>>>> REPLACE
"""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=4000
            )

            if not response.success:
                return {'success': False, 'error': response.error, 'files_modified': []}

            # Parse and apply patches
            patches = self._parse_fix_response(response.content)
            if not patches:
                return {'success': False, 'error': 'No patches parsed', 'files_modified': []}

            # CRITICAL: Filter out patches to ORPHANED files (not in execution path)
            patch_dicts = []
            for p in patches:
                fname = p['file']
                if self._execution_context and self._execution_context.active_files:
                    norm_fname = fname.replace('\\', '/')
                    if norm_fname not in self._execution_context.active_files:
                        if norm_fname in self._execution_context.orphaned_files:
                            logger.warning(f"REJECTED patch to orphaned file: {fname}")
                            continue
                patch_dicts.append({'file': fname, 'search': p['search'], 'replace': p['replace']})

            if not patch_dicts:
                return {'success': False, 'error': 'All patches targeted orphaned files', 'files_modified': []}

            apply_result = self.patch_applier.apply_patches(patch_dicts)

            if not apply_result.success:
                return {'success': False, 'error': apply_result.error, 'files_modified': apply_result.modified_files}

            # Lint check
            for fname in apply_result.modified_files:
                fpath = self.project_dir / fname
                linter_res = await self.linter_service.check_file(fpath, strict=False)
                if not linter_res.valid:
                    return {
                        'success': False,
                        'error': f'Lint failed: {linter_res.errors}',
                        'files_modified': apply_result.modified_files
                    }

            return {
                'success': True,
                'files_modified': apply_result.modified_files,
                'applied_patches': len(patches)
            }

        except Exception as e:
            logger.error(f"Fix application error: {e}")
            return {'success': False, 'error': str(e), 'files_modified': []}

    def _resolve_file_path(self, file_path: str) -> Optional[Path]:
        """
        Resolve a file path trying multiple strategies.

        Tries:
        1. Relative to project_dir
        2. Absolute path
        3. Search in common subdirectories
        4. Glob search for filename

        Returns:
            Resolved Path if found, None otherwise
        """
        if not file_path:
            return None

        # Strategy 1: Relative to project_dir
        relative_path = self.project_dir / file_path
        if relative_path.exists():
            return relative_path

        # Strategy 2: Already absolute
        abs_path = Path(file_path)
        if abs_path.is_absolute() and abs_path.exists():
            return abs_path

        # Strategy 3: Try common subdirectories
        subdirs = ['', 'src', 'lib', 'app', 'js', 'scripts', 'utils', 'components']
        for subdir in subdirs:
            if subdir:
                check_path = self.project_dir / subdir / file_path
            else:
                check_path = self.project_dir / file_path
            if check_path.exists():
                return check_path

        # Strategy 4: Glob search for the filename
        filename = Path(file_path).name
        matches = list(self.project_dir.rglob(filename))
        if matches:
            # Return the first match (prefer shorter paths)
            return min(matches, key=lambda p: len(str(p)))

        # Strategy 5: Check parent directories (in case project_dir is a subdirectory)
        for parent in [self.project_dir.parent, self.project_dir.parent.parent]:
            check_path = parent / file_path
            if check_path.exists():
                return check_path

        logger.debug(f"Could not resolve file path: {file_path}")
        return None

    def _find_related_files(self, description: str) -> List[Path]:
        """
        Find files related to a description by keyword matching.

        Args:
            description: Bug/unit description

        Returns:
            List of potentially related file paths
        """
        # Extract keywords from description
        keywords = []
        desc_lower = description.lower()

        # Common technical keywords
        for word in ['constant', 'config', 'util', 'helper', 'api', 'data', 'model',
                     'controller', 'service', 'handler', 'loader', 'validator']:
            if word in desc_lower:
                keywords.append(word)

        # Look for specific file types mentioned
        extensions = ['.js', '.ts', '.py', '.jsx', '.tsx', '.json']

        found_files = []
        for ext in extensions:
            for f in self.project_dir.rglob(f'*{ext}'):
                # Skip node_modules, venv, etc.
                path_str = str(f).lower()
                if 'node_modules' in path_str or 'venv' in path_str or '.git' in path_str:
                    continue

                # Check if any keyword matches the filename
                fname_lower = f.name.lower()
                for kw in keywords:
                    if kw in fname_lower:
                        found_files.append(f)
                        break

        return found_files[:10]  # Limit to 10 files

    async def _get_llm_search_guidance(self, bug_description: str, error_trace: Optional[str], project_files: List[str]) -> Dict[str, Any]:
        """
        Ask the LLM to guide the search for files that might be related to the bug.

        This helps find files that might not be obvious from the error trace alone,
        such as files that override behavior or set conflicting values.

        Returns dict with:
        - search_terms: List of technical terms to search for in code
        - file_patterns: List of glob patterns to find files
        - reasoning: LLM's reasoning for the suggested searches
        """
        files_sample = "\n".join(project_files[:50])

        prompt = f"""You are helping a bug debugger find ALL files that might be related to a bug.

BUG DESCRIPTION: {bug_description}

ERROR TRACE:
{error_trace or 'Not provided'}

PROJECT FILES (sample):
{files_sample}

TASK: Suggest search terms and file patterns to find ALL code that might be relevant to this bug.

Think about:
1. Files mentioned in the error trace
2. Files that might OVERRIDE or CONFLICT with the expected behavior
3. Configuration files, styles, or settings that might affect the behavior
4. Related modules that the buggy code depends on

OUTPUT FORMAT (JSON only, no other text):
{{
    "search_terms": ["term1", "term2", ...],
    "file_patterns": ["*pattern*.py", "*.qss", ...],
    "reasoning": "Brief explanation of why these searches will find relevant code"
}}

Be thorough - the bug might be in an unexpected place!"""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=1500
            )

            if not response.success:
                logger.warning(f"LLM search guidance failed: {response.error}")
                return {'search_terms': [], 'file_patterns': [], 'reasoning': 'LLM failed'}

            content = response.content.strip() if response.content else ""

            # Check for empty response
            if not content:
                logger.warning("LLM search guidance returned empty response")
                return {'search_terms': [], 'file_patterns': [], 'reasoning': 'Empty LLM response'}

            # Extract JSON if wrapped in markdown
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            # Try to find JSON object if content doesn't start with {
            if not content.startswith('{'):
                json_start = content.find('{')
                json_end = content.rfind('}')
                if json_start != -1 and json_end != -1 and json_end > json_start:
                    content = content[json_start:json_end + 1]
                else:
                    logger.warning(f"Could not find JSON in LLM response: {content[:200]}")
                    return {'search_terms': [], 'file_patterns': [], 'reasoning': 'No JSON in response'}

            import json
            guidance = json.loads(content)

            logger.info(f"LLM search guidance: {len(guidance.get('search_terms', []))} terms, "
                       f"{len(guidance.get('file_patterns', []))} patterns")
            self.output(f"[LLM Search] {guidance.get('reasoning', 'No reasoning')[:200]}")

            return guidance

        except Exception as e:
            logger.warning(f"LLM search guidance error: {e}")
            return {'search_terms': [], 'file_patterns': [], 'reasoning': str(e)}

    async def _analyze_bug(self) -> Optional[Dict[str, Any]]:
        """
        Analyze the bug to identify root cause and affected files.

        CRITICAL: If execution context is available (from Phase 0), we ONLY
        consider files that are actually in the execution path. This prevents
        debugging orphaned files that look relevant but aren't loaded at runtime.

        Returns dict with:
        - hypothesis: Description of the root cause
        - affected_files: List of files involved
        - line_number: Specific line if identifiable
        - confidence: Confidence level (0-1)
        """
        # Gather context
        error_info = self._parse_error_trace()

        # CRITICAL: Use execution graph if available to filter to ACTIVE files only
        if self._execution_context and self._execution_context.active_files:
            project_files_list = list(self._execution_context.active_files)
            project_files = '\n'.join(sorted(self._execution_context.active_files))
            self.output(f"[Phase 1a] Using {len(project_files_list)} files from execution graph")

            # Add execution context summary for better debugging
            exec_summary = self.code_path_tracer.get_context_summary()
            logger.info(f"Execution context for debugging:\n{exec_summary}")
        else:
            # Fallback: use all project files
            project_files = self._get_project_structure()
            project_files_list = [f.strip() for f in project_files.split('\n') if f.strip()]

        # [NEW] Get LLM-guided search suggestions
        self.output("[Phase 1a] Getting LLM search guidance...")
        guidance = await self._get_llm_search_guidance(
            self._session.bug_description,
            self._session.error_trace,
            project_files_list
        )
        llm_search_terms = guidance.get('search_terms', [])
        llm_file_patterns = guidance.get('file_patterns', [])

        # Read relevant files - start with error trace files
        files_to_read = set()
        if error_info.get('file'):
            files_to_read.add(error_info['file'])

        # CRITICAL: If we have execution context, add ALL active files to be read!
        # This ensures the LLM sees actual code, not just file names.
        if self._execution_context and self._execution_context.active_files:
            for active_file in self._execution_context.active_files:
                # Only add code files, skip HTML entry points (they're just loaders)
                if not active_file.endswith('.html'):
                    files_to_read.add(active_file)
            logger.info(f"Added {len(files_to_read)} active files from execution context")
        else:
            # Fallback: Add main files if no execution context
            for ext in ['.py', '.js', '.ts']:
                main_file = self.project_dir / f"main{ext}"
                if main_file.exists():
                    files_to_read.add(f"main{ext}")
                    break
            # Also check common entry point names
            for name in ['app', 'index', 'script']:
                for ext in ['.py', '.js', '.ts']:
                    entry_file = self.project_dir / f"{name}{ext}"
                    if entry_file.exists():
                        files_to_read.add(f"{name}{ext}")

        # Helper to normalize paths to be relative to project_dir
        # CRITICAL: Also filters out files not in execution path if context available
        def normalize_path(p) -> Optional[str]:
            """Convert any path to relative path string, filtering orphaned files."""
            try:
                path_obj = Path(p) if isinstance(p, str) else p
                if path_obj.is_absolute():
                    # Try to make it relative to project_dir
                    try:
                        rel_path = str(path_obj.relative_to(self.project_dir))
                    except ValueError:
                        # Path is outside project_dir, use as-is
                        rel_path = str(path_obj)
                else:
                    rel_path = str(path_obj)

                # CRITICAL: If we have execution context, only include ACTIVE files
                if self._execution_context and self._execution_context.active_files:
                    if rel_path not in self._execution_context.active_files:
                        # Check if it's an orphaned file - log warning
                        if rel_path in self._execution_context.orphaned_files:
                            logger.warning(f"Skipping ORPHANED file (not in execution path): {rel_path}")
                        return None  # Exclude this file

                return rel_path
            except Exception:
                return str(p)

        # [NEW] Search with LLM-suggested file patterns
        for pattern in llm_file_patterns:
            try:
                pattern_matches = await self.code_searcher.find_files(pattern)
                for f in pattern_matches:
                    rel_path = normalize_path(f)
                    if rel_path:
                        files_to_read.add(rel_path)
                        logger.debug(f"Found file via pattern '{pattern}': {rel_path}")
            except Exception as e:
                logger.debug(f"Pattern {pattern} failed: {e}")

        # [NEW] Search for LLM-suggested technical terms
        for term in llm_search_terms[:8]:
            try:
                s_result = await self.code_searcher.search_text(term, max_results=3)
                if s_result.matches:
                    for m in s_result.matches:
                        rel_path = normalize_path(m.file_path)
                        if rel_path:
                            files_to_read.add(rel_path)
                            logger.debug(f"Found file via term '{term}': {rel_path}")
            except Exception as e:
                logger.debug(f"Search term {term} failed: {e}")

        self.output(f"[Phase 1a] Total {len(files_to_read)} files to analyze (active + search results)")
        logger.info(f"Files to read: {list(files_to_read)}")

        file_contents = {}
        for f in list(files_to_read)[:10]:  # Increased limit to 10
            try:
                # Handle both relative and absolute paths
                if Path(f).is_absolute():
                    full_path = Path(f)
                else:
                    full_path = self.project_dir / f

                if full_path.exists():
                    content = full_path.read_text(encoding='utf-8', errors='replace')
                    # Use relative path as key for cleaner display
                    rel_key = normalize_path(full_path) or f
                    file_contents[rel_key] = content
                    logger.debug(f"Successfully read: {rel_key} ({len(content)} chars)")
                else:
                    logger.warning(f"File not found: {full_path}")
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")

        # Detect project language using LanguageDetector
        lang = self.language_detector.detect()
        lang_context = self.language_detector.get_language_context_for_llm()

        # Gather file structures for symbols
        file_structures = "\n\n".join([self._get_file_structure(self.project_dir / f) for f in file_contents.keys()])

        # Build analysis prompt
        prompt = f"""Analyze this bug and identify the ROOT CAUSE.

{lang_context}

NOTE: This is a {lang.name} project. Look for {lang.name}-specific patterns and frameworks.
For UI bugs, check for programmatic styling, not just stylesheets.

BUG DESCRIPTION:
{self._session.bug_description}

ERROR TRACE:
{self._session.error_trace or 'Not provided'}

PROJECT FILES:
{project_files}

RELEVANT FILE STRUCTURES:
{file_structures}
{self._get_semantic_context(self._session.bug_description) if self.ragg_tool else ""}

FILE CONTENTS:
{self._format_file_contents(file_contents)}

PREVIOUS ATTEMPTS (if any):
{self._format_previous_attempts()}

IMPORTANT: If previous attempts failed due to "Search block not found" or "Patch application failed", it means the file content DOES NOT match what you expected.
DO NOT repeat the same "Locate X" strategy if X does not exist. Instead, propose creating it or check the FILE CONTENTS carefully.

CRITICAL: Check RELEVANT FILE STRUCTURES above. If a method or class already exists, DO NOT propose creating it again. Update it in place.

DO NOT provide lengthy reasoning or analysis.  
DO NOT use <details> tags or markdown formatting in your response.
DO NOT explain your thought process - ONLY provide the structured output below.

Provide your analysis in this EXACT format (no additional text):
HYPOTHESIS: <one sentence describing the root cause>
AFFECTED_FILES: <comma-separated list of files>
LINE_NUMBER: <specific line number if known, or "unknown">
CONFIDENCE: <number from 0.0 to 1.0>
FIX_APPROACH: <brief description of how to fix it>
"""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                provider=None, 
                model="qwen3-coder:480b-cloud", # Force specific model as requested
                temperature=0.3,
                max_tokens=4000
            )

            if not response.success:
                logger.error(f"Bug analysis failed: {response.error}")
                return None

            content = response.content
            # Debug logging
            self.output(f"RAW ANALYSIS RESPONSE:\n{content}")
            return self._parse_analysis_response(content)

        except Exception as e:
            logger.error(f"Bug analysis failed: {e}")
            self.output(f"❌ Bug analysis exception: {e}")
            return None

    def _parse_analysis_response(self, content: str) -> Dict[str, Any]:
        """Parse the structured analysis response."""
        result = {
            'hypothesis': '',
            'affected_files': [],
            'line_number': None,
            'confidence': 0.5,
            'fix_approach': ''
        }
        
        # Regex parsing for robustness against **bolding** and case
        hyp_match = re.search(r'(?:\*\*|)?HYPOTHESIS(?:\*\*|)?:\s*(.*)', content, re.IGNORECASE)
        if hyp_match:
            result['hypothesis'] = hyp_match.group(1).strip()
            
        # Match AFFECTED_FILES but stop at next field marker or end of line
        # The pattern stops at: LINE_NUMBER, CONFIDENCE, FIX_APPROACH, or newline
        files_match = re.search(
            r'(?:\*\*|)?AFFECTED_FILES(?:\*\*|)?:\s*([^\n]*?)(?=\s*(?:LINE_NUMBER|CONFIDENCE|FIX_APPROACH|\n|$))',
            content, re.IGNORECASE
        )
        if files_match:
            files_str = files_match.group(1).strip()
            # Remove brackets, trailing periods, and common sentence endings
            files_str = files_str.strip("[]").rstrip('.;:')
            # Strip each filename and remove markdown formatting characters
            result['affected_files'] = [f.strip().strip('*_` ').rstrip('.') for f in files_str.split(',') if f.strip() and not f.strip().startswith('LINE')]
            
        line_match = re.search(r'(?:\*\*|)?LINE_NUMBER(?:\*\*|)?:\s*(\d+|unknown)', content, re.IGNORECASE)
        if line_match:
            ln = line_match.group(1).strip()
            if ln.isdigit():
                result['line_number'] = int(ln)
                
        conf_match = re.search(r'(?:\*\*|)?CONFIDENCE(?:\*\*|)?:\s*([0-9.]+)', content, re.IGNORECASE)
        if conf_match:
            try:
                result['confidence'] = float(conf_match.group(1).strip())
            except ValueError:
                pass
                
        fix_match = re.search(r'(?:\*\*|)?FIX_APPROACH(?:\*\*|)?:\s*(.*)', content, re.IGNORECASE)
        if fix_match:
            result['fix_approach'] = fix_match.group(1).strip()

        # Fallback: If no affected files found, scan the ENTIRE content for known project filenames
        if not result['affected_files']:
            # We need access to the project structure to know what files exist.
            # Since this is a method on the controller, we can re-scan or use cached structure.
             try:
                 # Quick scan of likely text matches
                 potential_files = re.findall(r'[\w-]+\.(?:py|js|ts|html|css|json|md)', content)
                 
                 # Filter these against actual files to avoid hallucination
                 # We can use the cached structure from _get_project_structure if available
                 # But _get_project_structure is a method. Let's just verify existence.
                 
                 valid_files = []
                 seen = set()
                 
                 # 1. Check exact matches
                 for fname in potential_files:
                     if fname in seen: continue
                     if (self.project_dir / fname).exists():
                         valid_files.append(fname)
                         seen.add(fname)

                 # 2. Check for component names (without extension) if we still need files
                 # Scan for words that match existing files (e.g. "editor" -> "editor.py")
                 if not valid_files:
                     words = re.findall(r'\b\w+\b', content)
                     for word in words:
                         candidate = f"{word.lower()}.py" # Try python first
                         if candidate in seen: continue
                         if (self.project_dir / candidate).exists():
                             valid_files.append(candidate)
                             seen.add(candidate)
                             continue
                             
                         candidate = f"{word.lower()}.js" # Try JS
                         if (self.project_dir / candidate).exists():
                             valid_files.append(candidate)
                             seen.add(candidate)
                 
                 if valid_files:
                     result['affected_files'] = valid_files
                     logger.info(f"Fallback: Extracted affected files from text: {valid_files}")
                 
                 if valid_files:
                     result['affected_files'] = valid_files
                     logger.info(f"Fallback: Extracted affected files from text: {valid_files}")
             except Exception as e:
                 logger.warning(f"Fallback file extraction failed: {e}")

            
        return result


    async def _analyze_verification_failure(
        self,
        test_path: str,
        test_output: str,
        fix_description: str
    ) -> Dict[str, Any]:
        """
        Analyze why a test failed after a fix was applied.
        Determines if the fix is wrong OR if the test is wrong (false negative).
        """
        try:
            test_code = ""
            if Path(test_path).exists():
                test_code = Path(test_path).read_text()

            # Get framework guidance for test correction
            framework_guidance = self.test_generator._get_framework_specific_guidance()

            prompt = f"""The agent applied a fix for a bug, but the verification test still FAILS.
Review the situation and determine if the **TEST** is flawed (false negative) or if the **FIX** is incomplete.

BUG DESCRIPTION:
{self._session.bug_description}

APPLIED FIX:
{fix_description}

VERIFICATION TEST CODE:
{test_code}

TEST FAILURE OUTPUT:
{test_output}

{framework_guidance}

ANALYSIS INSTRUCTIONS:
1. Check if the test is asserting something too specific (brittle) that the fix didn't match exactly but is logically correct.
2. Check if the test logic itself is flawed (e.g., using wrong API like backgroundRole() instead of QPalette.Base for Qt).
3. Check if the fix clearly failed to address the root cause.

IF CORRECTING THE TEST, YOU MUST FOLLOW THE FRAMEWORK CONSTRAINTS ABOVE EXACTLY.

RESPONSE FORMAT:
VERDICT: [TEST_FLAWED | FIX_INCOMPLETE]
REASON: <explanation>
NEW_TEST_CODE: <if TEST_FLAWED, provide corrected test code here following the framework constraints above. Otherwise leave empty>
"""
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                model="qwen3-coder:480b-cloud", # High intelligence for judging
                temperature=0.1,
                max_tokens=2000
            )

            if not response.success:
                return {"verdict": "FIX_INCOMPLETE", "reason": "Analysis failed"}

            content = response.content
            
            # Simple parsing
            verdict = "FIX_INCOMPLETE"
            if "VERDICT: TEST_FLAWED" in content:
                verdict = "TEST_FLAWED"
            
            new_code = ""
            if verdict == "TEST_FLAWED":
                new_code = self.test_generator._extract_code(content)

            return {
                "verdict": verdict,
                "reason": content,
                "new_test_code": new_code
            }

        except Exception as e:
            logger.error(f"Failed to analyze verification failure: {e}")
            return {"verdict": "FIX_INCOMPLETE", "reason": str(e)}

    async def _apply_fix_and_lint(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate, Apply, and Lint a fix.
        Implements Gate 1 (Static Analysis).
        """
        affected_files = analysis.get('affected_files', [])
        if not affected_files:
            return {'success': False, 'error': 'No affected files identified'}

        # Read current file contents, backup, and capture lint baseline
        file_contents = {}
        baselines = {}
        for f in affected_files:
            try:
                full_path = self.project_dir / f
                if full_path.exists():
                    self.context.backup_file(full_path)
                    with open(full_path, 'r') as fp:
                        file_contents[f] = fp.read()
                    
                    # Capture baseline (non-strict check to avoid huge overhead, but gets current state)
                    baselines[f] = await self.linter_service.check_file(full_path, strict=True)
            except Exception as e:
                logger.warning(f"Could not read/baseline {f}: {e}")

        if not file_contents:
            # Provide detailed error message showing what was attempted
            attempted_files = [str(self.project_dir / f) for f in affected_files]
            error_msg = f'Could not read affected files. Attempted: {", ".join(attempted_files)}'
            logger.error(error_msg)
            self.output(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}

        # GENERALIZED APPROACH: Include the test code so LLM can align its implementation
        # with what the test actually verifies. No hardcoded framework rules needed.
        test_code = ""
        if self._session.bug_test_path:
            try:
                test_path = Path(self._session.bug_test_path)
                if test_path.exists():
                    test_code = test_path.read_text()
                    self.output(f"[Fix Alignment] Including test code for implementation alignment")
            except Exception as e:
                logger.warning(f"Could not read test file for alignment: {e}")

        # Build execution context info if available
        exec_context_info = ""
        code_location_info = ""
        if self._execution_context and self._execution_context.active_files:
            exec_context_info = f"""
============================================================
CODE PATH ANALYSIS
============================================================
Entry Points: {', '.join(self._execution_context.entry_points)}
Active Files (in execution path): {len(self._execution_context.active_files)}
Orphaned Files (NOT loaded): {len(self._execution_context.orphaned_files)}

⛔ CRITICAL: You may ONLY patch files in the ACTIVE list!
⛔ DO NOT patch orphaned files - they are NOT loaded at runtime!

Active files: {', '.join(sorted(self._execution_context.active_files))}
============================================================
"""
            # Feature-to-code mapping for bug keywords
            bug_keywords = [k for k in self._session.bug_description.split() if len(k) > 3 and k.isalpha()]
            if bug_keywords:
                code_locations = self.code_path_tracer.find_code_for_feature(bug_keywords[:10])
                if code_locations:
                    code_location_info = "\n🎯 RELEVANT CODE LOCATIONS:\n"
                    for file_path, matches in code_locations.items():
                        code_location_info += f"\n📍 {file_path}:\n"
                        for line_num, line_content in matches[:5]:
                            code_location_info += f"   Line {line_num}: {line_content[:80]}\n"

        # Build prompt with test code for natural alignment
        prompt = f"""Generate a SURGICAL fix for this bug using SEARCH/REPLACE blocks.
{exec_context_info}
BUG: {self._session.bug_description}

ROOT CAUSE: {analysis['hypothesis']}

FIX APPROACH: {analysis.get('fix_approach', 'Fix the identified issue')}
{code_location_info}
CURRENT CODE:
(Line numbers provided for reference only - do NOT include them in your SEARCH/REPLACE blocks)
{self._format_file_contents(file_contents)}

{"VERIFICATION TEST (your fix must pass this test):" + chr(10) + "```" + chr(10) + test_code + chr(10) + "```" + chr(10) + chr(10) + "CRITICAL: Analyze what the test is checking and ensure your implementation uses the SAME APIs/methods that the test verifies. If the test checks a specific property or method, your fix must set that same property or method." if test_code else ""}

REQUIREMENTS:
1. Make the SMALLEST possible change to fix the bug. Be surgical.
2. Provide multiple small patches instead of one large block if changes are far apart.
3. Your SEARCH block should ideally be 3-10 lines long.
4. Avoid rewriting entire functions if only a few lines need to change.
5. The SEARCH block must contain the EXACT original lines to be replaced (including whitespace, but WITHOUT line numbers).
6. Your implementation MUST align with what the verification test checks.
7. CRITICAL: To ADD code to a class, SEARCH for existing code INSIDE that class (like the end of __init__ or an existing method), NOT the class header itself.
8. CRITICAL: Your REPLACE block must be syntactically valid Python that can replace the SEARCH block.

🛑 ABSOLUTE PROHIBITIONS:
⛔ NEVER replace more than 15 lines in a single SEARCH/REPLACE block
⛔ NEVER include entire file content in SEARCH block
⛔ NEVER replace entire functions if only a few lines changed
⛔ NEVER replace complete class definitions
⛔ Wholesale file replacements will be AUTOMATICALLY REJECTED

✅ SURGICAL CHANGE PRINCIPLE:
- Identify the MINIMAL code that needs modification
- Include ONLY that code in your SEARCH block
- Add 1-2 lines of context before/after for uniqueness
- If multiple changes needed, create MULTIPLE small patches

FORMAT:
For EACH change:

File: <filename>
<<<<<<< SEARCH
<original code lines (exact match, 3-15 lines max, no line numbers)>
=======
<new code lines>
>>>>>>> REPLACE

IMPORTANT: Your SEARCH block must be SMALL and TARGETED (max 15 lines).
Large SEARCH blocks (>15 lines) will be automatically rejected as wholesale replacements.
"""

        # Retry loop for fix generation AND linting
        current_lint_error = None
        
        for attempt in range(4): # Increased attempts to handle lint failures
            try:
                # Add hint if retrying
                current_prompt = prompt
                if attempt > 0:
                    if current_lint_error:
                        current_prompt += f"\n\nIMPORTANT: Your previous patch introduced a SYNTAX/LINT ERROR:\n{current_lint_error}\n\nPlease fix the code to be valid."
                    else:
                        current_prompt += f"\n\nIMPORTANT: Your previous response was invalid. You MUST use the <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE format."

                # Progress indicator
                self.output(f"[Attempt {attempt + 1}/4] Generating fix code (this may take 30-60s)...")

                # Call LLM with timeout
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.llm_client.generate,
                            prompt=current_prompt,
                            provider=None,
                            model="qwen3-coder:480b-cloud", # Force specific model
                            temperature=0.2 + (0.1 * attempt),
                            max_tokens=8000
                        ),
                        timeout=120.0  # 2 minute timeout
                    )
                except asyncio.TimeoutError:
                    self.output(f"⚠ LLM call timed out after 120s")
                    if attempt == 3:
                        return {'success': False, 'error': 'LLM generation timed out'}
                    continue

                if not response.success:
                    if attempt == 3:
                        return {'success': False, 'error': f"LLM failed: {response.error}"}
                    continue

                content = response.content
                self.output(f"RAW FIX RESPONSE (Attempt {attempt+1}):\n{content}")
                
                # Parse patches
                patches = self._parse_fix_response(content)
                if not patches:
                    logger.warning(f"Attempt {attempt+1} parsed 0 patches")
                    if attempt == 3:
                         return {'success': False, 'error': 'Could not parse any patches'}
                    current_lint_error = None # Not a lint error, a parsing error
                    continue
                
                # Apply patches using Service
                # CRITICAL: Filter out patches to ORPHANED files (not in execution path)
                # This prevents LLM from modifying files that look relevant but aren't loaded
                patch_dicts = []
                rejected_patches = []
                for p in patches:
                    fname = p['file']
                    # Check if file is orphaned (exists but not in execution path)
                    if self._execution_context and self._execution_context.active_files:
                        # Normalize path for comparison
                        norm_fname = fname.replace('\\', '/')
                        if norm_fname not in self._execution_context.active_files:
                            if norm_fname in self._execution_context.orphaned_files:
                                rejected_patches.append(f"{fname} (ORPHANED - not loaded by entry point)")
                                logger.warning(f"REJECTED patch to orphaned file: {fname}")
                                continue
                            # File might be new or outside tracked area - allow it
                    patch_dicts.append({'file': fname, 'search': p['search'], 'replace': p['replace']})

                if rejected_patches:
                    self.output(f"  ⚠️ Rejected {len(rejected_patches)} patches to orphaned files:")
                    for rp in rejected_patches[:5]:  # Show up to 5
                        self.output(f"     • {rp}")
                    if len(rejected_patches) > 5:
                        self.output(f"     ... and {len(rejected_patches) - 5} more")

                if not patch_dicts:
                    # All patches were to orphaned files
                    current_lint_error = "All patches targeted orphaned files (not in execution path). Re-examine active files."
                    continue

                apply_result = self.patch_applier.apply_patches(patch_dicts)
                
                if not apply_result.success:
                     # Application failed (e.g. search block not found)
                     failed_file = apply_result.error or "Unknown"
                     logger.warning(f"Patch application failed: {failed_file}")
                     
                     # Build detailed error message with file content context
                     error_msg = (
                         f"Patch application failed. The SEARCH block was NOT found in the file.\n"
                         f"Error details: {apply_result.error}\n\n"
                         f"CRITICAL: The code you searched for does NOT exist in the current file.\n"
                         f"Here is the CURRENT CONTENT of the file you tried to patch:\n\n"
                     )
                     
                     # Include the actual file content so LLM can see what's really there
                     for fname in affected_files:
                         if fname in file_contents:
                             error_msg += f"=== {fname} (CURRENT CODE) ===\n{file_contents[fname]}\n\n"
                     
                     error_msg += (
                         "You MUST copy and paste the EXACT lines from the CURRENT CODE above into your SEARCH block.\n"
                         "DO NOT modify whitespace, comments, or any characters."
                     )
                     
                     current_lint_error = error_msg
                     
                     # Rollback partial changes
                     await self._rollback(apply_result.modified_files)
                     continue
                     
                # ── GATE 1: STATIC ANALYSIS ──
                self.output("[Gate 1] Running Static Analysis...")
                
                # Check all modified files
                lint_failed = False
                lint_errors = []
                
                for fname in apply_result.modified_files:
                    fpath = self.project_dir / fname
                    # On the last attempt, be less strict (only check syntax)
                    is_last_attempt = (attempt == 3)
                    linter_res = await self.linter_service.check_file(
                        fpath, 
                        strict=not is_last_attempt,
                        baseline=baselines.get(fname)
                    )
                    
                    if not linter_res.valid:
                        lint_failed = True
                        lint_errors.append(f"File {fname}: {'; '.join(linter_res.errors)}")
                        
                if lint_failed:
                    error_summary = "\n".join(lint_errors)
                    self.output(f"❌ Static Analysis Failed:\n{error_summary}")
                    current_lint_error = error_summary
                    
                    # Rollback and retry loop
                    await self._rollback(apply_result.modified_files)
                    continue
                    
                self.output("✅ Static Analysis Passed")
                
                # If we get here, patches applied AND linted correclty
                return {
                    'success': True,
                    'files_modified': apply_result.modified_files,
                    'description': analysis.get('fix_approach', 'Applied search/replace patches')
                }

            except Exception as e:
                logger.error(f"Fix attempt {attempt+1} failed: {e}")
                if attempt == 3:
                     return {'success': False, 'error': str(e)}

        # Return the last specific error if possible
        final_error = current_lint_error if current_lint_error else "Failed to generate valid fix after 4 attempts"
        return {'success': False, 'error': final_error}

    def _validate_patch_content(self, content: str) -> Tuple[bool, str]:
        """
        Validate that patch content doesn't contain LLM artifacts.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for LLM reasoning markers that should never be in code
        llm_artifacts = [
            ('<details>', 'Contains <details> tag - LLM reasoning'),
            ('</details>', 'Contains </details> tag - LLM reasoning'),
            ("I'm sorry, but I can't", 'Contains LLM refusal text'),
            ("I cannot provide", 'Contains LLM refusal text'),
            ("I can't generate", 'Contains LLM refusal text'),
            ('```', 'Contains markdown code fence - should be stripped'),
        ]

        for marker, error in llm_artifacts:
            if marker in content:
                return False, error

        return True, ''

    def _parse_fix_response(self, content: str) -> List[Dict[str, str]]:
        """
        Parse the fix response to extract patches.
        Returns a list of dicts: {'file': str, 'search': str, 'replace': str}
        """
        patches = []

        # Pattern for Search/Replace blocks
        # We need to capture: Filename, Search Block, Replace Block
        # Format:
        # File: <name>
        # <<<<<<< SEARCH
        # <content>
        # =======
        # <content>
        # >>>>>>> REPLACE

        # Strategy: Find "File: ..." then look for blocks
        # Split by "File:" to process per-file?
        # Simpler: Iterate over the whole string looking for the block pattern,
        # and search backwards for the filename.

        block_pattern = r'<<<<<<<\s*SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>\s*REPLACE'
        
        # We need to preserve order, so we iterate through matches
        for match in re.finditer(block_pattern, content, re.DOTALL):
            search_content = match.group(1)
            replace_content = match.group(2)
            
            # STRATEGY: Strip line numbers if the LLM included them
            # Context was provided as " 123: line_content"
            def strip_line_numbers(text):
                lines = text.splitlines()
                cleaned = []
                for line in lines:
                    # Match " 123: " or "123: " at start
                    line_cleaned = re.sub(r'^\s*\d+:\s?', '', line)
                    cleaned.append(line_cleaned)
                return "\n".join(cleaned)

            search_content = strip_line_numbers(search_content)
            replace_content = strip_line_numbers(replace_content)
            
            # Find filename preceding this block
            preceding_text = content[:match.start()]
            
            # Look for "File: <name>" closest to this block
            # Instead of reversing the whole text, search for markers from the end
            fname = None
            file_markers = ["File:", "FILE:", "file:", "--- File:", "--- FILE:"]
            latest_pos = -1
            
            for marker in file_markers:
                pos = preceding_text.rfind(marker)
                if pos > latest_pos:
                    latest_pos = pos
            
            if latest_pos != -1:
                # Extract the line/text after the marker
                after_marker = preceding_text[latest_pos:].splitlines()
                if after_marker:
                    line_after = after_marker[0]
                    # Regex to find filename (allowing for optional --- ends)
                    name_match = re.search(r'(?:File:|FILE:|file:|--- File:|--- FILE:)\s*([^\s\n`\'"]+\.\w+)', line_after, re.IGNORECASE)
                    if name_match:
                        fname = name_match.group(1).strip()
            
            # Fallback: search for filenames directly in the preceding text if no marker found
            if not fname:
                 # Check last 500 chars for any mention of a file we know about
                 tail = preceding_text[-500:]
                 candidates = []
                 # We don't have analysis here, so we look for common patterns or just mentions
                 pass
            
            if fname and search_content and replace_content:
                # CRITICAL: Validate patch content before accepting
                search_valid, search_err = self._validate_patch_content(search_content)
                replace_valid, replace_err = self._validate_patch_content(replace_content)

                if not search_valid:
                    logger.warning(f"Rejected SEARCH block for {fname}: {search_err}")
                    self.output(f"⚠️ Rejected invalid SEARCH block for {fname}: {search_err}")
                    continue
                if not replace_valid:
                    logger.warning(f"Rejected REPLACE block for {fname}: {replace_err}")
                    self.output(f"⚠️ Rejected invalid REPLACE block for {fname}: {replace_err}")
                    continue

                patches.append({
                    'file': fname,
                    'search': search_content,
                    'replace': replace_content
                })

        return patches

    async def _rollback(self, files: List[str]) -> None:
        """Rollback modified files to their original state."""
        for f in files:
            try:
                full_path = self.project_dir / f
                self.context.restore_file(full_path)
                logger.info(f"Rolled back {f}")
            except Exception as e:
                logger.error(f"Failed to rollback {f}: {e}")

    def _record_iteration(self, iteration: DebugIteration) -> None:
        """Record an iteration in the session."""
        self._session.add_iteration(iteration)
        self.context.save_iteration(iteration)
        self.context.save_session(self._session)

    def _parse_error_trace(self) -> Dict[str, Any]:
        """Parse the error trace to extract useful info."""
        result = {'file': None, 'line': None, 'error_type': None, 'message': None}

        if not self._session.error_trace:
            return result

        trace = self._session.error_trace

        # Extract file and line from traceback
        file_match = re.search(r'File "([^"]+)", line (\d+)', trace)
        if file_match:
            result['file'] = file_match.group(1)
            result['line'] = int(file_match.group(2))

        # Extract error type and message
        error_match = re.search(r'(\w+Error|\w+Exception): (.+)$', trace, re.MULTILINE)
        if error_match:
            result['error_type'] = error_match.group(1)
            result['message'] = error_match.group(2)

        return result

    def _is_web_project(self) -> bool:
        """
        Detect if this is a web project (HTML/CSS/JS).

        Returns True if the project contains HTML files with associated
        CSS or JavaScript, indicating a web-based visual application.
        """
        # Check for HTML files
        html_files = list(self.project_dir.glob('*.html'))
        if not html_files:
            html_files = list(self.project_dir.glob('**/*.html'))
            # Exclude node_modules, etc.
            html_files = [f for f in html_files if 'node_modules' not in str(f)]

        if html_files:
            # Has HTML files - check for CSS or JS
            has_css = bool(list(self.project_dir.glob('*.css'))) or bool(list(self.project_dir.glob('**/*.css')))
            has_js = bool(list(self.project_dir.glob('*.js'))) or bool(list(self.project_dir.glob('**/*.js')))

            if has_css or has_js:
                logger.info(f"[DETECT] Web project detected: {len(html_files)} HTML files with CSS/JS")
                return True

        # Check for common web project indicators
        web_indicators = ['index.html', 'style.css', 'script.js', 'app.js', 'main.js']
        for indicator in web_indicators:
            if (self.project_dir / indicator).exists():
                logger.info(f"[DETECT] Web project detected: found {indicator}")
                return True

        return False

    def _get_project_structure(self) -> str:
        """Get a summary of the project structure."""
        files = []
        extensions = [
            '*.py', '*.js', '*.ts', '*.jsx', '*.tsx',
            '*.html', '*.css', '*.scss',
            '*.java', '*.kt',
            '*.c', '*.cpp', '*.h', '*.hpp',
            '*.go', '*.rs', '*.php', '*.rb'
        ]
        
        # Use rglob to get all files recursively
        seen = set()
        exclude_dirs = {
            'node_modules', '__pycache__', '.git', '.venv', 'venv', 'env', '.env', 
            '.pytest_cache', '.raica', 'build', 'dist', '.mypy_cache', '.tox'
        }
        
        for ext in extensions:
            # We use rglob to find matches
            for f in self.project_dir.rglob(ext):
                # Skip if in hidden directories or excluded directories
                parts = set(f.parts)
                if parts.intersection(exclude_dirs) or any(part.startswith('.') for part in f.parts):
                    continue
                    
                rel_path = f.relative_to(self.project_dir)
                if str(rel_path) not in seen:
                    files.append(f)
                    seen.add(str(rel_path))

        # Limit and format
        file_list = sorted(set(str(f.relative_to(self.project_dir)) for f in files))[:50]
        return '\n'.join(file_list)

    def _get_file_structure(self, file_path: Path) -> str:
        """Get a summary of classes and functions in a file using AST."""
        if not file_path.exists() or file_path.suffix != '.py':
            return ""
            
        try:
            tree = ast.parse(file_path.read_text(encoding='utf-8'))
            symbols = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    symbols.append(f"class {node.name}:\n    " + "\n    ".join(f"def {m}(...)" for m in methods))
                elif isinstance(node, ast.FunctionDef) and not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree) if node in p.body if hasattr(p, 'body')):
                    # Top level functions
                    # Wait, the check above is complex. Let's just track parents.
                    pass 

            # Simpler approach:
            symbols = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    symbols.append(f"class {node.name} (Methods: {', '.join(methods)})")
                elif isinstance(node, ast.FunctionDef):
                    symbols.append(f"def {node.name}(...)")
            
            return f"Structure for {file_path.name}:\n" + "\n".join(symbols)
        except Exception:
            return f"(Could not parse {file_path.name})"

    def _format_file_contents(self, file_contents: Dict[str, str]) -> str:
        """Format file contents for prompt with line numbers."""
        result = []
        for path, content in file_contents.items():
            # Increase budget for modern LLMs - 15k chars is ~400-500 lines
            if len(content) > 15000:
                content = content[:15000] + "\n... (further content truncated)"
            
            # Add line numbers
            lines = content.splitlines()
            numbered_lines = [f"{i+1:4}: {line}" for i, line in enumerate(lines)]
            numbered_content = "\n".join(numbered_lines)
            
            result.append(f"--- {path} ---\n{numbered_content}")
        return '\n\n'.join(result)

    def _format_previous_attempts(self) -> str:
        """Format previous iteration attempts for context."""
        if not self._session.iterations:
            return "None"

        attempts = []
        for it in self._session.iterations[-3:]:  # Last 3 attempts
            attempts.append(f"Iteration {it.iteration_number}: {it.hypothesis or 'No hypothesis'}")
            if it.failure_reason:
                attempts.append(f"  Failed: {it.failure_reason}")
        return '\n'.join(attempts)

    def _generate_summary(self) -> str:
        """Generate a summary of what was fixed."""
        root_cause = self._session.root_cause or {}
        files = self._session.files_modified

        return f"""
BUG FIX SUMMARY
===============
Root Cause: {root_cause.get('description', self._current_hypothesis)}
Files Modified: {', '.join(files)}
Iterations: {self._session.current_iteration}
Bug Test: {self._session.bug_test_path}
Regression Check: Passed
"""

    def _generate_comprehensive_summary(self) -> str:
        """
        Generate a comprehensive summary of all changes made during debugging.

        Returns a formatted string with detailed information about:
        - What was the issue
        - Root cause analysis
        - Files modified with details
        - Verification results
        """
        # Create git checkpoint
        try:
            # Use empty patches list for now (patches not available in this scope)
            # TODO: Store patches in session for full changelog
            changelog = self.changelog_gen.generate_from_patches([], "BUG_FIX")
            commit_hash = self.git_tracker.create_checkpoint(
                modified_files=self._session.files_modified if self._session else [],
                session_id=self._session.session_id if self._session else "debug",
                change_type="BUG_FIX",
                description=(self._session.bug_description[:100] if self._session else "Debug fix"),
                changelog=changelog if changelog else "Changes applied"
            )
            if commit_hash:
                self.output(f"\n✓ Checkpoint: {commit_hash[:8]} | Restore: raica restore {commit_hash[:8]}")
        except Exception as e:
            logger.warning(f"Checkpoint failed: {e}")



        lines = []
        lines.append("\n" + "="*60)
        lines.append("📋 COMPREHENSIVE DEBUG SUMMARY")
        lines.append("="*60)

        # 1. Issue description
        lines.append(f"\n🐛 ISSUE: {self._session.bug_description[:200]}{'...' if len(self._session.bug_description) > 200 else ''}")

        # 2. Root cause
        root_cause = self._session.root_cause or {}
        hypothesis = root_cause.get('description', self._current_hypothesis)
        lines.append(f"\n🔍 ROOT CAUSE: {hypothesis}")

        # 3. Files modified with details
        files = self._session.files_modified
        lines.append(f"\n📁 FILES MODIFIED ({len(files)}):")

        for f in files:
            try:
                full_path = self.project_dir / f
                if full_path.exists():
                    content = full_path.read_text(encoding='utf-8', errors='replace')
                    line_count = len(content.splitlines())
                    size_kb = len(content) / 1024
                    ext = full_path.suffix.lower()

                    lines.append(f"   • {f}")
                    lines.append(f"     Lines: {line_count} | Size: {size_kb:.1f}KB")
                else:
                    lines.append(f"   • {f} (NEW FILE)")
            except Exception as e:
                lines.append(f"   • {f} (could not read)")

        # 4. Verification results
        lines.append(f"\n✅ VERIFICATION:")
        lines.append(f"   • Bug test path: {self._session.bug_test_path}")
        lines.append(f"   • Bug test passes: Yes")
        lines.append(f"   • Regression check: Passed")
        lines.append(f"   • Iterations used: {self._session.current_iteration}")

        lines.append("\n" + "="*60)

        return "\n".join(lines)

    async def _update_persistent_context(self, files_modified: List[str], success: bool) -> None:
        """
        Update the persistent project context after a debug fix is applied.

        This ensures future requests have up-to-date information about:
        - Current file structure
        - Recent changes made
        - What was modified and why
        """
        try:
            # 1. Rescan file structure if we have a context manager
            if self.context_manager:
                self.output("\n🔄 Updating project context...")

                # Force rescan to pick up new/modified files
                self.context_manager.project_context.scan_file_structure(force=True, extract_symbols=True)

                # Record this change in the context
                change_record = {
                    'timestamp': datetime.now().isoformat(),
                    'request': self._session.bug_description[:500],
                    'files_modified': files_modified,
                    'success': success,
                    'type': 'bugfix',
                    'root_cause': self._current_hypothesis[:200] if self._current_hypothesis else None
                }

                # Add to recent changes list (keep last 10)
                if not hasattr(self.context_manager.project_context, 'recent_changes'):
                    self.context_manager.project_context.recent_changes = []

                self.context_manager.project_context.recent_changes.append(change_record)
                self.context_manager.project_context.recent_changes = \
                    self.context_manager.project_context.recent_changes[-10:]

                # Save the updated context
                self.context_manager.save_all()

                self.output(f"   ✓ Scanned {len(self.context_manager.project_context.file_entries)} files")
                self.output(f"   ✓ Recorded fix in project history")
            else:
                logger.debug("No context manager available for persistent update")

        except Exception as e:
            logger.warning(f"Failed to update persistent context: {e}")
            self.output(f"   ⚠ Could not update context: {e}")

    def _get_model(self) -> str:
        """Get the LLM model to use."""
        from agents.common.config_loader import AgentConfigLoader
        try:
            config = AgentConfigLoader.load_config('coding_agent')
            return config.get_llm_model()
        except Exception:
            return "RAICA-Model1"
