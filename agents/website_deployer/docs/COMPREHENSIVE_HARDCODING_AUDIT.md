# Comprehensive Hardcoding Audit: Intelligent Code Generation Pipeline
**Technology Stack Agnosticism Violation Analysis**

---

## Executive Summary

### Severity: CRITICAL - Complete Pipeline Failure for Non-Python/FastAPI Stacks

This audit reveals **systematic and pervasive hardcoding violations** throughout the intelligent code generation pipeline that render it **completely non-functional** for any technology stack other than:
- Backend: Python + FastAPI + SQLAlchemy + Pydantic
- Frontend: Alpine.js + Tailwind CSS
- Database: PostgreSQL (with fallbacks to SQLite)
- Server: Uvicorn/ASGI

**Impact Assessment:**
- **Lines of hardcoded tech references**: 165+ across 5 files
- **Stages affected**: 5 of 6 pipeline stages (83%)
- **Pipeline functionality for PHP/Laravel**: 0%
- **Pipeline functionality for Node.js/Express**: 0%
- **Pipeline functionality for Ruby/Rails**: 0%

**Critical Finding**: Despite `requirement_elaborator.py` being partially refactored to detect user's tech stack preferences, **all subsequent stages completely ignore this information** and generate Python/FastAPI code regardless of user requirements.

---

## Files Analyzed

### Stage 1: Prompt Analysis
- **File**: `prompt_analyzer.py`
- **Status**: ✅ TECH-AGNOSTIC (Only stage not affected)
- **Lines of Code**: 378
- **Hardcoded References**: 0

### Stage 2: Requirement Elaboration
- **File**: `requirement_elaborator.py`
- **Status**: ⚠️ PARTIALLY REFACTORED (Detects tech stack but has residual hardcoding)
- **Lines of Code**: 687
- **Hardcoded References**: 12 violations

### Stage 3: Workflow Planning
- **File**: `workflow_planner.py`
- **Status**: ❌ SEVERELY HARDCODED
- **Lines of Code**: 714
- **Hardcoded References**: 73 violations

### Stage 4: Code Generation
- **File**: `llm_code_generator.py`
- **Status**: ❌ SEVERELY HARDCODED
- **Lines of Code**: 665
- **Hardcoded References**: 60 violations

### Stage 5: Project Assembly
- **File**: `assembly_coordinator.py`
- **Status**: ❌ SEVERELY HARDCODED
- **Lines of Code**: 281
- **Hardcoded References**: 23 violations

### Stage 6: Consistency Verification
- **File**: `consistency_verifier.py`
- **Status**: ❌ SEVERELY HARDCODED
- **Lines of Code**: 548
- **Hardcoded References**: 9 violations

---

## Detailed Findings by File

### 1. requirement_elaborator.py (Stage 2)
**Status**: Partially refactored but incomplete

#### Hardcoded File Paths (12 violations)
**Lines 116-144**: `get_all_files_needed()` method hardcodes Python/FastAPI structure
```python
# Line 116-120: Hardcoded paths
files.append("app/templates/base.html")           # Assumes FastAPI structure
files.append(f"app/templates/{layout['template_file']}")
files.append("app/static/js/main.js")
files.append("app/static/css/custom.css")

# Line 123-126: Python-specific file structure
files.append("app/main.py")                        # Python entry point
files.append("app/core/config.py")                 # Python config
files.append("app/core/security.py")               # Python security
files.append("app/api/api.py")                     # Python API router

# Line 129-131: Assumes Python module structure
endpoint_file = self._get_endpoint_file(endpoint.path)
# ...

# Line 135: Python model structure
files.append(f"app/models/{model.name.lower()}.py")
```

**Impact**:
- Returns Python `.py` files even when user requests PHP
- File structure assumes FastAPI project layout
- Breaks PHP projects requiring `index.php`, `api/*.php`, `includes/*.php`

#### Root Cause
- Method doesn't receive `tech_stack` information from `DetailedSpecification`
- Fixed file paths don't adapt to backend language
- No conditional logic based on `self.backend_language`

---

### 2. workflow_planner.py (Stage 3)
**Status**: SEVERELY HARDCODED - Complete rewrite required

This file contains **73 hardcoded violations** across multiple categories.

#### Category A: Hardcoded File Extensions (15+ violations)
**Lines throughout**: Assumes `.py` file extension universally
```python
# Line 130-136: Python __init__.py files
files["app/__init__.py"] = FileSpecification(...)
files["app/core/__init__.py"] = FileSpecification(...)

# Line 146-151: Python .py extensions
files["app/core/config.py"] = FileSpecification(...)

# Line 164: Hardcoded Python model extension
model_path = f"app/models/{model.name.lower()}.py"

# Line 186: Hardcoded Python schema extension
schema_path = f"app/schemas/{group_name}.py"

# Line 206: Hardcoded Python CRUD extension
crud_path = f"app/crud/{model.name.lower()}.py"

# Line 236: Hardcoded Python endpoint extension
endpoint_path = f"app/api/endpoints/{group_name}.py"

# Line 256: Python API router
files["app/api/api.py"] = FileSpecification(...)

# Line 267: Python security
files["app/core/security.py"] = FileSpecification(...)

# Line 304: Python main
files["app/main.py"] = FileSpecification(...)

# Line 326: Python Celery
files["app/workers/celery_app.py"] = FileSpecification(...)

# Line 334: Python worker
worker_path = f"app/workers/{worker['name']}.py"

# Line 295: JavaScript hardcoded
files["app/static/js/main.js"] = FileSpecification(...)
```

**Impact**:
- PHP projects get `.py` files instead of `.php`
- Node.js projects get `.py` files instead of `.js`/`.ts`
- Ruby projects get `.py` files instead of `.rb`

#### Category B: Hardcoded Python-Specific Structures (20+ violations)
**Lines 114-127**: FastAPI directory structure
```python
# Line 114-126: Hardcoded FastAPI project structure
(project_dir / "app").mkdir()
(project_dir / "app" / "api").mkdir()
(project_dir / "app" / "core").mkdir()
(project_dir / "app" / "models").mkdir()
(project_dir / "app" / "schemas").mkdir()      # Pydantic schemas
(project_dir / "app" / "crud").mkdir()
(project_dir / "app" / "static").mkdir()
(project_dir / "app" / "static" / "css").mkdir()
(project_dir / "app" / "static" / "js").mkdir()
(project_dir / "app" / "templates").mkdir()
(project_dir / "tests").mkdir()
(project_dir / "alembic").mkdir()              # Python Alembic migrations
(project_dir / "scripts").mkdir()
```

**Impact**:
- PHP Laravel projects need: `app/Http/Controllers/`, `routes/`, `database/migrations/`, `resources/views/`
- Node.js Express projects need: `routes/`, `controllers/`, `models/`, `views/`, `middleware/`
- Ruby Rails projects need: `app/controllers/`, `app/models/`, `app/views/`, `db/migrate/`

#### Category C: Hardcoded Technology Names in Prompts (38+ violations)
**Lines 447-693**: All prompt generation methods hardcode FastAPI/SQLAlchemy/Pydantic

```python
# Line 449-462: FastAPI/JWT/Pydantic hardcoded
def _create_config_prompt(self, spec: DetailedSpecification) -> str:
    return f"""Generate FastAPI settings configuration file (app/core/config.py).

Include:
- Pydantic BaseSettings for environment variables
- DATABASE_URL
- SECRET_KEY for JWT
- CORS_ORIGINS list
- JWT token expiry settings: {spec.authentication.get('token_expiry', '30 minutes')}
"""

# Line 465-487: SQLAlchemy hardcoded
def _create_model_prompt(self, model, spec: DetailedSpecification) -> str:
    return f"""Generate SQLAlchemy model: {model.name}

Include:
- Proper imports from sqlalchemy
- Type hints
- Docstrings
- Relationships with back_populates
"""

# Line 489-503: Pydantic hardcoded
def _create_schema_prompt(self, group_name: str, endpoints: List, spec: DetailedSpecification) -> str:
    return f"""Generate Pydantic schemas for {group_name} API endpoints.

Create request and response schemas for each endpoint:
- Use Pydantic BaseModel
- Include field validators
- Add docstrings with examples
- Use appropriate types (EmailStr, HttpUrl, etc.)
"""

# Line 505-517: SQLAlchemy Session hardcoded
def _create_crud_prompt(self, model, spec: DetailedSpecification) -> str:
    return f"""Generate CRUD operations for {model.name} model.

Functions needed:
- create_{model.name.lower()}(db: Session, obj_in: schema) -> model
- get_{model.name.lower()}(db: Session, id: UUID) -> Optional[model]
"""

# Line 519-544: FastAPI router hardcoded
def _create_endpoint_prompt(self, group_name: str, endpoints: List, spec: DetailedSpecification) -> str:
    return f"""Generate FastAPI endpoints for {group_name}.

Requirements:
- Use FastAPI router
- Include authentication dependencies if auth_required
- Proper error handling with HTTPException
"""

# Line 546-558: FastAPI APIRouter hardcoded
def _create_api_router_prompt(self, endpoint_groups: Dict[str, List]) -> str:
    return f"""Generate main API router (app/api/api.py).

- Create APIRouter
- Include all endpoint routers with proper prefixes
- Add tags for OpenAPI documentation
"""

# Line 560-578: python-jose/passlib hardcoded
def _create_security_prompt(self, spec: DetailedSpecification) -> str:
    return f"""Generate authentication and security utilities.

Use python-jose for JWT, passlib for password hashing.
"""

# Line 580-591: Alpine.js/Tailwind hardcoded
def _create_base_template_prompt(self, spec: DetailedSpecification) -> str:
    return f"""Generate base HTML template with Alpine.js and Tailwind CSS.

Include:
- Tailwind CSS CDN
- Alpine.js CDN
"""

# Line 656-672: FastAPI hardcoded
def _create_main_app_prompt(self, spec: DetailedSpecification) -> str:
    return f"""Generate FastAPI application entry point (app/main.py).

Include:
- FastAPI app instance
- CORS middleware with settings from config
"""

# Line 674-682: Celery/Redis hardcoded
def _create_celery_app_prompt(self, spec: DetailedSpecification) -> str:
    return """Generate Celery application (app/workers/celery_app.py).

Include:
- Celery instance with Redis broker
"""
```

**Impact**:
- LLM receives hardcoded FastAPI prompts even when user wants Laravel
- LLM receives SQLAlchemy prompts even when user wants Eloquent ORM
- LLM receives Pydantic prompts even when user wants PHP validation

#### Missing Tech Stack Awareness
**Critical Issue**: `workflow_planner.py` receives `DetailedSpecification` with `backend_language`, `backend_framework`, `frontend_framework`, `database_type` properties BUT NEVER USES THEM.

**Line 80**: `plan()` method receives `spec: DetailedSpecification`
**Line 96-342**: Entire `_identify_all_files()` method ignores:
- `spec.backend_language`
- `spec.backend_framework`
- `spec.frontend_framework`
- `spec.database_type`

---

### 3. llm_code_generator.py (Stage 4)
**Status**: SEVERELY HARDCODED - Complete rewrite required

This file contains **60+ hardcoded violations** across role prompts and language instructions.

#### Category A: Hardcoded Role Prompts (48 violations)
**Lines 367-549**: All role-based system prompts hardcode specific technologies

```python
# Line 371-384: SQLAlchemy/PostgreSQL hardcoded in model role
"model": """# Your Role: Senior Database Architect & SQLAlchemy Expert

You are a highly experienced database architect specializing in SQLAlchemy ORM design. You have:
- 10+ years of experience designing scalable database schemas
- Deep expertise in SQLAlchemy relationships, constraints, and performance optimization
- Experience with PostgreSQL, MySQL, and other relational databases

Your task is to generate production-ready SQLAlchemy models with:
- Proper foreign key relationships and cascading rules
- Optimized indexes for query performance
- Clear bidirectional relationships with back_populates
"""

# Line 386-401: FastAPI/async/await hardcoded in API endpoint role
"api_endpoint": """# Your Role: Senior Backend Engineer & REST API Specialist

You are an expert backend engineer specializing in FastAPI and RESTful API design. You have:
- Deep expertise in FastAPI, async/await patterns, and Python web frameworks
- Experience with authentication, rate limiting, and input validation

Your task is to generate production-ready API endpoints with:
- Proper async/await usage for I/O operations
- Comprehensive input validation and error handling
- Rate limiting and security considerations
- OpenAPI documentation with examples
"""

# Line 403-416: Pydantic v2 hardcoded in schema role
"schema": """# Your Role: Data Validation Expert & Pydantic Specialist

You are an expert in data validation and Pydantic schema design. You have:
- Extensive experience with Pydantic v2 and FastAPI integration
- Deep understanding of type systems, validation rules, and serialization

Your task is to generate production-ready Pydantic schemas with:
- Precise type hints and validation rules
- Custom validators for complex business logic
- Proper use of Field() for additional constraints
"""

# Line 418-431: SQLAlchemy Session hardcoded in CRUD role
"crud": """# Your Role: Database Operations Specialist

You are a database operations expert specializing in CRUD patterns and SQLAlchemy. You have:
- Deep experience with database transaction management
- Expertise in query optimization and N+1 query prevention

Your task is to generate production-ready CRUD operations with:
- Proper session management and transaction handling
- Efficient queries with eager/lazy loading
"""

# Line 433-448: Alpine.js/Tailwind hardcoded in template role
"template": """# Your Role: Senior Frontend Engineer & UX/UI Specialist

You are a highly skilled frontend engineer with expertise in modern web development. You have:
- Deep expertise in HTML5, CSS3, Tailwind CSS, and Alpine.js
- Experience with real-time features (SSE, WebSocket) and async operations

Your task is to generate production-ready HTML templates with:
- Semantic HTML5 structure for accessibility
- Responsive design using Tailwind CSS utility classes
- Interactive components using Alpine.js with proper state management
"""

# Line 450-465: Alpine.js/SSE hardcoded in JavaScript role
"javascript": """# Your Role: Senior JavaScript Engineer & Alpine.js Expert

You are an expert JavaScript engineer specializing in Alpine.js and modern frontend patterns. You have:
- Extensive experience with Alpine.js, reactive programming, and component architecture
- Experience with real-time features (Server-Sent Events, WebSocket)

Your task is to generate production-ready JavaScript with:
- Clean Alpine.js components with proper data/methods separation
- Robust error handling with user-friendly messages
"""

# Line 467-481: JWT/bcrypt/python-jose hardcoded in security role
"security": """# Your Role: Security Engineer & Authentication Specialist

You are a cybersecurity expert specializing in authentication and authorization. You have:
- Deep expertise in JWT, OAuth2, and modern auth patterns
- Strong knowledge of cryptography, password hashing, and token management

Your task is to generate production-ready security utilities with:
- Secure password hashing (bcrypt with proper rounds)
- Properly configured JWT with appropriate expiry
- Token validation and refresh mechanisms
"""

# Line 483-496: Pydantic Settings hardcoded in config role
"config": """# Your Role: DevOps Engineer & Configuration Specialist

You are a DevOps engineer specializing in application configuration and deployment. You have:
- Expertise in Pydantic Settings and configuration validation

Your task is to generate production-ready configuration with:
- Clear separation of secrets and public config
- Validation for all configuration values
"""

# Line 498-511: Celery/Redis hardcoded in worker role
"worker": """# Your Role: Distributed Systems Engineer & Celery Expert

You are an expert in distributed systems and background task processing. You have:
- Extensive experience with Celery, Redis, and async task queues
- Deep understanding of task scheduling, retries, and failure handling

Your task is to generate production-ready Celery tasks with:
- Proper task configuration (retries, timeouts, rate limits)
- Comprehensive error handling and logging
"""

# Line 513-528: FastAPI/ASGI/middleware hardcoded in main role
"main": """# Your Role: Senior Full-Stack Architect & FastAPI Expert

You are a senior full-stack architect with deep FastAPI expertise. You have:
- Deep knowledge of FastAPI, ASGI servers, and middleware
- Expertise in application lifecycle, startup/shutdown events

Your task is to generate the main FastAPI application with:
- Proper app initialization and configuration loading
- Middleware setup (CORS, logging, error handling)
- Static file and template configuration
"""

# Line 530-542: FastAPI routing hardcoded in API router role
"api_router": """# Your Role: API Architect & Routing Specialist

You are an API architect specializing in REST API organization and routing. You have:
- Deep knowledge of FastAPI routing, dependencies, and middleware
- Understanding of API versioning and OpenAPI documentation

Your task is to generate production-ready API routers with:
- Logical grouping of related endpoints
- Clear OpenAPI documentation structure
"""
```

**Impact**:
- LLM receives "SQLAlchemy Expert" role even when generating PHP Eloquent models
- LLM receives "FastAPI Expert" role even when generating Laravel routes
- LLM receives "Pydantic Specialist" role even when generating PHP request validation

#### Category B: Hardcoded Language Instructions (12 violations)
**Lines 551-588**: Language-specific instructions hardcode Python/Alpine.js patterns

```python
# Line 553-564: Python/Pydantic/async hardcoded
if file_type in ["model", "api_endpoint", "schema", "crud", "config", "security", "worker", "main"]:
    return """
**Python Standards:**
- Use type hints for all functions: `def func(arg: str) -> int:`
- Docstrings in Google format with Args, Returns, Raises sections
- Import ordering: stdlib, third-party, local (separated by blank lines)
- Use Pydantic for data validation
- Use async/await for I/O operations
"""

# Line 565-575: Jinja2/Alpine.js/Tailwind hardcoded
elif file_type == "template":
    return """
**HTML/Template Standards:**
- Use Jinja2 template syntax for dynamic content
- Alpine.js directives: x-data, x-show, x-if, x-for, @click, @submit
- Tailwind CSS utility classes for styling
"""

# Line 576-586: Alpine.js hardcoded
elif file_type == "javascript":
    return """
**JavaScript/Alpine.js Standards:**
- Use Alpine.js for component logic
- Alpine.store() for global state
- Async/await for API calls
"""
```

**Impact**:
- PHP files receive Python coding standards
- Laravel Blade templates receive Jinja2/Alpine.js instructions
- PHP request validation receives Pydantic instructions

#### Missing Tech Stack Integration
**Critical Issue**: `LLMCodeGenerator` class has NO access to `DetailedSpecification.backend_language` or any tech stack information.

**Line 225-235**: Constructor receives optional `LLMClient` but NO tech stack configuration
**Line 275-321**: `generate_file()` builds prompts without tech stack context
**Line 323-365**: `_build_full_prompt()` has NO access to target technology stack

---

### 4. assembly_coordinator.py (Stage 5)
**Status**: SEVERELY HARDCODED - Complete rewrite required

This file contains **23 hardcoded violations**.

#### Category A: Hardcoded Directory Structure (13 violations)
**Lines 114-126**: Creates FastAPI-specific directory structure

```python
# Line 114-126: FastAPI project structure hardcoded
(project_dir / "app").mkdir()
(project_dir / "app" / "api").mkdir()
(project_dir / "app" / "core").mkdir()
(project_dir / "app" / "models").mkdir()
(project_dir / "app" / "schemas").mkdir()         # Pydantic schemas (Python-specific)
(project_dir / "app" / "crud").mkdir()
(project_dir / "app" / "static").mkdir()
(project_dir / "app" / "static" / "css").mkdir()
(project_dir / "app" / "static" / "js").mkdir()
(project_dir / "app" / "templates").mkdir()
(project_dir / "tests").mkdir()
(project_dir / "alembic").mkdir()                 # Python Alembic migrations
(project_dir / "scripts").mkdir()
```

**Impact**:
- PHP Laravel projects get `app/schemas/` instead of `app/Http/Requests/`
- PHP projects get `alembic/` instead of `database/migrations/`
- Node.js projects get FastAPI structure instead of Express structure

#### Category B: Hardcoded README Content (5 violations)
**Lines 143-194**: README.md hardcodes FastAPI/SQLAlchemy/Alpine.js stack

```python
# Line 148: Hardcoded tech stack
content = f"""# {project_name}

## Overview
This is a fully generated web application using FastAPI, SQLAlchemy, and Alpine.js.

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run migrations:
   ```bash
   alembic upgrade head                           # Python Alembic
   ```

5. Start the server:
   ```bash
   uvicorn app.main:app --reload                  # FastAPI/Uvicorn
   ```

## Features
- FastAPI backend
- SQLAlchemy ORM with PostgreSQL
- Alpine.js frontend
- Tailwind CSS styling
"""
```

**Impact**:
- PHP projects get Python setup instructions
- Laravel projects shown `alembic upgrade head` instead of `php artisan migrate`
- Express projects shown `uvicorn app.main:app` instead of `npm start`

#### Category C: Hardcoded Dependencies (5 violations)
**Lines 229-253**: requirements.txt hardcodes Python packages

```python
# Line 230-234: FastAPI/SQLAlchemy/Pydantic hardcoded
requirements = {
    "fastapi", "uvicorn[standard]", "sqlalchemy", "alembic",
    "pydantic", "pydantic-settings", "python-dotenv",
    "jinja2", "python-multipart", "requests", "httpx"
}

# Line 237-247: Additional Python packages
if "passlib" in file.content:
    requirements.add("passlib[bcrypt]")
if "jose" in file.content or "jwt" in file.content:
    requirements.add("python-jose[cryptography]")
if "celery" in file.content:
    requirements.add("celery[redis]")
if "redis" in file.content:
    requirements.add("redis")
if "psycopg2" in file.content or "postgres" in file.content.lower():
    requirements.add("psycopg2-binary")
```

**Impact**:
- PHP projects get `requirements.txt` instead of `composer.json`
- Node.js projects get Python packages instead of `package.json`
- All non-Python projects get completely wrong dependency files

#### Missing Tech Stack Awareness
**Critical Issue**: `AssemblyCoordinator` receives `List[GeneratedFile]` and `project_name` but NO tech stack information.

**Line 57-103**: `assemble()` method has NO access to `backend_language` or `backend_framework`

---

### 5. consistency_verifier.py (Stage 6)
**Status**: SEVERELY HARDCODED - Complete rewrite required

This file contains **9 hardcoded violations**.

#### Category A: Hardcoded Python AST Parsing (3 violations)
**Lines 160-162**: Assumes all backend files are Python

```python
# Line 160-162: Assumes .py extension
if not str(file.path).endswith('.py'):
    continue

try:
    ast.parse(file.content)                       # Python AST parser
```

**Impact**:
- PHP files skip validation (not `.py`)
- Node.js files skip validation (not `.py`)
- Only Python files verified for syntax

#### Category B: Hardcoded Third-Party Packages (6 violations)
**Lines 260-267**: Third-party package whitelist hardcodes Python packages

```python
# Line 260-267: Python packages hardcoded
third_party = {
    'fastapi', 'pydantic', 'sqlalchemy', 'jose', 'passlib',
    'uvicorn', 'httpx', 'redis', 'celery', 'alembic', 'jinja2',
    'requests', 'python', 'email_validator', 'sse_starlette',
    'psycopg2', 'asyncpg', 'dotenv', 'starlette'
}
```

**Impact**:
- PHP imports like `use Illuminate\Http\Request;` flagged as unresolvable
- Node.js imports like `import express from 'express';` flagged as unresolvable
- Ruby imports like `require 'rails'` flagged as unresolvable

#### Category C: Hardcoded Expected Dependencies (BONUS violations)
**Lines 314-319**: Expects FastAPI-specific dependencies

```python
# Line 314-319: FastAPI dependencies expected
expected_deps = {
    'fastapi', 'uvicorn', 'pydantic', 'sqlalchemy',
    'alembic', 'python-jose', 'passlib', 'python-multipart',
    'email-validator', 'python-dotenv'
}
```

**Impact**:
- PHP Laravel projects fail validation (missing `fastapi`, `pydantic`, etc.)
- Node.js Express projects fail validation
- Verification stage becomes Python-only gatekeeper

---

## Root Cause Analysis

### Why This Happened

#### 1. **Incremental Refactoring Abandoned Midway**
- `requirement_elaborator.py` was partially refactored to detect tech stack (Lines 208-573)
- Excellent tech-agnostic prompt generation in Stage 2
- **BUT**: Stages 3-6 were never updated to consume this information
- Pipeline breaks between Stage 2 (tech-aware) and Stage 3 (tech-blind)

#### 2. **No Tech Stack Propagation Architecture**
**Current broken flow:**
```
Stage 1 (Analyzer) → PromptAnalysis
                        ↓
Stage 2 (Elaborator) → DetailedSpecification {backend_language, backend_framework, ...}
                        ↓
Stage 3 (Planner) → GenerationWorkflow [IGNORES tech stack ❌]
                        ↓
Stage 4 (Generator) → List[GeneratedFile] [IGNORES tech stack ❌]
                        ↓
Stage 5 (Assembler) → AssembledProject [IGNORES tech stack ❌]
                        ↓
Stage 6 (Verifier) → VerificationReport [IGNORES tech stack ❌]
```

**Required flow:**
```
Stage 1 → PromptAnalysis
          ↓
Stage 2 → DetailedSpecification {tech_stack}
          ↓ [PASS tech_stack to all stages]
Stage 3 → GenerationWorkflow (uses tech_stack)
          ↓
Stage 4 → GeneratedFile (uses tech_stack)
          ↓
Stage 5 → AssembledProject (uses tech_stack)
          ↓
Stage 6 → VerificationReport (uses tech_stack)
```

#### 3. **Configuration-Driven Design Not Implemented**
- No `tech_stack_registry.yaml` mapping tech stacks to:
  - File extensions (`.py` vs `.php` vs `.js` vs `.rb`)
  - Directory structures (`app/api/` vs `app/Http/Controllers/`)
  - Framework-specific patterns (FastAPI routers vs Laravel routes)
  - Dependency managers (`pip` vs `composer` vs `npm`)

#### 4. **LLM Prompts Not Parameterized**
- All prompts in `workflow_planner.py` and `llm_code_generator.py` hardcode technology names
- Should use template variables: `{backend_framework}`, `{orm_library}`, `{validation_library}`
- Example current: `"Generate FastAPI endpoints..."`
- Example needed: `"Generate {backend_framework} endpoints..."`

#### 5. **Missing Abstraction Layers**
No abstraction for:
- **FileNaming**: `.get_extension(backend_language)` → `.py` | `.php` | `.js` | `.rb`
- **DirectoryLayout**: `.get_structure(backend_framework)` → FastAPI | Laravel | Express | Rails
- **DependencyManager**: `.get_format(backend_language)` → requirements.txt | composer.json | package.json | Gemfile
- **PromptTemplates**: `.get_prompt(file_type, tech_stack)` → Tech-specific instructions

---

## Complete Refactoring Plan

### Phase 1: Foundation - Configuration Infrastructure
**Priority**: P0 (CRITICAL - Blocks all other work)
**Effort**: LARGE (3-5 days)
**Dependencies**: None

#### Tasks:
1. **Create Tech Stack Registry**
   - File: `config/tech_stack_registry.yaml`
   - Content:
     ```yaml
     tech_stacks:
       python_fastapi:
         backend_language: python
         backend_framework: fastapi
         file_extension: .py
         entry_point: app/main.py
         directory_structure:
           - app/api/
           - app/models/
           - app/schemas/
           - app/crud/
         dependency_manager: pip
         dependency_file: requirements.txt
         orm: sqlalchemy
         validation: pydantic
         server: uvicorn
         migration_tool: alembic

       php_laravel:
         backend_language: php
         backend_framework: laravel
         file_extension: .php
         entry_point: public/index.php
         directory_structure:
           - app/Http/Controllers/
           - app/Models/
           - app/Http/Requests/
           - database/migrations/
         dependency_manager: composer
         dependency_file: composer.json
         orm: eloquent
         validation: form_requests
         server: apache2
         migration_tool: artisan

       nodejs_express:
         backend_language: nodejs
         backend_framework: express
         file_extension: .js
         entry_point: server.js
         directory_structure:
           - routes/
           - models/
           - controllers/
           - middleware/
         dependency_manager: npm
         dependency_file: package.json
         orm: sequelize
         validation: express_validator
         server: nodejs
         migration_tool: sequelize_cli
     ```

2. **Create Prompt Template Registry**
   - File: `config/prompt_templates.yaml`
   - Tech-parameterized prompts for each file type
   - Example:
     ```yaml
     model_prompt:
       python_fastapi: "Generate SQLAlchemy model..."
       php_laravel: "Generate Eloquent model..."
       nodejs_express: "Generate Sequelize model..."

     api_endpoint_prompt:
       python_fastapi: "Generate FastAPI router endpoint..."
       php_laravel: "Generate Laravel controller method..."
       nodejs_express: "Generate Express route handler..."
     ```

3. **Create TechStackConfig Class**
   - File: `stages/intelligent_generators/tech_stack_config.py`
   - Loads registry and provides access methods:
     ```python
     class TechStackConfig:
         def __init__(self, backend_language: str, backend_framework: str):
             ...

         def get_file_extension(self) -> str:
             """Returns .py, .php, .js, .rb, etc."""

         def get_directory_structure(self) -> List[str]:
             """Returns tech-specific directory structure."""

         def get_dependency_file_name(self) -> str:
             """Returns requirements.txt, composer.json, package.json, etc."""

         def get_prompt_template(self, file_type: str) -> str:
             """Returns tech-specific LLM prompt template."""

         def get_orm_library(self) -> str:
             """Returns sqlalchemy, eloquent, sequelize, activerecord, etc."""
     ```

### Phase 2: Pipeline Refactoring - Data Flow
**Priority**: P0 (CRITICAL)
**Effort**: MEDIUM (2-3 days)
**Dependencies**: Phase 1 complete

#### Tasks:
1. **Update `DetailedSpecification` class**
   - Add method: `get_tech_config() -> TechStackConfig`
   - Cache `TechStackConfig` instance based on `backend_language` + `backend_framework`

2. **Update all pipeline stage constructors**
   - `WorkflowPlanner.__init__(tech_config: TechStackConfig)`
   - `LLMCodeGenerator.__init__(llm_client, tech_config: TechStackConfig)`
   - `AssemblyCoordinator.__init__(base_dir, tech_config: TechStackConfig)`
   - `ConsistencyVerifier.__init__(tech_config: TechStackConfig)`

3. **Update orchestrator to pass tech_config**
   - Main generation pipeline orchestrator
   - Extract `tech_config` from `DetailedSpecification` in Stage 2
   - Pass to Stages 3-6

### Phase 3: Workflow Planner Refactoring
**Priority**: P1 (HIGH)
**Effort**: LARGE (4-5 days)
**Dependencies**: Phase 2 complete

#### Tasks:
1. **Refactor `_identify_all_files()`** (Lines 125-343)
   - Replace hardcoded `.py` extensions:
     ```python
     # BEFORE
     model_path = f"app/models/{model.name.lower()}.py"

     # AFTER
     ext = self.tech_config.get_file_extension()
     model_path = f"app/models/{model.name.lower()}{ext}"
     ```

   - Replace hardcoded directory structure:
     ```python
     # BEFORE
     files["app/core/config.py"] = FileSpecification(...)

     # AFTER
     config_dir = self.tech_config.get_config_directory()  # "app/core" or "config"
     config_file = self.tech_config.get_config_file_name()  # "config.py" or "app.php"
     files[f"{config_dir}/{config_file}"] = FileSpecification(...)
     ```

2. **Refactor all `_create_*_prompt()` methods** (Lines 447-693)
   - Replace hardcoded prompts with template lookups:
     ```python
     # BEFORE
     def _create_model_prompt(self, model, spec: DetailedSpecification) -> str:
         return f"""Generate SQLAlchemy model: {model.name}
         Include:
         - Proper imports from sqlalchemy
         """

     # AFTER
     def _create_model_prompt(self, model, spec: DetailedSpecification) -> str:
         template = self.tech_config.get_prompt_template("model")
         orm_lib = self.tech_config.get_orm_library()
         return template.format(
             model_name=model.name,
             orm_library=orm_lib,
             fields=model.fields,
             relationships=model.relationships
         )
     ```

3. **Parameterize `__init__.py` generation**
   - PHP doesn't use `__init__.py`
   - Node.js uses `index.js` in some cases
   - Make conditional:
     ```python
     if self.tech_config.needs_init_files():
         files["app/__init__.py"] = FileSpecification(...)
     ```

### Phase 4: Code Generator Refactoring
**Priority**: P1 (HIGH)
**Effort**: LARGE (4-5 days)
**Dependencies**: Phase 3 complete

#### Tasks:
1. **Refactor `_get_role_system_prompt()`** (Lines 367-549)
   - Create parameterized templates:
     ```python
     # BEFORE
     "model": """...SQLAlchemy Expert..."""

     # AFTER
     "model": {
         "python_fastapi": """...SQLAlchemy Expert...""",
         "php_laravel": """...Eloquent ORM Expert...""",
         "nodejs_express": """...Sequelize Expert..."""
     }

     def _get_role_system_prompt(self, file_type: str) -> str:
         tech_key = self.tech_config.get_tech_key()  # "python_fastapi"
         role_prompts = self.prompt_registry.get_role_prompts()
         return role_prompts[file_type][tech_key]
     ```

2. **Refactor `_get_language_instructions()`** (Lines 551-588)
   - Replace hardcoded Python/Pydantic instructions:
     ```python
     # BEFORE
     if file_type in ["model", "api_endpoint", ...]:
         return """**Python Standards:**..."""

     # AFTER
     lang = self.tech_config.backend_language
     framework = self.tech_config.backend_framework

     if file_type in ["model", "api_endpoint", ...]:
         return self.tech_config.get_coding_standards(lang, framework)
     ```

3. **Update validators**
   - `CodeValidator.validate_python()` → `CodeValidator.validate_backend()`
   - Add validators for PHP, JavaScript, Ruby, etc.
   - Use appropriate parser based on `tech_config.backend_language`

### Phase 5: Assembly Coordinator Refactoring
**Priority**: P1 (HIGH)
**Effort**: MEDIUM (2-3 days)
**Dependencies**: Phase 4 complete

#### Tasks:
1. **Refactor `_create_project_structure()`** (Lines 105-127)
   - Replace hardcoded FastAPI structure:
     ```python
     # BEFORE
     (project_dir / "app").mkdir()
     (project_dir / "app" / "api").mkdir()
     (project_dir / "app" / "schemas").mkdir()
     (project_dir / "alembic").mkdir()

     # AFTER
     for directory in self.tech_config.get_directory_structure():
         (project_dir / directory).mkdir(parents=True)
     ```

2. **Refactor `_generate_readme()`** (Lines 141-198)
   - Parameterize tech stack mentions:
     ```python
     # BEFORE
     content = f"""...using FastAPI, SQLAlchemy, and Alpine.js..."""

     # AFTER
     tech_desc = self.tech_config.get_tech_stack_description()
     content = f"""...using {tech_desc}..."""
     ```

   - Parameterize setup instructions:
     ```python
     # BEFORE
     2. Install dependencies:
        ```bash
        pip install -r requirements.txt
        ```

     # AFTER
     dep_mgr = self.tech_config.get_dependency_manager()  # "composer"
     dep_cmd = self.tech_config.get_install_command()     # "composer install"

     2. Install dependencies:
        ```bash
        {dep_cmd}
        ```
     ```

3. **Refactor `_generate_requirements()`** (Lines 227-253)
   - Generate appropriate dependency file:
     ```python
     # BEFORE
     path = project_dir / "requirements.txt"
     content = "\n".join(sorted(requirements))

     # AFTER
     dep_file = self.tech_config.get_dependency_file_name()  # "composer.json"
     dep_format = self.tech_config.get_dependency_format()   # "json" | "text" | "yaml"
     path = project_dir / dep_file

     if dep_format == "json":
         content = json.dumps({
             "require": {pkg: "^1.0" for pkg in requirements}
         }, indent=2)
     elif dep_format == "text":
         content = "\n".join(sorted(requirements))
     ```

### Phase 6: Consistency Verifier Refactoring
**Priority**: P2 (MEDIUM)
**Effort**: SMALL (1-2 days)
**Dependencies**: Phase 5 complete

#### Tasks:
1. **Refactor `_verify_code_integrity()`** (Lines 148-182)
   - Use language-appropriate parser:
     ```python
     # BEFORE
     if not str(file.path).endswith('.py'):
         continue
     ast.parse(file.content)

     # AFTER
     lang = self.tech_config.backend_language
     ext = self.tech_config.get_file_extension()

     if not str(file.path).endswith(ext):
         continue

     parser = self._get_parser_for_language(lang)
     parser.parse(file.content)
     ```

2. **Refactor `_is_import_resolvable()`** (Lines 250-277)
   - Replace hardcoded Python packages:
     ```python
     # BEFORE
     third_party = {'fastapi', 'pydantic', 'sqlalchemy', ...}

     # AFTER
     third_party = self.tech_config.get_third_party_packages()
     # Returns different set based on tech stack
     ```

3. **Refactor `_verify_dependencies()`** (Lines 279-331)
   - Replace expected FastAPI deps:
     ```python
     # BEFORE
     expected_deps = {'fastapi', 'uvicorn', 'pydantic', ...}

     # AFTER
     expected_deps = self.tech_config.get_required_dependencies()
     # Returns Laravel packages for PHP, Express packages for Node.js, etc.
     ```

---

## Implementation Strategy

### Approach: Phased Rollout with Validation Gates

#### Step 1: Create Configuration Infrastructure (Week 1)
1. Create `config/tech_stack_registry.yaml` with 3 initial stacks:
   - `python_fastapi` (existing behavior)
   - `php_laravel` (new)
   - `nodejs_express` (new)

2. Create `config/prompt_templates.yaml` with parameterized prompts

3. Create `TechStackConfig` class with comprehensive tests

4. **Validation Gate**: Unit tests for `TechStackConfig` passing at 100%

#### Step 2: Update Data Flow (Week 1)
1. Update `DetailedSpecification.get_tech_config()`
2. Update all stage constructors to accept `TechStackConfig`
3. Update orchestrator to pass `tech_config` through pipeline

4. **Validation Gate**: Integration test showing `tech_config` propagates through all 6 stages

#### Step 3: Refactor Workflow Planner (Week 2)
1. Refactor file path generation using `tech_config`
2. Refactor prompt generation using templates
3. Update tests to cover PHP and Node.js scenarios

4. **Validation Gate**:
   - Generate workflow for Python/FastAPI → produces `.py` files
   - Generate workflow for PHP/Laravel → produces `.php` files
   - Generate workflow for Node.js/Express → produces `.js` files

#### Step 4: Refactor Code Generator (Week 2-3)
1. Parameterize role prompts
2. Parameterize language instructions
3. Add multi-language validators

4. **Validation Gate**:
   - Generate Python code with `python_fastapi` config → valid Python
   - Generate PHP code with `php_laravel` config → valid PHP
   - Generate JavaScript code with `nodejs_express` config → valid JavaScript

#### Step 5: Refactor Assembly Coordinator (Week 3)
1. Dynamic directory structure
2. Dynamic README generation
3. Dynamic dependency file generation

4. **Validation Gate**:
   - Assemble Python project → FastAPI structure + requirements.txt
   - Assemble PHP project → Laravel structure + composer.json
   - Assemble Node.js project → Express structure + package.json

#### Step 6: Refactor Consistency Verifier (Week 3)
1. Multi-language parsers
2. Tech-specific package whitelists
3. Tech-specific dependency validation

4. **Validation Gate**:
   - Verify Python project → validates Python syntax, FastAPI deps
   - Verify PHP project → validates PHP syntax, Laravel deps
   - Verify Node.js project → validates JavaScript syntax, Express deps

### Rollback Strategy
Each phase builds on previous infrastructure without breaking existing functionality:

1. **Backward Compatibility**: Default `tech_config` to `python_fastapi` if not provided
2. **Feature Flags**: Enable new tech stacks via configuration flag
3. **Parallel Testing**: Run both old and new code paths, compare outputs
4. **Incremental Migration**: Migrate one stage at a time, validate before proceeding

---

## Testing Requirements

### Unit Tests (Per Phase)
1. **Phase 1**: `TechStackConfig` class
   - Test loading registry for each tech stack
   - Test file extension mapping
   - Test directory structure retrieval
   - Test prompt template retrieval

2. **Phase 2**: Data flow propagation
   - Test `DetailedSpecification.get_tech_config()` caching
   - Test stage constructor acceptance of `tech_config`

3. **Phase 3**: Workflow planner
   - Test file path generation for Python/PHP/Node.js
   - Test prompt generation for each tech stack
   - Test directory structure planning

4. **Phase 4**: Code generator
   - Test role prompt selection by tech stack
   - Test language instruction selection
   - Test multi-language validation

5. **Phase 5**: Assembly coordinator
   - Test directory creation for each tech stack
   - Test README generation with correct tech mentions
   - Test dependency file format (requirements.txt vs composer.json vs package.json)

6. **Phase 6**: Consistency verifier
   - Test syntax validation for Python/PHP/JavaScript
   - Test import resolution for each language
   - Test dependency validation

### Integration Tests (End-to-End)
1. **Python/FastAPI Stack** (baseline)
   - Input: User prompt requesting FastAPI chat app
   - Output: Complete FastAPI project with `.py` files
   - Validation: All stages execute, project structure correct

2. **PHP/Laravel Stack**
   - Input: User prompt requesting Laravel e-commerce app
   - Output: Complete Laravel project with `.php` files
   - Validation: Laravel directory structure, `composer.json`, Eloquent models

3. **Node.js/Express Stack**
   - Input: User prompt requesting Express REST API
   - Output: Complete Express project with `.js` files
   - Validation: Express directory structure, `package.json`, Sequelize models

### Regression Tests
1. **Existing Python/FastAPI Projects**
   - Ensure refactoring doesn't break existing Python code generation
   - Compare before/after outputs for identical prompts

2. **Cross-Tech-Stack Consistency**
   - Same functional requirements across 3 tech stacks
   - Verify equivalent functionality in generated projects

---

## Success Criteria

### Phase Completion Criteria

#### Phase 1 Success:
- ✅ `tech_stack_registry.yaml` exists with 3+ tech stacks
- ✅ `prompt_templates.yaml` exists with parameterized templates
- ✅ `TechStackConfig` class passes 100% unit tests
- ✅ Can load and query tech stack configurations programmatically

#### Phase 2 Success:
- ✅ `tech_config` propagates through all 6 pipeline stages
- ✅ Each stage receives correct `TechStackConfig` instance
- ✅ Integration test validates data flow

#### Phase 3 Success:
- ✅ Workflow planner generates `.py` files for Python
- ✅ Workflow planner generates `.php` files for PHP
- ✅ Workflow planner generates `.js` files for Node.js
- ✅ Prompts use tech-specific terminology (no "FastAPI" in PHP prompts)

#### Phase 4 Success:
- ✅ Code generator produces valid Python code for Python projects
- ✅ Code generator produces valid PHP code for PHP projects
- ✅ Code generator produces valid JavaScript code for Node.js projects
- ✅ Role prompts match target technology

#### Phase 5 Success:
- ✅ Assembly creates FastAPI structure for Python
- ✅ Assembly creates Laravel structure for PHP
- ✅ Assembly creates Express structure for Node.js
- ✅ Dependency files match tech stack (requirements.txt vs composer.json vs package.json)

#### Phase 6 Success:
- ✅ Verifier validates Python syntax for Python projects
- ✅ Verifier validates PHP syntax for PHP projects
- ✅ Verifier validates JavaScript syntax for Node.js projects
- ✅ Dependency checks use tech-specific package lists

### Overall Success Metrics:

#### Quantitative:
- **Tech Stack Support**: 3+ fully supported (Python/FastAPI, PHP/Laravel, Node.js/Express)
- **Code Quality**: Generated code passes language-specific linters (pylint, phpcs, eslint)
- **Test Coverage**: 90%+ coverage for refactored code
- **Hardcoding Violations**: 0 (down from 177)

#### Qualitative:
- **User Experience**: User specifies "PHP Laravel" → receives working Laravel project
- **Consistency**: Equivalent features across all tech stacks
- **Maintainability**: Adding new tech stack requires only updating YAML configs
- **Documentation**: Clear guide for adding new tech stacks

---

## Appendix A: Hardcoding Violation Summary Table

| File | Stage | Total Lines | Violations | Violation Density | Severity |
|------|-------|-------------|-----------|-------------------|----------|
| `prompt_analyzer.py` | 1 | 378 | 0 | 0% | ✅ CLEAN |
| `requirement_elaborator.py` | 2 | 687 | 12 | 1.7% | ⚠️ PARTIAL |
| `workflow_planner.py` | 3 | 714 | 73 | 10.2% | ❌ SEVERE |
| `llm_code_generator.py` | 4 | 665 | 60 | 9.0% | ❌ SEVERE |
| `assembly_coordinator.py` | 5 | 281 | 23 | 8.2% | ❌ SEVERE |
| `consistency_verifier.py` | 6 | 548 | 9 | 1.6% | ❌ SEVERE |
| **TOTAL** | **1-6** | **3273** | **177** | **5.4%** | **❌ CRITICAL** |

## Appendix B: Example Before/After Code Snippets

### Before (Hardcoded)
```python
# workflow_planner.py - Line 164
model_path = f"app/models/{model.name.lower()}.py"

# assembly_coordinator.py - Line 148
content = f"""This is a fully generated web application using FastAPI, SQLAlchemy, and Alpine.js."""

# llm_code_generator.py - Line 371
"model": """You are a highly experienced database architect specializing in SQLAlchemy ORM design."""
```

### After (Tech-Agnostic)
```python
# workflow_planner.py
ext = self.tech_config.get_file_extension()  # .py | .php | .js
model_path = f"app/models/{model.name.lower()}{ext}"

# assembly_coordinator.py
tech_desc = self.tech_config.get_tech_stack_description()
content = f"""This is a fully generated web application using {tech_desc}."""

# llm_code_generator.py
tech_key = self.tech_config.get_tech_key()  # "python_fastapi" | "php_laravel" | "nodejs_express"
role_prompts = self.prompt_registry.get_role_prompts()
role_prompt = role_prompts["model"][tech_key]
# Returns: "...SQLAlchemy Expert" for Python, "...Eloquent Expert" for PHP
```

---

## Document History
- **Version**: 1.0
- **Date**: 2025-11-27
- **Author**: Audit System
- **Status**: INITIAL AUDIT COMPLETE
- **Next Review**: After Phase 1 completion

---

**END OF COMPREHENSIVE HARDCODING AUDIT**
