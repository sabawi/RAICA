"""
Documentation Generator
=======================

Generates project documentation files from CODE_GENERATION phase context.
Creates structured documentation in the project's docs/ directory.

Generated Files:
- docs/PLANNING.md - Implementation plan, requirements, milestones
- docs/ARCHITECTURE.md - Architecture type, components, patterns, data flow
- docs/DESIGN.md - File specifications, interfaces
- README.md enhancement - Adds "How to Continue Development" section

Usage:
    generator = DocumentationGenerator(project_dir, phase_context)
    generator.generate_all()
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DocumentationGenerator:
    """
    Generates project documentation from phase context.

    Takes the accumulated context from CODE_GENERATION phases
    (requirements, planning, architecture, design) and writes
    structured documentation files.
    """

    def __init__(
        self,
        project_dir: Path,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the documentation generator.

        Args:
            project_dir: Root directory of the generated project
            context: Phase context containing requirements, plan, architecture, design
        """
        self.project_dir = Path(project_dir)
        self.docs_dir = self.project_dir / "docs"
        self.context = context or {}

        # Extract commonly used context elements
        self.original_request = self.context.get('original_request', '')
        self.requirements = self.context.get('refined_requirements', [])
        self.implementation_plan = self.context.get('implementation_plan', [])
        self.architecture = self.context.get('architecture_decisions', {})
        self.components = self.context.get('components', [])
        self.file_specs = self.context.get('file_specifications', [])
        self.generated_files = self.context.get('generated_files', {})
        self.interfaces = self.context.get('interfaces', {})

    def generate_all(self) -> Dict[str, bool]:
        """
        Generate all documentation files.

        Returns:
            Dict mapping filename to success status
        """
        results = {}

        # Ensure docs directory exists
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        # Generate each documentation file
        results['PLANNING.md'] = self._generate_planning()
        results['ARCHITECTURE.md'] = self._generate_architecture()
        results['DESIGN.md'] = self._generate_design()
        results['README.md'] = self._enhance_readme()

        logger.info(f"Documentation generation complete: {results}")
        return results

    def _generate_planning(self) -> bool:
        """
        Generate docs/PLANNING.md with implementation plan and requirements.

        Returns:
            True if successful
        """
        try:
            # Ensure docs directory exists
            self.docs_dir.mkdir(parents=True, exist_ok=True)

            content = self._build_planning_content()
            path = self.docs_dir / "PLANNING.md"
            path.write_text(content)
            logger.info(f"Generated {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to generate PLANNING.md: {e}")
            return False

    def _build_planning_content(self) -> str:
        """Build the content for PLANNING.md."""
        lines = [
            "# Project Planning",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "## Original Request",
            "",
            f"> {self.original_request}",
            "",
        ]

        # Requirements section
        if self.requirements:
            lines.extend([
                "## Requirements",
                "",
            ])
            for req in self.requirements:
                lines.append(f"- {req}")
            lines.append("")

        # Implementation Plan section
        if self.implementation_plan:
            lines.extend([
                "## Implementation Plan",
                "",
            ])
            for i, step in enumerate(self.implementation_plan, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # Milestones (derived from plan)
        if self.implementation_plan:
            lines.extend([
                "## Milestones",
                "",
                "| Phase | Status |",
                "|-------|--------|",
            ])
            phases = ["Requirements", "Planning", "Architecture", "Design", "Coding", "Testing"]
            for phase in phases:
                lines.append(f"| {phase} | Completed |")
            lines.append("")

        # Future enhancements
        lines.extend([
            "## Future Enhancements",
            "",
            "- [ ] Add comprehensive test suite",
            "- [ ] Implement error handling improvements",
            "- [ ] Add logging and monitoring",
            "- [ ] Create deployment configuration",
            "",
        ])

        return "\n".join(lines)

    def _generate_architecture(self) -> bool:
        """
        Generate docs/ARCHITECTURE.md with system architecture.

        Returns:
            True if successful
        """
        try:
            # Ensure docs directory exists
            self.docs_dir.mkdir(parents=True, exist_ok=True)

            content = self._build_architecture_content()
            path = self.docs_dir / "ARCHITECTURE.md"
            path.write_text(content)
            logger.info(f"Generated {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to generate ARCHITECTURE.md: {e}")
            return False

    def _build_architecture_content(self) -> str:
        """Build the content for ARCHITECTURE.md."""
        lines = [
            "# System Architecture",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]

        # Architecture Type
        arch_type = self.architecture.get('type', 'modular')
        lines.extend([
            "## Architecture Type",
            "",
            f"**{arch_type.title()}**",
            "",
        ])

        # Design Patterns
        patterns = self.architecture.get('patterns', [])
        if patterns:
            lines.extend([
                "## Design Patterns",
                "",
            ])
            for pattern in patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        # Components
        if self.components:
            lines.extend([
                "## Components",
                "",
            ])
            for comp in self.components:
                name = comp.get('name', 'Unknown')
                purpose = comp.get('purpose', '')
                responsibilities = comp.get('responsibilities', [])

                lines.append(f"### {name}")
                lines.append("")
                if purpose:
                    lines.append(f"**Purpose:** {purpose}")
                    lines.append("")
                if responsibilities:
                    lines.append("**Responsibilities:**")
                    for resp in responsibilities:
                        lines.append(f"- {resp}")
                    lines.append("")

        # Data Flow
        data_flow = self.architecture.get('data_flow', '')
        if data_flow:
            lines.extend([
                "## Data Flow",
                "",
                data_flow,
                "",
            ])

        # Component Diagram (text-based)
        if self.components:
            lines.extend([
                "## Component Diagram",
                "",
                "```",
            ])
            for i, comp in enumerate(self.components):
                name = comp.get('name', 'Component')
                if i == 0:
                    lines.append(f"┌─────────────────────────────┐")
                    lines.append(f"│  {name:^25}  │")
                    lines.append(f"└─────────────────────────────┘")
                else:
                    lines.append(f"           │")
                    lines.append(f"           ▼")
                    lines.append(f"┌─────────────────────────────┐")
                    lines.append(f"│  {name:^25}  │")
                    lines.append(f"└─────────────────────────────┘")
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _generate_design(self) -> bool:
        """
        Generate docs/DESIGN.md with file specifications and interfaces.

        Returns:
            True if successful
        """
        try:
            # Ensure docs directory exists
            self.docs_dir.mkdir(parents=True, exist_ok=True)

            content = self._build_design_content()
            path = self.docs_dir / "DESIGN.md"
            path.write_text(content)
            logger.info(f"Generated {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to generate DESIGN.md: {e}")
            return False

    def _build_design_content(self) -> str:
        """Build the content for DESIGN.md."""
        lines = [
            "# Detailed Design",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]

        # File Specifications
        if self.file_specs:
            lines.extend([
                "## File Specifications",
                "",
            ])
            for spec in self.file_specs:
                path = spec.get('path', 'unknown')
                purpose = spec.get('purpose', '')
                outline = spec.get('contents_outline', '')
                deps = spec.get('dependencies', [])

                lines.append(f"### `{path}`")
                lines.append("")
                if purpose:
                    lines.append(f"**Purpose:** {purpose}")
                    lines.append("")
                if outline:
                    lines.append(f"**Contents:**")
                    lines.append(f"```")
                    lines.append(outline)
                    lines.append(f"```")
                    lines.append("")
                if deps:
                    lines.append(f"**Dependencies:** {', '.join(deps)}")
                    lines.append("")

        # Interface Definitions
        if self.interfaces:
            lines.extend([
                "## Interface Definitions",
                "",
            ])
            for file_path, interface in self.interfaces.items():
                lines.append(f"### `{file_path}`")
                lines.append("")

                # Handle both InterfaceDefinition objects and dicts
                if hasattr(interface, 'exports'):
                    exports = interface.exports
                    lines.append("**Exports:**")
                    for exp in exports[:10]:
                        if hasattr(exp, 'name'):
                            lines.append(f"- `{exp.name}` ({exp.symbol_type})")
                        else:
                            lines.append(f"- {exp}")
                    if len(exports) > 10:
                        lines.append(f"- ... and {len(exports) - 10} more")
                elif isinstance(interface, dict):
                    exports = interface.get('exports', [])
                    if exports:
                        lines.append("**Exports:**")
                        for exp in exports[:10]:
                            if isinstance(exp, dict):
                                lines.append(f"- `{exp.get('name', '?')}`")
                            else:
                                lines.append(f"- {exp}")

                lines.append("")

        # Generated Files Summary
        if self.generated_files:
            lines.extend([
                "## Generated Files",
                "",
                "| File | Size (bytes) |",
                "|------|-------------|",
            ])
            for file_path in sorted(self.generated_files.keys()):
                content = self.generated_files[file_path]
                size = len(content) if isinstance(content, str) else 0
                lines.append(f"| `{file_path}` | {size} |")
            lines.append("")

        return "\n".join(lines)

    def _enhance_readme(self) -> bool:
        """
        Enhance README.md with "How to Continue Development" section.

        Returns:
            True if successful
        """
        try:
            readme_path = self.project_dir / "README.md"

            if readme_path.exists():
                content = readme_path.read_text()
            else:
                # Create basic README if it doesn't exist
                content = self._build_basic_readme()

            # Check if continuation section already exists
            if "## How to Continue Development" not in content:
                content += self._build_continuation_section()
                readme_path.write_text(content)
                logger.info(f"Enhanced {readme_path}")

            return True
        except Exception as e:
            logger.error(f"Failed to enhance README.md: {e}")
            return False

    def _build_basic_readme(self) -> str:
        """Build a basic README if one doesn't exist."""
        project_name = self.project_dir.name.replace('_', ' ').title()

        lines = [
            f"# {project_name}",
            "",
            self.original_request[:200] if self.original_request else "Auto-generated project",
            "",
            f"*Generated by RAICA on {datetime.now().strftime('%Y-%m-%d')}*",
            "",
        ]

        # Files section
        if self.generated_files:
            lines.extend([
                "## Files",
                "",
            ])
            for file_path in sorted(self.generated_files.keys()):
                lines.append(f"- `{file_path}`")
            lines.append("")

        return "\n".join(lines)

    def _build_continuation_section(self) -> str:
        """Build the 'How to Continue Development' section for README."""
        lines = [
            "",
            "---",
            "",
            "## How to Continue Development",
            "",
            "This project was generated by RAICA. Here's how to continue development:",
            "",
            "### Understanding the Project",
            "",
            "1. **Read the documentation:**",
        ]

        # Point to generated docs
        if (self.docs_dir / "PLANNING.md").exists():
            lines.append("   - `docs/PLANNING.md` - Requirements and implementation plan")
        if (self.docs_dir / "ARCHITECTURE.md").exists():
            lines.append("   - `docs/ARCHITECTURE.md` - System architecture and components")
        if (self.docs_dir / "DESIGN.md").exists():
            lines.append("   - `docs/DESIGN.md` - File specifications and interfaces")

        lines.extend([
            "",
            "2. **Review the generated code** in each file to understand the implementation",
            "",
            "### Making Changes",
            "",
            "1. **For bug fixes:** Look at the relevant file, understand the logic, make targeted changes",
            "2. **For new features:** Update the docs first, then implement following the existing patterns",
            "3. **For refactoring:** Ensure tests pass before and after changes",
            "",
            "### Continuing with RAICA",
            "",
            "You can ask RAICA to:",
            "",
            "- \"Fix the bug in [file]\"",
            "- \"Add [feature] to the project\"",
            "- \"Improve error handling in [component]\"",
            "- \"Add tests for [module]\"",
            "",
            "RAICA will use the project context to understand the existing code.",
            "",
        ])

        return "\n".join(lines)

    def generate_phase_doc(self, phase: str, phase_data: Dict[str, Any]) -> bool:
        """
        Generate documentation for a specific phase.

        This can be called incrementally as each phase completes.

        Args:
            phase: Phase name (PLANNING, ARCHITECTURE, DESIGN, COMPLETE)
            phase_data: Data from that phase

        Returns:
            True if successful
        """
        # Update context with phase data
        self.context.update(phase_data)

        # Refresh extracted fields
        self.original_request = self.context.get('original_request', self.original_request)
        self.requirements = self.context.get('refined_requirements', self.requirements)
        self.implementation_plan = self.context.get('implementation_plan', self.implementation_plan)
        self.architecture = self.context.get('architecture_decisions', self.architecture)
        self.components = self.context.get('components', self.components)
        self.file_specs = self.context.get('file_specifications', self.file_specs)
        self.generated_files = self.context.get('generated_files', self.generated_files)
        self.interfaces = self.context.get('interfaces', self.interfaces)

        # Ensure docs directory exists
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        # Generate appropriate documentation based on phase
        phase_upper = phase.upper()

        if phase_upper == 'PLANNING':
            return self._generate_planning()
        elif phase_upper == 'ARCHITECTURE':
            return self._generate_architecture()
        elif phase_upper == 'DESIGN':
            return self._generate_design()
        elif phase_upper == 'COMPLETE':
            # Generate all and enhance README
            self.generate_all()
            return True
        else:
            logger.warning(f"Unknown phase for documentation: {phase}")
            return False
