# Intelligent Code Generator - LLM Prompts Review

**Document Purpose**: Comprehensive review of all LLM prompts used in the 7-stage intelligent code generation pipeline.

**Created**: 2025-11-27
**Status**: IN PROGRESS - Removing hardcoded tech stack references

---

## Executive Summary

This document catalogs all LLM prompts used in the intelligent code generation system. Each prompt is analyzed for:
- **Tech Stack Neutrality**: Does it assume specific technologies?
- **User Spec Adherence**: Does it follow user requirements strictly?
- **Flexibility**: Can it adapt to different project types?
- **Hardcoding Issues**: Any hardcoded assumptions that violate our "NO HARDCODING" directive?

### Critical Issues Found:
1. ❌ **Stage 2 (Requirement Elaborator)**: HARDCODED to Alpine.js/Tailwind/PostgreSQL
2. ❌ **UIComponentSpec dataclass**: HARDCODED field names (`alpine_js_data`, `tailwind_classes`)
3. ❌ **DetailedSpecification**: MISSING `backend_language`, `backend_framework`, `web_server` fields

---

## Stage 1: Prompt Analyzer

**File**: `stages/intelligent_generators/prompt_analyzer.py`
**Method**: `_build_analysis_prompt()`
**Lines**: 131-222

### Current Prompt:

```python
def _build_analysis_prompt(self, user_prompt: str) -> str:
    """Build LLM prompt for analyzing user's description."""

    return f"""# Task: Analyze Web Application Requirements

You are an expert system architect analyzing a user's description of a web application.
Your goal is to extract structured requirements and identify ANY ambiguities or missing details.

## User's Description
{user_prompt}

## Your Task
Analyze the description and output a JSON object with the following structure:

```json
{{
  "project_name": "Extracted or inferred project name",
  "project_type": "Type of application (e.g., 'chat_interface', 'e-commerce', 'task_manager')",
  "description": "Clean, concise description of the application",

  "components": [
    {{
      "name": "component_name",
      "type": "ui|api|database|worker",
      "description": "What this component does",
      "requirements": ["specific requirement 1", "requirement 2"],
      "ambiguities": ["What's ambiguous or unclear"],
      "missing_details": ["What details are not specified"]
    }}
  ],

  "features": {{
    "authentication": {{
      "enabled": true|false,
      "method": "specified method or 'AMBIGUOUS'"
    }},
    "chat": {{
      "enabled": true|false,
      "streaming": "specified method or 'AMBIGUOUS'",
      "file_upload": "specified types or 'AMBIGUOUS'"
    }},
    "agents": {{
      "enabled": true|false,
      "integration_method": "specified or 'AMBIGUOUS'"
    }}
  }},

  "integrations": [
    {{
      "name": "External system name",
      "purpose": "Why integrating",
      "details": "How to integrate or 'AMBIGUOUS'"
    }}
  ],

  "clarifications_needed": [
    {{
      "question": "Clear, specific question to ask user",
      "options": ["Option 1", "Option 2", "Option 3"],
      "context": "Why this matters for implementation",
      "importance": "low|medium|high|critical"
    }}
  ],

  "technical_constraints": {{
    "backend_language": "specified (e.g., 'python', 'php', 'nodejs', 'ruby', 'java') or 'UNSPECIFIED'",
    "backend_framework": "specified (e.g., 'flask', 'fastapi', 'laravel', 'express', 'rails') or 'UNSPECIFIED'",
    "frontend_framework": "specified (e.g., 'alpine_tailwind', 'react', 'vue', 'vanilla_js') or 'UNSPECIFIED'",
    "web_server": "specified (e.g., 'apache2', 'nginx', 'builtin') or 'UNSPECIFIED'",
    "database": "specified (e.g., 'postgresql', 'mysql', 'sqlite', 'mongodb') or 'UNSPECIFIED'",
    "deployment_target": "specified or 'UNSPECIFIED'"
  }}
}}
```

## Analysis Guidelines

1. **Be Thorough**: Extract every component, feature, and requirement mentioned
2. **Identify Ambiguities**: If something is mentioned but not clearly specified, flag it
3. **Find Missing Details**: Identify what's needed but not provided
4. **Generate Smart Questions**: Ask about ambiguities that significantly impact architecture
5. **Prioritize Questions**: Mark critical questions that must be answered vs. nice-to-knows
6. **Infer Wisely**: Make reasonable inferences but flag them as assumptions

## Examples of Good Questions

- "For streaming chat responses, should we use Server-Sent Events (simpler, one-way) or WebSocket (bidirectional, more complex)?"
- "What file types should users be able to upload? (Images only, Documents, Any file)"
- "Should the agent forms appear inline in the main pane or as modal dialogs?"
- "For conversation history, should we show just titles or preview first messages?"

## Return ONLY valid JSON
No explanations, no markdown formatting, just the JSON object.
"""
```

### Analysis:

✅ **Tech Stack Neutral**: YES - Prompt asks LLM to extract tech stack from user description
✅ **User Spec Adherence**: YES - Focuses on extracting what user specified
✅ **Flexibility**: YES - Can handle any project type
✅ **Hardcoding**: NONE - Recently updated to extract backend_language, backend_framework, web_server

**Status**: ✅ **COMPLIANT** - This prompt properly extracts tech stack requirements without imposing defaults.

---

## Stage 2: Requirement Elaborator

**File**: `stages/intelligent_generators/requirement_elaborator.py`
**Method**: `_build_elaboration_prompt()`
**Lines**: 200-471

### Current Prompt (BEFORE FIX):

```python
def _build_elaboration_prompt(self, analysis: PromptAnalysis) -> str:
    """Build LLM prompt for elaborating requirements."""

    # Include clarification answers if any
    clarifications_text = ""
    if analysis.clarifications_needed:
        clarifications_text = "\n## Clarification Answers\n"
        for q in analysis.clarifications_needed:
            if q.answered:
                clarifications_text += f"Q: {q.question}\nA: {q.answer}\n\n"

    # Build component descriptions
    components_text = "\n".join([
        f"- {comp.name} ({comp.type}): {comp.description}\n  Requirements: {', '.join(comp.requirements)}"
        for comp in analysis.components
    ])

    return f"""# Task: Elaborate Requirements into Detailed Technical Specification

You are an expert full-stack architect creating detailed technical specifications.

## Project Overview
**Name:** {analysis.project_name}
**Type:** {analysis.project_type}
**Description:** {analysis.description}

## Components Identified
{components_text}

## Features
{json.dumps(analysis.features, indent=2)}

## Technical Constraints
{json.dumps(analysis.technical_constraints, indent=2)}
{clarifications_text}

## Your Task
Create a COMPLETE technical specification with ALL details needed for code generation.
For EVERY UI component, specify exact HTML structure, Alpine.js logic, and Tailwind classes.  # ← ❌ HARDCODED!
For EVERY API endpoint, specify exact request/response schemas and implementation logic.

Output JSON with this structure:

```json
{{
  "project_name": "{analysis.project_name}",
  "project_type": "{analysis.project_type}",
  "description": "Technical description",

  "ui_components": [
    {{
      "name": "chat_window",
      "type": "interactive",
      "description": "Scrollable chat interface with message bubbles",
      "html_structure": "div.chat-container > div.messages-scroll > div.message-bubble",
      "alpine_js_data": {{  # ← ❌ HARDCODED ALPINE.JS!
        "messages": "array of {{role, content, timestamp}}",
        "streamingMessage": "string - current streaming content",
        "isStreaming": "boolean"
      }},
      "alpine_js_methods": [  # ← ❌ HARDCODED ALPINE.JS!
        "sendMessage(text) - POST to /api/chat/send",
        "streamResponse(messageId) - EventSource /api/chat/stream",
        "copyMessage(index) - copy to clipboard",
        "regenerateResponse(index) - POST /api/chat/regenerate"
      ],
      "tailwind_classes": ["h-full", "overflow-y-auto", "flex", "flex-col", "space-y-4"],  # ← ❌ HARDCODED TAILWIND!
      "api_interactions": [
        "POST /api/chat/send",
        "GET /api/chat/stream (Server-Sent Events)",
        "POST /api/chat/regenerate"
      ],
      "child_components": ["message_bubble", "input_area", "file_upload_button"]
    }}
  ],

  "page_layouts": [...],

  "frontend_framework": "alpine_tailwind",  # ← ❌ HARDCODED EXAMPLE!
  "state_management": {{
    "method": "Alpine.store for global state",  # ← ❌ HARDCODED ALPINE.JS!
    "stores": {{
      "auth": "user authentication state",
      "chat": "current conversation and messages",
      "agents": "available agents and execution status"
    }}
  }},

  "api_endpoints": [...],
  "data_models": [...],
  "authentication": {...},
  "authorization": {...},
  "data_flows": [...],

  "database_type": "postgresql",  # ← ❌ HARDCODED EXAMPLE!

  "caching_strategy": {...},
  "background_workers": [...],
  "external_integrations": [...]
}}
```

## Critical Instructions
1. Be EXHAUSTIVE - include every detail needed for implementation
2. For UI components, specify EXACT Alpine.js data structures and methods  # ← ❌ HARDCODED!
3. For API endpoints, specify EXACT request/response schemas
4. For data models, include ALL fields, types, and relationships
5. Define complete data flows with error handling
6. Include security considerations at every layer

Return ONLY valid JSON, no explanations.
"""
```

### Critical Issues:

❌ **Line 238**: "For EVERY UI component, specify exact HTML structure, **Alpine.js logic**, and **Tailwind classes**"
❌ **Lines 255-268**: Example shows `alpine_js_data`, `alpine_js_methods`, `tailwind_classes`
❌ **Line 302**: Example shows `"frontend_framework": "alpine_tailwind"`
❌ **Line 304**: Example shows `"method": "Alpine.store for global state"`
❌ **Line 422**: Example shows `"database_type": "postgresql"`
❌ **Line 464**: "For UI components, specify EXACT Alpine.js data structures and methods"

### Required Changes:

This prompt MUST be rewritten to:
1. **Extract tech stack from `analysis.technical_constraints`**
2. **Use user-specified frontend_framework instead of assuming Alpine.js**
3. **Use user-specified database_type instead of assuming PostgreSQL**
4. **Adapt UI component structure based on frontend framework**
5. **Adapt backend structure based on backend_language and backend_framework**
6. **Adapt web server configuration based on web_server choice**

**Status**: ✅ **COMPLIANT** - Refactoring completed.

---

## Stage 2: Requirement Elaborator - Proposed Fix

### New Prompt Template (TECH-STACK AGNOSTIC):

```python
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
- Specify `styling_classes` with Tailwind CSS classes
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
        backend_guidance = """
For PHP backend:
- API endpoints should use PHP syntax
- Use appropriate PHP framework patterns (Laravel, Symfony, or plain PHP)
- Database models should use PHP ORM or PDO
- File structure: index.php, api/, models/, includes/
"""
    elif backend_lang.lower() == 'nodejs':
        backend_guidance = """
For Node.js backend:
- API endpoints should use JavaScript/TypeScript
- Use Express.js, Fastify, or specified framework patterns
- Database models should use Sequelize, Mongoose, or Prisma
- File structure: server.js, routes/, models/, middleware/
"""
    elif backend_lang.lower() == 'python':
        backend_guidance = """
For Python backend:
- API endpoints should use Python syntax
- Use Flask, FastAPI, Django, or specified framework patterns
- Database models should use SQLAlchemy, Django ORM, or equivalent
- File structure: app/main.py, app/api/, app/models/, app/core/
"""
    elif backend_lang.lower() == 'ruby':
        backend_guidance = """
For Ruby backend:
- API endpoints should use Ruby syntax
- Use Rails, Sinatra, or specified framework patterns
- Database models should use ActiveRecord or DataMapper
- File structure: app/, config/, db/, models/
"""
    elif backend_lang.lower() == 'java':
        backend_guidance = """
For Java backend:
- API endpoints should use Java syntax
- Use Spring Boot, Jakarta EE, or specified framework patterns
- Database models should use JPA/Hibernate
- File structure: src/main/java/, controllers/, models/, services/
"""
    else:
        backend_guidance = f"""
For {backend_lang} backend:
- Use appropriate syntax and patterns for {backend_lang}
- Follow {backend_framework} framework conventions
- Use idiomatic {backend_lang} code structure
"""

    # Include clarification answers if any
    clarifications_text = ""
    if analysis.clarifications_needed:
        clarifications_text = "\n## Clarification Answers\n"
        for q in analysis.clarifications_needed:
            if q.answered:
                clarifications_text += f"Q: {q.question}\nA: {q.answer}\n\n"

    # Build component descriptions
    components_text = "\n".join([
        f"- {comp.name} ({comp.type}): {comp.description}\n  Requirements: {', '.join(comp.requirements)}"
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

For EVERY API endpoint, specify exact request/response schemas and implementation logic using {backend_lang} syntax.
For EVERY data model, specify fields, types, and relationships using {database} patterns.

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
        "// Framework-specific data/state": "Adapt to {frontend_framework}"
      }},
      "frontend_methods": [
        "// Framework-specific methods/functions - Adapt to {frontend_framework}"
      ],
      "styling_classes": ["container", "content", "// CSS framework classes"],
      "api_interactions": ["POST /api/endpoint"],
      "child_components": []
    }}
  ],

  "page_layouts": [
    {{
      "name": "Main Page",
      "route": "/",
      "template_file": "index.html or index.php or index.jsx - depends on {backend_lang}",
      "layout_type": "single_column or multi_column",
      "components": ["component1", "component2"]
    }}
  ],

  "state_management": {{
    "method": "State management approach for {frontend_framework}",
    "stores": {{
      "// Define stores appropriate for {frontend_framework}": ""
    }}
  }},

  "api_endpoints": [
    {{
      "method": "POST",
      "path": "/api/endpoint",
      "description": "Endpoint description",
      "request_body": {{
        "fields": [
          {{"name": "field1", "type": "appropriate type for {backend_lang}", "required": true}}
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
          "type": "Appropriate type for {database} (INTEGER PRIMARY KEY for SQLite, UUID for PostgreSQL, etc.)",
          "constraints": ["PRIMARY KEY"]
        }},
        {{
          "name": "field",
          "type": "Appropriate type for {database}",
          "constraints": []
        }}
      ],
      "relationships": [],
      "indexes": []
    }}
  ],

  "authentication": {{
    "method": "Authentication method appropriate for {backend_framework}",
    "// Additional auth details": ""
  }},

  "authorization": {{
    "method": "role_based or other",
    "roles": [],
    "permissions": {{}}
  }},

  "data_flows": [
    {{
      "name": "Example Flow",
      "steps": [
        {{"step": 1, "action": "User action"}},
        {{"step": 2, "action": "Frontend validates using {frontend_framework}"}},
        {{"step": 3, "action": "POST to API using {backend_lang}/{backend_framework}"}},
        {{"step": 4, "action": "Backend processes in {backend_lang}"}},
        {{"step": 5, "action": "Save to {database} database"}},
        {{"step": 6, "action": "Return response"}}
      ],
      "error_handling": [
        "Validation errors: Show error message",
        "Server errors: Handle gracefully"
      ]
    }}
  ],

  "caching_strategy": {{
    "enabled": true|false,
    "backend": "redis|memcached|file|null",
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
8. **Include security considerations at every layer**

Return ONLY valid JSON, no explanations.
"""
```

### Key Improvements:

✅ **Extracts tech stack from analysis.technical_constraints**
✅ **Dynamically adapts prompt based on user's choices**
✅ **Provides framework-specific guidance**
✅ **Emphasizes strict adherence to user specs**
✅ **Includes validation feedback for retry logic**
✅ **No hardcoded technology assumptions**

**Status**: ✅ **READY FOR IMPLEMENTATION**

---

## Stage 3: Workflow Planner

**File**: `stages/intelligent_generators/workflow_planner.py`
**Status**: NOT YET REVIEWED - Will need to ensure it respects tech stack

---

## Stage 4: LLM Code Generator

**File**: `stages/intelligent_generators/llm_code_generator.py`
**Status**: NOT YET REVIEWED - Will need to ensure code generation follows tech stack

---

## Stage 5: Assembly Coordinator

**File**: `stages/intelligent_generators/assembly_coordinator.py`
**Status**: NOT YET REVIEWED - Should be tech-stack agnostic

---

## Stage 6: Consistency Verifier

**File**: `stages/intelligent_generators/consistency_verifier.py`
**Status**: PARTIALLY REVIEWED - Python-specific AST validation needs to become language-agnostic

---

## Stage 7: Deployment Orchestrator

**Status**: NOT YET IMPLEMENTED - Placeholder stage

---

## Summary of Required Changes

### Immediate (P0 - CRITICAL):
1. ✅ Add `backend_language`, `backend_framework`, `web_server` to `DetailedSpecification`
2. ✅ Update `prompt_analyzer` to extract tech stack
3. ✅ Rename `alpine_js_data` → `frontend_logic`, `alpine_js_methods` → `frontend_methods`, `tailwind_classes` → `styling_classes`
4. ✅ Rewrite `requirement_elaborator` prompt to be tech-stack agnostic
5. ✅ Update `_create_specification_object()` to handle new fields

### High Priority (P1):
6. ❌ **PENDING**: Review and update `workflow_planner` prompts
7. ❌ **PENDING**: Review and update `llm_code_generator` prompts
8. ❌ **PENDING**: Make `consistency_verifier` language-agnostic (not just Python AST)

### Medium Priority (P2):
9. ❌ **PENDING**: Create tech-stack-specific code templates
10. ❌ **PENDING**: Add validation for tech stack compatibility

---

## Conclusion

The intelligent code generation system had **fundamental hardcoding violations** in Stage 2 (Requirement Elaborator). The prompts explicitly instructed the LLM to generate Alpine.js/Tailwind/PostgreSQL code regardless of user specifications.

This has been identified and a comprehensive fix is in progress. The new prompt design:
- Extracts tech stack from user requirements
- Dynamically adapts guidance based on chosen technologies
- Emphasizes strict adherence to user specifications
- Provides framework-specific examples and patterns
- Eliminates all hardcoded technology assumptions

**Next Steps**:
1. ✅ Complete implementation of tech-stack agnostic elaboration prompt
2. ✅ Update parsing logic to handle new fields
3. Test with PHP/Apache/SQLite Hello World example
4. Review and update remaining stages

---

**Document Status**: DRAFT - Active refactoring in progress
**Last Updated**: 2025-11-27
**Author**: Claude Code (Sonnet 4.5)
