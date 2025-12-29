#!/usr/bin/env python3
"""
LLM Code Generator - Stage 4 of Intelligent Code Generation
============================================================

Generates code files using LLM with context awareness.

This stage:
1. Iterates through generation workflow phases
2. Prepares context from previously generated files
3. Creates targeted prompts with examples
4. Generates code using LLM
5. Validates syntax and structure
6. Stores for next phase context
"""

import ast
import json
import logging
import re
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from pathlib import Path

from ..llm_client import LLMClient
from .workflow_planner import GenerationWorkflow, FileSpecification
from .tech_stack_config import TechStackConfig

logger = logging.getLogger(__name__)


@dataclass
class GeneratedFile:
    """A generated code file."""
    path: str
    content: str
    file_type: str
    validation_passed: bool
    validation_errors: List[str] = None

    def get_size_kb(self) -> float:
        """Get file size in KB."""
        return len(self.content.encode('utf-8')) / 1024


@dataclass
class GenerationContext:
    """Context manager for code generation."""
    generated_files: Dict[str, GeneratedFile]
    api_contracts: Dict[str, Dict[str, Any]]  # path -> {endpoints, schemas}
    data_models: Dict[str, Dict[str, Any]]  # model_name -> {fields, relationships}
    imports: Dict[str, Set[str]]  # file_path -> set of imports

    def __init__(self):
        self.generated_files = {}
        self.api_contracts = {}
        self.data_models = {}
        self.imports = {}

    def add_file(self, generated_file: GeneratedFile):
        """Add generated file to context."""
        self.generated_files[generated_file.path] = generated_file

        # Extract contracts and models
        if generated_file.file_type == "api_endpoint":
            self._extract_api_contract(generated_file)
        elif generated_file.file_type == "model":
            self._extract_data_model(generated_file)

        # Extract imports
        self._extract_imports(generated_file)

    def get_context_for_file(self, file_spec: FileSpecification) -> str:
        """Get relevant context for generating a file."""
        context_parts = []

        # Include dependency file contents
        for dep_path in file_spec.dependencies:
            if dep_path in self.generated_files:
                dep_file = self.generated_files[dep_path]
                context_parts.append(f"""
# Previously Generated: {dep_path}
```python
{dep_file.content}
```
""")

        # Include context files
        for ctx_path in file_spec.context_files:
            if ctx_path in self.generated_files:
                ctx_file = self.generated_files[ctx_path]
                context_parts.append(f"""
# Context: {ctx_path}
```python
{ctx_file.content}
```
""")

        return "\n\n".join(context_parts) if context_parts else "No prior context"

    def get_all_api_endpoints(self) -> List[str]:
        """Get list of all API endpoints defined."""
        endpoints = []
        for contract in self.api_contracts.values():
            endpoints.extend(contract.get("endpoints", []))
        return endpoints

    def get_all_models(self) -> List[str]:
        """Get list of all data models defined."""
        return list(self.data_models.keys())

    def _extract_api_contract(self, generated_file: GeneratedFile):
        """Extract API endpoints from generated file."""
        # Simple regex to find @router decorators
        endpoints = []
        pattern = r'@router\.(get|post|put|delete|patch)\("([^"]+)"'
        matches = re.finditer(pattern, generated_file.content)
        for match in matches:
            method, path = match.groups()
            endpoints.append(f"{method.upper()} {path}")

        self.api_contracts[generated_file.path] = {
            "endpoints": endpoints
        }

    def _extract_data_model(self, generated_file: GeneratedFile):
        """Extract data model info from generated file."""
        # Look for class definitions
        pattern = r'class (\w+)\(.*Base.*\):'
        matches = re.finditer(pattern, generated_file.content)
        for match in matches:
            model_name = match.group(1)
            self.data_models[model_name] = {
                "file": generated_file.path
            }

    def _extract_imports(self, generated_file: GeneratedFile):
        """Extract imports from generated file."""
        imports = set()
        # Extract from/import statements
        pattern = r'^(?:from .+ )?import .+$'
        for line in generated_file.content.split('\n'):
            if re.match(pattern, line.strip()):
                imports.add(line.strip())
        self.imports[generated_file.path] = imports


class CodeValidator:
    """Validates generated code."""

    @staticmethod
    def validate_python(content: str) -> tuple[bool, List[str]]:
        """Validate Python syntax."""
        errors = []

        try:
            ast.parse(content)
            return True, []
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
            return False, errors
        except Exception as e:
            errors.append(f"Parse error: {str(e)}")
            return False, errors

    @staticmethod
    def validate_html(content: str) -> tuple[bool, List[str]]:
        """Validate HTML structure (basic checks)."""
        errors = []

        # Check for balanced tags
        stack = []
        pattern = r'<(/?)(\w+)[^>]*>'
        for match in re.finditer(pattern, content):
            is_closing, tag = match.groups()
            tag = tag.lower()

            # Skip self-closing tags
            if tag in ['img', 'br', 'hr', 'input', 'meta', 'link']:
                continue

            if is_closing:
                if not stack or stack[-1] != tag:
                    errors.append(f"Unbalanced closing tag: </{tag}>")
                else:
                    stack.pop()
            else:
                stack.append(tag)

        if stack:
            errors.append(f"Unclosed tags: {', '.join(stack)}")

        return len(errors) == 0, errors

    @staticmethod
    def validate_javascript(content: str) -> tuple[bool, List[str]]:
        """Validate JavaScript (basic checks)."""
        errors = []

        # Check for balanced braces/brackets/parens
        stack = []
        pairs = {'(': ')', '[': ']', '{': '}'}
        for char in content:
            if char in pairs:
                stack.append(char)
            elif char in pairs.values():
                if not stack or pairs[stack[-1]] != char:
                    errors.append(f"Unbalanced closing: {char}")
                else:
                    stack.pop()

        if stack:
            errors.append(f"Unclosed: {', '.join(stack)}")

        return len(errors) == 0, errors


class LLMCodeGenerator:
    """
    Generates code files using LLM with context awareness.

    Uses targeted prompts and maintains context across related files
    to ensure consistency and proper integration.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None, tech_config: Optional[TechStackConfig] = None):
        """
        Initialize LLM code generator.

        Args:
            llm_client: LLM client for generation (creates new if not provided)
            tech_config: Technology stack configuration
        """
        self.llm = llm_client or LLMClient()
        self.tech_config = tech_config
        self.context = GenerationContext()
        self.validator = CodeValidator()
        logger.info("LLMCodeGenerator initialized")

    def generate_all(self, workflow: GenerationWorkflow) -> List[GeneratedFile]:
        """
        Generate all files according to workflow.

        Args:
            workflow: GenerationWorkflow with phased file specifications

        Returns:
            List of GeneratedFile objects
        """
        logger.info("=" * 60)
        logger.info("CODE GENERATION STARTED")
        logger.info("=" * 60)

        all_files = []

        for phase in workflow.phases:
            logger.info(f"\n{phase.name}: {phase.description}")
            logger.info(f"  Generating {phase.get_file_count()} files...")

            for file_spec in phase.files:
                logger.info(f"    → {file_spec.path}")

                generated_file = self.generate_file(file_spec)
                all_files.append(generated_file)

                if generated_file.validation_passed:
                    logger.info(f"      ✓ {generated_file.get_size_kb():.1f} KB")
                else:
                    logger.warning(f"      ⚠ Validation issues: {generated_file.validation_errors}")

        logger.info(f"\n✅ Generated {len(all_files)} files")
        logger.info("=" * 60)
        logger.info("CODE GENERATION COMPLETE")
        logger.info("=" * 60)

        return all_files

    def generate_file(self, file_spec: FileSpecification) -> GeneratedFile:
        """
        Generate a single file with context.

        Args:
            file_spec: FileSpecification with details

        Returns:
            GeneratedFile with code content
        """
        # Get context from dependencies
        context = self.context.get_context_for_file(file_spec)

        # Build full prompt
        full_prompt = self._build_full_prompt(file_spec, context)

        # Generate code
        try:
            response_obj = self.llm.generate(full_prompt, temperature=0.2)  # Low temp for deterministic code
            code = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)
            code = self._clean_generated_code(code)
        except Exception as e:
            logger.error(f"Generation failed for {file_spec.path}: {e}")
            code = f"# ERROR: Generation failed\n# {str(e)}\n"

        # Validate
        is_valid, errors = self._validate_generated_code(file_spec.file_type, code)

        # Retry once if validation fails
        if not is_valid and file_spec.file_type in ["model", "api_endpoint", "schema"]:
            logger.warning(f"Validation failed for {file_spec.path}, retrying with fixes...")
            code = self._retry_with_fixes(file_spec, code, errors, context)
            is_valid, errors = self._validate_generated_code(file_spec.file_type, code)

        # Create GeneratedFile
        generated_file = GeneratedFile(
            path=file_spec.path,
            content=code,
            file_type=file_spec.file_type,
            validation_passed=is_valid,
            validation_errors=errors if not is_valid else None
        )

        # Add to context
        self.context.add_file(generated_file)

        return generated_file

    def _build_full_prompt(self, file_spec: FileSpecification, context: str) -> str:
        """Build complete prompt for code generation."""

        # Get specialized role-based system prompt
        role_prompt = self._get_role_system_prompt(file_spec.file_type)

        # Determine language and add relevant instructions
        language_instructions = self._get_language_instructions(file_spec.file_type)

        prompt = f"""{role_prompt}

# Code Generation Task

Generate production-ready code for: **{file_spec.path}**

## File Description
{file_spec.description}

## Context from Dependencies
{context}

## Requirements
{file_spec.prompt}

## Code Standards
{language_instructions}

## Critical Instructions
1. Generate COMPLETE, WORKING code - no placeholders or TODOs
2. Include ALL necessary imports at the top
3. Add comprehensive docstrings (Google style)
4. Use proper type hints throughout
5. Include error handling where appropriate
6. Follow PEP 8 for Python, standard conventions for other languages
7. Make code production-ready and secure

## Output Format
Return ONLY the code for {file_spec.path}.
No explanations, no markdown formatting, just the raw code.
Start with imports/docstring, end with last function/class.
"""

        return prompt

    def _get_role_system_prompt(self, file_type: str) -> str:
        """Get specialized role-based system prompt for the file type."""
        
        # If tech_config is available, use it to get role prompts
        if self.tech_config:
            role_prompt = self.tech_config.get_role_prompt(file_type)
            if role_prompt:
                return role_prompt
        
        # Fallback to generic prompt if tech_config not available or template not found
        return """# Your Role: Senior Software Engineer

You are an experienced software engineer with expertise across multiple domains.
Generate production-ready, well-documented code following industry best practices."""

    def _get_language_instructions(self, file_type: str) -> str:
        """Get language-specific coding standards."""
        if not self.tech_config:
            return "Follow industry best practices and conventions."
        
        backend_lang = self.tech_config.backend_language
        
        # Backend file types
        if file_type in ["model", "api_endpoint", "schema", "crud", "config", "security", "worker", "main"]:
            if backend_lang == "python":
                return """
**Python Standards:**
- Use type hints for all functions: `def func(arg: str) -> int:`
- Docstrings in Google format with Args, Returns, Raises sections
- Import ordering: stdlib, third-party, local (separated by blank lines)
- Use async/await for I/O operations
- Handle exceptions explicitly, don't use bare except
- Use descriptive variable names (no single letters except loop counters)
- Add logging at appropriate levels (debug, info, warning, error)
"""
            elif backend_lang == "php":
                return """
**PHP Standards:**
- Use type declarations for all functions and properties
- PHPDoc blocks for all classes, methods, and properties
- PSR-12 coding standards
- Use dependency injection
- Handle exceptions with try/catch blocks
- Use meaningful variable and method names
- Follow Laravel conventions (if using Laravel)
"""
            elif backend_lang == "nodejs":
                return """
**Node.js/JavaScript Standards:**
- Use TypeScript or JSDoc for type annotations
- Async/await for asynchronous operations
- Proper error handling with try/catch
- Use const/let, avoid var
- ES6+ syntax (arrow functions, destructuring, template literals)
- Descriptive variable and function names
- Add logging for debugging
"""
        
        # Frontend template files
        elif file_type == "template":
            return """
**HTML/Template Standards:**
- Use semantic HTML5 tags
- Include proper DOCTYPE and meta tags
- Responsive design with mobile-first approach
- Accessibility: proper ARIA labels, alt text, semantic structure
"""
        
        # Frontend JavaScript files
        elif file_type == "javascript":
            return """
**JavaScript Standards:**
- Async/await for API calls
- Proper error handling with try/catch
- Loading states for async operations
- User-friendly error messages
- ES6+ syntax (const/let, arrow functions, destructuring)
"""
        
        # Dependency files
        elif file_type == "dependency":
            if backend_lang == "python":
                return "Format: requirements.txt (one package per line)"
            elif backend_lang == "php":
                return "Format: composer.json (valid JSON)"
            elif backend_lang == "nodejs":
                return "Format: package.json (valid JSON)"
        
        return "Follow industry best practices and conventions."

    def _clean_generated_code(self, code: str) -> str:
        """Clean LLM-generated code."""
        # Remove markdown code blocks
        if code.strip().startswith("```"):
            lines = code.strip().split("\n")
            # Remove first line (```python or ```)
            lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        # Remove trailing whitespace
        code = "\n".join(line.rstrip() for line in code.split("\n"))

        # Ensure ends with newline
        if not code.endswith("\n"):
            code += "\n"

        return code

    def _validate_generated_code(self, file_type: str, code: str) -> tuple[bool, List[str]]:
        """Validate generated code based on file type."""
        # Determine language from tech_config
        if self.tech_config:
            backend_lang = self.tech_config.backend_language
        else:
            backend_lang = "python"  # Default fallback
        
        # Backend code validation
        if file_type in ["model", "api_endpoint", "schema", "crud", "config", "security", "worker", "main"]:
            if backend_lang == "python":
                return self.validator.validate_python(code)
            elif backend_lang == "php":
                # PHP validation - basic syntax check
                # TODO: Implement proper PHP validation
                return True, []
            elif backend_lang == "nodejs":
                # JavaScript validation
                return self.validator.validate_javascript(code)
        
        # Frontend template validation
        elif file_type == "template":
            return self.validator.validate_html(code)
        
        # Frontend JavaScript validation
        elif file_type == "javascript":
            return self.validator.validate_javascript(code)
        
        # Init files
        elif file_type == "init":
            if backend_lang == "python":
                # __init__.py can be empty or simple imports
                if not code.strip() or "import" in code:
                    return True, []
                return self.validator.validate_python(code)
            else:
                # Non-Python languages don't have __init__ files
                return True, []
        
        # Dependency files
        elif file_type == "dependency":
            if backend_lang == "python":
                # requirements.txt validation
                return True, []
            elif backend_lang in ["php", "nodejs"]:
                # JSON validation for composer.json/package.json
                try:
                    json.loads(code)
                    return True, []
                except json.JSONDecodeError as e:
                    return False, [f"Invalid JSON: {e}"]
        
        # Skip validation for unknown types
        return True, []

    def _retry_with_fixes(self,
                         file_spec: FileSpecification,
                         failed_code: str,
                         errors: List[str],
                         context: str) -> str:
        """Retry generation with error feedback."""

        fix_prompt = f"""# Code Fix Required

The generated code for {file_spec.path} has validation errors.

## Original Requirements
{file_spec.prompt}

## Context
{context}

## Generated Code (with errors)
```python
{failed_code}
```

## Validation Errors
{chr(10).join(f"- {error}" for error in errors)}

## Your Task
Fix the validation errors and regenerate COMPLETE, WORKING code for {file_spec.path}.
Return ONLY the corrected code, no explanations.
"""

        try:
            response_obj = self.llm.generate(fix_prompt, temperature=0.1)
            fixed_code = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)
            return self._clean_generated_code(fixed_code)
        except Exception as e:
            logger.error(f"Fix generation failed: {e}")
            return failed_code  # Return original if fix fails
