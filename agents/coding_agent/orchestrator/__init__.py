"""
Intelligent Request Orchestrator
================================

Provides semantic classification and intelligent routing of user requests.
Handles complex mixed requests that require both system operations and code generation.

Components:
- RequestClassifier: Semantic classification of request types
- TaskDecomposer: Break complex requests into atomic steps
- SystemExecutor: Safe command execution with approval workflow
- VerificationLoop: Verify and retry until success
- Orchestrator: Main coordinator

Example:
    "Check my system and install LAMP stack, then create a PHP form"

    This gets decomposed into:
    1. [SYSTEM_QUERY] Check current system (OS, installed packages)
    2. [SYSTEM_TASK] Install Apache (with approval)
    3. [SYSTEM_TASK] Install MySQL (with approval)
    4. [SYSTEM_TASK] Install PHP (with approval)
    5. [VERIFY] Test each component
    6. [SYSTEM_TASK] Configure Apache for PHP
    7. [CODE_GEN] Create index.php with form
    8. [CODE_GEN] Create database schema
    9. [VERIFY] Test complete integration
"""

from .request_classifier import RequestClassifier, RequestType, ClassificationResult
from .task_decomposer import TaskDecomposer, TaskStep, StepType
from .system_executor import SystemExecutor, CommandRisk, ExecutionResult
from .orchestrator import Orchestrator, OrchestratorCallbacks, OrchestratorResult

__all__ = [
    'RequestClassifier',
    'RequestType',
    'ClassificationResult',
    'TaskDecomposer',
    'TaskStep',
    'StepType',
    'SystemExecutor',
    'CommandRisk',
    'ExecutionResult',
    'Orchestrator',
    'OrchestratorCallbacks',
    'OrchestratorResult',
]
