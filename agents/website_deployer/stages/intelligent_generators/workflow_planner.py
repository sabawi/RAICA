#!/usr/bin/env python3
"""
Workflow Planner - Stage 3 of Intelligent Code Generation
==========================================================

Creates dependency-aware generation workflow.

This stage:
1. Identifies all files to generate
2. Determines dependencies between files
3. Creates generation order (topological sort)
4. Prepares targeted prompts for each file
5. Groups related files for context sharing
"""

import logging
from typing import Dict, Any, List, Set, Optional
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

from .requirement_elaborator import DetailedSpecification
from .tech_stack_config import TechStackConfig
from ..dependency_resolver import DependencyResolver, DependencyGraph
from ..workflow_generator import WorkflowGenerator, Workflow
from ..intelligent_dependency_resolver import IntelligentDependencyResolver

logger = logging.getLogger(__name__)


@dataclass
class FileSpecification:
    """Specification for a single file to generate."""
    path: str
    file_type: str  # "model", "api_endpoint", "ui_template", "config", etc.
    description: str
    dependencies: List[str]  # List of file paths this depends on
    prompt: str  # Targeted prompt for generating this file
    context_files: List[str] = field(default_factory=list)  # Files to include as context
    priority: int = 0  # For ordering within a phase


@dataclass
class GenerationPhase:
    """A phase of file generation with related files."""
    name: str
    phase_number: int
    description: str
    files: List[FileSpecification]

    def get_file_count(self) -> int:
        """Get number of files in this phase."""
        return len(self.files)


@dataclass
class GenerationWorkflow:
    """Complete workflow for code generation."""
    project_name: str
    phases: List[GenerationPhase]
    total_files: int
    dependency_graph: Dict[str, List[str]]

    def get_all_files(self) -> List[FileSpecification]:
        """Get flat list of all file specifications."""
        all_files = []
        for phase in self.phases:
            all_files.extend(phase.files)
        return all_files


class WorkflowPlanner:
    """
    Plans code generation workflow with proper dependencies.

    Creates a dependency-aware plan for generating all files needed
    for the application, ensuring files are generated in the correct order.
    """

    def __init__(self, tech_config: Optional[TechStackConfig] = None):
        """Initialize workflow planner."""
        self.tech_config = tech_config
        self.dependency_resolver = DependencyResolver()
        self.workflow_generator = WorkflowGenerator()
        self.intelligent_resolver = IntelligentDependencyResolver()
        self.researched_dependencies = []  # Cache for researched dependencies
        self.security_patterns = {}  # Cache for security patterns
        logger.info("WorkflowPlanner initialized with enhanced dependency resolution and Agentic-RAG integration")

    def _research_dependencies_sync(self, spec: DetailedSpecification):
        """
        Synchronous wrapper for async dependency research using Agentic-RAG.

        Queries the parent server's Agentic-RAG model to get:
        - Latest dependencies with versions
        - Security implementation patterns
        - Best practices for the tech stack
        """
        import asyncio

        logger.info("🔬 Researching dependencies via parent Agentic-RAG model...")

        # Extract features from spec
        features = []
        if spec.authentication:
            features.append("authentication")
            if spec.authentication.get('email_verification'):
                features.append("email_verification")
            if spec.authentication.get('method') == 'jwt':
                features.append("jwt_auth")

        if spec.data_models:
            features.append("database_orm")
            features.append("async_operations")

        if spec.api_endpoints:
            features.append("rest_api")

        # Run async research
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            self.intelligent_resolver.research_dependencies(
                tech_stack=self.tech_config.backend_language,
                framework=self.tech_config.backend_framework,
                features=features,
                database=spec.database_type
            )
        )

        if result.success:
            self.researched_dependencies = result.dependencies
            self.security_patterns = result.security_patterns
            logger.info(f"✅ Successfully researched {len(self.researched_dependencies)} dependencies")
            logger.info(f"✅ Extracted {len(self.security_patterns)} security patterns")
        else:
            logger.warning(f"⚠️ Dependency research failed: {result.error}")
            logger.warning("   Using static fallback prompts")

    def plan(self, spec: DetailedSpecification) -> GenerationWorkflow:
        """
        Create generation workflow from detailed specification.

        Args:
            spec: DetailedSpecification with all technical details

        Returns:
            GenerationWorkflow with phased generation plan
        """
        logger.info("=" * 60)
        logger.info("WORKFLOW PLANNING STARTED")
        logger.info("=" * 60)

        # Ensure tech config is available
        if not self.tech_config:
            self.tech_config = spec.get_tech_config()
            logger.info(f"Using tech config: {self.tech_config.tech_key}")

        # NEW: Research dependencies using Agentic-RAG BEFORE generating prompts
        self._research_dependencies_sync(spec)

        # Step 1: Identify all files needed
        logger.info("Identifying all files to generate...")
        file_specs = self._identify_all_files(spec)
        logger.info(f"  → {len(file_specs)} files identified")

        # Step 2: Build dependency graph
        logger.info("Building dependency graph...")
        dep_graph = self._build_dependency_graph(file_specs)
        self._log_dependency_summary(dep_graph)

        # Step 3: Topological sort into phases
        logger.info("Creating generation phases...")
        phases = self._create_phases(file_specs, dep_graph)
        logger.info(f"  → {len(phases)} phases created")

        # Step 4: Create workflow
        workflow = GenerationWorkflow(
            project_name=spec.project_name,
            phases=phases,
            total_files=len(file_specs),
            dependency_graph=dep_graph
        )

        self._log_workflow_summary(workflow)

        logger.info("=" * 60)
        logger.info("WORKFLOW PLANNING COMPLETE")
        logger.info("=" * 60)

        return workflow

    def _identify_all_files(self, spec: DetailedSpecification) -> Dict[str, FileSpecification]:
        """Identify all files that need to be generated."""
        files = {}
        ext = self.tech_config.get_file_extension()
        
        # Helper to get paths
        config_dir = self.tech_config.get_config_dir()
        models_dir = self.tech_config.get_models_dir()
        schemas_dir = self.tech_config.get_schemas_dir()
        crud_dir = self.tech_config.get_crud_dir()
        controllers_dir = self.tech_config.get_controllers_dir()
        templates_dir = self.tech_config.get_templates_dir()
        static_dir = self.tech_config.get_static_dir()

        # Phase 1: Foundation files
        # Add __init__.py files only for Python
        if self.tech_config.backend_language == 'python':
            init_paths = [
                "app/__init__.py", 
                f"{config_dir}/__init__.py",
                f"{models_dir}/__init__.py",
                f"{schemas_dir}/__init__.py",
                f"{crud_dir}/__init__.py",
                f"{controllers_dir}/__init__.py"
            ]
            for path in init_paths:
                files[path] = FileSpecification(
                    path=path,
                    file_type="init",
                    description=f"Package initialization for {path}",
                    dependencies=[],
                    prompt=f"Generate empty __init__.py for {path}"
                )

        # Dependency file with Agentic-RAG researched dependencies
        dep_file = self.tech_config.get_dependency_file_name()
        if dep_file != "none":
            files[dep_file] = FileSpecification(
                path=dep_file,
                file_type="dependency",
                description=f"Project dependencies ({dep_file})",
                dependencies=[],
                prompt=self._create_dependency_file_prompt(dep_file, spec)
            )
        else:
            logger.debug("Skipping dependency file - tech stack has no dependencies")

        # Config file
        config_file = f"{config_dir}/config{ext}"
        files[config_file] = FileSpecification(
            path=config_file,
            file_type="config",
            description="Application configuration",
            dependencies=[],
            prompt=self._create_config_prompt(spec)
        )

        # Phase 2: Database models
        logger.info(f"🔍 DEBUG: Creating file specs for {len(spec.data_models)} data models")
        for model in spec.data_models:
            model_path = f"{models_dir}/{model.name.lower()}{ext}"
            logger.info(f"🔍 DEBUG: Creating model file spec: {model_path} (type: {model.name})")
            deps = []
            if self.tech_config.backend_language == 'python':
                deps.append(f"{models_dir}/__init__.py")

            files[model_path] = FileSpecification(
                path=model_path,
                file_type="model",
                description=f"{model.name} database model",
                dependencies=deps,
                prompt=self._create_model_prompt(model, spec)
            )
            logger.info(f"✅ DEBUG: Added model file spec: {model_path}")

        # Phase 3: Schemas / Validators
        # Group schemas by API endpoint prefix
        schema_groups = self._group_schemas_by_endpoint(spec.api_endpoints)
        for group_name, endpoints in schema_groups.items():
            schema_path = f"{schemas_dir}/{group_name}{ext}"
            model_deps = [f"{models_dir}/{model.name.lower()}{ext}" for model in spec.data_models]
            
            files[schema_path] = FileSpecification(
                path=schema_path,
                file_type="schema",
                description=f"Schemas/Validators for {group_name}",
                dependencies=model_deps,
                prompt=self._create_schema_prompt(group_name, endpoints, spec)
            )

        # Phase 4: CRUD / Services
        for model in spec.data_models:
            crud_path = f"{crud_dir}/{model.name.lower()}{ext}"
            schema_group = self._get_schema_group_for_model(model, schema_groups)

            deps = [f"{models_dir}/{model.name.lower()}{ext}"]
            # Only add schema dependency if the schema group actually exists
            if schema_group and schema_group in schema_groups:
                deps.append(f"{schemas_dir}/{schema_group}{ext}")

            files[crud_path] = FileSpecification(
                path=crud_path,
                file_type="crud",
                description=f"CRUD/Service operations for {model.name}",
                dependencies=deps,
                prompt=self._create_crud_prompt(model, spec)
            )

        # Phase 5: API endpoints / Controllers
        endpoint_groups = self._group_endpoints(spec.api_endpoints)
        for group_name, endpoints in endpoint_groups.items():
            endpoint_path = f"{controllers_dir}/{group_name}{ext}"
            deps = [config_file]

            # Add schema dependency only if it was created
            schema_path = f"{schemas_dir}/{group_name}{ext}"
            if schema_path in files:
                deps.append(schema_path)

            # Add CRUD dependencies
            for model in spec.data_models:
                if model.name.lower() in group_name or group_name in model.name.lower():
                    deps.append(f"{crud_dir}/{model.name.lower()}{ext}")

            files[endpoint_path] = FileSpecification(
                path=endpoint_path,
                file_type="api_endpoint",
                description=f"API endpoints/Controller for {group_name}",
                dependencies=deps,
                prompt=self._create_endpoint_prompt(group_name, endpoints, spec),
                context_files=deps
            )

        # API router / Main Router
        # For Python/FastAPI it's app/api/api.py, for others it might be routes/api.php or routes/index.js
        if self.tech_config.backend_language == 'python':
            router_path = f"app/api/api{ext}"
        elif self.tech_config.backend_language == 'php':
            router_path = f"routes/api{ext}"
        else:
            router_path = f"routes/index{ext}"
            
        files[router_path] = FileSpecification(
            path=router_path,
            file_type="api_router",
            description="Main API router",
            dependencies=[f"{controllers_dir}/{g}{ext}" for g in endpoint_groups.keys()],
            prompt=self._create_api_router_prompt(endpoint_groups)
        )

        # Phase 6: Authentication/Security
        if spec.authentication:
            security_path = f"{config_dir}/security{ext}"
            files[security_path] = FileSpecification(
                path=security_path,
                file_type="security",
                description="Authentication and security utilities",
                dependencies=[config_file],
                prompt=self._create_security_prompt(spec)
            )

        # Phase 7: Frontend templates
        base_template = f"{templates_dir}/base.html"
        files[base_template] = FileSpecification(
            path=base_template,
            file_type="template",
            description="Base HTML template",
            dependencies=[],
            prompt=self._create_base_template_prompt(spec)
        )

        for layout in spec.page_layouts:
            template_path = f"{templates_dir}/{layout['template_file']}"
            files[template_path] = FileSpecification(
                path=template_path,
                file_type="template",
                description=f"Template for {layout['name']}",
                dependencies=[base_template],
                prompt=self._create_page_template_prompt(layout, spec),
                context_files=[base_template]
            )

        # Frontend JavaScript
        js_path = f"{static_dir}/js/main.js"
        files[js_path] = FileSpecification(
            path=js_path,
            file_type="javascript",
            description="Main JavaScript file",
            dependencies=[],
            prompt=self._create_javascript_prompt(spec)
        )

        # Phase 8: Main application entry point
        entry_point = self.tech_config.config.get('entry_point', f'main{ext}')
        files[entry_point] = FileSpecification(
            path=entry_point,
            file_type="main",
            description="Application entry point",
            dependencies=[
                config_file,
                router_path
            ],
            prompt=self._create_main_app_prompt(spec)
        )

        # Phase 9: Background workers (if any)
        if spec.background_workers:
            workers_dir = self.tech_config.get_path('workers')
            if self.tech_config.backend_language == 'python':
                files[f"{workers_dir}/__init__.py"] = FileSpecification(
                    path=f"{workers_dir}/__init__.py",
                    file_type="init",
                    description="Workers package",
                    dependencies=[],
                    prompt="Generate empty __init__.py"
                )

            celery_app = f"{workers_dir}/celery_app{ext}"
            files[celery_app] = FileSpecification(
                path=celery_app,
                file_type="worker",
                description="Celery/Worker application",
                dependencies=[config_file],
                prompt=self._create_celery_app_prompt(spec)
            )

            for worker in spec.background_workers:
                worker_name = worker.get('name', 'unknown_worker')
                worker_path = f"{workers_dir}/{worker_name}{ext}"
                files[worker_path] = FileSpecification(
                    path=worker_path,
                    file_type="worker",
                    description=f"Worker task: {worker_name}",
                    dependencies=[celery_app],
                    prompt=self._create_worker_prompt(worker, spec)
                )

        return files

    def _build_dependency_graph(self, file_specs: Dict[str, FileSpecification]) -> Dict[str, List[str]]:
        """
        Build dependency graph from file specifications using enhanced DependencyResolver.

        Returns:
            Dict mapping file paths to their dependencies
        """
        # Reset dependency resolver for this build
        self.dependency_resolver = DependencyResolver()

        # Add all files to dependency resolver
        for path, spec in file_specs.items():
            # Determine phase based on file type
            phase_map = {
                'init': 1,
                'dependency': 1,
                'config': 1,
                'model': 2,
                'schema': 3,
                'crud': 4,
                'security': 4,
                'api_endpoint': 5,
                'api_router': 5,
                'template': 6,
                'javascript': 6,
                'main': 7,
                'worker': 8
            }
            phase = phase_map.get(spec.file_type, 5)

            self.dependency_resolver.add_file(
                path=path,
                depends_on=spec.dependencies,
                file_type=spec.file_type,
                priority=spec.priority,
                phase=phase
            )

        # Build the dependency graph with cycle detection
        dep_graph_obj = self.dependency_resolver.build_graph()

        # Check for cycles
        if dep_graph_obj.has_cycles:
            logger.error("=" * 60)
            logger.error("CIRCULAR DEPENDENCIES DETECTED!")
            logger.error("=" * 60)
            for cycle in dep_graph_obj.cycle_details:
                logger.error(f"Cycle: {' -> '.join(cycle)}")
            raise ValueError(f"Circular dependencies detected in {len(dep_graph_obj.cycle_details)} locations")

        # Check for missing dependencies
        if dep_graph_obj.missing_dependencies:
            logger.warning("Missing dependencies detected:")
            for file_path, missing_deps in dep_graph_obj.missing_dependencies.items():
                logger.warning(f"  {file_path} requires: {', '.join(missing_deps)}")

        # Return the dependency graph in the expected format
        graph = {}
        for path, file_dep in dep_graph_obj.files.items():
            graph[path] = file_dep.depends_on

        return graph

    def _create_phases(self,
                      file_specs: Dict[str, FileSpecification],
                      dep_graph: Dict[str, List[str]]) -> List[GenerationPhase]:
        """
        Create generation phases using enhanced topological sort.

        Uses the DependencyResolver's topological sort which respects
        both dependencies and phase assignments for optimal generation order.
        """
        # Get the dependency graph object from resolver (already built)
        dep_graph_obj = self.dependency_resolver.build_graph()

        # Use the generation_order from the dependency resolver
        # This order respects both dependencies and phases
        generation_order = dep_graph_obj.generation_order

        # Group files by their assigned phase
        phase_groups = {}
        logger.info(f"🔍 DEBUG: Grouping {len(generation_order)} files by phase")
        for file_path in generation_order:
            if file_path in file_specs:
                file_dep = dep_graph_obj.files[file_path]
                phase_num = file_dep.generates_in_phase
                logger.debug(f"🔍 DEBUG: File {file_path} -> Phase {phase_num} (type: {file_specs[file_path].file_type})")
                if phase_num not in phase_groups:
                    phase_groups[phase_num] = []
                phase_groups[phase_num].append(file_path)
            else:
                logger.warning(f"⚠️  DEBUG: File {file_path} in generation_order but NOT in file_specs!")

        logger.info(f"🔍 DEBUG: Phase groups created: {sorted(phase_groups.keys())}")
        for phase_num in sorted(phase_groups.keys()):
            logger.info(f"🔍 DEBUG: Phase {phase_num} has {len(phase_groups[phase_num])} files")

        # Create GenerationPhase objects
        phases = []
        phase_descriptions = {
            1: "Foundation - Configuration and base setup",
            2: "Data Models - Database models and relationships",
            3: "Schemas - Pydantic request/response schemas",
            4: "CRUD - Database operations and security",
            5: "API Endpoints - REST API implementation",
            6: "Frontend - Templates and JavaScript",
            7: "Main Application - Entry point",
            8: "Background Workers - Async tasks"
        }

        for phase_num in sorted(phase_groups.keys()):
            file_paths = phase_groups[phase_num]
            phase_files = [file_specs[path] for path in file_paths]
            if phase_files:
                phase = GenerationPhase(
                    name=f"Phase {phase_num}",
                    phase_number=phase_num,
                    description=phase_descriptions.get(phase_num, f"Generation phase {phase_num}"),
                    files=phase_files
                )
                phases.append(phase)

        logger.info(f"Created {len(phases)} phases with enhanced dependency resolution:")
        for phase in phases:
            logger.info(f"  Phase {phase.phase_number}: {phase.description} ({len(phase.files)} files)")

        return phases

    def _topological_sort_levels(self,
                                 file_specs: Dict[str, FileSpecification],
                                 dep_graph: Dict[str, List[str]]) -> List[List[str]]:
        """Topological sort that groups files into levels."""

        # Calculate in-degrees
        in_degree = {path: 0 for path in file_specs}
        for path, deps in dep_graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[path] += 1

        levels = []
        processed = set()

        while len(processed) < len(file_specs):
            # Find all files with in-degree 0 (no unprocessed dependencies)
            current_level = []
            for path in file_specs:
                if path not in processed:
                    deps_satisfied = all(dep in processed or dep not in file_specs
                                       for dep in dep_graph[path])
                    if deps_satisfied:
                        current_level.append(path)

            if not current_level:
                # Handle circular dependencies or missing deps
                remaining = [p for p in file_specs if p not in processed]
                logger.warning(f"Circular dependency detected. Remaining files: {remaining}")
                current_level = remaining

            levels.append(current_level)
            processed.update(current_level)

        return levels

    def _group_endpoints(self, endpoints: List) -> Dict[str, List]:
        """Group API endpoints by prefix."""
        import os
        groups = defaultdict(list)
        for endpoint in endpoints:
            parts = endpoint.path.split("/")
            if len(parts) >= 3:
                # Strip file extension from group name (e.g., "login.php" → "login")
                # This prevents issues when LLM generates paths like "/api/login.php"
                group_name = os.path.splitext(parts[2])[0]
            else:
                group_name = "main"
            groups[group_name].append(endpoint)
        return dict(groups)

    def _group_schemas_by_endpoint(self, endpoints: List) -> Dict[str, List]:
        """Group schemas by endpoint prefix."""
        return self._group_endpoints(endpoints)

    def _get_schema_group_for_model(self, model, schema_groups: Dict[str, List]) -> str:
        """Find schema group name for a model."""
        model_name_lower = model.name.lower()
        for group_name in schema_groups:
            if model_name_lower in group_name or group_name in model_name_lower:
                return group_name
        return "main"

    # Prompt creation methods
    def _create_dependency_file_prompt(self, dep_file: str, spec: DetailedSpecification) -> str:
        """
        Create prompt for dependency file generation with researched dependencies injected.

        If Agentic-RAG research succeeded, inject researched dependencies.
        Otherwise, use generic prompt and let LLM guess (old behavior).
        """
        if self.researched_dependencies:
            # SUCCESS: Inject researched dependencies from Agentic-RAG
            deps_str = "\n".join(self.researched_dependencies)
            return f"""Generate {dep_file} for {self.tech_config.get_tech_stack_description()}.

REQUIRED DEPENDENCIES (researched via parent Agentic-RAG model with tool calling):
{deps_str}

CRITICAL INSTRUCTIONS:
- Include ALL dependencies listed above with their exact versions
- Do NOT add extra dependencies not listed
- Do NOT modify version numbers
- These dependencies were researched using web search and documentation lookup
- Format correctly for {dep_file} file format

Output ONLY the file contents, no explanations.
"""
        else:
            # FALLBACK: No research available, use generic prompt
            logger.warning(f"⚠️ No researched dependencies available for {dep_file}, using generic prompt")
            return f"""Generate {dep_file} for {self.tech_config.get_tech_stack_description()}.

Include all necessary dependencies for:
- {self.tech_config.backend_framework} framework
- Database ORM
- Authentication (JWT)
- Email operations
- Password hashing
- Async operations

Use latest stable versions as of 2024.
"""

    def _create_config_prompt(self, spec: DetailedSpecification) -> str:
        """Create prompt for config file generation."""
        template = self.tech_config.get_prompt_template('config_prompt')
        if template:
            return template.format(
                project_name=spec.project_name,
                database_type=spec.database_type
            )
        # Fallback if template not found
        return f"""Generate configuration file for {spec.project_name}.
Database: {spec.database_type}
"""

    def _create_model_prompt(self, model, spec: DetailedSpecification) -> str:
        """
        Create prompt for model generation.

        Enhances User model with email verification fields if authentication
        with email verification is enabled.
        """
        fields_str = "\n".join([f"  - {f['name']}: {f['type']}" for f in model.fields])

        # Check if this is User model and email verification is required
        email_verification_enabled = spec.authentication.get('email_verification', False)
        is_user_model = model.name.lower() in ['user', 'users', 'account']

        # Add email verification field requirement for User model
        email_verification_note = ""
        if is_user_model and email_verification_enabled:
            # Check if email_verified field already exists
            has_email_verified = any(f['name'] == 'email_verified' for f in model.fields)
            if not has_email_verified:
                fields_str += "\n  - email_verified: Boolean (default: false)"
                email_verification_note = """

CRITICAL: Email Verification Integration
- This User model MUST include 'email_verified' boolean field (default: false)
- New users start with email_verified=false
- Login workflow will check this field before allowing access
- Email verification endpoint will set this to true upon successful verification
"""

        # Make relationship string generation more robust
        rel_items = []
        for r in model.relationships:
            if isinstance(r, dict):
                # Handle different possible dictionary structures
                target_model = r.get('model') or r.get('target_model') or r.get('name', 'Unknown')
                rel_type = r.get('type') or r.get('relationship_type') or 'unknown'
                rel_items.append(f"  - {target_model} ({rel_type})")
            else:
                # Handle string relationships if any
                rel_items.append(f"  - {r}")
        rels_str = "\n".join(rel_items)

        # Handle indexes (can be strings or dicts)
        indexes_str = 'None'
        if model.indexes:
            index_items = []
            for idx in model.indexes:
                if isinstance(idx, dict):
                    # Index is a dict like {"fields": ["email"], "unique": true}
                    fields = idx.get('fields', [])
                    unique = idx.get('unique', False)
                    idx_str = f"{'UNIQUE ' if unique else ''}INDEX({', '.join(fields)})"
                    index_items.append(idx_str)
                else:
                    # Index is a simple string
                    index_items.append(str(idx))
            indexes_str = ', '.join(index_items)

        template = self.tech_config.get_prompt_template('model_prompt')
        if template:
            return template.format(
                model_name=model.name,
                table_name=model.table_name,
                fields=fields_str,
                relationships=rels_str,
                indexes=indexes_str
            ) + email_verification_note

        # Fallback
        return f"""Generate database model: {model.name}
Fields: {fields_str}
Relationships: {rels_str}
{email_verification_note}
"""

    def _create_schema_prompt(self, group_name: str, endpoints: List, spec: DetailedSpecification) -> str:
        """Create prompt for schemas/validators."""
        endpoints_desc = "\n".join([f"- {ep.method} {ep.path}: {ep.description}" for ep in endpoints])
        
        template = self.tech_config.get_prompt_template('schema_prompt')
        if template:
            return template.format(
                group_name=group_name,
                endpoints=endpoints_desc
            )
        # Fallback
        return f"""Generate validation schemas for {group_name}.
Endpoints: {endpoints_desc}
"""

    def _create_crud_prompt(self, model, spec: DetailedSpecification) -> str:
        """Create prompt for CRUD/Service operations."""
        template = self.tech_config.get_prompt_template('crud_prompt')
        if template:
            return template.format(
                model_name=model.name,
                model_name_lower=model.name.lower()
            )
        # Fallback
        return f"""Generate CRUD operations for {model.name} model.
"""

    def _create_endpoint_prompt(self, group_name: str, endpoints: List, spec: DetailedSpecification) -> str:
        """Create prompt for API endpoints/controllers."""
        endpoints_detail = []
        for ep in endpoints:
            ep_detail = f"""
{ep.method} {ep.path}
Description: {ep.description}
Auth Required: {ep.auth_required}
Request: {ep.request_body}
Response: {ep.response}
"""
            endpoints_detail.append(ep_detail)
        
        template = self.tech_config.get_prompt_template('api_endpoint_prompt')
        if template:
            return template.format(
                group_name=group_name,
                endpoints="".join(endpoints_detail)
            )
        # Fallback
        return f"""Generate API endpoints for {group_name}.
Endpoints: {"".join(endpoints_detail)}
"""

    def _create_api_router_prompt(self, endpoint_groups: Dict[str, List]) -> str:
        """Create prompt for main API router."""
        groups_str = "\n".join([f"- {group}" for group in endpoint_groups.keys()])
        
        template = self.tech_config.get_prompt_template('api_router_prompt')
        if template:
            return template.format(groups=groups_str)
        # Fallback
        return f"""Generate main API router.
Include routers from: {groups_str}
"""

    def _create_security_prompt(self, spec: DetailedSpecification) -> str:
        """
        Create prompt for security utilities using workflow-based approach.

        If email verification is enabled, includes complete workflow integration.
        Enhanced with Agentic-RAG researched security patterns.
        """
        auth_method = spec.authentication.get('method', 'JWT')
        token_expiry = spec.authentication.get('token_expiry', '30 minutes')
        email_verification_enabled = spec.authentication.get('email_verification', False)

        base_prompt = f"""Generate authentication and security utilities.

Method: {auth_method}
Token Expiry: {token_expiry}

Functions needed:
- create_access_token(data: dict) -> str
- verify_token(token: str) -> dict
- get_current_user(token: str) -> User
- hash_password(password: str) -> str
- verify_password(plain: str, hashed: str) -> bool

Use python-jose for JWT, passlib for password hashing.
"""

        # Inject researched security patterns if available
        if self.security_patterns:
            logger.info(f"✅ Injecting {len(self.security_patterns)} security patterns into security prompt")
            patterns_prompt = "\n\nSECURITY IMPLEMENTATION PATTERNS (from Agentic-RAG research):\n"

            for pattern_name, pattern_code in self.security_patterns.items():
                patterns_prompt += f"\n{pattern_name.upper()} PATTERN:\n```\n{pattern_code}\n```\n"

            patterns_prompt += """
CRITICAL: Use the patterns above for security implementations.
These were researched using web search and official documentation.
"""
            base_prompt += patterns_prompt

        # Add email verification workflow if enabled
        if email_verification_enabled:
            # Generate comprehensive registration workflow
            reg_workflow = self.workflow_generator.generate_registration_workflow(with_email_verification=True)
            login_workflow = self.workflow_generator.generate_login_workflow(require_email_verification=True)

            workflow_prompt = f"""

CRITICAL - EMAIL VERIFICATION WORKFLOW:
This application requires email verification. Follow this exact workflow:

REGISTRATION WORKFLOW ({reg_workflow.name}):
Trigger: {reg_workflow.trigger}

"""
            for step in reg_workflow.steps:
                workflow_prompt += f"""
Step {step.step_number}: {step.action}
  Description: {step.description}
  Files: {', '.join(step.files_involved)}
  Database: {', '.join(step.database_operations) if step.database_operations else 'None'}
  Validation: {', '.join(step.validation_required) if step.validation_required else 'None'}
"""

            workflow_prompt += f"""

LOGIN WORKFLOW ({login_workflow.name}):
Trigger: {login_workflow.trigger}

"""
            for step in login_workflow.steps:
                workflow_prompt += f"""
Step {step.step_number}: {step.action}
  Description: {step.description}
  Database: {', '.join(step.database_operations) if step.database_operations else 'None'}
"""

            workflow_prompt += """

INTEGRATION REQUIREMENTS:
- User model MUST have 'email_verified' boolean field (default: false)
- Database MUST have 'email_verification_tokens' table
- Login MUST check email_verified status before allowing access
- Registration MUST send verification email with token
- Include verify_email(token: str) function to handle email verification

SECURITY REQUIREMENTS:
- Tokens must expire after 24 hours
- Use cryptographically secure random token generation
- Verify token hasn't expired before accepting verification
- Delete token after successful verification
"""

            return base_prompt + workflow_prompt

        return base_prompt

    def _create_base_template_prompt(self, spec: DetailedSpecification) -> str:
        """Create prompt for base HTML template."""
        return f"""Generate base HTML template with Alpine.js and Tailwind CSS.

Include:
- <!DOCTYPE html> with proper meta tags
- Tailwind CSS CDN
- Alpine.js CDN
- Navigation bar with app name: {spec.project_name}
- Content block for child templates
- Responsive design
"""

    def _create_page_template_prompt(self, layout: Dict[str, Any], spec: DetailedSpecification) -> str:
        """Create prompt for page template."""
        layout_type = layout.get('layout_type', 'single')
        columns = layout.get('columns', {})

        components_by_area = {}
        for area, config in columns.items():
            components_by_area[area] = config.get('components', [])

        # Find UI component specs for each area
        component_details = {}
        for area, comp_names in components_by_area.items():
            component_details[area] = []
            for comp_name in comp_names:
                for ui_comp in spec.ui_components:
                    if ui_comp.name == comp_name:
                        component_details[area].append(ui_comp)

        # Build detailed prompt
        prompt = f"""Generate HTML template: {layout['name']} ({layout['template_file']})

Layout: {layout_type}

"""
        for area, comps in component_details.items():
            if comps:
                prompt += f"\n{area.upper()} AREA:\n"
                for comp in comps:
                    prompt += f"""
Component: {comp.name}
Type: {comp.type}
Description: {comp.description}
HTML Structure: {comp.html_structure}
Frontend Logic: {comp.frontend_logic}
Frontend Methods: {comp.frontend_methods}
Styling Classes: {comp.styling_classes}
API Interactions: {comp.api_interactions}
"""

        prompt += """
Generate complete HTML template extending base.html with all components properly implemented.
Use appropriate frontend framework and styling as specified in the component details.
"""
        return prompt

    def _create_javascript_prompt(self, spec: DetailedSpecification) -> str:
        """Create prompt for main JavaScript file."""
        return f"""Generate main JavaScript file with frontend framework components.

Project: {spec.project_name}
Frontend Framework: {spec.frontend_framework}
State Management: {spec.state_management}

UI Components to implement:
{chr(10).join([f"- {comp.name}: {', '.join(comp.frontend_methods)}" for comp in spec.ui_components])}

Include:
- State management definitions for global state (appropriate for {spec.frontend_framework})
- Component methods for API interactions
- Error handling
- Loading states
"""

    def _create_main_app_prompt(self, spec: DetailedSpecification) -> str:
        """Create prompt for main application entry point."""
        template = self.tech_config.get_prompt_template('main_app_prompt')
        if template:
            return template.format(
                project_name=spec.project_name,
                description=spec.description
            )
        # Fallback
        return f"""Generate application entry point for {spec.project_name}.
Description: {spec.description}
"""

    def _create_celery_app_prompt(self, spec: DetailedSpecification) -> str:
        """Create prompt for Celery app."""
        return """Generate Celery application (app/workers/celery_app.py).

Include:
- Celery instance with Redis broker
- Task configurations
- Result backend setup
"""

    def _create_worker_prompt(self, worker: Dict[str, Any], spec: DetailedSpecification) -> str:
        """Create prompt for background worker."""
        name = worker.get('name', 'unknown_worker')
        description = worker.get('description', 'Background worker task')
        trigger = worker.get('trigger', 'manual')
        schedule = worker.get('schedule', '')
        priority = worker.get('priority', 'medium')
        parameters = worker.get('parameters', [])

        prompt = f"""Generate Celery task: {name}

Description: {description}
Trigger: {trigger}"""

        if schedule:
            prompt += f"\nSchedule: {schedule}"

        prompt += f"""
Priority: {priority}
Parameters: {parameters}

Create Celery task with proper error handling and retry logic.
"""
        return prompt

    def _log_dependency_summary(self, dep_graph: Dict[str, List[str]]):
        """Log dependency graph summary."""
        files_with_deps = sum(1 for deps in dep_graph.values() if deps)
        logger.info(f"  → {files_with_deps} files have dependencies")

    def _log_workflow_summary(self, workflow: GenerationWorkflow):
        """Log workflow summary."""
        logger.info(f"\n📋 Workflow Summary:")
        logger.info(f"  Project: {workflow.project_name}")
        logger.info(f"  Total Files: {workflow.total_files}")
        logger.info(f"  Phases: {len(workflow.phases)}")

        for phase in workflow.phases:
            logger.info(f"\n  {phase.name}: {phase.description}")
            logger.info(f"    Files: {phase.get_file_count()}")
            for file_spec in phase.files[:3]:  # Show first 3
                logger.info(f"      - {file_spec.path}")
            if phase.get_file_count() > 3:
                logger.info(f"      ... and {phase.get_file_count() - 3} more")
