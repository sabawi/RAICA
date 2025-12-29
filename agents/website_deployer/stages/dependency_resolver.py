#!/usr/bin/env python3
"""
Dependency Resolution System
============================

Ensures all generated files have their dependencies available and paths are correct.

Features:
- Dependency graph generation
- Topological sorting for correct generation order
- Path resolution validation
- Circular dependency detection
- Missing dependency identification
"""

import logging
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class FileDependency:
    """Represents a file and its dependencies."""
    path: str
    depends_on: List[str] = field(default_factory=list)
    required_by: List[str] = field(default_factory=list)
    file_type: str = "code"  # code, config, template, migration
    generates_in_phase: int = 1
    priority: int = 0  # Higher priority files generated first


@dataclass
class DependencyGraph:
    """Complete dependency graph for project."""
    files: Dict[str, FileDependency] = field(default_factory=dict)
    generation_order: List[str] = field(default_factory=list)
    has_cycles: bool = False
    cycle_details: List[List[str]] = field(default_factory=list)
    missing_dependencies: Dict[str, List[str]] = field(default_factory=dict)


class DependencyResolver:
    """
    Resolves file dependencies and determines correct generation order.

    Example:
        resolver = DependencyResolver()

        # Add file dependencies
        resolver.add_file("config/config.php")
        resolver.add_file("includes/email_helper.php", depends_on=["config/config.php"])
        resolver.add_file("register.php", depends_on=["config/config.php", "includes/email_helper.php"])

        # Build dependency graph
        graph = resolver.build_graph()

        # Get generation order
        order = graph.generation_order
        # Result: ["config/config.php", "includes/email_helper.php", "register.php"]
    """

    def __init__(self):
        self.dependencies: Dict[str, FileDependency] = {}

    def add_file(self, path: str, depends_on: Optional[List[str]] = None,
                 file_type: str = "code", priority: int = 0, phase: int = 1) -> None:
        """
        Add a file to the dependency graph.

        Args:
            path: File path relative to project root
            depends_on: List of file paths this file depends on
            file_type: Type of file (code, config, template, migration)
            priority: Priority level (higher = generated first among same dependencies)
            phase: Generation phase (1=infrastructure, 2=core, 3=features)
        """
        if path not in self.dependencies:
            self.dependencies[path] = FileDependency(
                path=path,
                depends_on=depends_on or [],
                file_type=file_type,
                priority=priority,
                generates_in_phase=phase
            )
        else:
            # Update existing
            dep = self.dependencies[path]
            if depends_on:
                dep.depends_on.extend(depends_on)
            dep.file_type = file_type
            dep.priority = max(dep.priority, priority)
            dep.generates_in_phase = phase

    def add_dependency(self, file_path: str, depends_on: str) -> None:
        """Add a single dependency relationship."""
        if file_path not in self.dependencies:
            self.add_file(file_path)
        if depends_on not in self.dependencies:
            self.add_file(depends_on)

        self.dependencies[file_path].depends_on.append(depends_on)
        self.dependencies[depends_on].required_by.append(file_path)

    def build_graph(self) -> DependencyGraph:
        """
        Build complete dependency graph with generation order.

        Returns:
            DependencyGraph with topologically sorted generation order
        """
        # CRITICAL FIX: Build reverse dependencies (required_by) before any other operations
        self._build_reverse_dependencies()

        graph = DependencyGraph(files=self.dependencies.copy())

        # Check for missing dependencies
        graph.missing_dependencies = self._find_missing_dependencies()

        if graph.missing_dependencies:
            logger.warning(f"Found {len(graph.missing_dependencies)} files with missing dependencies")
            for file_path, missing in graph.missing_dependencies.items():
                logger.warning(f"  {file_path} missing: {', '.join(missing)}")

        # Detect circular dependencies
        cycles = self._detect_cycles()
        if cycles:
            graph.has_cycles = True
            graph.cycle_details = cycles
            logger.error(f"Detected {len(cycles)} circular dependencies!")
            for cycle in cycles:
                logger.error(f"  Cycle: {' → '.join(cycle)} → {cycle[0]}")
            return graph

        # Topological sort for generation order
        graph.generation_order = self._topological_sort()

        logger.info(f"Dependency graph built: {len(graph.files)} files, {len(graph.generation_order)} in order")

        return graph

    def _build_reverse_dependencies(self) -> None:
        """
        Build reverse dependency relationships (required_by lists).

        For each file A that depends on file B, add A to B's required_by list.
        This is critical for the topological sort to work correctly.
        """
        # Clear all required_by lists first
        for dep in self.dependencies.values():
            dep.required_by = []

        # Build required_by relationships
        for file_path, dep in self.dependencies.items():
            for dependency in dep.depends_on:
                if dependency in self.dependencies:
                    self.dependencies[dependency].required_by.append(file_path)

    def _find_missing_dependencies(self) -> Dict[str, List[str]]:
        """Find dependencies that are referenced but not defined."""
        missing = {}
        all_files = set(self.dependencies.keys())

        for file_path, dep in self.dependencies.items():
            missing_deps = [d for d in dep.depends_on if d not in all_files]
            if missing_deps:
                missing[file_path] = missing_deps

        return missing

    def _detect_cycles(self) -> List[List[str]]:
        """
        Detect circular dependencies using DFS.

        Returns:
            List of cycles found (each cycle is a list of file paths)
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node: str) -> bool:
            """DFS to detect cycles."""
            # Skip nodes that don't exist in dependencies (missing dependencies)
            if node not in self.dependencies:
                return False

            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self.dependencies[node].depends_on:
                # Skip missing dependencies
                if neighbor not in self.dependencies:
                    continue

                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
                    return True

            path.pop()
            rec_stack.remove(node)
            return False

        for node in self.dependencies:
            if node not in visited:
                dfs(node)

        return cycles

    def _topological_sort(self) -> List[str]:
        """
        Topological sort using Kahn's algorithm.

        Returns:
            List of files in dependency order (dependencies first)
        """
        # Calculate in-degree for each node
        # in-degree = number of dependencies this node has
        in_degree = {path: 0 for path in self.dependencies}
        for path, dep in self.dependencies.items():
            for dependency in dep.depends_on:
                if dependency in in_degree:
                    in_degree[path] += 1

        # Queue for nodes with no dependencies
        # Use a list for sorting, then convert to deque
        initial_nodes = [path for path, degree in in_degree.items() if degree == 0]

        # Sort by phase (ascending) and priority (descending within phase)
        initial_nodes.sort(key=lambda p: (
            self.dependencies[p].generates_in_phase,
            -self.dependencies[p].priority
        ))

        queue = deque(initial_nodes)
        result = []

        while queue:
            # Get node with no dependencies
            current = queue.popleft()
            result.append(current)

            # Collect newly available nodes
            newly_available = []

            # Reduce in-degree for dependent nodes
            for dependent in self.dependencies[current].required_by:
                if dependent in in_degree:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        newly_available.append(dependent)

            # Sort newly available nodes before adding to queue
            if newly_available:
                newly_available.sort(key=lambda p: (
                    self.dependencies[p].generates_in_phase,
                    -self.dependencies[p].priority
                ))
                queue.extend(newly_available)

        return result

    def validate_path(self, from_file: str, include_path: str) -> Tuple[bool, str]:
        """
        Validate that an include/require path will work from the given file.

        Args:
            from_file: Source file path (e.g., "templates/register.php")
            include_path: Path used in include/require statement

        Returns:
            Tuple of (is_valid, corrected_path)
        """
        from_dir = Path(from_file).parent

        # If absolute path (starts with /), check if file exists in project
        if include_path.startswith('/'):
            target = include_path[1:]  # Remove leading /
        # If uses __DIR__, extract the relative part
        elif '__DIR__' in include_path:
            # Extract path after __DIR__
            parts = include_path.split('__DIR__')
            if len(parts) > 1:
                rel_path = parts[1].strip().strip('/').strip("'").strip('"')
                target = str(from_dir / rel_path)
            else:
                return False, include_path
        else:
            # Relative path from file location
            target = str(from_dir / include_path)

        # Normalize path
        target = str(Path(target).normalize())

        # Check if target exists in dependencies
        is_valid = target in self.dependencies

        if not is_valid:
            # Try to find closest match
            suggested = self._find_closest_path(target)
            if suggested:
                return False, suggested

        return is_valid, target if is_valid else include_path

    def _find_closest_path(self, target: str) -> Optional[str]:
        """Find closest matching path for a missing dependency."""
        target_name = Path(target).name

        # Look for files with same name
        for file_path in self.dependencies:
            if Path(file_path).name == target_name:
                return file_path

        return None

    def get_generation_phases(self) -> Dict[int, List[str]]:
        """
        Group files by generation phase.

        Returns:
            Dictionary mapping phase number to list of file paths
        """
        phases = defaultdict(list)

        for path, dep in self.dependencies.items():
            phases[dep.generates_in_phase].append(path)

        # Sort within each phase by priority
        for phase in phases:
            phases[phase].sort(key=lambda p: -self.dependencies[p].priority)

        return dict(sorted(phases.items()))

    def generate_dependency_report(self, output_file: Optional[str] = None) -> str:
        """
        Generate a human-readable dependency report.

        Args:
            output_file: Optional file path to save report

        Returns:
            Report as string
        """
        report_lines = [
            "=" * 80,
            "DEPENDENCY ANALYSIS REPORT",
            "=" * 80,
            ""
        ]

        graph = self.build_graph()

        # Summary
        report_lines.extend([
            "SUMMARY:",
            f"  Total files: {len(graph.files)}",
            f"  Files with dependencies: {sum(1 for d in graph.files.values() if d.depends_on)}",
            f"  Circular dependencies: {'YES ❌' if graph.has_cycles else 'NO ✅'}",
            f"  Missing dependencies: {len(graph.missing_dependencies)}",
            ""
        ])

        # Cycles
        if graph.has_cycles:
            report_lines.extend([
                "CIRCULAR DEPENDENCIES (Must Fix!):",
                ""
            ])
            for i, cycle in enumerate(graph.cycle_details, 1):
                report_lines.append(f"  Cycle {i}: {' → '.join(cycle)} → {cycle[0]}")
            report_lines.append("")

        # Missing dependencies
        if graph.missing_dependencies:
            report_lines.extend([
                "MISSING DEPENDENCIES (Must Fix!):",
                ""
            ])
            for file_path, missing in sorted(graph.missing_dependencies.items()):
                report_lines.append(f"  {file_path}:")
                for dep in missing:
                    report_lines.append(f"    - {dep}")
            report_lines.append("")

        # Generation order
        report_lines.extend([
            "GENERATION ORDER (Dependencies First):",
            ""
        ])

        phases = self.get_generation_phases()
        for phase_num, files in phases.items():
            report_lines.append(f"  Phase {phase_num}:")
            for file_path in files:
                dep = graph.files[file_path]
                deps_str = f" (depends on: {', '.join(dep.depends_on)})" if dep.depends_on else ""
                report_lines.append(f"    {file_path}{deps_str}")
            report_lines.append("")

        # File details
        report_lines.extend([
            "FILE DETAILS:",
            ""
        ])

        for file_path in sorted(graph.files.keys()):
            dep = graph.files[file_path]
            report_lines.extend([
                f"  {file_path}:",
                f"    Type: {dep.file_type}",
                f"    Phase: {dep.generates_in_phase}",
                f"    Priority: {dep.priority}",
                f"    Depends on: {dep.depends_on or 'None'}",
                f"    Required by: {dep.required_by or 'None'}",
                ""
            ])

        report = "\n".join(report_lines)

        # Save to file if requested
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report)
            logger.info(f"Dependency report saved to: {output_file}")

        return report


def extract_php_dependencies(file_content: str, file_path: str) -> List[str]:
    """
    Extract PHP require/include dependencies from file content.

    Args:
        file_content: PHP file content
        file_path: Path of the file being analyzed

    Returns:
        List of dependency file paths
    """
    import re

    dependencies = []

    # Patterns for require/include statements
    patterns = [
        r"require_once\s+['\"]([^'\"]+)['\"]",
        r"require\s+['\"]([^'\"]+)['\"]",
        r"include_once\s+['\"]([^'\"]+)['\"]",
        r"include\s+['\"]([^'\"]+)['\"]",
        r"require_once\s+__DIR__\s*\.\s*['\"]([^'\"]+)['\"]",
        r"require\s+__DIR__\s*\.\s*['\"]([^'\"]+)['\"]",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, file_content)
        dependencies.extend(matches)

    # Resolve relative paths
    file_dir = Path(file_path).parent
    resolved_deps = []

    for dep in dependencies:
        if dep.startswith('/'):
            # Absolute path from project root
            resolved_deps.append(dep[1:])
        else:
            # Relative path from file location
            resolved = str((file_dir / dep).normalize())
            resolved_deps.append(resolved)

    return resolved_deps


def build_workflow_dependencies(workflow_spec: Dict) -> DependencyResolver:
    """
    Build dependency graph from workflow specification.

    Args:
        workflow_spec: Workflow specification with file dependencies

    Returns:
        Configured DependencyResolver
    """
    resolver = DependencyResolver()

    # Add files from workflow
    for workflow_name, workflow_data in workflow_spec.items():
        if 'files' in workflow_data:
            for file_spec in workflow_data['files']:
                if isinstance(file_spec, dict):
                    path = file_spec.get('path')
                    depends_on = file_spec.get('requires', [])
                    priority = file_spec.get('priority', 0)
                    phase = file_spec.get('phase', 1)
                    file_type = file_spec.get('type', 'code')

                    resolver.add_file(
                        path=path,
                        depends_on=depends_on,
                        file_type=file_type,
                        priority=priority,
                        phase=phase
                    )
                else:
                    # Simple string path
                    resolver.add_file(file_spec)

    return resolver


if __name__ == "__main__":
    # Example usage
    print("Dependency Resolver - Example Usage")
    print("=" * 60)

    # Create resolver
    resolver = DependencyResolver()

    # Add files with dependencies (typical PHP application)
    resolver.add_file("config/config.php", file_type="config", priority=100, phase=1)
    resolver.add_file("app/database/Database.php", depends_on=["config/config.php"],
                     file_type="code", priority=90, phase=1)
    resolver.add_file("includes/email_helper.php", depends_on=["config/config.php"],
                     file_type="code", priority=80, phase=2)
    resolver.add_file("templates/register.php",
                     depends_on=["config/config.php", "includes/email_helper.php"],
                     file_type="template", priority=50, phase=3)
    resolver.add_file("templates/login.php",
                     depends_on=["config/config.php"],
                     file_type="template", priority=50, phase=3)
    resolver.add_file("templates/verify-email.php",
                     depends_on=["config/config.php"],
                     file_type="template", priority=40, phase=3)

    # Build graph
    graph = resolver.build_graph()

    # Generate report
    report = resolver.generate_dependency_report()
    print(report)

    # Show generation order
    print("\n" + "=" * 60)
    print("RECOMMENDED GENERATION ORDER:")
    print("=" * 60)
    for i, file_path in enumerate(graph.generation_order, 1):
        print(f"{i}. {file_path}")
