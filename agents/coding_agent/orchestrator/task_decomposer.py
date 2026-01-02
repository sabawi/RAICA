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

logger = logging.getLogger(__name__)


class StepType(Enum):
    """Types of execution steps."""
    INVESTIGATE = auto()     # Gather information about system state
    INSTALL = auto()         # Install packages/software
    CONFIGURE = auto()       # Configure services/applications
    VERIFY = auto()          # Verify/test something works
    CODE_GENERATE = auto()   # Generate code files
    EXECUTE = auto()         # Run a command or script
    USER_INPUT = auto()      # Get input from user
    CONDITIONAL = auto()     # Conditional step based on previous results
    INFORM_USER = auto()     # Inform user about something (can't do X, need Y first)


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
    """

    # Common step templates for known patterns
    LAMP_STACK_TEMPLATE = [
        TaskStep(
            id="step_1",
            step_type=StepType.INVESTIGATE,
            title="Check System",
            description="Identify OS and current installed packages",
            commands=["cat /etc/os-release", "which apache2 nginx", "which mysql mariadb", "which php"],
            requires_sudo=False,
            verification="Identify what's already installed"
        ),
        TaskStep(
            id="step_2",
            step_type=StepType.INSTALL,
            title="Install Apache",
            description="Install Apache web server",
            commands=["apt update", "apt install -y apache2"],
            requires_sudo=True,
            requires_approval=True,
            depends_on=["step_1"],
            verification="systemctl status apache2"
        ),
        TaskStep(
            id="step_3",
            step_type=StepType.INSTALL,
            title="Install MySQL",
            description="Install MySQL database server",
            commands=["apt install -y mysql-server"],
            requires_sudo=True,
            requires_approval=True,
            depends_on=["step_1"],
            verification="systemctl status mysql"
        ),
        TaskStep(
            id="step_4",
            step_type=StepType.INSTALL,
            title="Install PHP",
            description="Install PHP and Apache module",
            commands=["apt install -y php libapache2-mod-php php-mysql"],
            requires_sudo=True,
            requires_approval=True,
            depends_on=["step_2"],
            verification="php -v"
        ),
        TaskStep(
            id="step_5",
            step_type=StepType.VERIFY,
            title="Verify LAMP Stack",
            description="Test all components are working",
            commands=["systemctl status apache2", "systemctl status mysql", "php -v"],
            depends_on=["step_2", "step_3", "step_4"],
            verification="All services running"
        ),
    ]

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

        Args:
            request: User's request
            classification: How the request was classified

        Returns:
            ExecutionPlan with ordered steps
        """
        logger.info(f"Decomposing request: {request[:50]}...")
        logger.info(f"Classification: {classification.primary_type.name}")

        # For simple requests, use quick decomposition
        if classification.complexity == "simple":
            plan = self._simple_decompose(request, classification)
        else:
            # For complex requests, use LLM
            plan = self._llm_decompose(request, classification)

        plan.total_steps = len(plan.steps)
        return plan

    def _simple_decompose(
        self,
        request: str,
        classification: ClassificationResult
    ) -> ExecutionPlan:
        """Quick decomposition for simple requests."""
        steps = []
        request_lower = request.lower()

        if classification.primary_type == RequestType.SYSTEM_QUERY:
            # Single investigation step
            steps.append(TaskStep(
                id="step_1",
                step_type=StepType.INVESTIGATE,
                title="Check System",
                description=f"Investigate: {classification.intent}",
                commands=self._generate_query_commands(request),
                requires_sudo=classification.requires_sudo,
                verification="Report findings"
            ))

        elif classification.primary_type == RequestType.SYSTEM_TASK:
            # Single execution step with verification
            steps.append(TaskStep(
                id="step_1",
                step_type=StepType.EXECUTE,
                title="Execute Task",
                description=classification.intent,
                commands=self._generate_task_commands(request),
                requires_sudo=classification.requires_sudo,
                requires_approval=True,
                verification="Verify task completed"
            ))
            steps.append(TaskStep(
                id="step_2",
                step_type=StepType.VERIFY,
                title="Verify Result",
                description="Confirm task completed successfully",
                depends_on=["step_1"],
                verification="Check for success indicators"
            ))

        elif classification.primary_type == RequestType.CODE_GENERATION:
            # Code generation step
            steps.append(TaskStep(
                id="step_1",
                step_type=StepType.CODE_GENERATE,
                title="Generate Code",
                description=classification.intent,
                verification="Code files created"
            ))

        elif classification.primary_type == RequestType.HYBRID:
            # Use templates for known hybrid patterns
            if 'lamp' in request_lower or ('apache' in request_lower and 'mysql' in request_lower and 'php' in request_lower):
                # Use LAMP stack template
                import copy
                steps = [copy.deepcopy(step) for step in self.LAMP_STACK_TEMPLATE]

                # Add code generation step if requested
                if 'form' in request_lower or 'page' in request_lower or 'create' in request_lower:
                    steps.append(TaskStep(
                        id=f"step_{len(steps)+1}",
                        step_type=StepType.CODE_GENERATE,
                        title="Generate PHP Application",
                        description="Create PHP form or application",
                        depends_on=["step_5"],
                        verification="PHP files created in /var/www/html"
                    ))
            else:
                # Generic hybrid: system task first, then code gen
                steps.append(TaskStep(
                    id="step_1",
                    step_type=StepType.INVESTIGATE,
                    title="Check System",
                    description="Determine current system state",
                    commands=["uname -a", "cat /etc/os-release", "which apt yum dnf 2>/dev/null"],
                    requires_sudo=False,
                    verification="Identify system requirements"
                ))
                steps.append(TaskStep(
                    id="step_2",
                    step_type=StepType.EXECUTE,
                    title="System Setup",
                    description="Execute required system operations",
                    commands=self._generate_task_commands(request),
                    requires_sudo=classification.requires_sudo,
                    requires_approval=True,
                    depends_on=["step_1"],
                    verification="System setup complete"
                ))
                steps.append(TaskStep(
                    id="step_3",
                    step_type=StepType.CODE_GENERATE,
                    title="Generate Code",
                    description="Generate requested code/application",
                    depends_on=["step_2"],
                    verification="Code files created"
                ))
                steps.append(TaskStep(
                    id="step_4",
                    step_type=StepType.VERIFY,
                    title="Final Verification",
                    description="Verify complete setup works",
                    depends_on=["step_3"],
                    verification="All components functioning"
                ))

        return ExecutionPlan(
            request=request,
            classification=classification,
            steps=steps
        )

    def _llm_decompose(
        self,
        request: str,
        classification: ClassificationResult
    ) -> ExecutionPlan:
        """Use LLM for intelligent decomposition of complex requests."""
        if not self.llm_client:
            logger.warning("No LLM client, falling back to simple decomposition")
            return self._simple_decompose(request, classification)

        prompt = f"""Decompose this complex request into atomic execution steps.

REQUEST: {request}

CLASSIFICATION:
- Type: {classification.primary_type.name}
- Intent: {classification.intent}
- Requires sudo: {classification.requires_sudo}
- Complexity: {classification.complexity}

Create a step-by-step execution plan. For each step, specify:
1. Type: INVESTIGATE, INSTALL, CONFIGURE, VERIFY, CODE_GENERATE, EXECUTE
2. Commands to run (for system steps)
3. Dependencies (which steps must complete first)
4. How to verify success

Output as JSON array:
[
    {{
        "id": "step_1",
        "step_type": "INVESTIGATE",
        "title": "Check Current System",
        "description": "Determine OS and installed packages",
        "commands": ["cat /etc/os-release", "dpkg -l | grep -E 'apache|mysql|php'"],
        "requires_sudo": false,
        "requires_approval": false,
        "depends_on": [],
        "verification": "Identify missing components"
    }},
    {{
        "id": "step_2",
        "step_type": "INSTALL",
        "title": "Install Apache",
        "description": "Install Apache web server",
        "commands": ["apt update", "apt install -y apache2"],
        "requires_sudo": true,
        "requires_approval": true,
        "depends_on": ["step_1"],
        "verification": "systemctl status apache2 shows active"
    }}
]

IMPORTANT RULES:
1. INVESTIGATE steps should come first to understand current state
2. INSTALL steps need sudo and approval
3. CONFIGURE steps come after installation
4. VERIFY steps should test that everything works
5. CODE_GENERATE steps create files (no sudo needed)
6. Each step should be atomic (one clear action)
7. Include dependencies so steps run in correct order

8. Always end with a VERIFY step to confirm success
9. CRITICAL: For complex date math (e.g. ISO weeks loopups), use `python3 -c` instead of `date -d` (GNU date doesn't support week input).
   Example: `python3 -c "import datetime; print(datetime.date.fromisocalendar(2026, 33, 1))"`
"""

        try:
            response = self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON array from response
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                steps_data = json.loads(json_match.group())

                steps = []
                type_map = {
                    'INVESTIGATE': StepType.INVESTIGATE,
                    'INSTALL': StepType.INSTALL,
                    'CONFIGURE': StepType.CONFIGURE,
                    'VERIFY': StepType.VERIFY,
                    'CODE_GENERATE': StepType.CODE_GENERATE,
                    'EXECUTE': StepType.EXECUTE,
                    'USER_INPUT': StepType.USER_INPUT,
                    'CONDITIONAL': StepType.CONDITIONAL
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
                        timeout_seconds=data.get('timeout_seconds', 300)
                    ))

                return ExecutionPlan(
                    request=request,
                    classification=classification,
                    steps=steps
                )

        except Exception as e:
            logger.error(f"LLM decomposition failed: {e}")

        # Fallback to simple
        return self._simple_decompose(request, classification)

    def _generate_query_commands(self, request: str) -> List[str]:
        """Generate commands for system queries using LLM when needed."""
        request_lower = request.lower()
        commands = []

        # Check for common patterns first (fast path)
        if 'nginx' in request_lower:
            commands.extend(['which nginx', 'nginx -v 2>&1', 'systemctl status nginx 2>/dev/null || echo "not running"'])
        elif 'apache' in request_lower:
            commands.extend(['which apache2', 'apache2 -v 2>&1', 'systemctl status apache2 2>/dev/null || echo "not running"'])
        elif 'mysql' in request_lower:
            commands.extend(['which mysql', 'mysql --version 2>&1', 'systemctl status mysql 2>/dev/null || echo "not running"'])
        elif 'php' in request_lower:
            commands.extend(['which php', 'php -v 2>&1'])
        elif 'python' in request_lower:
            commands.extend(['which python3', 'python3 --version 2>&1'])
        elif 'node' in request_lower or 'npm' in request_lower:
            commands.extend(['which node', 'node --version 2>&1', 'npm --version 2>&1'])
        elif 'docker' in request_lower:
            commands.extend(['which docker', 'docker --version 2>&1', 'docker ps 2>/dev/null || echo "not running"'])
        else:
            # Use LLM to generate appropriate commands for this specific query
            commands = self._llm_generate_query_commands(request)

        return commands

    def _llm_generate_query_commands(self, request: str) -> List[str]:
        """Use LLM to generate appropriate shell commands for a query."""
        if not self.llm_client:
            # Fallback to generic if no LLM
            return ['echo "Query: ' + request[:50] + '"']

        prompt = f"""Generate Linux shell commands to answer this user query.

USER QUERY: {request}

Requirements:
1. Generate 1-5 shell commands that will gather the information needed
2. Commands must be READ-ONLY (no modifications to the system)
3. Commands should be safe to run without sudo if possible
4. Output should be informative and answer the user's question

Common patterns:
- For directory listings: ls -lah /path, find /path -type f
- For file ages: find /path -mtime +30 (files older than 30 days)
- For disk usage: du -sh /path/*
- For file counts: find /path -type f | wc -l

- For specific file types: find /path -name "*.ext"
- For date math (weeks/ISO): python3 -c "import datetime; print(datetime.date.fromisocalendar(2026, 33, 1))" (GNU date fails on week input)

Output ONLY the commands, one per line, no explanations:
"""

        try:
            response = self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse commands from response
            commands = []
            for line in content.strip().split('\n'):
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Skip lines that look like explanations
                if any(line.lower().startswith(x) for x in ['this', 'the', 'to ', 'use ', 'note', 'here']):
                    continue
                # Remove markdown code block markers
                if line.startswith('```') or line.endswith('```'):
                    continue
                # Remove leading $ or > prompts
                if line.startswith('$ '):
                    line = line[2:]
                elif line.startswith('> '):
                    line = line[2:]

                if line:
                    commands.append(line)

            # Limit to 5 commands max
            return commands[:5] if commands else ['ls -la ~']

        except Exception as e:
            logger.warning(f"LLM command generation failed: {e}")
            return ['ls -la ~']

    def _generate_task_commands(self, request: str) -> List[str]:
        """Generate commands for system tasks."""
        request_lower = request.lower()
        commands = []

        if 'install' in request_lower:
            if 'nginx' in request_lower:
                commands = ['apt update', 'apt install -y nginx']
            elif 'apache' in request_lower:
                commands = ['apt update', 'apt install -y apache2']
            elif 'mysql' in request_lower:
                commands = ['apt update', 'apt install -y mysql-server']
            elif 'php' in request_lower:
                commands = ['apt update', 'apt install -y php']
            elif 'docker' in request_lower:
                commands = ['curl -fsSL https://get.docker.com | sh']
            elif 'ollama' in request_lower:
                commands = ['curl -fsSL https://ollama.com/install.sh | sh']

        return commands

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
