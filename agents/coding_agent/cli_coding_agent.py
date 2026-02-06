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
import subprocess
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
from .config_accessor import get_max_iterations

# Import Context Management and Awareness System (v2.2)
try:
    from common.context.manager import ContextManager
    from common.awareness.system import AwarenessSystem
    CONTEXT_SYSTEM_AVAILABLE = True
except ImportError:
    ContextManager = None
    AwarenessSystem = None
    CONTEXT_SYSTEM_AVAILABLE = False

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
    from .services.dependency_resolver import DependencyResolver
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
    from .services.dependency_resolver import DependencyResolver

# Agent name for configuration
AGENT_NAME = "coding_agent"
VERSION = "2.2.0"  # Added Context Management and Awareness System

# Global logger for module-level usage (fallback)
logger = logging.getLogger(__name__)

# Import new enhancement modules (v2.1)
# These provide TUI, hooks, knowledge, planning, verification, and state features
try:
    from .state.persistence import StatePersistence, check_resumable_session
    from .hooks.hook_manager import HookManager, HookTrigger
    from .hooks.builtin_hooks import register_builtin_hooks
    from .knowledge.raica_client import RAICAKnowledgeClient
    from .planning.iterative_planner import IterativePlanner, PlanStep
    from .planning.refinement_loop import RefinementLoop
    from .verification.success_verifier import SuccessVerifier, VerificationResult
except ImportError:
    # Fallback for direct execution
    try:
        from state.persistence import StatePersistence, check_resumable_session
        from hooks.hook_manager import HookManager, HookTrigger
        from hooks.builtin_hooks import register_builtin_hooks
        from knowledge.raica_client import RAICAKnowledgeClient
        from planning.iterative_planner import IterativePlanner, PlanStep
        from planning.refinement_loop import RefinementLoop
        from verification.success_verifier import SuccessVerifier, VerificationResult
    except ImportError:
        # Modules not yet installed - set to None for graceful degradation
        StatePersistence = None
        check_resumable_session = None
        HookManager = None
        HookTrigger = None
        register_builtin_hooks = None
        RAICAKnowledgeClient = None
        IterativePlanner = None
        PlanStep = None
        RefinementLoop = None
        SuccessVerifier = None
        VerificationResult = None


class DevelopmentPhase(Enum):
    """Development lifecycle phases."""
    REQUIREMENTS = auto()
    COMPLEXITY_ASSESSMENT = auto()  # NEW: Assess if SIMPLE/MEDIUM/COMPLEX
    SIMPLE_GENERATION = auto()      # NEW: Direct single-file generation for SIMPLE
    PLANNING = auto()
    ARCHITECTURE = auto()
    DESIGN = auto()
    INTERFACE_GENERATION = auto()
    CODING = auto()
    DEBUGGING = auto()
    TESTING = auto()
    COMPLETE = auto()


class ProjectComplexity(Enum):
    """Project complexity levels determined by LLM."""
    SIMPLE = "simple"      # Single script, no architecture needed (e.g., "plot sigmoid")
    MEDIUM = "medium"      # Few files, minimal architecture
    COMPLEX = "complex"    # Full project with architecture/design phases


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

    # Complexity assessment (SIMPLE, MEDIUM, COMPLEX)
    complexity: str = "complex"  # Default to complex for safety

    # Planning outputs
    implementation_plan: List[str] = field(default_factory=list)

    # Architecture outputs
    architecture_decisions: Dict[str, str] = field(default_factory=dict)
    components: List[Dict[str, str]] = field(default_factory=list)

    # Design outputs
    file_specifications: List[Dict[str, Any]] = field(default_factory=list)
    external_dependencies: List[str] = field(default_factory=list)

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
    max_iterations: Optional[int] = None

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
        max_iterations: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        use_existing_project: bool = False
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
            use_existing_project: If True, uses output_dir directly as project root
        """
        # Setup logging first
        log_level = logging.DEBUG if verbose else logging.INFO
        self.logger = setup_agent_logging(AGENT_NAME, level=log_level)

        # Fallback if logger is None (can happen when TUI patches logging)
        if self.logger is None:
            self.logger = logging.getLogger(AGENT_NAME)
            self.logger.setLevel(log_level)
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                ))
                self.logger.addHandler(handler)

        # Load agent-specific configuration (for non-LLM settings)
        try:
            self.config = get_agent_config(AGENT_NAME)
            self._max_iterations = self.config.get('execution', 'max_iterations', default=max_iterations)
        except AgentConfigError as e:
            self.logger.warning(f"Could not load agent config: {e}")
            self.config = None
            self._max_iterations = max_iterations

        # Override max_iterations if explicitly provided
        if max_iterations != 2:
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
        
        if use_existing_project:
            self.logger.info(f"Using existing project directory: {self.output_dir}")
            self.project_dir = self.output_dir
        else:
            self.project_dir = self.output_dir / self.project_name
            self.project_dir.mkdir(exist_ok=True, parents=True)

        # State machine
        self.current_phase = DevelopmentPhase.REQUIREMENTS
        self.context = ProjectContext(max_iterations=self._max_iterations)

        # Phase transition rules
        self._phase_order = [
            DevelopmentPhase.REQUIREMENTS,
            DevelopmentPhase.COMPLEXITY_ASSESSMENT,  # NEW: Assess complexity
            DevelopmentPhase.SIMPLE_GENERATION,      # NEW: For SIMPLE requests only
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
        self._project_language = 'auto'  # Detected from user request, NOT defaulted to Python

        # Initialize v2.1 enhancement modules
        self._init_enhancement_modules()

        # Initialize Context Management and Awareness System (v2.2)
        self._init_context_system()

        self.logger.info(f"CLI Coding Agent v{VERSION} initialized")
        self.logger.info(f"Project: {self.project_name}")
        self.logger.info(f"Output: {self.project_dir}")
        self.logger.info(f"LLM Provider: {self._provider}")
        self.logger.info(f"LLM Model: {self._model}")

    def _init_enhancement_modules(self) -> None:
        """Initialize v2.1 enhancement modules with graceful degradation."""
        # State Persistence
        if StatePersistence is not None:
            try:
                self.state_persistence = StatePersistence(self.project_dir)
                self.logger.debug("State persistence initialized")
            except Exception as e:
                self.logger.warning(f"State persistence unavailable: {e}")
                self.state_persistence = None
        else:
            self.state_persistence = None

        # Hook Manager
        if HookManager is not None:
            try:
                hooks_config_path = Path(__file__).parent / "config" / "hooks_config.yaml"
                self.hook_manager = HookManager(hooks_config_path)

                # Register built-in hooks
                if register_builtin_hooks is not None:
                    hooks_config = {}
                    if self.config:
                        hooks_config = self.config.get('hooks', 'builtin', default={})
                    register_builtin_hooks(self.hook_manager, hooks_config)
                    self.logger.debug("Built-in hooks registered")
            except Exception as e:
                self.logger.warning(f"Hook manager unavailable: {e}")
                self.hook_manager = None
        else:
            self.hook_manager = None

        # RAICA Knowledge Client
        if RAICAKnowledgeClient is not None:
            try:
                knowledge_config = {}
                if self.config:
                    knowledge_config = self.config.get('knowledge', default={})

                raica_url = knowledge_config.get('raica_server_url', 'http://localhost:5000')
                self.knowledge_client = RAICAKnowledgeClient(base_url=raica_url)
                self.logger.debug(f"Knowledge client initialized: {raica_url}")
            except Exception as e:
                self.logger.warning(f"Knowledge client unavailable: {e}")
                self.knowledge_client = None
        else:
            self.knowledge_client = None

        # Iterative Planner
        if IterativePlanner is not None:
            try:
                self.iterative_planner = IterativePlanner(
                    self.llm_client,
                    self.knowledge_client
                )
                self.logger.debug("Iterative planner initialized")
            except Exception as e:
                self.logger.warning(f"Iterative planner unavailable: {e}")
                self.iterative_planner = None
        else:
            self.iterative_planner = None

        # Refinement Loop
        if RefinementLoop is not None:
            try:
                threshold = 90.0
                if self.config:
                    threshold = float(self.config.get('verification', 'success_threshold', default=90))
                self.refinement_loop = RefinementLoop(
                    self.llm_client,
                    completeness_threshold=threshold
                )
                self.logger.debug("Refinement loop initialized")
            except Exception as e:
                self.logger.warning(f"Refinement loop unavailable: {e}")
                self.refinement_loop = None
        else:
            self.refinement_loop = None

        # Dependency Resolver (v2.2)
        self.dependency_resolver = DependencyResolver(self.llm_client)
        self.logger.debug("Dependency resolver initialized")

        # Success Verifier
        if SuccessVerifier is not None:
            try:
                threshold = 90.0
                if self.config:
                    threshold = float(self.config.get('verification', 'success_threshold', default=90))
                self.success_verifier = SuccessVerifier(
                    self.llm_client,
                    success_threshold=threshold
                )
                self.logger.debug("Success verifier initialized")
            except Exception as e:
                self.logger.warning(f"Success verifier unavailable: {e}")
                self.success_verifier = None
        else:
            self.success_verifier = None

        # Log enhancement module status
        modules_status = {
            'state_persistence': self.state_persistence is not None,
            'hook_manager': self.hook_manager is not None,
            'knowledge_client': self.knowledge_client is not None,
            'iterative_planner': self.iterative_planner is not None,
            'refinement_loop': self.refinement_loop is not None,
            'success_verifier': self.success_verifier is not None
        }
        enabled_count = sum(modules_status.values())
        self.logger.info(f"Enhancement modules: {enabled_count}/6 enabled")

    def _init_context_system(self) -> None:
        """
        Initialize Context Management and Awareness System (v2.2).

        This provides:
        - System awareness (OS, tools, package managers) - detected at startup
        - User preferences and patterns
        - Directory, project, task, and conversation context
        - Debugging discipline enforcement
        """
        if not CONTEXT_SYSTEM_AVAILABLE:
            self.logger.warning("Context system not available (import failed)")
            self.context_manager = None
            return

        try:
            self.context_manager = ContextManager(
                project_dir=self.project_dir,
                user_home=Path.home(),
                auto_initialize=True
            )

            # Log awareness summary
            if self.context_manager.awareness.is_initialized:
                sys_profile = self.context_manager.awareness.system_profile
                self.logger.info(
                    f"System awareness: {sys_profile.os_name} "
                    f"{sys_profile.distro or ''} "
                    f"({sys_profile.architecture})"
                )

                # Log available key tools
                key_tools = ['git', 'docker', 'python3', 'node', 'npm']
                available = [t for t in key_tools if sys_profile.is_tool_available(t)]
                if available:
                    self.logger.debug(f"Available tools: {', '.join(available)}")

                # Log user profile
                user_profile = self.context_manager.awareness.user_profile
                if user_profile.total_sessions > 0:
                    self.logger.debug(
                        f"User: {user_profile.total_sessions} sessions, "
                        f"{user_profile.total_tasks_completed} tasks completed"
                    )

            self.logger.info("Context management system initialized")

        except Exception as e:
            self.logger.warning(f"Context system initialization failed: {e}")
            self.context_manager = None

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
            DevelopmentPhase.COMPLEXITY_ASSESSMENT: "🎯",
            DevelopmentPhase.SIMPLE_GENERATION: "⚡",
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

    def _llm_classify_entry_file(self, user_request: str) -> str:
        """
        Ask LLM to determine the appropriate entry file for a project request.

        This follows CLAUDE.md: LLM interprets text, RAICA executes.
        NO hardcoded keyword matching.

        Args:
            user_request: The user's original project request

        Returns:
            Entry filename (e.g., "main.py", "index.html", "index.js")
        """
        prompt = f"""You are a software architect determining the appropriate entry file for a new project.

USER REQUEST: {user_request[:500]}

Based on the request, determine the single most appropriate entry file.
Consider:
- Web applications (HTML/CSS/JS) → index.html
- Node.js/JavaScript projects → index.js
- TypeScript projects → index.ts
- Python applications → main.py
- Go applications → main.go
- Rust applications → main.rs
- GDScript/Godot → main.gd
- Other languages → appropriate main/index file

Respond with ONLY a JSON object:
{{"entry_file": "filename.ext", "language": "language_name"}}

Examples:
- "create a calculator webapp" → {{"entry_file": "index.html", "language": "html"}}
- "build a CLI tool in Python" → {{"entry_file": "main.py", "language": "python"}}
- "express REST API" → {{"entry_file": "index.js", "language": "javascript"}}
"""
        response = self._call_llm(prompt)  # Use config max_tokens
        if response:
            data = self._extract_json(response)
            if data and 'entry_file' in data:
                self.logger.info(f"LLM classified entry file: {data['entry_file']}")
                return data['entry_file']

        # Fallback only if LLM completely fails (not based on keywords!)
        self.logger.warning("LLM classification failed, defaulting to main.py")
        return "main.py"

    def _llm_classify_language(self, user_request: str, filename: str) -> Tuple[str, str]:
        """
        Ask LLM to determine language and run instruction when file extension is ambiguous.

        This follows CLAUDE.md: LLM interprets text, RAICA executes.

        Args:
            user_request: The user's original project request
            filename: The target filename

        Returns:
            Tuple of (language, run_instruction)
        """
        prompt = f"""You are determining the programming language for a project.

USER REQUEST: {user_request[:500]}
FILENAME: {filename}

Determine the programming language and how to run this file.

Respond with ONLY a JSON object:
{{"language": "language_name", "run_instruction": "command to run the file"}}

Examples:
- Python script → {{"language": "python", "run_instruction": "python {filename}"}}
- HTML page → {{"language": "html", "run_instruction": "open {filename} in browser"}}
- Node.js → {{"language": "javascript", "run_instruction": "node {filename}"}}
"""
        response = self._call_llm(prompt)  # Use config max_tokens
        if response:
            data = self._extract_json(response)
            if data and 'language' in data:
                lang = data.get('language', 'python')
                run_cmd = data.get('run_instruction', f'python {filename}')
                self.logger.info(f"LLM classified language: {lang}")
                return (lang, run_cmd)

        # Fallback only if LLM completely fails
        self.logger.warning("LLM language classification failed, defaulting to python")
        return ("python", f"python {filename}")

    def _extract_code_blocks(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract code blocks from LLM response.

        ARCHITECTURE: If standard markdown extraction fails, asks LLM to extract.
        NO hardcoded language patterns - LLM decides what is code.

        Returns:
            List of (language, code) tuples
        """
        from .llm_client import strip_thinking_content

        # First strip any thinking/reasoning content from the response
        content = strip_thinking_content(content)

        # Try standard markdown code blocks first
        pattern = r'```(\w+)?\s*\n([\s\S]*?)```'
        matches = re.findall(pattern, content)

        if matches:
            return [(lang or "text", code.strip()) for lang, code in matches]

        # Try code blocks without newline after language
        pattern2 = r'```(\w+)?([\s\S]*?)```'
        matches = re.findall(pattern2, content)

        if matches:
            return [(lang or "text", code.strip()) for lang, code in matches]

        # ═══════════════════════════════════════════════════════════════════════
        # LLM-DRIVEN CODE EXTRACTION
        # No hardcoded patterns - ask LLM to extract the code
        # ═══════════════════════════════════════════════════════════════════════
        self.logger.info("No markdown code blocks found, asking LLM to extract code...")

        extracted = self._llm_extract_code(content)
        if extracted:
            return extracted

        self.logger.warning(f"Could not extract any code blocks from response ({len(content)} chars)")
        return []

    def _llm_extract_code(self, content: str) -> List[Tuple[str, str]]:
        """
        Use LLM to extract code from a response that doesn't have proper markdown formatting.

        ARCHITECTURE: LLM decides what is code, RAICA executes blindly.
        """
        if len(content) < 50:
            return []

        prompt = f"""The following text contains code but is not properly formatted with markdown code blocks.
Extract ONLY the actual code (no explanations, no markdown, no commentary).

TEXT TO EXTRACT CODE FROM:
{content[:8000]}

Return your response as JSON:
{{
    "language": "html",  // or "python", "javascript", "css", etc.
    "code": "... the extracted code here ..."
}}

RULES:
1. Extract ONLY the executable code
2. Do NOT include any explanations or commentary
3. Detect the language from the code itself
4. If there are multiple code sections, extract the main/complete one
5. Return ONLY the JSON, no other text"""

        try:
            response = self._call_llm(prompt)  # Use config max_tokens
            if response:
                from .utils.json_utils import extract_json_from_llm_response
                data = extract_json_from_llm_response(response)
                if data and 'code' in data:
                    code = data['code']
                    language = data.get('language', 'text')
                    if code and len(code) > 50:
                        self.logger.info(f"LLM extracted {language} code ({len(code)} chars)")
                        return [(language, code)]
        except Exception as e:
            self.logger.warning(f"LLM code extraction failed: {e}")

        return []

    def _detect_target_environment(self, language: str, file_path: str) -> str:
        """
        Detect the target runtime environment using LLM analysis.

        ARCHITECTURE: LLM decides environment, no hardcoded keyword matching.

        Args:
            language: Programming language
            file_path: File path for context

        Returns:
            Environment string: 'browser', 'node', 'python-cli', 'python-web', etc.
        """
        # Use LLM to determine environment
        prompt = f"""Determine the target runtime environment for this code project.

USER REQUEST: {self.context.original_request}
LANGUAGE: {language}
FILE PATH: {file_path}

Return ONLY a JSON response with the environment:
{{"environment": "browser"}} - for web pages, HTML/CSS/JS in browser, games, UI
{{"environment": "node"}} - for Node.js server, Express, CLI tools in JS
{{"environment": "python-cli"}} - for Python scripts, CLI tools, utilities
{{"environment": "python-web"}} - for Flask, FastAPI, Django web servers
{{"environment": "auto"}} - if unclear
"""
        try:
            response = self._call_llm(prompt)  # Use config max_tokens
            if response:
                from .utils.json_utils import extract_json_from_llm_response
                data = extract_json_from_llm_response(response)
                if data:
                    env = data.get('environment', 'auto')
                    if env in ('browser', 'node', 'python-cli', 'python-web', 'auto'):
                        return env
                # Fallback: look for keywords in response
                response_lower = response.lower()
                if 'browser' in response_lower:
                    return 'browser'
                elif 'node' in response_lower:
                    return 'node'
                elif 'python-web' in response_lower:
                    return 'python-web'
                elif 'python-cli' in response_lower or 'python' in response_lower:
                    return 'python-cli'
        except Exception as e:
            self.logger.warning(f"Environment detection failed: {e}")

        # Sensible defaults based on language if LLM fails
        if language in ('javascript', 'typescript'):
            return 'browser' if file_path.endswith('.html') else 'browser'
        elif language == 'python':
            return 'python-cli'
        elif language == 'html':
            return 'browser'
        return 'auto'

    def _extract_requested_frameworks(self) -> List[str]:
        """
        Extract frameworks mentioned in the user's request using LLM.

        ARCHITECTURE: LLM identifies frameworks, no hardcoded lists.

        Returns:
            List of framework names mentioned in the request
        """
        prompt = f"""Identify any frameworks or libraries explicitly mentioned in this request.

USER REQUEST: {self.context.original_request}

Return a JSON array of framework/library names that are EXPLICITLY mentioned.
Only include frameworks that the user specifically asked for.
Do NOT guess or add frameworks that weren't mentioned.

Return ONLY valid JSON: {{"frameworks": ["framework1", "framework2"]}}
If no frameworks mentioned, return: {{"frameworks": []}}
"""
        try:
            response = self._call_llm(prompt)  # Use config max_tokens
            if response:
                from .utils.json_utils import extract_json_from_llm_response
                data = extract_json_from_llm_response(response)
                if data:
                    frameworks = data.get('frameworks', [])
                    if isinstance(frameworks, list):
                        return [fw.lower() for fw in frameworks if isinstance(fw, str)]
        except Exception as e:
            self.logger.warning(f"Framework extraction failed: {e}")

        return []

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

        # DEBUG: Log what user_request we received
        self.logger.info(f"REQUIREMENTS - Received user_request: {repr(user_request[:200])}")

        self.context.original_request = user_request

        # DEBUG: Log what we stored
        self.logger.info(f"REQUIREMENTS - Stored in context.original_request: {repr(self.context.original_request[:200])}")

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

    def _phase_complexity_assessment(self) -> bool:
        """
        Phase 1.5: Assess request complexity to determine generation path.

        SIMPLE: Single script, direct generation (e.g., "plot sigmoid")
        MEDIUM: Few files, minimal architecture needed
        COMPLEX: Full project with architecture/design phases

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.COMPLEXITY_ASSESSMENT)

        requirements_text = "\n".join(f"- {r}" for r in self.context.refined_requirements)

        # DEBUG: Log the actual request we're parsing
        self.logger.info(f"COMPLEXITY_ASSESSMENT - Parsing request: {repr(self.context.original_request[:200])}")

        prompt = f"""You are assessing the complexity of a coding request AND extracting file organization details.

USER REQUEST:
{self.context.original_request}

REQUIREMENTS:
{requirements_text}

PROJECT DIRECTORY:
{self.output_dir}

🚨 CRITICAL - YOUR TASKS:

1. **TECHNOLOGY DETECTION** - Identify the target technology from the user's request:
   - "webapp", "web app", "HTML", "browser", "index.html" → Web frontend (HTML/CSS/JS)
   - "Python", "script", "pip" → Python
   - "Node", "npm", "JavaScript", "TypeScript" → Node.js
   - "CLI", "command line" → Infer from context
   DO NOT default to Python unless explicitly requested!

2. **COMPLEXITY ASSESSMENT** - Determine the appropriate complexity level:
   - SIMPLE: Single file (10-100 lines), single purpose, immediately executable
     Examples: "plot sigmoid", "animated button", "hello world"
   - MEDIUM: 2-5 files, some organization needed
     Examples: "todo app", "calculator with GUI", "file converter"
   - COMPLEX: Full project architecture, multiple modules
     Examples: "e-commerce platform", "REST API with auth", "multi-user chat"

3. **FILE ORGANIZATION EXTRACTION** - Extract ALL file organization details from the request:
   - Does user want a subdirectory created? What is its EXACT NAME?
   - What is the EXACT FILENAME (including extension)?
   - What is the FULL PATH (directory + filename)?

   Examples:
   - "create subdirectory named 'mydir'" → directory_to_create: "mydir"
   - "save as file.py" → filename: "file.py"
   - "save as mydir/file.py" → directory_to_create: "mydir", filename: "file.py", full_path: "mydir/file.py"
   - "subdirectory and name it 'test'" → directory_to_create: "test"
   - "in the subdirectory with the name 'scripts'" → directory_to_create: "scripts"

   ⚠️ CRITICAL: If user specifies ANY directory or filename details, extract them EXACTLY as stated!

OUTPUT FORMAT (JSON only):
```json
{{
    "detected_technology": "web-frontend | python | node | auto",
    "complexity": "simple|medium|complex",
    "reasoning": "Brief explanation of why this complexity level",
    "estimated_files": 1,
    "can_be_single_script": true,
    "directory_to_create": "exact_directory_name or null if not specified",
    "filename": "exact_filename.ext",
    "main_filename": "directory_name/filename.ext or just filename.ext (the complete relative path)"
}}
```

PRINCIPLES:
- Be pragmatic - if it CAN be done in one file, it SHOULD be done in one file
- Don't over-engineer simple requests
- Extract file organization details EXACTLY as user specified (no interpretation!)
- Use user's EXACT names for directories and files"""

        response = self._call_llm(prompt)
        if not response:
            # Default to complex if assessment fails
            self.context.complexity = ProjectComplexity.COMPLEX.value
            print("\n⚠️ Could not assess complexity, defaulting to COMPLEX")
            return True

        # DEBUG: Log LLM response
        self.logger.info(f"COMPLEXITY_ASSESSMENT - LLM response (first 500 chars): {response[:500]}")

        data = self._extract_json(response)
        if data and "complexity" in data:
            # DEBUG: Log parsed data
            self.logger.info(f"COMPLEXITY_ASSESSMENT - Parsed JSON: {data}")
            complexity = data["complexity"].lower()
            if complexity in ["simple", "medium", "complex"]:
                self.context.complexity = complexity
                print(f"\n✅ Complexity assessed: {complexity.upper()}")
                print(f"   Reasoning: {data.get('reasoning', 'N/A')[:100]}")

                # Extract file organization details from LLM (NO regex parsing!)
                directory_to_create = data.get('directory_to_create')
                filename = data.get('filename')
                main_filename = data.get('main_filename')

                # Store directory for later use
                if directory_to_create and directory_to_create != 'null':
                    self._directory_to_create = directory_to_create
                    self.logger.info(f"COMPLEXITY_ASSESSMENT - LLM extracted directory: {directory_to_create}")
                else:
                    self._directory_to_create = None

                if complexity == "simple":
                    # Use LLM-provided filename (with full path if directory specified)
                    # LLM should return main_filename with proper path like "mydir/file.py"
                    detected_tech = data.get('detected_technology', 'auto')

                    # Fallback only if LLM didn't provide a filename
                    default_file = 'main.py'
                    if detected_tech == 'web-frontend':
                        default_file = 'index.html'
                    elif detected_tech == 'node':
                        default_file = 'index.js'

                    # Use main_filename (full path) if provided, otherwise use filename, otherwise default
                    final_filename = main_filename or filename or default_file
                    print(f"   → Will generate single script: {final_filename}")

                    # DEBUG: Log what we're storing
                    self.logger.info(f"COMPLEXITY_ASSESSMENT - LLM extracted filename: {filename}")
                    self.logger.info(f"COMPLEXITY_ASSESSMENT - LLM extracted main_filename: {main_filename}")
                    self.logger.info(f"COMPLEXITY_ASSESSMENT - Storing _simple_filename: {final_filename}")

                    # Store filename for simple generation
                    self._simple_filename = final_filename
                return True

        # Default to complex if parsing fails
        self.context.complexity = ProjectComplexity.COMPLEX.value
        print("\n⚠️ Could not parse complexity, defaulting to COMPLEX")
        return True

    def _phase_simple_generation(self) -> bool:
        """
        Phase 2 (SIMPLE path): Generate a single runnable script directly.

        This skips all architecture/design phases and creates one complete,
        immediately executable file.

        Returns:
            True if successful, False otherwise
        """
        self._print_phase(DevelopmentPhase.SIMPLE_GENERATION)

        filename = getattr(self, '_simple_filename', 'main.py')
        requirements_text = "\n".join(f"- {r}" for r in self.context.refined_requirements)

        # Detect language from filename
        if filename.endswith('.py'):
            language = 'python'
            run_instruction = f"python {filename}"
        elif filename.endswith('.js'):
            language = 'javascript'
            run_instruction = f"node {filename}"
        elif filename.endswith('.html') or filename.endswith('.htm'):
            language = 'html'
            run_instruction = f"open {filename} in browser (or: python -m http.server 8080)"
        elif filename.endswith('.css'):
            language = 'css'
            run_instruction = f"open associated HTML file in browser"
        else:
            # LLM classifies language - NO hardcoded keyword matching (CLAUDE.md compliance)
            language, run_instruction = self._llm_classify_language(
                self.context.original_request, filename
            )

        self._project_language = language

        # Build language-specific instructions
        if language == 'html':
            lang_specific = """
CRITICAL REQUIREMENTS FOR HTML/WEB:
1. The file must be a COMPLETE, self-contained HTML document
2. Include <!DOCTYPE html>, <html>, <head>, and <body> tags
3. For JavaScript: use <script type="module"> for ES6 imports
4. For external libraries (Three.js, etc.): use importmap for bare module specifiers:
   <script type="importmap">
   { "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js" } }
   </script>
5. Include all CSS in a <style> tag or inline
6. The page must work when opened directly in a browser or via local server
7. NO server-side code, NO backend dependencies, NO requirements.txt needed"""
        elif language == 'javascript':
            lang_specific = """
CRITICAL REQUIREMENTS FOR JAVASCRIPT:
1. The script must be COMPLETE - no placeholders, no TODOs
2. Include all necessary imports at the top (ES6 or CommonJS as appropriate)
3. The script must be IMMEDIATELY RUNNABLE with: node {filename}
4. Keep it SIMPLE - no over-engineering"""
        else:  # python
            lang_specific = """
CRITICAL REQUIREMENTS FOR PYTHON:
1. The script must be COMPLETE - no placeholders, no TODOs, no "implement this"
2. The script must be IMMEDIATELY RUNNABLE with: python {filename}
3. Include all necessary imports at the top
4. Include a main block: if __name__ == "__main__":
5. Keep it SIMPLE - no over-engineering, no unnecessary classes
6. For plots: use plt.show() to display, don't just save to file

SECURITY (if applicable):
- Use environment variables for any secrets/API keys (os.environ.get())
- Sanitize file paths and user inputs
- Use parameterized queries for databases"""

        # Add directory context if specified
        directory_context = ""
        if hasattr(self, '_directory_to_create') and self._directory_to_create:
            directory_context = f"""
NOTE: The file will be saved to: {filename}
Directory creation is handled automatically - focus on writing the file content."""

        prompt = f"""You are a senior developer writing a complete, runnable {language} file.

USER REQUEST:
{self.context.original_request}

REQUIREMENTS:
{requirements_text}
{directory_context}

TASK:
Write a COMPLETE, IMMEDIATELY USABLE {language} file that fulfills the request.
{lang_specific}

OUTPUT FORMAT:
Return ONLY the code in a code block:
```{language}
<!-- or # Your complete code here -->
```

Do NOT include explanations before or after the code block."""

        response = self._call_llm(prompt)  # Use config max_tokens
        if not response:
            print("\n❌ Failed to generate script")
            return False

        code_blocks = self._extract_code_blocks(response)
        if not code_blocks:
            print("\n❌ No code block found in response")
            return False

        _, code = code_blocks[0]

        # Validate basic structure based on language
        if language == 'python':
            if 'import' not in code and 'def ' not in code and 'print' not in code:
                print("\n⚠️ Generated code seems incomplete")
        elif language == 'html':
            if '<!DOCTYPE' not in code and '<html' not in code.lower():
                print("\n⚠️ Generated HTML seems incomplete (missing DOCTYPE or html tag)")
            if '<script' not in code.lower() and '<style' not in code.lower():
                print("\n⚠️ Generated HTML has no script or style tags")

        # Save the file
        file_path = self.project_dir / filename

        # NEW: Create parent directories if they don't exist
        if file_path.parent != self.project_dir:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"   ✅ Created directory: {file_path.parent.relative_to(self.project_dir)}")

        file_path.write_text(code)

        # Track in context
        self.context.generated_files[filename] = code
        self.context.file_specifications = [{"path": filename, "purpose": self.context.original_request}]

        print(f"\n✅ Generated: {filename} ({len(code)} chars)")
        print(f"   Full path: {file_path}")
        print(f"   Run with: cd {self.project_dir} && {run_instruction}")

        # Also generate requirements.txt if needed
        if language == 'python':
            imports = self._extract_imports(code)
            external_packages = self._filter_external_packages(imports)
            if external_packages:
                req_content = '\n'.join(external_packages)
                req_path = self.project_dir / 'requirements.txt'
                req_path.write_text(req_content)
                self.context.generated_files['requirements.txt'] = req_content
                print(f"   ✅ Generated: requirements.txt ({', '.join(external_packages)})")
                print(f"   Install deps: pip install -r requirements.txt")

        return True

    def _extract_imports(self, code: str) -> List[str]:
        """Extract import statements from Python code."""
        imports = []
        for line in code.split('\n'):
            line = line.strip()
            if line.startswith('import '):
                # import foo, bar
                parts = line[7:].split(',')
                for part in parts:
                    module = part.strip().split()[0].split('.')[0]
                    imports.append(module)
            elif line.startswith('from '):
                # from foo import bar
                match = line.split()[1].split('.')[0]
                imports.append(match)
        return list(set(imports))

    def _filter_external_packages(self, imports: List[str]) -> List[str]:
        """Filter imports to only external packages (not stdlib) using runtime detection.

        ARCHITECTURE: Uses DependencyResolver for LLM-driven package mapping.
        """
        try:
            if not imports:
                return []
                
            # Filter stdlib
            external_imports = self.dependency_resolver.filter_stdlib(set(imports))
            
            if not external_imports:
                return []
                
            # Resolve to pip names
            package_map = self.dependency_resolver.resolve_packages(list(external_imports))
            return list(set(package_map.values()))
        except Exception as e:
            self.logger.warning(f"Package mapping failed: {e}")
            return []

        # Fallback: return imports as-is (user may need to fix names manually)
        return list(set(external_imports))

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

⚠️ CRITICAL - USER'S REQUEST IS THE SOLE SOURCE OF TRUTH:
1. The USER'S ORIGINAL REQUEST determines the technology, language, and architecture
2. If the user says "webapp", "index.html", "HTML/JS" → create a pure web app (NO Python backend)
3. If the user says "Python script" → create Python files
4. If the user says "Node.js" → create JavaScript/TypeScript files
5. NEVER assume Python unless the user explicitly requests it
6. Read the user request CAREFULLY for technology hints: "webapp", "browser", "HTML", "JavaScript", etc.

LANGUAGE-SPECIFIC REQUIREMENTS:
- For Python: Include requirements.txt with ALL pip dependencies
- For JavaScript/Node: Include package.json with dependencies
- For pure web apps (HTML/CSS/JS): NO backend files, NO requirements.txt, NO package.json unless needed for build tools

OUTPUT FORMAT (JSON):
```json
{{
    "detected_technology": "web-frontend | python | node | java | etc.",
    "files": [
        {{
            "path": "relative/path/filename.ext",
            "purpose": "What this file does",
            "contents_outline": "Key functions/classes to implement",
            "dependencies": ["other files it imports"]
        }}
    ],
    "directory_structure": "Brief description of folder organization",
    "external_dependencies": ["list of external packages/libraries needed (if any)"]
}}
```

Be specific about what code goes where. Include all necessary files.
VERIFY your file structure matches what the USER REQUESTED, not a default assumption."""

        response = self._call_llm(prompt)
        if not response:
            return False

        data = self._extract_json(response)
        if data and "files" in data:
            self.context.file_specifications = data["files"]
            self.context.external_dependencies = data.get("external_dependencies", [])
            print(f"\n✅ Designed {len(self.context.file_specifications)} files:")
            if self.context.external_dependencies:
                print(f"   📦 External dependencies detected: {', '.join(self.context.external_dependencies)}")
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
            response = self._call_llm(prompt)  # Use config max_tokens
            if not response:
                self.logger.warning(f"INTERFACE_GENERATION: LLM call failed for {file_path}")
                print(f"   ⚠️ LLM call failed for {file_path}")
                continue

            code_blocks = self._extract_code_blocks(response)
            if code_blocks:
                _, code = code_blocks[0]

                # Extract symbols
                try:
                    interface = extractor.extract(code, file_path)
                    self.context.interfaces[file_path] = interface
                    self.logger.info(f"INTERFACE_GENERATION: Successfully extracted interface for {file_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to extract interface from {file_path}: {e}")
            else:
                self.logger.warning(f"INTERFACE_GENERATION: No code blocks found in LLM response for {file_path}")
                print(f"   ⚠️ No code blocks in response for {file_path}")

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
            # LLM classifies entry file - NO hardcoded keyword matching (CLAUDE.md compliance)
            entry_file = self._llm_classify_entry_file(self.context.original_request)
            self.logger.info(f"LLM determined entry file: {entry_file}")

            self.context.file_specifications = [{
                "path": entry_file,
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

SECURITY REQUIREMENTS (MANDATORY):
- NEVER hardcode passwords, API keys, or secrets - use environment variables
- NEVER use string concatenation for SQL queries - use parameterized queries
- ALWAYS sanitize user input before using in file paths, URLs, or commands
- ALWAYS use HTTPS for external API calls when possible
- NEVER use eval() or exec() with user-provided input
- For web apps: escape HTML output to prevent XSS

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
                response = self._call_llm(current_prompt)  # Use config max_tokens
                if not response:
                    self.logger.warning(f"CODING: LLM call failed for {file_path} (attempt {attempt + 1}/{max_retries})")
                    print(f"   ⚠️ LLM call failed (attempt {attempt + 1}/{max_retries})")
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
                        self.logger.warning(f"Failed to extract interface for {file_path}: {e}")

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

        # DIAGNOSTIC: Summary of code generation
        total_specs = len(self.context.file_specifications) if self.context.file_specifications else 0
        self.logger.info(f"CODING PHASE SUMMARY: Generated {files_generated}/{total_specs} files")
        print(f"\n📊 CODING: Generated {files_generated}/{total_specs} files")
        if files_generated == 0:
            self.logger.error("CODING PHASE FAILED: No files were generated!")
            print("   ❌ WARNING: No files were generated - check logs for LLM call failures")
        elif files_generated < total_specs:
            self.logger.warning(f"CODING: Only generated {files_generated} of {total_specs} files")
            print(f"   ⚠️ Some files failed to generate - check logs for details")

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

            # LAYER 4.7: Reconcile requirements.txt (v2.2)
            self._generate_or_reconcile_requirements()

        self.logger.info(f"PHASE COMPLETE: {DevelopmentPhase.CODING.name}")
        return True

    def _generate_or_reconcile_requirements(self) -> bool:
        """
        Scan all generated files for dependencies and generate/update the appropriate file.
        """
        print(f"\n📦 Reconciling dependencies...")

        try:
            # 1. Detect language and get content
            dep_info = self.dependency_resolver.generate_dependency_file_content(self.project_dir)
            if not dep_info:
                print("   ✅ No external dependencies detected")
                return True
                
            filename = dep_info["filename"]
            actual_content = dep_info["content"]
            lang = self.dependency_resolver.detect_language(self.project_dir)
            
            # 2. Add dependencies identified in design phase (re-resolved for PyPI/NPM names)
            design_raw_deps = self.context.external_dependencies
            design_deps = set()
            if design_raw_deps:
                resolved_design = self.dependency_resolver.resolve_packages(design_raw_deps, language=lang)
                design_deps = set(resolved_design.values())

            # 3. Combine them
            code_deps = set(actual_content.strip().split('\n')) if actual_content.strip() else set()
            combined_deps = design_deps.union(code_deps)
            combined_deps = {dep for dep in combined_deps if dep.strip()}

            if not combined_deps:
                return True

            # Final sorted list
            final_deps = sorted(list(combined_deps))
            final_content = "\n".join(final_deps) + "\n"

            # 4. Save to file
            target_path = self.project_dir / filename
            target_path.write_text(final_content)
            self.context.generated_files[filename] = final_content

            print(f"   ✅ Updated: {filename} with {len(final_deps)} packages")
            for dep in final_deps:
                print(f"      - {dep}")

            return True
        except Exception as e:
            self.logger.error(f"Dependency reconciliation failed: {e}")
            return False
            self.logger.error(f"Failed to reconcile requirements: {e}")
            return False

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
            self.logger.warning(f"No spec found for {file_path}, cannot repair")
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

            response = self._call_llm(prompt)  # Use config max_tokens
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
                self.logger.warning(f"Repair attempt {attempt + 1} failed validation: {validation.errors}")
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
                    self.logger.warning(f"Failed to update interface for {file_path}: {e}")

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

            response = self._call_llm(prompt)  # Use config max_tokens
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
            response = self._call_llm(prompt)  # Use config max_tokens
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

    async def _phase_testing(self) -> bool:
        """
        Phase 7: Generate and run tests with Docker sandbox execution.

        Includes DECIDE-ACT-VERIFY loop for test failures (max 3 retries).

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
        # ONLY validate files we generated (skip unrelated files in project dir)
        print("\n   🧪 Validating imports...")
        files_to_validate = list(self.context.generated_files.keys())
        exec_result = self.code_validator.validate_execution(files_to_validate=files_to_validate)

        if exec_result.success:
            print(f"   ✅ Import validation passed ({exec_result.sandbox_type})")
        else:
            print(f"   ❌ Import validation failed:")
            # Show parsed errors if available
            if exec_result.errors:
                for error in exec_result.errors[:3]:
                    error_msg = error.get('message', str(error))[:200]
                    print(f"      - {error_msg}")
                    # Determine severity: only 'error' if it's likely a local file issue
                    # If it's a missing third-party module (like 'gi'), downgrade to 'warning'
                    # so we don't loop forever in the limited sandbox environment
                    severity = "error"
                    missing_module = error.get('missing_module')
                    if missing_module:
                        # Check if it's one of our generated files
                        is_local = False
                        for gen_path in self.context.generated_files:
                            # Convert path to module name format
                            gen_module = gen_path.replace('/', '.').replace('.py', '')
                            if gen_module == missing_module or gen_module.endswith('.' + missing_module):
                                is_local = True
                                break
                        
                        if not is_local:
                            severity = "warning"
                            print(f"      ℹ️  Note: '{missing_module}' is an external dependency (not a local file)")

                    self.context.issues_found.append({
                        "file": "execution",
                        "severity": severity,
                        "description": error_msg,
                        "fix": "Fix import or dependency issue"
                    })
            # Also check stdout for FAIL messages (validation script prints there)
            if exec_result.stdout and 'FAIL:' in exec_result.stdout:
                for line in exec_result.stdout.split('\n'):
                    if 'FAIL:' in line:
                        error_msg = line.strip()[:200]
                        print(f"      - {error_msg}")
                        
                        severity = "error"
                        if "ModuleNotFoundError" in line or "No module named" in line:
                            # Try to extract module name
                            match = re.search(r"No module named '([^']+)'", line)
                            missing_module = match.group(1) if match else None
                            if missing_module:
                                is_local = False
                                for gen_path in self.context.generated_files:
                                    gen_module = gen_path.replace('/', '.').replace('.py', '')
                                    if gen_module == missing_module or gen_module.endswith('.' + missing_module):
                                        is_local = True
                                        break
                                if not is_local:
                                    severity = "warning"
                        
                        self.context.issues_found.append({
                            "file": "execution",
                            "severity": severity,
                            "description": error_msg,
                            "fix": "Fix import or dependency issue"
                        })
            # Show stderr if no other errors found
            elif exec_result.stderr and not exec_result.errors:
                print(f"      - {exec_result.stderr[:300]}")
                self.context.issues_found.append({
                    "file": "execution",
                    "severity": "error",
                    "description": exec_result.stderr[:200],
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
        # Don't truncate - LLM needs full context to analyze
        main_code = self.context.generated_files[main_file]
        file_path = str(self.project_dir / main_file)

        print(f"\n   Generating tests for: {main_file}...")

        # ARCHITECTURE: LLM-driven test generation - NO hardcoded scenarios
        # LLM analyzes code → determines what to test → generates tests
        prompt = f"""You are writing unit tests for the following code.

FILE: {main_file}
LOCATION: {file_path}

CODE TO TEST:
```python
{main_code}
```

STEP 1: ANALYZE THE CODE
Before writing any tests, analyze the code to understand:
1. What functions/classes/methods are defined? (list their exact names and signatures)
2. What do they DO? (return values vs print output vs side effects vs file operations)
3. How is the code USED? (imported as library, run as CLI tool, server, etc.)
4. What are the inputs and expected outputs?
5. What edge cases exist in the logic? (boundary conditions, special values, branches)
6. What error cases should be handled? (invalid inputs, exceptions)

STEP 2: GENERATE STANDALONE TESTS
Based on your analysis, write comprehensive tests that:

CRITICAL REQUIREMENTS:
- Call ONLY functions that actually exist in the code above (don't invent function names!)
- Match the actual signatures (if function takes 3 args, pass 3 args)
- Handle the code's actual behavior:
  * If it RETURNS values → test the return values
  * If it PRINTS output → capture stdout with io.StringIO and contextlib.redirect_stdout
  * If it uses sys.argv → manipulate sys.argv in test setup/teardown
  * If it reads files → create temporary test files
- Test the scenarios you identified in your analysis (normal cases, edge cases, errors)
- Use ONLY Python standard library (no pytest, no unittest, no external packages)

OUTPUT FORMAT (standalone Python script):
```python
#!/usr/bin/env python3
import sys
import os
# Add any other standard library imports needed based on your analysis

def test_scenario_1():
    # Based on your analysis of the code
    assert condition, "error message"

def test_scenario_2():
    # More tests based on your analysis
    pass

if __name__ == "__main__":
    tests = [test_scenario_1, test_scenario_2, ...]
    failures = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failures.append((test.__name__, str(e)))

    if failures:
        print(f"{{len(failures)}} test(s) failed:")
        for name, err in failures:
            print(f"FAIL: {{name}}: {{err}}")
        sys.exit(1)
    else:
        print(f"All {{len(tests)}} tests passed.")
```

Remember: Analyze the code FIRST, then write tests for what actually exists!
"""

        # Use config max_tokens (no hardcoded override)
        response = self._call_llm(prompt)
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

                # LAYER 7: Run tests in Docker sandbox with retry loop
                print(f"\n   🧪 Running tests in sandbox...")

                max_test_retries = 3
                test_iteration = 0
                test_success = False

                # Allow one extra test run after the last fix attempt
                while test_iteration <= max_test_retries and not test_success:
                    test_iteration += 1
                    # ONLY run the test file we just generated (not all test_*.py files!)
                    test_result = self.code_validator.run_tests(test_pattern=test_file)

                    if test_result.ran:
                        if test_result.passed:
                            for t in test_result.passed[:5]:
                                print(f"   ✅ PASSED: {t}")
                                self.context.tests_passed.append(t)

                        if test_result.failed:
                            for t in test_result.failed[:5]:
                                print(f"   ❌ FAILED: {t}")

                            # If tests failed and we have retries left, trigger investigation
                            if test_iteration <= max_test_retries:
                                print(f"\n   🔍 Investigating test failures (attempt {test_iteration}/{max_test_retries})...")

                                # DECIDE-ACT-VERIFY: Ask LLM to investigate and fix
                                fix_applied = await self._investigate_and_fix_test_failure(
                                    test_file=test_file,
                                    main_file=main_file,
                                    test_result=test_result
                                )

                                if fix_applied:
                                    print(f"   ✅ Fix applied, retrying tests...")
                                    continue  # Retry tests
                                else:
                                    print(f"   ⚠️ Could not determine fix, skipping retry")
                                    break
                            else:
                                # No more retries, record failures
                                for t in test_result.failed[:5]:
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

                            # If there are errors and we have retries left, trigger investigation
                            if test_iteration <= max_test_retries:
                                print(f"\n   🔍 Investigating test errors (attempt {test_iteration}/{max_test_retries})...")

                                # DECIDE-ACT-VERIFY: Ask LLM to investigate and fix
                                fix_applied = await self._investigate_and_fix_test_failure(
                                    test_file=test_file,
                                    main_file=main_file,
                                    test_result=test_result
                                )

                                if fix_applied:
                                    print(f"   ✅ Fix applied, retrying tests...")
                                    continue  # Retry tests
                                else:
                                    print(f"   ⚠️ Could not determine fix, skipping retry")
                                    break

                        # Check if tests passed
                        total = len(test_result.passed) + len(test_result.failed)
                        if total > 0:
                            if len(test_result.failed) == 0:
                                test_success = True
                                print(f"\n   📊 Test Results: {len(test_result.passed)}/{total} passed ✅")
                            else:
                                print(f"\n   📊 Test Results: {len(test_result.passed)}/{total} passed")
                        else:
                            # No tests ran (total = 0) - this is a problem if we've already handled errors above
                            # If we reach here, it means test_result.ran=True but no tests executed and no errors
                            # This shouldn't normally happen, but break the loop to avoid infinite retries
                            if test_iteration >= max_test_retries or not test_result.errors:
                                print(f"   ⚠️ No tests executed")
                                break
                    else:
                        # Tests didn't run at all
                        if test_result.error_message:
                            print(f"   ❌ ERROR: Test execution failed: {test_result.error_message}")
                        else:
                            print("   ❌ ERROR: Tests did not run")

                        # If tests didn't run and we have retries left, investigate
                        if test_iteration <= max_test_retries:
                            print(f"\n   🔍 Investigating test execution failure (attempt {test_iteration}/{max_test_retries})...")
                            fix_applied = await self._investigate_and_fix_test_failure(
                                test_file=test_file,
                                main_file=main_file,
                                test_result=test_result
                            )

                            if fix_applied:
                                print(f"   ✅ Fix applied, retrying tests...")
                                continue
                            else:
                                print(f"   ⚠️ Could not determine fix, skipping retry")
                                break
                        break

        # Report results
        total_passed = len(self.context.tests_passed)
        total_failed = len(self.context.tests_failed)

        if total_passed > 0 or total_failed > 0:
            print(f"\n✅ Testing phase complete")
        elif not test_success:
            print(f"\n⚠️ Testing phase complete with issues")
            print(f"   ℹ️ Tests could not be executed successfully after {max_test_retries} retry attempts")
        else:
            print(f"\n✅ Testing phase complete")

        print(f"   Tests generated: {len([f for f in self.context.generated_files if f.startswith('test_')])}")
        print(f"   Tests passed: {total_passed}")
        print(f"   Tests failed: {total_failed}")
        return True

    async def _investigate_and_fix_test_failure(
        self,
        test_file: str,
        main_file: str,
        test_result
    ) -> bool:
        """
        DECIDE-ACT-VERIFY loop for test failures.

        When tests fail, LLM investigates the failure and proposes a fix.

        Args:
            test_file: Path to test file
            main_file: Path to main file being tested
            test_result: TestResult object with failure details

        Returns:
            True if fix was applied, False otherwise
        """
        try:
            # Read current files
            test_path = self.project_dir / test_file
            main_path = self.project_dir / main_file

            test_code = test_path.read_text() if test_path.exists() else ""
            main_code = main_path.read_text() if main_path.exists() else ""

            # Build failure context
            failure_context = {
                "test_file": test_file,
                "main_file": main_file,
                "test_code": test_code,
                "main_code": main_code,
                "test_output": test_result.output if hasattr(test_result, 'output') else "",
                "test_stderr": test_result.stderr if hasattr(test_result, 'stderr') else "",
                "failed_tests": test_result.failed if hasattr(test_result, 'failed') else [],
                "error_message": test_result.error_message if hasattr(test_result, 'error_message') else ""
            }

            # DECIDE: Ask LLM to analyze failure and propose fix
            # ARCHITECTURE: LLM analyzes both files and determines root cause
            prompt = f"""You are debugging a test failure.

TEST FILE: {test_file}
```python
{test_code}
```

MAIN CODE BEING TESTED: {main_file}
```python
{main_code}
```

TEST EXECUTION FAILURE:
Output: {failure_context['test_output']}
Stderr: {failure_context['test_stderr']}
Failed tests: {failure_context['failed_tests']}
Error: {failure_context['error_message']}

CRITICAL CONTEXT:
- Main code was generated in CODE GENERATION phase (should be working)
- Test was generated in TEST GENERATION phase (might have wrong expectations)
- Tests run in minimal sandbox (Python standard library only, no pytest/unittest)

STEP 1: ANALYZE THE FAILURE
Determine the ROOT CAUSE:

1. API MISMATCH? (test calls functions that don't exist in main)
   - Error: "AttributeError: no attribute 'function_name'"
   - Cause: Test expects different API than main provides
   - Fix: TEST needs rewriting to call actual functions

2. WRONG EXPECTATIONS? (test has incorrect assertions)
   - Error: AssertionError with wrong expected values
   - Cause: Test expects different behavior than main implements
   - Fix: TEST needs updated assertions

3. MISSING DEPENDENCIES? (test imports external packages)
   - Error: "ModuleNotFoundError: No module named 'pytest'"
   - Cause: Test uses packages not available in sandbox
   - Fix: TEST needs rewriting without external packages

4. MAIN CODE BUG? (actual logic error in implementation)
   - Error: Correct API calls but wrong results
   - Cause: Bug in main code's logic
   - Fix: MAIN needs bug fix

STEP 2: DETERMINE FIX TARGET
Based on your analysis:
- If API mismatch (1) → fix_target: test
- If wrong expectations (2) → fix_target: test
- If missing dependencies (3) → fix_target: test
- If actual bug in main (4) → fix_target: main

DEFAULT: Assume test is wrong (it was just generated and might not match main's actual API)

STEP 3: PROVIDE FIX
Write your analysis, then provide the complete fixed code.

RESPONSE FORMAT:
Analysis: [Your analysis of what's wrong and why]

fix_target: test
(or "fix_target: main" if main code has actual bug)

```python
# Complete fixed code for the target file
```

If fixing test for API mismatch: Read the main code's actual functions and call those (don't invent functions)!
"""

            response = self.llm_client.generate(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Extract fix target from LLM response
            # ARCHITECTURE: DEFAULT to 'test' (safer - don't destroy working main code)
            # LLM must explicitly say "fix_target: main" to fix main code
            fix_target = 'test'  # SAFE DEFAULT
            if 'fix_target: main' in response_text.lower() or 'fix_target:main' in response_text.lower():
                fix_target = 'main'

            self.logger.debug(f"Investigation determined fix_target: {fix_target}")

            # Use established code extraction method (same as CODE_GENERATION)
            code_blocks = self._extract_code_blocks(response_text)
            if not code_blocks:
                self.logger.warning(f"No code blocks found in fix response ({len(response_text)} chars)")
                self.logger.debug(f"Response preview: {response_text[:500]}")
                return False

            # Get the LAST code block (LLM often includes error examples first, then the fix)
            # Also filter out blocks that look like error messages
            valid_blocks = []
            for lang, code in code_blocks:
                # Skip blocks that look like error messages
                if any(err in code for err in ['Error:', 'Traceback', 'ModuleNotFoundError', 'ImportError',
                                                'SyntaxError', '/usr/bin/python:', '/usr/local/bin/python:']):
                    self.logger.debug(f"Skipping error message block: {code[:100]}")
                    continue
                if len(code) > 50:  # Must be substantial
                    valid_blocks.append((lang, code))

            if not valid_blocks:
                self.logger.warning(f"No valid code blocks found (total blocks: {len(code_blocks)})")
                return False

            # Use the last valid block (most likely to be the actual fix)
            _, fixed_code = valid_blocks[-1]

            if not fixed_code or len(fixed_code) < 50:
                self.logger.warning(f"Extracted code is too short: {len(fixed_code)} chars")
                return False

            # Extract analysis from response (DON'T truncate - show full reasoning)
            analysis_match = response_text.split('```')[0].strip()
            # Show first 300 chars (or full if shorter)
            analysis_display = analysis_match if len(analysis_match) <= 300 else analysis_match[:300] + '...'

            # Validate fix before applying (prevent disasters like pytest stub overwriting solver code)
            if fix_target == 'main':
                # CRITICAL: Validate that fixed main code makes sense
                # Check for obvious red flags that indicate LLM returned wrong code
                if 'def ' not in fixed_code and 'class ' not in fixed_code:
                    self.logger.warning("Fixed main code has no functions/classes - rejecting!")
                    print(f"   ⚠️ Warning: Fixed code has no definitions - likely wrong, skipping fix")
                    return False

                # Log what we're about to do (for debugging disasters)
                self.logger.warning(f"About to OVERWRITE main file {main_file} - this is risky!")
                self.logger.debug(f"New code preview (first 300 chars):\n{fixed_code[:300]}")

            print(f"   📝 Analysis: {analysis_display}")
            print(f"   🔧 Fixing: {fix_target} file")

            # Debug logging
            self.logger.debug(f"Applying fix to {fix_target} file: {test_file if fix_target == 'test' else main_file}")
            self.logger.debug(f"Code length: {len(fixed_code)} chars")

            if fix_target == 'test':
                # Fix test file (safer - test was just generated, likely has wrong expectations)
                test_path.write_text(fixed_code)
                self.context.generated_files[test_file] = fixed_code
            else:
                # Fix main file (risky - main was already generated and supposedly works)
                main_path.write_text(fixed_code)
                self.context.generated_files[main_file] = fixed_code

            return True

        except Exception as e:
            self.logger.error(f"Error in test failure investigation: {e}")
            return False

    # =========================================================================
    # DOCUMENTATION GENERATION
    # =========================================================================

    def _generate_or_update_readme(self) -> bool:
        """
        Generate or update README.md for the project.

        - Creates README.md if it doesn't exist
        - Updates README.md if project files have changed

        Returns:
            True if successful, False otherwise
        """
        readme_path = self.project_dir / "README.md"
        existing_readme = ""

        # Check if README exists and read it
        if readme_path.exists():
            existing_readme = readme_path.read_text()
            # Check if update is needed by comparing file list
            existing_files = set()
            for line in existing_readme.split('\n'):
                if line.strip().startswith('- `') or line.strip().startswith('│'):
                    # Extract filename from markdown
                    import re
                    match = re.search(r'`([^`]+)`', line)
                    if match:
                        existing_files.add(match.group(1))

            current_files = set(self.context.generated_files.keys())
            if current_files and existing_files == current_files:
                print("   📄 README.md is up to date")
                return True

            print("   📝 Updating README.md (files changed)...")
        else:
            print("   📝 Generating README.md...")

        # Build file structure for prompt
        file_list = []
        for file_path in sorted(self.context.generated_files.keys()):
            full_path = self.project_dir / file_path
            size = full_path.stat().st_size if full_path.exists() else 0
            file_list.append(f"- {file_path} ({size} bytes)")

        # Detect project type and dependencies
        project_type = "Unknown"
        run_command = ""
        install_command = ""

        files = list(self.context.generated_files.keys())
        if any(f.endswith('.html') for f in files):
            project_type = "Web Application (HTML/CSS/JS)"
            run_command = "python -m http.server 8080\n# Then open http://localhost:8080"
        elif any(f.endswith('.py') for f in files):
            project_type = "Python Application"
            if any('flask' in self.context.original_request.lower() for _ in [1]):
                run_command = "python app.py"
            elif any('streamlit' in self.context.original_request.lower() for _ in [1]):
                run_command = "streamlit run main.py"
            else:
                main_file = next((f for f in files if 'main' in f.lower() and f.endswith('.py')), files[0] if files else 'main.py')
                run_command = f"python {main_file}"
            install_command = "pip install -r requirements.txt"

        prompt = f"""Generate a professional README.md for this project.

PROJECT DESCRIPTION:
{self.context.original_request}

REQUIREMENTS:
{chr(10).join(self.context.refined_requirements[:10])}

PROJECT TYPE: {project_type}

FILES GENERATED:
{chr(10).join(file_list)}

{"EXISTING README (update this):" + chr(10) + existing_readme[:1000] if existing_readme else ""}

Generate a complete README.md with these sections:
1. # Project Title (derived from description)
2. ## Description (2-3 sentences)
3. ## Features (bullet list)
4. ## Installation (if applicable)
5. ## Usage (how to run)
6. ## Project Structure (file tree)
7. ## Dependencies (if any)
8. ## License (MIT)

Use proper markdown formatting. Be concise but informative.
Return ONLY the README content, no code blocks."""

        response = self._call_llm(prompt)  # Use config max_tokens
        if not response:
            self.logger.warning("Failed to generate README.md")
            return False

        # Clean up response (remove code blocks if present)
        content = response.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:-1] if lines[-1].startswith('```') else lines[1:])

        # Strip LLM thinking tags (<thinking>, <details>, etc.)
        from .llm_client import strip_thinking_content
        content = strip_thinking_content(content)

        # Write README
        readme_path.write_text(content)
        self.context.generated_files["README.md"] = content
        print(f"   ✅ {'Updated' if existing_readme else 'Generated'}: README.md ({len(content)} bytes)")

        return True

    def _setup_python_environment(self) -> bool:
        """
        Setup Python virtual environment and install dependencies.

        MANDATORY for all Python projects:
        1. Create virtual environment (venv) if not exists
        2. Install dependencies from requirements.txt

        Returns:
            True if setup successful or not a Python project, False on error
        """
        # Check if this is a Python project
        files = list(self.context.generated_files.keys())
        is_python_project = any(f.endswith('.py') for f in files)

        if not is_python_project:
            return True  # Not a Python project, nothing to do

        # Check if requirements.txt exists
        requirements_path = self.project_dir / 'requirements.txt'
        if not requirements_path.exists():
            self.logger.info("No requirements.txt found, skipping venv setup")
            return True

        # Read requirements to check if there are any dependencies
        requirements_content = requirements_path.read_text().strip()
        if not requirements_content or all(line.strip().startswith('#') or not line.strip() for line in requirements_content.split('\n')):
            self.logger.info("requirements.txt is empty or contains only comments, skipping venv setup")
            return True

        print(f"\n   📦 Setting up Python environment...")

        # Create venv if it doesn't exist
        venv_path = self.project_dir / 'venv'
        if not venv_path.exists():
            print(f"   🔧 Creating virtual environment...")
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'venv', str(venv_path)],
                    capture_output=True,
                    text=True,
                    cwd=str(self.project_dir)
                )
                if result.returncode != 0:
                    self.logger.error(f"Failed to create venv: {result.stderr}")
                    print(f"   ❌ Failed to create venv: {result.stderr[:100]}")
                    return False
                print(f"   ✅ Created virtual environment: venv/")
            except Exception as e:
                self.logger.error(f"Exception creating venv: {e}")
                print(f"   ❌ Exception creating venv: {e}")
                return False
        else:
            print(f"   ℹ️  Virtual environment already exists: venv/")

        # Determine pip path based on OS
        if sys.platform == 'win32':
            pip_path = venv_path / 'Scripts' / 'pip'
        else:
            pip_path = venv_path / 'bin' / 'pip'

        # Install dependencies
        print(f"   📥 Installing dependencies from requirements.txt...")
        try:
            result = subprocess.run(
                [str(pip_path), 'install', '-r', 'requirements.txt'],
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=300  # 5 minute timeout for large installs
            )
            if result.returncode != 0:
                self.logger.error(f"pip install failed: {result.stderr}")
                print(f"   ❌ pip install failed:")
                # Show first few lines of error
                for line in result.stderr.split('\n')[:5]:
                    if line.strip():
                        print(f"      {line}")
                return False

            # Count installed packages
            installed_count = len([line for line in result.stdout.split('\n')
                                   if 'Successfully installed' in line or 'Requirement already satisfied' in line])
            print(f"   ✅ Dependencies installed successfully")

            # Show activation instructions
            if sys.platform == 'win32':
                activate_cmd = f"venv\\Scripts\\activate"
            else:
                activate_cmd = f"source venv/bin/activate"
            print(f"   💡 Activate environment: cd {self.project_dir.name} && {activate_cmd}")

        except subprocess.TimeoutExpired:
            self.logger.error("pip install timed out after 5 minutes")
            print(f"   ❌ pip install timed out (dependencies may be too large)")
            return False
        except Exception as e:
            self.logger.error(f"Exception during pip install: {e}")
            print(f"   ❌ Exception during pip install: {e}")
            return False

        return True

    async def _trigger_doc_hooks(self, phase: str) -> None:
        """
        Trigger documentation hooks after phase completion.

        Passes full phase context to the hooks for comprehensive documentation
        generation. This enables DocumentationGenerator to create structured
        docs in docs/PLANNING.md, docs/ARCHITECTURE.md, docs/DESIGN.md.

        Args:
            phase: Current phase name (PLANNING, ARCHITECTURE, DESIGN, CODING, COMPLETE)
        """
        if self.hook_manager is None:
            return

        # Build full phase context for documentation
        phase_context = {
            'original_request': self.context.original_request,
            'refined_requirements': self.context.refined_requirements,
            'implementation_plan': self.context.implementation_plan,
            'architecture_decisions': self.context.architecture_decisions,
            'components': self.context.components,
            'file_specifications': self.context.file_specifications,
            'generated_files': self.context.generated_files,
            'interfaces': self.context.interfaces,
            'issues_found': self.context.issues_found,
            'tests_passed': self.context.tests_passed,
            'tests_failed': self.context.tests_failed,
            'iteration': self.context.iteration,
        }

        # Build hook context
        hook_context = {
            'project_dir': str(self.project_dir),
            'generated_files': self.context.generated_files,
            'original_request': self.context.original_request,
            'phase': phase,
            'phase_context': phase_context,
            'language': self._project_language,
        }

        try:
            # Trigger PHASE_END hooks
            if HookTrigger is not None:
                await self.hook_manager.trigger(
                    HookTrigger.PHASE_END,
                    hook_context
                )
                self.logger.debug(f"Documentation hooks triggered for phase: {phase}")
        except Exception as e:
            self.logger.warning(f"Documentation hook failed: {e}")

    def _trigger_doc_hooks_sync(self, phase: str) -> None:
        """
        Synchronous wrapper for _trigger_doc_hooks.

        Used in the run() method which is synchronous.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in an event loop, create a task
                asyncio.create_task(self._trigger_doc_hooks(phase))
            else:
                # If no event loop, run directly
                loop.run_until_complete(self._trigger_doc_hooks(phase))
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self._trigger_doc_hooks(phase))

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
        # DEBUG: Log what we received from orchestrator
        self.logger.info(f"CLI_AGENT_RUN - Received user_request: {repr(user_request[:300])}")

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
            DevelopmentPhase.COMPLEXITY_ASSESSMENT: self._phase_complexity_assessment,
            DevelopmentPhase.SIMPLE_GENERATION: self._phase_simple_generation,
            DevelopmentPhase.PLANNING: self._phase_planning,
            DevelopmentPhase.ARCHITECTURE: self._phase_architecture,
            DevelopmentPhase.DESIGN: self._phase_design,
            DevelopmentPhase.INTERFACE_GENERATION: self._phase_interface_generation,
            DevelopmentPhase.CODING: self._phase_coding,
            DevelopmentPhase.DEBUGGING: self._phase_debugging,
            DevelopmentPhase.TESTING: self._phase_testing,
        }

        # Phases that trigger documentation generation
        doc_phases = {
            DevelopmentPhase.PLANNING,
            DevelopmentPhase.ARCHITECTURE,
            DevelopmentPhase.DESIGN,
        }

        # Phases to skip for SIMPLE complexity (after SIMPLE_GENERATION, jump to DEBUGGING)
        simple_skip_phases = {
            DevelopmentPhase.PLANNING,
            DevelopmentPhase.ARCHITECTURE,
            DevelopmentPhase.DESIGN,
            DevelopmentPhase.INTERFACE_GENERATION,
            DevelopmentPhase.CODING,
        }

        while self.current_phase != DevelopmentPhase.COMPLETE:
            # Skip SIMPLE_GENERATION if not SIMPLE complexity
            if self.current_phase == DevelopmentPhase.SIMPLE_GENERATION:
                if self.context.complexity != ProjectComplexity.SIMPLE.value:
                    self.logger.debug(f"Skipping SIMPLE_GENERATION (complexity={self.context.complexity})")
                    self._next_phase()
                    continue

            # Skip full project phases if SIMPLE complexity
            if self.current_phase in simple_skip_phases:
                if self.context.complexity == ProjectComplexity.SIMPLE.value:
                    self.logger.info(f"SKIP: {self.current_phase.name} (SIMPLE complexity)")
                    print(f"   ⏭️ Skipping {self.current_phase.name} (SIMPLE project)")
                    self._next_phase()
                    continue

            handler = phase_handlers.get(self.current_phase)
            current_phase_name = self.current_phase.name

            if handler:
                self.logger.info(f"EXECUTING PHASE: {current_phase_name}")
                # Check if handler is async and await it if needed
                import inspect
                import asyncio
                if inspect.iscoroutinefunction(handler):
                    success = asyncio.run(handler())
                else:
                    success = handler()
                if not success:
                    self.logger.error(f"PHASE FAILED: {current_phase_name} returned False")
                    print(f"   ❌ Phase {current_phase_name} failed - continuing to salvage")
                    # Continue anyway to see what we can salvage
                else:
                    self.logger.info(f"PHASE COMPLETE: {current_phase_name}")

            # Trigger documentation hooks for key phases
            if self.current_phase in doc_phases:
                self._trigger_doc_hooks_sync(current_phase_name)

            self._next_phase()

            # Check if we need to iterate
            if self.current_phase == DevelopmentPhase.COMPLETE:
                if self._should_iterate():
                    continue  # Loop back

        # Generate comprehensive documentation at completion
        if self.context.generated_files:
            self._print_header("📄 DOCUMENTATION", "-")
            # Trigger COMPLETE phase documentation (generates all docs)
            self._trigger_doc_hooks_sync('COMPLETE')
            # Also run the basic README update as fallback
            self._generate_or_update_readme()

        # Setup Python environment (venv + dependencies) - MANDATORY for Python projects
        if self.context.generated_files:
            self._print_header("🐍 PYTHON ENVIRONMENT SETUP", "-")
            env_success = self._setup_python_environment()
            if not env_success:
                self.logger.warning("Python environment setup had issues")

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
        default=2,
        help="Maximum development iterations (default: 2)"
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
