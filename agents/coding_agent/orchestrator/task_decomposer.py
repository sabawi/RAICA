"""
Task Decomposer
===============

Breaks down complex user requests into atomic, executable steps.
Uses LLM to understand requirements and create a logical execution plan.
"""

import re
import json
import logging
from enum import Enum, auto
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .request_classifier import RequestType, ClassificationResult
from ..utils.json_utils import sanitize_json

logger = logging.getLogger(__name__)


class StepType(Enum):
    """Types of execution steps."""
    RESEARCH = auto()        # Research command/library/API before using it
    INVESTIGATE = auto()     # Gather information about system state
    INSTALL = auto()         # Install packages/software
    CONFIGURE = auto()       # Configure services/applications
    VERIFY = auto()          # Verify/test something works
    CODE_GENERATE = auto()   # Generate code files
    EXECUTE = auto()         # Run a command or script
    USER_INPUT = auto()      # Get input from user
    CONDITIONAL = auto()     # Conditional step based on previous results
    INFORM_USER = auto()     # Inform user about something (can't do X, need Y first)
    WEB_SEARCH = auto()      # Search the web for information


class StepStatus(Enum):
    """Status of a step."""
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class TaskStep:
    """A single atomic step in the execution plan."""
    id: str                              # Unique step ID (e.g., "step_1")
    step_type: StepType                  # Type of step
    title: str                           # Short title
    description: str                     # Detailed description
    commands: List[str] = field(default_factory=list)  # Commands to execute
    requires_sudo: bool = False          # Needs sudo
    requires_approval: bool = False      # Needs user approval
    depends_on: List[str] = field(default_factory=list)  # Step IDs this depends on
    verification: str = ""               # How to verify success
    on_failure: str = "abort"            # abort, retry, skip, ask_user
    max_retries: int = 2                 # Max retry attempts
    timeout_seconds: int = 300           # Timeout for this step
    condition: str = ""                  # Condition for when this step should run
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Parameters extracted by LLM from user's request
    target_directory: str = ""           # Target directory for code generation
    code_prompt: str = ""                # Specific prompt for code generation

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'step_type': self.step_type.name,
            'title': self.title,
            'description': self.description,
            'commands': self.commands,
            'requires_sudo': self.requires_sudo,
            'requires_approval': self.requires_approval,
            'depends_on': self.depends_on,
            'verification': self.verification,
            'on_failure': self.on_failure,
            'condition': self.condition,
            'status': self.status.name
        }


@dataclass
class ExecutionPlan:
    """Complete execution plan for a request."""
    request: str                         # Original request
    classification: ClassificationResult # How request was classified
    steps: List[TaskStep] = field(default_factory=list)
    total_steps: int = 0
    completed_steps: int = 0
    current_step_index: int = 0
    overall_status: str = "pending"      # pending, in_progress, completed, failed

    def get_next_step(self) -> Optional[TaskStep]:
        """Get the next pending step."""
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                # Check dependencies
                deps_met = all(
                    self.get_step(dep_id).status == StepStatus.COMPLETED
                    for dep_id in step.depends_on
                    if self.get_step(dep_id)
                )
                if deps_met:
                    return step
        return None

    def get_step(self, step_id: str) -> Optional[TaskStep]:
        """Get step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'request': self.request,
            'classification': self.classification.to_dict(),
            'steps': [s.to_dict() for s in self.steps],
            'total_steps': self.total_steps,
            'completed_steps': self.completed_steps,
            'overall_status': self.overall_status
        }


class TaskDecomposer:
    """
    Decomposes complex requests into atomic execution steps.

    Uses LLM to:
    1. Understand the full scope of the request
    2. Identify all required sub-tasks
    3. Order tasks by dependencies
    4. Define verification criteria

    ARCHITECTURE: LLM decides everything, RAICA executes blindly.
    No hardcoded templates or keyword matching allowed.
    """

    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize the decomposer.

        Args:
            llm_client: LLM client for intelligent decomposition
        """
        self.llm_client = llm_client

    def decompose(
        self,
        request: str,
        classification: ClassificationResult
    ) -> ExecutionPlan:
        """
        Decompose a request into an execution plan.

        ARCHITECTURE: Always uses LLM for decomposition.
        No hardcoded templates or keyword matching.

        Args:
            request: User's request
            classification: How the request was classified

        Returns:
            ExecutionPlan with ordered steps
        """
        logger.info(f"Decomposing request: {request[:50]}...")
        logger.info(f"Classification: {classification.primary_type.name}")

        # ALWAYS use LLM for decomposition - no hardcoded paths
        plan = self._llm_decompose(request, classification)

        plan.total_steps = len(plan.steps)
        return plan

    def _llm_decompose(
        self,
        request: str,
        classification: ClassificationResult
    ) -> ExecutionPlan:
        """Use LLM for intelligent decomposition of requests.

        ARCHITECTURE: LLM decides the execution plan, RAICA executes.
        Fails explicitly if LLM is unavailable.
        """
        if not self.llm_client:
            logger.error("LLM client required for task decomposition - cannot proceed without LLM")
            raise RuntimeError("Task decomposition requires LLM client. Cannot decompose request without LLM.")

        prompt = f"""Decompose this request into atomic execution steps with EXACT parameters extracted from the user's request.

REQUEST: {request}

CLASSIFICATION:
- Type: {classification.primary_type.name}
- Intent: {classification.intent}
- Requires sudo: {classification.requires_sudo}
- Complexity: {classification.complexity}

⚠️ CRITICAL: Extract EXACT values from the user's request:
- If user specifies a directory name, use THAT EXACT name (don't generate random names)
- If user specifies a location, use THAT EXACT location
- If user specifies file names, technology, features - extract and use them

Create a step-by-step execution plan. For each step, specify:
1. Type: INVESTIGATE, INSTALL, CONFIGURE, VERIFY, CODE_GENERATE, EXECUTE
2. Commands to run with EXACT parameters from user's request
3. Dependencies (which steps must complete first)
4. How to verify success

STEP TYPES:
- RESEARCH: Gather information before taking action (search docs, check APIs)
- INVESTIGATE: Check current system/project state (what's installed, file structure)
- EXECUTE: Run shell commands (e.g., mkdir, cp, mv)
- CODE_GENERATE: Generate code files (extracts prompt and target directory from request)
- INSTALL: Install packages (requires sudo and approval)
- CONFIGURE: Configure services/apps after installation (edit config files, set env vars)
- VERIFY: Check that everything works (run tests, check service status)

EXAMPLE - INVESTIGATE (check system state first):
[
    {{
        "id": "step_1",
        "step_type": "INVESTIGATE",
        "title": "Check Current State",
        "description": "Check what's already installed and configured",
        "commands": ["ls -la", "cat package.json 2>/dev/null || cat requirements.txt 2>/dev/null || echo 'No package file'"],
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": [],
        "verification": "Commands complete without error"
    }}
]
NOTE: Adapt INVESTIGATE commands to the project type:
- Python projects: which python3, pip list, cat requirements.txt
- Node.js projects: which node, npm list, cat package.json
- Web apps: ls *.html *.js *.css
- System services: systemctl status, which <binary>

EXAMPLE - CONFIGURE (after installation):
[
    {{
        "id": "step_1",
        "step_type": "CONFIGURE",
        "title": "Configure Service",
        "description": "Set up nginx configuration for the app",
        "commands": ["cp app.conf /etc/nginx/sites-available/", "ln -s /etc/nginx/sites-available/app.conf /etc/nginx/sites-enabled/"],
        "requires_sudo": true,
        "requires_approval": true,
        "depends_on": ["install_nginx"],
        "verification": "nginx -t returns OK"
    }}
]

EXAMPLE - VERIFY (test everything works):
[
    {{
        "id": "step_final",
        "step_type": "VERIFY",
        "title": "Verify Installation",
        "description": "Confirm everything is working correctly",
        "commands": ["systemctl status nginx", "curl -s http://localhost"],
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": ["configure_nginx"],
        "verification": "Service is running and responds to requests"
    }}
]

EXAMPLE - If user says "create game in directory my-game":
[
    {{
        "id": "step_1",
        "step_type": "EXECUTE",
        "title": "Create Target Directory",
        "description": "Create directory exactly as user specified: my-game",
        "commands": ["mkdir -p ./my-game"],
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": [],
        "verification": "Directory ./my-game exists"
    }},
    {{
        "id": "step_2",
        "step_type": "CODE_GENERATE",
        "title": "Generate Game Code",
        "description": "Generate game code in the user-specified directory",
        "commands": [],
        "target_directory": "./my-game",
        "code_prompt": "Create the game as user requested (extract details from original request)",
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": ["step_1"],
        "verification": "Code files created in ./my-game"
    }}
]

EXAMPLE - System package installation:
[
    {{
        "id": "step_1",
        "step_type": "INSTALL",
        "title": "Install Package",
        "description": "Install the requested package",
        "commands": ["apt update", "apt install -y nginx"],
        "requires_sudo": true,
        "requires_approval": true,
        "depends_on": [],
        "verification": "nginx --version works"
    }}
]

EXAMPLE - Web search + file creation (HYBRID request):
[
    {{
        "id": "step_1",
        "step_type": "WEB_SEARCH",
        "title": "Research Topic Online",
        "description": "Search the web for the requested information",
        "search_query": "top AI developers on Twitter/X with their handles",
        "max_results": 20,
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": [],
        "verification": "Search results obtained"
    }},
    {{
        "id": "step_2",
        "step_type": "CODE_GENERATE",
        "title": "Create Output File",
        "description": "Create a file with the search results formatted as requested",
        "commands": [],
        "target_file": "output.txt",
        "code_prompt": "Create a text file listing the search results in the format requested by user",
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": ["step_1"],
        "verification": "Output file created with results"
    }}
]

IMPORTANT RULES:
1. INVESTIGATE steps should come first to understand current state
2. INSTALL steps need sudo and approval
3. CONFIGURE steps come after installation
4. VERIFY steps should test that everything works
5. CODE_GENERATE steps create files (no sudo needed)
6. WEB_SEARCH steps search the internet for information (include search_query field)
7. Each step should be atomic (one clear action)
8. Include dependencies so steps run in correct order
9. Always end with a VERIFY step to confirm success
10. For HYBRID requests with web search + file creation, WEB_SEARCH step comes first, then CODE_GENERATE

🚨🚨🚨 CRITICAL RULE FOR SYSTEM_TASK - DO NOT GENERATE CODE UNLESS ABSOLUTELY NECESSARY 🚨🚨🚨

For SYSTEM_TASK requests (like "check my email", "run the scanner", "execute the tool"):
1. The user wants to EXECUTE something, NOT generate new code!
2. INVESTIGATE step MUST check the PROJECT directory for existing scripts:
   - "ls -la *.py" or "ls -la *.sh" to find existing scripts
   - "ls -la find_bills.py" or similar to check if specific script exists
   - Check the CURRENT DIRECTORY, not home directory!
3. If existing scripts are found, create an EXECUTE step to RUN them
4. DO NOT include CODE_GENERATE step unless INVESTIGATE confirms no usable scripts exist
5. The correct flow is: INVESTIGATE → EXECUTE existing script → VERIFY

EXAMPLE - SYSTEM_TASK (check email with existing script):
[
    {{
        "id": "step_1",
        "step_type": "INVESTIGATE",
        "title": "Check for Existing Email Scripts",
        "description": "Check if email checking scripts already exist in the project",
        "commands": ["ls -la *.py 2>/dev/null || echo 'No Python scripts'", "ls -la find_bills.py 2>/dev/null || echo 'Script not found'"],
        "requires_sudo": false,
        "depends_on": [],
        "verification": "List of available scripts"
    }},
    {{
        "id": "step_2",
        "step_type": "EXECUTE",
        "title": "Run Email Checker",
        "description": "Execute the existing email checking script",
        "commands": ["python3 find_bills.py --gmail"],
        "requires_sudo": false,
        "requires_approval": true,
        "depends_on": ["step_1"],
        "verification": "Script executes and outputs results"
    }},
    {{
        "id": "step_3",
        "step_type": "VERIFY",
        "title": "Verify Results",
        "description": "Confirm script ran and displayed results",
        "commands": ["echo 'Check complete'"],
        "requires_sudo": false,
        "depends_on": ["step_2"],
        "verification": "User sees output from script"
    }}
]

DO NOT create CODE_GENERATE steps for SYSTEM_TASK unless investigation proves no scripts exist!

🔧 FIX vs CREATE DECISION:
When existing scripts are found but may not work perfectly:
1. INVESTIGATE the existing script (read it, check its capabilities)
2. ESTIMATE EFFORT for each option:
   - Option A: FIX the existing script (minor modifications, add missing feature)
   - Option B: CREATE new script from scratch
3. Choose the option with LOWER estimated effort
4. If existing script is 70%+ of what's needed → FIX it (CODE_DEBUG path)
5. If existing script is <30% useful or fundamentally broken → CREATE new (CODE_GENERATE)
6. Default bias: PREFER FIXING over creating (reuse existing work!)

EXAMPLE DECISION PROCESS:
- Existing find_bills.py has local mailbox support but user wants Gmail → FIX (add Gmail support)
- Existing script is completely unrelated to the task → CREATE new
- Existing script has the right structure but wrong keywords → FIX (update keywords)
- No existing scripts found → CREATE new

ON_FAILURE OPTIONS (what to do if a step fails):
- "abort": Stop execution immediately (use for critical steps)
- "retry": Retry the step up to max_retries times (use for transient failures)
- "skip": Skip this step and continue (use for optional steps)
- "ask_user": Ask the user what to do (use when uncertain)

CRITICAL NOTES:
- For complex date calculations, choose the right tool for the environment:
  - If Python available: `python3 -c "import datetime; print(datetime.date.fromisocalendar(2026, 33, 1))"`
  - If Node.js available: `node -e "console.log(new Date('2026-08-10').toISOString())"`
  - For simple dates: `date -d "2026-08-10" +%Y-%m-%d`
"""

        try:
            # Use classification model if available (better at JSON)
            if hasattr(self.llm_client, 'generate_for_classification'):
                response = self.llm_client.generate_for_classification(prompt, max_tokens=2000)
            else:
                response = self.llm_client.generate(prompt, max_tokens=2000)
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON array from response with sanitization
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                sanitized = sanitize_json(json_match.group())
                steps_data = json.loads(sanitized)

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
                    'WEB_SEARCH': StepType.WEB_SEARCH,
                    'RESEARCH': StepType.RESEARCH
                }

                for data in steps_data:
                    step_type = type_map.get(data.get('step_type', 'EXECUTE'), StepType.EXECUTE)

                    steps.append(TaskStep(
                        id=data.get('id', f"step_{len(steps)+1}"),
                        step_type=step_type,
                        title=data.get('title', 'Untitled Step'),
                        description=data.get('description', ''),
                        commands=data.get('commands', []),
                        requires_sudo=data.get('requires_sudo', False),
                        requires_approval=data.get('requires_approval', step_type == StepType.INSTALL),
                        depends_on=data.get('depends_on', []),
                        verification=data.get('verification', ''),
                        on_failure=data.get('on_failure', 'ask_user'),
                        max_retries=data.get('max_retries', 2),
                        timeout_seconds=data.get('timeout_seconds', 300),
                        # Parameters extracted by LLM from user's request
                        target_directory=data.get('target_directory', ''),
                        code_prompt=data.get('code_prompt', '')
                    ))

                return ExecutionPlan(
                    request=request,
                    classification=classification,
                    steps=steps
                )

        except Exception as e:
            logger.error(f"LLM decomposition failed: {e}")
            raise RuntimeError(f"LLM decomposition failed: {e}. Cannot proceed without valid execution plan.")

    def _generate_query_commands(self, request: str) -> List[str]:
        """Generate commands for system queries using LLM.

        ARCHITECTURE: LLM decides what commands to run, no hardcoded patterns.
        """
        return self._llm_generate_commands(request, read_only=True)

    def _llm_generate_commands(self, request: str, read_only: bool = False) -> List[str]:
        """Use LLM to generate appropriate shell commands.

        ARCHITECTURE: LLM decides what commands to run based on the request.
        Fails explicitly if LLM unavailable or returns invalid response.

        Args:
            request: User's request text
            read_only: If True, commands must not modify the system

        Returns:
            List of shell commands from LLM

        Raises:
            RuntimeError: If LLM unavailable or fails to generate valid commands
        """
        if not self.llm_client:
            raise RuntimeError("LLM client required for command generation. Cannot proceed without LLM.")

        mode = "READ-ONLY (no modifications)" if read_only else "may include modifications"

        prompt = f"""Generate Linux shell commands to accomplish this request.

USER REQUEST: {request}

Requirements:
1. Generate 1-10 shell commands that accomplish the task
2. Commands {mode} to the system
3. Be specific and complete - the commands will be executed directly
4. If sudo is needed, include sudo in the command
5. Consider safety - include confirmation flags where appropriate

Return your response as JSON:
{{
    "commands": [
        "command1",
        "command2"
    ],
    "requires_sudo": false,
    "description": "Brief description of what these commands do"
}}

IMPORTANT: Return ONLY valid JSON, no other text.
"""

        try:
            # Use classification model if available (better at JSON)
            if hasattr(self.llm_client, 'generate_for_classification'):
                response = self.llm_client.generate_for_classification(prompt, max_tokens=1000)
            else:
                response = self.llm_client.generate(prompt, max_tokens=1000)
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON response
            from ..utils.json_utils import extract_json_from_llm_response
            data = extract_json_from_llm_response(content)

            if data and 'commands' in data:
                commands = data['commands']
                if commands and len(commands) > 0:
                    # Limit to 10 commands max for safety
                    return commands[:10]

            # LLM returned invalid or empty commands - fail explicitly
            logger.error(f"LLM returned invalid commands response: {content[:200]}")
            raise RuntimeError(f"LLM failed to generate valid commands for: {request[:50]}...")

        except RuntimeError:
            raise  # Re-raise RuntimeError as-is
        except Exception as e:
            logger.error(f"LLM command generation failed: {e}")
            raise RuntimeError(f"LLM command generation failed: {e}")

    def _generate_task_commands(self, request: str) -> List[str]:
        """Generate commands for system tasks using LLM.

        ARCHITECTURE: LLM decides what commands to run, no hardcoded patterns.
        """
        return self._llm_generate_commands(request, read_only=False)

    def get_plan_summary(self, plan: ExecutionPlan) -> str:
        """Get a human-readable summary of the plan."""
        lines = [
            f"Execution Plan: {plan.classification.intent}",
            f"Total Steps: {plan.total_steps}",
            f"Complexity: {plan.classification.complexity}",
            ""
        ]

        for i, step in enumerate(plan.steps, 1):
            sudo_marker = "[SUDO]" if step.requires_sudo else ""
            approval_marker = "[APPROVAL NEEDED]" if step.requires_approval else ""
            lines.append(f"{i}. [{step.step_type.name}] {step.title} {sudo_marker} {approval_marker}")
            lines.append(f"   {step.description}")
            if step.commands:
                lines.append(f"   Commands: {len(step.commands)}")
            if step.depends_on:
                lines.append(f"   Depends on: {', '.join(step.depends_on)}")
            lines.append("")

        return "\n".join(lines)
