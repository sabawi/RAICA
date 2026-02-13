"""
Debug Decomposer
================

Breaks complex bugs into testable units for incremental fix-verify cycles.

This addresses the critical gap where multi-file, multi-step bugs were
treated as a single monolithic fix, leading to:
- Difficulty isolating root causes
- Single tests that can't cover all failure modes
- No verification between intermediate fix steps

The decomposer separates bugs into:
1. FUNCTIONAL units - Can be tested automatically (logic, API, state)
2. VISUAL units - Require human verification (appearance, layout)
"""

import asyncio
import logging
import re
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..utils.json_utils import sanitize_json

logger = logging.getLogger(__name__)


class UnitType(Enum):
    """Type of debug unit."""
    FUNCTIONAL = "functional"  # Can be tested automatically
    VISUAL = "visual"          # Requires human verification
    INTEGRATION = "integration"  # Tests multiple components together


class UnitPriority(Enum):
    """Priority for fixing units."""
    CRITICAL = 1    # Blocks other units
    HIGH = 2        # Core functionality
    MEDIUM = 3      # Important but not blocking
    LOW = 4         # Nice to have / cosmetic


@dataclass
class DebugUnit:
    """A single testable unit extracted from a complex bug."""
    unit_id: str                          # Unique ID (e.g., "unit_1_validation")
    description: str                      # What this unit tests/fixes
    affected_files: List[str]             # Files involved in this unit
    unit_type: UnitType = UnitType.FUNCTIONAL
    priority: UnitPriority = UnitPriority.MEDIUM

    # Test information
    test_approach: str = ""               # How to test this unit
    test_assertions: List[str] = field(default_factory=list)  # Specific assertions

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # Other unit IDs

    # State tracking
    test_generated: bool = False
    test_path: Optional[str] = None
    fix_applied: bool = False
    fix_verified: bool = False

    # Results
    error_details: Optional[str] = None   # Specific error for this unit
    fix_description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'unit_id': self.unit_id,
            'description': self.description,
            'affected_files': self.affected_files,
            'unit_type': self.unit_type.value,
            'priority': self.priority.value,
            'test_approach': self.test_approach,
            'test_assertions': self.test_assertions,
            'depends_on': self.depends_on,
            'test_generated': self.test_generated,
            'fix_applied': self.fix_applied,
            'fix_verified': self.fix_verified
        }


@dataclass
class DecompositionResult:
    """Result of decomposing a bug into units."""
    bug_description: str
    units: List[DebugUnit] = field(default_factory=list)
    functional_units: List[DebugUnit] = field(default_factory=list)
    visual_units: List[DebugUnit] = field(default_factory=list)

    # Metadata
    total_files_affected: int = 0
    estimated_complexity: str = "medium"  # simple, medium, complex
    decomposition_confidence: float = 0.8

    def get_ordered_units(self) -> List[DebugUnit]:
        """Get units in execution order (respecting dependencies and priority)."""
        # Sort by priority first, then handle dependencies
        sorted_units = sorted(self.functional_units, key=lambda u: u.priority.value)

        # Topological sort for dependencies
        result = []
        visited = set()

        def visit(unit: DebugUnit):
            if unit.unit_id in visited:
                return
            visited.add(unit.unit_id)
            for dep_id in unit.depends_on:
                dep_unit = next((u for u in sorted_units if u.unit_id == dep_id), None)
                if dep_unit:
                    visit(dep_unit)
            result.append(unit)

        for unit in sorted_units:
            visit(unit)

        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            'bug_description': self.bug_description,
            'units': [u.to_dict() for u in self.units],
            'total_files_affected': self.total_files_affected,
            'estimated_complexity': self.estimated_complexity,
            'decomposition_confidence': self.decomposition_confidence
        }


class DebugDecomposer:
    """
    Breaks complex bugs into testable units.

    Key Principles:
    1. Separate FUNCTIONAL (testable) from VISUAL (human-verified)
    2. Create independent units that can be fixed/verified incrementally
    3. Identify dependencies between units
    4. Prioritize units by impact and blocking relationships
    """

    def __init__(self, llm_client, project_dir: Path):
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)

    async def decompose_bug(
        self,
        bug_description: str,
        error_trace: Optional[str],
        affected_files: List[str],
        file_contents: Optional[Dict[str, str]] = None
    ) -> DecompositionResult:
        """
        Decompose a bug into testable units.

        Args:
            bug_description: User's description of the bug
            error_trace: Stack trace if available
            affected_files: Files identified as affected
            file_contents: Optional dict of {filepath: content}

        Returns:
            DecompositionResult with ordered testable units
        """
        logger.info(f"Decomposing bug into testable units: {bug_description[:50]}...")

        # Read file contents if not provided
        if file_contents is None:
            file_contents = {}
            for f in affected_files[:5]:
                try:
                    full_path = self.project_dir / f
                    if full_path.exists():
                        file_contents[f] = full_path.read_text(encoding='utf-8', errors='replace')
                except Exception as e:
                    logger.warning(f"Could not read {f}: {e}")

        # Use LLM to decompose
        decomposition = await self._llm_decompose(
            bug_description, error_trace, affected_files, file_contents
        )

        # If LLM fails, fall back to heuristic decomposition
        if not decomposition.units:
            decomposition = self._heuristic_decompose(
                bug_description, error_trace, affected_files, file_contents
            )

        # Separate functional from visual units
        decomposition.functional_units = [
            u for u in decomposition.units if u.unit_type == UnitType.FUNCTIONAL
        ]
        decomposition.visual_units = [
            u for u in decomposition.units if u.unit_type == UnitType.VISUAL
        ]

        decomposition.total_files_affected = len(set(
            f for u in decomposition.units for f in u.affected_files
        ))

        # Estimate complexity
        if len(decomposition.units) <= 2:
            decomposition.estimated_complexity = "simple"
        elif len(decomposition.units) <= 5:
            decomposition.estimated_complexity = "medium"
        else:
            decomposition.estimated_complexity = "complex"

        logger.info(f"Decomposed into {len(decomposition.functional_units)} functional + "
                   f"{len(decomposition.visual_units)} visual units")

        return decomposition

    async def _llm_decompose(
        self,
        bug_description: str,
        error_trace: Optional[str],
        affected_files: List[str],
        file_contents: Dict[str, str]
    ) -> DecompositionResult:
        """Use LLM to intelligently decompose the bug."""

        # Format file contents for prompt
        files_context = ""
        for path, content in list(file_contents.items())[:5]:
            truncated = content[:2000] if len(content) > 2000 else content
            files_context += f"\n--- {path} ---\n{truncated}\n"

        prompt = f"""Analyze this bug and decompose it into TESTABLE UNITS.

BUG DESCRIPTION:
{bug_description}

ERROR TRACE:
{error_trace or 'Not provided'}

AFFECTED FILES:
{', '.join(affected_files)}

FILE CONTENTS:
{files_context}

TASK: Break this bug into independent, testable units.

CRITICAL DISTINCTION:
1. FUNCTIONAL units - Logic, data flow, API calls, state management, event handling
   → Can be tested with automated tests (pytest, jest, etc.)
   → Example: "Form validation rejects valid email" → Test validation function

2. VISUAL units - Colors, fonts, layout, spacing, animations, appearance
   → Require HUMAN verification (cannot be reliably automated)
   → Example: "Button color is wrong" → User must visually confirm

For each unit, provide:
- A unique ID (e.g., "unit_1_validation")
- Type: "functional" or "visual"
- Priority: 1=critical (blocks others), 2=high, 3=medium, 4=low
- Which specific file(s) need changes
- How to TEST this unit (specific assertions for functional units)
- Dependencies (if unit_2 depends on unit_1 being fixed first)

OUTPUT FORMAT (JSON only, no other text):
{{
    "units": [
        {{
            "unit_id": "unit_1_example",
            "description": "Brief description of what this unit covers",
            "unit_type": "functional",
            "priority": 2,
            "affected_files": ["file1.py"],
            "test_approach": "How to test this specific unit",
            "test_assertions": ["assert result == expected", "assert no_error_raised"],
            "depends_on": [],
            "error_details": "Specific error message or behavior for this unit"
        }}
    ],
    "confidence": 0.85
}}

GUIDELINES:
1. Create 1-5 units (don't over-decompose simple bugs)
2. Each unit should be independently testable
3. Put critical/blocking units as priority 1
4. For GUI/web apps, most logic bugs are FUNCTIONAL even if they affect appearance
5. Only mark something VISUAL if it ONLY affects appearance with no testable logic
"""

        try:
            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=3000
            )

            if not response.success:
                logger.warning(f"LLM decomposition failed: {response.error}")
                return DecompositionResult(bug_description=bug_description)

            content = response.content.strip()

            # Extract JSON with sanitization
            json_match = re.search(r'\{[\s\S]*\}', content)
            if not json_match:
                logger.warning("Could not extract JSON from LLM response")
                return DecompositionResult(bug_description=bug_description)

            sanitized = sanitize_json(json_match.group())
            data = json.loads(sanitized)

            units = []
            for u in data.get('units', []):
                unit_type = UnitType.VISUAL if u.get('unit_type') == 'visual' else UnitType.FUNCTIONAL
                priority_val = u.get('priority', 3)
                priority = UnitPriority(min(max(priority_val, 1), 4))

                units.append(DebugUnit(
                    unit_id=u.get('unit_id', f"unit_{len(units)+1}"),
                    description=u.get('description', ''),
                    affected_files=u.get('affected_files', []),
                    unit_type=unit_type,
                    priority=priority,
                    test_approach=u.get('test_approach', ''),
                    test_assertions=u.get('test_assertions', []),
                    depends_on=u.get('depends_on', []),
                    error_details=u.get('error_details', '')
                ))

            return DecompositionResult(
                bug_description=bug_description,
                units=units,
                decomposition_confidence=data.get('confidence', 0.7)
            )

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error in decomposition: {e}")
            return DecompositionResult(bug_description=bug_description)
        except Exception as e:
            logger.error(f"LLM decomposition error: {e}")
            return DecompositionResult(bug_description=bug_description)

    def _heuristic_decompose(
        self,
        bug_description: str,
        error_trace: Optional[str],
        affected_files: List[str],
        file_contents: Dict[str, str]
    ) -> DecompositionResult:
        """
        Fallback heuristic decomposition when LLM fails.

        Uses pattern matching and file analysis to create basic units.
        """
        units = []
        bug_lower = bug_description.lower()

        # Detect common bug patterns
        patterns = {
            'validation': ['validation', 'validate', 'invalid', 'required', 'format'],
            'api': ['api', 'endpoint', 'request', 'response', '500', '404', 'fetch'],
            'database': ['database', 'db', 'query', 'sql', 'save', 'insert', 'update'],
            'state': ['state', 'store', 'redux', 'context', 'useState'],
            'event': ['click', 'submit', 'event', 'handler', 'listener', 'onChange'],
            'display': ['display', 'show', 'render', 'visible', 'hidden'],
            'style': ['color', 'style', 'css', 'font', 'size', 'layout', 'position'],
        }

        detected_patterns = []
        for pattern_name, keywords in patterns.items():
            if any(kw in bug_lower for kw in keywords):
                detected_patterns.append(pattern_name)

        # Create units based on detected patterns
        for i, pattern in enumerate(detected_patterns[:5]):  # Max 5 units
            is_visual = pattern in ['style']

            # Find relevant files for this pattern
            relevant_files = []
            for f in affected_files:
                f_lower = f.lower()
                if pattern in f_lower:
                    relevant_files.append(f)
                elif pattern == 'api' and any(x in f_lower for x in ['api', 'route', 'endpoint', 'handler']):
                    relevant_files.append(f)
                elif pattern == 'database' and any(x in f_lower for x in ['model', 'db', 'repository', 'dao']):
                    relevant_files.append(f)

            if not relevant_files:
                relevant_files = affected_files[:1]  # Default to first file

            units.append(DebugUnit(
                unit_id=f"unit_{i+1}_{pattern}",
                description=f"{pattern.title()} related issue",
                affected_files=relevant_files,
                unit_type=UnitType.VISUAL if is_visual else UnitType.FUNCTIONAL,
                priority=UnitPriority.HIGH if i == 0 else UnitPriority.MEDIUM,
                test_approach=f"Test {pattern} functionality",
                test_assertions=[f"Verify {pattern} works correctly"]
            ))

        # If no patterns detected, create a single generic unit
        if not units:
            units.append(DebugUnit(
                unit_id="unit_1_main",
                description=bug_description[:100],
                affected_files=affected_files[:3],
                unit_type=UnitType.FUNCTIONAL,
                priority=UnitPriority.HIGH,
                test_approach="Test the reported functionality",
                test_assertions=["Verify bug is fixed"]
            ))

        return DecompositionResult(
            bug_description=bug_description,
            units=units,
            decomposition_confidence=0.5  # Lower confidence for heuristic
        )

    def is_simple_bug(self, decomposition: DecompositionResult) -> bool:
        """
        Determine if this is a simple bug that doesn't need decomposition.

        Returns True if:
        - Only 1 functional unit
        - Only 1 file affected
        - High decomposition confidence
        """
        return (
            len(decomposition.functional_units) <= 1 and
            decomposition.total_files_affected <= 1 and
            decomposition.decomposition_confidence >= 0.8
        )

    def format_units_for_display(self, decomposition: DecompositionResult) -> str:
        """Format units for user-friendly display."""
        lines = [
            f"Bug Decomposition: {len(decomposition.functional_units)} functional, "
            f"{len(decomposition.visual_units)} visual units",
            f"Complexity: {decomposition.estimated_complexity}",
            ""
        ]

        if decomposition.functional_units:
            lines.append("FUNCTIONAL UNITS (will be tested automatically):")
            for u in decomposition.functional_units:
                priority_str = ["", "CRITICAL", "HIGH", "MEDIUM", "LOW"][u.priority.value]
                lines.append(f"  [{priority_str}] {u.unit_id}: {u.description}")
                lines.append(f"    Files: {', '.join(u.affected_files)}")
                if u.depends_on:
                    lines.append(f"    Depends on: {', '.join(u.depends_on)}")
            lines.append("")

        if decomposition.visual_units:
            lines.append("VISUAL UNITS (require human verification):")
            for u in decomposition.visual_units:
                lines.append(f"  - {u.description}")
                lines.append(f"    Files: {', '.join(u.affected_files)}")
            lines.append("")

        return "\n".join(lines)
