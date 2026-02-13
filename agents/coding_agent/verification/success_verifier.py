"""
Success Verifier Module
=======================

Verifies that implementation meets 90%+ of requirements.
Uses a dedicated verification LLM (glm-4.7:cloud) for independent assessment.
"""

import asyncio
import logging
import json
import re
from typing import List, Dict, Any, Optional
from ..config_accessor import get_success_threshold
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RequirementStatus(Enum):
    """Status of a requirement implementation."""
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass
class RequirementAssessment:
    """Assessment of a single requirement."""
    requirement: str
    status: RequirementStatus
    evidence: str
    issues: List[str] = field(default_factory=list)
    score: float = 0.0  # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'requirement': self.requirement,
            'status': self.status.value,
            'evidence': self.evidence,
            'issues': self.issues,
            'score': self.score
        }


@dataclass
class TestResult:
    """Result from test execution."""
    passed: int
    failed: int
    errors: int
    skipped: int
    output: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100


@dataclass
class VerificationResult:
    """Complete verification result."""
    success: bool
    percentage: float
    requirements_status: List[RequirementAssessment]
    blocking_issues: List[str]
    recommendation: str  # PASS, ITERATE, FAIL
    reasoning: str
    test_results: Optional[TestResult] = None
    verification_model: str = "glm-4.7:cloud"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'percentage': self.percentage,
            'requirements_status': [r.to_dict() for r in self.requirements_status],
            'blocking_issues': self.blocking_issues,
            'recommendation': self.recommendation,
            'reasoning': self.reasoning,
            'test_results': {
                'passed': self.test_results.passed,
                'failed': self.test_results.failed,
                'errors': self.test_results.errors,
                'success_rate': self.test_results.success_rate
            } if self.test_results else None,
            'verification_model': self.verification_model
        }


class SuccessVerifier:
    """
    Verifies implementation success with 90%+ threshold.

    Features:
    - Independent verification using dedicated LLM (glm-4.7:cloud)
    - Requirement-by-requirement assessment
    - Test result integration
    - Blocking issue identification
    """

    VERIFICATION_MODEL = "glm-4.7:cloud"
    VERIFICATION_PROVIDER = "ollama"

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        success_threshold: Optional[float] = None,
        max_verification_iterations: int = 3
    ):
        """
        Initialize the success verifier.

        Args:
            llm_client: Optional pre-configured LLM client
            success_threshold: Minimum success percentage (default 90%)
            max_verification_iterations: Maximum verification attempts
        """
        self.llm_client = llm_client
        self.threshold = success_threshold if success_threshold is not None else get_success_threshold()
        self.max_iterations = max_verification_iterations
        self._verification_client = None

    async def _get_verification_client(self):
        """Get or create the verification LLM client."""
        if self._verification_client:
            return self._verification_client

        if self.llm_client:
            # Try to create a new client with verification model
            try:
                # Assuming CodeGenLLMClient pattern from the existing codebase
                from ..llm_client import CodeGenLLMClient
                self._verification_client = CodeGenLLMClient(
                    provider_override=self.VERIFICATION_PROVIDER,
                    model_override=self.VERIFICATION_MODEL
                )
            except Exception as e:
                logger.warning(f"Failed to create verification client: {e}")
                self._verification_client = self.llm_client

        return self._verification_client or self.llm_client

    async def verify_success(
        self,
        requirements: List[str],
        generated_files: Dict[str, str],
        test_results: Optional[TestResult] = None,
        project_type: str = "python"
    ) -> VerificationResult:
        """
        Verify that implementation meets success threshold.

        Args:
            requirements: List of requirements
            generated_files: Dict of filepath -> content
            test_results: Optional test execution results
            project_type: Programming language

        Returns:
            VerificationResult with detailed assessment
        """
        logger.info(f"Verifying implementation against {len(requirements)} requirements")
        logger.info(f"Using verification model: {self.VERIFICATION_MODEL}")

        client = await self._get_verification_client()

        if not client:
            return self._error_result("No LLM client available for verification")

        # Build file summary
        file_summary = self._build_file_summary(generated_files)

        # Build test summary
        test_summary = ""
        if test_results:
            test_summary = f"""
TEST RESULTS:
- Passed: {test_results.passed}
- Failed: {test_results.failed}
- Errors: {test_results.errors}
- Success Rate: {test_results.success_rate:.1f}%
"""
            if test_results.output:
                test_summary += f"- Output (excerpt): {test_results.output[:500]}...\n"

        prompt = f"""You are an independent QA engineer verifying code implementation.
Your job is to be STRICT and OBJECTIVE in assessing whether requirements are met.

PROJECT TYPE: {project_type}
SUCCESS THRESHOLD: {self.threshold}%

REQUIREMENTS TO VERIFY:
{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(requirements))}

GENERATED FILES:
{file_summary}
{test_summary}

VERIFICATION TASK:
For EACH requirement, determine its implementation status:
- COMPLETE (1.0): Fully implemented and tested, handles edge cases
- PARTIAL (0.5): Partially implemented, missing some aspects
- MISSING (0.0): Not implemented or placeholder only

Calculate overall percentage as: (sum of scores / total requirements) * 100

Output as JSON:
{{
    "requirements_status": [
        {{
            "requirement": "Requirement text",
            "status": "complete|partial|missing",
            "evidence": "Specific code/file that implements this",
            "issues": ["Any issues found"],
            "score": 1.0
        }}
    ],
    "overall_percentage": 85.5,
    "blocking_issues": ["Critical issues that prevent deployment"],
    "recommendation": "PASS|ITERATE|FAIL",
    "reasoning": "Explanation of assessment"
}}

GUIDELINES:
- PASS: >= {self.threshold}% complete AND no blocking issues
- ITERATE: < {self.threshold}% but fixable with more work
- FAIL: Fundamental issues that require major rework
- Be specific about evidence and issues
- Do not inflate scores - be accurate"""

        try:
            response = await client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            data = self._extract_json(content)

            if not data:
                return self._error_result("Failed to parse verification response")

            # Parse requirement assessments
            assessments = []
            for item in data.get('requirements_status', []):
                try:
                    status = RequirementStatus(item.get('status', 'unknown'))
                except ValueError:
                    status = RequirementStatus.UNKNOWN

                assessments.append(RequirementAssessment(
                    requirement=item.get('requirement', ''),
                    status=status,
                    evidence=item.get('evidence', ''),
                    issues=item.get('issues', []),
                    score=float(item.get('score', 0))
                ))

            percentage = float(data.get('overall_percentage', 0))
            recommendation = data.get('recommendation', 'ITERATE').upper()
            blocking_issues = data.get('blocking_issues', [])

            # Determine success
            success = (
                percentage >= self.threshold and
                recommendation == 'PASS' and
                len(blocking_issues) == 0
            )

            return VerificationResult(
                success=success,
                percentage=percentage,
                requirements_status=assessments,
                blocking_issues=blocking_issues,
                recommendation=recommendation,
                reasoning=data.get('reasoning', ''),
                test_results=test_results,
                verification_model=self.VERIFICATION_MODEL
            )

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return self._error_result(str(e))

    async def verify_with_retry(
        self,
        requirements: List[str],
        generated_files: Dict[str, str],
        test_results: Optional[TestResult] = None,
        on_feedback: Optional[callable] = None
    ) -> VerificationResult:
        """
        Verify with retry loop until success or max iterations.

        Args:
            requirements: Requirements to verify
            generated_files: Generated code files
            test_results: Test results
            on_feedback: Callback for providing feedback between iterations

        Returns:
            Final VerificationResult
        """
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"Verification iteration {iteration}/{self.max_iterations}")

            result = await self.verify_success(
                requirements,
                generated_files,
                test_results
            )

            if result.success:
                logger.info(f"Verification passed: {result.percentage}%")
                return result

            if iteration < self.max_iterations:
                logger.warning(
                    f"Verification failed ({result.percentage}%), "
                    f"issues: {len(result.blocking_issues)}"
                )

                # Provide feedback if callback is set
                if on_feedback:
                    feedback = self._format_feedback(result)
                    await on_feedback(feedback, result)

        return result

    def _build_file_summary(self, files: Dict[str, str]) -> str:
        """Build a summary of generated files for verification."""
        summary_parts = []

        for filepath, content in files.items():
            lines = content.split('\n')
            line_count = len(lines)

            # Extract key structures
            classes = re.findall(r'class\s+(\w+)', content)
            functions = re.findall(r'def\s+(\w+)', content)

            # Get imports
            imports = re.findall(r'^(?:from|import)\s+[\w.]+', content, re.MULTILINE)

            summary = f"""
=== {filepath} ({line_count} lines) ===
Imports: {len(imports)}
Classes: {', '.join(classes[:5]) if classes else 'None'}
Functions: {', '.join(functions[:10]) if functions else 'None'}

Content preview:
{chr(10).join(lines[:30])}
{'...(truncated)' if len(lines) > 30 else ''}
"""
            summary_parts.append(summary)

        return '\n'.join(summary_parts)

    def _extract_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from response content using robust utility."""
        from ..utils.json_utils import extract_json_from_llm_response
        return extract_json_from_llm_response(content)

    def _error_result(self, error: str) -> VerificationResult:
        """Create an error result."""
        return VerificationResult(
            success=False,
            percentage=0,
            requirements_status=[],
            blocking_issues=[f"Verification error: {error}"],
            recommendation="FAIL",
            reasoning=error
        )

    def _format_feedback(self, result: VerificationResult) -> str:
        """Format verification result as feedback for fixing."""
        feedback_parts = [
            f"VERIFICATION RESULT: {result.recommendation}",
            f"Completeness: {result.percentage}%",
            f"Threshold: {self.threshold}%",
            "",
            "BLOCKING ISSUES:"
        ]

        for issue in result.blocking_issues:
            feedback_parts.append(f"  - {issue}")

        feedback_parts.append("\nREQUIREMENTS ASSESSMENT:")

        for req in result.requirements_status:
            if req.status != RequirementStatus.COMPLETE:
                feedback_parts.append(f"  [{req.status.value.upper()}] {req.requirement[:50]}...")
                if req.issues:
                    for issue in req.issues[:2]:
                        feedback_parts.append(f"    Issue: {issue}")

        feedback_parts.append(f"\nREASONING: {result.reasoning}")

        return '\n'.join(feedback_parts)

    def get_improvement_priorities(
        self,
        result: VerificationResult
    ) -> List[Dict[str, Any]]:
        """
        Get prioritized list of improvements needed.

        Args:
            result: Verification result

        Returns:
            List of improvement items sorted by priority
        """
        improvements = []

        # Add blocking issues as highest priority
        for issue in result.blocking_issues:
            improvements.append({
                'priority': 1,
                'type': 'blocking',
                'description': issue,
                'action': 'fix_immediately'
            })

        # Add missing requirements
        for req in result.requirements_status:
            if req.status == RequirementStatus.MISSING:
                improvements.append({
                    'priority': 2,
                    'type': 'missing',
                    'description': req.requirement,
                    'action': 'implement'
                })

        # Add partial requirements
        for req in result.requirements_status:
            if req.status == RequirementStatus.PARTIAL:
                improvements.append({
                    'priority': 3,
                    'type': 'partial',
                    'description': req.requirement,
                    'issues': req.issues,
                    'action': 'complete'
                })

        return sorted(improvements, key=lambda x: x['priority'])
