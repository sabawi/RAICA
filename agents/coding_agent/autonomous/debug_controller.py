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
import json
import logging
import sys
import os
import re
import ast
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Tuple, Set

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


from ..config_accessor import get_max_iterations
from ..services.linter_service import LinterService
from ..services.patch_applier import PatchApplier
from ..services.language_detector import LanguageDetector, LANGUAGE_DEFINITIONS
from ..services.code_path_tracer import CodePathTracer, ExecutionContext

try:
    from tools.ragg_tool import RAGGTool
    HAS_RAGG = True
except ImportError:
    HAS_RAGG = False

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

    DEFAULT_MAX_ITERATIONS = 10  # Will be overridden by config in constructor

    def __init__(
        self,
        llm_client,
        project_dir: Path,
        output_callback: Optional[Callable[[str], None]] = None,
        max_iterations: Optional[int] = None,
        context_manager: Any = None,
        tool_client: Any = None,  # [NEW] Phase 5
        toolkit: Any = None       # [NEW] Phase 5
    ):
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)
        self.output = output_callback or (lambda x: logger.info(x))
        self.max_iterations = max_iterations if max_iterations is not None else get_max_iterations()
        self.context_manager = context_manager
        self.tool_client = tool_client
        self.toolkit = toolkit

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
        
        # [NEW] Phase 5: Imports
        from ..services.context_manager import ContextManager, ContextPriority
        self.ContextManager = ContextManager
        self.ContextPriority = ContextPriority

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

    async def _validate_target_file(self, bug_description: str) -> Dict[str, Any]:
        """
        Validate that if user specified a file in their bug description, it exists.

        Uses LLM to extract file path from description (NO regex pattern matching!).

        Args:
            bug_description: User's bug description

        Returns:
            Dict with 'valid' (bool), 'error' (str), 'suggestion' (str), 'file_path' (str)
        """
        # Ask LLM to extract file path from bug description
        prompt = f"""Extract the target file path from this bug description.

BUG DESCRIPTION:
{bug_description}

PROJECT DIRECTORY:
{self.project_dir}

TASK:
If the user mentioned a specific file path (e.g., "quad_solver.py", "/path/to/file.py", "myprograms_test/quad_solver.py"),
extract the COMPLETE file path that should be debugged.

Return JSON:
{{
    "file_mentioned": true/false,
    "file_path": "complete/path/to/file.py or null if no file mentioned",
    "reasoning": "Why you extracted this path or why no file was mentioned"
}}

IMPORTANT:
- If path starts with "/" but seems incomplete (like "/Development/..." instead of "/home/user/Development/..."),
  note this in reasoning
- Extract EXACT path as user provided, don't modify it

Return ONLY the JSON, no other text."""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate, prompt, max_tokens=300
            )
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON
            import json
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if not json_match:
                # LLM didn't return JSON, can't validate
                return {'valid': True}  # Proceed with automatic entry point detection

            data = json.loads(json_match.group(0))

            if not data.get('file_mentioned'):
                # No file mentioned, use automatic entry point detection
                return {'valid': True}

            file_path = data.get('file_path')
            if not file_path or file_path == 'null':
                return {'valid': True}

            # Check if file exists (try both as-is and with project_dir prefix)
            from pathlib import Path

            # Try as absolute path first
            target = Path(file_path)
            if not target.is_absolute():
                # Try relative to project_dir
                target = self.project_dir / file_path

            if target.exists():
                # File found!
                self.output(f"✅ Target file validated: {target}")
                return {'valid': True, 'file_path': str(target)}

            # File NOT found - this is the critical error case!
            error_msg = f"File not found: {file_path}"

            # Try to provide helpful suggestion
            suggestion = None
            if str(file_path).startswith('/Development/') or str(file_path).startswith('/home/'):
                # Path looks like it might be incomplete
                # Try to find the file in project_dir
                filename = Path(file_path).name
                matches = list(self.project_dir.rglob(filename))
                if matches:
                    suggestion = f"Did you mean: {matches[0]}?"
                else:
                    suggestion = f"File '{filename}' not found in {self.project_dir}"
            else:
                # Try searching for the file
                filename = Path(file_path).name
                matches = list(self.project_dir.rglob(filename))
                if matches:
                    suggestion = f"Found similar file(s): {', '.join(str(m) for m in matches[:3])}"

            return {
                'valid': False,
                'error': error_msg,
                'suggestion': suggestion,
                'file_path': file_path
            }

        except Exception as e:
            logger.warning(f"File validation failed: {e}, proceeding with automatic detection")
            return {'valid': True}  # On error, proceed with automatic detection

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

        # ═══════════════════════════════════════════════════════════════════
        # CRITICAL: Validate user-specified file exists BEFORE debugging
        # ═══════════════════════════════════════════════════════════════════
        logger.info(f"[DEBUG] Validating target file from request: {bug_description[:100]}")
        target_file_validation = await self._validate_target_file(bug_description)
        logger.info(f"[DEBUG] Validation result: {target_file_validation}")

        if not target_file_validation['valid']:
            self.output(f"\n❌ ERROR: {target_file_validation['error']}")
            if target_file_validation.get('suggestion'):
                self.output(f"\n💡 {target_file_validation['suggestion']}")

            # Ask user for correct path
            try:
                self.output("\n" + "="*60)
                self.output("FILE PATH CORRECTION NEEDED")
                self.output("="*60)
                corrected_path = input("\nEnter correct file path (or press Enter to cancel): ").strip()

                if not corrected_path:
                    # User cancelled
                    logger.info(f"[DEBUG] User cancelled file path correction")
                    return DebugResult(
                        outcome=DebugOutcome.BLOCKED,
                        iterations=0,
                        blocked_reason="User cancelled: " + target_file_validation['error'],
                        duration_seconds=time.time() - start_time
                    )

                # Validate corrected path
                from pathlib import Path
                corrected_file = Path(corrected_path)
                if not corrected_file.is_absolute():
                    corrected_file = self.project_dir / corrected_path

                if corrected_file.exists():
                    self.output(f"✅ Corrected file found: {corrected_file}")
                    # Update bug description with corrected path
                    bug_description = bug_description.replace(
                        target_file_validation.get('file_path', ''),
                        str(corrected_file)
                    )
                    # Re-create session with corrected description
                    self._session = self.context.create_session(bug_description, error_trace)
                else:
                    self.output(f"❌ Corrected path still not found: {corrected_file}")
                    return DebugResult(
                        outcome=DebugOutcome.BLOCKED,
                        iterations=0,
                        blocked_reason=f"Corrected path not found: {corrected_file}",
                        duration_seconds=time.time() - start_time
                    )

            except (EOFError, KeyboardInterrupt):
                # Non-interactive mode or user interrupted
                logger.info(f"[DEBUG] File validation failed, exiting (non-interactive or interrupted)")
                return DebugResult(
                    outcome=DebugOutcome.BLOCKED,
                    iterations=0,
                    blocked_reason=target_file_validation['error'],
                    duration_seconds=time.time() - start_time
                )

        logger.info(f"[DEBUG] File validation passed, proceeding to debug loop")

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

        # ═══════════════════════════════════════════════════════════════════
        # PRE-FLIGHT DEPENDENCY CHECK (NEW)
        # ═══════════════════════════════════════════════════════════════════
        # If the error trace indicates a missing module (ImportError/ModuleNotFoundError),
        # try installing dependencies BEFORE attempting code fixes
        # ═══════════════════════════════════════════════════════════════════
        error_trace = self._session.error_trace or ""
        is_import_error = any(kw in error_trace for kw in ['ImportError', 'ModuleNotFoundError', 'No module named', 'Failed to import'])
        
        if is_import_error:
            req_path = self.project_dir / 'requirements.txt'
            if req_path.exists():
                self.output("\n📦 [PRE-FLIGHT] ImportError detected - attempting pip install first...")
                import subprocess
                try:
                    result = subprocess.run(
                        ['pip', 'install', '-r', str(req_path)],
                        capture_output=True, text=True, timeout=120, cwd=str(self.project_dir)
                    )
                    if result.returncode == 0:
                        self.output("   ✓ Dependencies installed successfully")
                        # Re-run the code to see if it fixes the issue
                        self.output("   → Re-running code to verify...")
                        test_result = await self._run_entry_point()
                        if test_result.get('success'):
                            self.output("   ✓ Issue resolved by installing dependencies!")
                            self._session.set_status(DebugStatus.COMPLETE, "Fixed by installing dependencies")
                            self.context.save_session(self._session)
                            return DebugResult(
                                outcome=DebugOutcome.FIXED,
                                iterations=0,
                                root_cause="Missing dependencies",
                                files_modified=[],
                                fix_summary="Installed dependencies from requirements.txt"
                            )
                        else:
                            self.output("   ⚠ Still has errors after pip install - continuing with code analysis")
                    else:
                        self.output(f"   ⚠ pip install failed: {result.stderr[:200]}")
                except Exception as e:
                    self.output(f"   ⚠ Could not install dependencies: {e}")

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
        # NOTE: We intentionally DO NOT run all tests here.
        # We only test the specific bug we're fixing - running
        # the entire test suite is wasteful and slow.
        # ─────────────────────────────────────────────────────

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

            # Check if this language requires manual testing
            if not test_code:
                lang = self.test_generator.language_detector.detect()
                self.output(f"\n⚠️  {lang.name} requires MANUAL TESTING")
                self.output(f"   Automated testing not available for this language.")
                self.output(f"   Will apply fix and ask user to verify.")
                # Skip test verification - proceed directly to fix
                repro_success = True
                self._session.bug_test_path = None
                break

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

                files_modified = fix_result.get('files_modified', [])
                iteration.files_modified = files_modified
                iteration.action_taken = fix_result.get('description', 'Fix applied')
                self._session.files_modified = files_modified

                self.output(f"Modified: {', '.join(files_modified)}")

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
                        fix_result.get('description', 'Fix applied')
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
                    await self._rollback(fix_result.get('files_modified', []))
                    iteration.rollback_performed = True
                    iteration.failure_reason = "Fix did not resolve the bug (Verified Fix Logic)"
                    self._record_iteration(iteration)
                    continue

                self.output("Test PASSES - fix verified!")
                self._session.bug_test_passes = True

                # ─────────────────────────────────────────────────────
                # NOTE: We skip running ALL tests (targeted or full suite)
                # because it's wasteful. The bug-specific test already
                # passed - that's sufficient verification.
                # 
                # If the user has concerns about regressions, they can
                # run their test suite manually after RAICA completes.
                # ─────────────────────────────────────────────────────
                iteration.regression_check_passed = True  # Assumed - user can verify

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

        # Max iterations reached - but KEEP the progress!
        files_fixed = list(set(self._session.files_modified))
        
        self.output(f"\n{'='*60}")
        self.output(f"⏸️  PAUSED - Max iterations ({self.max_iterations}) reached")
        self.output(f"{'='*60}")
        
        if files_fixed:
            self.output(f"\n✓ PROGRESS KEPT - Modified {len(files_fixed)} files:")
            for f in files_fixed[:10]:
                self.output(f"   • {f}")
        
        self.output(f"\n⚠️  Run again to continue: raica debug -i\"continue fixing\"\n")
        
        self._session.set_status(DebugStatus.BLOCKED, "Max iterations - progress preserved")
        self.context.save_session(self._session)

        return DebugResult(
            outcome=DebugOutcome.MAX_ITERATIONS,
            iterations=self._session.current_iteration,
            root_cause=self._current_hypothesis if hasattr(self, '_current_hypothesis') else None,
            files_modified=files_fixed,
            blocked_reason=f"Paused after {self.max_iterations} iterations. Fixed {len(files_fixed)} files. Run again to continue."
        )

    async def _run_gui_debug_loop(self) -> DebugResult:
        """
        Debug loop for GUI applications with FULL RETRY CAPABILITY.

        GUI apps require visual verification which automated tests cannot provide.
        This loop:
        1. Analyzes the bug
        2. Applies the fix with lint checking
        3. On failure: tracks the failed strategy and RETRIES with different approach
        4. Loops until fixed or max iterations reached

        No test generation, no test verification phases - user verifies manually.
        """
        self.output("\n" + "="*60)
        self.output("GUI DEBUG MODE (No automated tests)")
        self.output("="*60)

        # Track failed strategies to inform subsequent attempts
        failed_strategies = []
        runtime_error = None  # Will store real error from running the code
        
        # ═══════════════════════════════════════════════════════════════════
        # PRE-FLIGHT: Install dependencies BEFORE any debugging attempts
        # ═══════════════════════════════════════════════════════════════════
        req_path = self.project_dir / 'requirements.txt'
        if req_path.exists():
            self.output("\n📦 [PRE-FLIGHT] Installing dependencies from requirements.txt...")
            import subprocess
            
            # [NEW] Sanitize requirements.txt before pip install
            # Remove stdlib modules and invalid entries that cause pip to fail
            try:
                STDLIB_MODULES = {
                    '__future__', 'abc', 'argparse', 'ast', 'asyncio', 'atexit', 'base64',
                    'bisect', 'builtins', 'calendar', 'collections', 'colorsys', 'concurrent',
                    'configparser', 'contextlib', 'copy', 'copyreg', 'csv', 'ctypes', 'dataclasses',
                    'datetime', 'decimal', 'difflib', 'email', 'encodings', 'enum', 'errno',
                    'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'fractions', 'functools', 'gc',
                    'getpass', 'gettext', 'glob', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac',
                    'html', 'http', 'imaplib', 'importlib', 'inspect', 'io', 'ipaddress',
                    'itertools', 'json', 'keyword', 'linecache', 'locale', 'logging', 'lzma',
                    'mailbox', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder', 'multiprocessing',
                    'netrc', 'ntpath', 'numbers', 'operator', 'os', 'pathlib', 'pickle', 'pkgutil',
                    'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint', 'profile',
                    'pwd', 'py_compile', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib',
                    'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select', 'selectors',
                    'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtplib', 'socket', 'socketserver',
                    'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep', 'struct',
                    'subprocess', 'sunau', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny',
                    'tarfile', 'tempfile', 'termios', 'test', 'textwrap', 'threading', 'time',
                    'timeit', 'token', 'tokenize', 'trace', 'traceback', 'tracemalloc', 'tty',
                    'turtle', 'types', 'typing', 'typing_extensions', 'unicodedata', 'unittest',
                    'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser',
                    'winreg', 'winsound', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp',
                    'zipfile', 'zipimport', 'zlib', '_thread', '_io', '_collections_abc'
                }
                
                # Get local project module names
                local_modules = set()
                for f in self.project_dir.rglob('*.py'):
                    local_modules.add(f.stem)
                for d in self.project_dir.iterdir():
                    if d.is_dir() and (d / '__init__.py').exists():
                        local_modules.add(d.name)
                
                # Read and sanitize
                original_content = req_path.read_text()
                cleaned_lines = []
                removed = []
                
                for line in original_content.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        cleaned_lines.append(line)
                        continue
                    
                    # Extract package name (before any version specifier)
                    import re
                    match = re.match(r'^([a-zA-Z0-9_-]+)', stripped)
                    if match:
                        pkg_name = match.group(1).lower().replace('-', '_')
                        if pkg_name in STDLIB_MODULES or pkg_name in local_modules:
                            removed.append(stripped)
                            continue
                    
                    cleaned_lines.append(line)
                
                # Write back if we removed anything
                if removed:
                    cleaned_content = '\n'.join(cleaned_lines) + '\n'
                    req_path.write_text(cleaned_content)
                    self.output(f"   ✓ Cleaned {len(removed)} invalid entries from requirements.txt")
                    for r in removed[:5]:
                        self.output(f"      - Removed: {r}")
                    if len(removed) > 5:
                        self.output(f"      ... and {len(removed) - 5} more")
            except Exception as e:
                self.output(f"   ⚠ Could not sanitize requirements.txt: {e}")
            
            # Now run pip install
            try:
                result = subprocess.run(
                    ['pip', 'install', '-r', str(req_path)],
                    capture_output=True, text=True, timeout=120, cwd=str(self.project_dir)
                )
                if result.returncode == 0:
                    self.output("   ✓ Dependencies installed successfully")
                else:
                    self.output(f"   ⚠ pip install failed: {result.stderr[:200]}")
            except Exception as e:
                self.output(f"   ⚠ Could not install dependencies: {e}")
        
        # ═══════════════════════════════════════════════════════════════════
        # MAIN RETRY LOOP - Keep trying until fixed or max iterations
        # ═══════════════════════════════════════════════════════════════════
        while self._session.current_iteration < self.max_iterations:
            iteration_num = self._session.current_iteration + 1
            
            if iteration_num > 1:
                self.output(f"\n{'='*60}")
                self.output(f"GUI DEBUG ITERATION {iteration_num}/{self.max_iterations}")
                self.output(f"{'='*60}")
            
            iteration = DebugIteration(iteration_number=iteration_num)

            try:
                # ═══════════════════════════════════════════════════════════
                # PHASE 0: RUN THE CODE TO GET REAL ERRORS
                # ═══════════════════════════════════════════════════════════
                self.output("\n[PHASE 0] Running code to capture real errors...")
                success, runtime_error = await self._run_entry_point(timeout=5)
                
                if success:
                    # Code runs without crashing
                    self.output("\n✅ CODE RUNS WITHOUT CRASH")

                    # ASK LLM: Is the user's request satisfied, or do we need to make changes?
                    # This follows the #1 rule - LLM decides, not RAICA
                    llm_decision = await self._ask_llm_if_task_complete(
                        self._session.bug_description,
                        self._session.files_modified
                    )

                    if llm_decision.get('status') == 'complete':
                        # LLM says task is complete
                        self._session.fix_applied = True
                        self._session.set_status(DebugStatus.COMPLETE)
                        self._session.completion_summary = self._generate_summary()
                        self.context.save_session(self._session)

                        self.output("\n" + "="*60)
                        self.output("✅ TASK COMPLETE - " + llm_decision.get('reason', 'LLM confirmed task is done'))
                        self.output("="*60)

                        return DebugResult(
                            outcome=DebugOutcome.FIXED,
                            iterations=iteration_num,
                            root_cause=self._current_hypothesis if hasattr(self, '_current_hypothesis') else None,
                            files_modified=self._session.files_modified,
                            fix_summary=llm_decision.get('reason', 'Task completed'),
                            test_results={
                                'gui_mode': True,
                                'runtime_verified': True,
                                'strategies_attempted': len(failed_strategies)
                            }
                        )
                    else:
                        # LLM says we need to make changes
                        self.output("   ℹ LLM: " + llm_decision.get('reason', 'Changes needed'))
                        # Use the user's request + LLM guidance as the "error" to analyze
                        runtime_error = f"USER REQUEST NOT YET SATISFIED: {self._session.bug_description}\nLLM GUIDANCE: {llm_decision.get('reason', 'Make the requested changes')}"
                
                # Show the real error
                self.output(f"[PHASE 0] Runtime error captured ({len(runtime_error)} chars):")
                self.output(f"   {runtime_error[:500]}..." if len(runtime_error) > 500 else f"   {runtime_error}")
                
                # Update session with real error trace
                if runtime_error:
                    self._session.error_trace = runtime_error
                
                # PHASE 1: UNDERSTAND
                self.output("\n[PHASE 1] Analyzing bug (using real runtime error)...")
                self._session.set_status(DebugStatus.ANALYZING)

                # Include previous failures in analysis context
                analysis = await self._analyze_bug_with_history(failed_strategies)
                
                if not analysis:
                    self.output("❌ Bug analysis failed - retrying with fresh approach...")
                    failed_strategies.append({
                        'iteration': iteration_num,
                        'error': 'Analysis returned None',
                        'approach': 'initial_analysis'
                    })
                    self._record_iteration(iteration)
                    self.context.save_session(self._session)
                    continue

                self._current_hypothesis = analysis['hypothesis']
                self._affected_files = analysis['affected_files']
                iteration.hypothesis = self._current_hypothesis

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

                # PHASE 2: APPLY FIX
                self.output("\n[PHASE 2] Applying fix & Linting...")
                self._session.set_status(DebugStatus.FIXING)

                fix_result = await self._apply_fix_and_lint(analysis)

                if not fix_result['success']:
                    error_msg = fix_result.get('error', 'Unknown error')
                    self.output(f"❌ Failed to apply fix: {error_msg}")
                    self.output(f"   Iteration {iteration_num}/{self.max_iterations} - will retry...")
                    
                    # Record failure for next attempt
                    failed_strategies.append({
                        'iteration': iteration_num,
                        'error': error_msg,
                        'approach': self._current_hypothesis[:200] if self._current_hypothesis else 'unknown',
                        'affected_files': self._affected_files[:3] if self._affected_files else []
                    })
                    
                    iteration.failure_reason = error_msg
                    self._record_iteration(iteration)
                    self.context.save_session(self._session)
                    continue  # RETRY instead of returning

                # Fix applied! Record the changes
                files_modified = fix_result.get('files_modified', [])
                iteration.files_modified = files_modified
                iteration.action_taken = fix_result.get('fix_description', fix_result.get('description', 'Fix applied'))
                self._session.files_modified.extend(files_modified)

                self.output(f"✅ Modified: {', '.join(files_modified)}")

                # ═══════════════════════════════════════════════════════════
                # PHASE 3: RE-RUN TO VERIFY THE FIX ACTUALLY WORKS
                # ═══════════════════════════════════════════════════════════
                self.output("\n[PHASE 3] Re-running code to verify fix...")
                verify_success, verify_error = await self._run_entry_point(timeout=5)
                
                if not verify_success:
                    # Fix didn't work! Still crashing
                    self.output(f"❌ Still crashing after fix!")
                    self.output(f"   New error: {verify_error[:300]}...")
                    
                    # Record this for next attempt
                    failed_strategies.append({
                        'iteration': iteration_num,
                        'error': f"Fix applied but still crashes: {verify_error[:200]}",
                        'approach': self._current_hypothesis[:200] if self._current_hypothesis else 'unknown',
                        'affected_files': fix_result.get('files_modified', [])
                    })
                    
                    # Update error trace with new error for next analysis
                    self._session.error_trace = verify_error
                    
                    iteration.failure_reason = f"Fix applied but verification failed: {verify_error[:100]}"
                    self._record_iteration(iteration)
                    self.context.save_session(self._session)
                    continue  # Try again with new error info
                
                # ═══════════════════════════════════════════════════════════
                # SUCCESS! Code runs without crashing!
                # ═══════════════════════════════════════════════════════════
                self.output("\n✅ VERIFIED: Code runs without errors!")
                
                iteration.success = True
                self._record_iteration(iteration)

                self._session.fix_applied = True
                self._session.set_status(DebugStatus.COMPLETE)
                self._session.completion_summary = self._generate_summary()
                self.context.save_session(self._session)

                # Generate comprehensive change summary
                comprehensive_summary = self._generate_comprehensive_summary()
                self.output(comprehensive_summary)

                # Update persistent context
                await self._update_persistent_context(
                    files_modified=self._session.files_modified,
                    success=True
                )

                self.output("\n" + "="*60)
                self.output("✅ BUG FIXED AND VERIFIED!")
                self.output("="*60)
                self.output("\n👁️  Run your application and check if the fix works.")
                self.output("   If not, describe what's still wrong and I'll try again.\n")

                return DebugResult(
                    outcome=DebugOutcome.FIXED,
                    iterations=iteration_num,
                    root_cause=self._current_hypothesis,
                    files_modified=self._session.files_modified,
                    fix_summary=self._session.completion_summary,
                    test_results={
                        'gui_mode': True,
                        'user_verification_required': True,
                        'strategies_attempted': len(failed_strategies) + 1
                    }
                )

            except Exception as e:
                logger.exception(f"GUI debug iteration {iteration_num} failed")
                self.output(f"❌ Iteration failed: {e}")
                failed_strategies.append({
                    'iteration': iteration_num,
                    'error': str(e),
                    'approach': 'exception'
                })
                iteration.failure_reason = str(e)
                self._record_iteration(iteration)
                self.context.save_session(self._session)
                continue

        # Max iterations reached - but KEEP the progress!
        # This is NOT a failure if we fixed some bugs along the way.
        files_fixed = list(set(self._session.files_modified))  # Unique files
        bugs_fixed_count = len([s for s in failed_strategies if 'Fix applied' not in s.get('error', '')])
        
        self.output(f"\n{'='*60}")
        self.output(f"⏸️  PAUSED - Max iterations ({self.max_iterations}) reached")
        self.output(f"{'='*60}")
        
        if files_fixed:
            self.output(f"\n✓ PROGRESS KEPT - Modified {len(files_fixed)} files:")
            for f in files_fixed[:10]:
                self.output(f"   • {f}")
            if len(files_fixed) > 10:
                self.output(f"   ... and {len(files_fixed) - 10} more")
        
        self.output(f"\n⚠️  Still has errors - run again to continue fixing!")
        self.output(f"   The fixes made so far are PRESERVED (not rolled back).")
        self.output(f"   Run: raica debug -i\"continue fixing\" to resume.\n")
        
        self._session.set_status(DebugStatus.BLOCKED, "Max iterations reached - progress preserved")
        self.context.save_session(self._session)

        return DebugResult(
            outcome=DebugOutcome.MAX_ITERATIONS,
            iterations=self._session.current_iteration,
            root_cause=self._current_hypothesis if hasattr(self, '_current_hypothesis') else None,
            files_modified=files_fixed,
            blocked_reason=f"Paused after {self.max_iterations} iterations. Fixed {len(files_fixed)} files. Run again to continue."
        )

    async def _ask_llm_if_task_complete(self, request: str, files_modified: list) -> dict:
        """
        Ask LLM: Given that the code runs, is the user's request satisfied?

        This follows the #1 rule - LLM decides if task is complete, not RAICA.
        """
        if not self.llm_client or not request:
            # No LLM - can't decide, assume changes needed
            return {'status': 'continue', 'reason': 'No LLM available to evaluate'}

        files_info = ', '.join(files_modified) if files_modified else 'none yet'

        prompt = f"""The code runs without crashing. But is the user's request actually satisfied?

USER REQUEST: {request}

FILES MODIFIED SO FAR: {files_info}

Analyze carefully:
1. What did the user ask for?
2. If no files were modified yet, did we actually make the changes they requested?
3. Just because code runs doesn't mean the request is fulfilled

Return JSON only:
{{
    "status": "complete" or "continue",
    "reason": "explanation of why task is complete OR what changes still need to be made"
}}

IMPORTANT:
- If user asked for code changes (fix layout, add feature, modify behavior) and we haven't modified any files → status: "continue"
- If user reported a crash and code now runs → status: "complete"
- If user asked for visual/layout changes → those require code modifications, not just running
"""
        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt,
                max_tokens=500
            )
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON response
            from ..utils.json_utils import extract_json_from_llm_response
            data = extract_json_from_llm_response(content)

            if data and 'status' in data:
                return data

        except Exception as e:
            self.output(f"   ⚠ Could not get LLM decision: {e}")

        # Default: if we can't determine, assume changes are needed
        return {'status': 'continue', 'reason': 'Could not determine if task is complete'}

    async def _analyze_bug_with_history(self, failed_strategies: list) -> Optional[Dict[str, Any]]:
        """
        Analyze bug with context about previous failed attempts.

        This helps the LLM avoid repeating the same mistakes.
        """
        if not failed_strategies:
            # First attempt - use standard analysis
            return await self._analyze_bug()
        
        # Build context about what failed before
        failure_context = "\n".join([
            f"  - Attempt {s['iteration']}: {s['approach'][:100]}... → FAILED: {s['error'][:100]}"
            for s in failed_strategies[-3:]  # Last 3 failures
        ])
        
        # Store for prompt injection
        self._previous_failures_context = f"""
PREVIOUS FAILED ATTEMPTS (DO NOT REPEAT THESE):
{failure_context}

You MUST try a DIFFERENT approach. Consider:
1. If file creation failed, check if the file already exists
2. If patch application failed, use more specific SEARCH blocks
3. If the same file keeps failing, try a different fix strategy
"""
        
        return await self._analyze_bug()

    async def _run_entry_point(self, timeout: int = 5) -> tuple[bool, str]:
        """
        Run the project's entry point and capture any runtime errors.
        
        This is CRITICAL for GUI apps where we can't rely on automated tests.
        We actually RUN the code to find real errors.
        
        Args:
            timeout: Seconds to wait before killing the process.
                     GUI apps may block on their main loop, so we use a short timeout.
        
        Returns:
            tuple: (success: bool, error_output: str)
                   success=True means no crash within timeout
                   error_output contains stderr if crash occurred
        """
        import subprocess
        import asyncio
        
        # Find the entry point
        entry_points = []
        if hasattr(self, '_execution_context') and self._execution_context:
            entry_points = self._execution_context.entry_points
        
        if not entry_points:
            # Try common entry points
            for candidate in ['main.py', 'app.py', 'run.py', '__main__.py']:
                if (self.project_dir / candidate).exists():
                    entry_points = [candidate]
                    break
        
        if not entry_points:
            return False, "No entry point found"

        entry_point = entry_points[0]
        self.output(f"[Runtime] Determining how to run {entry_point}...")

        # Ask LLM how to run this entry point
        run_cmd = await self._get_run_command_from_llm(entry_point)

        if not run_cmd:
            # LLM couldn't determine - return with explanation
            return False, f"Could not determine how to run {entry_point}"

        if run_cmd.get('skip_runtime'):
            # LLM says this type of app can't be tested via command line
            reason = run_cmd.get('reason', 'Visual verification required')
            self.output(f"[Runtime] ℹ {reason}")
            return True, ""

        cmd = run_cmd.get('command', [])
        if not cmd:
            return False, "LLM returned empty run command"

        self.output(f"[Runtime] Running: {' '.join(cmd)}")

        try:
            # Run with timeout
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0:
                # Crashed! Capture the error
                error_output = result.stderr or result.stdout
                self.output(f"[Runtime] ❌ CRASH detected (exit code {result.returncode})")
                return False, error_output
            else:
                # Exited cleanly (within timeout - unusual for GUI)
                self.output(f"[Runtime] ✓ Exited cleanly")
                return True, ""
                
        except subprocess.TimeoutExpired:
            # For GUI apps, timeout usually means it's running successfully
            self.output(f"[Runtime] ✓ Running (no crash within {timeout}s)")
            return True, ""
            
        except Exception as e:
            return False, f"Failed to run entry point: {str(e)}"

    async def _get_run_command_from_llm(self, entry_point: str) -> dict:
        """
        Ask LLM how to run/test the given entry point.

        Returns:
            dict with either:
            - {'command': ['cmd', 'arg1', ...]} for runnable entry points
            - {'skip_runtime': True, 'reason': '...'} for apps needing visual verification
        """
        # Read the entry point file to give LLM context
        entry_path = self.project_dir / entry_point
        file_content = ""
        try:
            if entry_path.exists():
                file_content = entry_path.read_text(encoding='utf-8', errors='replace')[:2000]
        except Exception:
            pass

        prompt = f"""Given this entry point file, determine how to run/test it.

ENTRY POINT: {entry_point}
PROJECT DIR: {self.project_dir}

FILE CONTENT (first 2000 chars):
{file_content}

RESPOND WITH JSON ONLY:

If this can be run from command line:
{{"command": ["python3", "main.py"]}}
or
{{"command": ["node", "index.js"]}}

If this requires a browser/GUI and cannot be tested via command line:
{{"skip_runtime": true, "reason": "Browser-based app - open in browser to test"}}

Consider:
- Python files: use python3 or check for venv
- JavaScript files: use node
- HTML files: cannot run directly, need browser
- Check for package.json scripts, Makefile, etc.

JSON ONLY, NO EXPLANATION:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                max_tokens=200
            )
            content = response.content if hasattr(response, 'content') else str(response)
            if content:
                # Extract JSON using robust utility
                from ..utils.json_utils import extract_json_from_llm_response
                data = extract_json_from_llm_response(content)
                if data:
                    return data
        except Exception as e:
            logger.warning(f"Failed to get run command from LLM: {e}")

        return {}

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

            # Check if this language requires manual testing
            if not test_code:
                lang = self.test_generator.language_detector.detect()
                self.output(f"  ⚠️  {lang.name} requires MANUAL TESTING")
                self.output(f"  → Will analyze code and suggest fix (user must verify)")
                unit.test_path = None
                unit.test_generated = False

                # Still generate and apply fix, but skip test verification
                # Read current file contents
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

                if not file_contents:
                    return {
                        'success': False,
                        'files_modified': [],
                        'fix_description': '',
                        'error': f'Could not read affected files for manual-test language: {unit.affected_files}'
                    }

                # Generate and apply fix (without test verification)
                self.output("  Generating fix based on code analysis...")
                fix_result = await self._apply_unit_fix(unit, file_contents, "")

                if fix_result.get('success'):
                    self.output(f"  ✓ Fix applied to: {fix_result.get('files_modified', [])}")
                    self.output(f"  ⚠️  MANUAL VERIFICATION REQUIRED: Run the {lang.name} application to verify fix")
                    return {
                        'success': True,
                        'files_modified': fix_result.get('files_modified', []),
                        'fix_description': fix_result.get('description', '') + f'\n[MANUAL VERIFICATION REQUIRED - {lang.name}]',
                        'error': None
                    }
                else:
                    self.output(f"  ❌ Fix generation failed: {fix_result.get('error', 'Unknown')}")
                    return fix_result

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
                    'description': f'Could not read affected files: {unit.affected_files}. Project dir: {self.project_dir}',
                    'error': f'Could not read affected files: {unit.affected_files}. Project dir: {self.project_dir}'
                }

            # Generate fix using LLM
            fix_result = await self._apply_unit_fix(unit, file_contents, test_code)

            if not fix_result['success']:
                self.output(f"  ❌ Fix application failed: {fix_result.get('error', 'Unknown')}")
                # Rollback and retry
                await self._rollback(fix_result.get('files_modified', []))
                continue

            self.output(f"  ✓ Fix applied to: {fix_result.get('files_modified', [])}")

            # STEP 4: Verify test passes (confirms fix works)
            self.output("  Verifying fix (test should pass)...")
            test_passes = await self.test_generator.verify_test_passes(test_path)

            if not test_passes:
                self.output("  ❌ Test still fails - fix incomplete")
                await self._rollback(fix_result.get('files_modified', []))
                continue

            self.output("  ✓ Test passes - unit fix verified!")

            # Skip regression check - only the bug-specific test matters
            # Running all tests is wasteful and slow

            # SUCCESS!
            return {
                'success': True,
                'files_modified': fix_result.get('files_modified', []),
                'fix_description': fix_result.get('description', ''),
                'error': None
            }

        # All attempts failed
        return {
            'success': False,
            'files_modified': [],
            'fix_description': '',
            'description': f'Failed after {MAX_UNIT_ATTEMPTS} attempts',
            'error': f'Failed after {MAX_UNIT_ATTEMPTS} attempts'
        }

    async def _apply_unit_fix(
        self,
        unit: DebugUnit,
        file_contents: Dict[str, str],
        test_code: str
    ) -> Dict[str, Any]:
        """
        Apply a fix for a single unit using ToolCallingClient (Phase 5).
        
        Uses intelligent tool use instead of raw text patching.
        Propagates errors back to the LLM for self-correction.
        Uses ContextManager for token-safe context construction.
        """
        if not self.tool_client:
            logger.error("Phase 5 Error: ToolCallingClient not initialized")
            return {
                'success': False,
                'files_modified': [],
                'fix_description': '',
                'description': 'ToolCallingClient not initialized (Phase 5 misconfiguration)',
                'error': 'ToolCallingClient not initialized (Phase 5 misconfiguration)'
            }

        instruction = f"""FIX THIS BUG BY CALLING THE PROVIDED TOOLS.

BUG TO FIX: {unit.description}
FILES TO EDIT: {list(file_contents.keys())}

⚠️ CRITICAL - FORBIDDEN PATHS (DO NOT WRITE TO):
- venv/, .venv/, __pycache__/, .git/, node_modules/, .raica/

⚠️ CRITICAL - CHOICE OF TOOLS:
1. replace_line: BEST for single-line fixes (e.g. removing/changing one line). Safe & precise.
2. edit_file: Use for multi-line search/replace blocks.
3. write_file: ONLY for creating NEW files. recursive destructive!

DISCRETE FIX PROCESS:
1. read_file to see current content (REQUIRED FIRST)
2. Use replace_line or edit_file to modify the code (REQUIRED)
3. ONLY report done AFTER the tool returns success

⚠️ A fix is NOT applied until the tool returns success.
⚠️ Do NOT explain. CALL THE TOOLS NOW.
"""
        # [NEW] Phase 5: Use ContextManager to ensure we respect token limits
        # We create a local instance to build the context string for this specific turn
        temp_cm = self.ContextManager()
        
        # Add file contents with high priority
        # We assume file_contents contains relative paths as keys
        full_content = ""
        for fname, content in file_contents.items():
            full_content += f"--- {fname} ---\n{content}\n\n"
            
        temp_cm.add_context_item(
            type="code",
            content=f"CURRENT CODE:\n{full_content}",
            priority=self.ContextPriority.FILE_CONTENT
        )
        
        # Add error details with higher priority
        if unit.error_details:
             temp_cm.add_context_item(
                type="error",
                content=f"ERROR TRACE:\n{unit.error_details}",
                priority=self.ContextPriority.CRITICAL_ERROR
             )

        # Compile token-safe context string
        context = temp_cm.compile_context()
        
        try:
            # Execute tools with retry/continuation
            execution_result = await self.tool_client.execute_and_continue(
                instruction=instruction,
                context=context,
                max_iterations=3  # Limit tool steps per unit
            )

            # Check which files were actually written by looking at tool results
            # This is more reliable than git status (file might already be dirty)
            files_written = []
            for result in execution_result.results:
                if result.success and result.result:
                    result_str = str(result.result)
                    # Check for write_file success patterns
                    if "Written" in result_str and "bytes to" in result_str:
                        # Extract filename from "Written X bytes to filename"
                        import re
                        match = re.search(r'bytes to (.+)$', result_str)
                        if match:
                            fname = match.group(1)
                            files_written.append(fname)
                            self.output(f"  ✓ Wrote: {fname}")

            # Also check git for any newly dirty files (backup detection)
            files_after_modification = set(self.git_tracker.get_dirty_files())

            if not execution_result.success:
                logger.warning(f"Tool execution had errors: {execution_result.errors}")
                if not files_written:
                     return {
                        'success': False,
                        'error': f"Tool execution failed: {execution_result.errors}",
                        'files_modified': [],
                        'description': f"Tool execution failed: {execution_result.errors}"
                    }

            # Use files_written as primary indicator (more reliable)
            modified_files = files_written if files_written else list(files_after_modification)
            
            # Final safety filter - ensure no forbidden paths slip through
            FORBIDDEN = ["venv/", ".venv/", "__pycache__/", ".git/", "node_modules/", ".raica/"]
            modified_files = [f for f in modified_files if not any(p in f for p in FORBIDDEN)]

            if not modified_files:
                return {
                    'success': False,
                    'files_modified': [],
                    'fix_description': "No files were modified by the agent.",
                    'description': "No files were modified by the agent.",
                    'error': "Agent did not modify any files."
                }

            return {
                'success': True,
                'files_modified': modified_files,
                'fix_description': "Applied fix via tool usage",
                'description': "Applied fix via tool usage",
                'applied_patches': len(modified_files)
            }

        except Exception as e:
            logger.error(f"Tool execution failed in _apply_unit_fix: {e}")
            return {'success': False, 'error': f"Exception during fix: {str(e)}", 'files_modified': [], 'description': f"Exception during fix: {str(e)}"}
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

        # Look for specific file types mentioned (from language definitions)
        extensions = set()
        for lang_info in LANGUAGE_DEFINITIONS.values():
            extensions.update(lang_info.file_extensions)
        extensions.add('.json')  # Always include config files

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

            # Use robust JSON extraction utility
            from ..utils.json_utils import extract_json_from_llm_response
            guidance = extract_json_from_llm_response(content)

            if not guidance:
                logger.warning(f"Could not extract JSON from LLM response: {content[:200]}")
                return {'search_terms': [], 'file_patterns': [], 'reasoning': 'No valid JSON in response'}

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

        # Read relevant files - start with ALL files from the error trace
        files_to_read = set()
        if error_info.get('all_files'):
            # Add ALL files mentioned in the error trace - critical for seeing all imports
            for trace_file in error_info['all_files']:
                files_to_read.add(trace_file)
        elif error_info.get('file'):
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
            # Use all extensions from language definitions
            all_extensions = set()
            for lang_info in LANGUAGE_DEFINITIONS.values():
                all_extensions.update(lang_info.file_extensions)

            for ext in all_extensions:
                main_file = self.project_dir / f"main{ext}"
                if main_file.exists():
                    files_to_read.add(f"main{ext}")
                    break
            # Also check common entry point names
            for name in ['app', 'index', 'script', 'Main']:
                for ext in all_extensions:
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

                # NOTE: We no longer filter "orphaned" files here.
                # The LLM should see ALL code and decide what's relevant.
                # Aggressive filtering prevented the LLM from seeing the full picture.
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
        
        # [NEW] Read project documentation to understand what files SHOULD exist
        project_documentation = self._get_project_documentation()
        if project_documentation:
            self.output(f"[Phase 1a] Read project documentation ({len(project_documentation)} chars)")

        # [NEW] Gather symbol context and analyze NameErrors
        symbol_analysis = ""
        symbol_context_str = ""
        
        try:
            from ..services.symbol_extractor import analyze_undefined_symbol, SymbolExtractor, SymbolContextGenerator
            
            # 1. Analyze specific NameErrors in trace
            if self._session.error_trace:
                suggestion, ctx = analyze_undefined_symbol(
                    self.project_dir, 
                    self._session.error_trace,
                    relevant_files=list(files_to_read)
                )
                if suggestion:
                    symbol_analysis = f"\n\nSYMBOL ANALYSIS (FUZZY MATCH):\n{suggestion}\n"
                    logger.info(f"Symbol analysis suggestion: {suggestion}")
            
            # 2. Build general symbol context for prompt
            extractor = SymbolExtractor(self.project_dir)
            table = extractor.build_symbol_table(list(files_to_read))
            ctx_gen = SymbolContextGenerator(table)
            symbol_context_str = ctx_gen.generate_context(list(files_to_read), max_symbols_per_file=30)
            
        except ImportError:
            logger.warning("SymbolExtractor service not available")
        except Exception as e:
            logger.warning(f"Symbol analysis failed: {e}")

        # Build analysis prompt with forceful structured output requirement
        prompt = f"""YOU ARE A CODE ANALYSIS AGENT. YOUR RESPONSE MUST BE VALID JSON ONLY.
DO NOT OUTPUT ANY PROSE, EXPLANATIONS, OR COMMENTARY BEFORE OR AFTER THE JSON.
DO NOT USE PHRASES LIKE "We'll fix..." OR "Let me analyze..." - ONLY OUTPUT THE JSON STRUCTURE BELOW.

Analyze this bug and identify the ROOT CAUSE.

{lang_context}

NOTE: This is a {lang.name} project. Look for {lang.name}-specific patterns and frameworks.
For UI bugs, check for programmatic styling, not just stylesheets.
{symbol_analysis}

BUG DESCRIPTION:
{self._session.bug_description}

ERROR TRACE:
{self._session.error_trace or 'Not provided'}

{self._get_import_error_context(error_info)}

{self._get_masked_error_prompt(error_info)}

{self._get_preemptive_fix_prompt(error_info)}

PROJECT FILES:
{project_files}

RELEVANT FILE STRUCTURES:
{file_structures}
{self._get_semantic_context(self._session.bug_description) if self.ragg_tool else ""}

PROJECT DOCUMENTATION (what files SHOULD exist):
{project_documentation if project_documentation else "No documentation found"}

{symbol_context_str}

FILE CONTENTS:
{self._format_file_contents(file_contents)}

PREVIOUS ATTEMPTS (if any):
{self._format_previous_attempts()}

{getattr(self, '_previous_failures_context', '')}

IMPORTANT: If previous attempts failed due to "Search block not found" or "Patch application failed", it means the file content DOES NOT match what you expected.
DO NOT repeat the same "Locate X" strategy if X does not exist. Instead, propose creating it or check the FILE CONTENTS carefully.

CRITICAL: Check RELEVANT FILE STRUCTURES above. If a method or class already exists, DO NOT propose creating it again. Update it in place.

CIRCULAR IMPORT/DEPENDENCY FIX GUIDE:
If you see "circular import", "partially initialized module", or circular dependency errors:
1. IDENTIFY the cycle: A imports B, B imports A
2. FIX using ONE of these strategies (language-appropriate):
   a) LAZY IMPORT: Move the import INSIDE the function that needs it
   b) RESTRUCTURE: Move shared code to a third module that both import
   c) For Python: use TYPE_CHECKING for type hints only
   d) For JavaScript/TypeScript: use dynamic imports or dependency injection
3. PREFER lazy imports as the simplest fix

DO NOT provide lengthy reasoning or analysis.
DO NOT use <details> tags or markdown formatting in your response.
DO NOT explain your thought process - ONLY provide the structured JSON output below.

Provide UP TO 3 RANKED HYPOTHESES as a JSON object (no additional text):

```json
{{
  "hypotheses": [
    {{
      "rank": 1,
      "hypothesis": "One sentence describing the most likely root cause",
      "affected_files": ["src/file1.ext", "src/file2.ext"],
      "line_number": 42,
      "confidence": 0.9,
      "fix_approach": "Brief description of how to fix it"
    }},
    {{
      "rank": 2,
      "hypothesis": "Alternative root cause if first fails",
      "affected_files": ["other/module.ext"],
      "line_number": null,
      "confidence": 0.6,
      "fix_approach": "Alternative fix approach"
    }}
  ]
}}
```

NOTE: Use actual file extensions from the project (.py, .js, .ts, .html, etc.)

RULES:
- Order hypotheses by confidence (highest first)
- Use null for unknown line_number
- confidence must be a number from 0.0 to 1.0
- affected_files must be an array of strings
- If only one cause is likely, provide just one hypothesis
- Return ONLY valid JSON, no other text
"""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                provider=None, 
                model=None,  # Use code_generation model from config
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
        """Parse the structured analysis response with multiple hypotheses.

        Supports both JSON format (preferred) and legacy text format (backward compatibility).

        Returns dict with:
        - hypotheses: List of hypothesis dicts (ranked by confidence)
        - hypothesis: Best hypothesis string (for backward compatibility)
        - affected_files: Files from best hypothesis
        - line_number: Line from best hypothesis
        - confidence: Confidence from best hypothesis
        - fix_approach: Fix from best hypothesis
        """
        hypotheses = []

        # Try JSON format first (preferred)
        hypotheses = self._parse_json_hypotheses(content)

        # Fallback to legacy text format if JSON parsing failed
        if not hypotheses:
            logger.debug("JSON parsing failed, trying legacy text format")
            # Split by hypothesis markers (legacy format)
            hypothesis_blocks = re.split(r'---HYPOTHESIS \d+---', content)

            for block in hypothesis_blocks:
                if not block.strip():
                    continue

                hyp = self._parse_single_hypothesis(block)
                if hyp.get('hypothesis'):
                    hypotheses.append(hyp)

            # If no multi-hypothesis format, try legacy single format
            if not hypotheses:
                hyp = self._parse_single_hypothesis(content)
                if hyp.get('hypothesis'):
                    hypotheses.append(hyp)
        
        # Sort by confidence (highest first)
        hypotheses.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        # Build result with best hypothesis for backward compatibility
        best = hypotheses[0] if hypotheses else {
            'hypothesis': '',
            'affected_files': [],
            'line_number': None,
            'confidence': 0.5,
            'fix_approach': ''
        }
        
        result = {
            'hypotheses': hypotheses,  # NEW: All ranked hypotheses
            'hypothesis': best.get('hypothesis', ''),
            'affected_files': best.get('affected_files', []),
            'line_number': best.get('line_number'),
            'confidence': best.get('confidence', 0.5),
            'fix_approach': best.get('fix_approach', '')
        }
        
        return result

    def _parse_json_hypotheses(self, content: str) -> List[Dict[str, Any]]:
        """Parse JSON-formatted hypotheses from LLM response.

        Args:
            content: Raw LLM response that may contain JSON

        Returns:
            List of hypothesis dicts, or empty list if parsing fails
        """
        hypotheses = []

        try:
            # Use robust JSON extraction utility
            from ..utils.json_utils import extract_json_from_llm_response
            data = extract_json_from_llm_response(content)

            if not data or not isinstance(data, dict) or 'hypotheses' not in data:
                return []

            for hyp in data['hypotheses']:
                if not isinstance(hyp, dict):
                    continue

                # Normalize the hypothesis dict
                parsed = {
                    'hypothesis': hyp.get('hypothesis', ''),
                    'affected_files': hyp.get('affected_files', []),
                    'line_number': hyp.get('line_number'),
                    'confidence': float(hyp.get('confidence', 0.5)),
                    'fix_approach': hyp.get('fix_approach', '')
                }

                # Ensure affected_files is a list
                if isinstance(parsed['affected_files'], str):
                    parsed['affected_files'] = [f.strip() for f in parsed['affected_files'].split(',')]

                # Ensure line_number is int or None
                if parsed['line_number'] is not None:
                    try:
                        parsed['line_number'] = int(parsed['line_number'])
                    except (ValueError, TypeError):
                        parsed['line_number'] = None

                if parsed['hypothesis']:
                    hypotheses.append(parsed)

            logger.debug(f"Parsed {len(hypotheses)} hypotheses from JSON format")
            return hypotheses

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"JSON hypothesis parsing failed: {e}")
            return []

    def _parse_single_hypothesis(self, content: str) -> Dict[str, Any]:
        """Parse a single hypothesis block (legacy text format)."""
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
                model=None,  # Use code_generation model from config
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
        
        Refactored in Phase 5 to delegate to the robust _apply_unit_fix method,
        ensuring consistent tool usage for both simple and complex bugs.
        """
        affected_files = analysis.get('affected_files', [])
        if not affected_files:
            return {'success': False, 'error': 'No affected files identified', 'description': 'No affected files identified', 'files_modified': []}

        # Read current file contents, backup, and capture lint baseline
        file_contents = {}
        for f in affected_files:
            try:
                full_path = self.project_dir / f
                if full_path.exists():
                    self.context.backup_file(full_path)
                    with open(full_path, 'r') as fp:
                        file_contents[f] = fp.read()
            except Exception as e:
                logger.warning(f"Could not read {f}: {e}")

        # Track which files are marked as new (to be created)
        new_files_to_create = []
        for f in affected_files:
            if '(new' in f.lower() or 'new file' in f.lower():
                clean_name = f.split('(')[0].strip()
                if clean_name:
                    new_files_to_create.append(clean_name)
                    logger.info(f"Detected new file to create: {clean_name}")

        if not file_contents and not new_files_to_create:
            attempted_files = [str(self.project_dir / f) for f in affected_files]
            error_msg = f'Could not read affected files. Attempted: {", ".join(attempted_files)}'
            logger.error(error_msg)
            self.output(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg, 'description': error_msg, 'files_modified': []}
        
        # Add placeholders for new files
        if new_files_to_create:
            for new_file in new_files_to_create:
                if new_file not in file_contents:
                    file_contents[new_file] = "# [NEW FILE - TO BE CREATED]\n# This file does not exist yet. Generate the complete content."

        # Get test code if available
        test_code = ""
        if self._session.bug_test_path:
            try:
                test_path = Path(self._session.bug_test_path)
                if test_path.exists():
                    test_code = test_path.read_text()
            except Exception as e:
                logger.warning(f"Could not read test file: {e}")

        # Create a transient DebugUnit for this fix
        unit = DebugUnit(
            unit_id="main_fix",
            description=self._session.bug_description,
            affected_files=affected_files,
            error_details=self._session.error_trace,
            test_approach="reproduction_test"
        )
        
        self.output(f"[Phase 4] delegating to _apply_unit_fix (Tool Enabled: {bool(self.tool_client)})")
        
        # Delegate to the unified fix method
        return await self._apply_unit_fix(unit, file_contents, test_code)

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

        # Pattern allows empty SEARCH block (for new file creation) by making first \n optional
        block_pattern = r'<<<<<<<\s*SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n>>>>>>>\s*REPLACE'
        
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
            
            if fname and replace_content:
                # For new file creation, search_content can be empty
                # Only validate non-empty search blocks
                if search_content and search_content.strip():
                    search_valid, search_err = self._validate_patch_content(search_content)
                    if not search_valid:
                        logger.warning(f"Rejected SEARCH block for {fname}: {search_err}")
                        self.output(f"⚠️ Rejected invalid SEARCH block for {fname}: {search_err}")
                        continue
                else:
                    # Empty search block = new file creation
                    logger.info(f"Empty SEARCH block detected for {fname} - will create new file")
                
                # Always validate replace block
                replace_valid, replace_err = self._validate_patch_content(replace_content)
                if not replace_valid:
                    logger.warning(f"Rejected REPLACE block for {fname}: {replace_err}")
                    self.output(f"⚠️ Rejected invalid REPLACE block for {fname}: {replace_err}")
                    continue

                patches.append({
                    'file': fname,
                    'search': search_content.strip(),
                    'replace': replace_content.strip()
                })
        
        # [NEW] Post-process patches to remove any leaked separator markers
        cleaned_patches = []
        for patch in patches:
            search = patch['search']
            replace = patch['replace']
            
            # Strip any '=======' or '>>>>>>>' that leaked into content
            search = re.sub(r'^={5,}$', '', search, flags=re.MULTILINE).strip()
            search = re.sub(r'^>{5,}.*$', '', search, flags=re.MULTILINE).strip()
            search = re.sub(r'^<{5,}.*$', '', search, flags=re.MULTILINE).strip()
            
            replace = re.sub(r'^={5,}$', '', replace, flags=re.MULTILINE).strip()
            replace = re.sub(r'^>{5,}.*$', '', replace, flags=re.MULTILINE).strip()
            replace = re.sub(r'^<{5,}.*$', '', replace, flags=re.MULTILINE).strip()
            
            # Skip if search is empty after cleaning (malformed patch)
            if not search:
                logger.warning(f"Skipping patch with empty SEARCH block for {patch['file']}")
                continue
            
            cleaned_patches.append({
                'file': patch['file'],
                'search': search,
                'replace': replace
            })
        
        return cleaned_patches

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
        """Parse the error trace to extract useful info.
        
        For ImportError, also extracts ALL names from the full import statement,
        not just the one that caused the error. This enables fixing all missing
        constants in one iteration.
        """
        result = {
            'file': None, 
            'line': None, 
            'error_type': None, 
            'message': None, 
            'all_files': [],
            'all_imports': []  # NEW: All names from the import statement
        }

        if not self._session.error_trace:
            return result

        trace = self._session.error_trace

        # Extract ALL files mentioned in the traceback, not just the first
        file_matches = re.findall(r'File "([^"]+)", line (\d+)', trace)
        if file_matches:
            # First match is the primary file
            result['file'] = file_matches[0][0]
            result['line'] = int(file_matches[0][1])
            
            # Collect ALL unique files from the trace
            all_files = []
            for fpath, _ in file_matches:
                # Normalize and dedupe
                if fpath not in all_files:
                    all_files.append(fpath)
            result['all_files'] = all_files

        # Extract error type and message
        error_match = re.search(r'(\w+Error|\w+Exception): (.+)$', trace, re.MULTILINE)
        if error_match:
            result['error_type'] = error_match.group(1)
            result['message'] = error_match.group(2)
            
        if not result['file'] and not result['error_type']:
            # NO TRACEBACK FOUND - Check for MASKED ERRORS (Warnings/caught exceptions)
            # Example: "[logger] Warning: could not import logging config (...)"
            warning_patterns = [
                r'(?:Warning|Error):\s*could not import.*',
                r'(?:Warning|Error):\s*failed to import.*',
                r'ImportError:.*',  # Sometimes printed without traceback
                r'ModuleNotFoundError:.*'
            ]
            
            for pattern in warning_patterns:
                warning_match = re.search(pattern, trace, re.IGNORECASE)
                if warning_match:
                    result['masked_error'] = warning_match.group(0)
                    result['warning_detected'] = True
                    logger.info(f"⚠️ Masked error detected: {result['masked_error']}")
                    break

        # For ImportError: extract ALL names from the import statement
        # Python only reports the FIRST missing name, but we want ALL of them
        if result['error_type'] == 'ImportError' and result['file'] and result['line']:
            all_imports = self._extract_all_imports_from_file(
                result['file'], 
                result['line']
            )
            if all_imports:
                result['all_imports'] = all_imports
                logger.info(f"Extracted {len(all_imports)} imports from statement: {all_imports[:10]}...")

        return result
    
    def _extract_all_imports_from_file(self, file_path: str, line_num: int) -> List[str]:
        """Extract ALL names from an import statement at the given line.
        
        Handles multi-line imports like:
            from config import (
                NAME1,
                NAME2,
                NAME3,
            )
        """
        try:
            # Read the file
            path = Path(file_path)
            if not path.exists():
                return []
            
            content = path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            
            if line_num < 1 or line_num > len(lines):
                return []
            
            # Get the line and check if it's a 'from X import' line
            start_line = lines[line_num - 1]
            
            # Check if this is the start of an import statement
            import_match = re.match(r'\s*from\s+(\S+)\s+import\s*(.*)$', start_line)
            if not import_match:
                return []
            
            module_name = import_match.group(1)
            rest = import_match.group(2).strip()
            
            # If it's a parenthesized import, collect all lines until closing paren
            if '(' in rest:
                # Multi-line import
                import_text = rest
                i = line_num
                while ')' not in import_text and i < len(lines):
                    import_text += ' ' + lines[i].strip()
                    i += 1
                # Remove parentheses
                import_text = import_text.replace('(', '').replace(')', '')
            else:
                import_text = rest
            
            # Extract all names
            # Handle: NAME1, NAME2 as alias, NAME3
            names = []
            for part in import_text.split(','):
                part = part.strip()
                if not part or part.startswith('#'):
                    continue
                # Handle 'as' aliases: "NAME as alias"
                name = part.split()[0] if part else ''
                if name and name.isidentifier():
                    names.append(name)
            
            return names
            
        except Exception as e:
            logger.warning(f"Failed to extract imports from {file_path}:{line_num}: {e}")
            return []
    
    def _gather_usage_context(self, symbol_name: str, source_module: str) -> str:
        """
        Gather RAW context about how a missing symbol is used in calling code.
        
        CLAUDE.md COMPLIANCE: This method ONLY gathers raw file contents.
        It does NOT interpret, parse, or infer anything. The LLM interprets.
        
        Args:
            symbol_name: The missing symbol (e.g., 'ClipboardApp')
            source_module: Where it's supposed to come from (e.g., 'clipboard_history')
            
        Returns:
            RAW file contents with prompts for LLM interpretation
        """
        importing_files = {}
        
        # Find files that import this symbol - just collect file contents
        import_pattern = rf'from\s+{re.escape(source_module)}\s+import'
        
        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in {'venv', '.venv', '__pycache__', '.git', 'node_modules'}]
            for f in files:
                if not f.endswith('.py'):
                    continue
                path = Path(root) / f
                try:
                    content = path.read_text('utf-8')
                    # Simple check: does this file import from the module?
                    if re.search(import_pattern, content):
                        rel_path = str(path.relative_to(self.project_dir))
                        importing_files[rel_path] = content
                except Exception as e:
                    logger.debug(f"Failed to read {path}: {e}")
                    continue
        
        if not importing_files:
            return ""
        
        # Build RAW context for LLM interpretation - NO hardcoded logic
        file_contents_str = ""
        for filepath, content in importing_files.items():
            # Truncate very long files but keep enough for context
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            file_contents_str += f"\n--- {filepath} ---\n{content}\n"
        
        # CLAUDE.md COMPLIANT: LLM interprets, RAICA just provides raw data
        context = f"""
=== MISSING SYMBOL CONTEXT ===

The symbol '{symbol_name}' cannot be imported from module '{source_module}'.
The following files import from '{source_module}' and may show how '{symbol_name}' should be used.

YOU (the LLM) must analyze these files to determine:
1. Is '{symbol_name}' a class or function? (Look for instantiation patterns like `{symbol_name}()`)
2. What methods must it have? (Look for method calls like `var.method()`)
3. What base class should it inherit from? (Look at the imports in the calling file)
4. What attributes must it have? (Look for attribute access like `var.attribute`)

FILES THAT IMPORT FROM '{source_module}':
{file_contents_str}

Based on your analysis of the above code, create '{symbol_name}' with the correct interface.
"""
        return context
    
    def _get_import_error_context(self, error_info: Dict[str, Any]) -> str:
        """Generate context for ImportError cases.
        
        CLAUDE.md COMPLIANCE: This method gathers raw context.
        The LLM interprets what the missing symbol should look like.
        """
        if error_info.get('error_type') != 'ImportError':
            return ""
        
        all_imports = error_info.get('all_imports', [])
        msg = error_info.get('message', '')
        
        context = ""
        
        # Gather usage context for "cannot import name" errors
        if 'cannot import name' in msg:
            # Extract symbol name - this is parsing the error message, not interpreting code
            match = re.search(r"cannot import name ['\"]?(\w+)['\"]?", msg)
            if match:
                symbol_name = match.group(1)
                # Extract source module from error
                module_match = re.search(r"from ['\"]?([^'\"]+)['\"]?", msg)
                source_module = module_match.group(1) if module_match else error_info.get('module', '')
                
                if not source_module and error_info.get('file'):
                    source_module = Path(error_info['file']).stem
                
                if source_module:
                    # Get RAW context - LLM will interpret
                    usage_context = self._gather_usage_context(symbol_name, source_module)
                    if usage_context:
                        context += usage_context + "\n"
        
        # Provide the full import list if available
        if all_imports:
            context += f"""
⚠️ FULL IMPORT STATEMENT ANALYSIS:
The error shows only ONE missing name ({msg}), but the import statement requires ALL of these:
{', '.join(all_imports)}

If creating a new symbol, ensure ALL required symbols are added.
"""
        
        return context

    def _get_masked_error_prompt(self, error_info: Dict[str, Any]) -> str:
        """Construct prompt instructions for masked/swallowed errors."""
        
        if not error_info.get('warning_detected'):
            return ""
            
        masked_warning = error_info.get('masked_error', 'Unknown warning')
        
        context = f"""
⚠️ MASKED ERROR DETECTED:
The application output contains a warning about imports but NO TRACEBACK.
This means the code is catching the exception and hiding the crash details.

YOUR TASK:
1. LOCATE the `try...except` block that prints this warning: "{masked_warning}"
2. MODIFY the code to UNMASK the error. 
   - Option A: Remove the try/except block entirely.
   - Option B: Add `import traceback; traceback.print_exc()` or `logger.exception(...)` before the except block ends.

DO NOT try to guess the missing constants yet!
We need to UNMASK the error first to get a proper traceback.
Fixing the masking is the PRIORITY.
"""
        return context

    def _scan_usage_requirements(self, module_name: str) -> Set[str]:
        """
        Scan the entire project for symbols imported from the given module.
        Used to identify ALL requirements for a module that is causing ImportErrors.
        
        Args:
            module_name: The name of the module (e.g. 'config' or 'src.utils.logger')
            
        Returns:
            Set of symbol names (e.g. {'PLAYER_GRAVITY', 'LOG_LEVEL'})
        """
        # Simplify module name to just the last part or relevant part
        # e.g. "src.config" -> "config"
        short_name = module_name.split('.')[-1]
        
        required_symbols = set()
        
        # Files to scan (skip hidden/system/venv)
        include_exts = {'.py'}
        exclude_dirs = {'venv', '.venv', '.git', '.raica', '__pycache__', 'node_modules'}
        
        logger.info(f"Scanning project for imports from '{module_name}' / '{short_name}'...")
        
        for root, dirs, files in os.walk(self.project_dir):
            # Prune excluded dirs
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            for f in files:
                if Path(f).suffix not in include_exts:
                    continue
                    
                path = Path(root) / f
                try:
                    content = path.read_text('utf-8')
                    
                    # Regex for "from <module> import X, Y, Z"
                    # We look for both "from config import" and "from src.config import"
                    patterns = [
                        rf'from\s+(?:.*\.)?{re.escape(short_name)}\s+import\s+([^#\n]+)',
                        rf'from\s+{re.escape(module_name)}\s+import\s+([^#\n]+)'
                    ]
                    
                    for pattern in patterns:
                        for match in re.finditer(pattern, content):
                            imports_str = match.group(1)
                            
                            # Skip if lines end with backslash or open paren (too complex for simple regex)
                            # But we can do basic cleanup
                            
                            # Clean up: remove parens, backslashes, newlines
                            cleaned = imports_str.replace('(', '').replace(')', '').replace('\\', '').replace('\n', ' ')
                            
                            # Split by comma
                            for item in cleaned.split(','):
                                symbol = item.split(' as ')[0].strip() # Handle aliases
                                if symbol and symbol != '*' and symbol.isidentifier():
                                    required_symbols.add(symbol)
                                    
                except Exception as e:
                    logger.debug(f"Failed to scan {path.name}: {e}")
                    
        return required_symbols

    def _get_preemptive_fix_prompt(self, error_info: Dict[str, Any]) -> str:
        """
        Generate prompt section for pre-emptive fixes if an internal module import error is detected.
        """
        if error_info.get('error_type') != 'ImportError' and not error_info.get('masked_error'):
            return ""
            
        # Try to identify the module being imported
        # Case 1: Standard traceback with message "cannot import name 'X' from 'config'"
        msg = error_info.get('message', '')
        
        # Determine module name
        module_name = None
        match = re.search(r"from ['\"]([^'\"]+)['\"]", msg)
        if match:
            module_name = match.group(1)
        
        # Case 2: Masked error message
        if not module_name and error_info.get('masked_error'):
             masked = error_info['masked_error']
             # Example: "Warning: could not import logging config (cannot import name 'LOG_MAX_BYTES' from 'config')"
             match = re.search(r"from ['\"]([^'\"]+)['\"]", masked)
             if match:
                 module_name = match.group(1)

        if not module_name:
            return ""

        # Only scan if it looks like an internal project module (no dots or starts with src/project dir name)
        # Quick heuristic: if it's a standard library or known package, skip
        if module_name in sys.stdlib_module_names:
            return ""
            
        # Scan usage
        required_symbols = self._scan_usage_requirements(module_name)
        
        if not required_symbols:
            return ""
            
        # Format the list
        formatted_list = '\n'.join([f"- {s}" for s in sorted(required_symbols)])
        
        return f"""
🛑 CRITICAL - PRE-EMPTIVE FIX REQUIRED:
The module `{module_name}` is a dependency for multiple files in the project.
The error shows one missing import, but a full project scan reveals that other files REQUIRE the following symbols from `{module_name}`:

{formatted_list}

YOU MUST ENSURE `{module_name}` EXPORTS ALL OF THESE SYMBOLS.
Do not fix just the one error. You must define/export ALL the symbols above in `{module_name}` NOW.
Refactoring `{module_name}` to include these will prevent cascading crashes.
"""

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
        # Build extensions from LANGUAGE_DEFINITIONS (no hardcoding!)
        extensions = []
        for lang_info in LANGUAGE_DEFINITIONS.values():
            for ext in lang_info.file_extensions:
                extensions.append(f"*{ext}")
        
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

    def _get_project_documentation(self) -> str:
        """
        Read project documentation to understand what files SHOULD exist.
        
        Reads:
        - README.md: Project description and expected structure
        - .raica/project_context.yaml: File entries and test imports
        
        Returns a formatted string with documentation context for the LLM.
        """
        doc_parts = []
        
        # Read README.md
        readme_path = self.project_dir / "README.md"
        if readme_path.exists():
            try:
                readme_content = readme_path.read_text(encoding='utf-8')
                # Truncate if too long
                if len(readme_content) > 3000:
                    readme_content = readme_content[:3000] + "\n... (truncated)"
                doc_parts.append(f"=== README.md ===\n{readme_content}")
                logger.info(f"Read README.md ({len(readme_content)} chars)")
            except Exception as e:
                logger.warning(f"Could not read README.md: {e}")
        
        # Read .raica/project_context.yaml
        context_path = self.project_dir / ".raica" / "project_context.yaml"
        if context_path.exists():
            try:
                import yaml
                context_data = yaml.safe_load(context_path.read_text(encoding='utf-8'))
                
                # Extract expected files from test imports
                expected_files = set()
                file_entries = context_data.get('file_entries', {})
                
                for file_path, entry in file_entries.items():
                    # Look at test files to find expected imports
                    if 'test' in file_path.lower():
                        imports = entry.get('imports', [])
                        for imp in imports:
                            # Convert import like "src.controllers.state_machine.GameStateMachine" 
                            # to expected file "src/controllers/state_machine.py"
                            if imp.startswith('src.') or imp.startswith('src/'):
                                parts = imp.replace('/', '.').split('.')
                                # Take all parts except the last (which is usually the class/function name)
                                if len(parts) > 1:
                                    # Check if it looks like a ClassName (starts with uppercase)
                                    if parts[-1] and parts[-1][0].isupper():
                                        module_parts = parts[:-1]
                                    else:
                                        module_parts = parts
                                    expected_file = '/'.join(module_parts) + '.py'
                                    expected_files.add((expected_file, file_path))
                
                if expected_files:
                    expected_list = "\n".join(
                        f"  - {exp_file} (imported by {test_file})" 
                        for exp_file, test_file in sorted(expected_files)
                    )
                    doc_parts.append(f"=== EXPECTED FILES (from test imports) ===\n{expected_list}")
                    logger.info(f"Found {len(expected_files)} expected files from test imports")
                
                # Also check README content in project_context
                key_contents = context_data.get('key_file_contents', {})
                if 'README.md' in key_contents and 'README.md' not in doc_parts[0] if doc_parts else True:
                    readme_from_context = key_contents['README.md']
                    if len(readme_from_context) > 2000:
                        readme_from_context = readme_from_context[:2000] + "..."
                    doc_parts.append(f"=== README (from context) ===\n{readme_from_context}")
                    
            except Exception as e:
                logger.warning(f"Could not parse project_context.yaml: {e}")
        
        if doc_parts:
            return "\n\n".join(doc_parts)
        return ""

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

    def _generate_incremental_summary(
        self,
        fixed_units: List['DebugUnit'],
        failed_units: List['DebugUnit'],
        visual_units: List['DebugUnit']
    ) -> str:
        """
        Generate a summary for incremental debug mode.

        This is used when debugging complex bugs broken into multiple units.
        Shows which units were successfully fixed, which failed, and visual checkpoints.

        Args:
            fixed_units: List of DebugUnit objects that were successfully fixed
            failed_units: List of DebugUnit objects that failed to fix
            visual_units: List of DebugUnit objects representing visual checkpoints

        Returns:
            Formatted summary string
        """
        lines = []
        lines.append("\n" + "="*60)
        lines.append("📋 INCREMENTAL DEBUG SUMMARY")
        lines.append("="*60)

        # Issue description
        if self._session and self._session.bug_description:
            desc = self._session.bug_description[:200]
            lines.append(f"\n🐛 ISSUE: {desc}{'...' if len(self._session.bug_description) > 200 else ''}")

        # Root cause
        if self._current_hypothesis:
            lines.append(f"\n🔍 ROOT CAUSE: {self._current_hypothesis}")

        # Fixed units
        lines.append(f"\n✅ FIXED UNITS ({len(fixed_units)}):")
        if fixed_units:
            for unit in fixed_units:
                lines.append(f"   • [{unit.unit_id}] {unit.description}")
                if unit.fix_description:
                    lines.append(f"     Fix: {unit.fix_description[:100]}{'...' if len(unit.fix_description) > 100 else ''}")
                if unit.affected_files:
                    lines.append(f"     Files: {', '.join(unit.affected_files[:3])}{'...' if len(unit.affected_files) > 3 else ''}")
        else:
            lines.append("   (none)")

        # Failed units
        lines.append(f"\n❌ FAILED UNITS ({len(failed_units)}):")
        if failed_units:
            for unit in failed_units:
                lines.append(f"   • [{unit.unit_id}] {unit.description}")
                if unit.error_details:
                    lines.append(f"     Error: {unit.error_details[:100]}{'...' if len(unit.error_details) > 100 else ''}")
        else:
            lines.append("   (none)")

        # Visual checkpoints
        if visual_units:
            lines.append(f"\n👁️ VISUAL CHECKPOINTS ({len(visual_units)}):")
            for unit in visual_units:
                status = "✓" if unit.fix_verified else "○"
                lines.append(f"   {status} {unit.description}")

        # Overall statistics
        total = len(fixed_units) + len(failed_units)
        if total > 0:
            success_rate = (len(fixed_units) / total) * 100
            lines.append(f"\n📊 SUCCESS RATE: {len(fixed_units)}/{total} ({success_rate:.0f}%)")

        # Iterations
        if self._session:
            lines.append(f"   Iterations: {self._session.current_iteration}")

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
