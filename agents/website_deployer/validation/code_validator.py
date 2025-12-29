"""
Code Generation Validation Module

This module provides comprehensive validation for LLM-generated code to ensure
completeness and correctness before deployment. It implements a multi-phase
validation strategy to catch issues early in the deployment process.

Phases:
1. AST-based import validation
2. Requirements.txt completeness check
3. Service layer completeness check
4. Schema completeness check
"""

import ast
import logging
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path
import re

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of code validation with detailed error information."""
    is_valid: bool = True
    missing_imports: List[str] = field(default_factory=list)
    missing_dependencies: List[str] = field(default_factory=list)
    incomplete_modules: List[str] = field(default_factory=list)
    incomplete_schemas: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, error: str):
        """Add an error and mark validation as invalid."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str):
        """Add a warning without invalidating."""
        self.warnings.append(warning)

    def get_summary(self) -> str:
        """Get a human-readable summary of validation results."""
        if self.is_valid:
            return "✅ Validation PASSED - All checks successful"

        summary = ["❌ Validation FAILED - Issues detected:"]

        if self.missing_imports:
            summary.append(f"\n🔴 Missing Imports ({len(self.missing_imports)}):")
            for imp in self.missing_imports[:10]:  # Limit to first 10
                summary.append(f"  - {imp}")
            if len(self.missing_imports) > 10:
                summary.append(f"  ... and {len(self.missing_imports) - 10} more")

        if self.missing_dependencies:
            summary.append(f"\n🔴 Missing Dependencies ({len(self.missing_dependencies)}):")
            for dep in self.missing_dependencies:
                summary.append(f"  - {dep}")

        if self.incomplete_modules:
            summary.append(f"\n🔴 Incomplete Modules ({len(self.incomplete_modules)}):")
            for mod in self.incomplete_modules:
                summary.append(f"  - {mod}")

        if self.incomplete_schemas:
            summary.append(f"\n🔴 Incomplete Schemas ({len(self.incomplete_schemas)}):")
            for schema in self.incomplete_schemas:
                summary.append(f"  - {schema}")

        if self.errors:
            summary.append(f"\n🔴 Other Errors ({len(self.errors)}):")
            for error in self.errors[:5]:
                summary.append(f"  - {error}")
            if len(self.errors) > 5:
                summary.append(f"  ... and {len(self.errors) - 5} more")

        if self.warnings:
            summary.append(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for warning in self.warnings[:5]:
                summary.append(f"  - {warning}")

        return "\n".join(summary)


class CodeValidator:
    """Validates LLM-generated code for completeness and correctness."""

    # Standard library modules that don't need validation
    STDLIB_MODULES = {
        'os', 'sys', 're', 'json', 'datetime', 'time', 'logging', 'typing',
        'pathlib', 'collections', 'dataclasses', 'functools', 'itertools',
        'asyncio', 'concurrent', 'contextlib', 'enum', 'abc', 'io', 'base64',
        'hashlib', 'hmac', 'secrets', 'uuid', 'copy', 'pickle', 'shutil',
    }

    # Expected service modules for RAICA
    EXPECTED_SERVICES = {
        'agent_service': ['get_available_agents', 'get_agent_definition', 'start_execution'],
        'chat_service': ['generate_and_stream_response', 'get_response_stream'],
    }

    # Expected schema patterns
    EXPECTED_SCHEMA_PATTERNS = {
        'Create': r'class\s+\w+Create\s*\(',
        'Read': r'class\s+\w+Read\s*\(',
        'Update': r'class\s+\w+Update\s*\(',
    }

    def __init__(self):
        self.result = ValidationResult()

    def validate_generated_code(self, generated_files: Dict[str, str]) -> ValidationResult:
        """
        Validates that all imports in generated code are resolvable.

        Args:
            generated_files: Dict mapping file paths to file contents

        Returns:
            ValidationResult with detailed validation information
        """
        logger.info("Starting code validation...")
        self.result = ValidationResult()

        # Extract all available modules from generated files
        all_modules = self._extract_available_modules(generated_files)
        logger.info(f"Found {len(all_modules)} available modules in generated code")

        # Phase 1: Validate imports
        self._validate_imports(generated_files, all_modules)

        # Phase 2: Validate dependencies
        self._validate_dependencies(generated_files)

        # Phase 3: Validate service layer
        self._validate_services(generated_files)

        # Phase 4: Validate schemas
        self._validate_schemas(generated_files)

        logger.info(f"Validation complete: {'PASSED' if self.result.is_valid else 'FAILED'}")
        return self.result

    def _extract_available_modules(self, generated_files: Dict[str, str]) -> Set[str]:
        """Extract all module paths that will exist after deployment."""
        modules = set()

        for file_path in generated_files.keys():
            # Convert file path to module path
            # e.g., "app/services/agent_service.py" -> "app.services.agent_service"
            if file_path.endswith('.py'):
                module_path = file_path.replace('/', '.').replace('.py', '')
                modules.add(module_path)

                # Also add parent packages
                parts = module_path.split('.')
                for i in range(1, len(parts)):
                    modules.add('.'.join(parts[:i]))

        return modules

    def _validate_imports(self, generated_files: Dict[str, str], all_modules: Set[str]):
        """Validate that all imports can be resolved."""
        logger.info("Validating imports...")

        for file_path, content in generated_files.items():
            if not file_path.endswith('.py'):
                continue

            try:
                tree = ast.parse(content)
                imports = self._extract_imports(tree)

                for imp in imports:
                    if not self._is_import_resolvable(imp, all_modules, file_path):
                        self.result.missing_imports.append(f"{file_path}: {imp}")
                        self.result.is_valid = False

            except SyntaxError as e:
                self.result.add_error(f"Syntax error in {file_path}: {e}")
            except Exception as e:
                self.result.add_error(f"Error parsing {file_path}: {e}")

    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extract all import statements from an AST."""
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                    # Also track "from X import Y" as "X.Y" for validation
                    for alias in node.names:
                        imports.append(f"{node.module}.{alias.name}")

        return imports

    def _is_import_resolvable(self, import_path: str, all_modules: Set[str],
                             file_path: str) -> bool:
        """Check if an import can be resolved."""
        # Get base module (first part of import)
        base_module = import_path.split('.')[0]

        # Check if it's stdlib
        if base_module in self.STDLIB_MODULES:
            return True

        # Check if it's a third-party package (we'll validate in dependencies check)
        if base_module in {'fastapi', 'pydantic', 'sqlalchemy', 'jose', 'passlib',
                          'uvicorn', 'httpx', 'redis', 'celery', 'alembic', 'jinja2',
                          'requests', 'python', 'email_validator', 'sse_starlette',
                          'psycopg2', 'asyncpg', 'dotenv'}:
            return True

        # Check if it's in generated modules
        if import_path in all_modules:
            return True

        # Check for relative imports by examining the module path
        # e.g., file "app/api/endpoints/agents.py" imports "app.services.agent_service"
        if import_path.startswith('app.'):
            return import_path in all_modules

        return False

    def _validate_dependencies(self, generated_files: Dict[str, str]):
        """Validate that requirements.txt includes all third-party dependencies."""
        logger.info("Validating dependencies...")

        # Expected dependencies for RAICA
        expected_deps = {
            'fastapi', 'uvicorn', 'pydantic', 'pydantic-settings', 'sqlalchemy',
            'asyncpg', 'psycopg2-binary', 'alembic', 'python-jose', 'passlib',
            'python-multipart', 'email-validator', 'sse-starlette', 'httpx',
            'redis', 'celery', 'jinja2', 'requests', 'python-dotenv'
        }

        # Extract actual dependencies from requirements.txt if present
        requirements_content = generated_files.get('requirements.txt', '')
        if not requirements_content:
            self.result.add_error("requirements.txt not found in generated files")
            return

        actual_deps = set()
        for line in requirements_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                # Extract package name (before any version specifier)
                pkg_name = re.split(r'[>=<\[]', line)[0].strip()
                actual_deps.add(pkg_name)

        # Find missing dependencies
        missing = expected_deps - actual_deps
        if missing:
            for dep in missing:
                self.result.missing_dependencies.append(dep)
                self.result.is_valid = False

    def _validate_services(self, generated_files: Dict[str, str]):
        """Validate that all expected service modules and functions exist."""
        logger.info("Validating service layer...")

        for service_name, expected_functions in self.EXPECTED_SERVICES.items():
            service_path = f'app/services/{service_name}.py'

            if service_path not in generated_files:
                self.result.incomplete_modules.append(
                    f"{service_path} is missing entirely"
                )
                self.result.is_valid = False
                continue

            service_content = generated_files[service_path]

            # Check for expected functions
            for func_name in expected_functions:
                # Look for function definition
                pattern = rf'^\s*(?:async\s+)?def\s+{func_name}\s*\('
                if not re.search(pattern, service_content, re.MULTILINE):
                    self.result.incomplete_modules.append(
                        f"{service_path}: missing function '{func_name}'"
                    )
                    self.result.is_valid = False

    def _validate_schemas(self, generated_files: Dict[str, str]):
        """Validate that schema files have complete CRUD schemas."""
        logger.info("Validating schemas...")

        # Find all schema files
        schema_files = [f for f in generated_files.keys()
                       if f.startswith('app/schemas/') and f.endswith('.py')
                       and not f.endswith('__init__.py')]

        for schema_file in schema_files:
            # Skip auth.py as it has different patterns
            if 'auth.py' in schema_file:
                continue

            content = generated_files[schema_file]

            # Check for Create, Read, Update patterns
            for pattern_name, pattern_regex in self.EXPECTED_SCHEMA_PATTERNS.items():
                if not re.search(pattern_regex, content):
                    # Only warn for Update (not always needed), error for Create/Read
                    if pattern_name == 'Update':
                        self.result.add_warning(
                            f"{schema_file}: missing {pattern_name} schema (may be intentional)"
                        )
                    else:
                        self.result.incomplete_schemas.append(
                            f"{schema_file}: missing {pattern_name} schema"
                        )
                        self.result.is_valid = False


def validate_generated_code(generated_files: Dict[str, str]) -> ValidationResult:
    """
    Convenience function to validate generated code.

    Args:
        generated_files: Dict mapping file paths to file contents

    Returns:
        ValidationResult with detailed validation information
    """
    validator = CodeValidator()
    return validator.validate_generated_code(generated_files)
