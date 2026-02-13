"""
Debug Controller V2 - Tool-Calling Architecture.

This is the new debug controller that uses structured tool calls
instead of parsing raw SEARCH/REPLACE text from the LLM.

Architecture:
1. Phase 1 (Planning): Get JSON diagnosis plan from LLM
2. Phase 2 (Execution): Execute each step using tool calls
3. Phase 3 (Integration): Feed results back, iterate

Benefits:
- No fragile regex parsing of LLM output
- Structured validation of all tool calls
- Deterministic tool execution
- Clear feedback loop
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..services.debug_toolkit import DebugToolkit, ToolResult
from ..services.tool_executor import ToolExecutor, ExecutionResult
from ..services.guidance_planner import GuidancePlanner, DiagnosisPlan, DiagnosisStep
from ..services.tool_calling_client import ToolCallingClient

logger = logging.getLogger(__name__)


class DebugOutcome(Enum):
    """Possible outcomes of the debug process."""
    FIXED = "fixed"
    BLOCKED = "blocked"
    MAX_ITERATIONS = "max_iterations"
    USER_CANCELLED = "user_cancelled"
    ERROR = "error"


@dataclass
class DebugResult:
    """Result of the debug process."""
    outcome: DebugOutcome
    iterations: int
    files_modified: List[str]
    root_cause: Optional[str] = None
    fix_summary: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "outcome": self.outcome.value,
            "iterations": self.iterations,
            "files_modified": self.files_modified,
            "root_cause": self.root_cause,
            "fix_summary": self.fix_summary
        }


class DebugControllerV2:
    """
    Tool-calling debug controller.
    
    This controller uses the new architecture where:
    1. LLM provides structured diagnosis plans
    2. Tools are executed via structured tool calls
    3. Results are fed back to LLM for iteration
    
    No regex parsing of free-form text!
    
    Usage:
        controller = DebugControllerV2(
            project_dir=Path("/path/to/project"),
            llm_client=llm_client,
            output_fn=print
        )
        result = await controller.debug_issue("Fix requirements.txt")
    """
    
    def __init__(
        self,
        project_dir: Path,
        llm_client,
        output_fn: Callable[[str], None] = print,
        max_iterations: int = 10
    ):
        """
        Initialize the debug controller.
        
        Args:
            project_dir: Path to the project directory
            llm_client: LLM client with generate() method
            output_fn: Function to output progress messages
            max_iterations: Maximum debug iterations
        """
        self.project_dir = Path(project_dir)
        self.llm_client = llm_client
        self.output = output_fn
        self.max_iterations = max_iterations
        
        # Initialize components
        self.toolkit = DebugToolkit(project_dir)
        self.executor = ToolExecutor(self.toolkit)
        self.planner = GuidancePlanner(llm_client)
        self.tool_client = ToolCallingClient(llm_client, self.toolkit)
        
        # State
        self._files_modified: List[str] = []
        self._iteration = 0
        self._root_cause: Optional[str] = None
    
    async def debug_issue(
        self,
        issue: str,
        error_trace: str = ""
    ) -> DebugResult:
        """
        Debug an issue using the tool-calling architecture.
        
        Args:
            issue: Description of the bug to fix
            error_trace: Error output from running the code
            
        Returns:
            DebugResult with outcome and details
        """
        self.output("\n" + "=" * 60)
        self.output("🔧 TOOL-CALLING DEBUG MODE (V2)")
        self.output("=" * 60)
        self.output(f"Issue: {issue}")
        self.output(f"Project: {self.project_dir}")
        
        try:
            # Pre-flight: Sanitize requirements.txt
            await self._pre_flight_checks()
            
            # Phase 1: Get diagnosis plan
            plan = await self._get_diagnosis_plan(issue, error_trace)
            if not plan.steps:
                self.output("❌ Failed to create diagnosis plan")
                return DebugResult(
                    outcome=DebugOutcome.ERROR,
                    iterations=0,
                    files_modified=[]
                )
            
            # Phase 2: Execute diagnosis steps
            diagnosis_result = await self._execute_diagnosis_plan(plan)
            
            # Phase 3: Execute fix using tool calls
            fix_result = await self._execute_fix(issue, diagnosis_result)
            
            # Verify fix
            if fix_result.success:
                self.output("\n" + "=" * 60)
                self.output("✅ BUG FIXED!")
                self.output("=" * 60)
                return DebugResult(
                    outcome=DebugOutcome.FIXED,
                    iterations=self._iteration,
                    files_modified=self._files_modified,
                    root_cause=self._root_cause,
                    fix_summary="Fixed using tool-calling architecture"
                )
            else:
                self.output("\n⚠️ Fix attempt completed but may have issues")
                return DebugResult(
                    outcome=DebugOutcome.BLOCKED,
                    iterations=self._iteration,
                    files_modified=self._files_modified,
                    root_cause=self._root_cause
                )
                
        except Exception as e:
            logger.exception("Debug process failed")
            self.output(f"\n❌ Error: {e}")
            return DebugResult(
                outcome=DebugOutcome.ERROR,
                iterations=self._iteration,
                files_modified=self._files_modified
            )
    
    async def _pre_flight_checks(self):
        """Run pre-flight checks before debugging."""
        self.output("\n📦 [PRE-FLIGHT] Running checks...")
        
        # Sanitize requirements.txt
        result = self.toolkit.sanitize_requirements()
        if result.success and result.result.get("removed"):
            self.output(f"   ✓ Cleaned {len(result.result['removed'])} invalid entries from requirements.txt")
        
        # Install dependencies
        req_path = self.project_dir / 'requirements.txt'
        if req_path.exists():
            result = self.toolkit.run_command(f"pip install -r requirements.txt")
            if result.success:
                self.output("   ✓ Dependencies installed")
            else:
                self.output(f"   ⚠ pip install issues: {result.error}")
    
    async def _get_diagnosis_plan(
        self,
        issue: str,
        error_trace: str
    ) -> DiagnosisPlan:
        """Phase 1: Get structured diagnosis plan from LLM."""
        self.output("\n[PHASE 1] Getting diagnosis plan...")
        
        # Get project files
        files = []
        for f in self.project_dir.rglob("*.py"):
            if '.raica' not in str(f) and 'venv' not in str(f):
                files.append(str(f.relative_to(self.project_dir)))
        files = files[:30]  # Limit
        
        # Get plan from LLM
        plan = await self.planner.get_diagnosis_plan(
            issue=issue,
            error_trace=error_trace,
            project_files=files
        )
        
        self.output(f"   ✓ Got {len(plan)} diagnosis steps")
        for step in plan.steps[:5]:
            self.output(f"      {step.step}. {step.action}: {step.reason or ''}")
        
        return plan
    
    async def _execute_diagnosis_plan(
        self,
        plan: DiagnosisPlan
    ) -> Dict[str, Any]:
        """Phase 2: Execute diagnosis steps and collect findings."""
        self.output("\n[PHASE 2] Executing diagnosis steps...")
        
        findings = {
            "files_read": {},
            "search_results": [],
            "errors": [],
            "symbols": {}
        }
        
        for step in plan.steps:
            self._iteration += 1
            self.output(f"\n   Step {step.step}: {step.action}")
            
            # Map diagnosis step to tool call
            result = await self._execute_diagnosis_step(step)
            
            if result.success:
                self.output(f"      ✓ Success")
                
                # Collect findings
                if step.action == "read_file":
                    findings["files_read"][step.target] = result.result[:2000]
                elif step.action == "grep_search":
                    findings["search_results"].extend(result.result[:10])
                elif step.action == "get_symbols":
                    findings["symbols"][step.target] = result.result
            else:
                self.output(f"      ✗ {result.error}")
                findings["errors"].append(f"{step.action}: {result.error}")
        
        return findings
    
    async def _execute_diagnosis_step(
        self,
        step: DiagnosisStep
    ) -> ToolResult:
        """
        Execute a single diagnosis step as a tool call.

        Maps DiagnosisStep fields to toolkit arguments and handles
        validation before execution.
        """
        action = step.action
        args = {}

        # ─────────────────────────────────────────────────────
        # READ-ONLY / DIAGNOSIS TOOLS
        # ─────────────────────────────────────────────────────
        if action == "read_file":
            if not step.target:
                return ToolResult(success=False, error="read_file requires a file path")
            args["path"] = step.target

        elif action == "grep_search":
            if not step.pattern:
                return ToolResult(success=False, error="grep_search requires a pattern")
            args["pattern"] = step.pattern
            args["scope"] = step.scope or "**/*.py"

        elif action == "search_with_context":
            args["path"] = step.target or "main.py"
            args["pattern"] = step.pattern or ""

        elif action == "get_lines_range":
            args["path"] = step.target or "main.py"
            if step.line_number is not None:
                args["start_line"] = step.line_number
            elif step.pattern:
                try:
                    args["start_line"] = int(step.pattern)
                except (ValueError, TypeError):
                    args["start_line"] = 1
            else:
                args["start_line"] = 1

        elif action == "get_line":
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

        elif action == "list_files":
            args["directory"] = step.target or "."
            args["pattern"] = step.pattern or "*"

        elif action in ("validate_syntax", "get_symbols"):
            if not step.target:
                return ToolResult(success=False, error=f"{action} requires a file path")
            args["path"] = step.target

        elif action == "find_file":
            args["name"] = step.pattern or step.target or "*"

        elif action == "sanitize_requirements":
            pass  # No args needed

        # ─────────────────────────────────────────────────────
        # MUTATION / FIX TOOLS (should be in fix phase, but handle anyway)
        # ─────────────────────────────────────────────────────
        elif action == "edit_file":
            if not step.target:
                return ToolResult(success=False, error="edit_file requires a file path")
            args["path"] = step.target
            args["search"] = step.search_text or step.pattern or ""
            args["replace"] = step.replace_text or step.new_content or ""
            if not args["search"]:
                return ToolResult(success=False, error="edit_file requires search text")

        elif action == "replace_line":
            if not step.target:
                return ToolResult(success=False, error="replace_line requires a file path")
            if step.line_number is None:
                return ToolResult(success=False, error="replace_line requires a line number")
            args["path"] = step.target
            args["line_number"] = step.line_number
            args["new_content"] = step.new_content or ""

        elif action == "insert_line":
            if not step.target:
                return ToolResult(success=False, error="insert_line requires a file path")
            args["path"] = step.target
            args["after_line"] = step.line_number if step.line_number is not None else 0
            args["content"] = step.new_content or ""

        # ─────────────────────────────────────────────────────
        # EXECUTION TOOLS
        # ─────────────────────────────────────────────────────
        elif action == "run_python":
            args["script"] = step.target or "main.py"

        elif action == "pip_install":
            if step.packages:
                args["packages"] = step.packages
            elif step.target:
                args["packages"] = [step.target]
            else:
                return ToolResult(success=False, error="pip_install requires package names")

        elif action == "run_command":
            if not step.target:
                return ToolResult(success=False, error="run_command requires a command")
            args["command"] = step.target

        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        # Execute the tool
        return self.toolkit.execute(action, args)
    
    async def _execute_fix(
        self,
        issue: str,
        diagnosis: Dict[str, Any]
    ) -> ExecutionResult:
        """Phase 3: Execute fix using tool-calling client."""
        self.output("\n[PHASE 3] Executing fix with tool calls...")
        
        # Build context from diagnosis findings
        context_parts = []
        
        if diagnosis.get("files_read"):
            context_parts.append("FILES READ:")
            for path, content in diagnosis["files_read"].items():
                context_parts.append(f"\n--- {path} ---\n{content[:1000]}")
        
        if diagnosis.get("search_results"):
            context_parts.append("\nSEARCH RESULTS:")
            for match in diagnosis["search_results"][:10]:
                context_parts.append(f"  {match.get('file')}:{match.get('line')}: {match.get('content', '')[:100]}")
        
        if diagnosis.get("errors"):
            context_parts.append("\nDIAGNOSIS ERRORS:")
            for err in diagnosis["errors"]:
                context_parts.append(f"  - {err}")
        
        context = "\n".join(context_parts)
        
        # Execute fix using tool-calling client
        result = await self.tool_client.execute_and_continue(
            instruction=f"""Fix this issue: {issue}

Based on the diagnosis findings above, use the edit_file tool to make the necessary changes.
After editing, use validate_syntax to verify the fix.
Then use run_python with main.py to test.

Make targeted, surgical edits. Do not rewrite entire files.""",
            context=context,
            max_iterations=5
        )
        
        # Track modified files
        for r in result.results:
            if r.metadata and r.metadata.get("path"):
                path = r.metadata["path"]
                if path not in self._files_modified:
                    self._files_modified.append(path)
        
        return result
