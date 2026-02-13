"""
Debug Orchestrator - Coordinates the tool-calling debug flow.

This is the main entry point that:
1. Initializes all components (toolkit, context, planners)
2. Coordinates the 3-phase debug architecture
3. Logs all tool calls through the context tracker
4. Manages the feedback loop with the LLM
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .debug_toolkit import DebugToolkit, ToolResult
from .tool_executor import ToolExecutor, ToolCall, ExecutionResult
from .guidance_planner import GuidancePlanner, DiagnosisPlan
from .tool_calling_client import ToolCallingClient
from .debug_context import DebugContext
from .adaptive_patch_matcher import AdaptivePatchMatcher
from .generalized_debug_engine import GeneralizedDebugEngine

logger = logging.getLogger(__name__)


class DebugOrchestrator:
    """
    Main orchestrator for tool-calling debug sessions.
    
    Coordinates:
    - Phase 1: Diagnosis planning (LLM provides JSON steps)
    - Phase 2: Tool execution (structured tool calls)
    - Phase 3: Fix application and verification
    
    Tracks all activity through DebugContext for:
    - LLM context continuity
    - Logging and auditing
    - Session persistence and recovery
    
    Usage:
        orchestrator = DebugOrchestrator(
            project_dir=Path("/path/to/project"),
            llm_client=llm_client,
            issue="Fix requirements.txt"
        )
        result = await orchestrator.run()
    """
    
    def __init__(
        self,
        project_dir: Path,
        llm_client,
        issue: str,
        error_trace: str = "",
        output_fn: Callable[[str], None] = print,
        max_iterations: int = 10,
        session_id: str = None,
        use_generalized_debug: bool = True
    ):
        """
        Initialize the debug orchestrator.

        Args:
            project_dir: Path to the project
            llm_client: LLM client with generate() method
            issue: Description of the bug
            error_trace: Error output from running code
            output_fn: Function to output progress
            max_iterations: Max debug iterations
            session_id: Resume from previous session
            use_generalized_debug: Use LLM-driven generalized debugging (default True)
                                   instead of pattern-matching special case handlers
        """
        self.use_generalized_debug = use_generalized_debug
        self.project_dir = Path(project_dir)
        self.llm_client = llm_client
        self.issue = issue
        self.error_trace = error_trace
        self.output = output_fn
        self.max_iterations = max_iterations
        
        # Initialize context (new or resumed)
        if session_id:
            self.context = DebugContext.load_state(project_dir, session_id)
            if not self.context:
                self.context = DebugContext(project_dir, issue, error_trace, session_id)
        else:
            self.context = DebugContext(project_dir, issue, error_trace)
        
        # Initialize the persistent context manager for file structure and symbols
        self.project_context = None
        try:
            from agents.common.context.manager import ContextManager
            self._context_manager = ContextManager(
                project_dir=project_dir,
                auto_initialize=True
            )
            self.project_context = self._context_manager.project_context
            self.output("   ✓ Project context loaded")
        except Exception as e:
            logger.warning(f"Could not load project context: {e}")
            self._context_manager = None
        
        # Initialize components
        self.toolkit = DebugToolkit(project_dir)
        self.executor = ToolExecutor(self.toolkit)
        self.planner = GuidancePlanner(llm_client)
        self.tool_client = ToolCallingClient(llm_client, self.toolkit)

        from .dependency_resolver import DependencyResolver
        self.dependency_resolver = DependencyResolver(llm_client)

        # Initialize generalized debug engine (LLM-driven, no pattern matching)
        # Pass project context so LLM has full knowledge of file structure and symbols
        # Pass debug_context so LLM has access to project LLD/objectives
        self.generalized_engine = GeneralizedDebugEngine(
            project_dir=project_dir,
            llm_client=llm_client,
            output_fn=output_fn,
            project_context=self.project_context,
            debug_context=self.context
        ) if use_generalized_debug else None
        
        # Wire up tool execution to context tracking
        self._original_execute = self.toolkit.execute
        self.toolkit.execute = self._tracked_execute
        
        # Log LLM model info
        self._log_model_info()
        logger.info(f"DebugOrchestrator initialized: session={self.context.session_id}")

    def _log_model_info(self):
        """Log which LLM model is being used."""
        try:
            model_info = []
            if hasattr(self.llm_client, 'primary_provider'):
                model_info.append(f"Provider: {self.llm_client.primary_provider}")
            if hasattr(self.llm_client, 'primary_model') and self.llm_client.primary_model:
                model_info.append(f"Model: {self.llm_client.primary_model}")
            if hasattr(self.llm_client, '_model_override') and self.llm_client._model_override:
                model_info.append(f"Override: {self.llm_client._model_override}")

            # Try to get model from config
            if hasattr(self.llm_client, 'config'):
                providers = self.llm_client.config.get('providers', {})
                primary = getattr(self.llm_client, 'primary_provider', 'ollama')
                if primary in providers:
                    model = providers[primary].get('model', 'unknown')
                    model_info.append(f"Config model: {model}")

            if model_info:
                self.output(f"   🤖 LLM: {' | '.join(model_info)}")
            else:
                self.output("   🤖 LLM: (model info not available)")
        except Exception as e:
            logger.warning(f"Could not get model info: {e}")
    
    def _tracked_execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """Execute a tool with context tracking."""
        # Start tracking
        call_id = self.context.start_tool_call(tool_name, args)
        start_time = time.time()
        
        # Execute
        result = self._original_execute(tool_name, args)
        
        # Complete tracking
        duration_ms = int((time.time() - start_time) * 1000)
        self.context.complete_tool_call(
            call_id,
            result=result.result if result.success else None,
            error=result.error,
            duration_ms=duration_ms
        )
        
        return result
    
    async def run(self) -> Dict:
        """
        Run the complete debug session with continuation until verified.

        This method:
        1. Runs diagnosis → fix → verification cycle
        2. If verification fails, captures new error and continues
        3. Repeats until verification passes or max_iterations reached

        Returns:
            Dict with outcome, files modified, etc.
        """
        self.output("\n" + "═" * 60)
        self.output("🔧 RAICA DEBUG ORCHESTRATOR")
        self.output("═" * 60)
        self.output(f"Session: {self.context.session_id}")
        self.output(f"Issue: {self.issue}")

        # Show LLM model info
        self._log_model_info()
        self.output("")
        
        # Track iterations
        iteration = 0
        max_debug_iterations = self.max_iterations
        last_error = self.error_trace
        
        try:
            # Pre-flight (only once)
            await self._pre_flight()
            
            # Debug loop - continues until verification passes or max iterations
            while iteration < max_debug_iterations:
                iteration += 1
                self.output(f"\n{'─' * 40}")
                self.output(f"🔄 DEBUG ITERATION {iteration}/{max_debug_iterations}")
                self.output(f"{'─' * 40}")
                
                # Update error trace with latest error
                if iteration > 1:
                    self.error_trace = last_error
                    self.context.add_finding(f"iteration_{iteration}_error", last_error[:500])
                
                # Phase 1: Diagnosis
                self.context.start_phase(f"diagnosis_{iteration}")
                plan = await self._run_diagnosis_phase()
                
                if not plan or not plan.steps:
                    self.output("❌ Could not create diagnosis plan")
                    # Try to continue with fallback
                    continue
                
                # Phase 2: Execute diagnosis
                diagnosis_findings = await self._execute_diagnosis(plan)
                
                # Phase 3: Apply fix
                self.context.start_phase(f"fix_{iteration}")
                fix_success = await self._run_fix_phase(diagnosis_findings)
                
                # Phase 4: Verify
                self.context.start_phase(f"verification_{iteration}")
                verified, new_error = await self._run_verification_phase_with_error_capture()
                
                if verified:
                    self.output("\n" + "═" * 60)
                    self.output(f"✅ DEBUG SUCCESSFUL after {iteration} iteration(s)!")
                    self.output("═" * 60)
                    return self._finalize(success=True)
                
                # Verification failed - capture new error and continue
                if new_error:
                    self.output(f"\n   ⚠ New error captured, continuing to next iteration...")
                    last_error = new_error
                else:
                    self.output(f"\n   ⚠ Verification failed but no new error captured")
                    # Try with original issue
                
                # Check if we're making progress
                if iteration > 1:
                    self.output("   📊 Checking if progress is being made...")
        
            # Max iterations reached
            self.output("\n" + "═" * 60)
            self.output(f"⚠️ Max iterations ({max_debug_iterations}) reached without full verification")
            self.output("═" * 60)
            return self._finalize(success=False, error=f"Max iterations ({max_debug_iterations}) reached")
                
        except Exception as e:
            logger.exception("Debug session failed")
            self.output(f"\n❌ Error: {e}")
            return self._finalize(success=False, error=str(e))
    
    def _finalize(self, success: bool, error: str = None) -> Dict:
        """Finalize the session and return results."""
        self.context.fix_summary = "Fixed successfully" if success else error
        self.context.save_state()
        
        summary = self.context.get_summary()
        summary["success"] = success
        summary["error"] = error
        
        self.output(f"\nSession saved: {self.context.session_id}")
        self.output(f"Tool calls: {summary['tool_calls']['total']} ({summary['tool_calls']['successful']} OK)")
        if self.context.files_modified:
            self.output(f"Files modified: {', '.join(self.context.files_modified)}")
        
        return summary
    
    async def _pre_flight(self):
        """Pre-flight checks."""
        self.output("📦 [PRE-FLIGHT] Running checks...")
        
        # Sanitize requirements
        result = self.toolkit.sanitize_requirements()
        if result.success and result.result.get("removed"):
            self.output(f"   ✓ Cleaned {len(result.result['removed'])} invalid entries")
        
        # Install dependencies
        req_path = self.project_dir / 'requirements.txt'
        if req_path.exists():
            result = self.toolkit.run_command("pip install -r requirements.txt")
            if result.success:
                self.output("   ✓ Dependencies installed")
            else:
                self.output(f"   ⚠ pip issues (continuing anyway)")
    
    async def _run_diagnosis_phase(self) -> DiagnosisPlan:
        """Phase 1: Get diagnosis plan from LLM."""
        self.output("\n[PHASE 1] Getting diagnosis plan...")
        
        # Get project files for context
        files = []
        for f in self.project_dir.rglob("*.py"):
            if '.raica' not in str(f) and 'venv' not in str(f):
                files.append(str(f.relative_to(self.project_dir)))
        
        # Get plan
        plan = await self.planner.get_diagnosis_plan(
            issue=self.issue,
            error_trace=self.error_trace,
            project_files=files[:30]
        )
        
        self.output(f"   ✓ Got {len(plan)} diagnosis steps")
        
        # Store in context
        self.context.add_finding("diagnosis_steps", [s.to_dict() for s in plan.steps])
        
        return plan
    
    async def _execute_diagnosis(self, plan: DiagnosisPlan) -> Dict:
        """Phase 2: Execute diagnosis steps."""
        self.output("\n[PHASE 2] Executing diagnosis...")

        findings = {
            "files_read": {},
            "search_results": [],
            "symbols": {},
            "line_context": {},  # NEW: Store line ranges with context
            "errors": []
        }

        for step in plan.steps:
            self.output(f"\n   Step {step.step}: {step.action} - {step.reason or ''}")

            # Build tool args
            args = self._step_to_args(step)

            # Check if step should be skipped
            if args.get("_skip"):
                reason = args.get("_reason", "Invalid arguments")
                self.output(f"      ⚠ Skipped: {reason}")
                findings["errors"].append(f"{step.action}: Skipped - {reason}")
                continue

            # Execute
            result = self.toolkit.execute(step.action, args)

            if result.success:
                self.output(f"      ✓ Success")

                # Collect findings based on action type
                if step.action == "read_file" and step.target:
                    content = result.result
                    findings["files_read"][step.target] = content[:3000] if isinstance(content, str) else str(content)[:3000]

                elif step.action in ("grep_search", "search_with_context"):
                    if isinstance(result.result, dict) and "matches" in result.result:
                        findings["search_results"].extend(result.result["matches"][:15])
                    elif isinstance(result.result, list):
                        findings["search_results"].extend(result.result[:15])

                elif step.action == "get_symbols":
                    target_key = step.target or "unknown"
                    findings["symbols"][target_key] = result.result

                elif step.action in ("get_lines_range", "get_line"):
                    # Store line context for fix phase
                    target_key = step.target or "main.py"
                    if isinstance(result.result, dict):
                        if target_key not in findings["line_context"]:
                            findings["line_context"][target_key] = []
                        findings["line_context"][target_key].append(result.result)

                elif step.action == "sanitize_requirements":
                    if isinstance(result.result, dict) and result.result.get("removed"):
                        self.output(f"      → Removed {len(result.result['removed'])} invalid entries")

            else:
                self.output(f"      ✗ {result.error}")
                findings["errors"].append(f"{step.action}: {result.error}")

        # Store findings in context
        for key, value in findings.items():
            if value:
                self.context.add_finding(key, value)

        return findings
    
    def _step_to_args(self, step) -> Dict:
        """
        Convert a diagnosis step to tool args.

        This method maps DiagnosisStep fields to the appropriate tool arguments.
        Returns empty dict with _skip=True if the step should be skipped.
        """
        args = {}

        # ─────────────────────────────────────────────────────
        # READ-ONLY / DIAGNOSIS TOOLS
        # ─────────────────────────────────────────────────────
        if step.action == "read_file":
            if not step.target:
                return {"_skip": True, "_reason": "No file path specified"}
            args["path"] = step.target

        elif step.action == "grep_search":
            if not step.pattern:
                return {"_skip": True, "_reason": "No search pattern specified"}
            args["pattern"] = step.pattern
            args["scope"] = step.scope or "**/*.py"

        elif step.action == "search_with_context":
            args["path"] = step.target or "main.py"
            args["pattern"] = step.pattern or ""
            if hasattr(step, 'context_lines'):
                args["context_lines"] = step.context_lines

        elif step.action == "get_lines_range":
            args["path"] = step.target or "main.py"
            # Use line_number field if available, otherwise try pattern
            if step.line_number is not None:
                args["start_line"] = step.line_number
            elif step.pattern:
                try:
                    args["start_line"] = int(step.pattern)
                except (ValueError, TypeError):
                    args["start_line"] = 1
            else:
                args["start_line"] = 1

        elif step.action == "get_line":
            args["path"] = step.target or "main.py"
            if step.line_number is not None:
                args["line_number"] = step.line_number
            elif step.pattern:
                try:
                    args["line_number"] = int(step.pattern)
                except (ValueError, TypeError):
                    args["line_number"] = 1
            else:
                args["line_number"] = 1

        elif step.action == "list_files":
            args["directory"] = step.target or "."
            args["pattern"] = step.pattern or "*"

        elif step.action in ("validate_syntax", "get_symbols"):
            if not step.target:
                return {"_skip": True, "_reason": f"No file path specified for {step.action}"}
            args["path"] = step.target

        elif step.action == "find_file":
            args["name"] = step.pattern or step.target or "*"

        elif step.action == "sanitize_requirements":
            pass  # No args needed

        # ─────────────────────────────────────────────────────
        # MUTATION / FIX TOOLS
        # ─────────────────────────────────────────────────────
        elif step.action == "edit_file":
            # Requires: path, search, replace
            if not step.target:
                return {"_skip": True, "_reason": "edit_file requires a file path"}
            args["path"] = step.target
            args["search"] = step.search_text or step.pattern or ""
            args["replace"] = step.replace_text or step.new_content or ""
            # Validate we have actual search/replace content
            if not args["search"]:
                return {"_skip": True, "_reason": "edit_file requires search text"}

        elif step.action == "replace_line":
            # Requires: path, line_number, new_content
            if not step.target:
                return {"_skip": True, "_reason": "replace_line requires a file path"}
            if step.line_number is None:
                return {"_skip": True, "_reason": "replace_line requires a line number"}
            args["path"] = step.target
            args["line_number"] = step.line_number
            args["new_content"] = step.new_content or ""

        elif step.action == "insert_line":
            # Requires: path, after_line, content
            if not step.target:
                return {"_skip": True, "_reason": "insert_line requires a file path"}
            args["path"] = step.target
            args["after_line"] = step.line_number if step.line_number is not None else 0
            args["content"] = step.new_content or ""

        elif step.action == "write_file":
            if not step.target:
                return {"_skip": True, "_reason": "write_file requires a file path"}
            args["path"] = step.target
            args["content"] = step.new_content or ""

        # ─────────────────────────────────────────────────────
        # EXECUTION TOOLS
        # ─────────────────────────────────────────────────────
        elif step.action == "run_python":
            args["script"] = step.target or "main.py"

        elif step.action == "pip_install":
            # Handle packages from various sources
            if step.packages:
                args["packages"] = step.packages
            elif step.target:
                # Single package from target
                args["packages"] = [step.target]
            else:
                # No packages - skip this step
                return {"_skip": True, "_reason": "pip_install requires package names"}

        elif step.action == "run_command":
            if not step.target:
                return {"_skip": True, "_reason": "run_command requires a command"}
            args["command"] = step.target

        # ─────────────────────────────────────────────────────
        # UNKNOWN ACTION
        # ─────────────────────────────────────────────────────
        else:
            logger.warning(f"Unknown action in _step_to_args: {step.action}")
            return {"_skip": True, "_reason": f"Unknown action: {step.action}"}

        return args
    
    async def _run_fix_phase(self, diagnosis: Dict) -> bool:
        """
        Phase 3: Apply fix using tool calls.

        Implements multiple fallback strategies:
        G. Generalized LLM-driven debugging (if enabled) - uses LLM reasoning, no patterns
        0. Special case handling (requirements.txt, syntax errors, etc.) - pattern matching
        1. LLM tool-calling (primary)
        2. Structured LLM fix with AdaptivePatchMatcher (fallback)
        3. LLM block-based fix with AdaptivePatchMatcher
        4. Heuristic direct fix (last resort)
        """
        self.output("\n[PHASE 3] Applying fix...")

        # Strategy G: Generalized LLM-driven debugging (no pattern matching)
        # This uses the LLM to analyze ANY error and propose fixes through investigation
        if self.generalized_engine:
            self.output("   → Strategy G: Generalized LLM-driven debugging")
            try:
                result = await self.generalized_engine.debug(
                    error_trace=self.error_trace,
                    issue_description=self.issue
                )
                if result.get("success"):
                    # Track modified files
                    for path in result.get("files_modified", []):
                        if path not in self.context.files_modified:
                            self.context.files_modified.append(path)
                    self.output("   ✓ Generalized debug succeeded")
                    return True
                else:
                    self.output(f"   ⚠ Generalized debug: {result.get('error', 'unknown error')}")
                    # Fall through to other strategies
            except Exception as e:
                logger.warning(f"Generalized debug engine failed: {e}")
                self.output(f"   ⚠ Generalized debug exception: {e}")

        # Strategy 0: Special case handling for known issue types (legacy pattern matching)
        if self._try_special_case_fix(diagnosis):
            return True

        # Build comprehensive context for LLM
        context = self._build_fix_context(diagnosis)

        # Strategy 1: LLM tool-calling
        self.output("   → Strategy 1: LLM tool-calling")
        result = await self._try_llm_tool_fix(context)

        if result and len(result.results) > 0:
            success = len(result.errors) == 0
            if success:
                # Track modified files
                has_modifications = False
                for r in result.results:
                    if r.metadata and r.metadata.get("path"):
                        path = r.metadata["path"]
                        has_modifications = True
                        if path not in self.context.files_modified:
                            self.context.files_modified.append(path)
                
                if has_modifications:
                    self.output(f"   ✓ Applied {len(result.results)} tool calls successfully")
                    return True
                else:
                    self.output(f"   ⚠ LLM only used informational tools, trying other strategies...")
            else:
                self.output(f"   ⚠ Tool calls had errors: {result.errors[:2]}")

        # Strategy 2: Structured LLM fix (supports both line and block modes)
        self.output("   → Strategy 2: Structured LLM fix (with AdaptivePatchMatcher)")
        success = await self._try_structured_fix(diagnosis, context)
        if success:
            return True

        # Strategy 3: LLM block-based fix (explicit search/replace)
        self.output("   → Strategy 3: LLM block-based fix")
        success = await self._try_block_based_fix(diagnosis, context)
        if success:
            return True

        # Strategy 4: Heuristic direct fix
        if diagnosis.get("files_read"):
            self.output("   → Strategy 4: Heuristic direct fix")
            success = self._attempt_direct_fix(diagnosis)
            if success:
                return True

        self.output("   ✗ All fix strategies failed")
        return False

    async def _try_block_based_fix(self, diagnosis: Dict, context: str) -> bool:
        """
        Strategy 3: Ask LLM explicitly for search/replace blocks.

        This is specifically designed to work with AdaptivePatchMatcher's
        6-strategy cascade for robust patching.
        """
        try:
            # Get files that might need fixing
            files_read = diagnosis.get("files_read", {})
            if not files_read:
                return False

            # Pick the most likely file to fix
            target_file = None
            for path in files_read.keys():
                if path.endswith('.py') and 'main' in path.lower():
                    target_file = path
                    break
            if not target_file:
                target_file = list(files_read.keys())[0]

            file_content = files_read.get(target_file, "")

            prompt = f"""You are a code fixer. Find and fix the bug in this code.

BUG: {self.issue}
ERROR: {self.error_trace[:300] if self.error_trace else 'none'}

FILE: {target_file}
```python
{file_content[:3000]}
```

CRITICAL INSTRUCTION:
If you are fixing an exception handler or adding one, you MUST preserve the full traceback. 
Use `logging.exception("msg", exc_info=True)` or `traceback.print_exc()`. 
NEVER use simple `print(e)` which hides the stack trace.

Provide a SEARCH/REPLACE block to fix the bug.
The SEARCH block must match EXACTLY what's in the file.

Respond in this JSON format ONLY:
{{
  "file": "{target_file}",
  "search": "exact lines to find (copy from file above)",
  "replace": "corrected lines"
}}"""

            import inspect
            result = self.llm_client.generate(
                prompt=prompt,
                temperature=0.0
            )
            if inspect.iscoroutine(result):
                response = await result
            else:
                response = result

            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON using robust utility
            from ..utils.json_utils import extract_json_from_llm_response
            fix_data = extract_json_from_llm_response(content)
            if fix_data:
                file_path = fix_data.get("file", target_file)
                search_block = fix_data.get("search", "")
                replace_block = fix_data.get("replace", "")

                if search_block and replace_block != search_block:
                    self.output(f"   Applying block fix to {file_path}...")

                    # Use AdaptivePatchMatcher with 6-strategy cascade
                    success = self._apply_patch_with_adaptive_matcher(
                        file_path=file_path,
                        search_block=search_block,
                        replace_block=replace_block,
                        verbose=True
                    )

                    if success:
                        return True

        except Exception as e:
            logger.warning(f"Block-based fix failed: {e}")

        return False

    def _try_special_case_fix(self, diagnosis: Dict) -> bool:
        """
        Handle special case fixes that don't need LLM.

        Returns True if a fix was applied.
        """
        issue_lower = self.issue.lower()
        error_trace = self.error_trace or ""
        error_lower = error_trace.lower()

        # Extract the ACTUAL error type from the last line of traceback
        # Format: "ErrorType: message" or just the error message
        actual_error_type = ""
        if error_trace.strip():
            lines = error_trace.strip().split('\n')
            # Get the last non-empty line (contains the actual error)
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith('File ') and not line.startswith('^'):
                    actual_error_type = line.lower()
                    break

        # For matching, prioritize actual error type, fall back to full trace
        combined = issue_lower + " " + error_lower

        # ─────────────────────────────────────────────────────
        # NAMEERROR: name 'X' is not defined (check FIRST - very specific)
        # ─────────────────────────────────────────────────────
        if actual_error_type.startswith("nameerror") or "is not defined" in actual_error_type:
            self.output("   → Strategy 0: NameError (undefined name) special handler")
            return self._fix_name_error(diagnosis)

        # ─────────────────────────────────────────────────────
        # SYNTAX ERROR FIXES
        # ─────────────────────────────────────────────────────
        if actual_error_type.startswith("syntaxerror") or "syntax error" in actual_error_type:
            self.output("   → Strategy 0: Syntax error special handler")
            return self._fix_syntax_error(diagnosis)

        # ─────────────────────────────────────────────────────
        # IMPORT ERROR FIXES
        # ─────────────────────────────────────────────────────
        if actual_error_type.startswith("importerror") or actual_error_type.startswith("modulenotfounderror"):
            self.output("   → Strategy 0: Import error special handler")
            return self._fix_import_error(diagnosis)

        # ─────────────────────────────────────────────────────
        # UNEXPECTED KEYWORD ARGUMENT (signature mismatch)
        # ─────────────────────────────────────────────────────
        if "unexpected keyword argument" in actual_error_type:
            self.output("   → Strategy 0: Unexpected keyword argument special handler")
            return self._fix_unexpected_keyword_argument(diagnosis)

        # ─────────────────────────────────────────────────────
        # MISSING ATTRIBUTE (object has no attribute)
        # ─────────────────────────────────────────────────────
        if "has no attribute" in actual_error_type or actual_error_type.startswith("attributeerror"):
            self.output("   → Strategy 0: Missing attribute special handler")
            return self._fix_missing_attribute(diagnosis)

        # ─────────────────────────────────────────────────────
        # FALLBACK: Check combined for any keywords (historical/issue text)
        # ─────────────────────────────────────────────────────
        if "nameerror" in combined or "is not defined" in combined:
            self.output("   → Strategy 0: NameError (undefined name) special handler")
            return self._fix_name_error(diagnosis)

        if "syntaxerror" in combined or "syntax error" in combined:
            self.output("   → Strategy 0: Syntax error special handler")
            return self._fix_syntax_error(diagnosis)

        if any(kw in combined for kw in ["importerror", "modulenotfounderror"]):
            self.output("   → Strategy 0: Import error special handler")
            return self._fix_import_error(diagnosis)

        # ─────────────────────────────────────────────────────
        # REQUIREMENTS.TXT FIXES
        # ─────────────────────────────────────────────────────
        if "requirements" in issue_lower:
            self.output("   → Strategy 0: Requirements.txt special handler")
            return self._fix_requirements_file(diagnosis)

        return False

    def _fix_unexpected_keyword_argument(self, diagnosis: Dict) -> bool:
        """
        Fix 'unexpected keyword argument' errors.
        
        This happens when a caller passes keyword args that the function
        definition doesn't accept. Fix by either:
        1. Adding the missing parameter to the function definition
        2. Removing the argument from the caller
        
        Usually option 1 is safer as it maintains intended functionality.
        """
        import re
        
        self.output("      Analyzing unexpected keyword argument error...")
        
        error_trace = self.error_trace.lower()
        issue_lower = self.issue.lower()
        combined = error_trace + " " + issue_lower
        
        # Extract the unexpected argument name
        arg_match = re.search(r"unexpected keyword argument ['\"]?(\w+)['\"]?", combined)
        if not arg_match:
            self.output("      ✗ Could not extract argument name from error")
            return False
        
        unexpected_arg = arg_match.group(1)
        self.output(f"      Found unexpected argument: '{unexpected_arg}'")
        
        # Extract the class/function name
        class_match = re.search(r"(\w+)\.__init__\(\)", combined)
        target_class = class_match.group(1) if class_match else None
        
        if target_class:
            self.output(f"      Target class: {target_class}")
        
        # Strategy 1: Find where the class is defined and add the parameter
        files_read = diagnosis.get("files_read", {})
        
        for path, content in files_read.items():
            lines = content.split('\n')
            
            # Look for the class definition
            for i, line in enumerate(lines):
                # Check if this is the __init__ method of the target class
                if "def __init__(" in line:
                    # Check if the unexpected arg is missing from signature
                    if unexpected_arg not in line:
                        self.output(f"      Found __init__ at line {i+1} missing '{unexpected_arg}'")
                        
                        # Find a good place to insert the parameter
                        # Look for the closing ) of the signature
                        signature_start = i
                        signature_lines = [line]
                        
                        # Handle multi-line signatures
                        current_line = i
                        while ')' not in lines[current_line] and ':' not in lines[current_line]:
                            current_line += 1
                            if current_line < len(lines):
                                signature_lines.append(lines[current_line])
                        
                        # Build the new parameter to add
                        # Use a sensible default based on arg name
                        if unexpected_arg in ('fps', 'target_fps', 'frame_rate'):
                            default_value = "60"
                        elif unexpected_arg in ('width', 'height', 'size'):
                            default_value = "800"
                        elif unexpected_arg.endswith('_path') or unexpected_arg.endswith('_dir') or unexpected_arg.endswith('_root'):
                            default_value = "None"
                        elif unexpected_arg.startswith('is_') or unexpected_arg.startswith('has_') or unexpected_arg.startswith('enable_'):
                            default_value = "False"
                        else:
                            default_value = "None"
                        
                        # Read the actual file
                        result = self.toolkit.read_file(path=path)
                        if not result.success:
                            continue
                        
                        actual_lines = result.result.split('\n')
                        
                        # Find the __init__ line in actual file
                        for actual_i, actual_line in enumerate(actual_lines):
                            if "def __init__(self" in actual_line and unexpected_arg not in actual_line:
                                # Add the parameter
                                # Find the closing paren or last param
                                if ')' in actual_line and ':' in actual_line:
                                    # Single-line signature: def __init__(self, ...):
                                    close_paren = actual_line.rfind(')')
                                    # Check if there are existing params
                                    if actual_line[close_paren-1] == '(':
                                        # Empty: (self)
                                        new_line = actual_line[:close_paren] + f", {unexpected_arg}={default_value}" + actual_line[close_paren:]
                                    else:
                                        # Has params: (self, x, y)
                                        new_line = actual_line[:close_paren] + f", {unexpected_arg}={default_value}" + actual_line[close_paren:]
                                    
                                    fix_result = self.toolkit.replace_line(
                                        path=path,
                                        line_number=actual_i + 1,
                                        new_content=new_line
                                    )
                                    
                                    if fix_result.success:
                                        self.output(f"      ✓ Added '{unexpected_arg}={default_value}' to {target_class}.__init__")
                                        
                                        # Also add the instance variable assignment
                                        # Find the next line after __init__ that's indented code
                                        for j in range(actual_i + 1, min(actual_i + 20, len(actual_lines))):
                                            next_line = actual_lines[j]
                                            if next_line.strip() and not next_line.strip().startswith('"""') and not next_line.strip().startswith("'''"):
                                                # Get indentation
                                                indent = len(next_line) - len(next_line.lstrip())
                                                indent_str = ' ' * indent
                                                
                                                # Insert instance variable
                                                self.toolkit.insert_line(
                                                    path=path,
                                                    after_line=j,
                                                    content=f"{indent_str}self.{unexpected_arg} = {unexpected_arg}"
                                                )
                                                self.output(f"      ✓ Added self.{unexpected_arg} = {unexpected_arg}")
                                                break
                                        
                                        return True
        
        self.output("      ✗ Could not apply automatic fix for unexpected keyword argument")
        return False

    def _fix_import_error(self, diagnosis: Dict) -> bool:
        """
        Fix import errors by analyzing module structure and dependencies.
        """
        import re

        self.output("      Scanning for syntax errors in project...")

        # PROACTIVELY check ALL Python files in game/ directory for syntax errors
        # This is more reliable than depending on diagnosis
        game_dir = self.project_dir / "game"
        if game_dir.exists():
            for py_file in game_dir.glob("**/*.py"):
                rel_path = str(py_file.relative_to(self.project_dir))
                result = self.toolkit.validate_syntax(path=rel_path)
                if not result.success:
                    self.output(f"      ✗ Syntax error in: {rel_path}")
                    # Get the actual error details from metadata (contains IndentationError, etc.)
                    error_msg = result.error or ""
                    if result.metadata and result.metadata.get("stderr"):
                        error_msg = result.metadata["stderr"]
                    if self._fix_syntax_error_in_file(rel_path, error_msg):
                        self.output(f"      ✓ Fixed syntax error in {rel_path}")
                        return True

        # Also check files mentioned in diagnosis
        errors = diagnosis.get("errors", [])
        for error in errors:
            if "syntax error" in error.lower():
                file_match = re.search(r'in (\S+\.py)', error)
                if file_match:
                    error_file = file_match.group(1)
                    self.output(f"      Found syntax error in diagnosis: {error_file}")
                    if self._fix_syntax_error_in_file(error_file, error):
                        return True

        # Check files_read from diagnosis
        files_read = diagnosis.get("files_read", {})
        for file_path in files_read.keys():
            if file_path.endswith('.py'):
                result = self.toolkit.validate_syntax(path=file_path)
                if not result.success:
                    self.output(f"      Found syntax error in: {file_path}")
                    # Get actual error from metadata
                    error_msg = result.error or ""
                    if result.metadata and result.metadata.get("stderr"):
                        error_msg = result.metadata["stderr"]
                    if self._fix_syntax_error_in_file(file_path, error_msg):
                        return True

        issue = self.issue  # Keep original case
        issue_lower = issue.lower()
        error_lower = (self.error_trace or "").lower()

        # Extract module/class name from issue (preserve case)
        # Pattern: "Could not import X" or "Failed to import X from Y" or "ImportError: cannot import name 'X'"
        
        # 1. Try "cannot import name 'X'" (most common)
        import_match = re.search(r"cannot import name ['\"](\w+)['\"]", issue, re.IGNORECASE)
        if not import_match:
             # 2. Try generic "from X import Y" pattern (very common in manual reports)
             import_match = re.search(r"from\s+[\w.]+\s+import\s+(\w+)", issue, re.IGNORECASE)
        if not import_match:
             # 3. Try generic "import X"
             import_match = re.search(r'(?:could not|failed to|cannot) import (\w+)', issue, re.IGNORECASE)
             
        # Extract source module
        # Pattern: "from Y import X" or "from 'Y'"
        from_match = re.search(r'from ([\w.]+)', issue)  # Case sensitive for module paths usually
        
        # Also check error trace if issue doesn't have it
        if not import_match and self.error_trace:
             # Try traceback-style: "from core.interfaces import AuditPlugin\nImportError: cannot import name 'AuditPlugin'"
             import_match = re.search(r"cannot import name ['\"](\w+)['\"]", self.error_trace, re.IGNORECASE)
             if not import_match:
                  # Try to find the import line in the traceback itself
                  import_match = re.search(r"from\s+[\w.]+\s+import\s+(\w+)", self.error_trace, re.IGNORECASE)

             if not from_match:
                  from_match = re.search(r"from ([\w.]+)", self.error_trace)

        if import_match:
            class_name = import_match.group(1)
            module_path = from_match.group(1).rstrip('.') if from_match else None  # Remove trailing dot
            self.output(f"      Looking for: {class_name}" + (f" in {module_path}" if module_path else ""))
        else:
            self.output("      Could not parse import target from issue or trace")
            return False

        # Convert module path to file path
        if module_path:
            file_path = module_path.replace('.', '/') + '.py'
            full_path = self.project_dir / file_path

            if not full_path.exists():
                # Try without the first component (might be package name)
                parts = module_path.split('.')
                if len(parts) > 1:
                    alt_path = '/'.join(parts[1:]) + '.py'
                    alt_full = self.project_dir / alt_path
                    if alt_full.exists():
                        file_path = alt_path
                        full_path = alt_full

            self.output(f"      Checking file: {file_path}")

            if not full_path.exists():
                self.output(f"      ✗ File not found: {file_path}")
                # Check if the module directory exists but file doesn't
                dir_path = full_path.parent
                if dir_path.exists():
                    self.output(f"      Directory exists: {dir_path}")
                    # List files in directory
                    files = list(dir_path.glob('*.py'))
                    if files:
                        self.output(f"      Available files: {[f.name for f in files[:5]]}")
                return False

            # Check syntax of the target file
            syntax_result = self.toolkit.validate_syntax(path=file_path)
            if not syntax_result.success:
                self.output(f"      ✗ Syntax error in {file_path}: {syntax_result.error}")
                # Get actual error from metadata (contains IndentationError, etc.)
                error_msg = syntax_result.error or ""
                if syntax_result.metadata and syntax_result.metadata.get("stderr"):
                    error_msg = syntax_result.metadata["stderr"]
                # Try to fix the syntax error
                return self._fix_syntax_error_in_file(file_path, error_msg)

            # Read the file and check if the class/function exists
            try:
                with open(full_path, 'r') as f:
                    content = f.read()

                # Check if the class/function is defined
                class_pattern = rf'\bclass\s+{class_name}\b'
                func_pattern = rf'\bdef\s+{class_name}\b'

                if re.search(class_pattern, content):
                    self.output(f"      ✓ Found class {class_name} in {file_path}")
                elif re.search(func_pattern, content):
                    self.output(f"      ✓ Found function {class_name} in {file_path}")
                else:
                    self.output(f"      ✗ {class_name} not defined in {file_path}")
                    
                    # NEW: Search whole project for class/def
                    self.output(f"      Searching project for {class_name} definition...")
                    search_result = self.toolkit.grep_search(pattern=rf'\b(class|def)\s+{class_name}\b', regex=True)
                    
                    if search_result.success and search_result.results:
                        # Found it somewhere else!
                        match = search_result.results[0]
                        new_path = match.path
                        self.output(f"      ✓ Found {class_name} in {new_path}")
                        
                        # Correct the import in the referring file
                        # We need to find which file was referring to it
                        # For now, let's assume it's the file in the error trace
                        error_file = None
                        if self.error_trace:
                             file_match = re.search(r'file ["\']?([^"\':\s]+\.py)["\']?', self.error_trace.lower())
                             if file_match:
                                  error_file = file_match.group(1)
                        
                        if error_file:
                             self.output(f"      Fixing import in {error_file}...")
                             # Calculate new module path
                             new_module = new_path.replace('.py', '').replace('/', '.')
                             if new_module.startswith('.'): new_module = new_module[1:]
                             
                             # Use edit_file to replace the old import
                             # Look for the old import line: from X import AuditPlugin
                             with open(self.project_dir / error_file, 'r') as f:
                                  referred_content = f.read()
                             
                             # Case 1: from core.interfaces import AuditPlugin
                             old_pattern = rf'from\s+[\w.]+\s+import\s+.*?\b{class_name}\b.*'
                             new_line = f"from {new_module} import {class_name}"
                             
                             match = re.search(old_pattern, referred_content)
                             if match:
                                  old_line = match.group(0)
                                  new_content = referred_content.replace(old_line, new_line)
                                  with open(self.project_dir / error_file, 'w') as f:
                                       f.write(new_content)
                                  self.output(f"      ✓ Updated import: {old_line} -> {new_line}")
                                  self.context.files_modified.append(error_file)
                                  return True
                             else:
                                  self.output(f"      ✗ Could not find import line to replace in {error_file}")
                                  
                    return False

                # Check if there are import errors within this file
                # Look for imports that might be failing
                imports = re.findall(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', content, re.MULTILINE)
                for from_module, import_names in imports:
                    if from_module:
                        # Check if the imported module exists
                        imported_path = from_module.replace('.', '/') + '.py'
                        imported_full = self.project_dir / imported_path
                        if not imported_full.exists():
                            # Try relative import
                            rel_path = full_path.parent / (from_module.split('.')[-1] + '.py')
                            if not rel_path.exists():
                                self.output(f"      ⚠ Missing dependency: {from_module}")

            except Exception as e:
                self.output(f"      Error reading file: {e}")
                return False

        # Check if it's a missing package issue
        if "no module named" in error_lower:
            module_match = re.search(r"no module named ['\"]?(\w+)", error_lower)
            if module_match:
                missing_module = module_match.group(1)
                self.output(f"      Missing module: {missing_module}")

                # Resolve module to package name (v2.2)
                lang = self.dependency_resolver.detect_language(self.project_dir)
                resolved = self.dependency_resolver.resolve_packages([missing_module], language=lang)
                missing_pkg = resolved.get(missing_module, missing_module)

                if missing_pkg != missing_module:
                    self.output(f"      Resolved module {missing_module} to package {missing_pkg}")

                result = self.toolkit.pip_install(packages=[missing_pkg])
                if result.success:
                    self.output(f"      ✓ Installed {missing_pkg}")
                    # Also update requirements.txt so it's persistent
                    self._fix_requirements_file({})
                    return True
                else:
                    self.output(f"      ⚠ pip install for {missing_pkg} failed. Checking system dependencies...")
                    error_out = ""
                    if hasattr(result, 'error') and result.error:
                        error_out = result.error
                    elif hasattr(result, 'metadata') and result.metadata.get('stderr'):
                        error_out = result.metadata['stderr']
                    
                    system_info = self.dependency_resolver.resolve_system_dependencies(error_out)
                    commands = system_info.get("commands", [])
                    queries = system_info.get("search_queries", [])
                    
                    if commands:
                        self.output("      💡 Detected missing system libraries. Suggestion:")
                        for fix in commands:
                            self.output(f"         {fix}")
                    
                    if queries:
                        self.output("      🔍 Performing internet research to verify current package versions...")
                        search_results = []
                        for query in queries[:2]:
                            res = self.toolkit.search_web(query)
                            if res.success:
                                search_results.append(str(res.result))
                        
                        if search_results:
                            self.output("      🧠 Analyzing research results...")
                            new_error_out = f"{error_out}\n\nRESEARCH RESULTS:\n" + "\n".join(search_results)
                            new_info = self.dependency_resolver.resolve_system_dependencies(new_error_out)
                            new_commands = new_info.get("commands", [])
                            if new_commands:
                                self.output("      ✅ Confirmed system fix after research:")
                                for fix in new_commands:
                                    self.output(f"         {fix}")
                    return False

        self.output("      Could not auto-fix this import error")
        return False

    def _fix_unexpected_keyword_argument(self, diagnosis: Dict) -> bool:
        """
        Fix 'unexpected keyword argument' errors.

        These happen when code calls a function/class with an argument
        it doesn't accept. Fix by either:
        1. Removing the argument from the call, OR
        2. Adding the argument to the function signature
        """
        import re

        error_trace = self.error_trace or ""
        issue = self.issue

        # Extract the class/function name and the unexpected argument
        # Pattern: ClassName.__init__() got an unexpected keyword argument 'argname'
        match = re.search(
            r"(\w+)\.__init__\(\) got an unexpected keyword argument ['\"](\w+)['\"]",
            error_trace + " " + issue
        )

        if not match:
            # Try alternative pattern
            match = re.search(
                r"(\w+)\(\) got an unexpected keyword argument ['\"](\w+)['\"]",
                error_trace + " " + issue
            )

        if not match:
            self.output("      Could not parse class/argument from error")
            return False

        class_name = match.group(1)
        bad_arg = match.group(2)
        self.output(f"      Class: {class_name}, unexpected arg: '{bad_arg}'")

        # Strategy 1: Find where the class is instantiated with the bad arg and remove it
        files_read = diagnosis.get("files_read", {})
        search_results = diagnosis.get("search_results", [])

        # Look for instantiation pattern: ClassName(...bad_arg=...)
        instantiation_pattern = rf'{class_name}\s*\([^)]*{bad_arg}\s*='

        for file_path, content in files_read.items():
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if re.search(instantiation_pattern, line):
                    self.output(f"      Found instantiation at {file_path}:{i}")
                    self.output(f"         {line.strip()[:80]}")

                    # Try to remove the bad argument from the call
                    # Pattern: , bad_arg=value OR bad_arg=value,
                    fixed_line = line

                    # Remove ", bad_arg=value" or "bad_arg=value, "
                    # Handle: , fps=60 or fps=60, or fps=self.fps
                    patterns_to_remove = [
                        rf',\s*{bad_arg}\s*=\s*[^,)]+',  # , fps=60
                        rf'{bad_arg}\s*=\s*[^,)]+\s*,',  # fps=60,
                        rf'{bad_arg}\s*=\s*[^,)]+',      # fps=60 (last arg)
                    ]

                    for pattern in patterns_to_remove:
                        new_line = re.sub(pattern, '', fixed_line)
                        if new_line != fixed_line:
                            fixed_line = new_line
                            break

                    if fixed_line != line:
                        # Clean up any double commas or trailing commas before )
                        fixed_line = re.sub(r',\s*,', ',', fixed_line)
                        fixed_line = re.sub(r',\s*\)', ')', fixed_line)
                        fixed_line = re.sub(r'\(\s*,', '(', fixed_line)

                        self.output(f"      Fixed: {fixed_line.strip()[:80]}")

                        # Apply the fix using validated line patch
                        success = self._apply_line_patch(
                            file_path=file_path,
                            line_number=i,
                            new_content=fixed_line.rstrip('\n'),
                            validate_syntax=True
                        )

                        if success:
                            self.output(f"      ✓ Removed '{bad_arg}' argument from {file_path}:{i}")
                            return True

        # Strategy 2: Add the argument to the class __init__
        # Find the class definition
        class_def_pattern = rf'class\s+{class_name}\s*[:\(]'

        for file_path, content in files_read.items():
            if re.search(class_def_pattern, content):
                self.output(f"      Found class definition in {file_path}")

                # Find __init__ method
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if 'def __init__' in line:
                        self.output(f"      Found __init__ at line {i+1}")

                        # Add the argument to __init__
                        # Pattern: def __init__(self, ...):
                        if ')' in line and ':' in line:
                            # Insert before the closing )
                            paren_pos = line.rfind(')')
                            colon_pos = line.find(':', paren_pos)

                            if paren_pos > 0:
                                # Check if there are existing args
                                has_other_args = ',' in line[:paren_pos] or line[:paren_pos].count('(') > 0

                                if has_other_args:
                                    new_arg = f", {bad_arg}=None"
                                else:
                                    new_arg = f"{bad_arg}=None"

                                fixed_line = line[:paren_pos] + new_arg + line[paren_pos:]
                                self.output(f"      Adding '{bad_arg}' to __init__: {fixed_line.strip()[:80]}")

                                success = self._apply_line_patch(
                                    file_path=file_path,
                                    line_number=i + 1,
                                    new_content=fixed_line.rstrip('\n'),
                                    validate_syntax=True
                                )

                                if success:
                                    self.output(f"      ✓ Added '{bad_arg}' parameter to {class_name}.__init__")
                                    return True
                        break

        self.output("      Could not auto-fix unexpected keyword argument")
        return False

    def _fix_missing_attribute(self, diagnosis: Dict) -> bool:
        """
        Fix 'object has no attribute' errors.

        Common causes:
        1. Method/attribute is expected but not defined in the class
        2. Typo in attribute name
        3. Method should be called but missing from class
        """
        import re

        error_trace = self.error_trace or ""
        issue = self.issue
        combined = error_trace + " " + issue

        # Extract class name and missing attribute
        # Pattern: 'ClassName' object has no attribute 'attr_name'
        match = re.search(
            r"['\"](\w+)['\"] object has no attribute ['\"](\w+)['\"]",
            combined
        )

        if not match:
            self.output("      Could not parse class/attribute from error")
            return False

        class_name = match.group(1)
        missing_attr = match.group(2)
        self.output(f"      Class: {class_name}, missing attribute: '{missing_attr}'")

        # Find the class definition
        files_read = diagnosis.get("files_read", {})
        class_def_pattern = rf'class\s+{class_name}\s*[:\(]'

        for file_path, content in files_read.items():
            if not re.search(class_def_pattern, content):
                continue

            self.output(f"      Found class in {file_path}")
            lines = content.split('\n')

            # Check if it's a method that should be defined
            if missing_attr in ('setup', 'init', 'initialize', 'start', 'run', 'update', 'draw', 'render'):
                # Common lifecycle methods - might need to be added
                self.output(f"      '{missing_attr}' looks like a lifecycle method")

                # Find the class body and check what's there
                class_line = None
                class_indent = 0
                for i, line in enumerate(lines):
                    if re.search(class_def_pattern, line):
                        class_line = i
                        class_indent = len(line) - len(line.lstrip())
                        break

                if class_line is not None:
                    # Look for __init__ to add the method after it
                    init_end = None
                    method_indent = class_indent + 4

                    for i in range(class_line + 1, len(lines)):
                        line = lines[i]
                        if line.strip().startswith('def __init__'):
                            # Find end of __init__
                            for j in range(i + 1, len(lines)):
                                next_line = lines[j]
                                if next_line.strip() and not next_line.strip().startswith('#'):
                                    next_indent = len(next_line) - len(next_line.lstrip())
                                    if next_indent <= method_indent and next_line.strip().startswith('def '):
                                        init_end = j
                                        break
                            if init_end is None:
                                init_end = i + 5  # Reasonable guess
                            break

                    if init_end:
                        # Add a stub method
                        stub = f"\n{' ' * method_indent}def {missing_attr}(self):\n{' ' * (method_indent + 4)}\"\"\"Auto-generated stub for {missing_attr}.\"\"\"\n{' ' * (method_indent + 4)}pass\n"

                        # Insert after __init__
                        new_lines = lines[:init_end] + [stub] + lines[init_end:]
                        new_content = '\n'.join(new_lines)

                        # Write and validate
                        full_path = self.project_dir / file_path
                        try:
                            original = full_path.read_text()
                            full_path.write_text(new_content)

                            # Validate syntax
                            syntax_result = self.toolkit.validate_syntax(path=file_path)
                            if syntax_result.success:
                                self.output(f"      ✓ Added stub method '{missing_attr}' to {class_name}")
                                if file_path not in self.context.files_modified:
                                    self.context.files_modified.append(file_path)
                                return True
                            else:
                                # Rollback
                                full_path.write_text(original)
                                self.output(f"      ✗ Adding method caused syntax error, rolled back")
                        except Exception as e:
                            self.output(f"      Error: {e}")

            # Check if it might be a typo - look for similar attributes
            existing_attrs = re.findall(r'self\.(\w+)', content)
            existing_methods = re.findall(r'def\s+(\w+)\s*\(', content)
            all_attrs = set(existing_attrs + existing_methods)

            # Find similar names
            from difflib import get_close_matches
            similar = get_close_matches(missing_attr, all_attrs, n=3, cutoff=0.6)
            if similar:
                self.output(f"      Similar attributes found: {similar}")
                self.output(f"      (This might be a typo - '{missing_attr}' vs '{similar[0]}')")

        self.output("      Could not auto-fix missing attribute")
        return False

    def _fix_name_error(self, diagnosis: Dict) -> bool:
        """
        Fix NameError: name 'X' is not defined.

        This usually means a missing import. The fix:
        1. Extract the undefined name from the error
        2. Search the project for where that name is defined
        3. Add an import statement to the file with the error
        """
        import re

        self.output("      Analyzing NameError...")

        error_trace = self.error_trace or ""

        # Extract the undefined name from ORIGINAL trace (preserve case!)
        # Pattern: name 'AuditPlugin' is not defined
        name_match = re.search(r"name ['\"](\w+)['\"] is not defined", error_trace, re.IGNORECASE)
        if not name_match:
            # Try issue text as fallback
            name_match = re.search(r"name ['\"](\w+)['\"] is not defined", self.issue, re.IGNORECASE)
        if not name_match:
            self.output("      Could not extract undefined name")
            return False

        undefined_name = name_match.group(1)  # Preserves original case (AuditPlugin not auditplugin)
        self.output(f"      Undefined name: '{undefined_name}'")

        # Extract the file that has the error - use the LAST file in traceback
        # (the first files are just the import chain, the last is where the error occurs)
        file_matches = re.findall(r'File ["\']([^"\']+\.py)["\'],\s*line\s*(\d+)', error_trace)
        if not file_matches:
            self.output("      Could not find error file location")
            return False

        # Use the LAST match (actual error location, not import chain)
        error_file, error_line_str = file_matches[-1]
        error_line = int(error_line_str)
        self.output(f"      Error in: {error_file}:{error_line}")

        # Make path relative if needed
        error_path = Path(error_file)
        if error_path.is_absolute():
            try:
                error_path = error_path.relative_to(self.project_dir)
            except ValueError:
                pass

        full_error_path = self.project_dir / error_path

        # Search for where the undefined name is defined
        self.output(f"      Searching for definition of '{undefined_name}'...")

        definition_file = None
        definition_module = None

        # Common patterns for class/function definitions
        definition_patterns = [
            rf'class\s+{undefined_name}\s*[\(:]',
            rf'def\s+{undefined_name}\s*\(',
            rf'{undefined_name}\s*=',
        ]

        for py_file in self.project_dir.rglob("*.py"):
            if "venv" in str(py_file) or "__pycache__" in str(py_file):
                continue
            if py_file == full_error_path:
                continue  # Skip the file with the error

            try:
                content = py_file.read_text()
                for pattern in definition_patterns:
                    if re.search(pattern, content):
                        # Found the definition
                        definition_file = py_file
                        # Calculate module path
                        try:
                            rel_path = py_file.relative_to(self.project_dir)
                            # Convert path to module: core/interfaces.py -> core.interfaces
                            module_parts = list(rel_path.parts)
                            if module_parts[-1].endswith('.py'):
                                module_parts[-1] = module_parts[-1][:-3]
                            if module_parts[-1] == '__init__':
                                module_parts = module_parts[:-1]
                            definition_module = '.'.join(module_parts)
                        except ValueError:
                            pass
                        break
            except Exception:
                continue

            if definition_file:
                break

        if not definition_file or not definition_module:
            self.output(f"      Could not find definition of '{undefined_name}'")
            return False

        self.output(f"      Found '{undefined_name}' in {definition_module}")

        # Read the error file and add the import
        try:
            with open(full_error_path, 'r') as f:
                lines = f.readlines()
        except Exception as e:
            self.output(f"      Could not read {error_file}: {e}")
            return False

        # Build the import statement
        import_stmt = f"from {definition_module} import {undefined_name}\n"

        # Check if import already exists
        content = ''.join(lines)
        if import_stmt.strip() in content:
            self.output(f"      Import already exists (might be a circular import issue)")
            return False

        # Find the best place to insert the import (after existing imports)
        insert_line = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                insert_line = i + 1
            elif stripped and not stripped.startswith('#') and not stripped.startswith('"""') and insert_line > 0:
                # Found non-import, non-comment line after imports
                break

        # Insert the import
        lines.insert(insert_line, import_stmt)

        # Write back
        try:
            with open(full_error_path, 'w') as f:
                f.writelines(lines)
            self.output(f"      ✓ Added import: {import_stmt.strip()}")
            self.context.files_modified.append(str(error_path))
            return True
        except Exception as e:
            self.output(f"      Failed to write fix: {e}")
            return False

    def _fix_syntax_error_in_file(self, file_path: str, error_msg: str = "") -> bool:
        """Fix syntax error in a specific file."""
        import re
        import subprocess

        full_path = self.project_dir / file_path

        if not full_path.exists():
            self.output(f"      File not found: {file_path}")
            return False

        # If error_msg doesn't have line number, get it by running Python syntax check
        line_match = re.search(r'line (\d+)', error_msg)
        if not line_match:
            # Run Python to get actual syntax error
            try:
                result = subprocess.run(
                    ['python', '-m', 'py_compile', str(full_path)],
                    capture_output=True, text=True, timeout=10
                )
                error_msg = result.stderr
                self.output(f"      Syntax check: {error_msg[:100]}...")
                line_match = re.search(r'line (\d+)', error_msg)
            except Exception as e:
                self.output(f"      Could not check syntax: {e}")
                return False

        if not line_match:
            self.output(f"      Could not find line number in error")
            return False

        error_line = int(line_match.group(1))
        self.output(f"      Syntax error at line {error_line}")

        try:
            with open(full_path, 'r') as f:
                lines = f.readlines()
        except Exception as e:
            self.output(f"      Could not read file: {e}")
            return False

        # Create error trace for the syntax error handler
        original_trace = self.error_trace
        self.error_trace = f'File "{full_path}", line {error_line}\n{error_msg}'

        # Try to fix it
        result = self._fix_syntax_error({})

        # Restore original trace
        self.error_trace = original_trace

        return result

    def _fix_syntax_error(self, diagnosis: Dict) -> bool:
        """
        Fix common syntax errors detected in the error trace.
        """
        import re
        import subprocess

        error_trace = self.error_trace or ""

        # Extract file path and line number from error trace
        # Pattern: File "path/to/file.py", line N
        file_match = re.search(r'File ["\']([^"\']+)["\'],\s*line\s*(\d+)', error_trace)

        error_file = None
        error_line = None

        if file_match:
            error_file = file_match.group(1)
            error_line = int(file_match.group(2))

            # Verify this file actually has a syntax error (not just an import that fails)
            # If py_compile succeeds on this file, the error is in an imported module
            try:
                verify_path = self.project_dir / error_file if not Path(error_file).is_absolute() else Path(error_file)
                if verify_path.exists():
                    verify_result = subprocess.run(
                        ['python', '-m', 'py_compile', str(verify_path)],
                        capture_output=True, text=True, timeout=10
                    )
                    if verify_result.returncode == 0:
                        # This file is fine, error is in an import - need to scan
                        self.output(f"      {error_file} compiles OK, error is in imported module...")
                        error_file = None
                        error_line = None
            except Exception:
                pass

        if not error_file:
            # Fallback: Find files with syntax errors by scanning ALL Python files
            self.output("      Scanning all Python files for syntax errors...")

            # ALWAYS scan all Python files - the error might be in any file
            files_to_check = [str(f.relative_to(self.project_dir))
                             for f in self.project_dir.rglob("*.py")
                             if "venv" not in str(f) and "__pycache__" not in str(f)]

            # Run syntax check on each file
            for file_path in files_to_check:
                full_path = self.project_dir / file_path
                if not full_path.exists() or not str(full_path).endswith('.py'):
                    continue
                try:
                    result = subprocess.run(
                        ['python', '-m', 'py_compile', str(full_path)],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        # Found a file with syntax error
                        check_match = re.search(r'line (\d+)', result.stderr)
                        if check_match:
                            error_file = str(full_path)
                            error_line = int(check_match.group(1))
                            error_trace = result.stderr  # Use the actual error message
                            self.output(f"      Found syntax error in {file_path}")
                            break
                except Exception:
                    continue

        if not error_file or not error_line:
            self.output("      Could not locate syntax error")
            return False

        error_file_orig = error_file  # Keep original for later
        error_line = int(error_line)

        self.output(f"      Error at: {error_file}:{error_line}")

        # Make path relative if it's absolute and in project
        error_path = Path(error_file)
        if error_path.is_absolute():
            try:
                error_path = error_path.relative_to(self.project_dir)
            except ValueError:
                pass

        file_path = self.project_dir / error_path

        if not file_path.exists():
            self.output(f"      File not found: {file_path}")
            return False

        # Read the file
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
        except Exception as e:
            self.output(f"      Could not read file: {e}")
            return False

        # ─────────────────────────────────────────────────────
        # UNTERMINATED TRIPLE-QUOTED STRING
        # ─────────────────────────────────────────────────────
        if "unterminated triple-quoted string" in error_trace.lower():
            self.output("      Detected: Unterminated triple-quoted string")
            fixed = self._fix_unterminated_triple_quote(lines, error_line, file_path)
            if fixed:
                return True

        # ─────────────────────────────────────────────────────
        # UNTERMINATED STRING LITERAL
        # ─────────────────────────────────────────────────────
        if "unterminated string" in error_trace.lower():
            self.output("      Detected: Unterminated string literal")
            fixed = self._fix_unterminated_string(lines, error_line, file_path)
            if fixed:
                return True

        # ─────────────────────────────────────────────────────
        # UNEXPECTED EOF / UNCLOSED BRACKETS
        # ─────────────────────────────────────────────────────
        # Detect various forms of unclosed bracket errors:
        # - "unexpected eof" / "unexpected end of file"
        # - "'[' was never closed" / "'(' was never closed" / "'{' was never closed"
        unclosed_patterns = [
            "unexpected eof",
            "unexpected end of file",
            "was never closed",
            "unclosed",
            "expected ']'",
            "expected ')'",
            "expected '}'",
        ]
        if any(p in error_trace.lower() for p in unclosed_patterns):
            self.output("      Detected: Unclosed bracket/EOF")
            fixed = self._fix_unexpected_eof(lines, error_line, file_path)
            if fixed:
                return True

        # ─────────────────────────────────────────────────────
        # MISSING COLON
        # ─────────────────────────────────────────────────────
        if "expected ':'" in error_trace.lower() or "missing ':'" in error_trace.lower():
            self.output("      Detected: Missing colon")
            fixed = self._fix_missing_colon(lines, error_line, file_path)
            if fixed:
                return True

        # ─────────────────────────────────────────────────────
        # INDENTATION ERROR
        # ─────────────────────────────────────────────────────
        if "indentationerror" in error_trace.lower() or "indentation" in error_trace.lower():
            self.output("      Detected: Indentation error")
            fixed = self._fix_indentation_error(lines, error_line, file_path)
            if fixed:
                return True

        self.output("      Could not auto-fix this syntax error type")
        return False

    def _fix_indentation_error(self, lines: list, error_line: int, file_path: Path) -> bool:
        """
        Fix indentation errors, especially "unindent does not match any outer indentation level".

        Strategy: Try different indentation levels until syntax is valid.
        This is more robust than trying to analyze the indent stack.
        """
        import subprocess

        if error_line > len(lines) or error_line < 1:
            return False

        # Get the problematic line
        problem_line = lines[error_line - 1]
        problem_stripped = problem_line.lstrip()
        current_indent = len(problem_line) - len(problem_line.lstrip())

        if not problem_stripped:
            # Empty line or whitespace only
            if "expected an indented block" in self.error_trace.lower():
                 # Special case: line after colon is empty, but we need an indent
                 # Try inserting a 'pass'
                 self.output(f"      Special case: Inserting 'pass' at line {error_line}")
                 # Detect indent unit and prev indent
                 indent_unit = 4
                 for line in lines[:error_line]:
                     stripped = line.lstrip()
                     if stripped and not stripped.startswith('#'):
                         indent = len(line) - len(stripped)
                         if indent > 0: indent_unit = indent; break
                 
                 # Look at previous line
                 prev_indent = 0
                 for i in range(error_line - 2, -1, -1):
                    if lines[i].strip():
                        prev_indent = len(lines[i]) - len(lines[i].lstrip())
                        break
                 
                 lines[error_line - 1 ] = ' ' * (prev_indent + indent_unit) + "pass\n"
                 # Test if this works
                 with open(file_path, 'w') as f: f.writelines(lines)
                 if subprocess.run(['python', '-m', 'py_compile', str(file_path)], capture_output=True).returncode == 0:
                      return True
                 # Fallback to removal if pass didn't help (but pass usually helps)
            
            self.output(f"      Removing empty/whitespace line {error_line}")
            del lines[error_line - 1]
        else:
            # Get the base indent unit (detect if file uses 2 or 4 spaces)
            indent_unit = 4  # default
            for line in lines[:error_line]:
                stripped = line.lstrip()
                if stripped and not stripped.startswith('#'):
                    indent = len(line) - len(stripped)
                    if indent > 0:
                        # Find the smallest non-zero indent
                        if indent < indent_unit:
                            indent_unit = indent
                        break

            # Look at the previous non-empty line to determine context
            prev_indent = 0
            prev_ends_with_colon = False
            for i in range(error_line - 2, -1, -1):
                prev_line = lines[i]
                prev_stripped = prev_line.strip()
                if prev_stripped and not prev_stripped.startswith('#'):
                    prev_indent = len(prev_line) - len(prev_line.lstrip())
                    prev_ends_with_colon = prev_stripped.endswith(':')
                    break

            # Build list of candidate indents to try
            candidates = []

            # If previous line ends with :, try indented
            if prev_ends_with_colon:
                candidates.append(prev_indent + indent_unit)

            # Try same indent as previous line
            candidates.append(prev_indent)

            # Try dedenting (for else/elif/except/finally)
            dedent_keywords = ('else:', 'elif ', 'except:', 'except ', 'finally:', 'case ')
            if any(problem_stripped.startswith(kw) for kw in dedent_keywords):
                # Find matching if/try/match
                for i in range(error_line - 2, -1, -1):
                    prev = lines[i].strip()
                    if prev.startswith(('if ', 'try:', 'match ', 'for ', 'while ')):
                        match_indent = len(lines[i]) - len(lines[i].lstrip())
                        candidates.insert(0, match_indent)  # Prioritize this
                        break

            # Add standard multiples of indent_unit
            for mult in range(0, 8):
                candidates.append(mult * indent_unit)

            # Remove duplicates while preserving order
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)

            self.output(f"      Trying indent levels: {unique_candidates[:6]}...")

            # Try each candidate until syntax is valid
            original_lines = lines.copy()
            for candidate_indent in unique_candidates:
                if candidate_indent == current_indent:
                    continue  # Skip current (already broken)

                # Apply candidate indent
                lines[error_line - 1] = ' ' * candidate_indent + problem_stripped + '\n'

                # Write and test
                try:
                    with open(file_path, 'w') as f:
                        f.writelines(lines)

                    result = subprocess.run(
                        ['python', '-m', 'py_compile', str(file_path)],
                        capture_output=True, text=True, timeout=10
                    )

                    if result.returncode == 0:
                        self.output(f"      Line {error_line}: indent {current_indent} -> {candidate_indent} ✓")
                        return True  # Success! Don't restore, keep the fix
                    else:
                        # Check if it's a DIFFERENT error (progress!)
                        if f"line {error_line}" not in result.stderr:
                            self.output(f"      Line {error_line}: indent {current_indent} -> {candidate_indent} (fixed this line, but other errors exist)")
                            return True  # This line is fixed, other issues remain

                except Exception as e:
                    self.output(f"      Error testing indent {candidate_indent}: {e}")

                # Restore for next attempt
                lines[:] = original_lines.copy()

            self.output(f"      Could not find valid indent for line {error_line}")
            # Restore original
            lines[:] = original_lines
            return False

        # For empty line removal case, write and verify
        import subprocess
        try:
            with open(file_path, 'w') as f:
                f.writelines(lines)

            result = subprocess.run(
                ['python', '-m', 'py_compile', str(file_path)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                self.output(f"      ✓ Removed empty line, syntax now valid")
                if str(file_path) not in self.context.files_modified:
                    try:
                        rel_path = file_path.relative_to(self.project_dir)
                        self.context.files_modified.append(str(rel_path))
                    except:
                        self.context.files_modified.append(str(file_path))
                return True
            else:
                self.output(f"      ⚠ Still has errors after removing line")
                return False
        except Exception as e:
            self.output(f"      Failed to write fix: {e}")
            return False

    def _fix_unterminated_triple_quote(self, lines: list, error_line: int, file_path: Path) -> bool:
        """Fix unterminated triple-quoted string."""
        # The error line shows where Python detected the problem
        # We need to find where the triple-quote started and should end

        # Look backwards from error_line to find the opening """
        start_line = None
        quote_type = None

        for i in range(error_line - 1, -1, -1):
            line = lines[i]
            # Check for opening triple-quote that isn't closed on same line
            if '"""' in line:
                # Count occurrences - odd means unclosed
                count = line.count('"""')
                if count % 2 == 1:
                    start_line = i
                    quote_type = '"""'
                    break
            if "'''" in line:
                count = line.count("'''")
                if count % 2 == 1:
                    start_line = i
                    quote_type = "'''"
                    break

        if start_line is None:
            self.output("      Could not find opening triple-quote")
            return False

        self.output(f"      Found opening {quote_type} at line {start_line + 1}")

        # Strategy 1: Check if this looks like a docstring that should end quickly
        # Look for the next function/class definition or significant code
        end_line = None
        for i in range(start_line + 1, min(start_line + 50, len(lines))):
            line = lines[i].strip()
            # If we hit a def, class, or significant code without closing quote
            if line.startswith(('def ', 'class ', 'if ', 'for ', 'while ', 'return ', 'import ', 'from ')):
                # The quote should have ended before this
                end_line = i - 1
                break
            # If the line is just """ it might be trying to close but failed
            if line == '"""' or line == "'''":
                # This line exists but isn't being recognized - check if it matches
                if quote_type in lines[i]:
                    # The closing quote exists, there might be a different issue
                    self.output(f"      Found closing quote at line {i + 1}, checking for issues...")
                    break

        if end_line is None:
            # Look for where content suggests the docstring should end
            # Find the next blank line or code pattern after start
            for i in range(start_line + 1, min(start_line + 30, len(lines))):
                line = lines[i]
                stripped = line.strip()
                # If we see code patterns that shouldn't be in a docstring
                if stripped and not stripped.startswith('#'):
                    # Check if this looks like code (has =, (), etc.)
                    if '=' in stripped and not stripped.startswith(('Args', 'Returns', 'Raises', 'Example', 'Note')):
                        if not any(stripped.startswith(x) for x in ['"""', "'''"]):
                            end_line = i
                            break

        if end_line is None:
            end_line = min(start_line + 5, len(lines) - 1)

        # Insert closing triple-quote before the problematic line
        indent = len(lines[start_line]) - len(lines[start_line].lstrip())
        closing_line = ' ' * indent + quote_type + '\n'

        self.output(f"      Inserting closing {quote_type} at line {end_line + 1}")

        # Insert the closing quote
        lines.insert(end_line, closing_line)

        # Write the fixed file
        try:
            with open(file_path, 'w') as f:
                f.writelines(lines)
            self.output(f"      ✓ Fixed unterminated triple-quote in {file_path.name}")
            self.context.files_modified.append(str(file_path.relative_to(self.project_dir)))
            return True
        except Exception as e:
            self.output(f"      Failed to write fix: {e}")
            return False

    def _fix_unterminated_string(self, lines: list, error_line: int, file_path: Path) -> bool:
        """Fix unterminated string literal (single/double quotes)."""
        if error_line > len(lines):
            return False

        line = lines[error_line - 1]

        # Count quotes
        single_quotes = line.count("'") - line.count("\\'")
        double_quotes = line.count('"') - line.count('\\"')

        fixed = False
        if single_quotes % 2 == 1:
            # Add closing single quote at end of line (before newline)
            lines[error_line - 1] = line.rstrip('\n') + "'\n"
            fixed = True
        elif double_quotes % 2 == 1:
            lines[error_line - 1] = line.rstrip('\n') + '"\n'
            fixed = True

        if fixed:
            try:
                with open(file_path, 'w') as f:
                    f.writelines(lines)
                self.output(f"      ✓ Fixed unterminated string in {file_path.name}")
                self.context.files_modified.append(str(file_path.relative_to(self.project_dir)))
                return True
            except Exception as e:
                self.output(f"      Failed to write fix: {e}")

        return False

    def _fix_unexpected_eof(self, lines: list, error_line: int, file_path: Path) -> bool:
        """Fix unexpected EOF - usually missing closing brackets/parens."""
        # Count brackets/parens in entire file
        open_parens = 0
        open_brackets = 0
        open_braces = 0

        for line in lines:
            # Skip strings (rough approximation)
            in_string = False
            for i, char in enumerate(line):
                if char in '"\'':
                    in_string = not in_string
                if not in_string:
                    if char == '(':
                        open_parens += 1
                    elif char == ')':
                        open_parens -= 1
                    elif char == '[':
                        open_brackets += 1
                    elif char == ']':
                        open_brackets -= 1
                    elif char == '{':
                        open_braces += 1
                    elif char == '}':
                        open_braces -= 1

        # Add missing closers at end
        closers = ')' * open_parens + ']' * open_brackets + '}' * open_braces
        if closers:
            lines.append(closers + '\n')
            try:
                with open(file_path, 'w') as f:
                    f.writelines(lines)
                self.output(f"      ✓ Added missing closers: {closers}")
                self.context.files_modified.append(str(file_path.relative_to(self.project_dir)))
                return True
            except Exception as e:
                self.output(f"      Failed to write fix: {e}")

        return False

    def _fix_missing_colon(self, lines: list, error_line: int, file_path: Path) -> bool:
        """Fix missing colon after def/class/if/for/while."""
        if error_line > len(lines):
            return False

        line = lines[error_line - 1]
        stripped = line.rstrip()

        # Check if line should end with colon
        needs_colon = any(stripped.lstrip().startswith(kw) for kw in
                        ['def ', 'class ', 'if ', 'elif ', 'else', 'for ', 'while ', 'with ', 'try', 'except', 'finally'])

        if needs_colon and not stripped.endswith(':'):
            lines[error_line - 1] = stripped + ':\n'
            try:
                with open(file_path, 'w') as f:
                    f.writelines(lines)
                self.output(f"      ✓ Added missing colon at line {error_line}")
                self.context.files_modified.append(str(file_path.relative_to(self.project_dir)))
                return True
            except Exception as e:
                self.output(f"      Failed to write fix: {e}")

        return False

    def _fix_requirements_file(self, diagnosis: Dict) -> bool:
        """
        Fix dependencies by analyzing imports and adding missing packages.
        """
        try:
            self.output("      Reconciling dependencies using LLM resolution...")
            
            # Step 1: Scan all files for imports and resolve to packages
            dep_info = self.dependency_resolver.generate_dependency_file_content(self.project_dir)
            if not dep_info:
                self.output("      No external dependencies found, skipping update")
                return True
                
            filename = dep_info["filename"]
            actual_content = dep_info["content"]
            target_path = self.project_dir / filename

            # Step 2: Write to file
            target_path.write_text(actual_content)
            self.output(f"      ✓ Successfully updated {filename} with resolved packages")
            
            if filename not in self.context.files_modified:
                self.context.files_modified.append(filename)
                
            # Step 3: Try to install
            if filename == "requirements.txt":
                result = self.toolkit.pip_install(packages=["-r", "requirements.txt"])
                if result.success:
                    self.output("      ✓ Dependencies installed successfully")
                    return True
                else:
                    self.output(f"      ⚠ pip install failed. Analyzing system dependencies...")
                    error_out = ""
                    if hasattr(result, 'error') and result.error:
                        error_out = result.error
                    elif hasattr(result, 'metadata') and result.metadata.get('stderr'):
                        error_out = result.metadata['stderr']
                    
                    system_info = self.dependency_resolver.resolve_system_dependencies(error_out)
                    commands = system_info.get("commands", [])
                    queries = system_info.get("search_queries", [])
                    
                    if commands:
                        self.output("      💡 Detected missing system libraries. Suggestion:")
                        for fix in commands:
                            self.output(f"         {fix}")
                    
                    if queries:
                        self.output("      🔍 Performing internet research to verify current package versions...")
                        search_results = []
                        for query in queries[:2]:
                            res = self.toolkit.search_web(query)
                            if res.success:
                                search_results.append(str(res.result))
                        
                        if search_results:
                            # Re-resolve with search context
                            self.output("      🧠 Analyzing research results...")
                            new_error_out = f"{error_out}\n\nRESEARCH RESULTS:\n" + "\n".join(search_results)
                            new_info = self.dependency_resolver.resolve_system_dependencies(new_error_out)
                            new_commands = new_info.get("commands", [])
                            if new_commands:
                                self.output("      ✅ Confirmed system fix after research:")
                                for fix in new_commands:
                                    self.output(f"         {fix}")
                    
                    if not commands and not queries:
                        self.output(f"      ⚠ pip install had issues: {str(error_out)[:100]}")
                    
                    return False
            
            return True

        except Exception as e:
            logger.error(f"Requirements fix failed: {e}")
            self.output(f"      ✗ Failed to update dependencies: {e}")
            return False

    def _build_fix_context(self, diagnosis: Dict) -> str:
        """Build comprehensive context for fix phase."""
        context_parts = []

        # ═══════════════════════════════════════════════════════════════════════
        # CRITICAL: Add project design context FIRST so LLM sees it prominently
        # ═══════════════════════════════════════════════════════════════════════
        design_context = self.context.get_design_context_for_llm()
        if design_context:
            context_parts.append(design_context)

        # Add system instructions about design adherence and fix approach
        context_parts.append("""
════════════════════════════════════════════════════════════════
MANDATORY FIX INSTRUCTIONS - YOU MUST FOLLOW THESE
════════════════════════════════════════════════════════════════

1. YOU MUST ADHERE to the original project objectives and design directives
   in the design statements above. Do NOT introduce changes that violate
   the project architecture or deviate from the intended functionality.

2. Surgical and targeted fixes are PREFERRED. Make the MINIMAL change needed
   to fix the bug. BUT you CAN do a FULL REWRITE of a function or a file
   when it is NECESSARY ONLY - for example:
   - When the function has fundamental structural issues
   - When multiple interrelated bugs require coordinated changes
   - When the existing code is too broken to patch surgically

3. When doing a full function rewrite, ensure you:
   - Preserve the function signature (unless that's part of the bug)
   - Maintain compatibility with calling code
   - Keep the same behavior for working cases

════════════════════════════════════════════════════════════════
""")

        # Add debug session context
        context_parts.append(self.context.get_llm_context())

        # Add rich project context (file structure, symbols)
        if self.project_context:
            try:
                self.project_context.scan_file_structure(extract_symbols=True, force=False)

                if self.project_context.directory_tree:
                    context_parts.append("\n═══ PROJECT STRUCTURE ═══")
                    context_parts.append(self.project_context.directory_tree.tree_string)

                symbol_info = []
                for path, entry in list(self.project_context.file_entries.items())[:10]:
                    if entry.file_type == 'python' and entry.symbols:
                        symbols_str = ", ".join(entry.symbols[:5])
                        symbol_info.append(f"  {path}: {symbols_str}")

                if symbol_info:
                    context_parts.append("\n═══ KEY SYMBOLS ═══")
                    context_parts.extend(symbol_info)

            except Exception as e:
                logger.warning(f"Could not get project structure: {e}")

        # Add diagnosis findings - FILE CONTENTS WITH LINE NUMBERS
        if diagnosis.get("files_read"):
            context_parts.append("\n═══ FILE CONTENTS (with line numbers) ═══")
            for path, content in diagnosis["files_read"].items():
                lines = content.split('\n')
                # Show more lines and format clearly
                numbered = [f"{i+1:4}| {line}" for i, line in enumerate(lines[:80])]
                context_parts.append(f"\n──── {path} ────")
                context_parts.append('\n'.join(numbered))
                if len(lines) > 80:
                    context_parts.append(f"     ... ({len(lines) - 80} more lines)")

        # Add line context if available
        if diagnosis.get("line_context"):
            context_parts.append("\n═══ SPECIFIC LINE CONTEXT ═══")
            for path, contexts in diagnosis["line_context"].items():
                for ctx in contexts:
                    if isinstance(ctx, dict) and "lines" in ctx:
                        context_parts.append(f"\n──── {path} (lines {ctx.get('start', '?')}-{ctx.get('end', '?')}) ────")
                        for line_info in ctx["lines"]:
                            ln = line_info.get("line_number", "?")
                            content = line_info.get("content", "")
                            context_parts.append(f"{ln:4}| {content}")

        # Add search results
        if diagnosis.get("search_results"):
            context_parts.append("\n═══ SEARCH RESULTS ═══")
            for match in diagnosis["search_results"][:20]:
                if isinstance(match, dict):
                    file = match.get("file", match.get("path", "?"))
                    line = match.get("line", match.get("match_line", "?"))
                    content = match.get("content", match.get("match_content", ""))
                    context_parts.append(f"  {file}:{line}: {content[:120]}")

        return "\n".join(context_parts)

    async def _try_llm_tool_fix(self, context: str) -> ExecutionResult:
        """Try to fix using LLM tool-calling."""
        import asyncio

        # Use a SIMPLE prompt - complex prompts confuse smaller models
        instruction = f"""Fix this bug: {self.issue}

Error: {self.error_trace[:400] if self.error_trace else 'none'}

Tools available:
- replace_line(path, line_number, new_content)
- edit_file(path, search, replace)
- edit_file(path, search, replace)
- write_file(path, content)

CRITICAL INSTRUCTION:
If you are modifying error handling code, ALWAYS ensure the full traceback is printed/logged.
Use `logging.exception(...)` or `traceback.print_exc()`. 
Do NOT replace full tracebacks with short error messages.

Respond with JSON:
{{"tool_calls": [{{"tool": "replace_line", "args": {{"path": "FILE", "line_number": N, "new_content": "FIXED"}}}}]}}"""

        try:
            self.output("      Waiting for LLM response (timeout: 45s)...")

            # Add timeout to prevent stuck states
            result = await asyncio.wait_for(
                self.tool_client.execute_and_continue(
                    instruction=instruction,
                    context=context[:15000],  # Increased context size
                    max_iterations=min(3, self.max_iterations)
                ),
                timeout=60  # Increased timeout slightly
            )
            self.output(f"   Tool calls: {len(result.results)}")
            return result

        except asyncio.TimeoutError:
            self.output("   ⚠ LLM timed out (45s) - moving to next strategy")
            return ExecutionResult(success=False, results=[], errors=["LLM timeout"])
        except Exception as e:
            logger.error(f"LLM tool fix failed: {e}")
            self.output(f"   ⚠ LLM error: {str(e)[:100]}")
            return ExecutionResult(success=False, results=[], errors=[str(e)])

    async def _try_structured_fix(self, diagnosis: Dict, context: str) -> bool:
        """
        Try to get a structured fix from LLM without tool-calling.

        Supports two fix modes:
        1. Line-based: LLM provides line number and replacement
        2. Block-based: LLM provides search/replace blocks (uses AdaptivePatchMatcher)
        """
        try:
            # Ask for BOTH line-based and block-based fix options
            prompt = f"""Analyze this bug and provide a SPECIFIC FIX.

BUG: {self.issue}
ERROR: {self.error_trace[:500] if self.error_trace else 'N/A'}

{context[:4000]}

CRITICAL INSTRUCTION:
When fixing error handling, NEVER suppress the traceback. 
Ensure `logging.exception(...)` or `traceback.print_exc()` is used so debugging is possible.

Provide your fix in ONE of these JSON formats:

OPTION 1 - Single line fix:
{{
  "fix_type": "line",
  "file": "path/to/file.py",
  "line_number": 42,
  "fixed_line": "the corrected line content"
}}

OPTION 2 - Block replacement (for multi-line changes):
{{
  "fix_type": "block",
  "file": "path/to/file.py",
  "search": "exact code block to find",
  "replace": "new code block"
}}

RESPOND WITH ONLY THE JSON OBJECT:"""

            import inspect
            result = self.llm_client.generate(
                prompt=prompt,
                temperature=0.0
            )
            if inspect.iscoroutine(result):
                response = await result
            else:
                response = result

            content = response.content if hasattr(response, 'content') else str(response)

            # Parse the response
            import json
            # Extract JSON using robust utility
            from ..utils.json_utils import extract_json_from_llm_response
            fix_data = extract_json_from_llm_response(content)

            if fix_data:
                file_path = fix_data.get("file")
                fix_type = fix_data.get("fix_type", "line")  # Default to line for backward compat

                if not file_path:
                    self.output("   ✗ No file path in fix response")
                    return False

                # ─────────────────────────────────────────────────────
                # BLOCK-BASED FIX using AdaptivePatchMatcher
                # ─────────────────────────────────────────────────────
                if fix_type == "block" or ("search" in fix_data and "replace" in fix_data):
                    search_block = fix_data.get("search", "")
                    replace_block = fix_data.get("replace", "")

                    if not search_block:
                        self.output("   ✗ Block fix missing search block")
                        return False

                    self.output(f"   Attempting block fix to {file_path} using AdaptivePatchMatcher...")

                    # Use v1's proven 6-strategy cascade
                    success = self._apply_patch_with_adaptive_matcher(
                        file_path=file_path,
                        search_block=search_block,
                        replace_block=replace_block,
                        verbose=True
                    )

                    if success:
                        self.output(f"   ✓ Block fix applied successfully")
                        return True
                    else:
                        self.output(f"   ✗ Block fix failed (all 6 strategies)")
                        # Fall through to try line-based if we have that data too

                # ─────────────────────────────────────────────────────
                # LINE-BASED FIX with validation and rollback
                # ─────────────────────────────────────────────────────
                line_num = fix_data.get("line_number")
                new_content = fix_data.get("fixed_line") or fix_data.get("new_content")

                if line_num and new_content:
                    self.output(f"   Attempting line fix to {file_path}:{line_num}")

                    # Validate new_content is reasonable
                    if len(new_content.strip()) < 2:
                        self.output(f"   ✗ Line fix rejected: new_content too short/empty")
                        return False

                    # Use the new validated line patch method
                    success = self._apply_line_patch(
                        file_path=file_path,
                        line_number=int(line_num),
                        new_content=new_content,
                        validate_syntax=True
                    )

                    if success:
                        self.output(f"   ✓ Line fix applied and validated")
                        return True
                    else:
                        self.output(f"   ✗ Line fix failed")

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error in structured fix: {e}")
        except Exception as e:
            logger.warning(f"Structured fix attempt failed: {e}")

        return False
    
    def _attempt_direct_fix(self, diagnosis: Dict) -> bool:
        """
        Attempt a direct fix when LLM doesn't return proper tool calls.

        Uses multiple heuristics based on the diagnosis findings and error trace.
        """
        try:
            files_read = diagnosis.get("files_read", {})
            issue_lower = self.issue.lower()
            error_lower = (self.error_trace or "").lower()

            # ─────────────────────────────────────────────────────
            # Heuristic 1: Requirements.txt issues
            # ─────────────────────────────────────────────────────
            if "requirements" in issue_lower or "requirements.txt" in error_lower:
                req_path = self.project_dir / "requirements.txt"
                if req_path.exists():
                    result = self.toolkit.sanitize_requirements()
                    if result.success:
                        self.output("   ✓ Sanitized requirements.txt")
                        self.context.files_modified.append("requirements.txt")
                        return True

            # ─────────────────────────────────────────────────────
            # Heuristic 2: Look for BUG/FIXME/TODO markers
            # ─────────────────────────────────────────────────────
            for path, content in files_read.items():
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    line_lower = line.lower()

                    # Look for explicit bug markers
                    if any(marker in line for marker in ['# BUG', '# FIXME', '# TODO', '# FIX']):
                        self.output(f"   Found bug marker at {path}:{i}")

                        # Try common fixes based on context
                        fixed = self._try_heuristic_fixes(path, i, line, lines, issue_lower)
                        if fixed:
                            return True

            # ─────────────────────────────────────────────────────
            # Heuristic 3: Error trace line number
            # ─────────────────────────────────────────────────────
            import re
            line_match = re.search(r'line (\d+)', error_lower)
            file_match = re.search(r'file ["\']?([^"\':\s]+\.py)["\']?', error_lower)

            if line_match:
                error_line = int(line_match.group(1))
                error_file = file_match.group(1) if file_match else None

                # Find the file in our diagnosis
                for path, content in files_read.items():
                    if error_file and error_file not in path:
                        continue

                    lines = content.split('\n')
                    if error_line <= len(lines):
                        target_line = lines[error_line - 1]
                        self.output(f"   Found error line {error_line}: {target_line[:50]}...")

                        # Try common fixes
                        fixed = self._try_heuristic_fixes(path, error_line, target_line, lines, issue_lower)
                        if fixed:
                            return True

            # ─────────────────────────────────────────────────────
            # Heuristic 4: Import errors
            # ─────────────────────────────────────────────────────
            if "import" in error_lower or "module" in error_lower:
                # Try to find missing import
                module_match = re.search(r"no module named ['\"]?([a-z_][a-z0-9_]*)", error_lower)
                if module_match:
                    missing_module = module_match.group(1)
                    self.output(f"   Detected missing module: {missing_module}")

                    # Try pip install
                    result = self.toolkit.pip_install(packages=[missing_module])
                    if result.success:
                        self.output(f"   ✓ Installed {missing_module}")
                        return True

            return False

        except Exception as e:
            logger.error(f"Direct fix attempt failed: {e}")
            return False

    def _try_heuristic_fixes(self, path: str, line_num: int, line: str, all_lines: list, issue: str) -> bool:
        """
        Try common heuristic fixes for a specific line.

        Returns True if a fix was successfully applied.
        """
        original_line = line
        fixed_line = None

        # Fix 1: Wrong arithmetic operator
        if 'sum' in issue or 'add' in issue or 'total' in issue:
            if ' - ' in line and 'return' in line:
                fixed_line = line.replace(' - ', ' + ')
            elif ' - b' in line:
                fixed_line = line.replace(' - b', ' + b')

        # Fix 2: Wrong comparison operator
        if 'greater' in issue or 'less' in issue or 'compare' in issue:
            if ' < ' in line and 'greater' in issue:
                fixed_line = line.replace(' < ', ' > ')
            elif ' > ' in line and 'less' in issue:
                fixed_line = line.replace(' > ', ' < ')

        # Fix 3: Missing colon
        if line.rstrip().endswith(')') and not line.rstrip().endswith(':'):
            # Check if this looks like a function/class/if/for/while
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in ['def ', 'class ', 'if ', 'elif ', 'else', 'for ', 'while ', 'with ', 'try', 'except', 'finally']):
                if not stripped.endswith(':'):
                    fixed_line = line.rstrip() + ':'

        # Fix 4: Remove bug comment markers
        if fixed_line:
            for marker in ['# BUG', '# FIXME', '# TODO: fix', '# Should be']:
                if marker in fixed_line:
                    # Remove the marker and everything after it
                    idx = fixed_line.find(marker)
                    fixed_line = fixed_line[:idx].rstrip()

        # Apply fix if found - use validated line patch for safety
        if fixed_line and fixed_line != original_line:
            success = self._apply_line_patch(
                file_path=path,
                line_number=line_num,
                new_content=fixed_line,
                validate_syntax=True
            )
            if success:
                self.output(f"   ✓ Applied heuristic fix to {path}:{line_num}")
                return True

        return False

    def _apply_patch_with_adaptive_matcher(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        verbose: bool = True
    ) -> bool:
        """
        Apply a patch using v1's robust AdaptivePatchMatcher (6-strategy cascade).

        This is the PROVEN patching logic from v1 that handles:
        1. Exact Match - Fast path for perfect matches
        2. Normalized Whitespace - Handles spacing variations
        3. Semantic AST Match - Compares code structure (Python only)
        4. Context Anchor - Uses surrounding code as reference
        5. Fuzzy Line Match - Line-by-line with tolerance
        6. Signature Match - Finds by function/class name

        Args:
            file_path: Relative path to file
            search_block: Code to search for
            replace_block: Code to replace with
            verbose: Print progress

        Returns:
            True if patch was applied successfully
        """
        full_path = self.project_dir / file_path

        if not full_path.exists():
            self.output(f"      ✗ File not found: {file_path}")
            return False

        try:
            # Read current content
            original_content = full_path.read_text(encoding='utf-8')

            # Create adaptive matcher with 6-strategy cascade
            matcher = AdaptivePatchMatcher(
                file_path=full_path,
                content=original_content,
                verbose=verbose
            )

            # Try to find and replace using all strategies
            if verbose:
                self.output(f"      Applying patch to {file_path} using adaptive matcher...")

            new_content = matcher.find_and_replace(search_block, replace_block)

            if new_content is None:
                self.output(f"      ✗ All 6 strategies failed to find match")
                return False

            # Validate syntax BEFORE writing (for Python files)
            if file_path.endswith('.py'):
                try:
                    import ast
                    ast.parse(new_content)
                except SyntaxError as e:
                    self.output(f"      ✗ Patch would introduce syntax error: {e}")
                    return False

            # Write the patched content
            full_path.write_text(new_content, encoding='utf-8')

            # Track modified file
            if file_path not in self.context.files_modified:
                self.context.files_modified.append(file_path)

            self.output(f"      ✓ Patch applied successfully to {file_path}")
            return True

        except Exception as e:
            self.output(f"      ✗ Patch failed: {e}")
            logger.error(f"Adaptive patch failed for {file_path}: {e}")
            return False

    def _apply_line_patch(
        self,
        file_path: str,
        line_number: int,
        new_content: str,
        validate_syntax: bool = True
    ) -> bool:
        """
        Apply a single line replacement with validation.

        Wraps the toolkit's replace_line with syntax validation and rollback.

        Args:
            file_path: Relative path to file
            line_number: Line number to replace (1-indexed)
            new_content: New content for the line
            validate_syntax: Whether to validate syntax after applying

        Returns:
            True if patch was applied successfully
        """
        full_path = self.project_dir / file_path

        if not full_path.exists():
            self.output(f"      ✗ File not found: {file_path}")
            return False

        try:
            # Read original for potential rollback
            original_content = full_path.read_text(encoding='utf-8')

            # Apply the replacement
            result = self.toolkit.replace_line(
                path=file_path,
                line_number=line_number,
                new_content=new_content
            )

            if not result.success:
                self.output(f"      ✗ Replace failed: {result.error}")
                return False

            # Validate syntax if requested (for Python files)
            if validate_syntax and file_path.endswith('.py'):
                syntax_check = self.toolkit.validate_syntax(path=file_path)
                if not syntax_check.success:
                    # Rollback
                    self.output(f"      ✗ Patch caused syntax error, rolling back...")
                    full_path.write_text(original_content, encoding='utf-8')
                    return False

            # Track modified file
            if file_path not in self.context.files_modified:
                self.context.files_modified.append(file_path)

            self.output(f"      ✓ Line {line_number} replaced in {file_path}")
            return True

        except Exception as e:
            self.output(f"      ✗ Line patch failed: {e}")
            return False

    async def _run_verification_phase_with_error_capture(self) -> tuple[bool, str | None]:
        """
        Phase 4: Verify the fix and capture any new errors.
        
        Returns:
            Tuple of (success, error_message)
        """
        self.output("\n[PHASE 4] Verifying fix...")
        
        issue_lower = self.issue.lower()
        
        # ─────────────────────────────────────────────────────
        # Requirements.txt verification - don't run main.py
        # ─────────────────────────────────────────────────────
        if "requirements" in issue_lower:
            success = self._verify_requirements_fix()
            return success, None if success else "Requirements verification failed"
        
        # ─────────────────────────────────────────────────────
        # Syntax/code verification - check modified files first
        # ─────────────────────────────────────────────────────
        if self.context.files_modified:
            all_valid = True
            first_syntax_error = None
            
            for file_path in self.context.files_modified:
                if file_path.endswith('.py'):
                    result = self.toolkit.validate_syntax(path=file_path)
                    if result.success:
                        self.output(f"   ✓ {file_path} - syntax valid")
                    else:
                        self.output(f"   ✗ {file_path} - {result.error}")
                        all_valid = False
                        if not first_syntax_error:
                            first_syntax_error = f"Syntax error in {file_path}: {result.error}"
            
            if not all_valid:
                return False, first_syntax_error
        
        # ─────────────────────────────────────────────────────
        # Run main.py if it exists and issue is about running code
        # ─────────────────────────────────────────────────────
        main_py = self.project_dir / "main.py"
        if main_py.exists():
            # Only run main.py if issue seems to be about runtime behavior
            run_keywords = ['run', 'error', 'crash', 'bug', 'fix', 'work', 'fail', 'broken', 'exception', 'traceback']
            should_run = any(kw in issue_lower for kw in run_keywords)
            
            if should_run:
                result = self.toolkit.run_python("main.py", timeout=10)

                if result.success:
                    self.output("   ✓ Code runs without errors")
                    return True, None
                else:
                    stderr = result.result.get("stderr", "") if isinstance(result.result, dict) else str(result.error)

                    # Check if "error" is just CLI argument requirement (not a bug)
                    cli_usage_patterns = [
                        "arguments are required",
                        "usage:",
                        "the following arguments are required",
                        "error: unrecognized arguments",
                        "error: argument",
                    ]
                    is_cli_usage = any(p in stderr.lower() for p in cli_usage_patterns)

                    if is_cli_usage:
                        self.output("   ✓ Code runs (CLI requires arguments - this is expected)")
                        return True, None

                    self.output(f"   ✗ Still has errors: {stderr[:200]}")
                    return False, stderr
            else:
                self.output("   ✓ Fix applied (not running main.py for this issue type)")
                return True, None
                
        self.output("   ✓ Fix applied")
        return True, None

    def _verify_requirements_fix(self) -> bool:
        """Verify requirements.txt fix specifically."""
        req_path = self.project_dir / "requirements.txt"

        if not req_path.exists():
            self.output("   ✗ requirements.txt not found")
            return False

        # Check 1: File exists and is readable
        try:
            with open(req_path, 'r') as f:
                content = f.read()
            self.output("   ✓ requirements.txt exists and readable")
        except Exception as e:
            self.output(f"   ✗ Cannot read requirements.txt: {e}")
            return False

        # Check 2: Try pip install --dry-run (or just check syntax)
        result = self.toolkit.run_command("pip check")
        # pip check might fail if packages aren't installed, that's OK

        # Check 3: Validate no obvious syntax errors in requirements
        import re
        lines = content.split('\n')
        invalid_lines = []
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Basic validation: should be package name with optional version
            if not re.match(r'^[a-zA-Z0-9_\-\.\[\]]+([<>=!~]+[a-zA-Z0-9_\-\.\*,]+)?$', line):
                # Allow -r, -e, --index-url etc
                if not line.startswith(('-r', '-e', '--', 'git+', 'http')):
                    invalid_lines.append((i, line))

        if invalid_lines:
            self.output(f"   ⚠ Found {len(invalid_lines)} potentially invalid lines:")
            for line_num, line in invalid_lines[:3]:
                self.output(f"      Line {line_num}: {line[:50]}")
            # Don't fail for this, just warn
        else:
            self.output("   ✓ requirements.txt format looks valid")

        # Check 4: Try to install (optional, may take time)
        # Only if we haven't already in the fix phase
        if "requirements.txt" in self.context.files_modified:
            self.output("   ✓ requirements.txt was updated")

        return True
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def get_session_summary(self) -> Dict:
        """Get current session summary."""
        return self.context.get_summary()
    
    def get_tool_history(self) -> str:
        """Get tool call history for display."""
        return self.context.get_tool_history_for_llm()
    
    def resume_session(self, session_id: str) -> bool:
        """Resume a previous session."""
        loaded = DebugContext.load_state(self.project_dir, session_id)
        if loaded:
            self.context = loaded
            return True
        return False
