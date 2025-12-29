#!/usr/bin/env python3
"""
Requirement Elaborator - Stage 2 of Intelligent Code Generation
================================================================

Expands requirements into detailed technical specifications.

This stage:
1. Takes analyzed prompt with clarifications
2. Expands component descriptions into technical specs
3. Defines data models and API contracts
4. Specifies state management strategy
5. Details authentication and authorization flows
6. Creates component interaction diagrams
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..llm_client import LLMClient
from .prompt_analyzer import PromptAnalysis
from .tech_stack_config import TechStackConfig

logger = logging.getLogger(__name__)


@dataclass
class APIEndpoint:
    """Detailed API endpoint specification."""
    method: str
    path: str
    description: str
    request_body: Optional[Dict[str, Any]] = None
    query_params: Optional[List[Dict[str, Any]]] = None
    response: Optional[Dict[str, Any]] = None
    auth_required: bool = True
    rate_limit: Optional[str] = None


@dataclass
class UIComponentSpec:
    """Detailed UI component specification."""
    name: str
    type: str  # "layout", "interactive", "display"
    description: str
    html_structure: str
    frontend_logic: Dict[str, Any]  # Framework-specific data/state (Alpine.js data, React state, Vue data, vanilla JS, etc.)
    frontend_methods: List[str]  # Framework-specific methods/functions
    styling_classes: List[str]  # CSS framework classes (Tailwind, Bootstrap, custom CSS, etc.)
    api_interactions: List[str]
    child_components: List[str] = field(default_factory=list)


@dataclass
class DataModel:
    """Database model specification."""
    name: str
    table_name: str
    fields: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    indexes: List[str] = field(default_factory=list)


@dataclass
class DataFlow:
    """Data flow specification."""
    name: str
    steps: List[Dict[str, str]]
    error_handling: List[str]


@dataclass
class DetailedSpecification:
    """Complete detailed technical specification."""
    project_name: str
    project_type: str
    description: str

    # Frontend specifications
    ui_components: List[UIComponentSpec]
    page_layouts: List[Dict[str, Any]]
    frontend_framework: str
    state_management: Dict[str, Any]

    # Backend specifications
    backend_language: str  # e.g., "python", "php", "nodejs", "ruby", "java"
    backend_framework: str  # e.g., "flask", "fastapi", "laravel", "express", "rails"
    api_endpoints: List[APIEndpoint]
    data_models: List[DataModel]
    authentication: Dict[str, Any]
    authorization: Dict[str, Any]

    # Data flows
    data_flows: List[DataFlow]

    # Infrastructure
    web_server: str  # e.g., "apache2", "nginx", "builtin"
    database_type: str
    caching_strategy: Optional[Dict[str, Any]]
    background_workers: List[Dict[str, Any]]

    # Integration details
    external_integrations: List[Dict[str, Any]]

    @property
    def tech_stack(self) -> str:
        """Return a human-readable tech stack description."""
        return f"{self.backend_language}/{self.backend_framework}, {self.frontend_framework}, {self.database_type}, {self.web_server}"

    def get_tech_config(self) -> TechStackConfig:
        """Get the TechStackConfig object for this specification."""
        return TechStackConfig(self.backend_language, self.backend_framework)

    def get_all_files_needed(self) -> List[str]:
        """Get list of all files that need to be generated."""
        files = []

        # Get tech config for file extensions and paths
        tech_config = self.get_tech_config()
        ext = tech_config.get_file_extension()

        # Get tech-specific paths
        models_dir = tech_config.get_models_dir()
        controllers_dir = tech_config.get_controllers_dir()
        config_dir = tech_config.get_config_dir()
        templates_dir = tech_config.get_templates_dir()
        static_dir = tech_config.get_static_dir()

        # Frontend files
        files.append(f"{templates_dir}/base.html")
        for layout in self.page_layouts:
            files.append(f"{templates_dir}/{layout['template_file']}")
        files.append(f"{static_dir}/js/main.js")
        files.append(f"{static_dir}/css/custom.css")

        # Backend files
        entry_point = tech_config.config.get('entry_point', f'app/main{ext}')
        files.append(entry_point)
        files.append(f"{config_dir}/config{ext}")
        files.append(f"{config_dir}/security{ext}")
        files.append(f"{controllers_dir}/api{ext}")

        for endpoint in self.api_endpoints:
            endpoint_file = self._get_endpoint_file(endpoint.path, ext, controllers_dir)
            if endpoint_file not in files:
                files.append(endpoint_file)

        # Models
        for model in self.data_models:
            files.append(f"{models_dir}/{model.name.lower()}{ext}")

        return files

    def _get_endpoint_file(self, path: str, ext: str, controllers_dir: str) -> str:
        """Determine endpoint file from path."""
        import os
        parts = path.split("/")
        if len(parts) >= 3:
            # Strip any file extension from the path component
            base_name = os.path.splitext(parts[2])[0]
            return f"{controllers_dir}/{base_name}{ext}"
        return f"{controllers_dir}/main{ext}"


class RequirementElaborator:
    """
    Elaborates requirements into detailed technical specifications.

    Uses LLM to expand brief descriptions into comprehensive specs
    with all technical details needed for code generation.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize requirement elaborator.

        Args:
            llm_client: LLM client for elaboration (creates new if not provided)
        """
        self.llm = llm_client or LLMClient()
        logger.info("RequirementElaborator initialized")

    def elaborate(self, analysis: PromptAnalysis) -> DetailedSpecification:
        """
        Elaborate requirements into detailed technical specification.

        Args:
            analysis: PromptAnalysis with structured requirements

        Returns:
            DetailedSpecification with complete technical details
        """
        logger.info("=" * 60)
        logger.info("REQUIREMENT ELABORATION STARTED")
        logger.info("=" * 60)

        # Build elaboration prompt
        elaboration_prompt = self._build_elaboration_prompt(analysis)

        # Call LLM for elaboration
        logger.info("Calling LLM for requirement elaboration...")
        response_obj = self.llm.generate(elaboration_prompt, temperature=0.3)  # Lower temp for consistency
        response = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)

        # Parse response
        try:
            spec_data = self._parse_elaboration_response(response)
            logger.info("✅ Successfully parsed elaboration response")
        except Exception as e:
            logger.error(f"❌ Failed to parse elaboration: {e}")
            logger.error(f"Response preview: {response[:500]}")
            raise

        # Create DetailedSpecification object
        spec = self._create_specification_object(spec_data, analysis)

        # Log summary
        self._log_specification_summary(spec)

        logger.info("=" * 60)
        logger.info("REQUIREMENT ELABORATION COMPLETE")
        logger.info("=" * 60)

        return spec

    def _build_elaboration_prompt(self, analysis: PromptAnalysis) -> str:
        """Build LLM prompt for elaborating requirements - TECH STACK AGNOSTIC."""

        # Extract tech stack from analysis
        tech = analysis.technical_constraints
        backend_lang = tech.get('backend_language', 'UNSPECIFIED')
        backend_framework = tech.get('backend_framework', 'UNSPECIFIED')
        frontend_framework = tech.get('frontend_framework', 'UNSPECIFIED')
        web_server = tech.get('web_server', 'UNSPECIFIED')
        database = tech.get('database', 'UNSPECIFIED')

        # Build tech stack description
        tech_stack_desc = f"""
## Technology Stack (FROM USER REQUIREMENTS - DO NOT CHANGE)
- **Backend Language**: {backend_lang}
- **Backend Framework**: {backend_framework}
- **Frontend Framework**: {frontend_framework}
- **Web Server**: {web_server}
- **Database**: {database}

**CRITICAL**: You MUST generate specifications that match the EXACT technology stack specified above.
DO NOT use Python if PHP is specified. DO NOT use Alpine.js if vanilla JavaScript is specified.
DO NOT use PostgreSQL if SQLite is specified. STRICTLY ADHERE to user's tech choices.
"""

        # Build framework-specific UI component guidance
        if 'alpine' in frontend_framework.lower():
            ui_component_guidance = """
For UI components using Alpine.js:
- Specify `frontend_logic` with Alpine.js x-data structure
- Specify `frontend_methods` with Alpine.js functions
- Specify `styling_classes` with Tailwind CSS classes (if Tailwind is used) or plain CSS classes
"""
        elif 'react' in frontend_framework.lower():
            ui_component_guidance = """
For UI components using React:
- Specify `frontend_logic` with React state and props
- Specify `frontend_methods` with React event handlers and hooks
- Specify `styling_classes` with CSS module classes or styled-components
"""
        elif 'vue' in frontend_framework.lower():
            ui_component_guidance = """
For UI components using Vue:
- Specify `frontend_logic` with Vue data() and computed properties
- Specify `frontend_methods` with Vue methods
- Specify `styling_classes` with scoped CSS classes
"""
        elif 'vanilla' in frontend_framework.lower() or frontend_framework == 'UNSPECIFIED':
            ui_component_guidance = """
For UI components using vanilla JavaScript:
- Specify `frontend_logic` with DOM manipulation and event listeners
- Specify `frontend_methods` with plain JavaScript functions
- Specify `styling_classes` with standard CSS classes
"""
        else:
            ui_component_guidance = f"""
For UI components using {frontend_framework}:
- Specify `frontend_logic` appropriate for this framework
- Specify `frontend_methods` appropriate for this framework
- Specify `styling_classes` appropriate for this framework
"""

        # Build backend-specific guidance
        if backend_lang.lower() == 'php':
            backend_guidance = f"""
For PHP backend:
- API endpoints should use PHP syntax
- Use {backend_framework if backend_framework != 'UNSPECIFIED' else 'plain PHP'} patterns
- Database models should use PHP ORM (if framework has one) or PDO
- File structure: index.php, api/, models/, includes/
- Web server configuration for {web_server if web_server != 'UNSPECIFIED' else 'Apache2'}
"""
        elif backend_lang.lower() == 'nodejs':
            backend_guidance = f"""
For Node.js backend:
- API endpoints should use JavaScript/TypeScript
- Use {backend_framework if backend_framework != 'UNSPECIFIED' else 'Express.js'} patterns
- Database models should use appropriate ORM (Sequelize, Mongoose, Prisma)
- File structure: server.js, routes/, models/, middleware/
"""
        elif backend_lang.lower() == 'python':
            backend_guidance = f"""
For Python backend:
- API endpoints should use Python syntax
- Use {backend_framework if backend_framework != 'UNSPECIFIED' else 'Flask'} patterns
- Database models should use SQLAlchemy, Django ORM, or equivalent
- File structure: app/main.py, app/api/, app/models/, app/core/
"""
        elif backend_lang.lower() == 'ruby':
            backend_guidance = f"""
For Ruby backend:
- API endpoints should use Ruby syntax
- Use {backend_framework if backend_framework != 'UNSPECIFIED' else 'Rails'} patterns
- Database models should use ActiveRecord or DataMapper
- File structure: app/, config/, db/, models/
"""
        elif backend_lang.lower() == 'java':
            backend_guidance = f"""
For Java backend:
- API endpoints should use Java syntax
- Use {backend_framework if backend_framework != 'UNSPECIFIED' else 'Spring Boot'} patterns
- Database models should use JPA/Hibernate
- File structure: src/main/java/, controllers/, models/, services/
"""
        else:
            backend_guidance = f"""
For {backend_lang} backend:
- Use appropriate syntax and patterns for {backend_lang}
- Follow {backend_framework} framework conventions (if specified)
- Use idiomatic {backend_lang} code structure
"""

        # Build database-specific guidance
        if database.lower() == 'sqlite':
            db_guidance = """
For SQLite database:
- Use INTEGER PRIMARY KEY for auto-incrementing IDs
- Field types: INTEGER, TEXT, REAL, BLOB
- No UUID support (use TEXT or INTEGER)
- Simple relationships with foreign keys
"""
        elif database.lower() == 'postgresql':
            db_guidance = """
For PostgreSQL database:
- Use UUID or SERIAL for primary keys
- Rich field types: UUID, TIMESTAMP, JSONB, ARRAY, etc.
- Full relationship support with constraints
"""
        elif database.lower() == 'mysql':
            db_guidance = """
For MySQL database:
- Use AUTO_INCREMENT for primary keys
- Field types: INT, VARCHAR, TEXT, DATETIME, etc.
- Full relationship support with foreign keys
"""
        elif database.lower() == 'mongodb':
            db_guidance = """
For MongoDB database:
- Use ObjectId for document IDs
- Flexible schema with embedded documents
- NoSQL relationships with references or embedding
"""
        else:
            db_guidance = f"""
For {database} database:
- Use appropriate field types for {database}
- Follow {database} best practices for schema design
"""

        # Include clarification answers if any
        clarifications_text = ""
        if analysis.clarifications_needed:
            clarifications_text = "\\n## Clarification Answers\\n"
            for q in analysis.clarifications_needed:
                if q.answered:
                    clarifications_text += f"Q: {q.question}\\nA: {q.answer}\\n\\n"

        # Build component descriptions
        components_text = "\\n".join([
            f"- {comp.name} ({comp.type}): {comp.description}\\n  Requirements: {', '.join(comp.requirements)}"
            for comp in analysis.components
        ])

        # Include validation feedback if present
        validation_feedback = ""
        if hasattr(analysis, 'clarified_inputs') and 'validation_feedback' in analysis.clarified_inputs:
            validation_feedback = f"""

## ⚠️ VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT
{analysis.clarified_inputs['validation_feedback']}

**ACTION REQUIRED**: Fix ALL issues mentioned above in this attempt.
"""

        return f"""# Task: Elaborate Requirements into Detailed Technical Specification

You are an expert full-stack architect creating detailed technical specifications.
{tech_stack_desc}

## Project Overview
**Name:** {analysis.project_name}
**Type:** {analysis.project_type}
**Description:** {analysis.description}

## Components Identified
{components_text}

## Features
{json.dumps(analysis.features, indent=2)}

## Technical Constraints (USER REQUIREMENTS)
{json.dumps(analysis.technical_constraints, indent=2)}
{clarifications_text}
{validation_feedback}

## Your Task
Create a COMPLETE technical specification with ALL details needed for code generation.
**CRITICAL**: Follow the EXACT technology stack specified above. Do not substitute technologies.

{ui_component_guidance}
{backend_guidance}
{db_guidance}

For EVERY API endpoint, specify exact request/response schemas using {backend_lang} types.
For EVERY data model, specify fields and types appropriate for {database}.

Output JSON with this structure:

```json
{{
  "project_name": "{analysis.project_name}",
  "project_type": "{analysis.project_type}",
  "description": "Technical description",

  "backend_language": "{backend_lang}",
  "backend_framework": "{backend_framework}",
  "frontend_framework": "{frontend_framework}",
  "web_server": "{web_server}",
  "database_type": "{database}",

  "ui_components": [
    {{
      "name": "example_component",
      "type": "interactive",
      "description": "Component description",
      "html_structure": "div.container > div.content",
      "frontend_logic": {{
        "// State/data structure appropriate for {frontend_framework}": "",
        "// Example for Alpine.js": {{"messages": "array", "isLoading": "boolean"}},
        "// Example for React": {{"state: {{messages, setMessages}}": ""}},
        "// Example for vanilla JS": {{"DOM references": "", "event listeners": ""}}
      }},
      "frontend_methods": [
        "// Methods/functions appropriate for {frontend_framework}",
        "// Example: handleSubmit(), fetchData(), updateUI()"
      ],
      "styling_classes": ["container", "content", "// CSS classes appropriate for your CSS framework"],
      "api_interactions": ["POST /api/endpoint"],
      "child_components": []
    }}
  ],

  "page_layouts": [
    {{
      "name": "Main Page",
      "route": "/",
      "template_file": "File extension appropriate for {backend_lang} (index.php, index.html, index.jsx, etc.)",
      "layout_type": "single_column",
      "components": ["component1"]
    }}
  ],

  "state_management": {{
    "method": "State management appropriate for {frontend_framework}",
    "stores": {{
      "// Define stores/state as needed": ""
    }}
  }},

  "api_endpoints": [
    {{
      "method": "POST",
      "path": "/api/endpoint",
      "description": "Endpoint description",
      "request_body": {{
        "fields": [
          {{
            "name": "field1",
            "type": "Type appropriate for {backend_lang} (string for PHP, str for Python, string for Node.js, etc.)",
            "required": true
          }}
        ]
      }},
      "response": {{
        "status_code": 200,
        "body": {{
          "field": "value"
        }}
      }},
      "auth_required": true
    }}
  ],

  "data_models": [
    {{
      "name": "ModelName",
      "table_name": "table_name",
      "fields": [
        {{
          "name": "id",
          "type": "Type appropriate for {database} (INTEGER PRIMARY KEY for SQLite, UUID for PostgreSQL, etc.)",
          "constraints": ["PRIMARY KEY"]
        }},
        {{
          "name": "name",
          "type": "Type appropriate for {database} (TEXT for SQLite, VARCHAR for MySQL, String for MongoDB, etc.)",
          "constraints": []
        }},
        {{
          "name": "created_at",
          "type": "Type appropriate for {database} (TEXT for SQLite, TIMESTAMP for PostgreSQL, DATETIME for MySQL, Date for MongoDB)",
          "constraints": ["DEFAULT CURRENT_TIMESTAMP or equivalent"]
        }}
      ],
      "relationships": [],
      "indexes": []
    }}
  ],

  "authentication": {{
    "method": "Authentication method appropriate for {backend_framework}",
    "token_expiry": "30 minutes",
    "password_hashing": "bcrypt or argon2"
  }},

  "authorization": {{
    "method": "role_based",
    "roles": ["user"],
    "permissions": {{}}
  }},

  "data_flows": [
    {{
      "name": "Example Flow",
      "steps": [
        {{"step": 1, "action": "User action"}},
        {{"step": 2, "action": "Frontend validates using {frontend_framework}"}},
        {{"step": 3, "action": "POST to API"}},
        {{"step": 4, "action": "Backend processes in {backend_lang}"}},
        {{"step": 5, "action": "Save to {database} database"}},
        {{"step": 6, "action": "Return response"}}
      ],
      "error_handling": [
        "Validation errors: Show error message",
        "Server errors: Log and return 500"
      ]
    }}
  ],

  "caching_strategy": {{
    "enabled": false,
    "backend": "null",
    "cache_items": []
  }},

  "background_workers": [],

  "external_integrations": []
}}
```

## Critical Instructions
1. **STRICTLY ADHERE to the technology stack specified above**
2. **DO NOT substitute technologies** - if PHP is specified, use PHP syntax, not Python
3. **Generate code structures appropriate for {backend_lang}/{backend_framework}**
4. **Use {database} data types and patterns, not other database types**
5. **Use {frontend_framework} patterns and syntax, not other frameworks**
6. **Configure for {web_server}, not other web servers**
7. **Be EXHAUSTIVE** - include every detail needed for implementation
8. **Match file extensions to backend language** (PHP: .php, Python: .py, Node.js: .js/.ts, etc.)
9. **Use appropriate routing patterns** (PHP: direct file access or framework routing, Python: framework routes, etc.)
10. **Include security considerations at every layer**

Return ONLY valid JSON, no explanations.
"""

    def _parse_elaboration_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured data."""
        json_str = response.strip()

        # Remove markdown code blocks
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]

        json_str = json_str.strip()

        return json.loads(json_str)

    def _create_specification_object(self,
                                     data: Dict[str, Any],
                                     analysis: PromptAnalysis) -> DetailedSpecification:
        """Create DetailedSpecification from parsed data."""

        # Parse UI components
        ui_components = []
        for comp_data in data.get("ui_components", []):
            component = UIComponentSpec(
                name=comp_data["name"],
                type=comp_data["type"],
                description=comp_data["description"],
                html_structure=comp_data.get("html_structure", ""),
                frontend_logic=comp_data.get("frontend_logic", {}),
                frontend_methods=comp_data.get("frontend_methods", []),
                styling_classes=comp_data.get("styling_classes", []),
                api_interactions=comp_data.get("api_interactions", []),
                child_components=comp_data.get("child_components", [])
            )
            ui_components.append(component)

        # Parse API endpoints
        api_endpoints = []
        for ep_data in data.get("api_endpoints", []):
            endpoint = APIEndpoint(
                method=ep_data["method"],
                path=ep_data["path"],
                description=ep_data.get("description", ""),
                request_body=ep_data.get("request_body"),
                query_params=ep_data.get("query_params"),
                response=ep_data.get("response"),
                auth_required=ep_data.get("auth_required", True),
                rate_limit=ep_data.get("rate_limit")
            )
            api_endpoints.append(endpoint)

        # Parse data models
        data_models = []
        for model_data in data.get("data_models", []):
            model = DataModel(
                name=model_data["name"],
                table_name=model_data["table_name"],
                fields=model_data.get("fields", []),
                relationships=model_data.get("relationships", []),
                indexes=model_data.get("indexes", [])
            )
            data_models.append(model)

        # Parse data flows
        data_flows = []
        for flow_data in data.get("data_flows", []):
            flow = DataFlow(
                name=flow_data["name"],
                steps=flow_data.get("steps", []),
                error_handling=flow_data.get("error_handling", [])
            )
            data_flows.append(flow)

        # Extract tech stack from prompt analysis technical constraints
        tech_constraints = analysis.technical_constraints
        backend_lang = tech_constraints.get("backend_language", "python")
        backend_framework = tech_constraints.get("backend_framework", "flask")
        frontend_framework = tech_constraints.get("frontend_framework", "alpine_tailwind")
        web_server = tech_constraints.get("web_server", "builtin")
        database_type = tech_constraints.get("database", "postgresql")

        # Override with data if provided (but respect prompt analysis defaults)
        backend_lang = data.get("backend_language", backend_lang)
        backend_framework = data.get("backend_framework", backend_framework)
        frontend_framework = data.get("frontend_framework", frontend_framework)
        web_server = data.get("web_server", web_server)
        database_type = data.get("database_type", database_type)

        # Special handling for PHP - if backend language is PHP but no framework specified,
        # use php_plain as framework for simpler code generation
        if backend_lang.lower() == "php" and backend_framework.lower() == "unspecified":
            backend_framework = "plain"

        # Create specification
        spec = DetailedSpecification(
            project_name=data.get("project_name", analysis.project_name),
            project_type=data.get("project_type", analysis.project_type),
            description=data.get("description", analysis.description),
            ui_components=ui_components,
            page_layouts=data.get("page_layouts", []),
            frontend_framework=frontend_framework,
            state_management=data.get("state_management", {}),
            backend_language=backend_lang,
            backend_framework=backend_framework,
            api_endpoints=api_endpoints,
            data_models=data_models,
            authentication=data.get("authentication", {}),
            authorization=data.get("authorization", {}),
            data_flows=data_flows,
            web_server=web_server,
            database_type=database_type,
            caching_strategy=data.get("caching_strategy"),
            background_workers=data.get("background_workers", []),
            external_integrations=data.get("external_integrations", [])
        )

        return spec

    def _log_specification_summary(self, spec: DetailedSpecification):
        """Log summary of specification."""
        logger.info(f"\n📋 Specification Summary:")
        logger.info(f"  Project: {spec.project_name}")
        logger.info(f"  UI Components: {len(spec.ui_components)}")
        for comp in spec.ui_components:
            logger.info(f"    - {comp.name} ({comp.type})")
        logger.info(f"  API Endpoints: {len(spec.api_endpoints)}")
        for ep in spec.api_endpoints:
            logger.info(f"    - {ep.method} {ep.path}")
        logger.info(f"  Data Models: {len(spec.data_models)}")
        for model in spec.data_models:
            logger.info(f"    - {model.name} ({len(model.fields)} fields)")
        logger.info(f"  Data Flows: {len(spec.data_flows)}")
