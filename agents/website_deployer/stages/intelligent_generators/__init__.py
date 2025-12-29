"""
Intelligent Code Generators
============================

Multi-stage LLM-based code generation system that:
1. Analyzes and dissects user prompts
2. Elaborates requirements with missing details
3. Plans generation workflow
4. Generates code using targeted LLM prompts
5. Assembles and verifies consistency
6. Deploys validated applications
"""

from .prompt_analyzer import PromptAnalyzer, PromptAnalysis
from .requirement_elaborator import RequirementElaborator, DetailedSpecification
from .workflow_planner import WorkflowPlanner, GenerationWorkflow
from .llm_code_generator import LLMCodeGenerator, GeneratedFile
from .assembly_coordinator import AssemblyCoordinator, AssembledProject
from .consistency_verifier import ConsistencyVerifier, VerificationReport

__all__ = [
    "PromptAnalyzer",
    "PromptAnalysis",
    "RequirementElaborator",
    "DetailedSpecification",
    "WorkflowPlanner",
    "GenerationWorkflow",
    "LLMCodeGenerator",
    "GeneratedFile",
    "AssemblyCoordinator",
    "AssembledProject",
    "ConsistencyVerifier",
    "VerificationReport",
]
