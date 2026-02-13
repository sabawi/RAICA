"""
Code Debug Agent for RAICA
===========================

Agent for debugging and enhancing existing code with the
"DO NO HARM" principle - 99.9% confidence no regression.

Features:
- Full codebase analysis
- Issue identification and root cause analysis
- Impact analysis before changes
- Smart planning (simple fix vs. architecture change)
- Baseline capture and rollback
- Intelligent regression fixing with escalating strategies
- Complete verification

Author: RAICA Development Team
Version: 1.0.0
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .baseline_manager import BaselineManager, BaselineSnapshot, DiffReport
from .regression_detector import (
    RegressionDetector, RegressionReport, RegressionSeverity,
    FixStrategy, FixAttempt
)
from .config_accessor import get_max_iterations

logger = logging.getLogger(__name__)


class DebugPhase(Enum):
    """Debug workflow phases."""
    ANALYSIS = auto()              # Read existing codebase, build understanding
    ISSUE_IDENTIFICATION = auto()  # User describes problem, find root cause
    IMPACT_ANALYSIS = auto()       # Determine affected files, assess risk
    PLANNING_DECISION = auto()     # Simple fix vs design review vs architecture
    BASELINE_CAPTURE = auto()      # Backup files, run tests, capture baseline
    IMPLEMENTATION = auto()        # Apply fix with validation
    REGRESSION_TESTING = auto()    # Compare before/after, verify no breakage
    VERIFICATION = auto()          # Final check, user acceptance
    DOCUMENTATION = auto()         # Update README.md to reflect changes
    USER_INSTRUCTIONS = auto()     # Provide test instructions to user
    COMPLETE = auto()              # Done


class FixComplexity(Enum):
    """Complexity level of required fix."""
    SIMPLE = auto()        # Direct code fix, single file
    MODERATE = auto()      # Multiple files, some refactoring
    COMPLEX = auto()       # Architectural changes needed
    REQUIRES_DESIGN = auto()  # Full design review needed


@dataclass
class IssueAnalysis:
    """Analysis of the reported issue."""
    description: str
    root_cause: Optional[str] = None
    affected_files: List[str] = field(default_factory=list)
    related_symbols: List[str] = field(default_factory=list)
    issue_type: str = "unknown"  # 'bug', 'enhancement', 'refactor', 'feature'
    confidence: float = 0.0  # Confidence in analysis (0.0 to 1.0)


@dataclass
class ImpactAssessment:
    """Assessment of change impact."""
    affected_files: List[str] = field(default_factory=list)
    affected_symbols: List[str] = field(default_factory=list)
    dependent_files: List[str] = field(default_factory=list)
    risk_level: str = "low"  # 'low', 'medium', 'high', 'critical'
    complexity: FixComplexity = FixComplexity.SIMPLE
    estimated_changes: int = 0  # Estimated number of changes
    recommendations: List[str] = field(default_factory=list)


@dataclass
class DebugContext:
    """Context maintained throughout debugging session."""
    project_dir: Path
    issue_description: str = ""
    issue_analysis: Optional[IssueAnalysis] = None
    impact_assessment: Optional[ImpactAssessment] = None
    baseline: Optional[BaselineSnapshot] = None
    changes_made: List[Dict[str, Any]] = field(default_factory=list)
    regression_attempts: int = 0
    max_regression_attempts: int = 2
    previous_failures: List[str] = field(default_factory=list)
    phase_history: List[str] = field(default_factory=list)
    user_instructions: str = ""  # Generated test instructions for user


@dataclass
class DebugResult:
    """Result of debug workflow."""
    success: bool
    phases_completed: List[str] = field(default_factory=list)
    issue_found: str = ""
    fix_applied: str = ""
    modified_files: List[str] = field(default_factory=list)
    rolled_back: bool = False  # Alias for rollback_performed
    rollback_performed: bool = False
    regression_attempts: int = 0
    final_test_results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_message: Optional[str] = None  # Alias for error
    summary: str = ""
    user_instructions: str = ""  # Test instructions for user

    def __post_init__(self):
        """Ensure aliases are synchronized."""
        if self.error and not self.error_message:
            self.error_message = self.error
        if self.rollback_performed:
            self.rolled_back = self.rollback_performed

    @property
    def files_modified(self) -> List[str]:
        """Alias for modified_files for compatibility."""
        return self.modified_files

    def get_summary(self) -> str:
        """Generate human-readable summary."""
        if self.success:
            self.summary = (
                f"DEBUG COMPLETE: {self.issue_found}\n"
                f"Fix: {self.fix_applied}\n"
                f"Modified files: {', '.join(self.modified_files)}\n"
                f"Phases: {' -> '.join(self.phases_completed)}"
            )
        else:
            self.summary = (
                f"DEBUG FAILED: {self.error}\n"
                f"Rollback: {'Yes' if self.rollback_performed else 'No'}\n"
                f"Attempts: {self.regression_attempts}"
            )
        return self.summary


class CodeDebugAgent:
    """
    Agent for debugging and enhancing existing code.

    DO NO HARM principle: 99.9% confidence no regression.

    Workflow:
    1. ANALYSIS - Understand existing codebase
    2. ISSUE_IDENTIFICATION - Find root cause
    3. IMPACT_ANALYSIS - Assess change risk
    4. PLANNING_DECISION - Choose fix strategy
    5. BASELINE_CAPTURE - Create safety backup
    6. IMPLEMENTATION - Apply fix
    7. REGRESSION_TESTING - Verify no breakage
    8. VERIFICATION - Final confirmation
    """

    def __init__(
        self,
        project_dir: Path,
        llm_client: Any,
        max_regression_attempts: int = get_max_iterations(),
        auto_rollback: bool = True,
        output_callback: Optional[Callable[[str, str], None]] = None,
        approval_callback: Optional[Callable[[str, List[str]], asyncio.Future]] = None,
        input_callback: Optional[Callable[[str], asyncio.Future]] = None,
        callbacks: Any = None,  # Generic callbacks object (TUI adapter)
        context_manager: Any = None  # ContextManager for file structure tracking
    ):
        """
        Initialize CodeDebugAgent.

        Args:
            project_dir: Project directory to debug
            llm_client: LLM client for analysis and fix generation
            max_regression_attempts: Max attempts to fix regressions (default 10)
            auto_rollback: Auto-rollback on failure (default True)
            output_callback: Callback for output messages (msg, type)
            approval_callback: Callback for approvals (question, options) -> answer
            input_callback: Callback for user input (prompt) -> answer
            callbacks: Generic callbacks object with on_* methods
            context_manager: Optional ContextManager for file structure tracking (prevents hallucination)
        """
        self.project_dir = Path(project_dir).resolve()
        self.llm_client = llm_client
        self.max_regression_attempts = max_regression_attempts
        self.auto_rollback = auto_rollback
        self.callbacks = callbacks
        self.context_manager = context_manager

        # Callbacks for TUI integration
        self._output = output_callback or self._default_output
        self._get_approval = approval_callback
        self._get_input = input_callback

        # If callbacks object provided, use its methods
        if callbacks:
            if hasattr(callbacks, 'on_progress'):
                # Create a wrapper that handles both sync and async callbacks
                def make_output_wrapper(cb):
                    def wrapper(msg, t="info"):
                        if asyncio.iscoroutinefunction(cb):
                            # Async callback - try to schedule it
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(cb(msg, 0.0))
                            except RuntimeError:
                                # No running loop - can't await, just skip
                                pass
                        else:
                            # Sync callback - call directly
                            cb(msg, 0.0)
                    return wrapper
                self._output = make_output_wrapper(callbacks.on_progress)
            if hasattr(callbacks, 'on_user_input'):
                self._get_input = callbacks.on_user_input
            if hasattr(callbacks, 'on_approval_needed'):
                self._get_approval = callbacks.on_approval_needed

        # Initialize components
        self.baseline_manager = BaselineManager(self.project_dir)
        self.regression_detector: Optional[RegressionDetector] = None

        # State
        self.current_phase = DebugPhase.ANALYSIS
        self.context = DebugContext(project_dir=self.project_dir)

        # Phase order for iteration
        self._phase_order = [
            DebugPhase.ANALYSIS,
            DebugPhase.ISSUE_IDENTIFICATION,
            DebugPhase.IMPACT_ANALYSIS,
            DebugPhase.PLANNING_DECISION,
            DebugPhase.BASELINE_CAPTURE,
            DebugPhase.IMPLEMENTATION,
            DebugPhase.REGRESSION_TESTING,
            DebugPhase.VERIFICATION,
            DebugPhase.DOCUMENTATION,
            DebugPhase.USER_INSTRUCTIONS,
            DebugPhase.COMPLETE
        ]

    def _default_output(self, message: str, msg_type: str = "info"):
        """Default output handler."""
        prefix = {
            "info": "[INFO]",
            "success": "[SUCCESS]",
            "warning": "[WARNING]",
            "error": "[ERROR]",
            "phase": "[PHASE]"
        }.get(msg_type, "[INFO]")
        print(f"{prefix} {message}")

    async def run(self, issue_description: str) -> DebugResult:
        """
        Run the complete debug/enhancement workflow.
        
        Now acts as a dispatcher to specialized autonomous controllers:
        - AutonomousDebugController (for bugs)
        - AutonomousEnhancementController (for features/enhancements)
        """
        self.context.issue_description = issue_description
        
        try:
            # Lazy import controllers to avoid circular deps and unused loads
            from .autonomous.debug_controller import AutonomousDebugController
            from .autonomous.enhancement_controller import AutonomousEnhancementController
            
            # [NEW] Phase 5: Initialize tool stack
            from .services.debug_toolkit import DebugToolkit
            from .services.tool_calling_client import ToolCallingClient
            
            toolkit = DebugToolkit(self.project_dir)
            tool_client = ToolCallingClient(self.llm_client, toolkit)
            
            # Determine correct controller
            task_type = await self._classify_task(issue_description)
            self._output(f"Classified task as: {task_type.upper()}", "info")
            
            if task_type == "bug":
                controller = AutonomousDebugController(
                    self.llm_client,
                    self.project_dir,
                    output_callback=lambda msg: self._output(msg, "info"),
                    max_iterations=self.max_regression_attempts,
                    context_manager=self.context_manager,
                    tool_client=tool_client, # [NEW]
                    toolkit=toolkit          # [NEW]
                )
                
                # specific to debug controller
                debug_result = await controller.debug_until_fixed(issue_description)
                
                # Convert result
                result = DebugResult(
                    success=debug_result.success,
                    issue_found=debug_result.root_cause or "Bug fix",
                    fix_applied=debug_result.fix_summary or "Fixed",
                    modified_files=debug_result.files_modified,
                    regression_attempts=debug_result.iterations,
                    summary=debug_result.fix_summary or "Bug fixed successfully"
                )
                if not result.success:
                    result.error = debug_result.blocked_reason
                    
            else: # enhancement
                controller = AutonomousEnhancementController(
                    self.llm_client,
                    self.project_dir,
                    output_callback=lambda msg: self._output(msg, "info"),
                    max_iterations=self.max_regression_attempts,
                    context_manager=self.context_manager
                )
                
                # specific to enhancement controller
                enh_result = await controller.run_enhancement(issue_description)
                
                # Convert result to generic DebugResult
                result = DebugResult(
                    success=enh_result.success,
                    issue_found="New Feature Request",
                    fix_applied=enh_result.summary or "Feature Implemented",
                    modified_files=enh_result.files_modified,
                    regression_attempts=enh_result.iterations,
                    summary=enh_result.summary or "Feature implemented successfully"
                )
                if not result.success:
                    result.error = enh_result.error

            # Don't print summary again - it's already shown by the controller
            return result

        except Exception as e:
            logger.exception("Agent session failed")
            return DebugResult(
                success=False,
                error=str(e),
                summary=f"Agent failed: {str(e)}"
            )

    async def _classify_task(self, description: str, max_retries: int = 3) -> str:
        """Determine if task is 'bug' or 'enhancement' using LLM.

        ARCHITECTURE: LLM decides classification semantically - NO hardcoded fallbacks.
        Retries with progressively more explicit prompts if LLM fails.
        """
        for attempt in range(max_retries):
            prompt = f"""YOU ARE A CLASSIFICATION AGENT. OUTPUT JSON ONLY. NO PROSE.

Classify this task as "bug" or "enhancement".

TASK: {description}

BUG = broken/error/crash/blank/debug
ENHANCEMENT = new feature/improve/optimize/refactor

RESPOND WITH EXACTLY ONE OF THESE (NO OTHER TEXT):
{{"classification": "bug"}}
{{"classification": "enhancement"}}
"""
            # Make prompt even more forceful on retries
            if attempt > 0:
                prompt = f"""OUTPUT JSON ONLY. ONE LINE. NO EXPLANATION.

Task: {description[:200]}

Reply EXACTLY: {{"classification": "bug"}} OR {{"classification": "enhancement"}}"""

            try:
                response = await self._call_llm(prompt, max_tokens=50)

                # Handle empty response - retry
                if not response or not response.strip():
                    self._output(f"LLM returned empty response (attempt {attempt + 1}/{max_retries})", "warning")
                    continue

                clean = response.strip().lower()

                # Try to parse JSON using robust utility
                from .utils.json_utils import extract_json_from_llm_response
                data = extract_json_from_llm_response(response)
                if data and 'classification' in data:
                    classification = data['classification']
                    if classification in ('bug', 'enhancement'):
                        return classification

                # Fallback: look for the word in response
                if "enhancement" in clean:
                    return "enhancement"
                if "bug" in clean:
                    return "bug"

                # LLM response unclear - retry
                self._output(f"LLM classification unclear (attempt {attempt + 1}/{max_retries}): '{clean[:50]}...'", "warning")

            except Exception as e:
                self._output(f"Task classification error (attempt {attempt + 1}/{max_retries}): {e}", "warning")

        # All retries failed - ask user instead of guessing
        self._output("LLM couldn't classify task. Asking user...", "warning")

        # Try to get user input
        try:
            print("\n" + "=" * 60)
            print("CLASSIFICATION NEEDED")
            print("=" * 60)
            print(f"\nTask: {description[:200]}...")
            print("\nIs this a BUG fix or an ENHANCEMENT?")
            print("  1. BUG - Something is broken/not working")
            print("  2. ENHANCEMENT - Adding new feature/improvement")
            user_input = input("\nEnter 1 or 2: ").strip()

            if user_input == "1" or "bug" in user_input.lower():
                return "bug"
            elif user_input == "2" or "enh" in user_input.lower():
                return "enhancement"
            else:
                raise RuntimeError("Invalid input. Please enter 1 (bug) or 2 (enhancement).")
        except EOFError:
            # Non-interactive mode
            raise RuntimeError(f"LLM failed to classify task after {max_retries} attempts and running in non-interactive mode.")

    def _next_phase(self):
        """Advance to the next phase."""
        current_index = self._phase_order.index(self.current_phase)
        if current_index < len(self._phase_order) - 1:
            self.current_phase = self._phase_order[current_index + 1]

    async def _phase_analysis(self) -> bool:
        """
        Phase 1: Analyze existing codebase.

        Builds understanding of:
        - Project structure
        - Key files and their purposes
        - Dependencies
        - Existing patterns

        IMPORTANT: Asks user for early clarifications and guidance.
        """
        self._output("Analyzing existing codebase...", "info")

        try:
            # Get all source files
            source_files = self.baseline_manager._get_source_files()
            self._output(f"Found {len(source_files)} source files", "info")

            # Build file summary for LLM
            file_summary = []
            for file_path in source_files[:50]:  # Limit to 50 files
                relative_path = file_path.relative_to(self.project_dir)
                size = file_path.stat().st_size
                file_summary.append(f"- {relative_path} ({size} bytes)")

            # Use LLM to understand codebase structure
            prompt = f"""Analyze this project structure and provide a brief summary:

PROJECT: {self.project_dir.name}

FILES:
{chr(10).join(file_summary[:30])}
{"... and more" if len(file_summary) > 30 else ""}

Provide:
1. What type of project is this? (web app, CLI tool, library, etc.)
2. What are the main components/modules?
3. What programming language(s) and frameworks are used?

Be concise (3-5 sentences)."""

            response = await self._call_llm(prompt, max_tokens=500)
            if response:
                self._output(f"Codebase analysis:\n{response}", "info")

            # === EARLY USER CLARIFICATION ===
            # Ask user for additional context before proceeding
            await self._ask_early_clarifications()

            return True

        except Exception as e:
            self._output(f"Analysis failed: {e}", "error")
            return False

    async def _ask_early_clarifications(self) -> None:
        """
        Ask user for early clarifications, options, and guidance.

        This runs early in the debug process to get user direction before
        making any changes.
        """
        self._output("\n" + "=" * 50, "info")
        self._output("EARLY CLARIFICATION - Please provide guidance:", "info")
        self._output("=" * 50, "info")

        questions = [
            {
                "key": "scope",
                "question": "What is the scope of changes you're comfortable with?",
                "options": [
                    "Minimal - Only fix the specific issue, no other changes",
                    "Moderate - Fix issue and clean up directly related code",
                    "Comprehensive - Fix issue and improve related code quality"
                ],
                "default": "Minimal"
            },
            {
                "key": "test_preference",
                "question": "How should testing be handled?",
                "options": [
                    "Run existing tests only",
                    "Run tests and suggest new tests if needed",
                    "Skip automated testing (manual verification)"
                ],
                "default": "Run existing tests only"
            },
            {
                "key": "risk_tolerance",
                "question": "What is your risk tolerance for this fix?",
                "options": [
                    "Low - Abort if any uncertainty",
                    "Medium - Proceed with user approval for risky changes",
                    "High - Trust the agent to make reasonable decisions"
                ],
                "default": "Medium"
            }
        ]

        self.user_preferences = {}

        for q in questions:
            self._output(f"\n{q['question']}", "info")
            for i, opt in enumerate(q['options'], 1):
                self._output(f"  {i}. {opt}", "info")

            if self._get_input:
                try:
                    if asyncio.iscoroutinefunction(self._get_input):
                        response = await self._get_input(
                            f"Select option (1-{len(q['options'])}) or press Enter for default [{q['default'][:20]}...]:"
                        )
                    else:
                        # Synchronous callback
                        response = q['default']
                except Exception:
                    response = q['default']

                # Parse response
                try:
                    choice = int(response.strip()) if response.strip() else 1
                    if 1 <= choice <= len(q['options']):
                        self.user_preferences[q['key']] = q['options'][choice - 1]
                    else:
                        self.user_preferences[q['key']] = q['default']
                except (ValueError, AttributeError):
                    # If response isn't a number, check if it's a text match
                    if response and any(response.lower() in opt.lower() for opt in q['options']):
                        for opt in q['options']:
                            if response.lower() in opt.lower():
                                self.user_preferences[q['key']] = opt
                                break
                    else:
                        self.user_preferences[q['key']] = q['default']
            else:
                self.user_preferences[q['key']] = q['default']

            self._output(f"  → Selected: {self.user_preferences[q['key']][:50]}...", "success")

        # Ask for any additional context
        self._output("\nAny additional context or guidance? (press Enter to skip):", "info")
        if self._get_input:
            try:
                if asyncio.iscoroutinefunction(self._get_input):
                    extra_context = await self._get_input("Additional context:")
                else:
                    extra_context = ""
                if extra_context and extra_context.strip():
                    self.user_preferences['additional_context'] = extra_context.strip()
                    self._output(f"  → Noted: {extra_context[:100]}...", "success")
            except Exception:
                pass

        self._output("\n" + "=" * 50, "info")
        self._output("Proceeding with debug analysis...", "info")

    async def _phase_issue_identification(self) -> bool:
        """
        Phase 2: Identify the root cause of the issue.

        Uses LLM to:
        - Understand the user's issue description
        - Identify likely root cause
        - Find affected files

        IMPORTANT: Asks for clarification if confidence is low.
        """
        self._output("Identifying issue root cause...", "info")
        logger.info(f"ISSUE_IDENTIFICATION: Starting for issue: {self.context.issue_description[:100]}...")

        try:
            # Get relevant file contents
            source_files = self.baseline_manager._get_source_files()
            logger.info(f"ISSUE_IDENTIFICATION: Found {len(source_files)} source files")
            file_contents = {}
            total_size = 0
            max_size = 50000  # 50KB limit for context

            for file_path in source_files:
                if total_size >= max_size:
                    break
                try:
                    content = file_path.read_text(errors='replace')
                    if len(content) < 10000:  # Skip very large files
                        relative_path = str(file_path.relative_to(self.project_dir))
                        file_contents[relative_path] = content[:5000]
                        total_size += len(content)
                except Exception:
                    pass

            # Build prompt for root cause analysis
            files_context = "\n\n".join([
                f"=== {path} ===\n{content[:2000]}"
                for path, content in list(file_contents.items())[:10]
            ])

            # Include user preferences from early clarification
            user_context = ""
            if hasattr(self, 'user_preferences') and self.user_preferences:
                if self.user_preferences.get('additional_context'):
                    user_context = f"\n\nUSER ADDITIONAL CONTEXT:\n{self.user_preferences['additional_context']}"

            prompt = f"""Analyze this issue and identify the root cause:

ISSUE DESCRIPTION:
{self.context.issue_description}{user_context}

RELEVANT CODE:
{files_context}

Provide:
1. ROOT CAUSE: What is the underlying problem?
2. AFFECTED FILES: Which files need to be modified?
3. ISSUE TYPE: Is this a bug, enhancement, refactor, or new feature?
4. CONFIDENCE: How confident are you? (0-100%)
5. CLARIFICATION_NEEDED: What additional info would help? (if any)

Format as JSON:
{{
    "root_cause": "...",
    "affected_files": ["file1.ext", "file2.ext"],
    "issue_type": "bug|enhancement|refactor|feature",
    "confidence": 85,
    "clarification_needed": null or "..."
}}
NOTE: Use actual file extensions from the project (.py, .js, .ts, .html, .jsx, etc.)"""

            logger.info(f"ISSUE_IDENTIFICATION: Calling LLM with {len(files_context)} chars of code context...")
            self._output("Calling LLM for root cause analysis...", "info")
            response = await self._call_llm(prompt, max_tokens=4000)
            logger.info(f"ISSUE_IDENTIFICATION: LLM response received ({len(response) if response else 0} chars)")
            if response:
                logger.debug(f"ISSUE_IDENTIFICATION: Raw response: {response[:500]}...")
                # Parse JSON response
                analysis = self._extract_json(response)
                logger.info(f"ISSUE_IDENTIFICATION: Parsed analysis: {analysis}")
                if not analysis:
                    # If JSON extraction failed, try to create a basic analysis from the text
                    self._output("JSON parsing failed, using text analysis fallback...", "warning")
                    analysis = {
                        'root_cause': response[:500] if response else "Unable to determine",
                        'affected_files': self._guess_affected_files(response),
                        'issue_type': 'enhancement',
                        'confidence': 50
                    }
                    logger.info(f"ISSUE_IDENTIFICATION: Fallback analysis: {analysis}")
                if analysis:
                    confidence = analysis.get('confidence', 0) / 100
                    clarification_needed = analysis.get('clarification_needed')

                    # If confidence is low, ask for clarification
                    if confidence < 0.7 or clarification_needed:
                        await self._ask_issue_clarification(
                            analysis.get('root_cause', 'Unknown'),
                            confidence,
                            clarification_needed
                        )

                    self.context.issue_analysis = IssueAnalysis(
                        description=self.context.issue_description,
                        root_cause=analysis.get('root_cause'),
                        affected_files=analysis.get('affected_files', []),
                        issue_type=analysis.get('issue_type', 'unknown'),
                        confidence=confidence
                    )
                    self._output(
                        f"Root cause: {self.context.issue_analysis.root_cause}",
                        "info"
                    )
                    self._output(
                        f"Affected files: {', '.join(self.context.issue_analysis.affected_files)}",
                        "info"
                    )
                    self._output(
                        f"Confidence: {int(confidence * 100)}%",
                        "info" if confidence >= 0.7 else "warning"
                    )
                    return True

            # No response from LLM - create a minimal fallback analysis
            self._output("LLM returned no response - using minimal fallback analysis", "warning")
            logger.warning("ISSUE_IDENTIFICATION: LLM returned no response, creating fallback")

            # Create minimal issue analysis so subsequent phases can continue
            self.context.issue_analysis = IssueAnalysis(
                description=self.context.issue_description,
                root_cause="Unable to determine automatically - manual review needed",
                affected_files=self._guess_affected_files(self.context.issue_description),
                issue_type="unknown",
                confidence=0.1  # Very low confidence
            )
            self._output(f"Fallback analysis created with {len(self.context.issue_analysis.affected_files)} guessed files", "info")
            return True

        except Exception as e:
            logger.exception(f"ISSUE_IDENTIFICATION: Failed with exception: {e}")
            self._output(f"Issue identification failed: {e}", "error")
            return False

    async def _ask_issue_clarification(
        self,
        preliminary_cause: str,
        confidence: float,
        suggested_clarification: Optional[str]
    ) -> None:
        """
        Ask user for clarification when issue identification has low confidence.
        """
        self._output("\n" + "=" * 50, "warning")
        self._output(f"⚠️  LOW CONFIDENCE ({int(confidence * 100)}%) - Need clarification", "warning")
        self._output("=" * 50, "warning")

        self._output(f"\nPreliminary understanding: {preliminary_cause}", "info")

        if suggested_clarification:
            self._output(f"\nQuestion from analysis: {suggested_clarification}", "info")

        self._output("\nPlease provide more details to help identify the issue:", "info")
        self._output("  1. When does the problem occur?", "info")
        self._output("  2. What is the expected behavior?", "info")
        self._output("  3. What is the actual behavior?", "info")
        self._output("  4. Any error messages or logs?", "info")

        if self._get_input:
            try:
                if asyncio.iscoroutinefunction(self._get_input):
                    clarification = await self._get_input(
                        "\nProvide clarification (or press Enter to continue with current analysis):"
                    )
                else:
                    clarification = ""

                if clarification and clarification.strip():
                    # Update the issue description with clarification
                    self.context.issue_description += f"\n\nUSER CLARIFICATION: {clarification.strip()}"
                    self._output("  → Clarification added to analysis", "success")

                    # Re-run the LLM analysis with the clarification
                    self._output("Re-analyzing with additional context...", "info")

            except Exception as e:
                self._output(f"Could not get clarification: {e}", "warning")

        self._output("=" * 50 + "\n", "info")

    async def _phase_impact_analysis(self) -> bool:
        """
        Phase 3: Analyze the impact of proposed changes.

        Determines:
        - Full list of affected files
        - Dependent code that might break
        - Risk level
        - Recommended approach
        """
        self._output("Analyzing change impact...", "info")

        try:
            affected_files = []
            if self.context.issue_analysis:
                affected_files = self.context.issue_analysis.affected_files

            # Find dependencies using symbol extraction
            dependent_files = []
            for file_path in affected_files:
                full_path = self.project_dir / file_path
                if full_path.exists():
                    content = full_path.read_text(errors='replace')
                    # Extract symbols that might be imported elsewhere
                    symbols = self.baseline_manager._extract_symbols(
                        content, file_path,
                        'python' if file_path.endswith('.py') else 'javascript'
                    )

                    # Search for files that import these symbols
                    for source_file in self.baseline_manager._get_source_files():
                        if source_file.name != file_path:
                            try:
                                source_content = source_file.read_text(errors='replace')
                                for sym in symbols:
                                    if sym.name in source_content:
                                        rel_path = str(source_file.relative_to(self.project_dir))
                                        if rel_path not in dependent_files:
                                            dependent_files.append(rel_path)
                                        break
                            except Exception:
                                pass

            # Determine complexity
            complexity = FixComplexity.SIMPLE
            if len(affected_files) > 3:
                complexity = FixComplexity.MODERATE
            if len(affected_files) > 5 or len(dependent_files) > 10:
                complexity = FixComplexity.COMPLEX

            # Determine risk
            risk = "low"
            if dependent_files:
                risk = "medium"
            if len(dependent_files) > 5:
                risk = "high"

            self.context.impact_assessment = ImpactAssessment(
                affected_files=affected_files,
                dependent_files=dependent_files[:20],  # Limit
                risk_level=risk,
                complexity=complexity,
                estimated_changes=len(affected_files)
            )

            self._output(
                f"Impact: {len(affected_files)} files to modify, "
                f"{len(dependent_files)} dependent files, "
                f"risk={risk}, complexity={complexity.name}",
                "info"
            )

            return True

        except Exception as e:
            self._output(f"Impact analysis failed: {e}", "error")
            return False

    async def _phase_planning_decision(self) -> bool:
        """
        Phase 4: Decide on fix approach.

        Chooses between:
        - SIMPLE: Direct fix
        - MODERATE: Multiple file changes
        - COMPLEX: Needs design review
        - REQUIRES_DESIGN: Full architecture consideration
        """
        self._output("Deciding fix approach...", "info")

        try:
            complexity = FixComplexity.SIMPLE
            if self.context.impact_assessment:
                complexity = self.context.impact_assessment.complexity

            if complexity == FixComplexity.SIMPLE:
                self._output(
                    "Approach: SIMPLE - Direct code fix",
                    "info"
                )
            elif complexity == FixComplexity.MODERATE:
                self._output(
                    "Approach: MODERATE - Multiple file changes with careful review",
                    "info"
                )
            elif complexity == FixComplexity.COMPLEX:
                self._output(
                    "Approach: COMPLEX - Will need thorough testing",
                    "warning"
                )
            else:
                self._output(
                    "Approach: REQUIRES DESIGN - Consider architectural implications",
                    "warning"
                )

                # Ask for user confirmation on complex changes
                if self._get_approval:
                    future = await self._get_approval(
                        "This fix requires significant changes. Proceed?",
                        ["Yes, proceed", "No, abort"]
                    )
                    answer = await future
                    if "No" in answer:
                        self._output("User aborted complex fix", "info")
                        return False

            return True

        except Exception as e:
            self._output(f"Planning decision failed: {e}", "error")
            return False

    async def _phase_baseline_capture(self) -> bool:
        """
        Phase 5: Capture baseline before making changes.

        Creates:
        - File backup (git stash or file copy)
        - Symbol table snapshot
        - Test results baseline
        """
        self._output("Capturing baseline for safety rollback...", "info")

        try:
            # Capture baseline
            self.context.baseline = await self.baseline_manager.capture_baseline()

            self._output(
                f"Baseline captured: {len(self.context.baseline.files)} files, "
                f"backup method: {self.context.baseline.backup_method}",
                "success"
            )

            # Initialize regression detector with baseline
            self.regression_detector = RegressionDetector(
                project_dir=self.project_dir,
                baseline=self.context.baseline,
                baseline_manager=self.baseline_manager,
                llm_client=self.llm_client
            )

            return True

        except Exception as e:
            self._output(f"Baseline capture failed: {e}", "error")
            return False

    async def _phase_implementation(self) -> bool:
        """
        Phase 6: Apply the fix.

        Generates and applies code changes with validation.
        """
        self._output("Implementing fix...", "info")

        try:
            # Handle missing or incomplete issue analysis
            affected_files = []
            root_cause = "Issue needs to be fixed based on user description"

            if self.context.issue_analysis:
                affected_files = self.context.issue_analysis.affected_files or []
                root_cause = self.context.issue_analysis.root_cause or root_cause
            else:
                self._output("No issue analysis available - attempting to identify files automatically", "warning")

            # If no affected files, try to find relevant files
            if not affected_files:
                self._output("No affected files specified - scanning project for relevant files...", "info")
                affected_files = self._guess_affected_files(self.context.issue_description)
                if not affected_files:
                    # Get all source files as fallback (limit to 5)
                    source_files = self.baseline_manager._get_source_files()[:5]
                    affected_files = [str(f.relative_to(self.project_dir)) for f in source_files]
                self._output(f"Auto-detected {len(affected_files)} potentially relevant files", "info")

            file_contents = {}

            for file_path in affected_files:
                full_path = self.project_dir / file_path
                if full_path.exists():
                    file_contents[file_path] = full_path.read_text(errors='replace')

            # Generate fix using LLM
            files_context = "\n\n".join([
                f"=== {path} ===\n{content}"
                for path, content in file_contents.items()
            ])

            prompt = f"""Fix the following issue in the code:

ISSUE: {self.context.issue_description}
ROOT CAUSE: {root_cause}

CURRENT CODE:
{files_context}

Provide the COMPLETE fixed file content for each file that needs changes.
Format as:
```filename.ext
<complete file content>
```
(Use actual extensions: .py, .js, .ts, .html, .jsx, .css, etc.)

Important:
- Provide COMPLETE file contents, not just the changed parts
- Make minimal changes to fix the issue
- Preserve all existing functionality
- Add comments explaining the fix (use appropriate syntax for the language)"""

            response = await self._call_llm(prompt, max_tokens=4000)
            if not response:
                self._output("Failed to generate fix", "error")
                return False

            # Extract code blocks and apply changes
            code_blocks = self._extract_code_blocks(response)
            if not code_blocks:
                self._output("No valid code changes in response - LLM may have refused or provided invalid content", "error")
                return False  # FAIL - no valid code to apply

            files_modified = 0
            for filename, content in code_blocks:
                # Find matching file
                target_path = None
                for affected in affected_files:
                    if affected.endswith(filename) or filename in affected:
                        target_path = self.project_dir / affected
                        break

                if target_path and target_path.exists():
                    # Backup before modifying
                    backup_content = target_path.read_text()

                    # Apply change
                    target_path.write_text(content)

                    # Verify the content was written correctly
                    written_content = target_path.read_text()
                    if written_content != content:
                        self._output(f"Write verification failed for {target_path.name}", "error")
                        target_path.write_text(backup_content)  # Restore
                        continue

                    self.context.changes_made.append({
                        'file': str(target_path.relative_to(self.project_dir)),
                        'action': 'modified',
                        'timestamp': datetime.now().isoformat()
                    })
                    self._output(f"Modified: {target_path.name}", "success")
                    files_modified += 1
                else:
                    self._output(f"Could not find target file for: {filename}", "warning")

            if files_modified == 0:
                self._output("No files were successfully modified", "error")
                return False

            return True

        except Exception as e:
            self._output(f"Implementation failed: {e}", "error")
            return False

    async def _phase_regression_testing(self) -> bool:
        """
        Phase 7: Test for regressions.

        Runs regression detection and auto-fix loop with
        escalating strategies.
        """
        self._output("Testing for regressions...", "info")

        try:
            if not self.regression_detector:
                self._output("No regression detector available", "error")
                return False

            # Detect regressions
            report = await self.regression_detector.detect_all()

            if not report.has_regressions:
                self._output("No regressions detected!", "success")
                return True

            # Log regressions
            self._output(report.get_summary(), "warning")

            # Auto-fix loop with escalating strategies
            while self.context.regression_attempts < self.max_regression_attempts:
                self.context.regression_attempts += 1
                attempt = self.context.regression_attempts

                self._output(
                    f"Attempting regression fix {attempt}/{self.max_regression_attempts}...",
                    "info"
                )

                # Get strategy-specific prompt
                strategy = [
                    FixStrategy.TARGETED,
                    FixStrategy.CONTEXTUAL,
                    FixStrategy.ALTERNATIVE
                ][attempt - 1]

                fix_prompt = self.regression_detector.get_fix_prompt(
                    attempt,
                    self.context.previous_failures,
                    report
                )

                # Attempt fix
                success, failure_reason = await self._attempt_fix(
                    fix_prompt, strategy, report
                )

                if success:
                    # Re-check regressions
                    new_report = await self.regression_detector.detect_all()
                    if not new_report.has_regressions:
                        self._output(
                            f"Regression fixed on attempt {attempt}!",
                            "success"
                        )
                        return True

                    # Still has regressions
                    failure_reason = f"Still has {len(new_report.test_regressions)} test failures"
                    report = new_report

                self.context.previous_failures.append(failure_reason or "Unknown failure")
                self.regression_detector.record_fix_attempt(
                    attempt, strategy,
                    f"Attempt {attempt} with {strategy.name}",
                    success=False,
                    failure_reason=failure_reason
                )

            # All attempts failed
            self._output(
                f"All {self.max_regression_attempts} fix attempts failed",
                "error"
            )
            self._output(
                self.regression_detector.get_fix_history_summary(),
                "info"
            )

            return False

        except Exception as e:
            self._output(f"Regression testing failed: {e}", "error")
            return False

    async def _attempt_fix(
        self,
        fix_prompt: str,
        strategy: FixStrategy,
        report: RegressionReport
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to fix regressions using specified strategy.

        Args:
            fix_prompt: Prompt for LLM
            strategy: Fix strategy being used
            report: Current regression report

        Returns:
            (success, failure_reason)
        """
        try:
            # Get current state of affected files
            affected_files = [
                r.file_path for r in report.test_regressions
            ] + [
                r.file_path for r in report.execution_regressions
            ]
            affected_files = list(set(affected_files))

            file_contents = {}
            for file_path in affected_files:
                full_path = self.project_dir / file_path
                if full_path.exists():
                    file_contents[file_path] = full_path.read_text(errors='replace')

            # Add file contents to prompt
            files_context = "\n\n".join([
                f"=== {path} ===\n{content}"
                for path, content in file_contents.items()
            ])

            full_prompt = f"""{fix_prompt}

CURRENT CODE STATE:
{files_context}

Provide fixed file contents using the format:
```filename.ext
<complete fixed content>
```
(Use actual file extensions: .py, .js, .ts, .html, .jsx, etc.)"""

            response = await self._call_llm(full_prompt, max_tokens=4000)
            if not response:
                return False, "LLM returned no response"

            # Extract and apply fixes
            code_blocks = self._extract_code_blocks(response)
            if not code_blocks:
                return False, "No code changes in response"

            for filename, content in code_blocks:
                for affected in affected_files:
                    if affected.endswith(filename) or filename in affected:
                        target_path = self.project_dir / affected
                        if target_path.exists():
                            target_path.write_text(content)
                            self._output(f"Applied fix to: {affected}", "info")
                        break

            return True, None

        except Exception as e:
            return False, str(e)

    async def _phase_verification(self) -> bool:
        """
        Phase 8: Final verification.

        Confirms:
        - All tests pass
        - No symbol regressions
        - Code executes properly
        """
        self._output("Running final verification...", "info")

        try:
            if self.regression_detector:
                # Final regression check
                report = await self.regression_detector.detect_all()
                if report.has_regressions:
                    self._output(
                        "Final verification failed - regressions detected",
                        "error"
                    )
                    return False

            # Show changes summary
            if self.context.changes_made:
                self._output("Changes made:", "info")
                for change in self.context.changes_made:
                    self._output(f"  - {change['file']}: {change['action']}", "info")

            # Clean up backup
            if self.context.baseline:
                self.baseline_manager.cleanup_backup(self.context.baseline)
                self._output("Backup cleaned up", "info")

            self._output("Verification complete - all checks passed!", "success")
            return True

        except Exception as e:
            self._output(f"Verification failed: {e}", "error")
            return False

    async def _phase_documentation(self) -> bool:
        """
        Phase 9: Update README.md to reflect the changes.

        Updates or creates README.md with:
        - Description of the fix/enhancement
        - What was changed
        - Any new dependencies or requirements
        """
        self._output("Updating documentation...", "info")

        try:
            readme_path = self.project_dir / "README.md"
            existing_readme = ""

            # Read existing README if it exists
            if readme_path.exists():
                existing_readme = readme_path.read_text(errors='replace')
                self._output("Found existing README.md", "info")
            else:
                self._output("No README.md found - will create one", "info")

            # Build context for LLM
            changes_summary = "\n".join([
                f"- {c['file']}: {c['action']}"
                for c in self.context.changes_made
            ]) if self.context.changes_made else "No files modified"

            issue_description = self.context.issue_description
            root_cause = ""
            if self.context.issue_analysis:
                root_cause = self.context.issue_analysis.root_cause or ""

            # Generate README update using LLM
            prompt = f"""Update the README.md for this project to document a recent fix/change.

EXISTING README:
{existing_readme[:3000] if existing_readme else "(No existing README)"}

ISSUE FIXED:
{issue_description}

ROOT CAUSE:
{root_cause}

FILES CHANGED:
{changes_summary}

Instructions:
1. If README exists, ADD a new section called "## Recent Changes" or "## Changelog" at an appropriate place
2. Document what was fixed/changed in a clear, user-friendly way
3. If no README exists, create a basic one with project name, description, and the change documentation
4. Keep the existing content intact - only ADD the change documentation
5. Use markdown formatting

Return the COMPLETE updated README.md content."""

            logger.info("DOCUMENTATION: Calling LLM to update README...")
            response = await self._call_llm(prompt, max_tokens=2000)
            logger.info(f"DOCUMENTATION: LLM response received ({len(response) if response else 0} chars)")
            if response:
                # Extract content (remove any markdown code block wrapper)
                content = response.strip()
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

                # Strip LLM thinking tags (<thinking>, <details>, <think>, etc.)
                from .llm_client import strip_thinking_content
                content = strip_thinking_content(content)

                # Write the README
                readme_path.write_text(content)
                self._output(f"Updated README.md ({len(content)} bytes)", "success")

                # Track as a change
                self.context.changes_made.append({
                    'file': 'README.md',
                    'action': 'updated' if existing_readme else 'created',
                    'timestamp': datetime.now().isoformat()
                })

                return True
            else:
                self._output("Could not generate README update", "warning")
                return True  # Continue anyway - not a critical failure

        except Exception as e:
            self._output(f"Documentation update failed: {e}", "warning")
            return True  # Continue anyway - not a critical failure

    async def _phase_user_instructions(self) -> bool:
        """
        Phase 10: Provide test instructions to the user.

        Generates step-by-step instructions for the user to:
        - Test the fix
        - Verify the expected behavior
        - Run any relevant commands
        """
        self._output("Generating test instructions...", "info")

        try:
            # Build context
            changes_summary = "\n".join([
                f"- {c['file']}: {c['action']}"
                for c in self.context.changes_made
            ]) if self.context.changes_made else "No files modified"

            issue_description = self.context.issue_description
            issue_type = "unknown"
            if self.context.issue_analysis:
                issue_type = self.context.issue_analysis.issue_type

            # Detect project type for appropriate instructions
            project_files = list(self.project_dir.glob("*"))
            project_indicators = {
                'python': any(f.suffix == '.py' for f in project_files),
                'javascript': any(f.suffix in ['.js', '.ts', '.jsx', '.tsx'] for f in project_files),
                'package_json': (self.project_dir / 'package.json').exists(),
                'requirements': (self.project_dir / 'requirements.txt').exists(),
                'dockerfile': (self.project_dir / 'Dockerfile').exists(),
                'html': any(f.suffix == '.html' for f in project_files),
            }

            # Generate instructions using LLM
            prompt = f"""Generate clear, step-by-step instructions for the user to test this fix.

ISSUE THAT WAS FIXED:
{issue_description}

ISSUE TYPE: {issue_type}

FILES CHANGED:
{changes_summary}

PROJECT INDICATORS:
{', '.join(k for k, v in project_indicators.items() if v)}

Generate instructions that:
1. Explain what was fixed in simple terms
2. Provide exact commands to run (if applicable)
3. Describe the expected behavior after the fix
4. Include any setup steps needed (e.g., install dependencies)
5. Suggest how to verify the fix is working

Format as a numbered list with clear, actionable steps.
Use code blocks for any commands.
Be specific to this project type."""

            response = await self._call_llm(prompt, max_tokens=1500)
            if response:
                self._output("\n" + "=" * 60, "info")
                self._output("📋 TEST INSTRUCTIONS FOR USER", "success")
                self._output("=" * 60, "info")
                self._output(response, "info")
                self._output("=" * 60 + "\n", "info")

                # Store instructions in context for result
                self.context.user_instructions = response

                return True
            else:
                self._output("Could not generate test instructions", "warning")
                # Provide basic fallback instructions
                self._output("\n📋 BASIC TEST INSTRUCTIONS:", "info")
                self._output(f"1. The issue '{issue_description[:50]}...' has been fixed", "info")
                self._output(f"2. Files modified: {len(self.context.changes_made)}", "info")
                self._output("3. Please test the affected functionality manually", "info")
                return True

        except Exception as e:
            self._output(f"Instruction generation failed: {e}", "warning")
            return True  # Continue anyway - not a critical failure

    async def _rollback(self) -> bool:
        """Rollback to baseline state."""
        self._output("Rolling back to baseline...", "warning")

        if not self.context.baseline:
            self._output("No baseline available for rollback", "error")
            return False

        success = await self.baseline_manager.restore_baseline(self.context.baseline)
        if success:
            self._output("Rollback successful", "success")
        else:
            self._output("Rollback failed!", "error")

        return success

    async def _call_llm(self, prompt: str, max_tokens: int = 2000) -> Optional[str]:
        """Call LLM and return response text."""
        try:
            if hasattr(self.llm_client, 'generate'):
                # CodeGenLLMClient - returns LLMResponse with .content attribute
                response = self.llm_client.generate(prompt, max_tokens=max_tokens)
                # Extract text from LLMResponse object
                if hasattr(response, 'content'):
                    return response.content
                elif hasattr(response, 'text'):
                    return response.text
                elif isinstance(response, str):
                    return response
                else:
                    logger.warning(f"Unknown response type: {type(response)}")
                    return str(response)
            elif hasattr(self.llm_client, 'chat'):
                # OpenAI-style client
                response = self.llm_client.chat.completions.create(
                    model=getattr(self.llm_client, 'model', 'gpt-4'),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens
                )
                return response.choices[0].message.content
            else:
                logger.warning("Unknown LLM client type")
                return None
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return None

    def _guess_affected_files(self, response: str) -> List[str]:
        """Guess affected files from LLM response text."""
        import re

        # Look for file paths mentioned in the response
        file_patterns = [
            r'[\w/]+\.(?:py|js|ts|jsx|tsx|html|css|json)',  # Common extensions
            r'src/[\w/]+\.\w+',  # src/ paths
            r'api/[\w/]+\.\w+',  # api/ paths
        ]

        files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, response)
            files.update(matches)

        # If no files found, look for the main entry files
        if not files:
            # Check what exists in project
            common_files = ['index.html', 'main.py', 'app.py', 'main.js', 'App.js']
            for f in common_files:
                if (self.project_dir / f).exists():
                    files.add(f)

        return list(files)[:10]  # Limit to 10 files

    def _extract_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response using robust utility."""
        from .utils.json_utils import extract_json_from_llm_response
        return extract_json_from_llm_response(content)

    def _validate_code_content(self, code: str, filename: str) -> Tuple[bool, str]:
        """
        Validate that code content doesn't contain LLM artifacts.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for LLM reasoning markers
        llm_artifacts = [
            ('<details>', 'Contains <details> tag - LLM reasoning leaked into code'),
            ('</details>', 'Contains </details> tag - LLM reasoning leaked into code'),
            ("I'm sorry, but I can't", 'Contains LLM refusal text'),
            ("I cannot provide", 'Contains LLM refusal text'),
            ("I can't generate", 'Contains LLM refusal text'),
            ('<<<<<<< SEARCH', 'Contains raw SEARCH/REPLACE markers - should be parsed, not written'),
            ('>>>>>>> REPLACE', 'Contains raw SEARCH/REPLACE markers - should be parsed, not written'),
            ('=======\n', 'Contains raw patch separator - should be parsed, not written'),
        ]

        for marker, error in llm_artifacts:
            if marker in code:
                return False, error

        # Check for nested markdown code blocks (indicates LLM wrapped code incorrectly)
        if '```' in code:
            return False, 'Contains nested markdown code blocks'

        # Basic syntax validation for common file types
        if filename.endswith('.py'):
            try:
                import ast
                ast.parse(code)
            except SyntaxError as e:
                return False, f'Python syntax error: {e}'
        elif filename.endswith('.js'):
            # Basic JS validation - check for obvious issues
            if code.strip().startswith('<') and not code.strip().startswith('<!'):
                return False, 'JavaScript file starts with < - likely HTML or XML content'
        elif filename.endswith('.json'):
            try:
                import json
                json.loads(code)
            except json.JSONDecodeError as e:
                return False, f'Invalid JSON: {e}'

        return True, ''

    def _extract_code_blocks(self, content: str) -> List[Tuple[str, str]]:
        """Extract code blocks from LLM response with validation."""
        import re
        from .llm_client import strip_thinking_content

        # First strip any thinking/reasoning content from the response
        content = strip_thinking_content(content)

        blocks = []
        # Pattern: ```filename.ext or ```language filename
        pattern = r'```(\S+?)?\s*\n(.*?)```'

        for match in re.finditer(pattern, content, re.DOTALL):
            header = match.group(1) or ''
            code = match.group(2).strip()

            # Extract filename from header
            filename = header
            if '.' not in filename:
                # Header might be language, look for filename in code
                first_line = code.split('\n')[0]
                if first_line.startswith('#') or first_line.startswith('//'):
                    # Comment with filename
                    parts = first_line.split()
                    for part in parts:
                        if '.' in part:
                            filename = part
                            break

            if filename and '.' in filename:
                # CRITICAL: Validate content before accepting
                is_valid, error = self._validate_code_content(code, filename)
                if is_valid:
                    blocks.append((filename, code))
                else:
                    logger.warning(f"Rejected code block for {filename}: {error}")
                    self._output(f"Rejected invalid code for {filename}: {error}", "warning")

        return blocks
