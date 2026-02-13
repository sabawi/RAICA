"""
Intelligent Request Orchestrator
================================

Provides semantic classification and intelligent routing of user requests.
Handles complex mixed requests that require both system operations and code generation.

Components:
- RequestClassifier: Semantic classification of request types
- TaskDecomposer: Break complex requests into atomic steps
- SystemExecutor: Safe command execution with approval workflow
- UniversalHandler: Investigation-First pattern for ALL requests
- Orchestrator: Main coordinator

Architecture Evolution:
~~~~~~~~~~~~~~~~~~~~~~~
Traditional (OLD):
    Request → Classify → Route to handler → Create plan → Execute → Skip logic

Universal Investigation-First (NEW):
    Request → TRIAGE → GATHER → DECIDE → ACT → VERIFY

The Universal Handler eliminates speculative planning by:
1. TRIAGE: Asking LLM what information it needs
2. GATHER: Executing triage requests (file reads, commands, searches)
3. DECIDE: LLM decides action WITH full context
4. ACT: Execute the decided action (EXECUTE/FIX/CREATE/RESPOND)
5. VERIFY: Confirm success

Token Savings: ~40-60% by avoiding speculative CODE_GENERATE steps
that would later be skipped.

Example:
    "Check my email for bills"

    OLD: Classify → Create plan with CODE_GENERATE → Execute → Skip CODE_GENERATE
    NEW: TRIAGE → "What scripts exist?" → GATHER → "find_bills.py found" → DECIDE → EXECUTE
"""

from .request_classifier import RequestClassifier, RequestType, ClassificationResult
from .task_decomposer import TaskDecomposer, TaskStep, StepType
from .system_executor import SystemExecutor, CommandRisk, ExecutionResult
from .orchestrator import Orchestrator, OrchestratorCallbacks, OrchestratorResult
from .universal_handler import (
    UniversalHandler, UniversalHandlerCallbacks, UniversalHandlerResult,
    TriageActionType, TriageAction, TriageResult,
    DecisionType, Decision
)

__all__ = [
    # Traditional components (still used for some request types)
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
    # Universal Handler (new architecture)
    'UniversalHandler',
    'UniversalHandlerCallbacks',
    'UniversalHandlerResult',
    'TriageActionType',
    'TriageAction',
    'TriageResult',
    'DecisionType',
    'Decision',
]
