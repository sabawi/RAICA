"""
Universal Investigation-First Handler
======================================

Implements the Universal Investigation-First Pattern where ALL requests,
regardless of type, follow the same intelligent flow:

1. TRIAGE   - LLM determines what information it needs
2. GATHER   - Execute triage requests (file reads, commands, searches)
3. DECIDE   - LLM decides action WITH full context
4. ACT      - Execute the decided action
5. VERIFY   - Confirm success and report results

This eliminates:
- Speculative planning (no more CODE_GENERATE steps that get skipped)
- Classification routing (LLM figures it out from context)
- Special case handlers (one universal flow)

Token Savings: ~40-60% by avoiding speculative steps and skip logic.

Architecture Principle: LLM drives ALL decisions, RAICA executes blindly.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger(__name__)

# Context-First Architecture imports
try:
    from ..services.context_builder import ContextBuilder, Context
    from ..services.first_contact_template import build_first_contact_prompt, build_iteration_prompt
    from ..services.tool_details_provider import get_tool_details
    CONTEXT_FIRST_AVAILABLE = True
except ImportError:
    logger.warning("Context-First modules not available - using fallback mode")
    CONTEXT_FIRST_AVAILABLE = False


# =============================================================================
# TRIAGE PHASE - What information does the LLM need?
# =============================================================================

class TriageActionType(Enum):
    """Types of information-gathering actions during triage."""
    LIST_FILES = auto()      # List files in a directory
    READ_FILE = auto()       # Read contents of a file
    RUN_COMMAND = auto()     # Run a read-only shell command
    CHECK_TOOL = auto()      # Check if a tool/command is installed
    WEB_SEARCH = auto()      # Search the web for information
    READ_DOCS = auto()       # Read local documentation
    CHECK_PROJECT = auto()   # Get project structure and context
    CHECK_ENVIRONMENT = auto()  # Check environment variables, Python packages, etc.


@dataclass
class TriageAction:
    """A single triage action to gather information."""
    action_type: TriageActionType
    target: str                      # Path, command, query, etc.
    reason: str                      # Why this information is needed
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action_type': self.action_type.name,
            'target': self.target,
            'reason': self.reason,
            'parameters': self.parameters
        }


@dataclass
class TriageResult:
    """Result of a single triage action."""
    action: TriageAction
    success: bool
    output: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action': self.action.to_dict(),
            'success': self.success,
            'output': self.output[:2000] if self.output else '',
            'error': self.error
        }


# =============================================================================
# DECISION PHASE - What action should be taken?
# =============================================================================

class DecisionType(Enum):
    """Types of actions the LLM can decide to take."""
    RESPOND = auto()         # Answer directly (for questions)
    EXECUTE = auto()         # Run existing script/tool
    FIX = auto()             # Modify existing code (CODE_DEBUG)
    CREATE = auto()          # Create new code (CODE_GENERATION)
    INSTALL = auto()         # Install missing tool
    CONFIGURE = auto()       # Configure service/application
    INVESTIGATE = auto()     # Gather more information (read files, run commands, get tool details)
    SEARCH_MORE = auto()     # Need more information before deciding (deprecated - use INVESTIGATE)
    DELEGATE = auto()        # Hand off to specialist handler
    CANNOT_PROCEED = auto()  # Cannot fulfill request (explain why)


@dataclass
class Decision:
    """The LLM's decision on how to handle the request."""
    decision_type: DecisionType
    reasoning: str                   # Why this decision was made
    target: str = ""                 # What to execute/fix/create
    commands: List[str] = field(default_factory=list)  # Commands to run
    code_prompt: str = ""            # Prompt for code generation/fix
    response_text: str = ""          # Direct response (for RESPOND type)
    requires_approval: bool = True   # Whether user approval is needed
    requires_sudo: bool = False      # Whether sudo is needed
    execute_after_create: bool = False  # For CREATE: execute the script after creating it (for immediate actions)
    additional_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision_type': self.decision_type.name,
            'reasoning': self.reasoning,
            'target': self.target,
            'commands': self.commands,
            'code_prompt': self.code_prompt[:500] if self.code_prompt else '',
            'response_text': self.response_text[:500] if self.response_text else '',
            'requires_approval': self.requires_approval,
            'requires_sudo': self.requires_sudo
        }


# =============================================================================
# RESULT STRUCTURES
# =============================================================================

@dataclass
class UniversalHandlerResult:
    """Final result of the Universal Handler."""
    success: bool
    request: str
    decision: Optional[Decision] = None
    triage_results: List[TriageResult] = field(default_factory=list)
    execution_output: str = ""
    generated_files: List[str] = field(default_factory=list)
    error: Optional[str] = None
    phases_completed: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    tokens_saved_estimate: int = 0  # Estimated tokens saved vs old approach

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'request': self.request[:200],
            'decision': self.decision.to_dict() if self.decision else None,
            'triage_results_count': len(self.triage_results),
            'execution_output': self.execution_output[:1000] if self.execution_output else '',
            'generated_files': self.generated_files,
            'error': self.error,
            'phases_completed': self.phases_completed,
            'duration_seconds': self.duration_seconds,
            'tokens_saved_estimate': self.tokens_saved_estimate
        }


# =============================================================================
# EXECUTION STRATEGY - LLM-Driven Phase Selection
# =============================================================================

@dataclass
class RetryPolicy:
    """Retry policy for execution strategy."""
    enabled: bool
    max_retries: int = 3
    reason: str = ""


@dataclass
class ExecutionStrategy:
    """
    LLM-decided execution strategy for this request.

    Replaces hardcoded phase flow with intelligent strategy selection.
    """
    execution_type: str  # ONE_SHOT_ACTION, INVESTIGATIVE_TASK, CODE_MODIFICATION, etc.
    phases_needed: List[str]  # Which phases to execute
    retry_policy: RetryPolicy
    verification_strategy: str  # TRUST_EXIT_CODE, LLM_SEMANTIC, TEST_DRIVEN, etc.
    failure_handling: str  # REPORT_AND_STOP, RETRY_WITH_DIFFERENT_APPROACH, ROLLBACK_AND_RETRY
    reasoning: str  # Why this strategy was chosen

    def should_retry(self) -> bool:
        """Check if retries are allowed for this strategy."""
        return self.retry_policy.enabled

    def is_one_shot(self) -> bool:
        """Check if this is a one-shot action (no retries, no verification)."""
        return self.execution_type == "ONE_SHOT_ACTION"


# =============================================================================
# CALLBACKS
# =============================================================================

@dataclass
class UniversalHandlerCallbacks:
    """Callbacks for UI communication during universal handling."""
    on_phase_start: Optional[Callable[[str], Awaitable[None]]] = None
    on_triage_action: Optional[Callable[[TriageAction], Awaitable[None]]] = None
    on_triage_result: Optional[Callable[[TriageResult], Awaitable[None]]] = None
    on_decision: Optional[Callable[[Decision], Awaitable[None]]] = None
    on_approval_needed: Optional[Callable[[str, Decision], Awaitable[bool]]] = None
    on_output: Optional[Callable[[str, str], Awaitable[None]]] = None  # message, type
    on_error: Optional[Callable[[str], Awaitable[None]]] = None


# =============================================================================
# UNIVERSAL HANDLER - The Main Class
# =============================================================================

class UniversalHandler:
    """
    Universal Investigation-First Handler.

    ALL requests follow the same intelligent flow:

    1. TRIAGE: Ask LLM "What do you need to know to handle this?"
       - LLM requests: file listings, tool checks, web searches, etc.

    2. GATHER: Execute triage requests
       - Run commands, read files, search web
       - Collect all results into a context bundle

    3. DECIDE: Ask LLM "With this context, what action should be taken?"
       - LLM sees full picture before deciding
       - No more speculative planning!

    4. ACT: Execute the decided action
       - EXECUTE: Run existing script
       - FIX: Modify code (delegates to CodeDebugAgent)
       - CREATE: Generate code (delegates to CLICodingAgent)
       - RESPOND: Return answer directly
       - etc.

    5. VERIFY: Confirm success
       - Check results match user's intent
       - Report outcome

    This eliminates classification routing, speculative planning,
    and skip logic - saving ~40-60% tokens per request.
    """

    def __init__(
        self,
        llm_client: Any,
        project_dir: Path,
        callbacks: Optional[UniversalHandlerCallbacks] = None,
        system_executor: Optional[Any] = None,
        web_researcher: Optional[Any] = None,
        context_manager: Optional[Any] = None,
        allow_sudo: bool = False,
        max_triage_iterations: int = 3,
        max_act_iterations: int = 3
    ):
        """
        Initialize the Universal Handler.

        Args:
            llm_client: LLM client for intelligent decisions
            project_dir: Directory for project operations
            callbacks: UI callbacks
            system_executor: SystemExecutor for command execution
            web_researcher: WebResearcher for web searches
            context_manager: ContextManager for project context
            allow_sudo: Whether to allow sudo operations
            max_triage_iterations: Max rounds of triage (prevent infinite loops)
            max_act_iterations: Max rounds of DECIDE→ACT→VERIFY iteration (retry on failure)
        """
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)
        self.callbacks = callbacks or UniversalHandlerCallbacks()
        self.system_executor = system_executor
        self.web_researcher = web_researcher
        self.context_manager = context_manager
        self.allow_sudo = allow_sudo
        self.max_triage_iterations = max_triage_iterations

        # Context-First Architecture
        self.context_builder = ContextBuilder() if CONTEXT_FIRST_AVAILABLE else None
        self.first_contact_context: Optional[Context] = None
        self.iteration_count = 0
        self.max_act_iterations = max_act_iterations

        # Ensure project directory exists
        self.project_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # PHASE 0: STRATEGY SELECTION - LLM decides execution approach
    # =========================================================================

    async def _select_execution_strategy(self, request: str) -> ExecutionStrategy:
        """
        Ask LLM to analyze request and decide execution strategy.

        This replaces the hardcoded phase flow with LLM-driven decisions.
        The LLM decides:
        - What type of execution (ONE_SHOT_ACTION, INVESTIGATIVE_TASK, etc.)
        - Which phases are needed
        - Whether retries are allowed
        - Verification strategy

        Args:
            request: User's request text

        Returns:
            ExecutionStrategy with LLM's decisions
        """
        prompt = f"""Analyze this user request and decide the execution strategy.

USER REQUEST: {request}

Your task: Determine what type of execution this request requires.

EXECUTION TYPES:

1. ONE_SHOT_ACTION - **SINGLE** action with SIDE EFFECTS:
   - "Send this email" (one step: send)
   - "Post this tweet" (one step: post)
   - "Delete this file" (one step: delete)
   - "Download this URL" (one step: download)

   KEY: SINGLE action that changes external state!
   ⚠️ If request needs MULTIPLE STEPS, it's NOT ONE_SHOT!

   Examples of what is NOT ONE_SHOT:
   - "Research X and email results" → 2 steps (research + email) → INVESTIGATIVE_TASK
   - "Find data and save to file" → 2 steps (find + save) → INVESTIGATIVE_TASK
   - "Check status and notify me" → 2 steps (check + notify) → INVESTIGATIVE_TASK

   Phases: ["EXECUTE"]
   Retry: NO (will cause duplicates - email sent 3 times!)
   Verification: TRUST_EXIT_CODE (exit 0 = success, done!)

2. INVESTIGATIVE_TASK - Multi-step workflows (can end with side effect):
   - Check system status, read files, search for info
   - Diagnose issue, analyze logs, inspect config
   - Research, lookup, query (read-only)
   - **Multi-step tasks:** "Research X and email it", "Find data and save it"

   KEY: Multiple sequential steps, even if last step has side effect!

   Examples:
   - "Look up latest news and email it" → INVESTIGATIVE_TASK (research + email = 2 steps)
   - "Find all TODO items and save to file" → INVESTIGATIVE_TASK (find + save = 2 steps)
   - "Check server status and notify me" → INVESTIGATIVE_TASK (check + notify = 2 steps)

   Phases: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"]
   Retry: YES (each step can retry independently)
   Verification: LLM_SEMANTIC (did we accomplish the full workflow?)

3. CODE_MODIFICATION - Modify existing code:
   - Fix bug, add feature, improve code, refactor

   Phases: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"]
   Retry: YES (can rollback)
   Verification: TEST_DRIVEN (run tests)

4. RESOURCE_CREATION - Create new files/resources:
   - Create project, generate files

   Phases: ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"]
   Retry: YES (idempotent)
   Verification: EXISTENCE_CHECK

🚨 CRITICAL - MULTI-STEP vs SINGLE-STEP:

Count the steps needed:
1. One step? → ONE_SHOT_ACTION
   Examples: "Send email", "Post tweet", "Delete file"

2. Multiple steps? → INVESTIGATIVE_TASK (even if last step has side effects!)
   Examples:
   - "Research news AND email it" (2 steps: research + email)
   - "Find data AND save it" (2 steps: find + save)
   - "Check status AND notify me" (2 steps: check + notify)

⚠️ SIDE EFFECTS ALONE DON'T DETERMINE STRATEGY!
The NUMBER OF STEPS determines strategy:
- Single step with side effect → ONE_SHOT_ACTION
- Multiple steps (even if last has side effect) → INVESTIGATIVE_TASK
If NO → Choose based on read/write nature

EXAMPLES:

Request: "Send email to John"
{{
  "execution_type": "ONE_SHOT_ACTION",
  "phases_needed": ["EXECUTE"],
  "retry_policy": {{"enabled": false, "max_retries": 0, "reason": "Side effects - will send email multiple times if retried"}},
  "verification_strategy": "TRUST_EXIT_CODE",
  "failure_handling": "REPORT_AND_STOP",
  "reasoning": "Sending email has side effects. Must execute once only."
}}

Request: "Check if nginx is running"
{{
  "execution_type": "INVESTIGATIVE_TASK",
  "phases_needed": ["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"],
  "retry_policy": {{"enabled": true, "max_retries": 3, "reason": "Read-only, safe to retry"}},
  "verification_strategy": "LLM_SEMANTIC",
  "failure_handling": "RETRY_WITH_DIFFERENT_APPROACH",
  "reasoning": "Read-only status check, safe to retry."
}}

Return ONLY valid JSON, no other text."""

        try:
            # Use classification model for strategy selection (stronger model for critical decisions)
            response = await asyncio.to_thread(
                self.llm_client.generate_for_classification, prompt, max_tokens=600
            )
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON
            from ..utils.json_utils import extract_json_from_llm_response
            data = extract_json_from_llm_response(content)

            if data:
                return ExecutionStrategy(
                    execution_type=data['execution_type'],
                    phases_needed=data['phases_needed'],
                    retry_policy=RetryPolicy(**data['retry_policy']),
                    verification_strategy=data['verification_strategy'],
                    failure_handling=data['failure_handling'],
                    reasoning=data['reasoning']
                )
            else:
                # Fallback: Conservative approach with retries
                logger.warning("Failed to parse execution strategy, using conservative fallback")
                return ExecutionStrategy(
                    execution_type="INVESTIGATIVE_TASK",
                    phases_needed=["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"],
                    retry_policy=RetryPolicy(enabled=True, max_retries=3, reason="Fallback strategy"),
                    verification_strategy="LLM_SEMANTIC",
                    failure_handling="RETRY_WITH_DIFFERENT_APPROACH",
                    reasoning="Fallback - could not determine strategy"
                )

        except Exception as e:
            logger.error(f"Strategy selection failed: {e}")
            # Fallback
            return ExecutionStrategy(
                execution_type="INVESTIGATIVE_TASK",
                phases_needed=["TRIAGE", "GATHER", "DECIDE", "ACT", "VERIFY"],
                retry_policy=RetryPolicy(enabled=True, max_retries=3, reason="Error in strategy selection"),
                verification_strategy="LLM_SEMANTIC",
                failure_handling="RETRY_WITH_DIFFERENT_APPROACH",
                reasoning=f"Error selecting strategy: {e}"
            )

    async def handle(self, request: str) -> UniversalHandlerResult:
        """
        Handle any request using the Universal Investigation-First pattern.

        Args:
            request: User's request text

        Returns:
            UniversalHandlerResult with full execution details
        """
        start_time = datetime.now()
        result = UniversalHandlerResult(success=False, request=request)

        try:
            await self._output(f"Universal Handler: Processing request...", "info")

            # ═══════════════════════════════════════════════════════════════
            # PHASE 0: PREPARATION - Build context (if Context-First available)
            # ═══════════════════════════════════════════════════════════════
            user_tools_context = ""
            if CONTEXT_FIRST_AVAILABLE and self.context_builder and self.iteration_count == 0:
                await self._output("Building context (system, user, tools)...", "info")
                try:
                    self.first_contact_context = await self.context_builder.build_context(
                        request=request,
                        project_dir=self.project_dir if self.project_dir.exists() else None
                    )

                    # Add user tools catalog to context
                    if self.first_contact_context.user_tools and self.first_contact_context.user_tools.tools:
                        tools_catalog = self.first_contact_context.user_tools.tools
                        comm_tools = self.first_contact_context.user_tools.communication_tools

                        user_tools_context = f"\n\n═══ RAICA USER TOOLS ═══\n"
                        user_tools_context += f"You have access to {len(tools_catalog)} user-defined tools on the RAICA server.\n"
                        user_tools_context += f"Communication hub tools: {', '.join(comm_tools)}\n\n"

                        for tool_name, tool_info in sorted(tools_catalog.items()):
                            category = tool_info.get('category', 'utility')
                            desc = tool_info.get('description', 'No description')
                            marker = "⭐" if tool_name in comm_tools else " "
                            user_tools_context += f"{marker} [{category}] {tool_name}: {desc}\n"

                        user_tools_context += f"\n💡 To USE a tool, first request details:\n"
                        user_tools_context += f"   Decision: INVESTIGATE\n"
                        user_tools_context += f"   Commands: [\"get_tool_details <tool_name>\"]\n"
                        user_tools_context += f"   This returns the full parameter schema.\n\n"

                        await self._output(f"Found {len(tools_catalog)} user tools", "info")
                except Exception as e:
                    logger.warning(f"Failed to build context: {e}")

            self.iteration_count += 1

            # ═══════════════════════════════════════════════════════════════
            # PHASE 0.5: STRATEGY SELECTION - Ask LLM how to execute this request
            # ═══════════════════════════════════════════════════════════════
            await self._output("Selecting execution strategy...", "info")
            strategy = await self._select_execution_strategy(request)
            await self._output(
                f"Strategy: {strategy.execution_type} (retry: {strategy.retry_policy.enabled})",
                "info"
            )
            logger.info(f"Execution strategy: {strategy.execution_type}, reasoning: {strategy.reasoning}")

            # ═══════════════════════════════════════════════════════════════
            # ONE-SHOT ACTION: Intelligent retry with different approaches
            # ═══════════════════════════════════════════════════════════════
            if strategy.is_one_shot():
                await self._output("ONE-SHOT ACTION: Using intelligent retry loop", "info")

                # Skip TRIAGE/GATHER for first attempt
                # Use intelligent retry loop: DECIDE → ACT → INVESTIGATE → DECIDE (different approach)

                error_context = ""
                decision = None
                max_one_shot_attempts = 3

                for attempt in range(1, max_one_shot_attempts + 1):
                    if attempt > 1:
                        await self._output(f"Attempt {attempt}/{max_one_shot_attempts} with different approach...", "info")

                    # ═══════════════════════════════════════════════════════════
                    # DECIDE: LLM decides what to try (with error context from previous attempt)
                    # ═══════════════════════════════════════════════════════════
                    await self._phase_start("DECIDE")
                    result.phases_completed.append(f"DECIDE_START_ATTEMPT{attempt}")

                    # Build context with error information from previous attempt
                    one_shot_context = user_tools_context if user_tools_context else ""
                    one_shot_context += f"\n\n🚨 ONE-SHOT ACTION (Attempt {attempt}/{max_one_shot_attempts}):"
                    one_shot_context += "\nThis action has SIDE EFFECTS. Do NOT retry the same command!"
                    one_shot_context += "\nIf previous attempt failed, analyze the error and try a DIFFERENT approach."

                    # Add error context from previous failed attempt
                    if error_context:
                        one_shot_context += error_context

                    decision = await self._decide(request, one_shot_context)
                    result.decision = decision

                    if self.callbacks.on_decision:
                        await self.callbacks.on_decision(decision)

                    await self._output(f"Decision: {decision.decision_type.name}", "info")
                    result.phases_completed.append(f"DECIDE_COMPLETE_ATTEMPT{attempt}")

                    # ═══════════════════════════════════════════════════════════
                    # ACT: Execute the decision
                    # ═══════════════════════════════════════════════════════════
                    await self._phase_start("ACT")
                    result.phases_completed.append(f"ACT_START_ATTEMPT{attempt}")

                    # Get approval if needed
                    if decision.requires_approval and self.callbacks.on_approval_needed:
                        approved = await self.callbacks.on_approval_needed(
                            f"Execute {decision.decision_type.name}: {decision.target or decision.reasoning[:50]}?",
                            decision
                        )
                        if not approved:
                            result.error = "User did not approve action"
                            await self._output("Action not approved by user", "warning")
                            return result

                    # Execute with extended timeout for one-shot actions
                    act_start_time = datetime.now()
                    act_result = await self._act(decision, is_one_shot=True)
                    act_duration = (datetime.now() - act_start_time).total_seconds()

                    result.execution_output = act_result.get('output', '')
                    result.generated_files = act_result.get('files', [])
                    result.success = act_result.get('success', False)
                    result.phases_completed.append(f"ACT_COMPLETE_ATTEMPT{attempt}")

                    # ═══════════════════════════════════════════════════════════
                    # VERIFY: Check if action succeeded
                    # ═══════════════════════════════════════════════════════════
                    if result.success:
                        await self._output(f"✅ ONE-SHOT ACTION completed successfully on attempt {attempt}", "success")
                        result.duration_seconds = (datetime.now() - start_time).total_seconds()
                        return result

                    # ═══════════════════════════════════════════════════════════
                    # INVESTIGATE: Action failed - prepare error context for LLM
                    # ═══════════════════════════════════════════════════════════
                    await self._output(f"❌ Attempt {attempt} failed, investigating...", "warning")
                    result.phases_completed.append(f"INVESTIGATE_START_ATTEMPT{attempt}")

                    # Capture complete error information
                    error_info = {
                        'attempt': attempt,
                        'command': decision.commands if decision.commands else decision.target,
                        'decision_type': decision.decision_type.name,
                        'output': act_result.get('output', ''),
                        'duration': act_duration,
                        'error_detected': not result.success
                    }

                    # Format error context for LLM
                    error_context = f"""

🚨 PREVIOUS ATTEMPT {attempt} FAILED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Decision Type: {error_info['decision_type']}
Command/Target: {error_info['command']}
Duration: {error_info['duration']:.1f} seconds
Output/Error: {error_info['output'][:500] if error_info['output'] else '(no output)'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 ANALYZE THIS FAILURE:
1. What went wrong?
2. Was the action partially successful? (e.g., email sent but command timed out)
3. What is a DIFFERENT approach to accomplish the task?

⚠️ CRITICAL: Do NOT retry the same command if it has side effects!
   - If this was an email and it might have been sent, try a DIFFERENT verification approach
   - If this was a deletion and it might have succeeded, try checking if file exists
   - Always choose a DIFFERENT tool/method/approach for retry

DIFFERENT APPROACHES TO CONSIDER:
- Different command (mail → sendmail → mutt → Python script)
- Different parameters (--no-wait, --timeout=300, etc.)
- Different tool entirely (system command → Python script → RAICA user tool)
- Verification approach (check if action already completed instead of retrying)
- CREATE a custom script with better error handling

What should we try next?
"""

                    await self._output(f"Error details captured, will try different approach", "info")
                    result.phases_completed.append(f"INVESTIGATE_COMPLETE_ATTEMPT{attempt}")

                    # If this was the last attempt, exit with failure
                    if attempt >= max_one_shot_attempts:
                        result.error = f"Failed after {max_one_shot_attempts} attempts with different approaches"
                        await self._output(f"❌ ONE-SHOT ACTION failed after {max_one_shot_attempts} attempts", "error")
                        result.duration_seconds = (datetime.now() - start_time).total_seconds()
                        return result

                    # Loop continues - LLM will see error_context and decide different approach

                # Should not reach here, but just in case
                result.duration_seconds = (datetime.now() - start_time).total_seconds()
                return result

            # ═══════════════════════════════════════════════════════════════
            # FULL FLOW: TRIAGE → GATHER → DECIDE → ACT → VERIFY (with retries)
            # ═══════════════════════════════════════════════════════════════
            await self._output("FULL FLOW: Using complete investigation-first pattern", "info")

            # ═══════════════════════════════════════════════════════════════
            # PHASE 1: TRIAGE - What information do we need?
            # ═══════════════════════════════════════════════════════════════
            await self._phase_start("TRIAGE")
            result.phases_completed.append("TRIAGE_START")

            all_triage_results: List[TriageResult] = []
            triage_iteration = 0

            while triage_iteration < self.max_triage_iterations:
                triage_iteration += 1
                await self._output(f"Triage iteration {triage_iteration}...", "info")

                # Ask LLM what information it needs
                triage_actions = await self._triage(request, all_triage_results)

                if not triage_actions:
                    await self._output("Triage complete - LLM has enough information", "info")
                    break

                # ═══════════════════════════════════════════════════════════
                # PHASE 2: GATHER - Execute triage requests
                # ═══════════════════════════════════════════════════════════
                await self._phase_start("GATHER")

                for action in triage_actions:
                    if self.callbacks.on_triage_action:
                        await self.callbacks.on_triage_action(action)

                    await self._output(f"  Gathering: {action.action_type.name} - {action.target}", "info")
                    triage_result = await self._execute_triage_action(action)
                    all_triage_results.append(triage_result)

                    if self.callbacks.on_triage_result:
                        await self.callbacks.on_triage_result(triage_result)

            result.triage_results = all_triage_results
            result.phases_completed.append("TRIAGE_COMPLETE")
            result.phases_completed.append("GATHER_COMPLETE")

            # Build context from all triage results
            gathered_context = self._build_context(all_triage_results)

            # Prepend user tools context (if available)
            if user_tools_context:
                gathered_context = user_tools_context + "\n" + gathered_context

            await self._output(f"Gathered {len(all_triage_results)} pieces of information", "info")

            # ═══════════════════════════════════════════════════════════════
            # ITERATION LOOP: DECIDE → ACT → VERIFY (with retry on failure)
            # ═══════════════════════════════════════════════════════════════
            act_iteration = 0
            last_error = None
            decision = None

            # Use strategy's max_retries if retries enabled, otherwise use default
            max_iterations = strategy.retry_policy.max_retries if strategy.should_retry() else self.max_act_iterations

            while act_iteration < max_iterations:
                act_iteration += 1

                if act_iteration > 1:
                    await self._output(f"Retry attempt {act_iteration}/{max_iterations}...", "info")

                # ═══════════════════════════════════════════════════════════
                # PHASE 3: DECIDE - What action should be taken?
                # ═══════════════════════════════════════════════════════════
                await self._phase_start("DECIDE")
                result.phases_completed.append(f"DECIDE_START_ITER{act_iteration}")

                # Include last_error in context for retry
                decision_context = gathered_context
                if last_error:
                    decision_context += f"\n\n🚨 PREVIOUS ATTEMPT FAILED:\n{last_error}\n\nBased on this failure, choose a different approach."

                decision = await self._decide(request, decision_context)
                result.decision = decision

                if self.callbacks.on_decision:
                    await self.callbacks.on_decision(decision)

                await self._output(
                    f"Decision: {decision.decision_type.name} - {decision.reasoning[:100]}...",
                    "info"
                )
                result.phases_completed.append(f"DECIDE_COMPLETE_ITER{act_iteration}")

                # ═══════════════════════════════════════════════════════════
                # PHASE 4: ACT - Execute the decision
                # ═══════════════════════════════════════════════════════════
                await self._phase_start("ACT")
                result.phases_completed.append(f"ACT_START_ITER{act_iteration}")

                # Get approval if needed
                if decision.requires_approval and self.callbacks.on_approval_needed:
                    approved = await self.callbacks.on_approval_needed(
                        f"Execute {decision.decision_type.name}: {decision.target or decision.reasoning[:50]}?",
                        decision
                    )
                    if not approved:
                        result.error = "User did not approve action"
                        await self._output("Action not approved by user", "warning")
                        return result

                # Execute the decision
                act_result = await self._act(decision)
                result.execution_output = act_result.get('output', '')
                result.generated_files = act_result.get('files', [])
                result.success = act_result.get('success', False)
                result.phases_completed.append(f"ACT_COMPLETE_ITER{act_iteration}")

                # ═══════════════════════════════════════════════════════════
                # PHASE 5: VERIFY - Confirm success
                # ═══════════════════════════════════════════════════════════
                await self._phase_start("VERIFY")
                result.phases_completed.append(f"VERIFY_START_ITER{act_iteration}")

                verification = await self._verify(request, decision, act_result)

                # CRITICAL: Verification result OVERRIDES act_result
                if verification['success']:
                    result.success = True
                    result.error = None
                    result.phases_completed.append(f"VERIFY_COMPLETE_ITER{act_iteration}")
                    await self._output(f"✅ Verification SUCCESS on attempt {act_iteration}", "success")
                    break  # Exit iteration loop - SUCCESS!
                else:
                    # Verification FAILED
                    result.success = False

                    # Build comprehensive retry context that includes what was ACCOMPLISHED
                    error_msg = verification.get('error', 'Verification failed')

                    # For INVESTIGATE that succeeded but task incomplete, include what we learned
                    if decision.decision_type == DecisionType.INVESTIGATE and act_result.get('success', False):
                        # Investigation succeeded - we have new information!
                        investigation_output = act_result.get('output', '')[:500]  # First 500 chars
                        last_error = f"""✅ ACCOMPLISHED: {decision.reasoning}

INFORMATION OBTAINED:
{investigation_output}

⚠️ TASK STATUS: {error_msg}

🚨 CRITICAL - DO NOT REPEAT:
- You already have the information from the investigation above
- Do NOT investigate the same tool again
- NEXT ACTION: Use the information you now have to proceed (e.g., EXECUTE the tool)

What should you do next to complete the original request?"""
                    else:
                        # Regular failure - use standard error
                        last_error = error_msg

                    result.error = last_error
                    result.phases_completed.append(f"VERIFY_FAILED_ITER{act_iteration}")

                    if act_iteration < max_iterations:
                        await self._output(
                            f"❌ Verification FAILED on attempt {act_iteration}: {last_error}",
                            "warning"
                        )
                        await self._output(
                            f"Will retry with different approach (attempt {act_iteration + 1}/{max_iterations})...",
                            "info"
                        )
                    else:
                        await self._output(
                            f"❌ Verification FAILED after {max_iterations} attempts: {last_error}",
                            "error"
                        )

            # End of iteration loop

            # Calculate token savings estimate
            result.tokens_saved_estimate = self._estimate_token_savings(
                len(all_triage_results), decision
            )

            await self._output(
                f"Request handled: {'SUCCESS' if result.success else 'FAILED'} "
                f"(estimated {result.tokens_saved_estimate} tokens saved)",
                "success" if result.success else "error"
            )

        except Exception as e:
            logger.exception("Universal handler error")
            result.error = str(e)
            await self._output(f"Error: {e}", "error")

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result

    # =========================================================================
    # PHASE 1: TRIAGE
    # =========================================================================

    async def _triage(
        self,
        request: str,
        previous_results: List[TriageResult]
    ) -> List[TriageAction]:
        """
        Ask LLM what information it needs to handle this request.

        Args:
            request: User's request
            previous_results: Results from previous triage iterations

        Returns:
            List of triage actions to execute
        """
        # Build context from previous results
        prev_context = ""
        if previous_results:
            prev_context = "\n\nINFORMATION ALREADY GATHERED:\n"
            for tr in previous_results:
                prev_context += f"\n[{tr.action.action_type.name}] {tr.action.target}:\n"
                prev_context += f"{tr.output[:500]}...\n" if len(tr.output) > 500 else f"{tr.output}\n"

        prompt = f"""You are analyzing a user request to determine what information you need.

USER REQUEST: {request}

PROJECT DIRECTORY: {self.project_dir}
{prev_context}

═══════════════════════════════════════════════════════════════════════════════
TRIAGE PHASE: What information do you need to handle this request?
═══════════════════════════════════════════════════════════════════════════════

Available triage actions:
- LIST_FILES: List files in a directory (target: path, parameters: {{"pattern": "*.py"}})
- READ_FILE: Read contents of a file (target: file path)
- RUN_COMMAND: Run a read-only shell command (target: command)
- CHECK_TOOL: Check if a tool is installed (target: tool name)
- WEB_SEARCH: Search the web (target: search query)
- CHECK_PROJECT: Get project structure (target: project path)
- CHECK_ENVIRONMENT: Check env vars or packages (target: what to check)

RULES:
1. Only request information you ACTUALLY NEED to decide how to handle the request
2. Be efficient - don't request redundant information
3. If you have enough information from previous results, return an empty array []
4. Focus on answering: "Do I have what I need to fulfill this request?"

🚨 CRITICAL - FOR SYSTEM OPERATIONS (email, download, file operations):
**ALWAYS check if relevant system commands are available BEFORE deciding!**
**When a needed system tool is not available AND installing IS AN OPTION, TRY TO INSTALL IT FIRST!**
**IF INSTALLING IS NOT AN OPTION, CREATE A SCRIPT TO PERFORM THE ACTION!**

Examples:
- Email request → CHECK_TOOL for "mail", "sendmail", "msmtp", or "mutt"  to know if shell command available
- Download request → CHECK_TOOL for "curl", "wget", "aria2c" to know which to use
- Archive request → CHECK_TOOL for "tar", "zip", "unzip" to know which is available

This information is REQUIRED to decide between EXECUTE (use system command) vs CREATE (write script)!

Return JSON array of triage actions (or empty array if you have enough info):
[
    {{"action_type": "CHECK_TOOL", "target": "mail", "reason": "Check if mail command available for sending email"}},
    {{"action_type": "CHECK_TOOL", "target": "sendmail", "reason": "Fallback email tool if mail not available"}},
    {{"action_type": "LIST_FILES", "target": "{self.project_dir}", "reason": "See what scripts exist", "parameters": {{"pattern": "*.py"}}}}
]

Return ONLY the JSON array, no other text."""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate, prompt, max_tokens=800
            )
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON array
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                from ..utils.json_utils import sanitize_json
                actions_data = json.loads(sanitize_json(json_match.group()))

                actions = []
                action_type_map = {
                    'LIST_FILES': TriageActionType.LIST_FILES,
                    'READ_FILE': TriageActionType.READ_FILE,
                    'RUN_COMMAND': TriageActionType.RUN_COMMAND,
                    'CHECK_TOOL': TriageActionType.CHECK_TOOL,
                    'WEB_SEARCH': TriageActionType.WEB_SEARCH,
                    'READ_DOCS': TriageActionType.READ_DOCS,
                    'CHECK_PROJECT': TriageActionType.CHECK_PROJECT,
                    'CHECK_ENVIRONMENT': TriageActionType.CHECK_ENVIRONMENT,
                }

                for data in actions_data:
                    action_type_str = data.get('action_type', '').upper()
                    if action_type_str in action_type_map:
                        actions.append(TriageAction(
                            action_type=action_type_map[action_type_str],
                            target=data.get('target', ''),
                            reason=data.get('reason', ''),
                            parameters=data.get('parameters', {})
                        ))

                return actions

            return []  # No valid JSON found, assume triage complete

        except Exception as e:
            logger.error(f"Triage phase failed: {e}")
            # Return basic triage on failure
            return [
                TriageAction(
                    action_type=TriageActionType.LIST_FILES,
                    target=str(self.project_dir),
                    reason="Basic project exploration",
                    parameters={"pattern": "*"}
                )
            ]

    async def _execute_triage_action(self, action: TriageAction) -> TriageResult:
        """Execute a single triage action and return the result."""
        try:
            output = ""

            if action.action_type == TriageActionType.LIST_FILES:
                pattern = action.parameters.get('pattern', '*')
                path = Path(action.target) if action.target else self.project_dir
                try:
                    if pattern == '*':
                        files = list(path.iterdir())
                    else:
                        files = list(path.glob(pattern))

                    # Format output with file sizes
                    file_info = []
                    for f in sorted(files)[:50]:  # Limit to 50 files
                        try:
                            size = f.stat().st_size if f.is_file() else 0
                            ftype = "DIR" if f.is_dir() else f"{size} bytes"
                            file_info.append(f"  {f.name} ({ftype})")
                        except:
                            file_info.append(f"  {f.name}")

                    output = f"Files in {path}:\n" + "\n".join(file_info) if file_info else "No files found"
                except Exception as e:
                    output = f"Error listing files: {e}"

            elif action.action_type == TriageActionType.READ_FILE:
                try:
                    file_path = Path(action.target)
                    if file_path.exists():
                        content = file_path.read_text()[:5000]  # Limit to 5000 chars
                        output = f"Contents of {file_path.name}:\n{content}"
                    else:
                        output = f"File not found: {action.target}"
                except Exception as e:
                    output = f"Error reading file: {e}"

            elif action.action_type == TriageActionType.RUN_COMMAND:
                if self.system_executor:
                    result = await self.system_executor.execute(
                        action.target,
                        timeout=30,
                        require_approval=False  # Triage commands are read-only
                    )
                    output = result.stdout if result.success else f"Error: {result.stderr}"
                else:
                    # Fallback: direct execution for read-only commands
                    import subprocess
                    try:
                        result = subprocess.run(
                            action.target,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        output = result.stdout or result.stderr
                    except Exception as e:
                        output = f"Command error: {e}"

            elif action.action_type == TriageActionType.CHECK_TOOL:
                import subprocess
                try:
                    result = subprocess.run(
                        f"which {action.target} 2>/dev/null || type {action.target} 2>/dev/null",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        output = f"Tool '{action.target}' is installed: {result.stdout.strip()}"
                    else:
                        output = f"Tool '{action.target}' is NOT installed"
                except Exception as e:
                    output = f"Error checking tool: {e}"

            elif action.action_type == TriageActionType.WEB_SEARCH:
                if self.web_researcher:
                    result = await self.web_researcher.search(action.target)
                    output = result.get_context_for_llm() if result.success else f"Search failed: {result.error}"
                else:
                    output = "Web search not available"

            elif action.action_type == TriageActionType.CHECK_PROJECT:
                if self.context_manager:
                    try:
                        ctx = self.context_manager.get_file_structure_context(include_symbols=True)
                        output = ctx if ctx else "No project context available"
                    except:
                        output = "Could not get project context"
                else:
                    # Fallback: basic file listing
                    try:
                        files = list(self.project_dir.rglob('*'))[:100]
                        output = "Project files:\n" + "\n".join([str(f.relative_to(self.project_dir)) for f in files if f.is_file()])
                    except Exception as e:
                        output = f"Error scanning project: {e}"

            elif action.action_type == TriageActionType.CHECK_ENVIRONMENT:
                import subprocess
                try:
                    if 'pip' in action.target.lower() or 'package' in action.target.lower():
                        result = subprocess.run(
                            "pip list 2>/dev/null | head -30",
                            shell=True, capture_output=True, text=True, timeout=15
                        )
                        output = f"Installed packages:\n{result.stdout}"
                    elif 'env' in action.target.lower():
                        result = subprocess.run(
                            "env | grep -v PASSWORD | grep -v SECRET | grep -v KEY | head -30",
                            shell=True, capture_output=True, text=True, timeout=10
                        )
                        output = f"Environment (sanitized):\n{result.stdout}"
                    else:
                        output = f"Unknown environment check: {action.target}"
                except Exception as e:
                    output = f"Environment check error: {e}"

            else:
                output = f"Unknown triage action type: {action.action_type}"

            return TriageResult(action=action, success=True, output=output)

        except Exception as e:
            logger.error(f"Triage action failed: {e}")
            return TriageResult(action=action, success=False, output="", error=str(e))

    def _build_context(self, triage_results: List[TriageResult]) -> str:
        """Build a context string from all triage results."""
        if not triage_results:
            return "No information gathered."

        sections = []
        for tr in triage_results:
            section = f"═══ {tr.action.action_type.name}: {tr.action.target} ═══\n"
            section += f"Reason: {tr.action.reason}\n"
            if tr.success:
                section += f"Result:\n{tr.output}\n"
            else:
                section += f"FAILED: {tr.error}\n"
            sections.append(section)

        return "\n".join(sections)

    # =========================================================================
    # PHASE 3: DECIDE
    # =========================================================================

    async def _decide(self, request: str, context: str) -> Decision:
        """
        Ask LLM to decide what action to take based on gathered context.

        Args:
            request: User's request
            context: Gathered context from triage phase

        Returns:
            Decision object with action details
        """
        prompt = f"""Based on the gathered information, decide how to handle this request.

USER REQUEST: {request}

PROJECT DIRECTORY: {self.project_dir}

GATHERED INFORMATION:
{context}

═══════════════════════════════════════════════════════════════════════════════
DECISION PHASE: What action should be taken?
═══════════════════════════════════════════════════════════════════════════════

Available decision types:
- EXECUTE: Run commands/scripts (shell commands, existing scripts, system tools)
- INVESTIGATE: Gather more information (get_tool_details <tool_name>, read files, run diagnostic commands)
- FIX: Modify existing code to fix/improve it
- CREATE: Create new code/files (when nothing suitable exists)
- INSTALL: Install a missing tool/package first, then proceed
- RESPOND: Answer a question directly
- CANNOT_PROCEED: ONLY use when request is fundamentally impossible

🚨🚨🚨 CRITICAL: NEVER USE CANNOT_PROCEED WITHOUT CHECKING USER TOOLS FIRST! 🚨🚨🚨

**BEFORE choosing CANNOT_PROCEED, you MUST check if any RAICA USER TOOLS can help!**

1. **Look at the "RAICA USER TOOLS" section in gathered information**
   - Do you see ANY tool that might help with this request?
   - Examples: raica_research_agent (web search/research), secure_email_sender (email), pdf_generator (PDF), etc.

2. **If you see a relevant tool in the catalog:**
   ✅ Use INVESTIGATE with "get_tool_details <tool_name>" to learn how to use it
   ❌ DO NOT use CANNOT_PROCEED just because you don't know the parameters yet!

   Example:
   - User: "look up latest news"
   - You see: raica_research_agent in user tools catalog
   - CORRECT: INVESTIGATE with "get_tool_details raica_research_agent"
   - WRONG: CANNOT_PROCEED (you haven't tried the tool yet!)

3. **CANNOT_PROCEED is ONLY for:**
   - Illegal requests (hack into systems, bypass security)
   - Impossible requests (violate laws of physics, time travel)
   - Outside agent capabilities (physical world actions like "make me a sandwich")

   **NOT for:**
   - "I don't know the tool parameters" → Use INVESTIGATE!
   - "Tool might not be available" → Use INVESTIGATE to check!
   - "Not sure how to proceed" → Use INVESTIGATE to learn!

**The user tools catalog shows AVAILABLE tools. If a tool is listed, you CAN use it - just INVESTIGATE to get details first!**

🚨🚨🚨 CRITICAL DECISION RULES - READ CAREFULLY 🚨🚨🚨

1. **INVESTIGATE**: Use when you need MORE INFORMATION before acting:

   **USE CASE 1: Getting User Tool Details (MOST COMMON!)**
   - You see a tool name in "RAICA USER TOOLS" catalog but don't know its parameters
   - Command format: "get_tool_details <tool_name>"
   - This gives you the full parameter schema so you can use the tool

   Examples:
   - See "raica_research_agent" → INVESTIGATE with "get_tool_details raica_research_agent"
   - See "secure_email_sender" → INVESTIGATE with "get_tool_details secure_email_sender"
   - See "pdf_generator" → INVESTIGATE with "get_tool_details pdf_generator"

   **After getting tool details, your NEXT decision should use the tool!**

   **USE CASE 2: Diagnostic Commands for Retries**
   - Previous command failed with unclear error
   - Need to learn correct syntax/options

   Examples:
   - "mail: invalid option" → INVESTIGATE with "mail --help"
   - "curl: unknown flag" → INVESTIGATE with "curl --help"

2. **EXECUTE**: Use for IMMEDIATE ACTIONS that can be accomplished via:
   - **RAICA USER TOOLS:** Call user tools with their parameters (after getting details via INVESTIGATE!)
   - Shell commands: ANY command available on the system (mail, curl, wget, grep, find, sendmail, git, docker, etc.)
   - Existing project scripts: Scripts already in the project directory
   - System tools: Any installed command-line tool

   IMPORTANT: Don't limit yourself to a predefined list of commands. Use whatever shell command accomplishes the task.

   Examples (shell commands):
   - "send email to John" → EXECUTE with mail/sendmail command
   - "download file from URL" → EXECUTE with curl/wget command
   - "check Gmail for bills" → EXECUTE existing script if found
   - "search for files containing 'TODO'" → EXECUTE with grep command
   - "compress this directory" → EXECUTE with tar command

   Examples (user tools - after INVESTIGATE):
   - "look up latest news" → After INVESTIGATE: EXECUTE raica_research_agent with {{"query": "latest news", "task_type": "news_lookup"}}
   - "send professional email" → After INVESTIGATE: EXECUTE secure_email_sender with required parameters
   - "generate PDF report" → After INVESTIGATE: EXECUTE pdf_generator with content and options

3. **FIX**: Use if existing code exists but needs modifications

4. **CREATE**: Use when NO suitable approach exists AND user wants a REUSABLE script/tool:
   - User asks: "write a script that...", "create a program to...", "make a tool that..."
   - No system command can accomplish the task
   - Task requires custom logic that can't be done in a single shell command

   ⚠️ CREATE is for creating REUSABLE tools, NOT for immediate one-time actions!

   After CREATE completes:
   - If the original request was an ACTION ("send email", "download file"), set `execute_after_create: true` in your response
   - If the request was to BUILD something ("create a script", "write a tool"), set `execute_after_create: false`

5. **INSTALL**: Use when a system tool (not Python library) is missing

6. **RESPOND**: Use for questions, not action requests

7. **CANNOT_PROCEED**: ONLY for truly impossible requests (e.g., "hack into NASA")
   ⚠️ Check user tools with INVESTIGATE before using this!

🚨🚨🚨 CRITICAL: IMMEDIATE ACTIONS vs SCRIPT CREATION 🚨🚨🚨

**User wants ACTION NOW (imperative verbs):**
- "send email", "download file", "check Gmail", "find files", "compress directory"
- Decision: EXECUTE with shell command (preferred) OR CREATE with `execute_after_create: true`
- Example: "send email to John" → EXECUTE with `echo "..." | mail -s "Subject" john@email.com`

**User wants TOOL/SCRIPT (creation verbs):**
- "create a script that sends email", "write a program to download files", "make a tool that checks Gmail"
- Decision: CREATE with `execute_after_create: false`
- Example: "create a script that sends email" → CREATE send_email.py (don't execute)

🚨 WHEN TO USE SHELL COMMANDS vs CREATE:
- Simple one-time action? → EXECUTE with shell command (faster, no files created)
- Complex logic, authentication, or API integration needed? → CREATE (then execute if action request)
- User explicitly asks for a script? → CREATE (don't execute unless they also ask to run it)

🚨 CRITICAL DECISION PRIORITY FOR IMMEDIATE ACTIONS:

**STEP 1: Check gathered information for tool availability**
- Look at TRIAGE results for CHECK_TOOL actions
- Did we check if `mail`, `sendmail`, `curl`, `wget`, etc. are available?
- Use this information to decide between EXECUTE vs CREATE

**STEP 2: Choose decision based on tool availability:**

1. **FIRST CHOICE:** EXECUTE with shell command (if tool is available!)
   - Fast, simple, no files created
   - Example: CHECK_TOOL found `mail` → use EXECUTE with mail command
   - Example: CHECK_TOOL found `curl` → use EXECUTE with curl command

2. **SECOND CHOICE:** CREATE with execute_after_create=true (if tool NOT available OR needs complex logic)
   - If CHECK_TOOL shows mail/sendmail NOT installed → CREATE Python script
   - If needs authentication (Gmail SMTP, API keys) → CREATE Python script
   - If needs complex logic beyond simple command → CREATE Python script
   - IMPORTANT: Set execute_after_create=true to run immediately!

3. **WHEN IN DOUBT:** For "send email", prefer EXECUTE with mail command unless:
   - Gmail/SMTP authentication needed (use CREATE + execute)
   - Complex formatting/attachments needed (use CREATE + execute)
   - Simple text email → EXECUTE with mail command

🚨 IMPORTANT: If the project directory is EMPTY or has NO relevant scripts:
   → Use EXECUTE with shell commands for immediate actions
   → Use CREATE for building new tools/scripts
   → DO NOT use CANNOT_PROCEED!

🚨 CANNOT_PROCEED is ONLY for requests that are:
   - Illegal or unethical
   - Technically impossible (violate laws of physics)
   - Outside the agent's capabilities (e.g., "make me a sandwich")

   DO NOT use CANNOT_PROCEED just because:
   - No scripts exist yet (use EXECUTE with shell commands or CREATE!)
   - Libraries are missing (CREATE handles this!)
   - Credentials need setup (CREATE includes instructions!)

🚨🚨🚨 CRITICAL FOR CREATE DECISIONS - FILE ORGANIZATION 🚨🚨🚨

When generating the "code_prompt" for CREATE decisions, you MUST preserve ALL file organization instructions from the user's request:

✅ PRESERVE THESE EXACTLY:
- Directory creation: "create subdirectory X", "mkdir Y", "save to directory Z"
- File paths: "save as dir/file.ext", "put in folder/subfolder/file.py"
- File locations: "save in the new subdirectory", "put it in directory X"
- Multiple files: If user requests multiple files in different locations

Example user request: "create a subdirectory ./data and save the output as data/results.csv"
✅ CORRECT code_prompt: "Create a Python script. First create a subdirectory with the name 'data'. Then save the output as 'data/results.csv' in that subdirectory."
❌ WRONG code_prompt: "Create a Python script and save the output as results.csv" (LOST directory instruction!)

The code_prompt will be passed to the code generator, so it MUST include ALL file/directory organization details!

🚨🚨🚨 CRITICAL FOR FIX DECISIONS - PRESERVE USER INSTRUCTIONS 🚨🚨🚨

When generating the "code_prompt" for FIX decisions, you MUST preserve ALL specific details from the user's request:

✅ PRESERVE THESE EXACTLY:
- Which files to modify: "fix keypad.py", "update the login function in auth.py"
- What to change: "set Pi to math.pi", "change timeout from 30 to 60", "add error handling"
- Specific values/implementations: "use bcrypt for hashing", "return JSON instead of dict"
- Line numbers if mentioned: "fix line 42", "update lines 10-15"

Example user request: "The Pi key in keypad.py shows undefined, set it to math.pi"
✅ CORRECT code_prompt: "Fix keypad.py. The Pi key currently shows undefined because it's set to None. Update the Pi key definition to use math.pi instead."
❌ WRONG code_prompt: "Fix the undefined values in keypad.py" (LOST what to change and how!)

The code_prompt will be passed to the debugging agent, so it MUST include ALL specific details about what to fix and how!

🚨🚨🚨 RETRY STRATEGY - IF THIS IS A RETRY AFTER FAILURE 🚨🚨🚨

If the gathered information includes "PREVIOUS ATTEMPT FAILED", you are on a retry iteration.
Analyze the failure and choose ONE of these strategies:

**Strategy 1: INVESTIGATE - Learn more before trying again**
- If command failed due to unknown syntax/options → Run diagnostic command
- Examples:
  - "mail: invalid option" → EXECUTE with "mail --help" or "man mail" to learn correct syntax
  - "curl: unknown flag" → EXECUTE with "curl --help" to learn correct options
  - "Command not found" → Already checked with CHECK_TOOL, so switch to Strategy 3

**Strategy 2: CORRECT - Try corrected approach based on learned information**
- If diagnostic command showed you the correct syntax → Try EXECUTE with corrected command
- If you now know the correct format → Try EXECUTE with proper format
- Examples:
  - After seeing "mail --help" output → EXECUTE with correctly formatted mail command
  - After understanding error → EXECUTE with fixed command

**Strategy 3: SWITCH - Change strategy completely**
- If EXECUTE keeps failing → Switch to CREATE with execute_after_create=true
- If simple command isn't working → Build a script to handle complexity
- Examples:
  - "mail command keeps failing" → CREATE Python script with smtplib
  - "Complex authentication needed" → CREATE script with proper auth handling

**IMPORTANT FOR RETRIES:**
- DON'T repeat the exact same command that just failed!
- DO analyze what went wrong and try a different approach
- DO learn from diagnostic commands before attempting task again
- DO switch strategies if same approach keeps failing

Return your decision as JSON:

🚨 REQUIRED FIELDS FOR CREATE DECISIONS:
- For CREATE decision type, you MUST include the "execute_after_create" field
- Set to true if user wants immediate action (send, download, execute)
- Set to false if user wants to build a reusable tool (create, write, build)
- This field is MANDATORY for all CREATE decisions!

For EXECUTE (immediate action with shell command - PREFERRED for simple one-time actions):
{{
    "decision_type": "EXECUTE",
    "reasoning": "User wants to send email NOW. Using system mail command for immediate action.",
    "target": "mail",
    "commands": ["echo 'Hi John,\\n\\nI will not be able to attend lunch tomorrow. Something has come up.\\n\\nThanks,\\nAl' | mail -s 'Unable to Attend Lunch Tomorrow' sabawi@gmail.com"],
    "requires_approval": true
}}

⚠️ IMPORTANT - mail command format:
- The -s flag sets the subject
- DO NOT include "Subject:" in the echo body
- Body should start directly with the message content
- WRONG: echo 'Subject: Hello\\n\\nMessage' | mail -s 'Hello' user@example.com
- RIGHT: echo 'Message content here' | mail -s 'Hello' user@example.com

For EXECUTE (existing script found):
{{
    "decision_type": "EXECUTE",
    "reasoning": "Found find_bills.py which checks Gmail for bills",
    "target": "find_bills.py",
    "commands": ["python3 {self.project_dir}/find_bills.py --gmail"],
    "requires_approval": true
}}

For CREATE (immediate action requiring complex logic - create AND execute):
{{
    "decision_type": "CREATE",
    "reasoning": "User wants to send email NOW, but needs SMTP authentication which requires a script. Will create and immediately execute.",
    "code_prompt": "Create a Python script that sends an email to John at sabawi@gmail.com with subject 'Unable to Attend Lunch Tomorrow' and body explaining inability to attend lunch. Use smtplib with Gmail SMTP server. Include authentication setup instructions.",
    "target": "send_email.py",
    "execute_after_create": true,
    "requires_approval": true
}}

For CREATE (building a reusable tool - create but DON'T execute):
{{
    "decision_type": "CREATE",
    "reasoning": "User wants to CREATE a reusable script for future use, not execute it now.",
    "code_prompt": "Create a Python script that can send emails via Gmail SMTP. Accept recipient, subject, and body as command-line arguments. Include authentication setup and error handling. Save as send_email.py.",
    "target": "send_email.py",
    "execute_after_create": false,
    "requires_approval": true
}}

For CREATE with subdirectory (PRESERVE all file organization instructions!):
{{
    "decision_type": "CREATE",
    "reasoning": "User wants a Python script in a subdirectory. Will create the directory structure and file.",
    "code_prompt": "Create a subdirectory with the name 'scripts'. Then create a Python script that solves quadratic equations by accepting a, b, c as command-line arguments. Save the script as 'scripts/quad_solver.py' in the newly created subdirectory.",
    "target": "scripts/quad_solver.py",
    "execute_after_create": false,
    "requires_approval": true
}}

For FIX (modifying existing code - PRESERVE all user instructions!):
{{
    "decision_type": "FIX",
    "reasoning": "User wants to modify keypad.py to fix undefined Pi and e values",
    "code_prompt": "Fix the keypad.py file. The Pi and e keys currently produce undefined values because they are set to None. Update lines 5-6 to set Pi=math.pi and e=math.e so the keys generate their actual mathematical values.",
    "target": "keypad.py",
    "requires_approval": true
}}

For INSTALL (system tool missing):
{{
    "decision_type": "INSTALL",
    "reasoning": "Required system tool X is not installed",
    "commands": ["sudo apt install X"],
    "requires_approval": true,
    "requires_sudo": true
}}

For INVESTIGATE (getting user tool details):
{{
    "decision_type": "INVESTIGATE",
    "reasoning": "User wants to send email. I see 'secure_email_sender' tool in RAICA USER TOOLS. Need full details to use it.",
    "commands": ["get_tool_details secure_email_sender"],
    "requires_approval": false
}}

For INVESTIGATE (getting user tool details - news + email example):
{{
    "decision_type": "INVESTIGATE",
    "reasoning": "User wants to look up latest news and email it. I see 'raica_research_agent' in RAICA USER TOOLS which can handle web search and research. Getting its details first.",
    "commands": ["get_tool_details raica_research_agent"],
    "requires_approval": false
}}

🚨 IMPORTANT: After INVESTIGATE returns tool details, your NEXT decision should EXECUTE the tool!
Don't INVESTIGATE and then give up - use what you learned!

Example of COMPLETE workflow (news lookup + email):
Step 1: INVESTIGATE to get raica_research_agent details
Step 2: EXECUTE raica_research_agent to fetch news
Step 3: INVESTIGATE to get secure_email_sender details
Step 4: EXECUTE secure_email_sender to send email

For INVESTIGATE (diagnostic command to learn - RETRY Strategy 1):
{{
    "decision_type": "INVESTIGATE",
    "reasoning": "Previous mail command failed with 'invalid option' error. Running mail --help to learn correct syntax before retrying.",
    "target": "mail",
    "commands": ["mail --help"],
    "requires_approval": false
}}

For EXECUTE (corrected attempt - RETRY Strategy 2):
{{
    "decision_type": "EXECUTE",
    "reasoning": "After reviewing mail --help output, I now understand the correct format. The -s flag sets subject and body goes in echo. Retrying with corrected syntax.",
    "target": "mail",
    "commands": ["echo 'Hi John, I cannot attend lunch tomorrow. Thanks, Al' | mail -s 'Unable to Attend Lunch' sabawi@gmail.com"],
    "requires_approval": true
}}

For CREATE (switched strategy after EXECUTE failures - RETRY Strategy 3):
{{
    "decision_type": "CREATE",
    "reasoning": "EXECUTE with mail command failed multiple times due to syntax issues. Switching to CREATE Python script with smtplib for more reliable email sending.",
    "code_prompt": "Create a Python script that sends an email with subject 'Unable to Attend Lunch' to sabawi@gmail.com, explaining inability to attend. Use smtplib with Gmail SMTP.",
    "target": "send_email.py",
    "execute_after_create": true,
    "requires_approval": true
}}

🚨🚨🚨 ANTI-PATTERN: NEVER DO THIS! 🚨🚨🚨

❌ WRONG - Using CANNOT_PROCEED without checking user tools:
{{
    "decision_type": "CANNOT_PROCEED",
    "reasoning": "I need to look up news but don't know how to do web searches"
}}
Why wrong? You see 'raica_research_agent' in user tools! Use INVESTIGATE first!

❌ WRONG - Using CANNOT_PROCEED because you don't know parameters:
{{
    "decision_type": "CANNOT_PROCEED",
    "reasoning": "I see raica_research_agent tool but don't know its parameters"
}}
Why wrong? That's exactly what INVESTIGATE with get_tool_details is for!

✅ CORRECT - Use INVESTIGATE then proceed:
{{
    "decision_type": "INVESTIGATE",
    "reasoning": "I see raica_research_agent in user tools. Getting its parameter schema.",
    "commands": ["get_tool_details raica_research_agent"],
    "requires_approval": false
}}

Return ONLY the JSON object, no other text."""

        try:
            # Use classification model for decision-making (stronger model for critical decisions)
            response = await asyncio.to_thread(
                self.llm_client.generate_for_classification, prompt, max_tokens=1000
            )
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON object
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                from ..utils.json_utils import sanitize_json
                data = json.loads(sanitize_json(json_match.group()))

                decision_type_map = {
                    'RESPOND': DecisionType.RESPOND,
                    'EXECUTE': DecisionType.EXECUTE,
                    'FIX': DecisionType.FIX,
                    'CREATE': DecisionType.CREATE,
                    'INSTALL': DecisionType.INSTALL,
                    'CONFIGURE': DecisionType.CONFIGURE,
                    'SEARCH_MORE': DecisionType.SEARCH_MORE,
                    'CANNOT_PROCEED': DecisionType.CANNOT_PROCEED,
                    'DELEGATE': DecisionType.DELEGATE,
                }

                decision_type_str = data.get('decision_type', 'CANNOT_PROCEED').upper()
                decision_type = decision_type_map.get(decision_type_str, DecisionType.CANNOT_PROCEED)

                # ═══════════════════════════════════════════════════════════════
                # INTELLIGENT FALLBACK: Auto-correct CANNOT_PROCEED misuse
                # ═══════════════════════════════════════════════════════════════
                # If LLM chose CANNOT_PROCEED but has commands like "get_tool_details"
                # then it actually meant INVESTIGATE
                if decision_type == DecisionType.CANNOT_PROCEED:
                    commands = data.get('commands', [])
                    reasoning = data.get('reasoning', '').lower()

                    # Check if commands suggest investigation (not truly cannot proceed)
                    investigate_commands = any(
                        cmd.startswith('get_tool_details ') for cmd in commands
                    ) if commands else False

                    # Check if reasoning mentions needing tool details
                    needs_tool_details = any(phrase in reasoning for phrase in [
                        'need the parameter schema',
                        'need to get',
                        'must first retrieve',
                        'i need the',
                        'need its parameter',
                        'need full details',
                    ])

                    if investigate_commands or needs_tool_details:
                        # Extract tool name from reasoning or commands
                        tool_name = None
                        if commands:
                            for cmd in commands:
                                if cmd.startswith('get_tool_details '):
                                    tool_name = cmd.split(' ', 1)[1].strip()
                                    break

                        if not tool_name:
                            # Try to extract from reasoning
                            match = re.search(r"'([a-z_]+)'", reasoning)
                            if match:
                                tool_name = match.group(1)

                        if tool_name or investigate_commands:
                            logger.warning(
                                f"🔧 AUTO-CORRECT: LLM chose CANNOT_PROCEED but clearly needs investigation. "
                                f"Converting to INVESTIGATE{' for ' + tool_name if tool_name else ''}"
                            )
                            await self._output(
                                f"🔧 Auto-correcting decision: CANNOT_PROCEED → INVESTIGATE",
                                "warning"
                            )

                            decision_type = DecisionType.INVESTIGATE
                            if not commands and tool_name:
                                commands = [f"get_tool_details {tool_name}"]
                                data['commands'] = commands
                            data['requires_approval'] = False  # Investigation doesn't need approval

                return Decision(
                    decision_type=decision_type,
                    reasoning=data.get('reasoning', ''),
                    target=data.get('target', ''),
                    commands=data.get('commands', []),
                    code_prompt=data.get('code_prompt', ''),
                    response_text=data.get('response_text', ''),
                    requires_approval=data.get('requires_approval', True),
                    requires_sudo=data.get('requires_sudo', False),
                    execute_after_create=data.get('execute_after_create', False),
                    additional_info=data.get('additional_info', {})
                )

            # Fallback if JSON parsing fails
            return Decision(
                decision_type=DecisionType.CANNOT_PROCEED,
                reasoning=f"Could not parse decision from LLM response: {content[:200]}"
            )

        except Exception as e:
            logger.error(f"Decision phase failed: {e}")
            return Decision(
                decision_type=DecisionType.CANNOT_PROCEED,
                reasoning=f"Decision phase error: {e}"
            )

    # =========================================================================
    # PHASE 4: ACT
    # =========================================================================

    async def _act(self, decision: Decision, is_one_shot: bool = False) -> Dict[str, Any]:
        """
        Execute the decided action.

        Args:
            decision: The decision to execute
            is_one_shot: If True, use extended timeout for one-shot actions (mail, network commands)

        Returns:
            Dict with 'success', 'output', 'files' keys
        """
        result = {'success': False, 'output': '', 'files': []}

        # Use extended timeout for one-shot actions (mail/network commands may take longer)
        exec_timeout = 300 if is_one_shot else 120

        try:
            if decision.decision_type == DecisionType.RESPOND:
                # Direct response - no execution needed
                result['success'] = True
                result['output'] = decision.response_text
                await self._output(f"Response: {decision.response_text}", "info")

            elif decision.decision_type == DecisionType.EXECUTE:
                # Execute existing script/tool
                if decision.commands:
                    outputs = []
                    for cmd in decision.commands:
                        await self._output(f"Executing: {cmd}", "info")
                        if self.system_executor:
                            exec_result = await self.system_executor.execute(cmd, timeout=exec_timeout)
                            outputs.append(exec_result.stdout or exec_result.stderr)
                            if not exec_result.success:
                                result['output'] = f"Command failed: {exec_result.stderr}"
                                return result
                        else:
                            import subprocess
                            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=exec_timeout)
                            outputs.append(proc.stdout or proc.stderr)

                    result['success'] = True
                    result['output'] = "\n".join(outputs)
                else:
                    result['output'] = "No commands specified for EXECUTE"

            elif decision.decision_type == DecisionType.INVESTIGATE:
                # INVESTIGATE - Gather more information
                # Handles commands like "get_tool_details <tool_name>"
                if decision.commands:
                    outputs = []
                    for cmd in decision.commands:
                        await self._output(f"Investigating: {cmd}", "info")

                        # Check for special investigate commands
                        if cmd.startswith('get_tool_details '):
                            # Get user tool details on-demand
                            tool_name = cmd.split(' ', 1)[1].strip()
                            if CONTEXT_FIRST_AVAILABLE:
                                details = await get_tool_details(tool_name)
                                outputs.append(f"Tool Details for '{tool_name}':\n{json.dumps(details, indent=2)}")
                            else:
                                outputs.append(f"Context-First modules not available - cannot get tool details")

                        elif cmd.startswith('list_tools'):
                            # List all available user tools
                            if CONTEXT_FIRST_AVAILABLE:
                                from ..services.tool_details_provider import list_all_tools
                                all_tools = await list_all_tools()
                                outputs.append(f"Available Tools:\n{json.dumps(all_tools, indent=2)}")
                            else:
                                outputs.append("Context-First modules not available - cannot list tools")

                        else:
                            # Regular command execution (read-only investigation commands)
                            if self.system_executor:
                                exec_result = await self.system_executor.execute(cmd, timeout=60)
                                outputs.append(exec_result.stdout or exec_result.stderr)
                                if not exec_result.success:
                                    result['output'] = f"Investigation command failed: {exec_result.stderr}"
                                    return result
                            else:
                                import subprocess
                                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                                outputs.append(proc.stdout or proc.stderr)

                    result['success'] = True
                    result['output'] = "\n\n".join(outputs)
                else:
                    result['output'] = "No investigation commands specified"

            elif decision.decision_type == DecisionType.FIX:
                # Delegate to CodeDebugAgent
                await self._output("Delegating to Code Debug Agent...", "info")
                try:
                    from ..code_debug_agent import CodeDebugAgent
                    debug_agent = CodeDebugAgent(
                        project_dir=self.project_dir,
                        llm_client=self.llm_client
                    )
                    debug_result = await debug_agent.run(decision.code_prompt or decision.reasoning)
                    result['success'] = debug_result.success
                    result['output'] = str(debug_result.phases_completed)
                    result['files'] = debug_result.files_modified
                except Exception as e:
                    result['output'] = f"Code debug delegation failed: {e}"

            elif decision.decision_type == DecisionType.CREATE:
                # Delegate to CLICodingAgent
                await self._output("Delegating to Code Generation Agent...", "info")
                try:
                    from ..cli_coding_agent import CLICodingAgent
                    coding_agent = CLICodingAgent(
                        output_dir=str(self.project_dir),
                        use_existing_project=True
                    )
                    success = await asyncio.to_thread(
                        coding_agent.run,
                        decision.code_prompt or decision.reasoning
                    )
                    result['success'] = success
                    result['output'] = "Code generation completed"
                    if hasattr(coding_agent, 'generated_files'):
                        result['files'] = coding_agent.generated_files

                    # If this was an immediate action request, execute the created script
                    if decision.execute_after_create and success and decision.target:
                        await self._output(f"Executing created script: {decision.target}", "info")

                        # Determine how to run the script based on file extension
                        target_path = self.project_dir / decision.target
                        if not target_path.exists():
                            # Try to find the file in generated files
                            if result.get('files'):
                                for f in result['files']:
                                    if decision.target in f:
                                        target_path = Path(f)
                                        break

                        if target_path.exists():
                            # Build execution command based on file type
                            if target_path.suffix == '.py':
                                exec_cmd = f"python3 {target_path}"
                            elif target_path.suffix in ('.js', '.mjs'):
                                exec_cmd = f"node {target_path}"
                            elif target_path.suffix == '.sh':
                                exec_cmd = f"bash {target_path}"
                            else:
                                exec_cmd = str(target_path)

                            # Execute the script
                            if self.system_executor:
                                exec_result = await self.system_executor.execute(exec_cmd, timeout=120)
                                result['output'] += f"\n\nExecution result:\n{exec_result.stdout or exec_result.stderr}"
                                if not exec_result.success:
                                    result['output'] += f"\n⚠️ Execution failed: {exec_result.stderr}"
                            else:
                                import subprocess
                                proc = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=120)
                                result['output'] += f"\n\nExecution result:\n{proc.stdout or proc.stderr}"
                        else:
                            result['output'] += f"\n⚠️ Could not find created script to execute: {decision.target}"

                except Exception as e:
                    result['output'] = f"Code generation delegation failed: {e}"

            elif decision.decision_type == DecisionType.INSTALL:
                # Install tool/package
                if decision.commands:
                    for cmd in decision.commands:
                        await self._output(f"Installing: {cmd}", "info")
                        if self.system_executor:
                            exec_result = await self.system_executor.execute(cmd, timeout=300)
                            result['output'] = exec_result.stdout or exec_result.stderr
                            result['success'] = exec_result.success
                        else:
                            result['output'] = "System executor not available for install"
                else:
                    result['output'] = "No install commands specified"

            elif decision.decision_type == DecisionType.CONFIGURE:
                # Configure service
                if decision.commands:
                    for cmd in decision.commands:
                        await self._output(f"Configuring: {cmd}", "info")
                        if self.system_executor:
                            exec_result = await self.system_executor.execute(cmd, timeout=60)
                            result['output'] = exec_result.stdout or exec_result.stderr
                            result['success'] = exec_result.success
                else:
                    result['output'] = "No configure commands specified"

            elif decision.decision_type == DecisionType.SEARCH_MORE:
                # Need more information - this triggers another triage round
                result['output'] = f"More information needed: {decision.reasoning}"
                result['success'] = True  # Not a failure, just needs more triage

            elif decision.decision_type == DecisionType.CANNOT_PROCEED:
                result['output'] = f"Cannot proceed: {decision.reasoning}"
                result['success'] = False

            else:
                result['output'] = f"Unknown decision type: {decision.decision_type}"

        except Exception as e:
            logger.error(f"Action phase failed: {e}")
            result['output'] = f"Action error: {e}"

        return result

    # =========================================================================
    # PHASE 5: VERIFY
    # =========================================================================

    async def _verify(
        self,
        request: str,
        decision: Decision,
        act_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Verify the action achieved the user's goal.

        Args:
            request: Original request
            decision: The decision that was executed
            act_result: Result of the action execution

        Returns:
            Dict with 'success' and optional 'error'
        """
        # For simple responses, verification is implicit
        if decision.decision_type == DecisionType.RESPOND:
            return {'success': True}

        # ═══════════════════════════════════════════════════════════════════════
        # CREATE VERIFICATION - Must check if files were actually created!
        # ═══════════════════════════════════════════════════════════════════════
        if decision.decision_type == DecisionType.CREATE:
            files = act_result.get('files', [])

            # First check: Did the agent report created files?
            if files:
                await self._output(f"Verification: Created {len(files)} files", "info")
                return {'success': True}

            # Second check: Scan project directory for ANY recently created files
            # NO hardcoded patterns - check all user-visible files
            try:
                import time
                recent_cutoff = time.time() - 600  # 10 minutes

                # Check all files in project directory (not subdirs to avoid noise)
                all_files = [f for f in self.project_dir.iterdir() if f.is_file()]

                # Filter to recently created/modified files
                recent_files = [f for f in all_files if f.stat().st_mtime > recent_cutoff]

                # Exclude hidden files, metadata, logs, and build artifacts
                # This is a general system convention, not semantic interpretation
                excluded_suffixes = (
                    '_context.json', '.log', '.pyc', '.pyo', '.cache',
                    '.egg-info', '.dist-info', '.swp', '.swo', '~'
                )
                recent_files = [f for f in recent_files
                               if not f.name.startswith('.')
                               and not f.name.startswith('__pycache__')
                               and not any(f.name.endswith(suf) for suf in excluded_suffixes)]

                if recent_files:
                    file_names = [f.name for f in recent_files[:5]]  # Show first 5
                    await self._output(
                        f"Verification: Found {len(recent_files)} recently created files: {', '.join(file_names)}",
                        "info"
                    )
                    return {'success': True}
            except Exception as e:
                logger.warning(f"File scan verification failed: {e}")

            # CREATE failed - no files were created
            await self._output("Verification FAILED: No files were created!", "error")
            return {
                'success': False,
                'error': "Code generation completed but no files were created. The LLM may have failed to produce valid code."
            }

        # ═══════════════════════════════════════════════════════════════════════
        # FIX VERIFICATION - Must check if files were actually modified!
        # ═══════════════════════════════════════════════════════════════════════
        if decision.decision_type == DecisionType.FIX:
            files = act_result.get('files', [])
            if files:
                await self._output(f"Verification: Modified {len(files)} files", "info")
                return {'success': True}

            # FIX may have failed silently
            if not act_result.get('success', False):
                return {'success': False, 'error': act_result.get('output', 'Fix failed')}

        # ═══════════════════════════════════════════════════════════════════════
        # EXECUTE VERIFICATION - Trust exit code (MINIMAL SCAFFOLDING)
        # ═══════════════════════════════════════════════════════════════════════
        # ARCHITECTURE: System commands return error on failure, exit cleanly on success.
        # Just capture stderr/stdout - that's all the verification needed!
        # DON'T ask LLM - exit code 0 = SUCCESS, non-zero = FAILED (deterministic)
        # This prevents retrying commands with side effects (send email 3 times!)
        # ═══════════════════════════════════════════════════════════════════════
        if decision.decision_type == DecisionType.EXECUTE:
            # Check exit code - this is DETERMINISTIC!
            if not act_result.get('success', False):
                # Command failed (exit code != 0)
                # stderr contains the error message
                error_msg = act_result.get('output', 'Command execution failed')
                return {'success': False, 'error': error_msg}

            # ✅ Exit code 0 = SUCCESS
            # Command executed successfully - TRUST IT, DONE!
            # Don't ask LLM, don't retry - the action already happened!
            return {'success': True}

        # ═══════════════════════════════════════════════════════════════════════
        # INVESTIGATE VERIFICATION - Check if task is complete
        # ═══════════════════════════════════════════════════════════════════════
        # INVESTIGATE is for gathering information (get_tool_details, diagnostic commands)
        # Success means we got the information AND the overall task is complete
        # We must ask the LLM: "Is the ORIGINAL request fully accomplished?"
        # ═══════════════════════════════════════════════════════════════════════
        if decision.decision_type == DecisionType.INVESTIGATE:
            # First check: Did the investigation itself succeed?
            if not act_result.get('success', False):
                return {'success': False, 'error': act_result.get('output', 'Investigation failed')}

            # Investigation succeeded - but is the ORIGINAL REQUEST complete?
            # Ask LLM to determine if we need to continue or if we're done
            await self._output("Verification: Investigation completed, checking if task is done...", "info")

            # Build verification prompt
            verification_prompt = f"""Analyze if the user's ORIGINAL request has been fully accomplished.

ORIGINAL REQUEST: {request}

WHAT WE JUST DID: {decision.reasoning}

INVESTIGATION RESULT:
{act_result.get('output', '')[:1000]}

QUESTION: Is the ORIGINAL request now FULLY COMPLETE?

Examples:
- Original: "Get tool details for raica_research_agent"
  Just did: Got tool details
  Answer: YES - Request complete ✅

- Original: "Look up latest news and email it"
  Just did: Got tool details for raica_research_agent
  Answer: NO - Still need to execute the tool and send email ❌

Return JSON:
{{
    "task_complete": true/false,
    "reasoning": "Brief explanation of what's done and what remains"
}}

Return ONLY JSON, no other text."""

            try:
                response = await asyncio.to_thread(
                    self.llm_client.generate_for_classification, verification_prompt, max_tokens=300
                )
                content = response.content if hasattr(response, 'content') else str(response)

                # Parse JSON
                import json
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    data = json.loads(json_match.group())
                    task_complete = data.get('task_complete', False)
                    reasoning = data.get('reasoning', '')

                    if task_complete:
                        await self._output(f"✅ Task complete: {reasoning}", "success")
                        return {'success': True}
                    else:
                        await self._output(f"⏩ Continue: {reasoning}", "info")
                        # Investigation succeeded but task NOT complete - continue to next iteration
                        return {'success': False, 'error': f'Task incomplete: {reasoning}'}

            except Exception as e:
                logger.warning(f"LLM verification failed, assuming task incomplete: {e}")

            # Fallback: Assume task is NOT complete (safer to continue than stop early)
            return {'success': False, 'error': 'Investigation complete but overall task status unclear - continuing'}

        # ═══════════════════════════════════════════════════════════════════════
        # OTHER VERIFICATIONS
        # ═══════════════════════════════════════════════════════════════════════
        if decision.decision_type == DecisionType.INSTALL:
            if act_result.get('success', False):
                await self._output("Verification: Installation completed", "info")
                return {'success': True}
            return {'success': False, 'error': act_result.get('output', 'Installation failed')}

        if decision.decision_type == DecisionType.CANNOT_PROCEED:
            return {'success': False, 'error': act_result.get('output', 'Cannot proceed')}

        # Generic fallback
        return {'success': act_result.get('success', False)}

    # =========================================================================
    # SYNTHESIS - Analyze gathered information and present findings
    # =========================================================================

    async def _synthesize_findings(
        self,
        request: str,
        execution_output: str,
        decision: Decision
    ) -> Optional[str]:
        """
        Ask LLM to synthesize and analyze the gathered information.

        This is called after EXECUTE when the user requested analysis/information.
        The LLM analyzes all gathered data and produces a meaningful summary.

        Args:
            request: Original user request
            execution_output: Output from executed commands
            decision: The decision that was executed

        Returns:
            Synthesized analysis string, or None if synthesis not needed
        """
        # Truncate output if too long (keep first and last parts for context)
        max_output_length = 15000
        if len(execution_output) > max_output_length:
            half = max_output_length // 2
            execution_output = (
                execution_output[:half] +
                f"\n\n... [{len(execution_output) - max_output_length} chars truncated] ...\n\n" +
                execution_output[-half:]
            )

        prompt = f"""You are analyzing project information for a user.

ORIGINAL REQUEST:
{request}

COMMANDS EXECUTED:
{', '.join(decision.commands) if decision.commands else 'N/A'}

GATHERED INFORMATION:
{execution_output}

Based on this information, provide a comprehensive analysis that directly addresses the user's request.

Your response should:
1. Start with a brief STATUS SUMMARY (2-3 sentences)
2. List KEY FINDINGS (bullet points)
3. If issues were found, list them under ISSUES DETECTED
4. If the user asked for fixes, provide RECOMMENDED ACTIONS
5. End with NEXT STEPS if applicable

Be concise but thorough. Focus on what the user asked for.
Format your response clearly with section headers."""

        try:
            response = await self.llm_client.complete(prompt, max_tokens=2000)
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            # Fall back to just showing raw output summary
            return f"Gathered {len(execution_output)} characters of project information. Raw output available in logs."

        return None

    # =========================================================================
    # UTILITIES
    # =========================================================================

    async def _phase_start(self, phase: str):
        """Notify that a phase is starting."""
        await self._output(f"\n{'='*60}\n  PHASE: {phase}\n{'='*60}", "phase")
        if self.callbacks.on_phase_start:
            await self.callbacks.on_phase_start(phase)

    async def _output(self, message: str, msg_type: str = "info"):
        """Send output to callbacks."""
        logger.info(f"[{msg_type.upper()}] {message}")
        if self.callbacks.on_output:
            await self.callbacks.on_output(message, msg_type)

    def _estimate_token_savings(
        self,
        triage_count: int,
        decision: Decision
    ) -> int:
        """
        Estimate how many tokens were saved vs the old approach.

        Old approach: Full classification + full plan generation + skip logic
        New approach: Targeted triage + informed decision
        """
        # Old approach estimates:
        # - Classification prompt: ~500 tokens
        # - Full plan generation: ~800 tokens
        # - Each skip check: ~200 tokens
        # - Total for typical request: ~1500-2000 tokens

        # New approach:
        # - Triage prompts: ~300 tokens each, but only what's needed
        # - Decision prompt: ~500 tokens (but informed, so no wasted steps)
        # - No skip logic needed

        old_estimate = 1500
        new_estimate = 300 * min(triage_count, 2) + 500

        # If we decided to EXECUTE instead of CREATE, we saved even more
        if decision.decision_type == DecisionType.EXECUTE:
            old_estimate += 500  # Would have generated code then skipped

        return max(0, old_estimate - new_estimate)
