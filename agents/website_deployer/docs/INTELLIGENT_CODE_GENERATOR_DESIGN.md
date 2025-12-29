# Intelligent Code Generator Agent Design
## Multi-Stage LLM-Based Code Generation System

**Version:** 2.0.0
**Date:** 2025-11-25
**Status:** Design Document

---

## Overview

This document describes the new **Intelligent Code Generator Agent** - a sophisticated multi-stage system that:

1. **Dissects** user prompts into detailed requirements
2. **Elaborates** missing details and asks clarifying questions
3. **Plans** step-by-step generation workflow
4. **Generates** each file/function using targeted LLM prompts
5. **Assembles** all components into a complete application
6. **Verifies** consistency and correctness
7. **Deploys** the validated application

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 INTELLIGENT CODE GENERATOR AGENT                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Stage 1: PROMPT ANALYZER                                        │
│  ├─ Dissect user prompt into atomic requirements                │
│  ├─ Identify ambiguities and missing details                    │
│  └─ Ask clarifying questions interactively                      │
│                          ↓                                        │
│  Stage 2: REQUIREMENT ELABORATOR                                 │
│  ├─ Expand brief descriptions into detailed specifications      │
│  ├─ Fill in technical details (APIs, data flows, state mgmt)   │
│  └─ Create component hierarchy and relationships                │
│                          ↓                                        │
│  Stage 3: WORKFLOW PLANNER                                       │
│  ├─ Break down into generation steps                            │
│  ├─ Determine file dependencies                                 │
│  ├─ Create generation order (topological sort)                  │
│  └─ Prepare targeted prompts for each component                 │
│                          ↓                                        │
│  Stage 4: LLM CODE GENERATOR                                     │
│  ├─ Generate each file using specialized prompts                │
│  ├─ Maintain context across related files                       │
│  ├─ Apply coding standards and best practices                   │
│  └─ Generate tests for each component                           │
│                          ↓                                        │
│  Stage 5: ASSEMBLY COORDINATOR                                   │
│  ├─ Collect all generated files                                 │
│  ├─ Verify file structure completeness                          │
│  ├─ Check imports and dependencies                              │
│  └─ Integrate configuration files                               │
│                          ↓                                        │
│  Stage 6: CONSISTENCY VERIFIER                                   │
│  ├─ Cross-check generated code against requirements             │
│  ├─ Verify API contracts match across frontend/backend          │
│  ├─ Validate database schema matches models                     │
│  └─ Check security implementations                              │
│                          ↓                                        │
│  Stage 7: DEPLOYMENT ORCHESTRATOR                                │
│  └─ Trigger existing deployment pipeline                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Prompt Analyzer

### Purpose
Transform vague user descriptions into detailed, structured requirements.

### Process
1. **Parse** user prompt into semantic units
2. **Identify** UI components, features, data flows, integrations
3. **Detect** ambiguities (e.g., "chat window" - WebSocket? SSE? Polling?)
4. **Question** user for clarification
5. **Expand** shorthand into explicit requirements

### Example

**Input:**
```
Build a ChatGPT-like interface for my Flask server
```

**Analysis Output:**
```json
{
  "components": {
    "ui": {
      "layout": "multi-pane",
      "panes": {
        "left": "conversation_history",
        "center": "chat_window",
        "right": "agent_selector"
      }
    },
    "features": {
      "chat": {
        "streaming": "AMBIGUOUS - method not specified",
        "file_upload": "mentioned but format unclear",
        "response_actions": ["copy", "regenerate", "save"]
      }
    }
  },
  "clarifications_needed": [
    {
      "question": "How should responses stream?",
      "options": ["Server-Sent Events", "WebSocket", "Long polling"],
      "context": "Affects backend architecture and client-side implementation"
    },
    {
      "question": "What file types can users upload?",
      "options": ["Images only", "Documents (PDF, TXT)", "Any file type"],
      "context": "Determines file validation and storage strategy"
    }
  ]
}
```

### Implementation
**File:** `stages/intelligent_generators/prompt_analyzer.py`

```python
class PromptAnalyzer:
    """Dissects user prompts and identifies ambiguities."""

    def analyze(self, user_prompt: str) -> PromptAnalysis:
        # Use LLM to extract structured requirements
        # Identify missing details
        # Generate clarifying questions
        pass
```

---

## Stage 2: Requirement Elaborator

### Purpose
Fill in technical details and create comprehensive specifications.

### Process
1. **Expand** component descriptions into technical specs
2. **Define** data models and API contracts
3. **Specify** state management strategy
4. **Detail** authentication and authorization flows
5. **Create** component interaction diagrams

### Example

**Input (from Stage 1):**
```
"chat window with streaming responses"
```

**Elaboration Output:**
```json
{
  "component": "chat_window",
  "technical_spec": {
    "frontend": {
      "framework": "Alpine.js",
      "state": {
        "messages": "array",
        "streaming_message": "string",
        "is_streaming": "boolean"
      },
      "events": {
        "on_message_send": "POST /api/chat/send",
        "on_stream_start": "EventSource('/api/chat/stream')",
        "on_file_upload": "POST /api/chat/upload (multipart)"
      },
      "ui_elements": [
        "scrollable_message_container",
        "message_bubble (user/assistant variants)",
        "input_textarea with auto-resize",
        "file_upload_button with preview",
        "send_button (disabled during streaming)"
      ]
    },
    "backend": {
      "endpoints": [
        {
          "path": "/api/chat/send",
          "method": "POST",
          "body": {"message": "string", "conversation_id": "uuid"},
          "response": {"message_id": "uuid", "stream_url": "string"}
        },
        {
          "path": "/api/chat/stream",
          "method": "GET",
          "params": {"message_id": "uuid"},
          "response": "text/event-stream"
        }
      ],
      "streaming_impl": {
        "method": "Server-Sent Events",
        "chunk_strategy": "word-by-word with 50ms delay",
        "error_handling": "reconnection with exponential backoff"
      }
    },
    "data_flow": {
      "1": "User types message",
      "2": "Frontend validates (non-empty, max 4000 chars)",
      "3": "POST to /api/chat/send",
      "4": "Backend creates message record, returns stream URL",
      "5": "Frontend opens EventSource to stream URL",
      "6": "Backend streams LLM response chunks",
      "7": "Frontend appends chunks to streaming_message",
      "8": "On stream complete, save to messages array",
      "9": "Update conversation in database"
    }
  }
}
```

### Implementation
**File:** `stages/intelligent_generators/requirement_elaborator.py`

```python
class RequirementElaborator:
    """Expands requirements into detailed technical specifications."""

    def elaborate(self, prompt_analysis: PromptAnalysis) -> DetailedSpecification:
        # For each component, generate detailed spec
        # Define data flows
        # Specify API contracts
        # Create state management plan
        pass
```

---

## Stage 3: Workflow Planner

### Purpose
Create step-by-step generation plan with proper dependencies.

### Process
1. **Identify** all files to generate
2. **Determine** dependencies between files
3. **Create** generation order (topological sort)
4. **Prepare** targeted prompts for each file
5. **Group** related files for context sharing

### Example

**Generation Plan:**
```yaml
generation_workflow:
  phase_1_foundation:
    - file: app/core/config.py
      dependencies: []
      prompt: "Generate FastAPI settings with database URL, JWT secret, CORS origins"

    - file: app/models/__init__.py
      dependencies: []
      prompt: "Generate SQLAlchemy base model class"

  phase_2_data_models:
    - file: app/models/user.py
      dependencies: [app/models/__init__.py]
      prompt: "Generate User model with: id, email, password_hash, created_at. Include password hashing methods."

    - file: app/models/conversation.py
      dependencies: [app/models/__init__.py, app/models/user.py]
      prompt: "Generate Conversation model linked to User. Fields: id, user_id, title, created_at."

    - file: app/models/message.py
      dependencies: [app/models/__init__.py, app/models/conversation.py, app/models/user.py]
      prompt: "Generate Message model. Fields: id, conversation_id, role (user/assistant), content, created_at."

  phase_3_api_schemas:
    - file: app/schemas/chat.py
      dependencies: [app/models/message.py]
      prompt: "Generate Pydantic schemas for chat: MessageCreate, MessageResponse, StreamChunk"

  phase_4_crud_operations:
    - file: app/crud/conversation.py
      dependencies: [app/models/conversation.py, app/models/message.py]
      prompt: "Generate CRUD for conversations: create, get, list, add_message"

  phase_5_api_endpoints:
    - file: app/api/endpoints/chat.py
      dependencies: [app/schemas/chat.py, app/crud/conversation.py, app/core/config.py]
      prompt: |
        Generate FastAPI endpoints:
        - POST /api/chat/send: Create message, start LLM processing, return stream URL
        - GET /api/chat/stream: Server-Sent Events streaming endpoint
        - POST /api/chat/upload: Handle file uploads (images/documents)
        Include error handling, rate limiting, authentication.

  phase_6_frontend_templates:
    - file: app/templates/base.html
      dependencies: []
      prompt: "Generate base HTML with Tailwind CSS, Alpine.js CDN, navigation bar"

    - file: app/templates/components/chat_window.html
      dependencies: [app/templates/base.html]
      prompt: |
        Generate chat window component:
        - Scrollable message container (auto-scroll to bottom)
        - Message bubbles (user: right-aligned blue, assistant: left-aligned gray)
        - Streaming message display (typewriter effect)
        - Input textarea with file upload button
        - Send button (disabled during streaming)
        Alpine.js data: messages[], streamingMessage, isStreaming

  phase_7_frontend_javascript:
    - file: app/static/js/chat.js
      dependencies: [app/api/endpoints/chat.py]
      prompt: |
        Generate Alpine.js component for chat:
        - sendMessage() function (POST to /api/chat/send)
        - streamResponse() function (EventSource for /api/chat/stream)
        - uploadFile() function (FormData upload)
        - Message state management
        - Error handling with user-friendly messages

  phase_8_configuration:
    - file: alembic/versions/001_initial_schema.py
      dependencies: [app/models/user.py, app/models/conversation.py, app/models/message.py]
      prompt: "Generate Alembic migration for User, Conversation, Message tables"

    - file: .env.example
      dependencies: [app/core/config.py]
      prompt: "Generate .env.example with all required environment variables"
```

### Implementation
**File:** `stages/intelligent_generators/workflow_planner.py`

```python
class WorkflowPlanner:
    """Creates dependency-aware generation workflow."""

    def plan(self, detailed_spec: DetailedSpecification) -> GenerationWorkflow:
        # Extract all components
        # Build dependency graph
        # Topologically sort
        # Create targeted prompts
        # Group into phases
        pass
```

---

## Stage 4: LLM Code Generator

### Purpose
Generate each file using specialized, context-aware LLM prompts.

### Process
1. **Iterate** through generation workflow phases
2. **Prepare** context (previously generated files)
3. **Create** targeted prompt with examples
4. **Generate** code using LLM
5. **Validate** syntax and structure
6. **Store** for next phase context

### Prompt Engineering Strategy

#### Prompt Template Structure
```python
GENERATION_PROMPT = """
# Task: Generate {file_path}

## Context
Previously generated files:
{context_files}

## Requirements
{detailed_requirements}

## Technical Specifications
- Framework: {framework}
- Dependencies: {dependencies}
- Integration Points: {integration_points}

## Code Standards
- Use type hints for all functions
- Include docstrings (Google style)
- Error handling with specific exceptions
- Logging at appropriate levels
- Security: validate inputs, sanitize outputs

## Example Pattern
{example_code}

## Generate Complete File
Provide production-ready code for {file_path}.
Include all imports, error handling, and documentation.
"""
```

#### Context Management
```python
class GenerationContext:
    """Manages context across file generations."""

    def __init__(self):
        self.generated_files = {}
        self.api_contracts = {}
        self.data_models = {}

    def add_file(self, path: str, content: str):
        """Add generated file to context."""
        self.generated_files[path] = content
        self._extract_contracts(path, content)

    def get_context_for(self, file_path: str) -> str:
        """Get relevant context for generating file."""
        # Return related files based on dependencies
        pass
```

### Implementation
**File:** `stages/intelligent_generators/llm_code_generator.py`

```python
class LLMCodeGenerator:
    """Generates code files using LLM with context awareness."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.context = GenerationContext()

    def generate_file(self,
                     file_spec: FileSpecification,
                     workflow: GenerationWorkflow) -> GeneratedFile:
        """Generate single file with context."""

        # Prepare context from dependencies
        context = self._prepare_context(file_spec.dependencies)

        # Build targeted prompt
        prompt = self._build_prompt(file_spec, context)

        # Generate code
        code = self.llm.generate(prompt)

        # Validate
        if not self._validate_code(code, file_spec):
            # Retry with error feedback
            code = self._regenerate_with_fixes(code, file_spec)

        # Store in context
        self.context.add_file(file_spec.path, code)

        return GeneratedFile(path=file_spec.path, content=code)
```

---

## Stage 5: Assembly Coordinator

### Purpose
Collect all generated files and create project structure.

### Process
1. **Create** directory structure
2. **Write** all generated files
3. **Generate** supporting files (README, .gitignore, etc.)
4. **Create** requirements.txt from dependencies
5. **Verify** file structure completeness

### Implementation
**File:** `stages/intelligent_generators/assembly_coordinator.py`

```python
class AssemblyCoordinator:
    """Assembles generated files into complete project."""

    def assemble(self,
                generated_files: List[GeneratedFile],
                project_name: str) -> AssembledProject:

        project_dir = Path("generated_projects") / project_name

        # Create directory structure
        self._create_directories(project_dir)

        # Write all generated files
        for file in generated_files:
            self._write_file(project_dir / file.path, file.content)

        # Generate supporting files
        self._generate_readme(project_dir)
        self._generate_gitignore(project_dir)
        self._generate_requirements(project_dir, generated_files)

        return AssembledProject(path=project_dir, files=generated_files)
```

---

## Stage 6: Consistency Verifier

### Purpose
Verify generated code is consistent and correct relative to requirements.

### Process
1. **API Contract Verification**
   - Frontend API calls match backend endpoints
   - Request/response schemas match
   - Authentication methods consistent

2. **Database Schema Verification**
   - Models match migration files
   - Foreign keys properly defined
   - Relationships bidirectional

3. **Security Verification**
   - Authentication implemented
   - Authorization checks present
   - Input validation in place
   - SQL injection prevention

4. **UI Requirements Verification**
   - All specified components present
   - Layout matches description
   - Features implemented

### Verification Strategy

#### API Contract Check
```python
def verify_api_contracts(self, project: AssembledProject) -> List[Issue]:
    issues = []

    # Extract frontend API calls
    frontend_calls = self._extract_api_calls_from_templates(project)

    # Extract backend endpoints
    backend_endpoints = self._extract_endpoints_from_api(project)

    # Cross-check
    for call in frontend_calls:
        if call.endpoint not in backend_endpoints:
            issues.append(Issue(
                severity="ERROR",
                location=call.file,
                message=f"Frontend calls {call.endpoint} but endpoint not defined"
            ))

    return issues
```

#### Requirements Coverage Check
```python
def verify_requirements_coverage(self,
                                project: AssembledProject,
                                requirements: DetailedSpecification) -> CoverageReport:

    coverage = CoverageReport()

    # Check UI components
    for component in requirements.ui_components:
        if not self._component_exists_in_templates(project, component):
            coverage.missing_components.append(component)

    # Check features
    for feature in requirements.features:
        if not self._feature_implemented(project, feature):
            coverage.missing_features.append(feature)

    return coverage
```

### Implementation
**File:** `stages/intelligent_generators/consistency_verifier.py`

```python
class ConsistencyVerifier:
    """Verifies generated code consistency and correctness."""

    def verify(self,
              project: AssembledProject,
              requirements: DetailedSpecification) -> VerificationReport:

        report = VerificationReport()

        # API contracts
        report.api_issues = self._verify_api_contracts(project)

        # Database schema
        report.schema_issues = self._verify_schema_consistency(project)

        # Security
        report.security_issues = self._verify_security(project)

        # Requirements coverage
        report.coverage = self._verify_requirements_coverage(project, requirements)

        return report
```

---

## Stage 7: Deployment Orchestrator

### Purpose
Trigger deployment only after verification passes.

### Process
1. **Check** verification report
2. **Fix** any critical issues (regenerate affected files)
3. **Trigger** existing deployment pipeline
4. **Monitor** deployment progress

### Implementation
Uses existing `deployment_orchestrator.py` after verification passes.

---

## Complete System Integration

### Main Orchestrator
**File:** `stages/intelligent_code_generator.py`

```python
class IntelligentCodeGenerator:
    """
    Multi-stage intelligent code generation system.

    Transforms user prompts into deployed applications through:
    1. Prompt analysis and clarification
    2. Requirement elaboration
    3. Workflow planning
    4. LLM-based code generation
    5. Assembly and verification
    6. Deployment
    """

    def __init__(self):
        self.prompt_analyzer = PromptAnalyzer()
        self.elaborator = RequirementElaborator()
        self.planner = WorkflowPlanner()
        self.generator = LLMCodeGenerator(LLMClient())
        self.assembler = AssemblyCoordinator()
        self.verifier = ConsistencyVerifier()

    def generate(self, user_prompt: str, interactive: bool = True) -> DeploymentResult:
        """
        Generate complete application from user prompt.

        Args:
            user_prompt: User's description of desired application
            interactive: If True, ask clarifying questions

        Returns:
            DeploymentResult with deployed application details
        """

        logger.info("=" * 60)
        logger.info("INTELLIGENT CODE GENERATION STARTED")
        logger.info("=" * 60)

        # Stage 1: Analyze prompt
        logger.info("[1/7] Analyzing prompt...")
        analysis = self.prompt_analyzer.analyze(user_prompt)

        if interactive and analysis.clarifications_needed:
            logger.info("Clarifications needed:")
            analysis = self._ask_clarifications(analysis)

        # Stage 2: Elaborate requirements
        logger.info("[2/7] Elaborating requirements...")
        detailed_spec = self.elaborator.elaborate(analysis)

        if interactive:
            logger.info("Generated specification:")
            self._show_specification_summary(detailed_spec)
            if not self._confirm_proceed():
                return DeploymentResult(success=False, message="User cancelled")

        # Stage 3: Plan workflow
        logger.info("[3/7] Planning generation workflow...")
        workflow = self.planner.plan(detailed_spec)
        logger.info(f"  → {len(workflow.phases)} phases, {workflow.total_files} files")

        # Stage 4: Generate code
        logger.info("[4/7] Generating code files...")
        generated_files = []
        for phase_num, phase in enumerate(workflow.phases, 1):
            logger.info(f"  Phase {phase_num}/{len(workflow.phases)}: {phase.name}")
            for file_spec in phase.files:
                logger.info(f"    Generating {file_spec.path}...")
                generated_file = self.generator.generate_file(file_spec, workflow)
                generated_files.append(generated_file)

        logger.info(f"  → Generated {len(generated_files)} files")

        # Stage 5: Assemble project
        logger.info("[5/7] Assembling project...")
        project = self.assembler.assemble(generated_files, detailed_spec.project_name)

        # Stage 6: Verify consistency
        logger.info("[6/7] Verifying consistency...")
        verification = self.verifier.verify(project, detailed_spec)

        if verification.has_critical_issues():
            logger.warning("Critical issues found, attempting fixes...")
            project = self._fix_issues(project, verification)
            verification = self.verifier.verify(project, detailed_spec)

        self._show_verification_report(verification)

        if not verification.is_acceptable():
            return DeploymentResult(
                success=False,
                message="Verification failed",
                verification_report=verification
            )

        # Stage 7: Deploy
        logger.info("[7/7] Deploying application...")
        deployment_result = self._deploy(project, detailed_spec)

        logger.info("=" * 60)
        logger.info("INTELLIGENT CODE GENERATION COMPLETE")
        logger.info("=" * 60)

        return deployment_result
```

---

## Usage Example

```python
from stages.intelligent_code_generator import IntelligentCodeGenerator

generator = IntelligentCodeGenerator()

user_prompt = """
Build a website as the frontend to ~/Development/flaskserver server and OpenAI API LLMs:

a) Left sidebar: Settings, past conversations, user profile
b) Middle pane: Chat window with streaming responses, file upload, copy/regenerate buttons
c) Right sidebar: Agent list from server, interactive forms
d) Bottom status bar for agent execution status

Similar to OpenAI ChatGPT interface.
"""

# This will:
# 1. Analyze prompt, ask clarifying questions
# 2. Generate detailed specifications
# 3. Create generation workflow
# 4. Generate each file using LLM
# 5. Assemble complete project
# 6. Verify consistency
# 7. Deploy to server

result = generator.generate(user_prompt, interactive=True)

if result.success:
    print(f"✅ Deployed at: {result.url}")
else:
    print(f"❌ Failed: {result.message}")
```

---

## Testing Strategy

### Unit Tests
- Test each stage independently
- Mock LLM responses
- Verify prompt construction
- Test verification logic

### Integration Tests
- Test full pipeline with simple spec
- Test with complex ChatGPT-like spec
- Test error handling and regeneration
- Test verification failure paths

### Test Files
```
tests/intelligent_generators/
├── test_prompt_analyzer.py
├── test_requirement_elaborator.py
├── test_workflow_planner.py
├── test_llm_code_generator.py
├── test_assembly_coordinator.py
├── test_consistency_verifier.py
└── test_intelligent_code_generator_integration.py
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create `intelligent_generators/` directory structure
- [ ] Implement `PromptAnalyzer`
- [ ] Implement `RequirementElaborator`
- [ ] Write unit tests

### Phase 2: Planning & Generation (Week 2)
- [ ] Implement `WorkflowPlanner`
- [ ] Implement `LLMCodeGenerator` with context management
- [ ] Implement prompt templates
- [ ] Write generation tests

### Phase 3: Assembly & Verification (Week 3)
- [ ] Implement `AssemblyCoordinator`
- [ ] Implement `ConsistencyVerifier`
- [ ] Write verification tests
- [ ] Integration testing

### Phase 4: Integration & Testing (Week 4)
- [ ] Implement main `IntelligentCodeGenerator` orchestrator
- [ ] End-to-end testing with ChatGPT-like spec
- [ ] Performance optimization
- [ ] Documentation

---

## Success Criteria

- [ ] User's ChatGPT-like specification generates correct UI
- [ ] All UI components present and functional
- [ ] API contracts consistent between frontend/backend
- [ ] Streaming responses work correctly
- [ ] Agent integration functional
- [ ] No placeholder code in generated output
- [ ] Verification catches inconsistencies
- [ ] Deployment succeeds after verification passes

---

## Next Steps

1. Review this design document
2. Get user approval on architecture
3. Begin Phase 1 implementation
4. Create first working version with user's spec

---

**Document Status:** Ready for Review
**Author:** Website Deployment Agent Development Team
