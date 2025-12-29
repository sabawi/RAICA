#!/usr/bin/env python3
"""
Consistency Verifier - Stage 6 of Intelligent Code Generation
==============================================================

Verifies generated code consistency and correctness.

This stage:
1. Verifies API contracts match across frontend/backend
2. Validates database schema matches models
3. Checks security implementations
4. Verifies requirements coverage
5. AST-based code integrity validation (NEW)
6. Import resolution verification (NEW)
7. Dependencies completeness check (NEW)
8. Generates verification report
"""

import ast
import logging
import re
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field

from .assembly_coordinator import AssembledProject
from .requirement_elaborator import DetailedSpecification
from .tech_stack_config import TechStackConfig

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    """A verification issue."""
    severity: str  # "CRITICAL", "ERROR", "WARNING", "INFO"
    location: str
    message: str
    component: str


@dataclass
class CoverageReport:
    """Report on requirements coverage."""
    missing_components: List[str] = field(default_factory=list)
    missing_features: List[str] = field(default_factory=list)
    missing_endpoints: List[str] = field(default_factory=list)
    
    def is_complete(self) -> bool:
        return not (self.missing_components or self.missing_features or self.missing_endpoints)


@dataclass
class VerificationReport:
    """Complete verification report."""
    api_issues: List[Issue] = field(default_factory=list)
    schema_issues: List[Issue] = field(default_factory=list)
    security_issues: List[Issue] = field(default_factory=list)
    code_integrity_issues: List[Issue] = field(default_factory=list)  # NEW
    import_issues: List[Issue] = field(default_factory=list)  # NEW
    dependency_issues: List[Issue] = field(default_factory=list)  # NEW
    coverage: CoverageReport = field(default_factory=CoverageReport)

    def has_critical_issues(self) -> bool:
        """Check if there are any CRITICAL issues (not ERROR or WARNING)."""
        all_issues = (self.api_issues + self.schema_issues + self.security_issues +
                     self.code_integrity_issues + self.import_issues + self.dependency_issues)
        return any(i.severity == "CRITICAL" for i in all_issues)

    def is_acceptable(self) -> bool:
        """Check if the project is acceptable for deployment."""
        return not self.has_critical_issues() and self.coverage.is_complete()


class ConsistencyVerifier:
    """
    Verifies generated code consistency and correctness.
    
    Performs static analysis on generated files to ensure they meet
    requirements and maintain internal consistency.
    """

    # Standard library modules that don't need validation
    STDLIB_MODULES = {
        'os', 'sys', 're', 'json', 'datetime', 'time', 'logging', 'typing',
        'pathlib', 'collections', 'dataclasses', 'functools', 'itertools',
        'asyncio', 'concurrent', 'contextlib', 'enum', 'abc', 'io', 'base64',
        'hashlib', 'hmac', 'secrets', 'uuid', 'copy', 'pickle', 'shutil',
    }

    def __init__(self, tech_config: Optional[TechStackConfig] = None):
        """Initialize consistency verifier."""
        self.tech_config = tech_config
        logger.info("ConsistencyVerifier initialized")

    def verify(self,
              project: AssembledProject,
              requirements: DetailedSpecification) -> VerificationReport:
        """
        Verify project consistency and requirements coverage.

        Args:
            project: Assembled project with generated files
            requirements: Original detailed requirements

        Returns:
            VerificationReport with all findings
        """
        logger.info("=" * 60)
        logger.info("CONSISTENCY VERIFICATION STARTED")
        logger.info("=" * 60)

        report = VerificationReport()

        # 1. Code Integrity Verification (NEW - CRITICAL)
        logger.info("Verifying code integrity (AST parsing)...")
        report.code_integrity_issues = self._verify_code_integrity(project)

        # 2. Import Resolution Verification (NEW - CRITICAL)
        logger.info("Verifying import resolution...")
        report.import_issues = self._verify_imports(project)

        # 3. Dependencies Verification (NEW - CRITICAL)
        logger.info("Verifying dependencies completeness...")
        report.dependency_issues = self._verify_dependencies(project)

        # 4. API Contract Verification
        logger.info("Verifying API contracts...")
        report.api_issues = self._verify_api_contracts(project, requirements)

        # 5. Database Schema Verification
        logger.info("Verifying database schema...")
        report.schema_issues = self._verify_schema_consistency(project, requirements)

        # 6. Security Verification
        logger.info("Verifying security implementation...")
        report.security_issues = self._verify_security(project, requirements)

        # 7. Requirements Coverage
        logger.info("Checking requirements coverage...")
        report.coverage = self._verify_requirements_coverage(project, requirements)

        self._log_verification_summary(report)

        logger.info("=" * 60)
        logger.info("CONSISTENCY VERIFICATION COMPLETE")
        logger.info("=" * 60)

        return report

    def _verify_code_integrity(self, project: AssembledProject) -> List[Issue]:
        """
        Verify code integrity using AST parsing.

        This catches:
        - Syntax errors
        - Incomplete code generation
        - Malformed Python files
        """
        issues = []

        for file in project.files:
            # Only check Python files
            if not str(file.path).endswith('.py'):
                continue

            try:
                # Attempt to parse the file as Python
                ast.parse(file.content)
            except SyntaxError as e:
                issues.append(Issue(
                    severity="CRITICAL",
                    location=str(file.path),
                    message=f"Syntax error at line {e.lineno}: {e.msg}",
                    component="Code Integrity"
                ))
            except Exception as e:
                issues.append(Issue(
                    severity="CRITICAL",
                    location=str(file.path),
                    message=f"Failed to parse file: {str(e)}",
                    component="Code Integrity"
                ))

        return issues

    def _verify_imports(self, project: AssembledProject) -> List[Issue]:
        """
        Verify that all imports can be resolved.

        This catches:
        - Missing modules that are imported
        - Incomplete code generation (missing files)
        - Incorrect import statements
        """
        issues = []

        # Build set of all available modules from generated files
        available_modules = set()
        for file in project.files:
            if str(file.path).endswith('.py'):
                # Convert file path to module path
                # e.g., "app/services/agent_service.py" -> "app.services.agent_service"
                module_path = str(file.path).replace('/', '.').replace('.py', '')
                available_modules.add(module_path)

                # Also add parent packages
                parts = module_path.split('.')
                for i in range(1, len(parts)):
                    available_modules.add('.'.join(parts[:i]))

        # Check each Python file's imports
        for file in project.files:
            if not str(file.path).endswith('.py'):
                continue

            try:
                tree = ast.parse(file.content)
                imports = self._extract_imports_from_ast(tree)

                for imp in imports:
                    if not self._is_import_resolvable(imp, available_modules):
                        issues.append(Issue(
                            severity="CRITICAL",
                            location=str(file.path),
                            message=f"Unresolvable import: {imp}",
                            component="Imports"
                        ))
            except Exception as e:
                # Already caught in code integrity check
                pass

        return issues

    def _extract_imports_from_ast(self, tree: ast.AST) -> List[str]:
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
                        if alias.name != '*':
                            imports.append(f"{node.module}.{alias.name}")

        return imports

    def _is_import_resolvable(self, import_path: str, available_modules: Set[str]) -> bool:
        """Check if an import can be resolved."""
        # Get base module (first part of import)
        base_module = import_path.split('.')[0]
        
        # Determine language from tech_config
        if self.tech_config:
            backend_lang = self.tech_config.backend_language
        else:
            backend_lang = "python"

        # Language-specific import resolution
        if backend_lang == "python":
            return self._is_python_import_resolvable(base_module, import_path, available_modules)
        elif backend_lang == "php":
            return self._is_php_import_resolvable(import_path, available_modules)
        elif backend_lang == "nodejs":
            return self._is_nodejs_import_resolvable(base_module, import_path, available_modules)
        
        return True  # Default to True for unknown languages
    
    def _is_python_import_resolvable(self, base_module: str, import_path: str, available_modules: Set[str]) -> bool:
        """Check if a Python import can be resolved."""
        # Check if it's stdlib
        if base_module in self.STDLIB_MODULES:
            return True

        # Check if it's a known third-party package
        third_party = {
            'fastapi', 'pydantic', 'sqlalchemy', 'jose', 'passlib',
            'uvicorn', 'httpx', 'redis', 'celery', 'alembic', 'jinja2',
            'requests', 'python', 'email_validator', 'sse_starlette',
            'psycopg2', 'asyncpg', 'dotenv', 'starlette'
        }
        if base_module in third_party:
            return True

        # Check if it's in generated modules
        if import_path in available_modules:
            return True

        # Check if it's a relative import within the app
        if import_path.startswith('app.'):
            return import_path in available_modules

        return False
    
    def _is_php_import_resolvable(self, import_path: str, available_modules: Set[str]) -> bool:
        """Check if a PHP use statement can be resolved."""
        # Common Laravel/PHP namespaces
        common_namespaces = {
            'Illuminate', 'App', 'Database', 'Illuminate\\Http',
            'Illuminate\\Support', 'Illuminate\\Database', 'Illuminate\\Foundation'
        }
        
        base_namespace = import_path.split('\\\\')[0]
        if base_namespace in common_namespaces:
            return True
        
        return import_path in available_modules
    
    def _is_nodejs_import_resolvable(self, base_module: str, import_path: str, available_modules: Set[str]) -> bool:
        """Check if a Node.js require/import can be resolved."""
        # Common Node.js built-in modules
        nodejs_builtins = {
            'fs', 'path', 'http', 'https', 'crypto', 'util', 'events',
            'stream', 'buffer', 'process', 'os', 'url', 'querystring'
        }
        
        if base_module in nodejs_builtins:
            return True
        
        # Common third-party packages
        third_party = {
            'express', 'sequelize', 'pg', 'dotenv', 'cors', 'helmet',
            'bcryptjs', 'jsonwebtoken', 'express-validator', 'joi'
        }
        
        if base_module in third_party:
            return True
        
        return import_path in available_modules

    def _verify_dependencies(self, project: AssembledProject) -> List[Issue]:
        """
        Verify that dependency file includes all necessary dependencies.

        This catches:
        - Missing dependency file
        - Missing packages in dependency file
        - Incomplete dependency list
        """
        issues = []
        
        # Determine expected dependency file based on tech stack
        if self.tech_config:
            dep_file_name = self.tech_config.get_dependency_file_name()
            backend_lang = self.tech_config.backend_language
        else:
            dep_file_name = "requirements.txt"
            backend_lang = "python"

        # For tech stacks with no dependencies, skip dependency verification
        if dep_file_name == "none":
            return issues

        # Find dependency file
        dep_file = None
        for file in project.files:
            if str(file.path) == dep_file_name or str(file.path).endswith(dep_file_name):
                dep_file = file
                break

        if not dep_file:
            issues.append(Issue(
                severity="CRITICAL",
                location="Project Root",
                message=f"{dep_file_name} not found in generated files",
                component="Dependencies"
            ))
            return issues

        # Verify dependencies based on backend language
        if backend_lang == "python":
            issues.extend(self._verify_python_dependencies(dep_file))
        elif backend_lang == "php":
            issues.extend(self._verify_php_dependencies(dep_file))
        elif backend_lang == "nodejs":
            issues.extend(self._verify_nodejs_dependencies(dep_file))

        return issues
    
    def _verify_python_dependencies(self, dep_file) -> List[Issue]:
        """Verify Python requirements.txt dependencies."""
        issues = []
        
        # Extract actual dependencies
        actual_deps = set()
        for line in dep_file.content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                # Extract package name (before any version specifier)
                pkg_name = re.split(r'[>=<\[]', line)[0].strip()
                actual_deps.add(pkg_name.lower())

        # Expected core dependencies for FastAPI projects
        expected_deps = {
            'fastapi', 'uvicorn', 'pydantic', 'sqlalchemy',
            'alembic', 'python-jose', 'passlib', 'python-multipart',
            'email-validator', 'python-dotenv'
        }

        # Check for missing dependencies
        missing = expected_deps - actual_deps
        for dep in missing:
            issues.append(Issue(
                severity="ERROR",  # ERROR not CRITICAL, as LLM might use alternatives
                location="requirements.txt",
                message=f"Expected dependency '{dep}' not found in requirements.txt",
                component="Dependencies"
            ))

        return issues
    
    def _verify_php_dependencies(self, dep_file) -> List[Issue]:
        """Verify PHP composer.json dependencies."""
        issues = []
        
        try:
            import json
            composer_data = json.loads(dep_file.content)
            
            # Check for Laravel framework
            require = composer_data.get('require', {})
            if 'laravel/framework' not in require:
                issues.append(Issue(
                    severity="WARNING",
                    location="composer.json",
                    message="Laravel framework not found in dependencies",
                    component="Dependencies"
                ))
        except json.JSONDecodeError:
            issues.append(Issue(
                severity="CRITICAL",
                location="composer.json",
                message="Invalid JSON in composer.json",
                component="Dependencies"
            ))
        
        return issues
    
    def _verify_nodejs_dependencies(self, dep_file) -> List[Issue]:
        """Verify Node.js package.json dependencies."""
        issues = []
        
        try:
            import json
            package_data = json.loads(dep_file.content)
            
            # Check for Express
            dependencies = package_data.get('dependencies', {})
            if 'express' not in dependencies:
                issues.append(Issue(
                    severity="WARNING",
                    location="package.json",
                    message="Express not found in dependencies",
                    component="Dependencies"
                ))
        except json.JSONDecodeError:
            issues.append(Issue(
                severity="CRITICAL",
                location="package.json",
                message="Invalid JSON in package.json",
                component="Dependencies"
            ))
        
        return issues

    def _verify_api_contracts(self,
                             project: AssembledProject,
                             requirements: DetailedSpecification) -> List[Issue]:
        """Verify API contracts between frontend and backend."""
        issues = []

        # Extract defined endpoints from backend code with router prefix detection
        defined_endpoints = set()
        router_prefixes = {}  # file_path -> prefix

        for file in project.files:
            if file.file_type == "api_endpoint":
                # Extract router prefix if defined
                prefix_match = re.search(r'router\s*=\s*APIRouter\s*\([^)]*prefix\s*=\s*["\']([^"\']+)["\']', file.content)
                file_prefix = prefix_match.group(1) if prefix_match else ""
                router_prefixes[file.path] = file_prefix

                # Find @router decorators
                pattern = r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
                matches = re.finditer(pattern, file.content)
                for match in matches:
                    method, path = match.groups()
                    # Combine prefix with path
                    full_path = file_prefix + path if not path.startswith('/') else file_prefix + path
                    # Normalize path (remove parameter brackets for matching)
                    norm_path = re.sub(r'\{[^}]+\}', '{}', full_path)
                    defined_endpoints.add(f"{method.upper()} {norm_path}")

        # Also check api.py for mounted routers with additional prefixes
        for file in project.files:
            if 'api.py' in str(file.path) or 'main.py' in str(file.path):
                # Look for router includes: api_router.include_router(chat.router, prefix="/chat")
                include_pattern = r'include_router\s*\([^,]+,\s*prefix\s*=\s*["\']([^"\']+)["\']'
                includes = re.finditer(include_pattern, file.content)
                for inc_match in includes:
                    mount_prefix = inc_match.group(1)
                    # Add this prefix to all endpoints (we'll create variations)
                    # This is a heuristic - we add common API prefixes
                    for endpoint in list(defined_endpoints):
                        method, path = endpoint.split(' ', 1)
                        if not path.startswith(mount_prefix):
                            defined_endpoints.add(f"{method} {mount_prefix}{path}")

        # Check if all required endpoints are implemented
        for endpoint in requirements.api_endpoints:
            norm_required = re.sub(r'\{[^}]+\}', '{}', endpoint.path)
            method = endpoint.method.upper()

            # Try multiple matching strategies
            found = False
            for defined in defined_endpoints:
                defined_method, defined_path = defined.split(' ', 1)

                # Strategy 1: Exact match
                if defined_method == method and defined_path == norm_required:
                    found = True
                    break

                # Strategy 2: Path ends with required (handles prefixes)
                if defined_method == method and defined_path.endswith(norm_required):
                    found = True
                    break

                # Strategy 3: Required ends with defined (handles missing /api prefix in requirement)
                if defined_method == method and norm_required.endswith(defined_path):
                    found = True
                    break

                # Strategy 4: Core path matching (strip /api, /v1, etc.)
                core_defined = re.sub(r'^/(api|v\d+)/', '/', defined_path)
                core_required = re.sub(r'^/(api|v\d+)/', '/', norm_required)
                if defined_method == method and core_defined == core_required:
                    found = True
                    break

            if not found:
                # Downgrade to WARNING instead of ERROR - LLM might have valid alternative routing
                issues.append(Issue(
                    severity="WARNING",
                    location="Backend API",
                    message=f"Expected endpoint {method} {endpoint.path} not found with standard patterns. Verify routing manually.",
                    component="API"
                ))

        return issues

    def _verify_schema_consistency(self, 
                                  project: AssembledProject, 
                                  requirements: DetailedSpecification) -> List[Issue]:
        """Verify database schema consistency."""
        issues = []
        
        # Check if all models are generated
        generated_models = set()
        for file in project.files:
            if file.file_type == "model":
                # Extract class name (Python and PHP support)
                # Python: class User(Base): or class User:
                # PHP: class User extends Model or class User
                # Use word boundary and start of line to avoid matching comments
                match = re.search(r'^\s*class\s+(\w+)', file.content, re.MULTILINE)
                if match:
                    generated_models.add(match.group(1))

        for model in requirements.data_models:
            if model.name not in generated_models:
                issues.append(Issue(
                    severity="CRITICAL",
                    location="Database Models",
                    message=f"Required data model {model.name} not found",
                    component="Database"
                ))

        return issues

    def _verify_security(self, 
                        project: AssembledProject, 
                        requirements: DetailedSpecification) -> List[Issue]:
        """Verify security implementation."""
        issues = []
        
        # Check for auth middleware/dependencies
        has_auth_check = False
        for file in project.files:
            # Python checks
            if "get_current_user" in file.content or "verify_token" in file.content:
                has_auth_check = True
                break
            # PHP checks (Laravel/Native)
            if "Auth::attempt" in file.content or "Auth::check" in file.content or "Session::put" in file.content or "session_start" in file.content:
                has_auth_check = True
                break
        
        if requirements.authentication and not has_auth_check:
            issues.append(Issue(
                severity="CRITICAL",
                location="Security",
                message="Authentication required but no auth checks found in code",
                component="Security"
            ))

        # Check for password hashing
        has_hashing = False
        for file in project.files:
            # Python checks
            if "CryptContext" in file.content or "bcrypt" in file.content:
                has_hashing = True
                break
            # PHP checks
            if "Hash::make" in file.content or "password_hash" in file.content or "Hash::check" in file.content:
                has_hashing = True
                break
                
        if requirements.authentication and not has_hashing:
            issues.append(Issue(
                severity="CRITICAL",
                location="Security",
                message="Password hashing not detected",
                component="Security"
            ))

        return issues

    def _verify_requirements_coverage(self, 
                                     project: AssembledProject, 
                                     requirements: DetailedSpecification) -> CoverageReport:
        """Check if all requirements are covered."""
        coverage = CoverageReport()
        
        # Check UI components
        # This is a heuristic check - looking for component names in templates/js
        all_code = "\n".join([f.content for f in project.files])
        
        for component in requirements.ui_components:
            # Check for component name or description keywords
            if component.name not in all_code and component.name.replace("_", "-") not in all_code:
                coverage.missing_components.append(component.name)

        return coverage

    def _log_verification_summary(self, report: VerificationReport):
        """Log summary of verification results."""
        logger.info(f"\n🔍 Verification Summary:")

        if report.has_critical_issues():
            logger.error("❌ CRITICAL ISSUES FOUND")
        else:
            logger.info("✅ No critical issues found")

        # NEW: Code Integrity Issues (HIGHEST PRIORITY)
        if report.code_integrity_issues:
            logger.error(f"  🔴 Code Integrity Issues: {len(report.code_integrity_issues)}")
            for i in report.code_integrity_issues:
                logger.error(f"    - [{i.severity}] {i.location}: {i.message}")

        # NEW: Import Issues (CRITICAL)
        if report.import_issues:
            logger.error(f"  🔴 Import Issues: {len(report.import_issues)}")
            for i in report.import_issues[:10]:  # Limit to first 10
                logger.error(f"    - [{i.severity}] {i.location}: {i.message}")
            if len(report.import_issues) > 10:
                logger.error(f"    ... and {len(report.import_issues) - 10} more")

        # NEW: Dependency Issues
        if report.dependency_issues:
            logger.warning(f"  ⚠️  Dependency Issues: {len(report.dependency_issues)}")
            for i in report.dependency_issues:
                logger.warning(f"    - [{i.severity}] {i.message}")

        if report.api_issues:
            logger.warning(f"  API Issues: {len(report.api_issues)}")
            for i in report.api_issues:
                logger.warning(f"    - [{i.severity}] {i.message}")

        if report.schema_issues:
            logger.warning(f"  Schema Issues: {len(report.schema_issues)}")
            for i in report.schema_issues:
                logger.warning(f"    - [{i.severity}] {i.message}")

        if report.security_issues:
            logger.warning(f"  Security Issues: {len(report.security_issues)}")
            for i in report.security_issues:
                logger.warning(f"    - [{i.severity}] {i.message}")

        if not report.coverage.is_complete():
            logger.warning("  Missing Coverage:")
            if report.coverage.missing_components:
                logger.warning(f"    - Components: {', '.join(report.coverage.missing_components)}")
