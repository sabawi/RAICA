"""
Refinement Loop Module
======================

Implements the "What's missing?" loop for continuous improvement.
Identifies missing functionality and adds as subtasks.
"""

import asyncio
import logging
import json
import re
from typing import List, Dict, Any, Optional
from ..config_accessor import get_success_threshold
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MissingItem:
    """A missing item identified during refinement."""
    description: str
    priority: str  # critical, high, medium, low
    category: str  # functionality, error_handling, validation, testing, documentation
    estimated_effort: str  # small, medium, large
    suggested_fix: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'priority': self.priority,
            'category': self.category,
            'estimated_effort': self.estimated_effort,
            'suggested_fix': self.suggested_fix
        }


@dataclass
class RefinementResult:
    """Result of a refinement iteration."""
    iteration: int
    completeness_percentage: float
    missing_items: List[MissingItem]
    critical_missing: List[str]
    recommendation: str  # continue, complete, fail
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'iteration': self.iteration,
            'completeness_percentage': self.completeness_percentage,
            'missing_items': [m.to_dict() for m in self.missing_items],
            'critical_missing': self.critical_missing,
            'recommendation': self.recommendation,
            'reasoning': self.reasoning
        }


class RefinementLoop:
    """
    Iteratively asks "What's missing?" and identifies gaps.

    Features:
    - Analyzes generated code against requirements
    - Identifies missing functionality
    - Suggests fixes for each gap
    - Tracks completeness percentage
    """


    def __init__(
        self,
        llm_client: Any,
        max_iterations: int = 3,
        completeness_threshold: Optional[float] = None
    ):
        """
        Initialize the refinement loop.

        Args:
            llm_client: LLM client for analysis
            max_iterations: Maximum refinement iterations
            completeness_threshold: Target completeness percentage
        """
        self.llm_client = llm_client
        self.max_iterations = max_iterations
        self.threshold = completeness_threshold if completeness_threshold is not None else get_success_threshold()

    async def run(
        self,
        requirements: List[str],
        generated_files: Dict[str, str],
        project_type: str = "python"
    ) -> List[RefinementResult]:
        """
        Run the refinement loop.

        Args:
            requirements: Original requirements
            generated_files: Dict of filepath -> content
            project_type: Programming language/type

        Returns:
            List of RefinementResult for each iteration
        """
        results = []
        current_files = generated_files.copy()

        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"Refinement iteration {iteration}/{self.max_iterations}")

            result = await self._analyze_completeness(
                iteration,
                requirements,
                current_files,
                project_type
            )

            results.append(result)

            # Check if we've reached the threshold
            if result.completeness_percentage >= self.threshold:
                logger.info(f"Completeness threshold reached: {result.completeness_percentage}%")
                break

            # Check if there's nothing critical missing
            if not result.critical_missing and not result.missing_items:
                logger.info("No more missing items identified")
                break

            # Log what's missing
            if result.missing_items:
                logger.info(f"Found {len(result.missing_items)} missing items")
                for item in result.missing_items[:3]:
                    logger.debug(f"  - [{item.priority}] {item.description}")

        return results

    async def _analyze_completeness(
        self,
        iteration: int,
        requirements: List[str],
        generated_files: Dict[str, str],
        project_type: str
    ) -> RefinementResult:
        """Analyze completeness of implementation."""

        # Build file summary
        file_summary = self._build_file_summary(generated_files)

        prompt = f"""You are a QA engineer reviewing code implementation for completeness.

PROJECT TYPE: {project_type}

REQUIREMENTS:
{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(requirements))}

GENERATED FILES:
{file_summary}

TASK:
1. For each requirement, determine if it's fully implemented, partially implemented, or missing
2. Identify any missing functionality that is REQUIRED by the requirements
3. Do NOT identify nice-to-haves or improvements, only MISSING required functionality
4. Estimate overall completeness percentage

Output as JSON:
{{
    "completeness_percentage": 85,
    "missing_items": [
        {{
            "description": "What is missing",
            "priority": "critical|high|medium|low",
            "category": "functionality|error_handling|validation|testing|documentation",
            "estimated_effort": "small|medium|large",
            "suggested_fix": "Brief suggestion on how to fix"
        }}
    ],
    "critical_missing": ["List of critical missing items that block deployment"],
    "recommendation": "continue|complete|fail",
    "reasoning": "Brief explanation of the assessment"
}}

Rules:
- Be strict about requirements coverage
- Only mark as complete if ALL aspects of a requirement are implemented
- Critical missing items are those that prevent the application from functioning
- Recommendation 'complete' if >= 90% complete and no critical items
- Recommendation 'continue' if < 90% but fixable
- Recommendation 'fail' if fundamental issues exist"""

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            data = self._extract_json(content)

            if not data:
                return self._default_result(iteration)

            # Parse missing items
            missing_items = []
            for item_data in data.get('missing_items', []):
                try:
                    missing_items.append(MissingItem(
                        description=item_data.get('description', ''),
                        priority=item_data.get('priority', 'medium'),
                        category=item_data.get('category', 'functionality'),
                        estimated_effort=item_data.get('estimated_effort', 'medium'),
                        suggested_fix=item_data.get('suggested_fix')
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse missing item: {e}")

            return RefinementResult(
                iteration=iteration,
                completeness_percentage=float(data.get('completeness_percentage', 0)),
                missing_items=missing_items,
                critical_missing=data.get('critical_missing', []),
                recommendation=data.get('recommendation', 'continue'),
                reasoning=data.get('reasoning', '')
            )

        except Exception as e:
            logger.error(f"Failed to analyze completeness: {e}")
            return self._default_result(iteration)

    def _build_file_summary(self, files: Dict[str, str]) -> str:
        """Build a summary of generated files."""
        summary_parts = []

        for filepath, content in files.items():
            # Extract key information from file
            lines = content.split('\n')
            line_count = len(lines)

            # Get first docstring or comment if present
            first_lines = '\n'.join(lines[:10])

            # Try to extract classes and functions
            classes = re.findall(r'class\s+(\w+)', content)
            functions = re.findall(r'def\s+(\w+)', content)

            summary = f"""
FILE: {filepath} ({line_count} lines)
Classes: {', '.join(classes[:5]) if classes else 'None'}
Functions: {', '.join(functions[:10]) if functions else 'None'}
Preview:
{first_lines[:500]}
---"""
            summary_parts.append(summary)

        return '\n'.join(summary_parts)

    def _extract_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response."""
        # Try to find JSON object in content
        try:
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Try parsing entire content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        return None

    def _default_result(self, iteration: int) -> RefinementResult:
        """Return a default result when analysis fails."""
        return RefinementResult(
            iteration=iteration,
            completeness_percentage=0,
            missing_items=[],
            critical_missing=["Unable to analyze completeness"],
            recommendation="continue",
            reasoning="Analysis failed - manual review recommended"
        )

    def get_implementation_tasks(
        self,
        result: RefinementResult
    ) -> List[Dict[str, Any]]:
        """
        Convert missing items to implementation tasks.

        Args:
            result: RefinementResult to convert

        Returns:
            List of task dicts suitable for implementation
        """
        tasks = []

        # Add critical items first
        for critical in result.critical_missing:
            tasks.append({
                'description': critical,
                'priority': 'critical',
                'type': 'implementation'
            })

        # Add other missing items by priority
        priority_order = ['critical', 'high', 'medium', 'low']

        for priority in priority_order:
            for item in result.missing_items:
                if item.priority == priority:
                    tasks.append({
                        'description': item.description,
                        'priority': item.priority,
                        'category': item.category,
                        'effort': item.estimated_effort,
                        'fix': item.suggested_fix,
                        'type': 'subtask'
                    })

        return tasks

    async def suggest_fixes(
        self,
        missing_item: MissingItem,
        current_files: Dict[str, str],
        project_type: str
    ) -> Optional[str]:
        """
        Get detailed fix suggestion for a missing item.

        Args:
            missing_item: The item to fix
            current_files: Current generated files
            project_type: Programming language

        Returns:
            Detailed fix suggestion or None
        """
        # Find relevant files
        relevant_files = self._find_relevant_files(
            missing_item.description,
            current_files
        )

        file_context = ""
        if relevant_files:
            file_context = "\n\nRelevant existing code:\n"
            for filepath, content in relevant_files.items():
                file_context += f"\n=== {filepath} ===\n{content[:1000]}...\n"

        prompt = f"""Provide a detailed fix for this missing functionality.

MISSING: {missing_item.description}
CATEGORY: {missing_item.category}
PROJECT TYPE: {project_type}
{file_context}

Provide:
1. What file(s) need to be modified or created
2. Specific code changes needed
3. Any imports or dependencies required

Be concise but specific."""

        try:
            response = await self.llm_client.generate(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Failed to suggest fix: {e}")
            return None

    def _find_relevant_files(
        self,
        description: str,
        files: Dict[str, str]
    ) -> Dict[str, str]:
        """Find files relevant to a missing item description."""
        relevant = {}

        # Extract keywords from description
        keywords = set(re.findall(r'\b\w{4,}\b', description.lower()))

        for filepath, content in files.items():
            content_lower = content.lower()

            # Check if any keyword appears in the file
            matches = sum(1 for kw in keywords if kw in content_lower)

            if matches >= 2:  # At least 2 keyword matches
                relevant[filepath] = content

        # Limit to top 3 most relevant
        return dict(list(relevant.items())[:3])
