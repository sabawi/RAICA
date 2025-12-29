#!/usr/bin/env python3
"""
CLI Coding Agent
================

An autonomous coding agent that iterates through the software development lifecycle:
    Requirements → Planning → Architecture → Design → Coding → Debugging → Testing

Uses the code_generation LLM configuration directly for intelligent code generation.
This bypasses the FastAPI server and uses the dedicated code generation model
(e.g., deepseek-v3.2:cloud) configured in llm_config.yaml.

Features:
- State machine for iterative development phases
- Context-efficient prompting to maximize output quality
- Rich terminal interface with progress indicators
- Automatic code file generation
- Integrated testing and debugging loops
- Persistent project context across phases
- Direct LLM access using code_generation config

Author: RAICA Development Team
Version: 1.1.0
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import common utilities
from common.config_loader import get_agent_config, AgentConfigError
from common.agent_utils import (
    setup_agent_logging,
    create_output_directory
)

# Import the code generation LLM client
# Handle both direct execution and module import
try:
    from .llm_client import CodeGenLLMClient, LLMResponse
    from .validation import (
        CodeValidator,
        GenerationValidator,
        EnvironmentSanityValidator,
        WebSanityValidator,  # Backwards compatibility alias
        ImportResolver,
        DockerSandbox,
        ValidationResult,
        ExecutionResult,
        TestResult,
        detect_language,
        detect_project_language,
        # Layer 4.5: Consistency Verification
        SymbolExtractor,
        ConsistencyVerifier,
        InterfaceDefinition,
        ExportedSymbol,
        ConsistencyError
    )
except ImportError:
    from llm_client import CodeGenLLMClient, LLMResponse
    from validation import (
        CodeValidator,
        GenerationValidator,
        EnvironmentSanityValidator,
        WebSanityValidator,  # Backwards compatibility alias
        ImportResolver,
        DockerSandbox,
        ValidationResult,
        ExecutionResult,
        TestResult,
        detect_language,
        detect_project_language,
        # Layer 4.5: Consistency Verification
        SymbolExtractor,
        ConsistencyVerifier,
        InterfaceDefinition,
        ExportedSymbol,
        ConsistencyError
    )

# Agent name for configuration
AGENT_NAME = "coding_agent"
VERSION = "2.0.0"


class DevelopmentPhase(Enum):
    """Development lifecycle phases."""
    REQUIREMENTS = auto()
    PLANNING = auto()
    ARCHITECTURE = auto()
    DESIGN = auto()
    INTERFACE_GENERATION = auto()
    CODING = auto()
    DEBUGGING = auto()
    TESTING = auto()
    COMPLETE = auto()


@dataclass
class ProjectContext:
    """
    Maintains project context across development phases.

    Designed for context efficiency - stores only essential information
    that needs to persist across LLM calls.
    """
    # User requirements
    original_request: str = ""
    refined_requirements: List[str] = field(default_factory=list)

    # Planning outputs
    implementation_plan: List[str] = field(default_factory=list)

    # Architecture outputs
    architecture_decisions: Dict[str, str] = field(default_factory=dict)
    components: List[Dict[str, str]] = field(default_factory=list)

    # Design outputs
    file_specifications: List[Dict[str, Any]] = field(default_factory=list)

    # Coding outputs
    generated_files: Dict[str, str] = field(default_factory=dict)

    # Interface definitions (Layer 4.5 - Symbol Table)
    # Maps file paths to their extracted InterfaceDefinition objects
    interfaces: Dict[str, Any] = field(default_factory=dict)  # Any to avoid circular import

    # Debug/Test outputs
    issues_found: List[Dict[str, str]] = field(default_factory=list)
    tests_passed: List[str] = field(default_factory=list)
    tests_failed: List[str] = field(default_factory=list)

    # Iteration tracking
    iteration: int = 1
    max_iterations: int = 10

    def get_summary(self) -> str:
        """Get a concise summary of current project state for context efficiency."""
        summary_parts = []

        if self.refined_requirements:
            summary_parts.append(f"Requirements: {len(self.refined_requirements)} items")
        if self.implementation_plan:
            summary_parts.append(f"Plan: {len(self.implementation_plan)} steps")
        if self.components:
            summary_parts.append(f"Components: {len(self.components)}")
        if self.generated_files:
            summary_parts.append(f"Files: {len(self.generated_files)}")
        if self.issues_found:
            summary_parts.append(f"Issues: {len(self.issues_found)} open")
        if self.tests_passed or self.tests_failed:
            total = len(self.tests_passed) + len(self.tests_failed)
            passed = len(self.tests_passed)
            summary_parts.append(f"Tests: {passed}/{total} passed")

        return " | ".join(summary_parts) if summary_parts else "Initial state"

    def to_compact_dict(self) -> Dict[str, Any]:
        """Export to compact dictionary for serialization."""
        return {
            "request": self.original_request[:500] if self.original_request else "",
            "requirements": self.refined_requirements[:10],
            "plan_steps": len(self.implementation_plan),
            "components": [c.get("name", "") for c in self.components[:10]],
            "files": list(self.generated_files.keys()),
            "issues_count": len(self.issues_found),
            "tests": {"passed": len(self.tests_passed), "failed": len(self.tests_failed)},
            "iteration": self.iteration
        }


class CLICodingAgent:
    """
    Autonomous CLI Coding Agent.

    Iterates through software development phases until requirements are met
    or max iterations reached.
    """

    def __init__(
        self,
        output_dir: str = "generated_projects",
        project_name: Optional[str] = None,
        verbose: bool = False,
        max_iterations: int = 10,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize the CLI Coding Agent.

        Args:
            output_dir: Base directory for generated projects
            project_name: Name for the project (auto-generated if not provided)
            verbose: Enable verbose logging
            max_iterations: Maximum development iterations
            provider: Optional LLM provider override (ollama, openai, anthropic, gemini, qwen)
            model: Optional model name override (e.g., deepseek-v3.2:cloud, gpt-4o, claude-sonnet-4-20250514)
        """
        # Setup logging first
        log_level = logging.DEBUG if verbose else logging.INFO
        self.logger = setup_agent_logging(AGENT_NAME, level=log_level)

        # Load agent-specific configuration (for non-LLM settings)
        try:
            self.config = get_agent_config(AGENT_NAME)
            self._max_iterations = self.config.get('execution', 'max_iterations', default=max_iterations)
        except AgentConfigError as e:
            self.logger.warning(f"Could not load agent config: {e}")
            self.config = None
            self._max_iterations = max_iterations

        # Override max_iterations if explicitly provided
        if max_iterations != 10:
            self._max_iterations = max_iterations

        # Initialize the code generation LLM client
        # This reads from code_generation section of llm_config.yaml
        try:
            self.llm_client = CodeGenLLMClient(
                provider_override=provider,
                model_override=model
            )
            llm_info = self.llm_client.get_config_info()
            self._provider = llm_info['primary_provider']
            self._model = llm_info['primary_model']
            self._temperature = llm_info['temperature']
            self._max_tokens = llm_info['max_tokens']
        except Exception as e:
            self.logger.error(f"Failed to initialize LLM client: {e}")
            raise

        # Project setup
        self.project_name = project_name or f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.output_dir = create_output_directory(output_dir)
        self.project_dir = self.output_dir / self.project_name
        self.project_dir.mkdir(exist_ok=True, parents=True)

        # State machine
        self.current_phase = DevelopmentPhase.REQUIREMENTS
        self.context = ProjectContext(max_iterations=self._max_iterations)

        # Phase transition rules
        self._phase_order = [
            DevelopmentPhase.REQUIREMENTS,
            DevelopmentPhase.PLANNING,
            DevelopmentPhase.ARCHITECTURE,
            DevelopmentPhase.DESIGN,
            DevelopmentPhase.INTERFACE_GENERATION,
            DevelopmentPhase.CODING,
            DevelopmentPhase.DEBUGGING,
            DevelopmentPhase.TESTING,
            DevelopmentPhase.COMPLETE
        ]

        # Initialize validators (will be fully set up after project language is detected)
        self.generation_validator = GenerationValidator()
        self.code_validator = None  # Initialized after first file is generated
        self._project_language = 'python'  # Default, updated during coding phase

        self.logger.info(f"CLI Coding Agent v{VERSION} initialized")
        self.logger.info(f"Project: {self.project_name}")
        self.logger.info(f"Output: {self.project_dir}")
        self.logger.info(f"LLM Provider: {self._provider}")
        self.logger.info(f"LLM Model: {self._model}")

    def _print_header(self, text: str, char: str = "=") -> None:
        """Print a formatted header."""
        width = 80
        print(f"\n{char * width}")
        print(f" {text}")
        print(f"{char * width}")

    def _print_phase(self, phase: DevelopmentPhase) -> None:
        """Print current phase indicator."""
        phase_icons = {
            DevelopmentPhase.REQUIREMENTS: "📋",
            DevelopmentPhase.PLANNING: "📝",
            DevelopmentPhase.ARCHITECTURE: "🏗️",
            DevelopmentPhase.DESIGN: "✏️",
            DevelopmentPhase.INTERFACE_GENERATION: "🧩",
            DevelopmentPhase.CODING: "💻",
            DevelopmentPhase.DEBUGGING: "🔧",
            DevelopmentPhase.TESTING: "🧪",
            DevelopmentPhase.COMPLETE: "✅"
        }
        icon = phase_icons.get(phase, "▶️")
        self._print_header(f"{icon} PHASE: {phase.name} (Iteration {self.context.iteration})")

    def _call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> Optional[str]:
        """
        Make a call to the LLM using the code_generation config.

        Args:
            prompt: The prompt to send
            max_tokens: Override max tokens if needed

        Returns:
            Response content or None on failure
        """
        tokens = max_tokens or self._max_tokens

        try:
            response: LLMResponse = self.llm_client.generate(
                prompt=prompt,
                temperature=self._temperature,
                max_tokens=tokens
            )

            if not response.success:
                self.logger.error(f"LLM call failed: {response.error}")
                return None

            if not response.content:
                self.logger.error("Empty response from LLM")
                return None

            return response.content

        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            return None

    def _extract_json(self, content: str) -> Optional[Dict]:
        """Extract JSON from LLM response."""
        # Try to find JSON block
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to find object
        obj_match = re.search(r'\{[\s\S]*\}', content)
        if obj_match:
            try:
                return json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _extract_code_blocks(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract code blocks from LLM response.

        Returns:
            List of (language, code) tuples
        """
        pattern = r'```(\w+)?\s*\n([\s\S]*?)```'
        matches = re.findall(pattern, content)
        return [(lang or "text", code.strip()) for lang, code in matches]

    def _detect_target_environment(self, language: str, file_path: str) -> str:
        """
        Detect the target runtime environment based on language and context.

        Args:
            language: Programming language
            file_path: File path for context

        Returns:
            Environment string: 'browser', 'node', 'python-cli', 'python-web', etc.
        """
        # Check for explicit hints in the original request
        request_lower = self.context.original_request.lower()

        if language in ('javascript', 'typescript'):
            # Check for Node.js indicators in request
            node_keywords = ['node', 'npm', 'server', 'express', 'api server', 'backend', 'cli tool']
            if any(kw in request_lower for kw in node_keywords):
                return 'node'

            # Check for browser indicators
            browser_keywords = ['browser', 'web page', 'html', 'dom', 'canvas', 'animation', 'game', 'frontend', 'ui']
            if any(kw in request_lower for kw in browser_keywords):
                return 'browser'

            # Default based on file
            if file_path.endswith('.html') or 'index' in file_path.lower():
                return 'browser'

            # Default to browser for vanilla JS (safer default)
            return 'browser'

        elif language == 'python':
            # Check for web server indicators
            web_keywords = ['flask', 'fastapi', 'django', 'web server', 'api server', 'rest api']
            if any(kw in request_lower for kw in web_keywords):
                return 'python-web'

            # Check for CLI indicators
            cli_keywords = ['cli', 'command line', 'terminal', 'script', 'tool', 'utility']
            if any(kw in request_lower for kw in cli_keywords):
                return 'python-cli'

            # Default to CLI for Python
            return 'python-cli'

        elif language == 'html':
            return 'browser'

        return 'auto'

    def _extract_requested_frameworks(self) -> List[str]:
        """
        Extract frameworks explicitly mentioned in the user's request.

        Returns:
            List of framework names mentioned in the request
        """
        request_lower = self.context.original_request.lower()

        # Known frameworks to check for
        frameworks = [
            # JavaScript
            'react', 'vue', 'angular', 'svelte', 'jquery', 'express',
            'next.js', 'nextjs', 'nuxt', 'gatsby',
            # Game engines
            'phaser', 'three.js', 'threejs', 'pixi', 'babylon', 'melonjs', 'p5.js', 'p5js',
            # Python
            'flask', 'django', 'fastapi', 'tornado', 'bottle',
            'pygame', 'pyglet', 'arcade',
            'pandas', 'numpy', 'tensorflow', 'pytorch', 'keras',
            'tkinter', 'pyqt', 'kivy', 'wxpython',
            # CSS
            'bootstrap', 'tailwind', 'bulma', 'materialize',
        ]

        requested = []
        for fw in frameworks:
            # Check for exact word match (avoid partial matches)
            if re.search(rf'\b{re.escape(fw)}\b', request_lower):
                requested.append(fw)

        return requested

    # =========================================================================
    # PHASE IMPLEMENTATIONS
    # =========================================================================

    def _phase_requirements(self, user_request: str) -> bool:
        """
        Phase 1: Gather and refine requirements.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.REQUIREMENTS)
        self.context.original_request = user_request

        prompt = f"""You are a senior software architect analyzing user requirements.

USER REQUEST:
{user_request}

TASK:
1. Analyze the request and extract clear, actionable requirements
2. Identify any implicit requirements
3. Clarify ambiguous aspects
4. Prioritize requirements (must-have vs nice-to-have)

OUTPUT FORMAT (JSON):
```json
{{
    "project_summary": "One-line project description",
    "requirements": [
        {{"id": "R1", "description": "...", "priority": "must-have|nice-to-have", "category": "functional|non-functional"}}
    ],
    "clarifications_needed": ["Any questions for the user"],
    "assumptions": ["Assumptions made"],
    "constraints": ["Technical or other constraints"]
}}
```

Be concise and specific. Focus on actionable requirements."""

        response = self._call_llm(prompt)
        if not response:
            return False

        data = self._extract_json(response)
        if data and "requirements" in data:
            self.context.refined_requirements = [
                f"{r.get('id', 'R?')}: {r.get('description', '')}"
                for r in data["requirements"]
            ]
            print(f"\n✅ Extracted {len(self.context.refined_requirements)} requirements")
            for req in self.context.refined_requirements[:5]:
                print(f"   • {req}")
            if len(self.context.refined_requirements) > 5:
                print(f"   ... and {len(self.context.refined_requirements) - 5} more")
            return True
        else:
            # Fallback: extract from text
            self.context.refined_requirements = [user_request]
            print("\n⚠️ Could not parse requirements JSON, using raw request")
            return True

    def _phase_planning(self) -> bool:
        """
        Phase 2: Create implementation plan.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.PLANNING)

        requirements_text = "\n".join(f"- {r}" for r in self.context.refined_requirements)

        prompt = f"""You are a senior software architect creating an implementation plan.

PROJECT CONTEXT:
{self.context.original_request[:500]}

REQUIREMENTS:
{requirements_text}

TASK:
Create a step-by-step implementation plan. Each step should be:
- Specific and actionable
- Ordered by dependency (do prerequisite steps first)
- Estimated for complexity (simple/medium/complex)

OUTPUT FORMAT (JSON):
```json
{{
    "implementation_steps": [
        {{"step": 1, "action": "...", "complexity": "simple|medium|complex", "dependencies": []}}
    ],
    "technology_stack": ["language/framework choices"],
    "estimated_files": ["list of files to create"],
    "risks": ["potential issues to watch for"]
}}
```

Be pragmatic and efficient. Avoid over-engineering."""

        response = self._call_llm(prompt)
        if not response:
            return False

        data = self._extract_json(response)
        if data and "implementation_steps" in data:
            self.context.implementation_plan = [
                f"Step {s.get('step', '?')}: {s.get('action', '')}"
                for s in data["implementation_steps"]
            ]
            print(f"\n✅ Created plan with {len(self.context.implementation_plan)} steps")
            for step in self.context.implementation_plan[:5]:
                print(f"   • {step}")
            if len(self.context.implementation_plan) > 5:
                print(f"   ... and {len(self.context.implementation_plan) - 5} more")
            return True
        else:
            self.logger.warning("Could not parse planning JSON")
            return True  # Continue anyway

    def _phase_architecture(self) -> bool:
        """
        Phase 3: Define system architecture.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.ARCHITECTURE)

        prompt = f"""You are a senior software architect designing system architecture.

PROJECT: {self.context.original_request[:300]}

REQUIREMENTS ({len(self.context.refined_requirements)} items):
{chr(10).join(f'- {r}' for r in self.context.refined_requirements[:5])}

PLAN ({len(self.context.implementation_plan)} steps):
{chr(10).join(self.context.implementation_plan[:3])}

TASK:
Define the high-level architecture. Focus on:
1. Major components/modules
2. How they interact
3. Key design patterns
4. Data flow

OUTPUT FORMAT (JSON):
```json
{{
    "architecture_type": "e.g., monolithic, modular, layered, microservices",
    "components": [
        {{"name": "...", "purpose": "...", "responsibilities": ["..."]}}
    ],
    "interactions": [
        {{"from": "component1", "to": "component2", "type": "calls/imports/events"}}
    ],
    "design_patterns": ["patterns used"],
    "data_flow": "Brief description of data flow"
}}
```

Keep it simple and appropriate for the project size."""

        response = self._call_llm(prompt)
        if not response:
            return False

        data = self._extract_json(response)
        if data:
            self.context.architecture_decisions = {
                "type": data.get("architecture_type", "modular"),
                "patterns": data.get("design_patterns", []),
                "data_flow": data.get("data_flow", "")
            }
            self.context.components = data.get("components", [])
            print(f"\n✅ Architecture: {self.context.architecture_decisions.get('type', 'defined')}")
            print(f"   Components: {len(self.context.components)}")
            for comp in self.context.components[:5]:
                print(f"   • {comp.get('name', '?')}: {comp.get('purpose', '')[:50]}")
            return True
        return True  # Continue anyway

    def _phase_design(self) -> bool:
        """
        Phase 4: Detailed design with file specifications.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.DESIGN)

        components_text = "\n".join(
            f"- {c.get('name', '?')}: {c.get('purpose', '')}"
            for c in self.context.components[:10]
        )

        prompt = f"""You are a senior developer creating detailed file specifications.

PROJECT: {self.context.original_request[:200]}

ARCHITECTURE: {self.context.architecture_decisions.get('type', 'modular')}

COMPONENTS:
{components_text}

TASK:
Design the file structure and define what each file should contain.

OUTPUT FORMAT (JSON):
```json
{{
    "files": [
        {{
            "path": "relative/path/filename.ext",
            "purpose": "What this file does",
            "contents_outline": "Key functions/classes to implement",
            "dependencies": ["other files it imports"]
        }}
    ],
    "directory_structure": "Brief description of folder organization"
}}
```

Be specific about what code goes where. Include all necessary files."""

        response = self._call_llm(prompt)
        if not response:
            return False

        data = self._extract_json(response)
        if data and "files" in data:
            self.context.file_specifications = data["files"]
            print(f"\n✅ Designed {len(self.context.file_specifications)} files:")
            for spec in self.context.file_specifications[:8]:
                print(f"   • {spec.get('path', '?')}")
            if len(self.context.file_specifications) > 8:
                print(f"   ... and {len(self.context.file_specifications) - 8} more")
            return True
        return True

    def _phase_interface_generation(self) -> bool:
        """
        Phase 4.5: Generate interface definitions for all files.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.INTERFACE_GENERATION)

        if not self.context.file_specifications:
            self.logger.warning("No file specifications found for interface generation")
            return True

        print(f"\n🧩 Generating interfaces for {len(self.context.file_specifications)} files...")
        
        # Initialize SymbolExtractor
        extractor = SymbolExtractor()

        for spec in self.context.file_specifications:
            file_path = spec.get("path", "unknown")
            purpose = spec.get("purpose", "")
            outline = spec.get("contents_outline", "")
            
            print(f"   • {file_path}...")
            
            # Detect language
            lang = detect_language(file_path)
            
            prompt = f"""You are a senior software architect defining interfaces.

PROJECT: {self.context.original_request[:200]}
FILE: {file_path}
PURPOSE: {purpose}
OUTLINE: {outline}

TASK:
Generate the INTERFACE DEFINITION (Skeleton) for this file.
- Include all exported classes, functions, and constants.
- Include constructors with exact parameters.
- Include public method signatures.
- DO NOT implement the method bodies (use 'pass', '...', or 'return null').
- This code must be syntactically valid so it can be parsed.

OUTPUT:
Return ONLY the code block.
"""
            # Call LLM
            response = self._call_llm(prompt, max_tokens=2048)
            if not response:
                continue
                
            code_blocks = self._extract_code_blocks(response)
            if code_blocks:
                _, code = code_blocks[0]
                
                # Extract symbols
                try:
                    interface = extractor.extract(code, file_path)
                    self.context.interfaces[file_path] = interface
                except Exception as e:
                    self.logger.warning(f"Failed to extract interface from {file_path}: {e}")

        print(f"✅ Generated {len(self.context.interfaces)} file interfaces")
        return True

    def _phase_coding(self) -> bool:
        """
        Phase 5: Generate actual code files.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.CODING)

        if not self.context.file_specifications:
            print("\n⚠️ No file specifications, generating from context...")
            self.context.file_specifications = [{
                "path": "main.py",
                "purpose": self.context.original_request[:200],
                "contents_outline": "Main implementation"
            }]

        files_generated = 0

        for spec in self.context.file_specifications:
            file_path = spec.get("path", "unknown.txt")
            purpose = spec.get("purpose", "")
            outline = spec.get("contents_outline", "")

            print(f"\n   Generating: {file_path}...")

            # Build context-efficient prompt with interface definitions (Layer 4.5)
            context_summary = f"""
PROJECT: {self.context.original_request[:150]}
ARCHITECTURE: {self.context.architecture_decisions.get('type', 'modular')}
"""

            # LAYER 4.5: Inject interface definitions instead of just file names
            # This gives the LLM visibility into actual exports, constructor signatures, etc.
            if self.context.interfaces:
                context_summary += "\nEXISTING INTERFACES (use these exact signatures):\n"
                for iface_path, iface in self.context.interfaces.items():
                    if hasattr(iface, 'to_prompt_string'):
                        context_summary += iface.to_prompt_string() + "\n"
                    else:
                        # Fallback for dict representation
                        context_summary += f"[{iface_path}]\n"
            elif self.context.generated_files:
                # Fallback: at least show file names if interfaces not extracted yet
                related = list(self.context.generated_files.keys())[:5]
                context_summary += f"OTHER FILES: {', '.join(related)}\n"

            # Detect language for proper code block syntax
            lang = detect_language(file_path)
            lang_for_block = lang if lang != 'unknown' else 'javascript'

            prompt = f"""You are an expert software developer writing production code.

{context_summary}

CURRENT FILE: {file_path}
PURPOSE: {purpose}
OUTLINE: {outline}

TASK:
Write complete, working code for this file. Include:
1. All necessary imports
2. Complete implementations (not stubs)
3. Docstrings and comments
4. Error handling where appropriate

CRITICAL - SYNTAX REQUIREMENTS:
- Every opening bracket {{ must have a matching closing bracket }}
- Every opening parenthesis ( must have a matching closing parenthesis )
- Every opening square bracket [ must have a matching closing square bracket ]
- Count your brackets before returning the code
- Do NOT truncate or cut off code mid-function

OUTPUT:
Return ONLY the code wrapped in a code block:
```{lang_for_block}
// Your complete code here
```

Write clean, maintainable, production-ready code with balanced brackets."""

            # Try up to 3 times to generate valid code
            max_retries = 3

            # LAYER 3.5: Determine target environment and get constraints
            env_validator = EnvironmentSanityValidator()
            target_env = self._detect_target_environment(lang, file_path)
            env_constraints = EnvironmentSanityValidator.get_environment_constraints(lang, target_env)

            for attempt in range(max_retries):
                # Inject environment constraints into prompt (first attempt only to avoid duplication)
                current_prompt = prompt
                if attempt == 0 and env_constraints:
                    current_prompt += f"\n{env_constraints}"

                # Call LLM with higher token limit for complex code files
                response = self._call_llm(current_prompt, max_tokens=8192)
                if not response:
                    continue

                code_blocks = self._extract_code_blocks(response)
                if code_blocks:
                    lang, code = code_blocks[0]
                else:
                    code = response
                    lang = detect_language(file_path)

                # LAYER 3: Validate generated code
                validation = self.generation_validator.validate(code, lang, spec)

                # LAYER 3.5: Environment Sanity Validation (for all languages)
                if validation.valid:
                    env_validation = env_validator.validate(
                        code, lang, file_path,
                        requested_frameworks=self._extract_requested_frameworks()
                    )
                    if not env_validation.valid:
                        validation.valid = False
                        validation.errors.extend(env_validation.errors)
                        validation.warnings.extend(env_validation.warnings)
                    else:
                        validation.warnings.extend(env_validation.warnings)

                if validation.valid:
                    # Code is valid, save it
                    self.context.generated_files[file_path] = code
                    full_path = self.project_dir / file_path
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(code)
                    files_generated += 1
                    print(f"   ✅ Generated: {file_path} ({len(code)} chars)")

                    # LAYER 4.5: Extract interface for incremental context injection
                    # This allows subsequent file generations to see this file's exports
                    try:
                        extractor = SymbolExtractor(lang)
                        interface = extractor.extract(code, file_path)
                        self.context.interfaces[file_path] = interface
                        if interface.exports:
                            export_names = [e.name for e in interface.exports[:3]]
                            print(f"   📋 Interface: exports {', '.join(export_names)}{'...' if len(interface.exports) > 3 else ''}")
                    except Exception as e:
                        logger.warning(f"Failed to extract interface for {file_path}: {e}")

                    # Show any warnings
                    for warning in validation.warnings:
                        print(f"   ⚠️ Warning: {warning}")
                    break
                else:
                    # Validation failed, retry with feedback
                    if attempt < max_retries - 1:
                        print(f"   ⚠️ Validation failed (attempt {attempt + 1}/{max_retries})")
                        for error in validation.errors:
                            print(f"      - {error}")

                        # Enhance prompt with validation feedback
                        prompt = f"""You are an expert software developer. Your previous code generation had CRITICAL SYNTAX ERRORS:

VALIDATION ERRORS:
{chr(10).join(f'- {e}' for e in validation.errors)}

ORIGINAL TASK:
{context_summary}

FILE: {file_path}
PURPOSE: {purpose}
OUTLINE: {outline}

CRITICAL SYNTAX REQUIREMENTS - YOUR CODE HAD UNBALANCED BRACKETS:
1. Count ALL opening braces {{ and ensure you have the SAME number of closing braces }}
2. Count ALL opening parentheses ( and ensure you have the SAME number of closing parentheses )
3. Every class and function must have a complete body with proper closing braces
4. Do NOT truncate or cut off the code
5. Do NOT use placeholders like '...' or 'TODO'
6. Write the ENTIRE file from start to finish

Return the COMPLETE, SYNTACTICALLY CORRECT code in a code block:
```{lang}
// Your complete, balanced code here
```"""
                    else:
                        # Final attempt failed, save anyway but mark as needing fix
                        print(f"   ❌ Validation failed after {max_retries} attempts, saving for debugging")
                        for error in validation.errors:
                            self.context.issues_found.append({
                                "file": file_path,
                                "severity": "error",
                                "description": error,
                                "fix": "Regenerate with complete implementation"
                            })
                        self.context.generated_files[file_path] = code
                        full_path = self.project_dir / file_path
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(code)
                        files_generated += 1

        # LAYER 4: Validate imports across all files
        if self.context.generated_files:
            print(f"\n🔍 Validating imports across {len(self.context.generated_files)} files...")
            self._project_language = detect_project_language(self.context.generated_files)

            resolver = ImportResolver(
                self.context.generated_files,
                self._project_language,
                self.project_dir
            )
            import_result = resolver.validate()

            if import_result.valid:
                print("   ✅ All imports resolved")
            else:
                print("   ❌ Import resolution issues:")
                for error in import_result.errors[:5]:
                    print(f"      - {error}")
                    # Add to issues for debugging phase
                    self.context.issues_found.append({
                        "file": "cross-file",
                        "severity": "error",
                        "description": error,
                        "fix": "Check import paths and module names"
                    })

            # LAYER 4.5: Consistency Verification (Symbol Table + Cross-Reference)
            print(f"\n🔗 Verifying cross-file consistency...")
            consistency_result = self._verify_consistency_and_repair()
            if not consistency_result:
                print("   ⚠️ Some consistency issues could not be repaired")

        print(f"\n✅ Generated {files_generated}/{len(self.context.file_specifications)} files")
        return files_generated > 0

    def _verify_consistency_and_repair(self, max_repair_attempts: int = 2) -> bool:
        """
        LAYER 4.5: Verify cross-file consistency and attempt repairs.

        Checks:
        1. All imports resolve to actual exports
        2. Import/export styles match (default vs named)
        3. Constructor/function signatures match call sites

        Args:
            max_repair_attempts: Maximum number of repair attempts per file

        Returns:
            True if all files are consistent, False otherwise
        """
        if not self.context.generated_files:
            return True

        # Create consistency verifier with current files
        verifier = ConsistencyVerifier(
            self.context.generated_files,
            self._project_language,
            self.project_dir
        )

        result = verifier.validate()

        if result.valid:
            print("   ✅ All cross-file references verified")
            return True

        # Group errors by source file for targeted repair
        file_errors: Dict[str, List[str]] = {}
        for error in result.errors:
            # Parse source file from error string (format: "filepath:line: message")
            parts = error.split(':', 2)
            if len(parts) >= 1:
                source_file = parts[0]
                if source_file not in file_errors:
                    file_errors[source_file] = []
                file_errors[source_file].append(error)

        print(f"   ❌ Found {len(result.errors)} consistency issues in {len(file_errors)} files")

        # Attempt to repair each file with errors
        repaired_count = 0
        for source_file, errors in file_errors.items():
            print(f"\n   🔧 Repairing: {source_file}")
            for error in errors[:3]:  # Show first 3 errors
                print(f"      - {error}")

            if source_file not in self.context.generated_files:
                print(f"      ⚠️ File not found in generated files, skipping")
                continue

            # Attempt repair by regenerating the file with full interface context
            repaired = self._repair_file_for_consistency(source_file, errors, max_repair_attempts)
            if repaired:
                repaired_count += 1
                print(f"      ✅ Repaired successfully")
            else:
                print(f"      ❌ Could not repair automatically")
                # Add to issues for debugging phase
                for error in errors:
                    self.context.issues_found.append({
                        "file": source_file,
                        "severity": "error",
                        "description": f"Consistency: {error}",
                        "fix": "Check import/export statements and function signatures"
                    })

        return len(file_errors) == repaired_count

    def _repair_file_for_consistency(
        self,
        file_path: str,
        errors: List[str],
        max_attempts: int
    ) -> bool:
        """
        Attempt to repair a file to fix consistency errors.

        Strategy: Regenerate the entire file with full interface context
        (per user preference 2-A: regenerate rather than surgical edit)

        Args:
            file_path: Path to the file to repair
            errors: List of consistency errors for this file
            max_attempts: Maximum repair attempts

        Returns:
            True if repair successful, False otherwise
        """
        # Find the original spec for this file
        spec = None
        for s in self.context.file_specifications:
            if s.get("path") == file_path:
                spec = s
                break

        if not spec:
            logger.warning(f"No spec found for {file_path}, cannot repair")
            return False

        # Build comprehensive interface context
        interface_context = "EXISTING FILE INTERFACES (you MUST use these exact signatures):\n\n"
        for iface_path, iface in self.context.interfaces.items():
            if iface_path != file_path:  # Don't include self
                if hasattr(iface, 'to_prompt_string'):
                    interface_context += iface.to_prompt_string() + "\n\n"

        # Build error context
        error_context = "CONSISTENCY ERRORS TO FIX:\n"
        for error in errors:
            error_context += f"- {error}\n"

        lang = detect_language(file_path)

        for attempt in range(max_attempts):
            prompt = f"""You are an expert software developer fixing cross-file consistency errors.

{interface_context}

{error_context}

FILE TO REGENERATE: {file_path}
PURPOSE: {spec.get('purpose', '')}
OUTLINE: {spec.get('contents_outline', '')}

CRITICAL REQUIREMENTS:
1. Use EXACTLY the constructor signatures and method names from EXISTING FILE INTERFACES
2. Use the correct import style (default vs named) to match how symbols are exported
3. Pass the correct number of arguments to constructors and functions
4. Ensure all imports reference files that exist and exports that are defined

Write the COMPLETE, CORRECTED code for this file. Do not truncate.

Return the code in a code block:
```{lang}
// your code here
```"""

            response = self._call_llm(prompt, max_tokens=4096)
            if not response:
                continue

            code_blocks = self._extract_code_blocks(response)
            if code_blocks:
                _, code = code_blocks[0]
            else:
                code = response

            # Validate syntax
            validation = self.generation_validator.validate(code, lang, spec)
            if not validation.valid:
                logger.warning(f"Repair attempt {attempt + 1} failed validation: {validation.errors}")
                continue

            # Temporarily update the file and check consistency
            old_code = self.context.generated_files[file_path]
            self.context.generated_files[file_path] = code

            # Re-verify consistency for this file
            temp_verifier = ConsistencyVerifier(
                self.context.generated_files,
                self._project_language,
                self.project_dir
            )
            temp_result = temp_verifier.validate()

            # Check if errors for this file are fixed
            remaining_errors = [e for e in temp_result.errors if e.startswith(file_path)]

            if len(remaining_errors) < len(errors):
                # Improvement! Save the file
                full_path = self.project_dir / file_path
                full_path.write_text(code)

                # Update interface
                try:
                    extractor = SymbolExtractor(lang)
                    interface = extractor.extract(code, file_path)
                    self.context.interfaces[file_path] = interface
                except Exception as e:
                    logger.warning(f"Failed to update interface for {file_path}: {e}")

                if len(remaining_errors) == 0:
                    return True
                else:
                    # Partial improvement, continue trying
                    errors = remaining_errors
            else:
                # No improvement, rollback
                self.context.generated_files[file_path] = old_code

        return False

    def _phase_debugging(self) -> bool:
        """
        Phase 6: Review and debug generated code.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.DEBUGGING)

        if not self.context.generated_files:
            print("\n⚠️ No files to debug")
            return True

        self.context.issues_found = []

        # Review each file
        for file_path, code in self.context.generated_files.items():
            print(f"\n   Reviewing: {file_path}...")

            # Truncate code for context efficiency (prevent excessive tokens, but allow enough for review)
            # Increased limit to prevent false positives about truncation
            code_preview = code[:30000] if len(code) > 30000 else code

            prompt = f"""You are a senior code reviewer finding bugs and issues.

FILE: {file_path}
CODE:
```
{code_preview}
```

TASK:
1. Identify bugs, errors, and issues
2. Check for missing imports, syntax errors
3. Look for logic errors
4. Check error handling

OUTPUT FORMAT (JSON):
```json
{{
    "issues": [
        {{"severity": "error|warning|info", "line": null, "description": "...", "fix": "..."}}
    ],
    "overall_quality": "good|needs-work|critical-issues",
    "suggestions": ["improvements"]
}}
```

Be thorough but practical."""

            response = self._call_llm(prompt, max_tokens=2048)
            if response:
                data = self._extract_json(response)
                if data and "issues" in data:
                    issues = data["issues"]
                    for issue in issues:
                        issue["file"] = file_path
                        self.context.issues_found.append(issue)

                    error_count = len([i for i in issues if i.get("severity") == "error"])
                    if error_count > 0:
                        print(f"   ⚠️ Found {error_count} errors in {file_path}")
                    else:
                        print(f"   ✅ {file_path}: {data.get('overall_quality', 'reviewed')}")

        # Fix critical issues
        critical_issues = [i for i in self.context.issues_found if i.get("severity") == "error"]
        if critical_issues:
            print(f"\n🔧 Fixing {len(critical_issues)} critical issues...")
            for issue in critical_issues[:5]:  # Limit fixes per iteration
                self._fix_issue(issue)

        print(f"\n✅ Debug phase complete: {len(self.context.issues_found)} issues found")
        return True

    def _fix_issue(self, issue: Dict) -> bool:
        """Attempt to fix a single issue."""
        file_path = issue.get("file", "")
        if file_path not in self.context.generated_files:
            return False

        code = self.context.generated_files[file_path]
        description = issue.get("description", "")
        fix_hint = issue.get("fix", "")
        
        # Determine language
        ext = Path(file_path).suffix.lower()
        if ext == '.py':
            language = 'python'
        elif ext in ('.js', '.jsx'):
            language = 'javascript'
        elif ext in ('.ts', '.tsx'):
            language = 'typescript'
        else:
            language = 'text'

        print(f"   🔧 Fixing {file_path}: {description[:50]}...")

        # Initial prompt
        prompt = f"""You are fixing a bug in code.

FILE: {file_path}
ISSUE: {description}
SUGGESTED FIX: {fix_hint}

CURRENT CODE:
```
{code}
```

TASK:
Provide the COMPLETE fixed code. Apply the fix and ensure the code is complete.

OUTPUT:
Return the complete fixed code in a code block.
```python
# Fixed code here
```"""

        # Retry loop for validation
        max_retries = 3
        for attempt in range(max_retries):
            response = self._call_llm(prompt, max_tokens=4096)
            if not response:
                continue

            code_blocks = self._extract_code_blocks(response)
            if code_blocks:
                _, fixed_code = code_blocks[0]
                
                # Validation (Layer 3)
                validation = self.generation_validator.validate(fixed_code, language)
                
                if validation.valid:
                    # Success!
                    self.context.generated_files[file_path] = fixed_code
                    full_path = self.project_dir / file_path
                    full_path.write_text(fixed_code)
                    print(f"      ✅ Fixed and validated")
                    return True
                else:
                    # Validation failed
                    print(f"      ⚠️ Fix validation failed (attempt {attempt + 1}): {', '.join(validation.errors[:2])}")
                    
                    # Update prompt for retry
                    prompt = f"""Your fix was invalid:
{chr(10).join(f'- {e}' for e in validation.errors)}

Please regenerate the COMPLETE, VALID code for {file_path} fixed."""
            
        print(f"      ❌ Failed to generate valid fix after {max_retries} attempts")
        return False

    def _phase_testing(self) -> bool:
        """
        Phase 7: Generate and run tests with Docker sandbox execution.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.TESTING)

        self.context.tests_passed = []
        self.context.tests_failed = []

        if not self.context.generated_files:
            print("\n⚠️ No files to test")
            return True

        # LAYER 7: First, validate execution in Docker sandbox
        print("\n🔒 LAYER 7: Execution Validation (Docker Sandbox)")

        # Initialize the code validator with Docker sandbox
        if self.code_validator is None:
            self.code_validator = CodeValidator(
                self.project_dir,
                self._project_language,
                timeout=30,
                use_docker=True
            )

        # Show sandbox status
        if self.code_validator.docker_available:
            print("   🐳 Docker sandbox: ENABLED")
        else:
            print("   ⚠️ Docker not available, using subprocess fallback")

        # Validate imports by actually running them
        print("\n   🧪 Validating imports...")
        exec_result = self.code_validator.validate_execution()

        if exec_result.success:
            print(f"   ✅ Import validation passed ({exec_result.sandbox_type})")
        else:
            print(f"   ❌ Import validation failed:")
            for error in exec_result.errors[:3]:
                error_msg = error.get('message', str(error))[:200]
                print(f"      - {error_msg}")
                self.context.issues_found.append({
                    "file": "execution",
                    "severity": "error",
                    "description": error_msg,
                    "fix": "Fix import or dependency issue"
                })

        # Generate test file
        main_files = [f for f in self.context.generated_files.keys()
                      if not f.startswith("test_") and f.endswith('.py')]

        if not main_files:
            print("\n⚠️ No main Python files to test")
            return True

        # Generate tests for main file
        main_file = main_files[0]
        main_code = self.context.generated_files[main_file][:2500]

        print(f"\n   Generating tests for: {main_file}...")

        prompt = f"""You are writing unit tests for code.

FILE: {main_file}
CODE:
```
{main_code}
```

TASK:
Write comprehensive unit tests using pytest.
- Test main functionality
- Test edge cases
- Test error handling
- Make tests self-contained (don't require external resources)

OUTPUT:
Return complete test code in a code block.
```python
import pytest
# Import the module being tested

# Test code here
```"""

        response = self._call_llm(prompt, max_tokens=3000)
        if response:
            code_blocks = self._extract_code_blocks(response)
            if code_blocks:
                _, test_code = code_blocks[0]
                test_file = f"test_{Path(main_file).stem}.py"
                self.context.generated_files[test_file] = test_code

                # Save test file
                full_path = self.project_dir / test_file
                full_path.write_text(test_code)
                print(f"   ✅ Generated: {test_file}")

                # LAYER 7: Run tests in Docker sandbox
                print(f"\n   🧪 Running tests in sandbox...")
                test_result = self.code_validator.run_tests()

                if test_result.ran:
                    if test_result.passed:
                        for t in test_result.passed[:5]:
                            print(f"   ✅ PASSED: {t}")
                            self.context.tests_passed.append(t)
                    if test_result.failed:
                        for t in test_result.failed[:5]:
                            print(f"   ❌ FAILED: {t}")
                            self.context.tests_failed.append(t)
                            self.context.issues_found.append({
                                "file": test_file,
                                "severity": "error",
                                "description": f"Test failed: {t}",
                                "fix": "Fix the failing test or the code it tests"
                            })
                    if test_result.errors:
                        for e in test_result.errors[:3]:
                            print(f"   ❌ ERROR: {e}")

                    # Summary
                    total = len(test_result.passed) + len(test_result.failed)
                    if total > 0:
                        print(f"\n   📊 Test Results: {len(test_result.passed)}/{total} passed")
                else:
                    if test_result.error_message:
                        print(f"   ⚠️ Could not run tests: {test_result.error_message}")
                    else:
                        print("   ⚠️ Tests did not run")

        print(f"\n✅ Testing phase complete")
        print(f"   Tests generated: {len([f for f in self.context.generated_files if f.startswith('test_')])}")
        print(f"   Tests passed: {len(self.context.tests_passed)}")
        print(f"   Tests failed: {len(self.context.tests_failed)}")
        return True

    # =========================================================================
    # STATE MACHINE CONTROL
    # =========================================================================

    def _next_phase(self) -> None:
        """Advance to the next phase."""
        current_index = self._phase_order.index(self.current_phase)
        if current_index < len(self._phase_order) - 1:
            self.current_phase = self._phase_order[current_index + 1]

    def _should_iterate(self) -> bool:
        """
        Determine if we should loop back for another iteration.

        Returns:
            True if should iterate, False if done
        """
        if self.context.iteration >= self.context.max_iterations:
            print(f"\n⚠️ Max iterations ({self.context.max_iterations}) reached")
            return False

        # Check for unresolved critical issues
        critical_issues = [i for i in self.context.issues_found
                          if i.get("severity") == "error"]

        if critical_issues:
            print(f"\n🔄 {len(critical_issues)} critical issues remain, iterating...")
            self.context.iteration += 1
            self.current_phase = DevelopmentPhase.DEBUGGING
            return True

        # Check for failed tests
        if self.context.tests_failed:
            print(f"\n🔄 {len(self.context.tests_failed)} tests failed, iterating...")
            self.context.iteration += 1
            self.current_phase = DevelopmentPhase.DEBUGGING
            return True

        return False

    def run(self, user_request: str) -> bool:
        """
        Run the complete development cycle.

        Args:
            user_request: The user's coding request

        Returns:
            True if completed successfully, False otherwise
        """
        self._print_header(f"🤖 CLI CODING AGENT v{VERSION}")
        print(f"Project: {self.project_name}")
        print(f"Output: {self.project_dir}")
        print(f"LLM: {self._provider}/{self._model}")
        print(f"Request: {user_request[:100]}...")

        # Test LLM connection
        print("\n🔌 Testing LLM connection...")
        success, message = self.llm_client.test_connection()
        if not success:
            print(f"❌ LLM connection failed: {message}")
            return False
        print(f"✅ {message}")

        # Phase execution loop
        phase_handlers = {
            DevelopmentPhase.REQUIREMENTS: lambda: self._phase_requirements(user_request),
            DevelopmentPhase.PLANNING: self._phase_planning,
            DevelopmentPhase.ARCHITECTURE: self._phase_architecture,
            DevelopmentPhase.DESIGN: self._phase_design,
            DevelopmentPhase.INTERFACE_GENERATION: self._phase_interface_generation,
            DevelopmentPhase.CODING: self._phase_coding,
            DevelopmentPhase.DEBUGGING: self._phase_debugging,
            DevelopmentPhase.TESTING: self._phase_testing,
        }

        while self.current_phase != DevelopmentPhase.COMPLETE:
            handler = phase_handlers.get(self.current_phase)
            if handler:
                success = handler()
                if not success:
                    self.logger.error(f"Phase {self.current_phase.name} failed")
                    # Continue anyway to see what we can salvage

            self._next_phase()

            # Check if we need to iterate
            if self.current_phase == DevelopmentPhase.COMPLETE:
                if self._should_iterate():
                    continue  # Loop back

        # Final summary
        self._print_header("✅ DEVELOPMENT COMPLETE", "=")
        print(f"\nProject: {self.project_name}")
        print(f"Location: {self.project_dir}")
        print(f"Iterations: {self.context.iteration}")
        print(f"\nFiles generated:")
        for file_path in self.context.generated_files:
            full_path = self.project_dir / file_path
            if full_path.exists():
                size = full_path.stat().st_size
                print(f"   • {file_path} ({size} bytes)")

        print(f"\n{self.context.get_summary()}")

        # Save project context
        context_path = self.project_dir / "project_context.json"
        with open(context_path, "w") as f:
            json.dump(self.context.to_compact_dict(), f, indent=2)
        print(f"\nContext saved: {context_path}")

        return True

    def test_connection(self) -> bool:
        """Test LLM connection."""
        success, message = self.llm_client.test_connection()
        if success:
            self.logger.info(message)
        else:
            self.logger.error(message)
        return success

    def show_config(self) -> None:
        """Display current configuration."""
        llm_info = self.llm_client.get_config_info()

        print("\n=== CLI Coding Agent Configuration ===")
        print(f"LLM Provider: {llm_info['primary_provider']}")
        print(f"LLM Model: {llm_info['primary_model']}")
        print(f"Temperature: {llm_info['temperature']}")
        print(f"Max Tokens: {llm_info['max_tokens']}")
        print(f"Fallback Enabled: {llm_info['fallback_enabled']}")
        if llm_info['fallback_enabled']:
            print(f"Fallback Order: {llm_info['fallback_order']}")
        print(f"Max Iterations: {self._max_iterations}")
        print(f"Output Directory: {self.output_dir}")
        print(f"\nLLM Config: {llm_info['config_path']}")
        if self.config:
            print(f"Agent Config: {self.config.agent_name} in agents_config.yaml")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CLI Coding Agent - Autonomous code generation through iterative development phases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a simple script
  python cli_coding_agent.py "Create a Python script to calculate fibonacci numbers"

  # Generate with custom project name
  python cli_coding_agent.py "Build a REST API for user management" --project my-api

  # Run with verbose logging
  python cli_coding_agent.py "Create a web scraper" --verbose

  # Use a specific LLM provider/model
  python cli_coding_agent.py "Create a CLI tool" --provider ollama --model deepseek-v3.2:cloud
  python cli_coding_agent.py "Create a CLI tool" --provider openai --model gpt-4o
  python cli_coding_agent.py "Create a CLI tool" --provider anthropic --model claude-sonnet-4-20250514

  # Test LLM connection
  python cli_coding_agent.py --test

  # Test with specific provider
  python cli_coding_agent.py --test --provider openai

  # Show configuration
  python cli_coding_agent.py --show-config
        """
    )

    parser.add_argument(
        "request",
        nargs="?",
        help="Your coding request (what you want to build)"
    )

    parser.add_argument(
        "--project", "-p",
        dest="project_name",
        help="Project name (default: auto-generated)"
    )

    parser.add_argument(
        "--output", "-o",
        dest="output_dir",
        default="generated_projects",
        help="Output directory for generated projects (default: generated_projects)"
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum development iterations (default: 10)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Test LLM connection and exit"
    )

    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show configuration and exit"
    )

    parser.add_argument(
        "--provider",
        choices=['ollama', 'openai', 'anthropic', 'gemini', 'qwen'],
        help="LLM provider to use (overrides config)"
    )

    parser.add_argument(
        "--model",
        help="Model name to use (overrides config, e.g., deepseek-v3.2:cloud, gpt-4o)"
    )

    args = parser.parse_args()

    # Initialize agent
    agent = CLICodingAgent(
        output_dir=args.output_dir,
        project_name=args.project_name,
        verbose=args.verbose,
        max_iterations=args.max_iterations,
        provider=args.provider,
        model=args.model
    )

    # Handle special modes
    if args.show_config:
        agent.show_config()
        sys.exit(0)

    if args.test:
        print("\n🔌 Testing LLM connection...")
        if agent.test_connection():
            print("✅ LLM connection successful!")
            sys.exit(0)
        else:
            print("❌ LLM connection failed")
            sys.exit(1)

    # Require request for normal operation
    if not args.request:
        parser.print_help()
        print("\n❌ Error: Please provide a coding request")
        sys.exit(1)

    # Run the agent
    success = agent.run(args.request)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
