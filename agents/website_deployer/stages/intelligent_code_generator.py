#!/usr/bin/env python3
"""
Intelligent Code Generator - Main Orchestrator
==============================================

Orchestrates the 7-stage intelligent code generation pipeline.

Stages:
1. Prompt Analyzer: Dissects user prompt
2. Requirement Elaborator: Creates detailed specs
3. Workflow Planner: Plans generation steps
4. LLM Code Generator: Generates code files
5. Assembly Coordinator: Creates project structure
6. Consistency Verifier: Checks correctness
7. Deployment Orchestrator: Deploys application
"""

import logging
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from .llm_client import LLMClient
from .intelligent_generators.prompt_analyzer import PromptAnalyzer, PromptAnalysis
from .intelligent_generators.requirement_elaborator import RequirementElaborator, DetailedSpecification
from .intelligent_generators.workflow_planner import WorkflowPlanner, GenerationWorkflow
from .intelligent_generators.llm_code_generator import LLMCodeGenerator, GeneratedFile
from .intelligent_generators.assembly_coordinator import AssemblyCoordinator, AssembledProject
from .intelligent_generators.consistency_verifier import ConsistencyVerifier, VerificationReport
from .intelligent_generators.tech_stack_config import TechStackConfig

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DeploymentResult:
    """Result of the full deployment process."""
    success: bool
    message: str
    project_path: Optional[str] = None
    verification_report: Optional[VerificationReport] = None
    url: Optional[str] = None


class IntelligentCodeGenerator:
    """
    Multi-stage intelligent code generation system.

    Transforms user prompts into deployed applications through:
    1. Prompt analysis and clarification
    2. Requirement elaboration
    3. Workflow planning
    4. LLM-based code generation (with retries and LLM escalation)
    5. Assembly and verification
    6. Deployment
    """

    MAX_RETRIES = 3  # Maximum retry attempts per stage

    def __init__(self, anthropic_api_key: Optional[str] = None, response_cache=None):
        """
        Initialize intelligent code generator.

        Args:
            anthropic_api_key: Optional API key (uses env var if not provided)
            response_cache: Optional ResponseCache for caching/replaying LLM responses
        """
        # Set API key in environment if provided
        if anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key

        # Initialize LLM client with response cache
        self.llm = LLMClient(response_cache=response_cache)
        self.response_cache = response_cache

        # Initialize stages
        self.prompt_analyzer = PromptAnalyzer(self.llm)
        self.elaborator = RequirementElaborator(self.llm)
        self.planner = WorkflowPlanner()
        self.generator = LLMCodeGenerator(self.llm)
        self.assembler = AssemblyCoordinator()
        self.verifier = ConsistencyVerifier()

        logger.info("IntelligentCodeGenerator initialized")
        logger.info(f"Retry policy: Up to {self.MAX_RETRIES} attempts per stage with LLM escalation")

    def generate(self, user_prompt: str, interactive: bool = True) -> DeploymentResult:
        """
        Generate complete application from user prompt.

        Args:
            user_prompt: User's description of desired application
            interactive: If True, ask clarifying questions

        Returns:
            DeploymentResult with deployed application details
        """
        try:
            logger.info("=" * 60)
            logger.info("INTELLIGENT CODE GENERATION STARTED")
            logger.info("=" * 60)

            # Stage 1: Analyze prompt
            logger.info("[1/7] Analyzing prompt...")
            analysis = self.prompt_analyzer.analyze(user_prompt)

            if interactive and analysis.has_clarifications():
                logger.info("Clarifications needed:")
                analysis = self.prompt_analyzer.ask_clarifications(analysis)

            # Retry loop for stages 2-6 (with validation feedback)
            for attempt in range(1, self.MAX_RETRIES + 1):
                if attempt > 1:
                    logger.info("=" * 60)
                    logger.info(f"RETRY ATTEMPT {attempt}/{self.MAX_RETRIES}")
                    logger.info("=" * 60)

                # Stage 2: Elaborate requirements
                logger.info(f"[2/7] Elaborating requirements... (attempt {attempt}/{self.MAX_RETRIES})")
                detailed_spec = self.elaborator.elaborate(analysis)
                
                # Update stages with tech stack configuration
                tech_config = detailed_spec.get_tech_config()
                logger.info(f"Configuring pipeline for: {tech_config.get_tech_stack_description()}")
                
                self.planner = WorkflowPlanner(tech_config)
                self.generator = LLMCodeGenerator(self.llm, tech_config)
                self.assembler = AssemblyCoordinator(tech_config=tech_config)
                self.verifier = ConsistencyVerifier(tech_config)

                if interactive and attempt == 1:
                    if not self._confirm_proceed(detailed_spec):
                        return DeploymentResult(success=False, message="User cancelled")

                # Stage 3: Plan workflow
                logger.info(f"[3/7] Planning generation workflow... (attempt {attempt}/{self.MAX_RETRIES})")
                workflow = self.planner.plan(detailed_spec)
                logger.info(f"  → {len(workflow.phases)} phases, {workflow.total_files} files")

                # Stage 4: Generate code
                logger.info(f"[4/7] Generating code files... (attempt {attempt}/{self.MAX_RETRIES})")
                generated_files = self.generator.generate_all(workflow)
                logger.info(f"  → Generated {len(generated_files)} files")

                # Stage 5: Assemble project
                logger.info(f"[5/7] Assembling project... (attempt {attempt}/{self.MAX_RETRIES})")
                project = self.assembler.assemble(generated_files, detailed_spec.project_name)
                logger.info(f"  → Project assembled at {project.path}")

                # Stage 6: Verify consistency
                logger.info(f"[6/7] Verifying consistency... (attempt {attempt}/{self.MAX_RETRIES})")
                verification = self.verifier.verify(project, detailed_spec)

                # Check if validation passed
                if not verification.has_critical_issues():
                    # Success! Break out of retry loop
                    logger.info(f"✅ Validation passed on attempt {attempt}/{self.MAX_RETRIES}")
                    break

                # Validation failed
                logger.warning(f"⚠️  Validation failed on attempt {attempt}/{self.MAX_RETRIES}")
                logger.warning("Critical issues found:")

                # Collect all critical issues for feedback
                critical_issues = []
                for issue in (verification.code_integrity_issues +
                             verification.import_issues +
                             verification.dependency_issues +
                             verification.api_issues +
                             verification.schema_issues +
                             verification.security_issues):
                    if issue.severity == "CRITICAL":
                        critical_issues.append(f"  - [{issue.component}] {issue.message}")
                        logger.warning(f"  - [{issue.component}] {issue.message}")

                # If we've exhausted retries, fail
                if attempt >= self.MAX_RETRIES:
                    logger.error("=" * 60)
                    logger.error(f"❌ FAILED after {self.MAX_RETRIES} attempts")
                    logger.error("=" * 60)
                    logger.error("Deployment blocked due to persistent CRITICAL issues:")
                    for issue_msg in critical_issues:
                        logger.error(issue_msg)

                    return DeploymentResult(
                        success=False,
                        message=f"Code generation failed after {self.MAX_RETRIES} attempts - CRITICAL verification issues persist",
                        project_path=str(project.path),
                        verification_report=verification
                    )

                # Prepare feedback for next attempt
                logger.info(f"🔄 Preparing to retry with validation feedback...")
                feedback = self._create_validation_feedback(verification, critical_issues, detailed_spec)

                # NEW: Query RAICA for intelligent fixes based on verification failures
                logger.info(f"🔬 Querying parent RAICA for solutions to verification failures...")
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                fix_research = loop.run_until_complete(
                    self._research_verification_fixes(
                        detailed_spec=detailed_spec,
                        verification_errors=critical_issues,
                        generated_files=generated_files
                    )
                )

                if fix_research['success']:
                    logger.info(f"✅ Got {len(fix_research['fixes'])} fix suggestions from RAICA research")
                    # Append RAICA fixes to feedback string
                    feedback += "\n\n" + "=" * 60 + "\n"
                    feedback += "INTELLIGENT FIXES FROM AGENTIC-RAG RESEARCH:\n"
                    feedback += "=" * 60 + "\n\n"
                    for error_msg, fix_suggestion in fix_research['fixes'].items():
                        feedback += f"Issue: {error_msg}\n"
                        feedback += f"Solution: {fix_suggestion[:500]}...\n\n"  # First 500 chars
                else:
                    logger.warning(f"⚠️ Failed to get fix suggestions: {fix_research.get('error')}")

                # Update the analysis with feedback for next iteration
                analysis = self._enrich_analysis_with_feedback(analysis, feedback)

            # Log warnings but allow deployment to proceed
            if verification.api_issues or verification.schema_issues or verification.security_issues:
                logger.warning("⚠️  Non-critical issues found (deployment will proceed):")
                for issue in verification.api_issues + verification.schema_issues + verification.security_issues:
                    if issue.severity in ["ERROR", "WARNING"]:
                        logger.warning(f"  - [{issue.severity}] [{issue.component}] {issue.message}")
                logger.warning("Review these issues after deployment.")

            # Stage 7: Ready for deployment
            logger.info("[7/7] Code generation complete, ready for deployment")

            logger.info("=" * 60)
            logger.info("✅ INTELLIGENT CODE GENERATION SUCCESSFUL")
            logger.info("=" * 60)

            return DeploymentResult(
                success=True,
                message="Code generation complete and verified",
                project_path=str(project.path),
                verification_report=verification
            )

        except Exception as e:
            logger.error(f"Generation failed: {e}", exc_info=True)
            return DeploymentResult(success=False, message=str(e))

    def _confirm_proceed(self, spec: DetailedSpecification) -> bool:
        """Ask user confirmation to proceed with generation."""
        print("\n" + "=" * 60)
        print(f"Ready to generate: {spec.project_name}")
        print(f"Type: {spec.project_type}")
        print(f"Components: {len(spec.ui_components)} UI, {len(spec.api_endpoints)} API, {len(spec.data_models)} Models")
        print("=" * 60)

        response = input("\nProceed with code generation? (y/n): ").strip().lower()
        return response == 'y'

    async def _research_verification_fixes(
        self,
        detailed_spec: DetailedSpecification,
        verification_errors: List[str],
        generated_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Query parent RAICA model for solutions to verification failures.

        This is called on retry attempts to get intelligent fixes for specific
        issues like "Password hashing not detected" or "Auth middleware not found".

        Args:
            detailed_spec: The project specification
            verification_errors: List of error messages from verification
            generated_files: The generated code files

        Returns:
            Dict with 'success', 'fixes', and optionally 'error'
        """
        from .intelligent_dependency_resolver import IntelligentDependencyResolver

        try:
            resolver = IntelligentDependencyResolver()

            # Get a sample of generated code to provide context
            sample_code = ""
            # generated_files is a List[GeneratedFile], not a dict
            for generated_file in list(generated_files)[:3]:  # First 3 files
                sample_code += f"\n\n=== {generated_file.path} ===\n{generated_file.content[:500]}"  # First 500 chars

            # Query for fixes
            result = await resolver.research_verification_fix(
                tech_stack=detailed_spec.backend_language,
                framework=detailed_spec.backend_framework,
                verification_errors=verification_errors,
                generated_code_sample=sample_code
            )

            return result

        except Exception as e:
            logger.error(f"Failed to research verification fixes: {e}")
            return {
                'success': False,
                'fixes': {},
                'error': str(e)
            }

    def _create_validation_feedback(self, verification: VerificationReport, critical_issues: list, spec: DetailedSpecification) -> str:
        """
        Create detailed feedback from validation errors to guide retry.

        Args:
            verification: The verification report with all issues
            critical_issues: List of critical issue messages
            spec: The detailed specification that was attempted

        Returns:
            Formatted feedback string for the LLM
        """
        feedback_parts = [
            "VALIDATION ERRORS - The following critical issues were found:\n"
        ]

        # Add tech stack reminder if there are code integrity issues
        if verification.code_integrity_issues:
            feedback_parts.append(f"\n⚠️  TECH STACK MISMATCH DETECTED!")
            feedback_parts.append(f"Required tech stack: {spec.tech_stack}")
            feedback_parts.append("Ensure generated code matches the specified technology stack.\n")

        # Add import issues
        if verification.import_issues:
            feedback_parts.append("\n📦 IMPORT ISSUES:")
            for issue in verification.import_issues[:10]:  # Limit to first 10
                if issue.severity == "CRITICAL":
                    feedback_parts.append(f"  - {issue.message}")

        # Add dependency issues
        if verification.dependency_issues:
            feedback_parts.append("\n📋 DEPENDENCY ISSUES:")
            for issue in verification.dependency_issues:
                if issue.severity == "CRITICAL":
                    feedback_parts.append(f"  - {issue.message}")

        # Add code integrity issues
        if verification.code_integrity_issues:
            feedback_parts.append("\n🔍 CODE INTEGRITY ISSUES:")
            for issue in verification.code_integrity_issues:
                if issue.severity == "CRITICAL":
                    feedback_parts.append(f"  - {issue.message}")

        feedback_parts.append("\n💡 INSTRUCTIONS FOR RETRY:")
        feedback_parts.append("  1. Match the EXACT technology stack specified in requirements")
        feedback_parts.append("  2. Ensure all imports are valid and resolvable")
        feedback_parts.append(f"  3. Include {spec.get_tech_config().get_dependency_file_name()} with all dependencies")
        feedback_parts.append("  4. Fix all syntax errors and code integrity issues")

        return "\n".join(feedback_parts)

    def _enrich_analysis_with_feedback(self, analysis: PromptAnalysis, feedback: str) -> PromptAnalysis:
        """
        Enrich the prompt analysis with validation feedback for retry.

        Args:
            analysis: Original prompt analysis
            feedback: Validation feedback to incorporate

        Returns:
            Updated PromptAnalysis with feedback incorporated
        """
        # Add feedback to constraints
        if not hasattr(analysis, 'clarified_inputs'):
            analysis.clarified_inputs = {}

        # Store feedback as a constraint
        analysis.clarified_inputs['validation_feedback'] = feedback

        # Also update the project description to include feedback
        if hasattr(analysis, 'project_description'):
            analysis.project_description += f"\n\nVALIDATION FEEDBACK FROM PREVIOUS ATTEMPT:\n{feedback}"

        return analysis


if __name__ == "__main__":
    # Simple CLI for testing
    import sys
    
    if len(sys.argv) > 1:
        prompt = sys.argv[1]
    else:
        print("Please provide a prompt description.")
        sys.exit(1)
        
    generator = IntelligentCodeGenerator()
    result = generator.generate(prompt)
    
    if result.success:
        print(f"\n✅ Success! Project generated at: {result.project_path}")
    else:
        print(f"\n❌ Failed: {result.message}")
