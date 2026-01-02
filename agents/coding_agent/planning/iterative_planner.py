"""
Iterative Planner Module
========================

Enhanced planner that creates implementation plans with edge case analysis.
Queries RAICA for patterns before planning and identifies potential issues.
"""

import asyncio
import logging
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StepComplexity(Enum):
    """Complexity levels for plan steps."""
    SIMPLE = "simple"      # Can be done in one LLM call
    MEDIUM = "medium"      # Requires 2-3 LLM calls
    COMPLEX = "complex"    # Requires multiple iterations


@dataclass
class PlanStep:
    """A single step in the implementation plan."""
    id: str
    action: str
    description: str
    complexity: StepComplexity = StepComplexity.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    edge_cases: List[str] = field(default_factory=list)
    validation_criteria: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    estimated_files: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'action': self.action,
            'description': self.description,
            'complexity': self.complexity.value,
            'dependencies': self.dependencies,
            'edge_cases': self.edge_cases,
            'validation_criteria': self.validation_criteria,
            'hooks': self.hooks,
            'tests': self.tests,
            'estimated_files': self.estimated_files,
            'notes': self.notes
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlanStep':
        return cls(
            id=data['id'],
            action=data['action'],
            description=data.get('description', ''),
            complexity=StepComplexity(data.get('complexity', 'medium')),
            dependencies=data.get('dependencies', []),
            edge_cases=data.get('edge_cases', []),
            validation_criteria=data.get('validation_criteria', []),
            hooks=data.get('hooks', []),
            tests=data.get('tests', []),
            estimated_files=data.get('estimated_files', []),
            notes=data.get('notes', '')
        )


@dataclass
class ImplementationPlan:
    """Complete implementation plan."""
    steps: List[PlanStep]
    total_complexity: str
    estimated_files: int
    knowledge_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'steps': [s.to_dict() for s in self.steps],
            'total_complexity': self.total_complexity,
            'estimated_files': self.estimated_files,
            'knowledge_sources': self.knowledge_sources,
            'warnings': self.warnings
        }


class IterativePlanner:
    """
    Enhanced planner that creates detailed implementation plans.

    Features:
    - Queries RAICA for relevant patterns and best practices
    - Analyzes edge cases for each step
    - Generates validation criteria
    - Identifies potential pitfalls
    """

    def __init__(
        self,
        llm_client: Any,
        knowledge_client: Optional[Any] = None,
        max_edge_cases_per_step: int = 5
    ):
        """
        Initialize the iterative planner.

        Args:
            llm_client: LLM client for generating plans
            knowledge_client: Optional RAICA knowledge client
            max_edge_cases_per_step: Maximum edge cases to identify per step
        """
        self.llm_client = llm_client
        self.knowledge_client = knowledge_client
        self.max_edge_cases = max_edge_cases_per_step

    async def create_plan(
        self,
        requirements: List[str],
        project_type: str = "python",
        existing_files: Optional[List[str]] = None
    ) -> ImplementationPlan:
        """
        Create a detailed implementation plan.

        Args:
            requirements: List of requirements to implement
            project_type: Type of project (python, javascript, etc.)
            existing_files: Optional list of existing files in project

        Returns:
            ImplementationPlan with detailed steps
        """
        logger.info(f"Creating implementation plan for {len(requirements)} requirements")

        # Step 1: Query knowledge for patterns (if available)
        knowledge_results = []
        if self.knowledge_client:
            try:
                result = await self.knowledge_client.search_patterns(
                    requirements[:5],  # Limit to first 5 requirements
                    language=project_type
                )
                if result.success:
                    knowledge_results = result.results
                    logger.info(f"Found {len(knowledge_results)} relevant patterns")
            except Exception as e:
                logger.warning(f"Knowledge lookup failed: {e}")

        # Step 2: Generate initial plan
        initial_plan = await self._generate_initial_plan(
            requirements,
            project_type,
            knowledge_results,
            existing_files
        )

        # Step 3: Analyze edge cases for each step
        for step in initial_plan:
            step.edge_cases = await self._analyze_edge_cases(
                step,
                requirements,
                project_type
            )

        # Step 4: Generate validation criteria
        for step in initial_plan:
            step.validation_criteria = await self._generate_validation_criteria(
                step,
                project_type
            )

        # Step 5: Calculate total complexity
        total_complexity = self._calculate_complexity(initial_plan)

        # Step 6: Identify warnings
        warnings = self._identify_warnings(initial_plan, requirements)

        return ImplementationPlan(
            steps=initial_plan,
            total_complexity=total_complexity,
            estimated_files=sum(len(s.estimated_files) for s in initial_plan),
            knowledge_sources=[r.source for r in knowledge_results[:3]],
            warnings=warnings
        )

    async def _generate_initial_plan(
        self,
        requirements: List[str],
        project_type: str,
        knowledge_results: List[Any],
        existing_files: Optional[List[str]]
    ) -> List[PlanStep]:
        """Generate the initial implementation plan."""

        # Build context from knowledge results
        knowledge_context = ""
        if knowledge_results:
            knowledge_context = "\n\nRelevant patterns and best practices:\n"
            for result in knowledge_results[:3]:
                knowledge_context += f"- {result.title}: {result.content[:200]}...\n"

        existing_context = ""
        if existing_files:
            existing_context = f"\n\nExisting files in project:\n"
            existing_context += "\n".join(f"- {f}" for f in existing_files[:10])

        prompt = f"""Create a detailed implementation plan for the following requirements.

PROJECT TYPE: {project_type}

REQUIREMENTS:
{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(requirements))}
{knowledge_context}
{existing_context}

For each step, provide:
1. A unique ID (step_1, step_2, etc.)
2. Action (short verb phrase)
3. Description (what this step accomplishes)
4. Complexity (simple, medium, complex)
5. Dependencies (list of step IDs this depends on)
6. Estimated files to create/modify

Output as JSON array:
[
  {{
    "id": "step_1",
    "action": "Create main entry point",
    "description": "Create main.py with application entry point",
    "complexity": "simple",
    "dependencies": [],
    "estimated_files": ["main.py"]
  }},
  ...
]

Focus on:
- Logical order of implementation
- Clear separation of concerns
- Testable units of work
- Proper error handling steps"""

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON from response
            steps_data = self._extract_json_array(content)

            return [PlanStep.from_dict(s) for s in steps_data]

        except Exception as e:
            logger.error(f"Failed to generate initial plan: {e}")
            # Return a basic plan
            return [
                PlanStep(
                    id="step_1",
                    action="Implement requirements",
                    description="Implement all requirements in a single step",
                    complexity=StepComplexity.COMPLEX
                )
            ]

    async def _analyze_edge_cases(
        self,
        step: PlanStep,
        requirements: List[str],
        project_type: str
    ) -> List[str]:
        """Analyze edge cases for a plan step."""

        prompt = f"""Analyze potential edge cases for this implementation step.

STEP: {step.action}
DESCRIPTION: {step.description}
PROJECT TYPE: {project_type}

Consider:
1. Input validation edge cases (empty, null, invalid types)
2. Boundary conditions (min/max values, empty collections)
3. Error handling scenarios (network failures, file errors)
4. Race conditions (if applicable)
5. Resource constraints (memory, timeouts)

Output as JSON array of strings (max {self.max_edge_cases}):
["edge case 1", "edge case 2", ...]"""

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            edge_cases = self._extract_json_array(content)

            if isinstance(edge_cases, list) and all(isinstance(e, str) for e in edge_cases):
                return edge_cases[:self.max_edge_cases]

            return []

        except Exception as e:
            logger.warning(f"Failed to analyze edge cases: {e}")
            return []

    async def _generate_validation_criteria(
        self,
        step: PlanStep,
        project_type: str
    ) -> List[str]:
        """Generate validation criteria for a step."""

        prompt = f"""Generate validation criteria for this implementation step.

STEP: {step.action}
DESCRIPTION: {step.description}
EDGE CASES: {', '.join(step.edge_cases[:3]) if step.edge_cases else 'None identified'}
PROJECT TYPE: {project_type}

What criteria must be met to consider this step successfully implemented?

Output as JSON array of strings:
["Files compile without errors", "All imports resolve correctly", ...]"""

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            criteria = self._extract_json_array(content)

            if isinstance(criteria, list) and all(isinstance(c, str) for c in criteria):
                return criteria[:5]

            return []

        except Exception as e:
            logger.warning(f"Failed to generate validation criteria: {e}")
            return []

    def _calculate_complexity(self, steps: List[PlanStep]) -> str:
        """Calculate overall plan complexity."""
        if not steps:
            return "unknown"

        complexity_scores = {
            StepComplexity.SIMPLE: 1,
            StepComplexity.MEDIUM: 2,
            StepComplexity.COMPLEX: 3
        }

        avg_score = sum(complexity_scores[s.complexity] for s in steps) / len(steps)

        if avg_score < 1.5:
            return "low"
        elif avg_score < 2.5:
            return "medium"
        else:
            return "high"

    def _identify_warnings(
        self,
        steps: List[PlanStep],
        requirements: List[str]
    ) -> List[str]:
        """Identify potential warnings about the plan."""
        warnings = []

        # Check for complex steps without dependencies
        for step in steps:
            if step.complexity == StepComplexity.COMPLEX and not step.dependencies:
                if step.id != "step_1":
                    warnings.append(
                        f"Complex step '{step.action}' has no dependencies - verify order"
                    )

        # Check for many edge cases
        high_edge_case_steps = [s for s in steps if len(s.edge_cases) >= 4]
        if high_edge_case_steps:
            warnings.append(
                f"{len(high_edge_case_steps)} step(s) have many edge cases - extra testing recommended"
            )

        # Check if requirements are covered
        if len(steps) < len(requirements) / 2:
            warnings.append(
                "Plan has fewer steps than requirements - verify all requirements are addressed"
            )

        return warnings

    def _extract_json_array(self, content: str) -> List[Any]:
        """Extract JSON array from LLM response."""
        # Try to find JSON array in content
        try:
            # Look for array pattern
            match = re.search(r'\[[\s\S]*\]', content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Try parsing entire content
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        return []

    def get_execution_order(self, plan: ImplementationPlan) -> List[PlanStep]:
        """
        Get steps in execution order (respecting dependencies).

        Args:
            plan: Implementation plan

        Returns:
            Steps sorted by dependency order
        """
        ordered = []
        remaining = plan.steps.copy()
        completed_ids = set()

        while remaining:
            # Find steps with all dependencies satisfied
            ready = [
                s for s in remaining
                if all(dep in completed_ids for dep in s.dependencies)
            ]

            if not ready:
                # No ready steps - break cycle by taking first remaining
                ready = [remaining[0]]
                logger.warning(f"Breaking dependency cycle at step: {ready[0].id}")

            # Add ready steps to ordered list
            for step in ready:
                ordered.append(step)
                completed_ids.add(step.id)
                remaining.remove(step)

        return ordered
