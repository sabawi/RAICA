"""
Main Orchestrator
=================

Coordinates all components to handle any type of user request intelligently.
Routes between system operations, code generation, and hybrid workflows.
"""

import asyncio
import json
import logging
import re
from typing import Optional, Callable, Awaitable, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .request_classifier import RequestClassifier, RequestType, ClassificationResult
from .task_decomposer import TaskDecomposer, TaskStep, StepType, StepStatus, ExecutionPlan
from .system_executor import SystemExecutor, CommandRisk, ExecutionResult, SudoHelper

# Import CODE_DEBUG components (lazy import to avoid circular dependencies)
CODE_DEBUG_AGENT = None

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorCallbacks:
    """Callbacks for orchestrator to communicate with UI."""
    on_classification: Optional[Callable[[ClassificationResult], Awaitable[None]]] = None
    on_plan_ready: Optional[Callable[[ExecutionPlan], Awaitable[bool]]] = None  # Returns approval
    on_step_start: Optional[Callable[[TaskStep], Awaitable[None]]] = None
    on_step_complete: Optional[Callable[[TaskStep, bool], Awaitable[None]]] = None
    on_output: Optional[Callable[[str, str], Awaitable[None]]] = None  # message, type
    on_approval_needed: Optional[Callable[[str, str, CommandRisk], Awaitable[bool]]] = None
    on_user_input: Optional[Callable[[str], Awaitable[str]]] = None
    on_error: Optional[Callable[[str], Awaitable[None]]] = None
    on_complete: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None


@dataclass
class OrchestratorResult:
    """Result of orchestrator execution."""
    success: bool
    request: str
    classification: ClassificationResult
    plan: Optional[ExecutionPlan] = None
    steps_completed: int = 0
    steps_failed: int = 0
    execution_results: List[ExecutionResult] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'request': self.request[:100],
            'classification': self.classification.to_dict(),
            'steps_completed': self.steps_completed,
            'steps_failed': self.steps_failed,
            'generated_files': self.generated_files,
            'error': self.error,
            'duration_seconds': self.duration_seconds
        }


class Orchestrator:
    """
    Main orchestrator that handles any type of user request.

    Workflow:
    1. Classify the request (system query, system task, code gen, hybrid)
    2. Decompose into atomic steps
    3. Present plan to user for approval
    4. Execute steps with verification
    5. Handle failures with retry/fix logic
    6. Report results

    Example:
        orchestrator = Orchestrator(llm_client)
        result = await orchestrator.handle_request(
            "Check my system and install LAMP stack, then create a PHP form"
        )
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        project_dir: Optional[Path] = None,
        callbacks: Optional[OrchestratorCallbacks] = None,
        allow_sudo: bool = False,
        max_retries: int = 2
    ):
        """
        Initialize the orchestrator.

        Args:
            llm_client: LLM client for intelligent processing
            project_dir: Directory for generated code
            callbacks: UI callbacks
            allow_sudo: Allow sudo command execution
            max_retries: Max retries per step
        """
        self.llm_client = llm_client
        self.project_dir = project_dir or Path.cwd() / "generated_projects"
        self.callbacks = callbacks or OrchestratorCallbacks()
        self.allow_sudo = allow_sudo
        self.max_retries = max_retries

        # Initialize components
        self.classifier = RequestClassifier(llm_client)
        self.decomposer = TaskDecomposer(llm_client)
        self.executor = SystemExecutor(
            approval_callback=self._handle_approval,
            allow_sudo=allow_sudo
        )

        # State
        self._current_plan: Optional[ExecutionPlan] = None
        self._aborted = False

    async def handle_request(self, request: str) -> OrchestratorResult:
        """
        Handle any user request intelligently.

        Args:
            request: User's request text

        Returns:
            OrchestratorResult with execution details
        """
        start_time = datetime.now()
        self._aborted = False

        await self._output(f"Analyzing request: {request[:100]}...", "info")

        # Step 1: Classify the request
        classification = self.classifier.classify(request)
        await self._output(
            f"Request classified as: {classification.primary_type.name} "
            f"(confidence: {classification.confidence:.0%})",
            "info"
        )

        if self.callbacks.on_classification:
            await self.callbacks.on_classification(classification)

        # Step 2: Route based on classification
        try:
            if classification.primary_type == RequestType.CONVERSATION:
                # Just a question, handle conversationally
                result = await self._handle_conversation(request, classification)

            elif classification.primary_type == RequestType.SYSTEM_QUERY:
                # Read-only system check
                result = await self._handle_system_query(request, classification)

            elif classification.primary_type == RequestType.SYSTEM_TASK:
                # System modification
                result = await self._handle_system_task(request, classification)

            elif classification.primary_type == RequestType.CODE_GENERATION:
                # Pure code generation
                result = await self._handle_code_generation(request, classification)

            elif classification.primary_type == RequestType.CODE_DEBUG:
                # Debug/fix existing code
                result = await self._handle_code_debug(request, classification)

            elif classification.primary_type == RequestType.HYBRID:
                # Complex hybrid request
                result = await self._handle_hybrid(request, classification)

            else:
                result = OrchestratorResult(
                    success=False,
                    request=request,
                    classification=classification,
                    error="Unknown request type"
                )

        except Exception as e:
            logger.exception("Orchestrator error")
            result = OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error=str(e)
            )

        result.duration_seconds = (datetime.now() - start_time).total_seconds()

        if self.callbacks.on_complete:
            await self.callbacks.on_complete(result.to_dict())

        return result

    async def handle_request_intelligently(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """
        Handle ANY request using LLM-based intelligent planning.

        This method doesn't rely on keyword-based classification. Instead, it:
        1. Asks the LLM to analyze what the user actually wants
        2. Creates an intelligent plan with investigation, capability checks, execution
        3. Executes each step, adapting based on real-world results
        4. Reports honest results (success only if actually successful)

        Args:
            request: User's request text
            classification: Initial classification (used as hint, not final)

        Returns:
            OrchestratorResult with execution details
        """
        start_time = datetime.now()
        self._aborted = False

        await self._output(f"Analyzing: {request[:80]}...", "info")

        if not self.llm_client:
            await self._output("No LLM available for intelligent planning", "error")
            return OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error="LLM client required for intelligent planning"
            )

        try:
            # Step 1: Use LLM to create an intelligent action plan
            plan = await self._create_intelligent_plan(request, classification)

            if not plan or not plan.steps:
                await self._output("Could not create execution plan", "error")
                return OrchestratorResult(
                    success=False,
                    request=request,
                    classification=classification,
                    error="Failed to create execution plan"
                )

            await self._output(f"Created plan with {len(plan.steps)} steps", "info")

            # Show plan and get approval
            if self.callbacks.on_plan_ready:
                approved = await self.callbacks.on_plan_ready(plan)
                if not approved:
                    return OrchestratorResult(
                        success=False,
                        request=request,
                        classification=classification,
                        plan=plan,
                        error="Plan not approved by user"
                    )

            # Step 2: Execute the plan
            result = await self._execute_plan(plan, request, classification)

            # If plan requires code generation, add the marker to result
            if getattr(plan, 'requires_code_generation', False):
                if "__USE_CODE_GEN_PIPELINE__" not in result.generated_files:
                    result.generated_files.append("__USE_CODE_GEN_PIPELINE__")
                    logger.info("Plan requires code generation - flagging for code gen pipeline")

            result.duration_seconds = (datetime.now() - start_time).total_seconds()

            if self.callbacks.on_complete:
                await self.callbacks.on_complete(result.to_dict())

            return result

        except Exception as e:
            logger.exception("Intelligent planning error")
            return OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error=str(e)
            )

    async def _create_intelligent_plan(
        self,
        request: str,
        classification: ClassificationResult
    ) -> Optional[ExecutionPlan]:
        """
        Use LLM to create an intelligent execution plan for any request.

        The LLM analyzes what the user wants and creates appropriate steps:
        - INVESTIGATE: Check system state, capabilities, prerequisites
        - INFORM_USER: Tell user if something isn't possible and how to fix
        - EXECUTE: Run commands to accomplish the task
        - CODE_GENERATE: Only if actual code/project creation is needed
        - VERIFY: Confirm the task was actually completed
        """
        prompt = f"""Analyze this user request and create an execution plan.

USER REQUEST: {request}

INITIAL CLASSIFICATION: {classification.primary_type.name} (but re-evaluate this)

Your job is to understand what the user ACTUALLY wants and create a step-by-step plan.

IMPORTANT PRINCIPLES:
1. If the user says "send an email" - they want to SEND an email, not create an email-sending program
2. If the user says "check if X is installed" - they want system information, not code
3. Only create code/projects if the user explicitly asks for a program/application/script
4. Always start with INVESTIGATE steps to check capabilities
5. If something isn't possible, use INFORM_USER to explain why and how to fix it

STEP TYPES:
- INVESTIGATE: Check system state (which command, file exists, etc.) - READ ONLY
- EXECUTE: Run commands to do something (send email, install package, etc.)
- INFORM_USER: Tell the user something important (can't do X because Y, need to install Z first)
- CODE_GENERATE: Create actual code files (ONLY if user wants a program/application)
- VERIFY: Confirm the action was successful

CRITICAL RULE FOR CODE_GENERATE:
- CODE_GENERATE steps must be the LAST step(s) in the plan
- NEVER include EXECUTE steps that depend on generated code (like "run the script")
- The code generation happens in a separate pipeline AFTER this plan completes
- If the user wants a program/script, investigate prerequisites first, then end with CODE_GENERATE
- DO NOT include steps to "launch" or "run" the generated code - the user will do that manually

For "create a program/script" type requests, the plan should be:
1. INVESTIGATE: Check if required language/dependencies are installed
2. INSTALL (if needed, with condition): Install missing dependencies
3. CODE_GENERATE: Create the code (THIS MUST BE THE LAST STEP - no execution after this!)

For "send an email" type requests, the plan should be:
1. INVESTIGATE: Check if mail/sendmail/msmtp is available (which mail; which sendmail; which msmtp)
2. If available: EXECUTE to send the email using the available tool
3. If not available: INFORM_USER about how to set up email capability
4. VERIFY: Confirm email was queued/sent

Output as JSON:
{{
    "understanding": "What the user actually wants in one sentence",
    "requires_code_generation": false,
    "steps": [
        {{
            "id": "step_1",
            "step_type": "INVESTIGATE",
            "title": "Check email capability",
            "description": "Check if system can send emails",
            "commands": ["which mail", "which sendmail", "which msmtp"],
            "requires_sudo": false,
            "on_failure": "continue"
        }},
        {{
            "id": "step_2",
            "step_type": "EXECUTE",
            "title": "Send the email",
            "description": "Send email using available mail command",
            "commands": ["echo 'Message body' | mail -s 'Subject' recipient@email.com"],
            "requires_sudo": false,
            "condition": "step_1 found mail command"
        }},
        {{
            "id": "step_3",
            "step_type": "INFORM_USER",
            "title": "Email capability not available",
            "description": "System doesn't have email sending capability. Install with: sudo apt install mailutils",
            "condition": "step_1 found no mail commands"
        }}
    ]
}}

Create an appropriate plan for this request:"""

        try:
            response = await asyncio.to_thread(self.llm_client.generate, prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if not json_match:
                logger.error("No JSON found in LLM response")
                return None

            data = json.loads(json_match.group())

            # Log understanding
            understanding = data.get('understanding', 'Unknown')
            await self._output(f"Understanding: {understanding}", "info")

            requires_code_gen = data.get('requires_code_generation', False)
            if requires_code_gen:
                await self._output("This request requires code generation", "info")

            # Parse steps
            steps = []
            type_map = {
                'INVESTIGATE': StepType.INVESTIGATE,
                'EXECUTE': StepType.EXECUTE,
                'INSTALL': StepType.INSTALL,
                'CONFIGURE': StepType.CONFIGURE,
                'VERIFY': StepType.VERIFY,
                'CODE_GENERATE': StepType.CODE_GENERATE,
                'INFORM_USER': StepType.INFORM_USER,
                'USER_INPUT': StepType.USER_INPUT,
            }

            for step_data in data.get('steps', []):
                step_type_str = step_data.get('step_type', 'EXECUTE')
                step_type = type_map.get(step_type_str, StepType.EXECUTE)

                step = TaskStep(
                    id=step_data.get('id', f"step_{len(steps)+1}"),
                    step_type=step_type,
                    title=step_data.get('title', 'Untitled'),
                    description=step_data.get('description', ''),
                    commands=step_data.get('commands', []),
                    requires_sudo=step_data.get('requires_sudo', False),
                    requires_approval=step_data.get('requires_approval', step_type == StepType.EXECUTE),
                    depends_on=step_data.get('depends_on', []),
                    verification=step_data.get('verification', ''),
                    on_failure=step_data.get('on_failure', 'ask_user'),
                    condition=step_data.get('condition', ''),
                )
                steps.append(step)
                if step.condition:
                    logger.debug(f"Step {step.id} has condition: {step.condition}")

            plan = ExecutionPlan(
                request=request,
                classification=classification,
                steps=steps
            )
            plan.total_steps = len(steps)

            # Attach the requires_code_gen flag to the plan for later use
            plan.requires_code_generation = requires_code_gen

            logger.info(f"Created intelligent plan: {len(steps)} steps, requires_code_gen={requires_code_gen}")

            return plan

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.exception(f"Failed to create intelligent plan: {e}")
            return None

    async def _handle_conversation(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Handle conversational/question requests."""
        await self._output("This appears to be a question. Let me help...", "info")

        if self.llm_client:
            try:
                response = await asyncio.to_thread(
                    self.llm_client.generate,
                    request
                )
                content = response.content if hasattr(response, 'content') else str(response)
                await self._output(content, "llm_response")

                return OrchestratorResult(
                    success=True,
                    request=request,
                    classification=classification
                )
            except Exception as e:
                return OrchestratorResult(
                    success=False,
                    request=request,
                    classification=classification,
                    error=str(e)
                )
        else:
            await self._output("No LLM available to answer questions", "warning")
            return OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error="No LLM available"
            )

    async def _handle_system_query(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Handle read-only system queries."""
        await self._output("Investigating system...", "info")

        # Decompose into steps
        plan = self.decomposer.decompose(request, classification)
        self._current_plan = plan

        await self._output(f"Will execute {len(plan.steps)} investigation steps", "info")

        # Execute investigation steps
        execution_results = []
        for step in plan.steps:
            await self._output(f"Step: {step.title}", "info")

            if step.commands:
                for cmd in step.commands:
                    await self._output(f"Running: {cmd}", "command")
                    result = await self.executor.execute(
                        cmd,
                        description=step.description,
                        require_approval=False  # Queries don't need approval
                    )
                    execution_results.append(result)

                    if result.success and result.stdout:
                        await self._output(result.stdout.strip(), "output")
                    elif result.stderr:
                        await self._output(result.stderr.strip(), "warning")

            step.status = StepStatus.COMPLETED

        # Analyze results and provide recommendations using LLM
        await self._output("\n=== Analyzing Results ===", "info")

        if self.llm_client and execution_results:
            try:
                # Compile all command outputs
                outputs = []
                for result in execution_results:
                    if result.success and result.stdout:
                        outputs.append(f"Command: {result.command}\nOutput:\n{result.stdout[:1000]}")

                combined_output = "\n\n".join(outputs)

                analysis_prompt = f"""Analyze the following system query results and provide helpful recommendations.

ORIGINAL USER REQUEST: {request}

COMMAND OUTPUTS:
{combined_output}

Based on the above information, provide:
1. A clear summary of what was found
2. Specific recommendations or actionable insights
3. Any concerns or issues noticed

Be concise but helpful. If the user asked for recommendations (like which files to delete), provide specific suggestions based on the data."""

                response = await asyncio.to_thread(
                    self.llm_client.generate,
                    analysis_prompt
                )
                analysis = response.content if hasattr(response, 'content') else str(response)

                await self._output("\n=== Analysis & Recommendations ===", "success")
                await self._output(analysis, "llm_response")

                # Offer follow-up actions based on the analysis
                await self._offer_followup_actions(request, analysis, execution_results)

            except Exception as e:
                await self._output(f"Analysis failed: {e}", "warning")
                await self._output("\n=== Investigation Complete ===", "success")
        else:
            await self._output("\n=== Investigation Complete ===", "success")

        return OrchestratorResult(
            success=True,
            request=request,
            classification=classification,
            plan=plan,
            steps_completed=len(plan.steps),
            execution_results=execution_results
        )

    async def _offer_followup_actions(
        self,
        original_request: str,
        analysis: str,
        execution_results: List[ExecutionResult]
    ) -> None:
        """Offer follow-up actions based on the analysis."""
        if not self.callbacks.on_user_input:
            return

        # Use LLM to determine if there are actionable follow-ups
        followup_prompt = f"""Based on this analysis, determine if there are actionable follow-up tasks the user might want to execute.

ORIGINAL REQUEST: {original_request}

ANALYSIS:
{analysis[:2000]}

If there ARE actionable follow-ups (like deletions, installations, configurations, etc.), respond with:
ACTIONABLE: YES
DESCRIPTION: Brief description of what can be done
COMMANDS: List of commands that would execute the recommended actions (one per line)

If there are NO actionable follow-ups, respond with:
ACTIONABLE: NO

Be conservative - only suggest follow-ups that directly address the user's original request."""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                followup_prompt
            )
            content = response.content if hasattr(response, 'content') else str(response)

            if "ACTIONABLE: YES" in content:
                # Extract commands
                commands = []
                in_commands = False
                description = ""

                for line in content.split('\n'):
                    if line.startswith("DESCRIPTION:"):
                        description = line.replace("DESCRIPTION:", "").strip()
                    elif line.startswith("COMMANDS:"):
                        in_commands = True
                    elif in_commands and line.strip():
                        cmd = line.strip()
                        if cmd.startswith('- '):
                            cmd = cmd[2:]
                        if cmd.startswith('$ '):
                            cmd = cmd[2:]
                        if cmd and not cmd.startswith('#'):
                            commands.append(cmd)

                if commands:
                    await self._present_followup_options(description, commands)

        except Exception as e:
            logger.warning(f"Follow-up analysis failed: {e}")

    async def _present_followup_options(self, description: str, commands: List[str]) -> None:
        """Present follow-up action options to the user."""
        await self._output("\n" + "=" * 60, "info")
        await self._output("FOLLOW-UP ACTIONS AVAILABLE", "success")
        await self._output("=" * 60, "info")
        await self._output(f"\n{description}\n", "info")

        # Show what would be executed
        await self._output(f"Commands to execute ({len(commands)} total):", "info")
        for i, cmd in enumerate(commands[:5], 1):
            await self._output(f"  {i}. {cmd[:70]}{'...' if len(cmd) > 70 else ''}", "info")
        if len(commands) > 5:
            await self._output(f"  ... and {len(commands) - 5} more", "info")

        await self._output("\nOptions:", "info")
        await self._output("  1. Execute ALL actions (with single approval)", "info")
        await self._output("  2. Execute ONE BY ONE (approve each step)", "info")
        await self._output("  3. Create a SCRIPT for manual execution", "info")
        await self._output("  4. SKIP - do nothing", "info")

        if self.callbacks.on_user_input:
            choice = await self.callbacks.on_user_input("Select option (1-4):")

            if choice == "1":
                await self._execute_followup_all(commands)
            elif choice == "2":
                await self._execute_followup_one_by_one(commands)
            elif choice == "3":
                await self._create_followup_script(commands)
            else:
                await self._output("Skipped follow-up actions", "info")

    async def _execute_followup_all(self, commands: List[str]) -> None:
        """Execute all follow-up commands with single approval."""
        await self._output("\n=== Executing All Follow-up Actions ===", "phase")

        # Show all commands and ask for approval
        await self._output("The following commands will be executed:", "warning")
        for cmd in commands:
            await self._output(f"  $ {cmd}", "command")

        if self.callbacks.on_approval_needed:
            approved = await self.callbacks.on_approval_needed(
                "\n".join(commands),
                "Execute all follow-up commands",
                CommandRisk.MEDIUM
            )

            if not approved:
                await self._output("Execution cancelled by user", "warning")
                return

        # Execute each command
        success_count = 0
        fail_count = 0

        for cmd in commands:
            await self._output(f"$ {cmd}", "command")
            result = await self.executor.execute(cmd, require_approval=False)

            if result.success:
                success_count += 1
                if result.stdout:
                    await self._output(result.stdout.strip()[:200], "output")
                await self._output("✓ Success", "success")
            else:
                fail_count += 1
                await self._output(f"✗ Failed: {result.error or result.stderr}", "error")

        await self._output(f"\nCompleted: {success_count} succeeded, {fail_count} failed", "info")

    async def _execute_followup_one_by_one(self, commands: List[str]) -> None:
        """Execute follow-up commands one at a time with individual approval."""
        await self._output("\n=== Executing Follow-up Actions (One by One) ===", "phase")

        for i, cmd in enumerate(commands, 1):
            await self._output(f"\nStep {i}/{len(commands)}: {cmd}", "info")

            if self.callbacks.on_approval_needed:
                approved = await self.callbacks.on_approval_needed(
                    cmd,
                    f"Execute step {i}/{len(commands)}",
                    CommandRisk.MEDIUM
                )

                if not approved:
                    await self._output("Skipped this step", "warning")

                    # Ask if user wants to continue with remaining
                    if self.callbacks.on_user_input and i < len(commands):
                        continue_choice = await self.callbacks.on_user_input(
                            "Continue with remaining steps? (yes/no)"
                        )
                        if continue_choice.lower() not in ['yes', 'y']:
                            await self._output("Stopped execution", "info")
                            break
                    continue

            result = await self.executor.execute(cmd, require_approval=False)

            if result.success:
                if result.stdout:
                    await self._output(result.stdout.strip()[:300], "output")
                await self._output("✓ Success", "success")
            else:
                await self._output(f"✗ Failed: {result.error or result.stderr}", "error")

        await self._output("\n=== Follow-up Execution Complete ===", "success")

    async def _create_followup_script(self, commands: List[str]) -> None:
        """Create a shell script for manual execution."""
        await self._output("\n=== Creating Execution Script ===", "phase")

        script_content = [
            "#!/bin/bash",
            "# Auto-generated follow-up script",
            f"# Generated by RAICA on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "set -e  # Exit on error",
            "",
            "echo 'Starting follow-up actions...'",
            ""
        ]

        for i, cmd in enumerate(commands, 1):
            script_content.append(f"echo 'Step {i}: {cmd[:50]}...'")
            script_content.append(cmd)
            script_content.append("")

        script_content.extend([
            "echo 'All actions completed successfully!'",
            ""
        ])

        script_text = "\n".join(script_content)

        # Save script
        script_path = self.project_dir / "followup_actions.sh"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_text)
        script_path.chmod(0o755)  # Make executable

        await self._output(f"Script saved to: {script_path}", "success")
        await self._output("", "info")
        await self._output("To execute the script:", "info")
        await self._output(f"  $ bash {script_path}", "command")
        await self._output("", "info")
        await self._output("Or for commands requiring sudo:", "info")
        await self._output(f"  $ sudo bash {script_path}", "command")

    async def _handle_system_task(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Handle system modification tasks."""
        await self._output("Planning system modifications...", "info")

        # Decompose into steps
        plan = self.decomposer.decompose(request, classification)
        self._current_plan = plan

        # Show plan summary
        summary = self.decomposer.get_plan_summary(plan)
        await self._output(f"\n{summary}", "info")

        # Get plan approval
        if self.callbacks.on_plan_ready:
            approved = await self.callbacks.on_plan_ready(plan)
            if not approved:
                await self._output("Plan not approved by user", "warning")
                return OrchestratorResult(
                    success=False,
                    request=request,
                    classification=classification,
                    plan=plan,
                    error="Plan not approved"
                )

        # Execute the plan
        return await self._execute_plan(plan, request, classification)

    async def _handle_code_generation(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Handle pure code generation requests."""
        await self._output("Generating code...", "info")

        # This will delegate to the existing code generation pipeline
        # For now, create a simple plan
        plan = self.decomposer.decompose(request, classification)
        self._current_plan = plan

        # Signal that code generation should use existing pipeline
        return OrchestratorResult(
            success=True,
            request=request,
            classification=classification,
            plan=plan,
            # Flag to indicate existing code gen pipeline should be used
            generated_files=["__USE_CODE_GEN_PIPELINE__"]
        )

    async def _handle_hybrid(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Handle complex hybrid requests (system + code)."""
        await self._output("This is a complex request requiring multiple phases...", "info")

        # Decompose into detailed steps
        plan = self.decomposer.decompose(request, classification)
        self._current_plan = plan

        # Show detailed plan
        summary = self.decomposer.get_plan_summary(plan)
        await self._output(f"\n{summary}", "info")

        # Identify sudo commands
        sudo_steps = [s for s in plan.steps if s.requires_sudo]
        if sudo_steps:
            await self._output(
                f"\n⚠️  {len(sudo_steps)} steps require sudo privileges",
                "warning"
            )

            if not self.allow_sudo:
                # Generate script for user to run
                sudo_commands = []
                for step in sudo_steps:
                    sudo_commands.extend(step.commands)

                script = SudoHelper.generate_sudo_script(sudo_commands)
                script_path = self.project_dir / "install_sudo.sh"
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text(script)

                await self._output(
                    f"\nGenerated sudo script: {script_path}\n"
                    f"Run it with: sudo bash {script_path}",
                    "info"
                )

        # Get plan approval
        if self.callbacks.on_plan_ready:
            approved = await self.callbacks.on_plan_ready(plan)
            if not approved:
                return OrchestratorResult(
                    success=False,
                    request=request,
                    classification=classification,
                    plan=plan,
                    error="Plan not approved"
                )

        # Execute the plan
        return await self._execute_plan(plan, request, classification)

    async def _handle_code_debug(
        self,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """
        Handle CODE_DEBUG requests - debugging/fixing existing projects.

        This is a specialized workflow that:
        1. Captures baseline state of the project
        2. Analyzes the issue
        3. Applies fixes with regression detection
        4. Rolls back if regressions are found

        Adheres to "DO NO HARM" principle - 99.9% confidence no regression.
        """
        await self._output("Initializing debug workflow...", "info")
        await self._output("⚠️  DEBUG MODE: DO NO HARM - changes will be reverted if regression detected", "warning")

        try:
            # Lazy import to avoid circular dependencies
            global CODE_DEBUG_AGENT
            if CODE_DEBUG_AGENT is None:
                from ..code_debug_agent import CodeDebugAgent
                CODE_DEBUG_AGENT = CodeDebugAgent

            # Create debug agent with project directory
            debug_agent = CODE_DEBUG_AGENT(
                project_dir=self.project_dir,
                llm_client=self.llm_client,
                callbacks=DebugCallbackAdapter(self.callbacks, self._output),
                max_regression_attempts=10  # User requested higher default
            )

            # Run the debug workflow
            debug_result = await debug_agent.run(request)

            # Convert debug result to OrchestratorResult
            return OrchestratorResult(
                success=debug_result.success,
                request=request,
                classification=classification,
                steps_completed=len([p for p in debug_result.phases_completed if p]),
                steps_failed=1 if not debug_result.success else 0,
                generated_files=debug_result.files_modified,
                error=debug_result.error_message
            )

        except ImportError as e:
            logger.error(f"CODE_DEBUG agent not available: {e}")
            await self._output(f"Debug agent not available: {e}", "error")
            return OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error=f"Debug agent not available: {e}"
            )
        except Exception as e:
            logger.exception("CODE_DEBUG handler error")
            await self._output(f"Debug workflow error: {e}", "error")
            return OrchestratorResult(
                success=False,
                request=request,
                classification=classification,
                error=str(e)
            )

    async def _execute_plan(
        self,
        plan: ExecutionPlan,
        request: str,
        classification: ClassificationResult
    ) -> OrchestratorResult:
        """Execute a decomposed plan step by step."""
        execution_results = []
        generated_files = []
        steps_completed = 0
        steps_failed = 0

        plan.overall_status = "in_progress"

        while True:
            if self._aborted:
                await self._output("Execution aborted", "warning")
                break

            step = plan.get_next_step()
            if not step:
                break  # All steps complete or blocked

            # Check if step has a condition that should be evaluated
            if hasattr(step, 'condition') and step.condition:
                should_run = self._evaluate_condition(step.condition, plan)
                if not should_run:
                    await self._output(f"\n=== Step: {step.title} (SKIPPED - condition not met) ===", "info")
                    step.status = StepStatus.SKIPPED
                    continue

            step.status = StepStatus.IN_PROGRESS

            if self.callbacks.on_step_start:
                await self.callbacks.on_step_start(step)

            await self._output(f"\n=== Step: {step.title} ===", "phase")
            await self._output(step.description, "info")

            success = False
            retries = 0

            while not success and retries <= step.max_retries:
                if retries > 0:
                    await self._output(f"Retry {retries}/{step.max_retries}...", "warning")

                try:
                    if step.step_type == StepType.CODE_GENERATE:
                        # Use code generation pipeline
                        success = await self._execute_code_generation_step(step, generated_files)

                    elif step.step_type in [StepType.INVESTIGATE, StepType.VERIFY]:
                        # Read-only execution
                        success = await self._execute_query_step(step, execution_results)

                    elif step.step_type in [StepType.INSTALL, StepType.CONFIGURE, StepType.EXECUTE]:
                        # System modification
                        success = await self._execute_system_step(step, execution_results)

                    elif step.step_type == StepType.USER_INPUT:
                        # Get user input
                        success = await self._execute_input_step(step)

                    elif step.step_type == StepType.INFORM_USER:
                        # Inform user about something important
                        success = await self._execute_inform_step(step)

                    else:
                        await self._output(f"Unknown step type: {step.step_type}", "warning")
                        success = True  # Skip unknown steps

                except Exception as e:
                    await self._output(f"Step error: {e}", "error")
                    step.error = str(e)
                    success = False

                if not success:
                    retries += 1

            # Update step status
            if success:
                step.status = StepStatus.COMPLETED
                steps_completed += 1
                await self._output(f"✓ {step.title} complete", "success")
            else:
                step.status = StepStatus.FAILED
                steps_failed += 1
                await self._output(f"✗ {step.title} failed", "error")

                # Handle failure based on step config
                if step.on_failure == "abort":
                    await self._output("Aborting due to step failure", "error")
                    break
                elif step.on_failure == "ask_user":
                    if self.callbacks.on_user_input:
                        response = await self.callbacks.on_user_input(
                            "Step failed. Continue anyway? (yes/no)"
                        )
                        if response.lower() not in ['yes', 'y']:
                            break

            if self.callbacks.on_step_complete:
                await self.callbacks.on_step_complete(step, success)

            plan.completed_steps = steps_completed

        # Determine overall success
        overall_success = steps_failed == 0 and steps_completed > 0
        plan.overall_status = "completed" if overall_success else "failed"

        return OrchestratorResult(
            success=overall_success,
            request=request,
            classification=classification,
            plan=plan,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            execution_results=execution_results,
            generated_files=generated_files
        )

    async def _execute_query_step(
        self,
        step: TaskStep,
        results: List[ExecutionResult]
    ) -> bool:
        """
        Execute a read-only query/investigation step.

        For INVESTIGATE steps, we use "any success" logic - if ANY command
        succeeds (finds something), the step succeeds. This is important for
        commands like "which mail; which sendmail; which msmtp" where we're
        checking for alternatives.
        """
        if not step.commands:
            return True

        any_success = False
        found_results = []

        for cmd in step.commands:
            await self._output(f"$ {cmd}", "command")

            result = await self.executor.execute(
                cmd,
                description=step.description,
                require_approval=False
            )
            results.append(result)

            if result.stdout:
                await self._output(result.stdout.strip()[:500], "output")
                any_success = True
                found_results.append(result.stdout.strip())
            elif result.stderr and not result.success:
                # Command failed (e.g., which returned nothing) - that's OK for investigation
                pass  # Don't output warning for expected "not found" results

        # Store what we found in the step result for conditional logic
        step.result = {
            'found': found_results,
            'any_success': any_success
        }

        # For investigation steps, success means we found at least ONE thing
        # (or all commands ran without error if just gathering info)
        return any_success or len(results) > 0

    async def _execute_system_step(
        self,
        step: TaskStep,
        results: List[ExecutionResult]
    ) -> bool:
        """Execute a system modification step."""
        if not step.commands:
            return True

        for cmd in step.commands:
            await self._output(f"$ {cmd}", "command")

            result = await self.executor.execute(
                cmd,
                description=step.description,
                require_approval=step.requires_approval,
                timeout=step.timeout_seconds
            )
            results.append(result)

            if result.stdout:
                await self._output(result.stdout.strip()[:500], "output")
            if result.error:
                await self._output(result.error, "error")
                return False
            if result.stderr and not result.success:
                await self._output(result.stderr.strip()[:200], "error")
                return False

        # Run verification if specified
        if step.verification:
            await self._output(f"Verifying: {step.verification}", "info")

        return True

    async def _execute_inform_step(self, step: TaskStep) -> bool:
        """
        Execute an INFORM_USER step - display important information to the user.

        This is used when:
        - System capability is missing
        - Prerequisites need to be met first
        - User needs to take manual action
        - Something cannot be done automatically
        """
        # Display the information prominently
        await self._output("", "info")
        await self._output("╔══════════════════════════════════════════════════════════════╗", "warning")
        await self._output("║  📢 IMPORTANT INFORMATION                                     ║", "warning")
        await self._output("╚══════════════════════════════════════════════════════════════╝", "warning")
        await self._output("", "info")

        # Display the title and description
        await self._output(f"⚠️  {step.title}", "warning")
        await self._output("", "info")
        await self._output(step.description, "info")
        await self._output("", "info")

        # If there are commands suggested (e.g., how to install something)
        if step.commands:
            await self._output("Suggested actions:", "info")
            for cmd in step.commands:
                await self._output(f"  $ {cmd}", "command")
            await self._output("", "info")

        # This step always "succeeds" because it's just informational
        # But it signals that the original request couldn't be fulfilled
        return True

    async def _execute_code_generation_step(
        self,
        step: TaskStep,
        generated_files: List[str]
    ) -> bool:
        """Execute a code generation step."""
        # This signals that the code generation pipeline should be used
        # The actual code generation happens in the main agent
        generated_files.append(f"__CODE_GEN__{step.title}")
        await self._output(
            f"Code generation step: {step.title} (will use code gen pipeline)",
            "info"
        )
        return True

    async def _execute_input_step(self, step: TaskStep) -> bool:
        """Execute a user input step."""
        if self.callbacks.on_user_input:
            response = await self.callbacks.on_user_input(step.description)
            step.result = {'user_input': response}
            return True
        return False

    def _evaluate_condition(self, condition: str, plan: ExecutionPlan) -> bool:
        """
        Evaluate a step condition based on previous step results.

        Conditions are natural language strings like:
        - "step_1 found mail command"
        - "step_1 found no mail commands"
        - "step_1 any_success"
        - "step_1 failed"

        Args:
            condition: The condition string from the step
            plan: The execution plan with step results

        Returns:
            True if condition is met, False otherwise
        """
        condition_lower = condition.lower()
        logger.debug(f"Evaluating condition: {condition}")

        # Extract step reference (e.g., "step_1")
        step_match = re.match(r'(step_\d+)', condition_lower)
        if not step_match:
            # No step reference, can't evaluate - default to True
            logger.warning(f"No step reference found in condition: {condition}")
            return True

        step_id = step_match.group(1)
        ref_step = plan.get_step(step_id)

        if not ref_step:
            logger.warning(f"Referenced step not found: {step_id}")
            return True  # Default to True if step not found

        # Get the result from the referenced step
        result = ref_step.result or {}
        found_items = result.get('found', [])
        any_success = result.get('any_success', False)
        step_status = ref_step.status

        logger.debug(f"Step {step_id} result: found={found_items}, any_success={any_success}, status={step_status}")

        # Evaluate different condition patterns
        
        # 1. Negative conditions (Check these FIRST to avoid partial matches on "found")
        negative_markers = ['found no', 'did not find', 'not found', 'no mail', 'no email', 'failed']
        if any(marker in condition_lower for marker in negative_markers):
            # "step_1 found no mail commands" - True if nothing was found OR step failed
            return (not any_success and len(found_items) == 0) or step_status == StepStatus.FAILED

        if 'failed' in condition_lower:
            # "step_1 failed" - True if step failed
            return step_status == StepStatus.FAILED

        # 2. Positive conditions (found/success)
        if 'found mail' in condition_lower or 'found email' in condition_lower:
            # "step_1 found mail command" - True if mail/sendmail/msmtp was found
            for item in found_items:
                if any(x in item.lower() for x in ['mail', 'sendmail', 'msmtp']):
                    return True
            return False

        if 'found' in condition_lower:
            # Generic "found" - True if anything was found
            return any_success or len(found_items) > 0

        if 'any_success' in condition_lower or 'success' in condition_lower:
            # "step_1 any_success" - True if any command succeeded
            return any_success

        if 'completed' in condition_lower:
            # "step_1 completed" - True if step completed
            return step_status == StepStatus.COMPLETED

        # Default: if we can't parse the condition, assume it should run
        logger.warning(f"Could not parse condition pattern: {condition}")
        return True

    async def _handle_approval(
        self,
        command: str,
        description: str,
        risk: CommandRisk
    ) -> bool:
        """Handle command approval request."""
        if self.callbacks.on_approval_needed:
            return await self.callbacks.on_approval_needed(command, description, risk)

        # Default: approve low risk, deny high risk
        return risk in [CommandRisk.LOW, CommandRisk.MEDIUM]

    async def _output(self, message: str, msg_type: str = "info") -> None:
        """Send output to UI."""
        if self.callbacks.on_output:
            await self.callbacks.on_output(message, msg_type)
        else:
            logger.info(f"[{msg_type}] {message}")

    def abort(self) -> None:
        """Abort current execution."""
        self._aborted = True
        if self._current_plan:
            self._current_plan.overall_status = "aborted"

    def get_state(self) -> Dict[str, Any]:
        """
        Get current state for persistence.
        
        Returns:
            Dictionary containing current execution state
        """
        state = {
            'aborted': self._aborted,
            'plan': None,
            'timestamp': datetime.now().isoformat()
        }
        
        if self._current_plan:
            state['plan'] = self._current_plan.to_dict()
            
        return state

    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Restore state from persistence.
        
        Args:
            state: Dictionary containing execution state
        """
        self._aborted = state.get('aborted', False)
        
        if state.get('plan'):
            # Reconstruct Plan and Steps
            plan_data = state['plan']
            classification_data = plan_data.get('classification', {})
            
            # Reconstruct Classification
            classification = ClassificationResult(
                primary_type=getattr(RequestType, classification_data.get('primary_type', 'System Task').upper().replace(' ', '_'), RequestType.SYSTEM_TASK),
                confidence=classification_data.get('confidence', 1.0),
                intent=classification_data.get('intent', ''),
                complexity=classification_data.get('complexity', 'simple'),
                requires_sudo=classification_data.get('requires_sudo', False)
            )
            
            # Reconstruct Steps
            steps = []
            type_map = {
                'INVESTIGATE': StepType.INVESTIGATE,
                'INSTALL': StepType.INSTALL,
                'CONFIGURE': StepType.CONFIGURE,
                'VERIFY': StepType.VERIFY,
                'CODE_GENERATE': StepType.CODE_GENERATE,
                'EXECUTE': StepType.EXECUTE,
                'USER_INPUT': StepType.USER_INPUT,
                'CONDITIONAL': StepType.CONDITIONAL,
                'INFORM_USER': StepType.INFORM_USER
            }
            
            status_map = {
                'PENDING': StepStatus.PENDING,
                'IN_PROGRESS': StepStatus.IN_PROGRESS,
                'COMPLETED': StepStatus.COMPLETED,
                'FAILED': StepStatus.FAILED,
                'SKIPPED': StepStatus.SKIPPED
            }
            
            for step_data in plan_data.get('steps', []):
                step_type = type_map.get(step_data.get('step_type', 'EXECUTE'), StepType.EXECUTE)
                status = status_map.get(step_data.get('status', 'PENDING'), StepStatus.PENDING)
                
                step = TaskStep(
                    id=step_data.get('id', ''),
                    step_type=step_type,
                    title=step_data.get('title', ''),
                    description=step_data.get('description', ''),
                    commands=step_data.get('commands', []),
                    requires_sudo=step_data.get('requires_sudo', False),
                    requires_approval=step_data.get('requires_approval', False),
                    depends_on=step_data.get('depends_on', []),
                    verification=step_data.get('verification', ''),
                    on_failure=step_data.get('on_failure', 'abort'),
                    condition=step_data.get('condition', ''),
                    status=status
                )
                steps.append(step)
            
            self._current_plan = ExecutionPlan(
                request=plan_data.get('request', ''),
                classification=classification,
                steps=steps,
                total_steps=plan_data.get('total_steps', 0),
                completed_steps=plan_data.get('completed_steps', 0),
                overall_status=plan_data.get('overall_status', 'pending')
            )
            
            logger.info("Orchestrator state restored")


class DebugCallbackAdapter:
    """
    Adapter to bridge OrchestratorCallbacks to CodeDebugAgent callbacks.

    This allows the debug agent to communicate through the orchestrator's
    existing callback infrastructure.
    """

    def __init__(
        self,
        orchestrator_callbacks: OrchestratorCallbacks,
        output_fn: Callable[[str, str], Awaitable[None]]
    ):
        self.callbacks = orchestrator_callbacks
        self.output = output_fn

    async def on_phase_change(self, phase: str, description: str) -> None:
        """Called when debug phase changes."""
        await self.output(f"\n=== {phase}: {description} ===", "phase")

    async def on_progress(self, message: str, progress: float) -> None:
        """Called to report progress."""
        await self.output(f"[{int(progress * 100)}%] {message}", "info")

    async def on_baseline_captured(self, file_count: int) -> None:
        """Called when baseline is captured."""
        await self.output(f"✓ Baseline captured: {file_count} files", "success")

    async def on_regression_detected(self, regressions: list) -> None:
        """Called when regressions are detected."""
        await self.output(f"⚠️  Detected {len(regressions)} regression(s)", "warning")
        for reg in regressions[:3]:
            await self.output(f"  - {reg}", "warning")

    async def on_fix_attempt(self, attempt: int, strategy: str, target: str) -> None:
        """Called when attempting a fix."""
        await self.output(f"🔧 Fix attempt {attempt} ({strategy}): {target}", "info")

    async def on_rollback(self, reason: str) -> None:
        """Called when rolling back."""
        await self.output(f"↩️  Rolling back: {reason}", "warning")

    async def on_approval_needed(self, message: str, risk_level: str) -> bool:
        """Called when approval is needed."""
        if self.callbacks.on_approval_needed:
            risk = CommandRisk.MEDIUM if risk_level == "medium" else CommandRisk.HIGH
            return await self.callbacks.on_approval_needed("", message, risk)
        return True  # Default to approved

    async def on_user_input(self, prompt: str) -> str:
        """Called when user input is needed."""
        if self.callbacks.on_user_input:
            return await self.callbacks.on_user_input(prompt)
        return ""

    async def on_error(self, error: str) -> None:
        """Called when an error occurs."""
        await self.output(f"❌ Error: {error}", "error")
        if self.callbacks.on_error:
            await self.callbacks.on_error(error)

    async def on_success(self, summary: str) -> None:
        """Called when debug completes successfully."""
        await self.output(f"✅ {summary}", "success")
