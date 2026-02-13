"""
Autonomous Enhancement Controller
=================================

The main controller for autonomous feature implementation. 
Implements a Test-Driven Development (TDD) loop:

1. UNDERSTAND - Analyze request and query codebase
2. PLAN & RESEARCH - Research libraries, plan implementation
3. GENERATE TEST - Create feature-specific test that fails (TDD)
4. IMPLEMENT - Write code to satisfy the test
5. VERIFY - Confirm test passes
6. CHECK REGRESSIONS - Ensure no existing functionality is broken

Uses CodeSearcher for efficient context gathering and WebResearcher
for library usage correctness.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
import json

from .project_context import (
    ProjectDebugContext,
    DebugSession,
    DebugIteration,
    DebugStatus
)
from .bug_test_generator import BugTestGenerator
from .code_searcher import CodeSearcher
from ..orchestrator.web_research import get_researcher

from ..services.linter_service import LinterService, LinterResult
from ..services.patch_applier import PatchApplier
from ..services.language_detector import LanguageDetector, LANGUAGE_DEFINITIONS
from ..services.code_path_tracer import CodePathTracer, ExecutionContext

logger = logging.getLogger(__name__)


@dataclass
class EnhancementResult:
    """Result of the enhancement process."""
    success: bool
    iterations: int = 0
    files_modified: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


from ..config_accessor import get_max_iterations

class AutonomousEnhancementController:
    """
    Controls the autonomous enhancement/feature loop.

    Principles:
    1. Test-Driven Development (Write test first)
    2. Thorough Context Gathering (Search + Research)
    3. Surgical Changes (Patches for updates, Full content for new files)
    4. 4-Gate Verification (Lint -> Test -> Targeted -> Full)
    """

    def __init__(
        self,
        llm_client,
        project_dir: Path,
        output_callback: Optional[Callable[[str], None]] = None,
        max_iterations: Optional[int] = None,
        context_manager: Any = None
    ):
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)
        self.output = output_callback or (lambda x: logger.info(x))
        self.max_iterations = max_iterations if max_iterations is not None else get_max_iterations()
        self.context_manager = context_manager

        # Initialize components
        self.context = ProjectDebugContext(project_dir)
        self.test_generator = BugTestGenerator(llm_client, project_dir)
        self.code_searcher = CodeSearcher(project_dir)
        self.web_researcher = get_researcher(llm_client)

        # Services
        self.linter_service = LinterService(project_dir)
        self.patch_applier = PatchApplier(project_dir)
        self.language_detector = LanguageDetector(project_dir)

        # Code path tracer - CRITICAL for proper debugging
        # Must trace execution paths to find ACTUAL code, not just similar-looking files
        self.code_path_tracer = CodePathTracer(project_dir)
        self._execution_context: Optional[ExecutionContext] = None

        # Track state
        self._session: Optional[DebugSession] = None
        self._plan: Optional[str] = None
        self._relevant_files: List[str] = []

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

    async def run_enhancement(
        self,
        request: str,
        resume: bool = True
    ) -> EnhancementResult:
        """Main entry point - implement feature until done or stuck."""
        import time
        start_time = time.time()

        self.output("Starting autonomous enhancement loop (TDD)...")

        # Load or create session
        # Load or create session
        self._session = None
        if resume and self.context.has_session():
            loaded_session = self.context.load_session()
            if loaded_session:
                # Check validity - must not be exhausted, failed, or complete
                if (loaded_session.current_iteration >= loaded_session.max_iterations or 
                    loaded_session.status in [DebugStatus.COMPLETE.value, DebugStatus.FAILED.value]):
                     self.output(f"Previous session {loaded_session.session_id} ended ({loaded_session.status}). Starting NEW session.")
                else:
                    self._session = loaded_session
                    self.output(f"Resuming session {self._session.session_id} (iteration {self._session.current_iteration})")
        
        if not self._session:
            self._session = self.context.create_session(request)
            
        try:
            result = await self._run_loop()
            result.duration_seconds = time.time() - start_time
            return result
            
        except Exception as e:
            logger.exception("Enhancement loop failed")
            self._session.set_status(DebugStatus.FAILED, str(e))
            self.context.save_session(self._session)
            return EnhancementResult(
                success=False,
                error=str(e),
                duration_seconds=time.time() - start_time
            )

    async def _run_loop(self) -> EnhancementResult:
        """Run the TDD enhancement loop."""

        # Check if this is a visual/web application
        ui_framework = self.test_generator._detect_ui_framework()
        is_desktop_gui = ui_framework in ('pyqt5', 'pyqt6', 'pyside2', 'pyside6', 'tkinter', 'wxpython', 'kivy')
        is_web_app = ui_framework in ('html', 'react', 'vue', 'angular', 'electron') or self._is_web_project()

        if is_desktop_gui or is_web_app:
            app_type = ui_framework or "web"
            self.output(f"\n🖥️  Visual application detected ({app_type})")
            self.output("   Skipping automated test cycle - user will verify visually")
            return await self._run_visual_loop()

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 0: BUILD EXECUTION GRAPH (CRITICAL - DO NOT SKIP)
        # ═══════════════════════════════════════════════════════════════════
        # For all projects, trace code paths from entry points to find
        # which files are ACTUALLY used at runtime.
        # ═══════════════════════════════════════════════════════════════════
        self.output("\n[PHASE 0] Building execution graph from entry points...")
        self._execution_context = await self.code_path_tracer.build_graph()

        if self._execution_context.entry_points:
            self.output(f"   Entry points: {', '.join(self._execution_context.entry_points)}")
            self.output(f"   Active files: {len(self._execution_context.active_files)}")
            if self._execution_context.orphaned_files:
                self.output(f"   Orphaned files: {len(self._execution_context.orphaned_files)}")

            if self._execution_context.warnings:
                self.output("\n   ⚠️  WARNINGS:")
                for warning in self._execution_context.warnings:
                    self.output(f"      {warning}")
        else:
            self.output("   ⚠️  No entry points found - will use all files (less accurate)")

        test_timeout = 60  # 1 minute for regular apps

        while self._session.current_iteration < self.max_iterations:
            iteration_num = self._session.current_iteration + 1
            self.output(f"\n{'='*60}")
            self.output(f"ENHANCEMENT ITERATION {iteration_num}/{self.max_iterations}")
            self.output(f"{'='*60}")
            
            iteration = DebugIteration(iteration_number=iteration_num)
            
            try:
                # ─────────────────────────────────────────────────────
                # PHASE 1: UNDERSTAND & RESEARCH
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 1] Understanding & Researching...")
                self._session.set_status(DebugStatus.ANALYZING)
                
                # Search codebase
                context_result = await self._gather_context(self._session.bug_description)
                self._relevant_files = context_result['files']
                
                # Web research
                research_info = await self._perform_web_research(
                    self._session.bug_description,
                    context_result['summary']
                )

                # ─────────────────────────────────────────────────────
                # INVESTIGATION PHASE: Check if existing functionality can fulfill request
                # LLM decides: execute_existing OR implement_new
                # ─────────────────────────────────────────────────────
                investigation_result = await self._investigate_before_implementation(
                    self._session.bug_description,
                    context_result
                )

                if investigation_result.get("decision") == "execute_existing":
                    # LLM found existing functionality - execute it instead of implementing
                    commands = investigation_result.get("commands", [])
                    self.output(f"\n Found existing functionality to execute!")
                    self.output(f"   Reasoning: {investigation_result.get('reasoning', 'N/A')[:200]}")

                    # Execute the commands
                    from ..services.debug_toolkit import DebugToolkit
                    toolkit = DebugToolkit(self.project_dir)

                    all_success = True
                    execution_outputs = []

                    for cmd in commands:
                        self.output(f"   Executing: {cmd}")
                        result = toolkit.run_command(cmd)
                        execution_outputs.append({
                            "command": cmd,
                            "success": result.success,
                            "output": str(result.result) if result.success else result.error
                        })
                        if not result.success:
                            all_success = False
                            self.output(f"   Command failed: {result.error}")
                        else:
                            stdout = result.result.get('stdout', '') if isinstance(result.result, dict) else str(result.result)
                            self.output(f"   Output: {stdout[:500]}")

                    # Update session and return
                    self._session.set_status(DebugStatus.COMPLETE if all_success else DebugStatus.FAILED)
                    self.context.save_session(self._session)

                    return EnhancementResult(
                        success=all_success,
                        iterations=iteration_num,
                        files_modified=[],
                        summary=f"Executed existing functionality: {investigation_result.get('reasoning', '')}",
                        error=None if all_success else "Some commands failed"
                    )

                # LLM decided to implement new - proceed with TDD
                self.output("   Proceeding with implementation (no existing solution found)")

                # Generate Plan
                plan = await self._create_implementation_plan(
                    self._session.bug_description,
                    context_result['full_text'],
                    research_info
                )
                self._plan = plan
                iteration.hypothesis = "Implementation Plan: " + plan[:100] + "..."
                self.output(f"Plan: {plan[:200]}...")

                # ─────────────────────────────────────────────────────
                # PHASE 2: GENERATE FEATURE TEST (TDD)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 2] Generating feature test (TDD)...")
                self._session.set_status(DebugStatus.GENERATING_TEST)
                
                test_code = await self._generate_feature_test(
                    request=self._session.bug_description,
                    plan=plan,
                    context=context_result['full_text']
                )
                
                test_name = f"feature_{self._session.session_id}_{iteration_num}"
                test_path = self.context.save_bug_test(test_name, test_code)
                iteration.test_generated = str(test_path)
                self._session.bug_test_path = str(test_path)
                self.output(f"Generated test: {test_path.name}")
                
                # ─────────────────────────────────────────────────────
                # PHASE 3: VERIFY TEST FAILS (Red Phase)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 3] Verifying test fails initially (Red Phase)...")

                test_result_initial = await self.test_generator.run_test(test_path, timeout=test_timeout)
                iteration.test_result_before = not test_result_initial.passed
                
                if test_result_initial.passed:
                    self.output("⚠️ Test PASSED immediately - feature might already exist or test is trivial.")
                else:
                    self.output("Test FAILED as expected (feature not implemented yet).")

                # ─────────────────────────────────────────────────────
                # PHASE 4: IMPLEMENTATION (Green Phase)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 4] Implementing feature & Linting...")
                self._session.set_status(DebugStatus.FIXING)
                
                # Updated implementation with Patching + New File creation + Linting
                impl_result = await self._implement_feature_and_lint(
                    plan=plan,
                    test_code=test_code,
                    test_error=test_result_initial.error,
                    context=context_result['full_text']
                )
                
                if not impl_result['success']:
                    iteration.failure_reason = f"Implementation/Linting failed: {impl_result.get('error')}"
                    self._record_iteration(iteration)
                    continue
                    
                iteration.files_modified = impl_result['files_modified']
                self._session.files_modified = impl_result['files_modified']
                self.output(f"Modified: {', '.join(impl_result['files_modified'])}")

                # ─────────────────────────────────────────────────────
                # PHASE 5: VERIFY IMPLEMENTATION
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 5] Verifying implementation...")
                self._session.set_status(DebugStatus.TESTING)

                test_passes = await self.test_generator.verify_test_passes(test_path, timeout=test_timeout)
                iteration.test_result_after = test_passes
                
                if not test_passes:
                    self.output("Test still FAILS. Entering Recursive Repair Loop to fix it...")
                    
                    repair_result = await self._attempt_recursive_repair(
                        plan=plan,
                        test_code=test_code,
                        initial_error=await self.test_generator.get_test_error(test_path), # We need error
                        files_modified=impl_result['files_modified'],
                        test_path=test_path
                    )
                    
                    if repair_result['success']:
                         self.output("Test PASSES after repair!")
                         # Update modified files list in case repair touched new files
                         impl_result['files_modified'] = repair_result['files_modified']
                         # Update session
                         iteration.files_modified = repair_result['files_modified']
                         self._session.files_modified = repair_result['files_modified']
                    else:
                        self.output("Repair Loop Failed. Rolling back to retry implementation...")
                        await self._rollback(repair_result['files_modified'])
                        iteration.rollback_performed = True
                        iteration.failure_reason = "Implementation failed test and repair loop"
                        self._record_iteration(iteration)
                        continue
                        
                self.output("Test PASSES - Feature implemented!")
                self._session.bug_test_passes = True

                # ─────────────────────────────────────────────────────
                # PHASE 6: TARGETED REGRESSION TEST (Gate 3)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 6] Running Targeted Regression Tests (Gate 3)...")
                relevant_tests = self.test_generator.identify_relevant_tests(impl_result['files_modified'])
                
                if relevant_tests:
                    self.output(f"Identified {len(relevant_tests)} relevant tests.")
                    targeted_result = await self.test_generator.run_targeted_tests(relevant_tests)
                    if not targeted_result.passed:
                        self.output(f"❌ Targeted Regressions found!\nFailed: {targeted_result.error[:200]}")
                        await self._rollback(impl_result['files_modified'])
                        iteration.rollback_performed = True
                        iteration.failure_reason = "Targeted Regression Failed"
                        self._record_iteration(iteration)
                        continue
                    self.output("✅ Targeted Regression Passed")
                else:
                    self.output("ℹ️ No specific relevant tests found.")

                # ─────────────────────────────────────────────────────
                # PHASE 7: FULL REGRESSION CHECK
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 7] Checking full regressions (Gate 4)...")
                self._session.set_status(DebugStatus.VERIFYING)
                
                regression_result = await self.test_generator.run_all_project_tests()
                iteration.regression_check_passed = regression_result.passed
                
                if not regression_result.passed:
                    self.output("REGRESSIONS detected! Rolling back...")
                    await self._rollback(impl_result['files_modified'])
                    iteration.rollback_performed = True
                    iteration.failure_reason = "Implementation caused regressions"
                    self._record_iteration(iteration)
                    continue
                    
                self.output("No regressions detected.")

                # ─────────────────────────────────────────────────────
                # PHASE 8: LLD VERIFICATION CHECKLIST (Final Gate)
                # ─────────────────────────────────────────────────────
                self.output("\n[PHASE 8] Verifying implementation against LLD...")
                
                # Collect files created in this iteration
                files_created = {}
                for fname in impl_result.get('files_created', []):
                    try:
                        fpath = self.project_dir / fname
                        if fpath.exists():
                            files_created[fname] = fpath.read_text(encoding='utf-8', errors='replace')
                    except Exception:
                        pass
                
                lld_verification = await self._verify_implementation_against_lld(
                    lld_content=plan,
                    files_modified=impl_result['files_modified'],
                    files_created=files_created
                )
                
                if not lld_verification['passed']:
                    self.output(f"⚠ LLD verification found gaps: {lld_verification['completion_pct']:.1f}% complete")
                    if lld_verification['critical_failures']:
                        self.output(f"  Critical failures: {len(lld_verification['critical_failures'])}")
                        # Don't rollback - just log the warning and continue
                        # The user should be informed of incomplete implementation
                    iteration.lld_verification_pct = lld_verification['completion_pct']
                else:
                    self.output(f"✅ LLD verification passed: {lld_verification['completion_pct']:.1f}% complete")
                    iteration.lld_verification_pct = lld_verification['completion_pct']

                # ─────────────────────────────────────────────────────
                # SUCCESS
                # ─────────────────────────────────────────────────────
                iteration.success = True
                self._record_iteration(iteration)

                # Generate comprehensive change summary
                change_summary = await self._generate_change_summary(
                    files_modified=self._session.files_modified,
                    plan=plan,
                    request=self._session.bug_description
                )
                self.output(change_summary)

                # Update persistent context for future requests
                await self._update_persistent_context(
                    files_modified=self._session.files_modified,
                    request=self._session.bug_description,
                    success=True
                )

                # NEW: Generate/update project documentation
                await self._generate_project_documentation(self._session.files_modified)

                self._session.set_status(DebugStatus.COMPLETE)
                self.context.save_session(self._session)

                return EnhancementResult(
                    success=True,
                    iterations=self._session.current_iteration,
                    files_modified=self._session.files_modified,
                    summary=change_summary
                )

            except Exception as e:
                logger.exception(f"Iteration {iteration_num} failed")
                iteration.failure_reason = str(e)
                self._record_iteration(iteration)
                continue
                
        # Max iterations
        return EnhancementResult(
            success=False,
            error=f"Max iterations ({self.max_iterations}) reached"
        )

    async def _get_llm_search_guidance(self, request: str, project_files: List[str]) -> Dict[str, Any]:
        """
        Ask the LLM to generate intelligent search terms based on project context.

        THIS IS CRITICAL: The LLM's keyword generation determines whether we find
        the correct code to modify. No hardcoded keyword mappings - the LLM must
        understand the project's language, framework, and patterns to generate
        accurate search terms.

        The LLM receives:
        - The feature request
        - Project file structure (to understand language/framework)
        - Entry points and active files (from execution graph)

        Returns dict with:
        - search_terms: List of technical terms to search for in code
        - file_patterns: List of glob patterns to find files
        - reasoning: LLM's reasoning for the suggested searches
        """
        # Build comprehensive project context for the LLM
        files_sample = "\n".join(project_files[:50])

        # Include execution context if available (entry points, active files)
        exec_context_info = ""
        if self._execution_context:
            exec_context_info = f"""
PROJECT EXECUTION CONTEXT:
- Entry Points: {', '.join(self._execution_context.entry_points)}
- Active Files (actually loaded at runtime): {', '.join(sorted(self._execution_context.active_files))}
- Language/Framework: Infer from file extensions and patterns below
"""

        # Detect language for context
        lang = self.language_detector.detect()
        lang_context = f"""
DETECTED PROJECT LANGUAGE: {lang.name}
- Common patterns: {lang.common_patterns if hasattr(lang, 'common_patterns') else 'N/A'}
- Test framework: {lang.test_framework if hasattr(lang, 'test_framework') else 'N/A'}
"""

        prompt = f"""You are the CRITICAL keyword generation engine for a code modification system.

YOUR ROLE IS ESSENTIAL: The search terms you generate will be used to find the EXACT code
locations that need to be modified. If you miss important terms, the system will fail to
find relevant code. If you generate irrelevant terms, it will waste time on wrong files.

FEATURE REQUEST:
{request}
{exec_context_info}
{lang_context}
PROJECT FILES (these are the files that exist):
{files_sample}

YOUR TASK: Generate precise, project-specific search terms to find ALL code relevant to this request.

THINK CAREFULLY about:
1. What SPECIFIC variable names, function names, or class names might be involved?
2. What framework-specific patterns does this project use? (e.g., Three.js for 3D, React for UI)
3. What property names appear in data files that the code must reference?
4. What methods handle the specific behavior being changed?

CRITICAL GUIDELINES:
- Generate terms that are SPECIFIC to this project, not generic programming terms
- Include BOTH the concept (e.g., "zoom") AND likely implementation names (e.g., "maxDistance", "controls")
- For UI changes: include render methods, event handlers, style properties
- For data changes: include model fields, schema properties, validation methods
- For behavior changes: include state variables, update methods, event listeners

ACCURACY IS PARAMOUNT: Your search terms directly determine which code gets modified.
Wrong terms = wrong code modified = failed enhancement.

OUTPUT FORMAT (JSON only, no markdown, no explanation outside JSON):
{{
    "search_terms": ["specific_term1", "specific_term2", "methodName", "propertyName", ...],
    "file_patterns": ["*.js", "*.json", ...],
    "reasoning": "Brief explanation connecting terms to the specific request"
}}"""

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

            # Parse JSON from response
            content = response.content.strip()
            logger.debug(f"LLM search guidance raw response: {content[:500]}")

            # Extract JSON if wrapped in markdown
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()


            # Try to find JSON object if there's extra text
            if not content.startswith('{'):
                # Look for first { and last }
                first_brace = content.find('{')
                last_brace = content.rfind('}')
                if first_brace != -1 and last_brace != -1:
                    content = content[first_brace:last_brace + 1]

            guidance = json.loads(content)

            logger.info(f"LLM search guidance: {len(guidance.get('search_terms', []))} terms, "
                       f"{len(guidance.get('file_patterns', []))} patterns")
            self.output(f"[LLM Search Guidance] {guidance.get('reasoning', 'No reasoning')[:200]}")

            return guidance

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM search guidance JSON: {e}")
            return {'search_terms': [], 'file_patterns': [], 'reasoning': 'JSON parse failed'}
        except Exception as e:
            logger.warning(f"LLM search guidance error: {e}")
            return {'search_terms': [], 'file_patterns': [], 'reasoning': str(e)}

    async def _gather_context(self, request: str) -> Dict[str, Any]:
        """Gather relevant code context using CodeSearcher with LLM-guided expansion.

        CRITICAL: If execution context is available (from Phase 0), we ONLY
        consider files that are actually in the execution path. This prevents
        modifying orphaned files that look relevant but aren't loaded at runtime.
        """
        # 1. Get initial file list for LLM guidance
        # CRITICAL: Use execution graph if available to filter to ACTIVE files only
        if self._execution_context and self._execution_context.active_files:
            # Use only files that are actually in the execution path
            all_files_str = list(self._execution_context.active_files)
            self.output(f"[Phase 1a] Using {len(all_files_str)} files from execution graph (entry: {', '.join(self._execution_context.entry_points[:2])})")

            # Add execution context summary to help LLM understand the codebase structure
            exec_summary = self.code_path_tracer.get_context_summary()
            logger.info(f"Execution context:\n{exec_summary}")
        else:
            # Fallback: search all files
            all_files = await self.code_searcher.find_files("*")
            all_files_str = [str(f) for f in all_files]

        # 2. ASK LLM FOR SEARCH GUIDANCE (the intelligent approach)
        self.output("[Phase 1a] Getting LLM search guidance...")
        guidance = await self._get_llm_search_guidance(request, all_files_str)

        llm_search_terms = guidance.get('search_terms', [])
        llm_file_patterns = guidance.get('file_patterns', [])

        # 3. Also extract basic keywords from request as fallback
        keywords = [k for k in request.split() if len(k) > 4]

        found_files = set()
        full_text_contexts = []

        # Helper to normalize paths to be relative to project_dir
        # CRITICAL: Also filters out ORPHANED files from context gathering
        def normalize_path(p) -> Optional[str]:
            """Convert any path to relative path string, filtering orphaned files."""
            try:
                path_obj = Path(p) if isinstance(p, str) else p
                if path_obj.is_absolute():
                    try:
                        rel = str(path_obj.relative_to(self.project_dir))
                    except ValueError:
                        rel = str(path_obj)
                else:
                    rel = str(path_obj)

                # Normalize path separators
                rel = rel.replace('\\', '/')

                # Exclude backup and test files from context
                if '.raica/' in rel or '/test/' in rel or rel.startswith('test/'):
                    return None

                # CRITICAL: Exclude ORPHANED files (not in execution path)
                # This prevents the LLM from even seeing these files in context
                if self._execution_context and self._execution_context.orphaned_files:
                    if rel in self._execution_context.orphaned_files:
                        logger.debug(f"Filtering orphaned file from context: {rel}")
                        return None

                return rel
            except Exception:
                return str(p)

        # Search for files with similar names (basic keyword matching)
        for f in all_files_str:
            f_str = str(f).lower()
            if any(k.lower() in f_str for k in keywords):
                rel_path = normalize_path(f)
                if rel_path:
                    found_files.add(rel_path)

        # LLM-GUIDED: Search with LLM-suggested file patterns
        for pattern in llm_file_patterns:
            try:
                pattern_matches = await self.code_searcher.find_files(pattern)
                for f in pattern_matches:
                    rel_path = normalize_path(f)
                    if rel_path:
                        found_files.add(rel_path)
                        logger.debug(f"Found file via pattern '{pattern}': {rel_path}")
            except Exception as e:
                logger.debug(f"Pattern {pattern} failed: {e}")

        # Search text content with original keywords
        for k in keywords[:3]:
            s_result = await self.code_searcher.search_text(k, max_results=10)
            if s_result.matches:
                for m in s_result.matches:
                    rel_path = normalize_path(m.file_path)
                    if rel_path:
                        found_files.add(rel_path)
                        full_text_contexts.append(f"File: {rel_path}:{m.line_number}\n{m.content}")

        # LLM-GUIDED: Search for LLM-suggested technical terms (this is the key!)
        for term in llm_search_terms[:10]:
            try:
                s_result = await self.code_searcher.search_text(term, max_results=5)
                if s_result.matches:
                    for m in s_result.matches:
                        rel_path = normalize_path(m.file_path)
                        if rel_path:
                            found_files.add(rel_path)
                            full_text_contexts.append(f"[LLM:{term}] File: {rel_path}:{m.line_number}\n{m.content}")
            except Exception as e:
                logger.debug(f"Search term {term} failed: {e}")

        # ALWAYS include data files (JSON, YAML) - these define data structures
        # that the LLM must respect to avoid field name hallucination
        # Note: find_files walks recursively, so use simple patterns (not **)
        data_patterns = ['*.json', '*.yaml', '*.yml']
        data_files = set()
        for pattern in data_patterns:
            try:
                data_matches = await self.code_searcher.find_files(pattern)
                for f in data_matches:
                    rel_path = normalize_path(f)
                    if rel_path:
                        # Exclude internal/config files that aren't project data
                        excluded = (
                            'node_modules' in rel_path or
                            'package-lock' in rel_path or
                            '.raica/' in rel_path or
                            'raica_state' in rel_path or
                            rel_path.startswith('.') or
                            '/.' in rel_path or  # hidden files in subdirs
                            'lib/' in rel_path or
                            'tsconfig' in rel_path or
                            'eslint' in rel_path or
                            'prettier' in rel_path
                        )
                        if not excluded:
                            data_files.add(rel_path)
            except Exception as e:
                logger.debug(f"Data file pattern {pattern} failed: {e}")

        # Prioritize: files in data/ directory first, then others
        data_dir_files = [f for f in data_files if f.startswith('data/') or '/data/' in f]
        other_data_files = [f for f in data_files if f not in data_dir_files]
        # Sort to get most relevant data files
        sorted_data_files = data_dir_files + other_data_files
        data_files_list = sorted_data_files[:5]  # Max 5 data files
        code_files_list = [f for f in found_files if f not in data_files][:10]
        files_list = data_files_list + code_files_list
        files_list = files_list[:15]  # Total max 15 files

        if data_files_list:
            self.output(f"[Phase 1a] Including {len(data_files_list)} data files for structure reference")
            for df in data_files_list[:3]:
                self.output(f"   • {df}")
        else:
            logger.debug(f"No data files found. Searched patterns: {data_patterns}")

        self.output(f"[Phase 1a] Found {len(files_list)} relevant files via LLM-guided search")
        # Show JS files being included (important for display code)
        js_files = [f for f in files_list if f.endswith('.js')]
        if js_files:
            self.output(f"   JavaScript files: {', '.join(js_files[:5])}")
        logger.info(f"Files to read: {files_list}")

        # Read contents
        contents = {}
        for f in files_list:
            try:
                # Handle both relative and absolute paths
                if Path(f).is_absolute():
                    full_path = Path(f)
                else:
                    full_path = self.project_dir / f

                if full_path.exists():
                    # Increase budget for modern LLMs
                    raw_content = full_path.read_text(encoding='utf-8', errors='replace')
                    if len(raw_content) > 15000:
                        raw_content = raw_content[:15000] + "\n... (further content truncated)"
                    
                    # Add line numbers
                    lines = raw_content.splitlines()
                    numbered_lines = [f"{i+1:4}: {line}" for i, line in enumerate(lines)]
                    contents[f] = "\n".join(numbered_lines)
                    logger.debug(f"Successfully read: {f} ({len(raw_content)} chars)")
                else:
                    logger.warning(f"File not found: {full_path}")
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")
                
        full_text = ""

        # CRITICAL: Prepend execution graph summary so LLM knows which files are ACTIVE
        if self._execution_context and self._execution_context.active_files:
            exec_summary = self.code_path_tracer.get_context_summary()
            full_text += f"\n{exec_summary}\n"
            full_text += "\n" + "="*60 + "\n"
            full_text += "⚠️ CRITICAL: You may ONLY modify files listed as ACTIVE above!\n"
            full_text += "⚠️ Files marked [ORPHAN] exist but are NOT loaded - DO NOT PATCH THEM!\n"
            full_text += "="*60 + "\n"

            # FEATURE-TO-CODE MAPPING: Use LLM-generated search terms (no hardcoding!)
            # The LLM search guidance already intelligently expanded keywords based on:
            # - The project's language and framework
            # - The actual code patterns in the project
            # - The specific feature request context
            # This is the CORRECT approach - let the LLM do intelligent keyword expansion
            llm_keywords = llm_search_terms if llm_search_terms else []
            # Also include basic keywords from request as fallback
            basic_keywords = [k for k in request.split() if len(k) > 3 and k.isalpha()]
            all_keywords = list(set(llm_keywords + basic_keywords))

            if all_keywords:
                code_locations = self.code_path_tracer.find_code_for_feature(all_keywords)
                if code_locations:
                    full_text += "\n" + "="*60 + "\n"
                    full_text += "🎯 RELEVANT CODE LOCATIONS (modify these!):\n"
                    full_text += "="*60 + "\n"
                    for file_path, matches in code_locations.items():
                        full_text += f"\n📍 {file_path}:\n"
                        for line_num, line_content in matches[:10]:  # Limit to 10 matches per file
                            full_text += f"   Line {line_num}: {line_content[:100]}\n"
                    full_text += "="*60 + "\n"

        for f, c in contents.items():
            full_text += f"\n--- {f} (with line numbers) ---\n{c}\n"

        # Build summary
        summary_parts = [f"Found {len(files_list)} relevant files."]
        if self._execution_context:
            summary_parts.append(f"Entry: {', '.join(self._execution_context.entry_points[:2])}")
            if self._execution_context.orphaned_files:
                summary_parts.append(f"({len(self._execution_context.orphaned_files)} orphaned files excluded)")

        return {
            'files': files_list,
            'summary': ' '.join(summary_parts),
            'full_text': full_text,
            'execution_context': self._execution_context  # Include for reference
        }

    async def _perform_web_research(self, request: str, context_summary: str) -> str:
        """Research libraries if needed (language-aware)."""
        if "using" in request.lower() or "monitor" in request.lower() or "library" in request.lower():
            try:
                # Use detected language for more relevant search
                lang = self.language_detector.detect()
                result = await self.web_researcher.research(
                    f"{lang.name} library {request} best practices",
                    max_results=3
                )
                if result.success:
                    return result.get_context_for_llm()
            except Exception:
                pass
        return ""

    async def _create_implementation_plan(self, request: str, context: str, research: str) -> str:
        """Generate implementation plan."""
        
        # [NEW] Gather symbol context for the plan
        symbol_context_str = ""
        try:
            from ..services.symbol_extractor import SymbolExtractor, SymbolContextGenerator
            extractor = SymbolExtractor(self.project_dir)
            table = extractor.build_symbol_table() # Default: all project files
            ctx_gen = SymbolContextGenerator(table)
            symbol_context_str = ctx_gen.generate_context(max_symbols_per_file=30)
        except Exception as e:
            logger.warning(f"Failed to generate symbol context for plan: {e}")

        prompt = f"""Plan the implementation for this feature.

REQUEST: {request}

CODE CONTEXT:
{context}

{symbol_context_str}

RESEARCH:
{research}

CRITICAL: Analyze the code context carefully to identify:
1. ALL files that need modification (the context includes files found by searching for technical terms)
2. Any code that might OVERRIDE or CONFLICT with your changes (check for programmatic overrides)
3. All places where the same property/behavior is set
4. EXISTING SYMBOLS that must be reused (check AVAILABLE SYMBOLS above)

Provide a technical plan with:
1. Files to create/modify (list ALL relevant files from the context)
2. Key functions/classes to modify
3. Potential conflicts or overrides that must be addressed
4. How to verify the changes work
"""
        
        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            max_tokens=6000
        )
        if not response.success:
            raise Exception(f"Plan generation failed: {response.error}")
        
        # NEW: Verify LLD completeness before proceeding
        verified_plan = await self._verify_lld_completeness(response.content)
        return verified_plan

    async def _investigate_before_implementation(
        self,
        request: str,
        context: Dict[str, Any],
        max_iterations: int = 5
    ) -> Dict[str, Any]:
        """
        LLM-driven investigation phase - determine if existing functionality can fulfill request.

        FOLLOWS RAICA's CARDINAL RULE:
        - LLM drives the iteration via structured JSON tool requests
        - RAICA executes tool requests blindly (read files, run commands, search)
        - LLM decides outcome: use existing functionality OR implement new

        This prevents over-engineering simple tasks when a script already exists.

        Returns:
            {
                "decision": "execute_existing" | "implement_new",
                "commands": [...],  # Only if decision is "execute_existing"
                "reasoning": str,   # LLM's reasoning for the decision
                "investigation_results": [...]  # Results from investigation
            }
        """
        from .code_searcher import CodeSearcher

        # Build initial context for LLM
        files_summary = "\n".join([f"- {f}" for f in context.get('files', [])[:30]])
        context_text = context.get('full_text', '')[:8000]  # Truncate for prompt size

        investigation_results = []

        # Initialize toolkit for tool execution
        from ..services.debug_toolkit import DebugToolkit
        toolkit = DebugToolkit(self.project_dir)

        self.output("[PHASE 1b] LLM Investigation - checking for existing functionality...")

        for i in range(max_iterations):
            # Build prompt for LLM
            history_text = ""
            if investigation_results:
                history_text = "\n\nINVESTIGATION RESULTS SO FAR:\n"
                for result in investigation_results[-5:]:  # Last 5 results
                    history_text += f"\n--- {result['tool']}({result['args']}) ---\n{result['output'][:2000]}\n"

            prompt = f"""You are investigating whether existing functionality can fulfill a user request.

USER REQUEST:
{request}

PROJECT FILES FOUND:
{files_summary}

CODE CONTEXT:
{context_text[:4000]}
{history_text}

YOUR TASK:
1. Investigate if there's EXISTING functionality (scripts, functions, commands) that can fulfill this request
2. If you need more information, request tool calls
3. When you have enough information, make a DECISION

AVAILABLE TOOLS (request via JSON):
- read_file: {{"tool": "read_file", "args": {{"path": "path/to/file"}}}}
- run_command: {{"tool": "run_command", "args": {{"command": "python script.py --help"}}}}
- search_text: {{"tool": "search_text", "args": {{"pattern": "function_name"}}}}
- list_files: {{"tool": "list_files", "args": {{"path": "directory/"}}}}

DECISION FORMAT (when ready):
{{"decision": "execute_existing", "commands": ["python script.py arg1", "..."], "reasoning": "..."}}
OR
{{"decision": "implement_new", "reasoning": "No existing functionality found, need to implement"}}

CRITICAL:
- If you find a script/function that does what the user wants, return "execute_existing" with the commands
- Only return "implement_new" if you've investigated and confirmed nothing exists
- DO NOT assume - investigate first by reading files or running --help commands

Respond with ONLY valid JSON - either a tool request or a decision."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=2000
            )

            if not response.success:
                logger.warning(f"Investigation LLM call failed: {response.error}")
                return {"decision": "implement_new", "reasoning": "LLM call failed", "investigation_results": investigation_results}

            # Parse JSON response
            try:
                # Clean response - remove markdown code blocks if present
                content = response.content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()

                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse investigation response: {e}")
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{[^{}]*\}', response.content)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        return {"decision": "implement_new", "reasoning": "Could not parse LLM response", "investigation_results": investigation_results}
                else:
                    return {"decision": "implement_new", "reasoning": "Could not parse LLM response", "investigation_results": investigation_results}

            # Check if this is a decision
            if "decision" in parsed:
                decision = parsed.get("decision")
                if decision in ("execute_existing", "implement_new"):
                    self.output(f"   LLM Decision: {decision}")
                    if decision == "execute_existing":
                        self.output(f"   Commands: {parsed.get('commands', [])}")
                    self.output(f"   Reasoning: {parsed.get('reasoning', 'N/A')[:100]}...")
                    return {
                        "decision": decision,
                        "commands": parsed.get("commands", []),
                        "reasoning": parsed.get("reasoning", ""),
                        "investigation_results": investigation_results
                    }

            # This is a tool request - execute it
            if "tool" in parsed:
                tool_name = parsed["tool"]
                tool_args = parsed.get("args", {})

                # 🔧 FIX: Prevent duplicate tool requests (LLM stuck in loop)
                request_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                already_requested = any(
                    f"{r['tool']}:{r['args']}" == request_key
                    for r in investigation_results
                )
                if already_requested:
                    self.output(f"   [{i+1}/{max_iterations}] Skipping duplicate request: {tool_name}({tool_args})")
                    # Force LLM to make a decision by adding hint
                    investigation_results.append({
                        "tool": "SYSTEM_HINT",
                        "args": "{}",
                        "output": f"You already requested {tool_name}({tool_args}). The results are in INVESTIGATION RESULTS above. Please make a DECISION (execute_existing or implement_new) based on what you've learned."
                    })
                    continue

                self.output(f"   [{i+1}/{max_iterations}] LLM requests: {tool_name}({tool_args})")

                # Execute the tool
                try:
                    if tool_name == "read_file":
                        result = toolkit.read_file(tool_args.get("path", ""))
                    elif tool_name == "run_command":
                        result = toolkit.run_command(tool_args.get("command", ""))
                    elif tool_name == "search_text":
                        result = toolkit.search_text(tool_args.get("pattern", ""))
                    elif tool_name == "list_files":
                        result = toolkit.list_files(tool_args.get("path", ""))
                    else:
                        result = type('ToolResult', (), {'success': False, 'error': f"Unknown tool: {tool_name}", 'result': None})()

                    output_text = str(result.result) if result.success else f"ERROR: {result.error}"
                    investigation_results.append({
                        "tool": tool_name,
                        "args": str(tool_args),
                        "output": output_text[:3000]
                    })

                except Exception as e:
                    investigation_results.append({
                        "tool": tool_name,
                        "args": str(tool_args),
                        "output": f"Tool execution error: {e}"
                    })
            else:
                # Neither decision nor tool request - invalid response
                logger.warning(f"Invalid investigation response (no decision or tool): {parsed}")

        # Max iterations reached without decision - default to implement_new
        self.output("   Investigation max iterations reached - proceeding with implementation")
        return {
            "decision": "implement_new",
            "reasoning": "Investigation did not reach a conclusion",
            "investigation_results": investigation_results
        }

    async def _verify_lld_completeness(self, lld_content: str, max_iterations: int = 3) -> str:
        """
        Review→Update loop until LLD has no gaps.
        
        Ensures the implementation plan is complete with:
        - All classes/functions specified
        - All file paths defined
        - All dependencies listed
        - No TBD/TODO placeholders
        """
        self.output("[Quality Gate] Verifying LLD completeness...")
        
        for i in range(max_iterations):
            gaps = await self._find_lld_gaps(lld_content)
            
            if not gaps:
                self.output(f"  ✓ LLD verified complete after {i+1} iteration(s)")
                return lld_content
            
            self.output(f"  → Found {len(gaps)} gaps, filling... (iteration {i+1}/{max_iterations})")
            lld_content = await self._fill_lld_gaps(lld_content, gaps)
        
        self.output(f"  ⚠ LLD verification completed with {max_iterations} iterations")
        return lld_content
    
    async def _find_lld_gaps(self, lld_content: str) -> List[str]:
        """Ask LLM to identify gaps in the implementation plan."""
        prompt = f"""Review this implementation plan for COMPLETENESS.

IMPLEMENTATION PLAN:
{lld_content}

CHECKLIST - Identify ANY missing items:
1. Are ALL files to create/modify explicitly listed with full paths?
2. Are ALL functions/methods to implement specified with signatures?
3. Are ALL dependencies (imports, packages) listed?
4. Are there ANY "TBD", "TODO", "to be determined" placeholders?
5. Are ALL error handling approaches specified?
6. Is the verification/testing approach complete?

If the plan is COMPLETE (no gaps), respond with exactly: COMPLETE

If there are GAPS, list them in this format:
GAP: <description of what's missing>
GAP: <another missing item>
...

Be specific about what's missing, not vague."""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.1,
            max_tokens=2000
        )
        
        if not response.success:
            return []  # Assume complete if LLM fails
        
        content = response.content.strip()
        
        if "COMPLETE" in content and "GAP:" not in content:
            return []
        
        # Extract gaps
        gaps = []
        for line in content.splitlines():
            if line.strip().startswith("GAP:"):
                gaps.append(line.replace("GAP:", "").strip())
        
        return gaps
    
    async def _fill_lld_gaps(self, lld_content: str, gaps: List[str]) -> str:
        """Fill identified gaps in the implementation plan."""
        gaps_str = "\n".join([f"- {g}" for g in gaps])
        
        prompt = f"""Complete this implementation plan by filling the identified gaps.

CURRENT PLAN:
{lld_content}

GAPS TO FILL:
{gaps_str}

Provide the UPDATED implementation plan with all gaps filled.
- Add specific file paths where missing
- Add function signatures where missing
- Add dependency lists where missing
- Replace all TBD/TODO with concrete specifications
- Be specific and actionable, not vague

Output the complete updated plan."""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.2,
            max_tokens=6000
        )
        
        if not response.success:
            return lld_content  # Return original if fill fails
        
        return response.content
    
    def _detect_stubs(self, file_content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        Detect stub functions, placeholders, and incomplete implementations.
        
        Returns list of detected stubs with:
        - line: Line number
        - pattern: What was matched
        - context: Surrounding code
        - suggestion: How to fix
        """
        import re
        
        stubs = []
        lines = file_content.splitlines()
        
        # Patterns indicating stubs/placeholders
        patterns = [
            (r'^\s*pass\s*(?:#.*)?$', 'Empty function body (pass)'),
            (r'raise NotImplementedError', 'NotImplementedError placeholder'),
            (r'^\s*\.\.\.\s*(?:#.*)?$', 'Ellipsis placeholder'),
            (r'#\s*TODO\s*:', 'TODO comment'),
            (r'#\s*FIXME\s*:', 'FIXME comment'),
            (r'#\s*STUB\s*:', 'STUB comment'),
            (r'#\s*PLACEHOLDER', 'PLACEHOLDER comment'),
            (r'return\s+None\s*#\s*(?:stub|placeholder|todo)', 'Stub return None'),
            (r'^\s*pass\s*#\s*(?:stub|todo|implement)', 'Marked stub'),
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern, description in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Get context (2 lines before and after)
                    start = max(0, i - 3)
                    end = min(len(lines), i + 2)
                    context = "\n".join(lines[start:end])
                    
                    stubs.append({
                        'line': i,
                        'pattern': description,
                        'content': line.strip(),
                        'context': context,
                        'file': file_path,
                        'suggestion': f"Replace {description.lower()} with full implementation"
                    })
                    break  # Only match first pattern per line
        
        return stubs
    
    async def _complete_stubs(self, file_path: str, file_content: str, stubs: List[Dict], max_iterations: int = 3) -> str:
        """
        Iteratively complete stubs until none remain or max iterations reached.
        
        Uses a review→fix loop to ensure complete stub elimination.
        """
        if not stubs:
            return file_content
        
        current_content = file_content
        
        for iteration in range(max_iterations):
            # Get current stubs (use passed stubs on first iteration)
            current_stubs = stubs if iteration == 0 else self._detect_stubs(current_content, file_path)
            
            if not current_stubs:
                self.output(f"    ✓ All stubs completed after {iteration} iteration(s)")
                return current_content
            
            self.output(f"    → Completing {len(current_stubs)} stubs (iteration {iteration + 1}/{max_iterations})")
            
            stubs_description = "\n".join([
                f"Line {s['line']}: {s['pattern']}\nContext:\n{s['context']}\n"
                for s in current_stubs[:5]  # Max 5 stubs at a time
            ])
            
            prompt = f"""Complete these stub implementations with FULL working code.

FILE: {file_path}

DETECTED STUBS:
{stubs_description}

CURRENT FILE CONTENT:
{current_content}

CRITICAL RULES:
1. Replace EVERY stub/placeholder with COMPLETE, WORKING code
2. NO pass statements, NO NotImplementedError, NO TODO comments
3. NO ellipsis (...) placeholders
4. Implement REAL functionality, not more placeholders
5. Follow the existing code style and patterns
6. Each function must have COMPLETE logic - no shortcuts

Provide the COMPLETE updated file content with all stubs replaced."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=8000
            )
            
            if not response.success:
                logger.warning(f"Stub completion failed for {file_path}: {response.error}")
                break
            
            # Extract code from response
            content = response.content
            lang = self.language_detector.detect()
            completed_code = self._extract_code(content, lang.code_block_name)
            
            if completed_code and len(completed_code) > len(current_content) * 0.5:
                current_content = completed_code
            else:
                self.output(f"    ⚠ Failed to extract valid code in iteration {iteration + 1}")
                break
        
        # Final stub check
        remaining = self._detect_stubs(current_content, file_path)
        if remaining:
            self.output(f"    ⚠ {len(remaining)} stubs remain after {max_iterations} iterations")
        
        return current_content

    async def _review_code_quality(self, file_path: str, file_content: str, max_iterations: int = 2) -> str:
        """
        Iterative code quality review loop.
        
        Reviews generated code for issues beyond stubs:
        - Missing error handling
        - Hardcoded values that should be configurable
        - Missing input validation
        - Code inconsistencies
        - Missing docstrings/comments
        """
        import re
        
        current_content = file_content
        
        for iteration in range(max_iterations):
            issues = self._detect_quality_issues(current_content, file_path)
            
            if not issues:
                if iteration > 0:
                    self.output(f"    ✓ Code quality verified after {iteration} fix iteration(s)")
                return current_content
            
            self.output(f"    → Fixing {len(issues)} quality issues (iteration {iteration + 1}/{max_iterations})")
            
            issues_str = "\n".join([f"- {issue}" for issue in issues[:10]])  # Max 10 issues at a time
            
            prompt = f"""Review and fix these code quality issues.

FILE: {file_path}

ISSUES IDENTIFIED:
{issues_str}

CURRENT CODE:
{current_content}

FIX REQUIREMENTS:
1. Add proper error handling (try/except with meaningful messages)
2. Replace hardcoded values with constants or config
3. Add input validation where needed
4. Add docstrings to functions/classes
5. Ensure consistent coding style
6. Keep all existing functionality intact

Provide the COMPLETE fixed file content."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=8000
            )
            
            if not response.success:
                logger.warning(f"Quality review failed for {file_path}: {response.error}")
                break
            
            lang = self.language_detector.detect()
            fixed_code = self._extract_code(response.content, lang.code_block_name)
            
            if fixed_code and len(fixed_code) > len(current_content) * 0.5:
                current_content = fixed_code
            else:
                break
        
        return current_content
    
    def _detect_quality_issues(self, file_content: str, file_path: str) -> List[str]:
        """Detect code quality issues using pattern matching and heuristics."""
        import re
        
        issues = []
        lines = file_content.splitlines()
        
        # Language-specific checks (use language definitions)
        ext = Path(file_path).suffix.lower() if file_path else ""
        python_exts = LANGUAGE_DEFINITIONS.get('python', {}).file_extensions if 'python' in LANGUAGE_DEFINITIONS else ['.py']
        js_exts = LANGUAGE_DEFINITIONS.get('javascript', {}).file_extensions if 'javascript' in LANGUAGE_DEFINITIONS else ['.js']
        ts_exts = LANGUAGE_DEFINITIONS.get('typescript', {}).file_extensions if 'typescript' in LANGUAGE_DEFINITIONS else ['.ts']
        is_python = ext in python_exts or ext == ''
        is_js = ext in js_exts or ext in ts_exts
        
        # Check for functions without error handling
        if is_python:
            # Functions with file/network operations but no try/except
            func_pattern = r'def\s+(\w+)\s*\([^)]*\):'
            risky_ops = ['open(', 'requests.', 'urllib', '.read()', '.write()', 'json.load', 'connect(']
            
            in_function = False
            current_func = ""
            has_try = False
            has_risky = False
            
            for i, line in enumerate(lines):
                func_match = re.match(func_pattern, line)
                if func_match:
                    # Check previous function
                    if in_function and has_risky and not has_try:
                        issues.append(f"Function '{current_func}' has I/O operations but no error handling")
                    current_func = func_match.group(1)
                    in_function = True
                    has_try = False
                    has_risky = False
                    continue
                
                if in_function:
                    if 'try:' in line:
                        has_try = True
                    if any(op in line for op in risky_ops):
                        has_risky = True
        
        # Check for hardcoded strings that look like paths/URLs
        hardcoded_patterns = [
            (r'["\'][A-Za-z]:\\[^"\']+["\']', 'Hardcoded Windows path'),
            (r'["\']/home/[^"\']+["\']', 'Hardcoded Unix path'),
            (r'["\']https?://(?!example\.)[^"\']+["\']', 'Hardcoded URL'),
            (r'["\'](?:localhost|127\.0\.0\.1):\d+["\']', 'Hardcoded localhost address'),
        ]
        
        for i, line in enumerate(lines, 1):
            if '#' in line and any(x in line.split('#')[1].lower() for x in ['config', 'constant', 'env']):
                continue  # Skip lines already marked as config
            
            for pattern, desc in hardcoded_patterns:
                if re.search(pattern, line):
                    issues.append(f"Line {i}: {desc} should be configurable")
                    break
        
        # Check for missing docstrings (Python)
        if is_python:
            class_pattern = r'^class\s+(\w+)'
            for i, line in enumerate(lines):
                if re.match(class_pattern, line):
                    # Check if next non-empty line is a docstring
                    for j in range(i + 1, min(i + 4, len(lines))):
                        next_line = lines[j].strip()
                        if next_line and not next_line.startswith('#'):
                            if not (next_line.startswith('"""') or next_line.startswith("'''")):
                                match = re.match(class_pattern, line)
                                if match:
                                    issues.append(f"Class '{match.group(1)}' is missing a docstring")
                            break
        
        # Limit to most important issues
        return issues[:10]

    async def _verify_implementation_against_lld(
        self, 
        lld_content: str, 
        files_modified: List[str],
        files_created: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Final verification checklist: Compare actual code against LLD commitments.
        
        This is a REAL analysis, not optimistic wishful thinking.
        Each checklist item is verified with actual code inspection.
        
        Returns:
            {
                'passed': bool,
                'checklist': List[ChecklistItem],
                'completion_pct': float,
                'critical_failures': List[str],
                'warnings': List[str]
            }
        """
        self.output("\n[FINAL GATE] Verifying implementation against LLD...")
        
        # Step 1: Extract commitments from LLD
        commitments = await self._extract_lld_commitments(lld_content)
        
        if not commitments:
            self.output("  ⚠ Could not parse LLD commitments - skipping verification")
            return {'passed': True, 'checklist': [], 'completion_pct': 100.0, 
                    'critical_failures': [], 'warnings': ['LLD parsing failed']}
        
        self.output(f"  Found {len(commitments)} commitments in LLD")
        
        # Step 2: Verify each commitment against actual code
        checklist = []
        critical_failures = []
        warnings = []
        
        for commitment in commitments:
            result = await self._verify_single_commitment(
                commitment, files_modified, files_created
            )
            checklist.append(result)
            
            if not result['passed'] and result['priority'] == 'critical':
                critical_failures.append(result['description'])
            elif not result['passed']:
                warnings.append(result['description'])
        
        # Step 3: Calculate completion percentage (weighted by priority)
        total_weight = sum(3 if c['priority'] == 'critical' else 1 for c in checklist)
        passed_weight = sum(
            (3 if c['priority'] == 'critical' else 1) 
            for c in checklist if c['passed']
        )
        completion_pct = (passed_weight / total_weight * 100) if total_weight > 0 else 100.0
        
        # Step 4: Generate report
        self._output_verification_report(checklist, completion_pct, critical_failures, warnings)
        
        # Fail if any critical items failed
        passed = len(critical_failures) == 0 and completion_pct >= 80.0
        
        return {
            'passed': passed,
            'checklist': checklist,
            'completion_pct': completion_pct,
            'critical_failures': critical_failures,
            'warnings': warnings
        }
    
    async def _extract_lld_commitments(self, lld_content: str) -> List[Dict[str, Any]]:
        """
        Parse LLD to extract verifiable commitments.
        
        Looks for:
        - Files to create/modify (with paths)
        - Functions/methods to implement (with signatures)
        - Features to add (with acceptance criteria)
        - Dependencies to add
        """
        import re
        
        commitments = []
        
        # Pattern 1: File creation/modification
        file_patterns = [
            r'\[NEW\]\s*`?([^`\n]+)`?',
            r'\[MODIFY\]\s*`?([^`\n]+)`?',
            r'\[CREATE\]\s*`?([^`\n]+)`?',
            r'Create\s+(?:file\s+)?`?([^\s`]+\.\w+)`?',
            r'Modify\s+`?([^\s`]+\.\w+)`?',
            r'Update\s+`?([^\s`]+\.\w+)`?',
        ]
        
        for pattern in file_patterns:
            for match in re.finditer(pattern, lld_content, re.IGNORECASE):
                file_path = match.group(1).strip()
                if file_path and '.' in file_path:
                    commitments.append({
                        'type': 'file',
                        'description': f"File: {file_path}",
                        'target': file_path,
                        'priority': 'critical'
                    })
        
        # Pattern 2: Function/method implementation
        func_patterns = [
            r'(?:implement|add|create)\s+(?:function|method)\s+`?(\w+)\s*\([^)]*\)`?',
            r'def\s+(\w+)\s*\([^)]*\)\s*(?:->|\:)',
            r'function\s+(\w+)\s*\([^)]*\)',
            r'`(\w+)\(\)`\s*(?:method|function)',
        ]
        
        for pattern in func_patterns:
            for match in re.finditer(pattern, lld_content, re.IGNORECASE):
                func_name = match.group(1)
                if func_name and not func_name.startswith('_'):
                    commitments.append({
                        'type': 'function',
                        'description': f"Function: {func_name}()",
                        'target': func_name,
                        'priority': 'critical'
                    })
        
        # Pattern 3: Features/capabilities (look for bullet points with action verbs)
        feature_patterns = [
            r'(?:^|\n)\s*[-*]\s*(Add|Implement|Create|Enable|Support)\s+([^\n]+)',
            r'(?:^|\n)\s*\d+\.\s*(Add|Implement|Create|Enable|Support)\s+([^\n]+)',
        ]
        
        for pattern in feature_patterns:
            for match in re.finditer(pattern, lld_content, re.IGNORECASE):
                action = match.group(1)
                feature = match.group(2).strip()[:80]  # Limit length
                if feature:
                    commitments.append({
                        'type': 'feature',
                        'description': f"{action} {feature}",
                        'target': feature.lower(),
                        'priority': 'normal'
                    })
        
        # Pattern 4: Dependencies
        dep_patterns = [
            r'(?:add|install|require)\s+(?:dependency|package)\s*[:\s]+`?([^`\n,]+)`?',
            r'pip install\s+([^\s\n]+)',
            r'npm install\s+([^\s\n]+)',
        ]
        
        for pattern in dep_patterns:
            for match in re.finditer(pattern, lld_content, re.IGNORECASE):
                dep = match.group(1).strip()
                if dep:
                    commitments.append({
                        'type': 'dependency',
                        'description': f"Dependency: {dep}",
                        'target': dep,
                        'priority': 'normal'
                    })
        
        # Deduplicate by target
        seen = set()
        unique_commitments = []
        for c in commitments:
            key = f"{c['type']}:{c['target']}"
            if key not in seen:
                seen.add(key)
                unique_commitments.append(c)
        
        return unique_commitments[:30]  # Limit to prevent excessive checks
    
    async def _verify_single_commitment(
        self, 
        commitment: Dict[str, Any],
        files_modified: List[str],
        files_created: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Verify a single LLD commitment against actual implementation.
        
        Performs REAL verification:
        - File commitments: Check if file exists and has content
        - Function commitments: Search for function definition in code
        - Feature commitments: Ask LLM to verify implementation
        - Dependencies: Check requirements.txt / package.json
        """
        result = {
            **commitment,
            'passed': False,
            'comment': '',
            'evidence': ''
        }
        
        c_type = commitment['type']
        target = commitment['target']
        
        if c_type == 'file':
            # Normalize path for comparison
            normalized_target = target.replace('\\', '/').lstrip('./')
            
            # Check if file was created or modified
            for f in list(files_modified) + list(files_created.keys()):
                normalized_f = f.replace('\\', '/').lstrip('./')
                if normalized_target in normalized_f or normalized_f.endswith(normalized_target):
                    # Verify file exists and has content
                    full_path = self.project_dir / f
                    if full_path.exists():
                        content = full_path.read_text(encoding='utf-8', errors='replace')
                        if len(content) > 20:  # Non-empty
                            result['passed'] = True
                            result['comment'] = f"✓ File created/modified ({len(content)} bytes)"
                            result['evidence'] = f"Path: {full_path}"
                        else:
                            result['comment'] = f"✗ File exists but is nearly empty"
                    break
            
            if not result['passed'] and not result['comment']:
                result['comment'] = "✗ File not found in modified/created files"
        
        elif c_type == 'function':
            # Search for function definition in all modified/created files
            import re
            found_in = None
            is_stub = False
            
            # Patterns for function definitions
            patterns = [
                rf'def\s+{re.escape(target)}\s*\(',  # Python
                rf'function\s+{re.escape(target)}\s*\(',  # JS
                rf'async\s+def\s+{re.escape(target)}\s*\(',  # Python async
                rf'async\s+function\s+{re.escape(target)}\s*\(',  # JS async
                rf'{re.escape(target)}\s*:\s*function\s*\(',  # JS object method
                rf'{re.escape(target)}\s*=\s*(?:async\s+)?\([^)]*\)\s*=>',  # Arrow function
            ]
            
            for f in list(files_modified) + list(files_created.keys()):
                full_path = self.project_dir / f
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding='utf-8', errors='replace')
                        for pattern in patterns:
                            if re.search(pattern, content, re.IGNORECASE):
                                found_in = f
                                # Check if it's a stub
                                func_match = re.search(
                                    pattern + r'[^{]*(?:\{|:)([^}]*(?:\}|(?=\n\S)))',
                                    content, re.DOTALL | re.IGNORECASE
                                )
                                if func_match:
                                    func_body = func_match.group(1) if func_match.lastindex else ""
                                    stub_patterns = ['pass', 'NotImplementedError', '...', 'TODO', 'STUB']
                                    is_stub = any(p in func_body for p in stub_patterns)
                                break
                    except Exception:
                        continue
                if found_in:
                    break
            
            if found_in:
                if is_stub:
                    result['passed'] = False
                    result['comment'] = f"⚠ Function found but appears to be a stub"
                    result['evidence'] = f"In: {found_in}"
                else:
                    result['passed'] = True
                    result['comment'] = f"✓ Function implemented"
                    result['evidence'] = f"In: {found_in}"
            else:
                result['comment'] = f"✗ Function definition not found"
        
        elif c_type == 'feature':
            # For features, we need LLM assistance to verify
            # Collect relevant code snippets
            relevant_code = ""
            for f in list(files_modified)[:5]:  # Limit to avoid huge prompts
                full_path = self.project_dir / f
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding='utf-8', errors='replace')
                        relevant_code += f"\n--- {f} ---\n{content[:2000]}\n"
                    except Exception:
                        continue
            
            if relevant_code:
                # Quick heuristic first - look for keywords
                target_words = set(target.lower().split())
                code_lower = relevant_code.lower()
                matches = sum(1 for w in target_words if len(w) > 3 and w in code_lower)
                
                if matches >= len(target_words) * 0.5:  # At least half the keywords found
                    result['passed'] = True
                    result['comment'] = f"✓ Feature keywords found in code"
                else:
                    result['passed'] = False
                    result['comment'] = f"⚠ Feature keywords not clearly present"
            else:
                result['comment'] = "✗ No code available to verify"
        
        elif c_type == 'dependency':
            # Check requirements.txt or package.json
            req_path = self.project_dir / "requirements.txt"
            pkg_path = self.project_dir / "package.json"
            
            found = False
            if req_path.exists():
                content = req_path.read_text(encoding='utf-8', errors='replace').lower()
                if target.lower() in content:
                    found = True
                    result['evidence'] = "In requirements.txt"
            
            if pkg_path.exists() and not found:
                content = pkg_path.read_text(encoding='utf-8', errors='replace').lower()
                if target.lower() in content:
                    found = True
                    result['evidence'] = "In package.json"
            
            if found:
                result['passed'] = True
                result['comment'] = f"✓ Dependency listed"
            else:
                result['passed'] = False
                result['comment'] = f"⚠ Dependency not found in manifest"
        
        return result
    
    def _output_verification_report(
        self, 
        checklist: List[Dict], 
        completion_pct: float,
        critical_failures: List[str],
        warnings: List[str]
    ) -> None:
        """Output a formatted verification report to the user."""
        self.output(f"\n{'='*60}")
        self.output(f"  LLD VERIFICATION CHECKLIST - {completion_pct:.1f}% Complete")
        self.output(f"{'='*60}")
        
        # Group by type
        by_type = {}
        for item in checklist:
            t = item['type']
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(item)
        
        for item_type, items in by_type.items():
            self.output(f"\n  [{item_type.upper()}]")
            for item in items:
                status = "✓" if item['passed'] else "✗"
                priority = " [CRITICAL]" if item['priority'] == 'critical' and not item['passed'] else ""
                self.output(f"    {status} {item['description']}{priority}")
                if item['comment']:
                    self.output(f"       {item['comment']}")
        
        self.output(f"\n{'─'*60}")
        
        if critical_failures:
            self.output(f"  ❌ CRITICAL FAILURES ({len(critical_failures)}):")
            for cf in critical_failures:
                self.output(f"     - {cf}")
        
        if warnings:
            self.output(f"  ⚠ WARNINGS ({len(warnings)}):")
            for w in warnings[:5]:  # Limit displayed warnings
                self.output(f"     - {w}")
        
        if not critical_failures and not warnings:
            self.output(f"  ✅ All commitments verified!")
        
        self.output(f"{'='*60}\n")

    async def _generate_project_documentation(self, files_modified: List[str]) -> None:
        """
        Generate or update project documentation.
        
        Creates:
        - README.md with setup/run instructions
        - requirements.txt (for Python) or package.json updates
        - INSTALL.md with detailed setup steps
        """
        self.output("[Quality Gate] Generating project documentation...")
        
        lang = self.language_detector.detect()
        readme_path = self.project_dir / "README.md"
        
        # Collect information about the project
        project_files = []
        for f in self.project_dir.rglob("*"):
            if f.is_file() and not any(x in str(f) for x in ['.git', '__pycache__', 'node_modules', '.raica']):
                try:
                    rel = f.relative_to(self.project_dir)
                    project_files.append(str(rel))
                except:
                    pass
        
        # Detect dependencies
        dependencies = self._extract_dependencies(project_files)
        
        # Check for existing README
        existing_readme = ""
        if readme_path.exists():
            existing_readme = readme_path.read_text(encoding='utf-8', errors='replace')
        
        prompt = f"""Generate a comprehensive README.md for this {lang.name} project.

PROJECT FILES:
{chr(10).join(project_files[:50])}

FILES MODIFIED IN THIS SESSION:
{chr(10).join(files_modified)}

DETECTED DEPENDENCIES:
{chr(10).join(dependencies) if dependencies else 'None detected'}

EXISTING README (if any):
{existing_readme[:2000] if existing_readme else 'No existing README'}

Generate a README.md that includes:

1. **Project Overview** - Brief description based on the files
2. **Prerequisites** - Required software (Python version, Node version, etc.)
3. **Installation**
   - Virtual environment creation: `python -m venv venv` or equivalent
   - Activation: `source venv/bin/activate` (Linux/Mac) or `venv\\Scripts\\activate` (Windows)
   - Dependency installation: `pip install -r requirements.txt` or `npm install`
4. **Running the Application** - Exact command to execute
5. **Project Structure** - Key directories and files
6. **Recent Changes** - What was modified in this session

CRITICAL RULES:
- All commands must be COPY-PASTE ready
- Include BOTH Windows and Unix commands where different
- Be SPECIFIC about file paths and commands
- NO placeholders or "configure as needed" - give concrete instructions

Output ONLY the README.md content in markdown format."""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.2,
            max_tokens=4000
        )
        
        if response.success and response.content:
            # Write README
            readme_content = response.content
            # Strip markdown code fences if present
            if readme_content.startswith("```"):
                lines = readme_content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                readme_content = "\n".join(lines)

            # Strip LLM thinking tags (<thinking>, <details>, <think>, etc.)
            from ..llm_client import strip_thinking_content
            readme_content = strip_thinking_content(readme_content)

            # NEW: Iterative documentation review loop
            readme_content = await self._verify_documentation_completeness(readme_content)
            
            readme_path.write_text(readme_content, encoding='utf-8')
            self.output(f"  ✓ Generated README.md ({len(readme_content)} chars)")
            
            # Generate requirements.txt for Python projects
            if lang.name.lower() == 'python':
                await self._generate_requirements_txt(dependencies)
        else:
            self.output(f"  ⚠ Documentation generation failed: {response.error if response else 'No response'}")
    
    async def _verify_documentation_completeness(self, doc_content: str, max_iterations: int = 2) -> str:
        """
        Iterative documentation review loop.
        
        Ensures README/INSTALL docs include:
        - Complete installation steps
        - All dependencies listed
        - Working run commands
        - No placeholders
        """
        current_content = doc_content
        
        required_sections = [
            'installation', 'prerequisites', 'running', 'dependencies',
            'pip install', 'npm install', 'venv', 'activate'
        ]
        
        for iteration in range(max_iterations):
            # Check for missing sections
            content_lower = current_content.lower()
            missing = [s for s in ['installation', 'running', 'prerequisites'] 
                      if s not in content_lower]
            
            # Check for placeholders
            placeholder_patterns = ['[your-', '<your-', 'xxx', 'todo:', 'tbd', 
                                   'configure as needed', 'see documentation']
            has_placeholders = any(p in content_lower for p in placeholder_patterns)
            
            if not missing and not has_placeholders:
                if iteration > 0:
                    self.output(f"    ✓ Documentation verified complete after {iteration} iteration(s)")
                return current_content
            
            issues = []
            if missing:
                issues.append(f"Missing sections: {', '.join(missing)}")
            if has_placeholders:
                issues.append("Contains placeholders that need concrete values")
            
            self.output(f"    → Fixing documentation issues (iteration {iteration + 1}/{max_iterations})")
            
            prompt = f"""Fix these documentation issues:

ISSUES:
{chr(10).join(issues)}

CURRENT DOCUMENTATION:
{current_content}

REQUIREMENTS:
1. Add any missing sections (Installation, Running, Prerequisites)
2. Replace ALL placeholders with specific, concrete instructions
3. Ensure all commands are copy-paste ready
4. Include both Windows and Unix commands where applicable
5. Be specific about Python/Node versions, paths, and dependencies

Output the COMPLETE fixed documentation."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=4000
            )
            
            if not response.success:
                break
            
            # Strip code fences
            new_content = response.content
            if new_content.startswith("```"):
                lines = new_content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                new_content = "\n".join(lines)
            
            if len(new_content) > len(current_content) * 0.5:
                current_content = new_content
            else:
                break
        
        return current_content
    
    def _extract_dependencies(self, project_files: List[str]) -> List[str]:
        """Extract dependencies from project files."""
        dependencies = set()
        
        for f in project_files:
            full_path = self.project_dir / f
            if not full_path.exists():
                continue
            
            try:
                content = full_path.read_text(encoding='utf-8', errors='replace')
                
                # Python imports
                if f.endswith('.py'):
                    import re
                    # Match 'import X' and 'from X import'
                    for match in re.finditer(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE):
                        pkg = match.group(1)
                        # Filter out stdlib
                        stdlib = {'os', 'sys', 'json', 're', 'typing', 'pathlib', 'dataclasses', 
                                 'asyncio', 'logging', 'collections', 'datetime', 'time', 'math',
                                 'functools', 'itertools', 'copy', 'abc', 'enum', 'io', 'traceback'}
                        if pkg not in stdlib and not pkg.startswith('_'):
                            dependencies.add(pkg)
                
                # JavaScript/Node
                elif f.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    import re
                    for match in re.finditer(r"(?:require|from)\s*['\"]([^'\"./][^'\"]*)['\"]", content):
                        dependencies.add(match.group(1).split('/')[0])
                        
            except Exception:
                pass
        
        return sorted(dependencies)
    
    async def _generate_requirements_txt(self, dependencies: List[str]) -> None:
        """Generate requirements.txt for Python projects."""
        req_path = self.project_dir / "requirements.txt"
        
        # Read existing if present
        existing = set()
        if req_path.exists():
            for line in req_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    # Extract package name (before version specifier)
                    pkg = line.split('==')[0].split('>=')[0].split('<=')[0].split('[')[0]
                    existing.add(pkg.lower())
        
        # Add new dependencies
        new_deps = [d for d in dependencies if d.lower() not in existing]
        
        if new_deps:
            with open(req_path, 'a') as f:
                if existing:
                    f.write('\n# Added by RAICA\n')
                for dep in new_deps:
                    f.write(f'{dep}\n')
            self.output(f"  ✓ Updated requirements.txt (+{len(new_deps)} packages)")

    async def _generate_feature_test(self, request: str, plan: str, context: str) -> str:
        """Generate a new test file for the feature (language-aware)."""
        # Get detected language for appropriate test framework
        lang = self.language_detector.detect()

        prompt = f"""Generate a {lang.test_framework} test case for a NEW feature.

{self.language_detector.get_language_context_for_llm()}

FEATURE REQUEST: {request}
PLAN: {plan}
CONTEXT: {context}

CRITICAL PRINCIPLE - TEST ONLY WHAT CAN BE AUTOMATICALLY TESTED:

Visual verification (colors, fonts, spacing, look-and-feel, UI appearance) is BEST LEFT
TO THE END USER. You cannot and should not try to automatically verify visual aesthetics.

What YOU should test:
- Logic and business rules
- Configuration values are set/applied
- Methods and properties exist and are callable
- Data flows correctly
- Error handling works
- API contracts are met

What you should NOT test (leave for human verification):
- Exact colors, pixel positions, font rendering
- Visual appearance and aesthetics
- "Does it look good?" questions
- Subjective design quality

PRACTICAL TEST GUIDELINES:
1. Test that code CHANGES were made (methods added, config applied) not visual outcomes
2. If the feature is purely visual, create a MINIMAL test that verifies the code path exists
3. The test should FAIL initially (feature not implemented) but be PASSABLE after implementation
4. Prefer testing behavior over testing values - "method exists" over "returns exact value"

The test should:
1. Import the relevant modules
2. Verify expected behavior in a PRACTICAL, achievable way
3. Be runnable and follow {lang.name}/{lang.test_framework} conventions

Output ONLY the {lang.name} code for the test file.
"""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            max_tokens=4000
        )
        if not response.success:
             raise Exception(f"Test generation failed: {response.error}")
        content = response.content
        return self._extract_code(content, lang.code_block_name)


    async def _implement_feature_and_lint(self, plan: str, test_code: str, test_error: Optional[str], context: str) -> Dict[str, Any]:
        """Generate implementation code (surgical patches or new files) and Lint."""
        # Get framework-specific guidance (prefer static detection for reliability)
        file_contents_for_guidance = {}
        for f in self._relevant_files[:3]:
            try:
                full_path = self.project_dir / f
                if full_path.exists():
                    file_contents_for_guidance[f] = full_path.read_text(encoding='utf-8', errors='replace')[:2000]
            except Exception:
                pass

        framework_guidance = await self.test_generator.get_framework_guidance_for_fix(
            self._session.bug_description,
            file_contents_for_guidance
        )

        # Log if framework guidance is being used
        if framework_guidance:
            self.output(f"[Framework] UI framework constraints detected - will apply")

        # [NEW] Gather symbol context for implementation
        symbol_context_str = ""
        try:
            from ..services.symbol_extractor import SymbolExtractor, SymbolContextGenerator
            extractor = SymbolExtractor(self.project_dir)
            # Only index files relevant to the plan/context to save tokens
            table = extractor.build_symbol_table(list(file_contents_for_guidance.keys()) if file_contents_for_guidance else None) 
            ctx_gen = SymbolContextGenerator(table)
            symbol_context_str = ctx_gen.generate_context(max_symbols_per_file=30)
        except Exception as e:
            logger.warning(f"Failed to generate symbol context for implementation: {e}")

        # Build prompt based on whether this is TDD (with test) or visual (no test)
        if test_code:
            # TDD mode - have a test to satisfy
            prompt = f"""Implement the feature to pass the test.

PLAN: {plan}

TEST CODE:
{test_code}

TEST ERROR:
{test_error or "New test"}
{framework_guidance}
EXISTING CODE CONTEXT:
{context}

{symbol_context_str}

INSTRUCTIONS:
1. IMPLEMENT ALL CHANGES mentioned in the plan to make the test pass.
2. For NEW files, provide the FULL content.
3. For EXISTING files, provide surgical SEARCH/REPLACE patches.
4. CRITICAL: Use EXACT field names from JSON/data files in the context. DO NOT invent field names.
5. Use the line numbers in the context for reference only. Do NOT include them in your patches.
6. Make the SMALLEST possible change to achieve the goal. Be surgical.
7. Provide multiple small patches instead of one large block if changes are far apart.
8. Follow framework-specific guidelines above (if any).

⚠️ IMPORTANT: You MUST modify ALL files needed for the feature to work end-to-end.

⛔ CRITICAL RULE: You may ONLY patch files from the ACTIVE FILES list!
⛔ DO NOT patch files marked as [ORPHAN] - they are NOT loaded at runtime!

⚠️ CRITICAL PATCH RULE:
Your SEARCH block MUST be copied EXACTLY from the EXISTING CODE CONTEXT above.
- Copy the exact lines including all whitespace and formatting
- Do NOT invent or guess what the code looks like
- If you can't find the exact code in the context, do NOT patch that file

🛑 ABSOLUTE PROHIBITIONS (VIOLATIONS WILL BE REJECTED):
⛔ NEVER replace more than 20 lines in a single SEARCH/REPLACE block
⛔ NEVER include entire file content in SEARCH block
⛔ NEVER replace entire functions/classes - target specific sections
⛔ NEVER create SEARCH blocks larger than 20 lines
⛔ Wholesale file replacements are AUTOMATICALLY REJECTED by validation

✅ SURGICAL CHANGE PRINCIPLE:
- Identify the MINIMAL code that needs modification (typically 3-15 lines)
- Include ONLY the lines that change, plus 1-2 context lines
- Break large changes into MULTIPLE small patches
- Each patch should have a clear, focused purpose

FORMAT FOR NEW FILES:
--- NEW FILE: path/to/filename.ext ---
<content>
--- END FILE ---

FORMAT FOR MODIFYING FILES (Surgical Patch - MAX 20 LINES):
File: path/to/existing_file.ext
<<<<<<< SEARCH
<exact string match (3-20 lines, no line numbers)>
=======
<replacement (similar length)>
>>>>>>> REPLACE

EXAMPLE (GOOD - Small, Targeted):
File: src/utils/helper.js
<<<<<<< SEARCH
function getData() {{
    return this.data;
}}
=======
function getData() {{
    return {{ ...this.data, extra: this.getExtra() }};
}}
>>>>>>> REPLACE

EXAMPLE (BAD - Too Large, Will Be REJECTED):
File: src/utils/helper.js
<<<<<<< SEARCH
[50+ lines of code including entire file]
=======
[50+ lines with minor changes]
>>>>>>> REPLACE

DO NOT use [FILE:], [SEARCH], <<<<---, or any other format. Use EXACTLY the format above.
"""
        else:
            # Visual app mode - no test, implement the feature directly
            prompt = f"""Implement the feature described in the plan by modifying the existing source files.

⚠️⚠️⚠️ CRITICAL: For UI/display features, you MUST modify BOTH:
1. Data files (to add new data fields) - AND -
2. JavaScript/display code (to SHOW the new data in the UI)

Just adding data to JSON is NOT ENOUGH. The display code (Tooltip.js, Planet.js, etc.) must be patched to actually render the new information!

PLAN: {plan}
{framework_guidance}
EXISTING CODE CONTEXT (with line numbers for reference):
{context}

{symbol_context_str}

INSTRUCTIONS:
1. IMPLEMENT ALL CHANGES mentioned in the plan - both data changes AND UI/display code changes.
2. MODIFY existing source files (like .js, .html, .css) to implement the feature.
3. Do NOT create test files - this is a visual app that will be verified by the user.
4. CRITICAL: Use EXACT field names from JSON/data files in the context. DO NOT invent field names.
5. Use the line numbers in the context for reference only. Do NOT include them in your patches.
6. Make the SMALLEST possible change to achieve the goal. Be surgical.
7. Provide multiple small patches instead of one large block if changes are far apart.
8. Follow framework-specific guidelines above (if any).

⚠️ IMPORTANT: You MUST modify ALL files needed for the feature to work end-to-end.
If the plan mentions updating both data files AND display code, provide patches for BOTH.

⚠️ CRITICAL PATCH RULE:
Your SEARCH block MUST be copied EXACTLY from the EXISTING CODE CONTEXT above.
- Copy the exact lines including all whitespace and formatting
- Do NOT invent or guess what the code looks like
- If you can't find the exact code in the context, do NOT patch that file

🛑 ABSOLUTE PROHIBITIONS (VIOLATIONS WILL BE REJECTED):
⛔ NEVER replace more than 20 lines in a single SEARCH/REPLACE block
⛔ NEVER include entire file content in SEARCH block
⛔ NEVER replace entire functions/classes - target specific sections
⛔ NEVER create SEARCH blocks larger than 20 lines
⛔ Wholesale file replacements are AUTOMATICALLY REJECTED by validation

✅ SURGICAL CHANGE PRINCIPLE:
- Identify the MINIMAL code that needs modification (typically 3-15 lines)
- Include ONLY the lines that change, plus 1-2 context lines
- Break large changes into MULTIPLE small patches
- Each patch should have a clear, focused purpose

⛔ CRITICAL RULE: You may ONLY patch files from the ACTIVE FILES list in the context above!
⛔ DO NOT patch files marked as [ORPHAN] - they are NOT loaded at runtime!
⛔ If you patch an orphaned file, the changes will have NO EFFECT!

FORMAT FOR NEW FILES:
--- NEW FILE: actual/path/to/newfile.ext ---
<content>
--- END FILE ---

FORMAT FOR MODIFYING FILES (Surgical Patch):
File: actual/path/from/context.ext
<<<<<<< SEARCH
<exact string match copied from EXISTING CODE CONTEXT - no line numbers>
=======
<replacement>
>>>>>>> REPLACE

EXAMPLE (adding method to display more info):
File: src/components/Tooltip.js
<<<<<<< SEARCH
    show(content) {{
        this.element.innerHTML = content;
        this.element.style.display = 'block';
    }}
=======
    show(content) {{
        // Enhanced display
        const html = this._formatDetailedContent(content);
        this.element.innerHTML = html;
        this.element.style.display = 'block';
    }}
>>>>>>> REPLACE

DO NOT use [FILE:], [SEARCH], <<<<---, or any other format. Use EXACTLY the format above.
"""

        # Capture baselines for existing files that might be modified
        baselines = {}
        
        current_lint_error = None
        
        for attempt in range(4):
            try:
                # Add hint if retrying
                current_prompt = prompt
                if attempt > 0:
                    if current_lint_error:
                         current_prompt += f"\n\nIMPORTANT: Previous attempt had LINT/SYNTAX ERRORS:\n{current_lint_error}\nPlease fix."
                    else:
                         current_prompt += f"\n\nIMPORTANT: Previous attempt was parsed incorrectly. Follow formatting EXACTLY."

                # Progress indicator
                self.output(f"[Attempt {attempt + 1}/4] Generating implementation code (this may take 30-60s)...")

                # Call LLM with timeout
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.llm_client.generate,
                            prompt=current_prompt,
                            temperature=0.2,
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

                # Debug output: show LLM response info
                self.output(f"  └─ LLM response received: {len(content)} chars")

                # Parse New Files
                new_files = self._parse_new_files(content)
                # Parse Patches
                patches = self._parse_patches(content)

                # Debug output: show what was parsed
                self.output(f"  └─ Parsed: {len(new_files)} new files, {len(patches)} patches")

                if not new_files and not patches:
                    # Show snippet of what LLM returned to help diagnose
                    snippet = content[:500].replace('\n', ' ')[:200]
                    self.output(f"  ⚠ No changes parsed. LLM snippet: {snippet}...")
                    logger.warning(f"Failed to parse changes from LLM. Full response:\n{content[:2000]}")
                    if attempt == 3: return {'success': False, 'error': 'No changes parsed from LLM response'}
                    continue
                    
                # Apply Changes
                modified_list = []
                # 1. Apply New Files (with stub detection)
                if new_files:
                    self.output(f"  └─ Creating {len(new_files)} new files (with stub check)...")
                for fname, code in new_files.items():
                    fpath = self.project_dir / fname
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    # No backup for new files per se, but good practice if checking existence
                    if fpath.exists(): self.context.backup_file(fpath)
                    
                    # NEW: Detect and complete stubs before writing
                    stubs = self._detect_stubs(code, fname)
                    if stubs:
                        self.output(f"    ⚠ Detected {len(stubs)} stubs in {fname}, completing...")
                        code = await self._complete_stubs(fname, code, stubs)
                    
                    # NEW: Code quality review loop
                    code = await self._review_code_quality(fname, code)
                    
                    fpath.write_text(code)
                    modified_list.append(fname)
                    self.output(f"    ✓ Created: {fname}")
                    
                # 2. Apply Patches
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

                if patch_dicts:
                    self.output(f"  └─ Applying {len(patch_dicts)} patches...")
                    # Capture baselines for existing files that might be modified (with timeout)
                    for p in patch_dicts:
                        fname = p['file']
                        if fname not in baselines:
                            fpath = self.project_dir / fname
                            if fpath.exists():
                                try:
                                    baselines[fname] = await asyncio.wait_for(
                                        self.linter_service.check_file(fpath, strict=True),
                                        timeout=15.0  # 15 second timeout per file
                                    )
                                except asyncio.TimeoutError:
                                    logger.warning(f"Baseline lint check timed out for {fname}")
                                    baselines[fname] = None  # Skip baseline for this file

                    res = self.patch_applier.apply_patches(patch_dicts)
                    if not res.success:
                        # Rollback new files too
                        # Extract file name from error and include actual content
                        error_msg = res.error
                        # Try to find which file failed and show its actual content
                        for p in patch_dicts:
                            if p['file'] in error_msg:
                                fpath = self.project_dir / p['file']
                                if fpath.exists():
                                    actual_content = fpath.read_text(encoding='utf-8', errors='replace')
                                    # Show relevant portion of the file
                                    lines = actual_content.splitlines()
                                    snippet = '\n'.join(lines[:100])  # First 100 lines
                                    error_msg += f"\n\n--- ACTUAL CONTENT OF {p['file']} (first 100 lines) ---\n{snippet}\n---"
                                break
                        current_lint_error = f"Patch failed: {error_msg}"
                        self.output(f"  ❌ Patch application failed: {res.error}")
                        await self._rollback(modified_list + res.modified_files)
                        continue
                    else:
                        self.output(f"  ✓ Applied {len(patch_dicts)} patches to {len(res.modified_files)} files")
                    modified_list.extend(res.modified_files)
                
                # 3. Gate 1: Lint
                self.output("[Gate 1] Linting changes...")
                lint_failed = False
                lint_errors = []

                unique_modified = list(set(modified_list))
                for fname in unique_modified:
                    fpath = self.project_dir / fname
                    # On the last attempt, be less strict (only check syntax)
                    is_last_attempt = (attempt == 3)

                    try:
                        l_res = await asyncio.wait_for(
                            self.linter_service.check_file(
                                fpath,
                                strict=not is_last_attempt,
                                baseline=baselines.get(fname)
                            ),
                            timeout=30.0  # 30 second timeout per file
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Lint check timed out for {fname}")
                        l_res = LinterResult(True, [])  # Assume OK if times out

                    if not l_res.valid:
                        lint_failed = True
                        lint_errors.append(f"{fname}: {l_res.errors}")
                    
                if lint_failed:
                    current_lint_error = "\n".join(str(e) for e in lint_errors)
                    self.output(f"❌ Lint Failed: {current_lint_error}")
                    await self._rollback(unique_modified)
                    continue
                    
                self.output("✅ Lint Passed")
                return {'success': True, 'files_modified': unique_modified}
                
            except Exception as e:
                logger.exception("Implementation loop error")
                if attempt == 3: return {'success': False, 'error': str(e)}

        return {'success': False, 'error': "Failed to implement valid feature after 4 attempts (Lint/Patch error)"}

    async def _attempt_recursive_repair(
        self, 
        plan: str, 
        test_code: str, 
        initial_error: str, 
        files_modified: List[str],
        test_path: Path
    ) -> Dict[str, Any]:
        """
        Attempt to fix the implementation in-place based on test failure.
        Returns {'success': bool, 'files_modified': List[str]}
        """
        self.output("\n[REPAIR LOOP] Entering recursive repair loop...")
        
        current_error = initial_error
        # Copy list to avoid mutating original reference immediately, though we want to track all
        current_files_modified = list(files_modified)
        
        # We need the context of files we modified to help the LLM
        file_contents = {}
        for f in current_files_modified:
            try:
                p = self.project_dir / f
                if p.exists():
                    raw_content = p.read_text(encoding='utf-8')
                    if len(raw_content) > 15000:
                        raw_content = raw_content[:15000] + "\n... (further content truncated)"
                    
                    # Add line numbers
                    lines = raw_content.splitlines()
                    numbered_lines = [f"{i+1:4}: {line}" for i, line in enumerate(lines)]
                    file_contents[f] = "\n".join(numbered_lines)
            except Exception: pass
            
        formatted_files = "\n".join([f"--- {k} (with line numbers) ---\n{v}\n" for k, v in file_contents.items()])
        
        # Get LLM-guided framework guidance once before the loop (uses file_contents)
        # Build simple dict for guidance (without line numbers)
        guidance_files = {}
        for f in current_files_modified[:3]:
            try:
                p = self.project_dir / f
                if p.exists():
                    guidance_files[f] = p.read_text(encoding='utf-8')[:2000]
            except Exception:
                pass
        framework_guidance = await self.test_generator.get_framework_guidance_for_fix(
            self._session.bug_description if self._session else plan,
            guidance_files
        )

        # Max 3 repair attempts
        for attempt in range(3):
            self.output(f"Repair Attempt {attempt+1}/3: Fixing test error...")

            prompt = f"""The feature implementation FAILED the verification test.

PLAN: {plan}

TEST CODE:
{test_code}

ERROR OUTPUT:
{current_error}

CURRENT MODIFIED CODE:
(Line numbers provided for reference only - do NOT include them in your SEARCH/REPLACE blocks)
{formatted_files}
{framework_guidance}
INSTRUCTIONS:
1. Fix the code to pass the test.
2. Focus ONLY on the error above.
3. Be SURGICAL. Make the smallest possible change.
4. Use SEARCH/REPLACE blocks (Surgical Patches).
5. The SEARCH block must match exactly (ignoring line numbers).
6. Follow framework-specific guidelines above (if any).
7. Return ONLY the patches.

CRITICAL ANALYSIS - BEFORE FIXING, CONSIDER:
- Visual verification (colors, fonts, appearance) is for END USERS, not automated tests
- If the test asserts on visual properties that cannot be automatically verified,
  the IMPLEMENTATION may already be correct - the test itself may be inappropriate
- Focus on fixing code logic, not trying to match arbitrary visual assertions
- If the error is about exact values (colors, pixels, specific numbers) and the code
  change has been made correctly, consider that the test expectations may be wrong

File: path/to/file.ext
<<<<<<< SEARCH
<original code (no line numbers)>
=======
<replacement>
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
                    continue
                    
                patches = self._parse_patches(response.content)
                if not patches:
                    self.output("No patches generated in repair.")
                    continue
                    
                # Apply Patches
                patch_dicts = [{'file': p['file'], 'search': p['search'], 'replace': p['replace']} for p in patches]
                res = self.patch_applier.apply_patches(patch_dicts)
                
                if not res.success:
                    self.output(f"Repair patch failed: {res.error}")
                    continue
                    
                # Track newly modified files
                for f in res.modified_files:
                    if f not in current_files_modified:
                        current_files_modified.append(f)
                        
                # 1. Lint (Gate 1)
                lint_failed = False
                for fname in res.modified_files:
                    # On the last repair attempt, be less strict
                    is_last_attempt = (attempt == 2)
                    l_res = await self.linter_service.check_file(self.project_dir / fname, strict=not is_last_attempt)
                    if not l_res.valid:
                        lint_failed = True
                        self.output(f"Repair introduced lint error in {fname}: {l_res.errors}")
                        # Rollback this repair step?
                        # Yes, we should rollback this specific bad patch to try again
                        # But simpler is to define 'current_error' as 'Lint Error' and retry loop?
                        # For now, let's treat it as a failed attempt.
                        current_error = f"Previous repair attempt introduced Lint Error: {l_res.errors}"
                        break
                
                if lint_failed:
                    continue
                    
                # 2. Run Test (Gate 2)
                self.output("Verifying repair...")
                test_result = await self.test_generator.run_test(test_path, timeout=test_timeout)
                
                if test_result.passed:
                    self.output("✅ Repair Successful! Test passed.")
                    return {'success': True, 'files_modified': current_files_modified}
                else:
                    self.output(f"⚠️ Repair failed. Test still fails: {test_result.error[:100]}...")
                    current_error = test_result.error
                    
                    # Update file contents for next prompt
                    file_contents = {}
                    for f in current_files_modified:
                        try:
                            p = self.project_dir / f
                            if p.exists():
                                 file_contents[f] = p.read_text(encoding='utf-8')
                        except Exception: pass
                    formatted_files = "\n".join([f"--- {k} ---\n{v}\n" for k, v in file_contents.items()])
            
            except Exception as e:
                logger.warning(f"Repair loop exception: {e}")
                
        return {'success': False, 'files_modified': current_files_modified}

    def _parse_new_files(self, content: str) -> Dict[str, str]:
        """Parse '--- NEW FILE: ... ---' blocks."""
        files = {}
        pattern = r'---\s*NEW FILE:\s*([^\s-]+)\s*---\s*\n?(.*?)\n?---\s*END FILE\s*---'
        matches = re.findall(pattern, content, re.DOTALL)
        for name, code in matches:
            files[name.strip()] = code.strip()

        # Log if we see partial matches (debug parsing issues)
        if not files and '--- NEW FILE:' in content:
            logger.warning("Saw '--- NEW FILE:' marker but pattern didn't match. Check format.")
            # Try to find what file names were mentioned
            partial = re.findall(r'---\s*NEW FILE:\s*([^\n]+)', content)
            if partial:
                logger.warning(f"Partial matches found: {partial[:3]}")

        return files

    def _parse_patches(self, content: str) -> List[Dict[str, str]]:
        """Parse SEARCH/REPLACE blocks. Reusing logic from debug controller conceptually."""
        patches = []
        block_pattern = r'<<<<<<<\s*SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>\s*REPLACE'
        
        for match in re.finditer(block_pattern, content, re.DOTALL):
            search_content = match.group(1)
            replace_content = match.group(2)
            preceding_text = content[:match.start()]
            
            # Look for File: filename
            fname = None
            file_markers = ["File:", "FILE:", "file:", "--- File:", "--- FILE:"]
            latest_pos = -1
            
            for marker in file_markers:
                pos = preceding_text.rfind(marker)
                if pos > latest_pos:
                    latest_pos = pos
            
            if latest_pos != -1:
                # Extract the line after the marker
                after_marker = preceding_text[latest_pos:].splitlines()
                if after_marker:
                    line_after = after_marker[0]
                    name_match = re.search(r'(?:File:|FILE:|file:|--- File:|--- FILE:)\s*([^\s\n`\'"]+\.\w+)', line_after, re.IGNORECASE)
                    if name_match:
                        fname = name_match.group(1).strip()
                
            if fname:
                # STRATEGY: Strip line numbers if the LLM included them
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
                
                patches.append({'file': fname, 'search': search_content, 'replace': replace_content})

        # Log if we see partial matches (debug parsing issues)
        if not patches:
            if '<<<<<<< SEARCH' in content or '<<<<<<<SEARCH' in content:
                logger.warning("Saw SEARCH marker but pattern didn't match. Check format.")
            if 'File:' in content and '=======' in content:
                logger.warning("Saw File: and ======= markers but no complete patch block parsed.")

        return patches

    def _extract_code(self, text: str, lang_hint: str = "") -> str:
        """
        Extract code from LLM response using iron-clad extraction.

        Uses the centralized extraction from llm_client which handles:
        - Thinking/reasoning tags from various models
        - Multiple code blocks (picks the best/largest)
        - Quality scoring (completeness, bracket balance)
        - Unfenced code detection
        """
        from ..llm_client import extract_best_code_block, strip_thinking_content

        # First strip any thinking content
        text = strip_thinking_content(text)

        # Use iron-clad extraction with quality scoring
        # Map lang_hint to expected_type format
        expected_type = lang_hint.lower() if lang_hint else None
        return extract_best_code_block(text, expected_type)

    def _get_model(self) -> str:
        from agents.common.config_loader import AgentConfigLoader
        try:
            config = AgentConfigLoader.load_config('coding_agent')
            return config.get_llm_model()
        except Exception:
            return "RAICA-Model1"

    async def _run_visual_loop(self) -> EnhancementResult:
        """
        Run enhancement loop for visual/web applications.

        Visual apps require manual verification, so we:
        0. CRITICAL: Build execution graph from entry points
        1. Understand & research the feature (using ONLY active files)
        2. Apply the implementation (no test generation)
        3. User verifies visually

        No automated tests - user confirmation required.
        """
        self.output("\n" + "="*60)
        self.output("VISUAL APP ENHANCEMENT MODE (No automated tests)")
        self.output("="*60)

        iteration = DebugIteration(iteration_number=1)

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 0: BUILD EXECUTION GRAPH (CRITICAL - DO NOT SKIP)
        # ═══════════════════════════════════════════════════════════════════
        # This is the most important step! We MUST trace code paths from
        # entry points to find which files are ACTUALLY used at runtime.
        # Without this, we might modify orphaned files that look relevant
        # but are never loaded (e.g., ES module files when app.js is used).
        # ═══════════════════════════════════════════════════════════════════
        self.output("\n[PHASE 0] Building execution graph from entry points...")
        self._execution_context = await self.code_path_tracer.build_graph()

        if self._execution_context.entry_points:
            self.output(f"   Entry points: {', '.join(self._execution_context.entry_points)}")
            self.output(f"   Active files: {len(self._execution_context.active_files)}")
            self.output(f"   Orphaned files: {len(self._execution_context.orphaned_files)}")

            # CRITICAL: Show warnings about orphaned files
            if self._execution_context.warnings:
                self.output("\n   ⚠️  WARNINGS:")
                for warning in self._execution_context.warnings:
                    self.output(f"      {warning}")
        else:
            self.output("   ⚠️  No entry points found - will use all files (less accurate)")

        # PHASE 1: UNDERSTAND & RESEARCH
        self.output("\n[PHASE 1] Understanding & Researching...")
        self._session.set_status(DebugStatus.ANALYZING)

        # Search codebase - NOW USES EXECUTION GRAPH TO FILTER
        context_result = await self._gather_context(self._session.bug_description)
        self._relevant_files = context_result['files']

        # Web research
        research_info = await self._perform_web_research(
            self._session.bug_description,
            context_result['summary']
        )

        # ─────────────────────────────────────────────────────
        # INVESTIGATION PHASE: Check if existing functionality can fulfill request
        # LLM decides: execute_existing OR implement_new
        # ─────────────────────────────────────────────────────
        investigation_result = await self._investigate_before_implementation(
            self._session.bug_description,
            context_result
        )

        if investigation_result.get("decision") == "execute_existing":
            # LLM found existing functionality - execute it instead of implementing
            commands = investigation_result.get("commands", [])
            self.output(f"\n Found existing functionality to execute!")
            self.output(f"   Reasoning: {investigation_result.get('reasoning', 'N/A')[:200]}")

            # Execute the commands
            from ..services.debug_toolkit import DebugToolkit
            toolkit = DebugToolkit(self.project_dir)

            all_success = True
            execution_outputs = []

            for cmd in commands:
                self.output(f"   Executing: {cmd}")
                result = toolkit.run_command(cmd)
                execution_outputs.append({
                    "command": cmd,
                    "success": result.success,
                    "output": str(result.result) if result.success else result.error
                })
                if not result.success:
                    all_success = False
                    self.output(f"   Command failed: {result.error}")
                else:
                    stdout = result.result.get('stdout', '') if isinstance(result.result, dict) else str(result.result)
                    self.output(f"   Output: {stdout[:500]}")

            # Update session and return
            self._session.set_status(DebugStatus.COMPLETE if all_success else DebugStatus.FAILED)
            self.context.save_session(self._session)

            return EnhancementResult(
                success=all_success,
                iterations=1,
                files_modified=[],
                summary=f"Executed existing functionality: {investigation_result.get('reasoning', '')}",
                error=None if all_success else "Some commands failed"
            )

        # LLM decided to implement new - proceed with implementation
        self.output("   Proceeding with implementation (no existing solution found)")

        # Generate Plan
        plan = await self._create_implementation_plan(
            self._session.bug_description,
            context_result['full_text'],
            research_info
        )
        self._plan = plan
        iteration.hypothesis = "Implementation Plan: " + plan[:100] + "..."
        self.output(f"Plan: {plan[:200]}...")

        # PHASE 2: IMPLEMENT (Skip test generation)
        self.output("\n[PHASE 2] Implementing enhancement & Linting...")
        self._session.set_status(DebugStatus.FIXING)

        impl_result = await self._implement_feature_and_lint(
            plan=plan,
            test_code="",  # No test for visual apps
            test_error=None,
            context=context_result['full_text']
        )

        if not impl_result['success']:
            error_msg = impl_result.get('error', 'Unknown error')
            self.output(f"❌ Failed to apply enhancement: {error_msg}")
            return EnhancementResult(
                success=False,
                iterations=1,
                error=error_msg
            )

        iteration.files_modified = impl_result['files_modified']
        self._session.files_modified = impl_result['files_modified']

        self.output(f"✅ Modified: {', '.join(impl_result['files_modified'])}")

        # Generate comprehensive change summary
        change_summary = await self._generate_change_summary(
            files_modified=impl_result['files_modified'],
            plan=plan,
            request=self._session.bug_description
        )
        self.output(change_summary)

        # Update persistent context for future requests
        await self._update_persistent_context(
            files_modified=impl_result['files_modified'],
            request=self._session.bug_description,
            success=True
        )

        # SUCCESS - User must verify
        self.output("\n" + "="*60)
        self.output("✅ ENHANCEMENT APPLIED - Please verify visually")
        self.output("="*60)
        self.output("\n👁️  Run your application and check if the enhancement works.")
        self.output("   If not, describe what's still wrong and I'll try again.")

        self._session.set_status(DebugStatus.COMPLETE, "Enhancement applied - awaiting user verification")
        self._record_iteration(iteration)

        return EnhancementResult(
            success=True,
            iterations=1,
            files_modified=impl_result['files_modified'],
            summary=change_summary
        )

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

    async def _rollback(self, files: List[str]) -> None:
        for f in files:
            try:
                self.context.restore_file(self.project_dir / f)
            except Exception:
                pass

    async def _generate_change_summary(self, files_modified: List[str], plan: str, request: str) -> str:
        """
        Generate a comprehensive summary of all changes made.

        Returns a formatted string summarizing:
        - What was requested
        - What files were modified
        - Key changes in each file
        - Data structures used
        """
        summary_lines = []
        summary_lines.append("\n" + "="*60)
        summary_lines.append("📋 CHANGE SUMMARY")
        summary_lines.append("="*60)

        # 1. What was requested
        summary_lines.append(f"\n🎯 REQUEST: {request[:200]}{'...' if len(request) > 200 else ''}")

        # 2. Implementation approach
        summary_lines.append(f"\n📝 APPROACH: {plan[:300]}{'...' if len(plan) > 300 else ''}")

        # 3. Files modified with details
        summary_lines.append(f"\n📁 FILES MODIFIED ({len(files_modified)}):")

        for f in files_modified:
            try:
                full_path = self.project_dir / f
                if full_path.exists():
                    content = full_path.read_text(encoding='utf-8', errors='replace')
                    line_count = len(content.splitlines())
                    size_kb = len(content) / 1024

                    # Determine file type from language definitions
                    ext = full_path.suffix.lower()
                    file_type = "Unknown"
                    for lang_key, lang_info in LANGUAGE_DEFINITIONS.items():
                        if ext in lang_info.file_extensions:
                            file_type = lang_info.name
                            break
                    # Special cases for data/config files
                    if ext in ['.json', '.yaml', '.yml', '.toml']:
                        file_type = "Data/Config file"
                    elif file_type == "Unknown" and ext:
                        file_type = ext.upper().lstrip('.')

                    summary_lines.append(f"   • {f}")
                    summary_lines.append(f"     Type: {file_type} | Lines: {line_count} | Size: {size_kb:.1f}KB")
                else:
                    summary_lines.append(f"   • {f} (NEW FILE)")
            except Exception as e:
                summary_lines.append(f"   • {f} (could not read: {e})")

        # 4. Data structures referenced
        data_files_used = [f for f in self._relevant_files if f.endswith('.json') or f.endswith('.yaml')]
        if data_files_used:
            summary_lines.append(f"\n📊 DATA STRUCTURES REFERENCED:")
            for df in data_files_used[:3]:
                summary_lines.append(f"   • {df}")

        summary_lines.append("\n" + "="*60)

        return "\n".join(summary_lines)

    async def _update_persistent_context(self, files_modified: List[str], request: str, success: bool) -> None:
        """
        Update the persistent project context after changes are applied.

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
                    'request': request[:500],
                    'files_modified': files_modified,
                    'success': success,
                    'type': 'enhancement'
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
                self.output(f"   ✓ Recorded change in project history")
            else:
                logger.debug("No context manager available for persistent update")

        except Exception as e:
            logger.warning(f"Failed to update persistent context: {e}")
            self.output(f"   ⚠ Could not update context: {e}")

    def _record_iteration(self, iteration: DebugIteration) -> None:
        self._session.add_iteration(iteration)
        self.context.save_iteration(iteration)
        self.context.save_session(self._session)

