"""
Interactive Agent Runner
========================

Integrates the CLI Coding Agent with the TUI for a fully interactive experience.

Features:
- Scrolling output display showing agent progress
- Static prompt for user input
- Interactive clarification questions
- Approval prompts for major decisions
- Real-time phase and progress updates
- Session persistence and resume capability
"""

import asyncio
import logging
import signal
import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Install emergency exit handler BEFORE anything else
def _emergency_exit(signum, frame):
    """Emergency exit handler - always works even if app is frozen."""
    print("\n\n🚨 EMERGENCY EXIT (Ctrl+C pressed twice or SIGINT)\n", file=sys.__stderr__)
    try:
        # Attempt to save state if app instance exists
        if InteractiveAgentApp.instance:
            print("Saving state before emergency exit...", file=sys.__stderr__)
            InteractiveAgentApp.instance.save_state()
            
        # Attempt to run atexit handlers explicitly since os._exit won't
        import atexit
        atexit._run_exitfuncs()
    except:
        pass
    os._exit(1)

# Set up signal handler for hard kill
signal.signal(signal.SIGINT, _emergency_exit)
signal.signal(signal.SIGTERM, _emergency_exit)

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Static, Button, Input
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import on
from rich.text import Text
from rich.panel import Panel

from .widgets.output_panel import OutputPanel
from .widgets.prompt_panel import PromptPanel

# Import orchestrator for intelligent request routing
from ..orchestrator import (
    Orchestrator, RequestClassifier, RequestType,
    OrchestratorCallbacks, CommandRisk
)
from agents.common.state_manager import StateManager

logger = logging.getLogger(__name__)

# Set up file logging for the TUI agent
_log_file = Path(__file__).parent.parent.parent.parent / "tui_agent.log"
_file_handler = logging.FileHandler(_log_file)
_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
_file_handler.setLevel(logging.DEBUG)
logger.addHandler(_file_handler)
logger.setLevel(logging.DEBUG)

# Also add file handler to orchestrator and widgets
logging.getLogger("agents.coding_agent.orchestrator").addHandler(_file_handler)
logging.getLogger("agents.coding_agent.orchestrator").setLevel(logging.DEBUG)
logging.getLogger("agents.coding_agent.tui.widgets.prompt_panel").addHandler(_file_handler)
logging.getLogger("agents.coding_agent.tui.widgets.prompt_panel").setLevel(logging.DEBUG)







class InteractiveAgentApp(App):
    """
    Fully interactive TUI for the CLI Coding Agent.

    Provides:
    - Welcome screen with instructions
    - Prompt for coding request
    - Live output of agent phases
    - Interactive clarification dialogs
    - Approval prompts for decisions
    - Progress tracking
    - Session management
    """

    TITLE = "RAICA Coding Agent"
    SUB_TITLE = "Interactive Code Generation"

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: 1fr;
    }

    #output-container {
        height: 1fr;
        border: solid $primary;
    }

    #prompt-container {
        height: 12;  /* Fixed height for input area, allowing for multi-line */
        min-height: 5;
        border: solid $accent;
    }

    .welcome-panel {
        padding: 1 2;
        margin: 1;
        border: double $primary;
    }
    """

    BINDINGS = [
        # Ctrl+C should NOT quit - only /exit or clicking X does that
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("ctrl+p", "pause", "Pause"),
        Binding("ctrl+r", "resume", "Resume"),
        Binding("ctrl+s", "save", "Save State"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+o", "save_output", "Save Output"),
        Binding("ctrl+y", "copy_output", "Copy Output"),
        Binding("f1", "help", "Help"),
        Binding("escape", "interrupt", "Cancel"),
        Binding("ctrl+q", "force_quit", "Force Quit"),
        # Global scroll bindings for output panel
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_top", "Top", show=False),
        Binding("ctrl+end", "scroll_bottom", "Bottom", show=False),
    ]

    instance = None  # Class-level reference for signal handlers

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        InteractiveAgentApp.instance = self
        self._agent = None
        self._is_processing = False
        self._paused = False
        self._current_task = None
        self._pending_question: Optional[asyncio.Future] = None
        self._orchestrator: Optional[Orchestrator] = None
        self._llm_client = None  # Will be initialized when needed
        self._llm_client = None  # Will be initialized when needed
        self._output_history: List[str] = []  # Store output for copying/saving
        self._files_generated = 0  # detailed status tracking

        # Store configuration from CLI
        self._config = config or {}
        self._project_dir = Path(self._config.get('project_dir', '.')).resolve()
        self._resume = self._config.get('resume', False)
        self._hooks_enabled = self._config.get('hooks_enabled', True)
        self._knowledge_enabled = self._config.get('knowledge_enabled', True)
        self._verification_enabled = self._config.get('verification_enabled', True)
        self._model_override = self._config.get('model_override')
        self._raica_server_url = self._config.get('raica_server_url', 'http://localhost:5000')
        self._verbose = self._config.get('verbose', False)
        self._allow_sudo = self._config.get('allow_sudo', False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="main-container"):
            with Vertical():
                with Container(id="output-container"):
                    yield OutputPanel(id="output")
                with Container(id="prompt-container"):
                    yield PromptPanel(
                        default_prompt="Enter your coding request:",
                        placeholder="Describe what you want to build... (Shift+Enter for new line)",
                        id="prompt"
                    )

        yield Footer()

    @property
    def output(self) -> OutputPanel:
        return self.query_one("#output", OutputPanel)



    @property
    def prompt(self) -> PromptPanel:
        return self.query_one("#prompt", PromptPanel)

    def on_mount(self) -> None:
        """Show welcome message on startup."""
        self._show_welcome()
        self._load_prompt_history()  # Restore previous session's prompt history
        
        # Restore full application state if available
        self._load_state()
        
        self.prompt.input_widget.focus()

    def _load_state(self) -> None:
        """Load application state from persistence."""
        try:
            state = StateManager.load_state(self._project_dir)
            if not state:
                return
                
            # Restore logs
            if 'logs' in state:
                # We need to write logs back to output
                # Since RichLog doesn't have bulk set, we write lines
                self.output.add_info("Restoring previous session logs...")
                self.output.write("\n".join(state['logs']))
                self.output.add_success("Session restored")
                
            # Restore files generated count
            self._files_generated = state.get('files_generated', 0)
            
            # Restore orchestrator state if available
            if 'orchestrator' in state and state['orchestrator'].get('plan'):
                # Initialize orchestrator if needed (might not be if no request running yet)
                if not self._orchestrator:
                     # Lazy init usually happens on request, but we need it now to hold state
                     self._ensure_orchestrator()
                
                if self._orchestrator:
                    self._orchestrator.restore_state(state['orchestrator'])
                    self.output.add_info("Active plan restored")
                    
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            self.output.add_error(f"Failed to restore session: {e}")

    def _ensure_orchestrator(self) -> None:
        """Ensure orchestrator is initialized."""
        if not self._orchestrator:
            # We need LLM client for this
            if not self._llm_client:
                 from ..common.agent_utils import get_llm_client
                 self._llm_client = get_llm_client(self._model_override, self._verbose)
            
            self._orchestrator = Orchestrator(
                llm_client=self._llm_client, 
                project_dir=self._project_dir,
                allow_sudo=self._allow_sudo
            )

    @on(PromptPanel.PromptSubmitted)
    async def handle_input_submitted(self, event: PromptPanel.PromptSubmitted) -> None:
        """Handle PromptPanel.PromptSubmitted directly at App level."""
        # Debug: Log that we received the event
        # with open("/tmp/raica_debug.log", "a") as f:
        #     f.write(f"handle_input_submitted called with value: {event.value}\n")

        value = event.value.strip()
        logger.info(f"PromptSubmitted: {value[:50] if value else '(empty)'}...")

        # Save prompt history immediately so it's not lost on crash
        if value:
            self._save_prompt_history()

        if not value:
            self.notify("Empty input received", title="Debug")
            return

        # Handle /exit command
        if value.lower() in ['/exit', '/quit', 'exit', 'quit']:
            self.output.add_info("Exiting RAICA...")
            self.save_state()  # Save before exit
            self.exit()
            return

        # Handle /help command
        if value.lower() in ['/help', 'help']:
            await self.action_help()
            return

        # Handle /status command
        if value.lower() in ['/status', 'status']:
            self._show_status()
            return

        # Check if we're waiting for a question response
        if self._pending_question and not self._pending_question.done():
            self._pending_question.set_result(value)
            return

        # New coding request
        if not self._is_processing:
            # Log full prompt immediately (before any processing that could crash)
            logger.info(f"USER_PROMPT_RECEIVED: {value}")
            self.output.add_info(f"Processing: {value[:60]}...")
            # CRITICAL: Do NOT await here! Start as background task so event loop stays free
            # to process subsequent input events (for approval dialogs, questions, etc.)
            self._current_task = asyncio.create_task(self._run_agent_with_error_handling(value))
        else:
            self.output.add_warning("Agent is already running. Press Escape to interrupt.")

    def _show_status(self) -> None:
        """Show current agent status."""
        if self._agent:
            status_text = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                              AGENT STATUS                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Processing: {'Yes' if self._is_processing else 'No':<62} ║
║  Paused: {'Yes' if self._paused else 'No':<66} ║
║  Project: {self._agent.project_name:<64} ║
║  Phase: {self._agent.current_phase.name if hasattr(self._agent, 'current_phase') else 'N/A':<66} ║
║  Iteration: {self._agent.context.iteration if hasattr(self._agent, 'context') else 1:<63} ║
║  Files Generated: {self._files_generated:<56} ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
            self.output.write(Text(status_text, style="cyan"))
        else:
            self.output.add_info("No agent currently running. Enter a coding request to start.")

    async def _run_agent_with_error_handling(self, value: str) -> None:
        """Wrapper to run agent with proper error handling for background task."""
        try:
            await self._start_agent(value)
        except asyncio.CancelledError:
            self.output.add_warning("Agent task was cancelled")
        except Exception as e:
            self.output.add_error(f"Failed to start agent: {e}")
            import traceback
            logger.exception("Agent failed")
            # Log to output for visibility
            self.output.add_error(traceback.format_exc()[:500])
        finally:
            self._current_task = None

    def _show_welcome(self) -> None:
        """Display welcome message and instructions."""
        welcome = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    RAICA Interactive Agent v2.2                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  I handle CODING, SYSTEM QUERIES, and SYSTEM TASKS intelligently.             ║
║  I automatically detect your intent and route appropriately.                  ║
║                                                                               ║
║  CAPABILITIES:                                                                ║
║    CODE GEN    → "Create a Flask API with SQLite"                            ║
║    SYS QUERY   → "Is nginx installed?" / "Check Python version"              ║
║    SYS TASK    → "Install docker" / "Configure apache"                       ║
║    HYBRID      → "Install LAMP stack and create a PHP form"                  ║
║                                                                               ║
║  KEYBOARD SHORTCUTS:                                                          ║
║    Ctrl+C  - Interrupt     Ctrl+Q  - Force Quit     PageUp/Dn - Scroll       ║
║    Ctrl+S  - Save State    Ctrl+L  - Clear Output   F1        - Help         ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
        self.output.write(Text(welcome, style="cyan"))

        # Show project directory
        proj_dir = str(self._project_dir)
        if len(proj_dir) > 60:
            proj_dir = "..." + proj_dir[-57:]
        self.output.add_info(f"Project Directory: {proj_dir}")

        # Show configuration status
        features = []
        if self._hooks_enabled:
            features.append("Hooks")
        if self._knowledge_enabled:
            features.append("Knowledge")
        if self._verification_enabled:
            features.append("Verification")
        if features:
            self.output.add_info(f"Enabled Features: {', '.join(features)}")

        if self._model_override:
            self.output.add_info(f"Model Override: {self._model_override}")

        self.output.add_separator()
        self.output.add_separator()


    async def _start_agent(self, request: str) -> None:
        """Start the agent with intelligent request routing."""
        self._is_processing = True
        self.notify("Starting agent...", title="Status")
        self.prompt.set_waiting("Analyzing request...")

        self.output.add_info(f"Request: {request[:80]}...")
        self.output.add_separator()

        # Log full request for auditing/debugging
        logger.info(f"FULL_USER_REQUEST: {request}")

        try:
            # Step 1: Initialize LLM client if needed
            if not self._llm_client:
                await self._init_llm_client()

            # Step 2: Classify the request using the orchestrator
            self.output.add_info("Classifying request type...")
            classifier = RequestClassifier(self._llm_client)
            # Run classification in thread to avoid blocking (LLM call)
            classification = await asyncio.to_thread(classifier.classify, request)

            self.output.add_info(
                f"Request type: {classification.primary_type.name} "
                f"(confidence: {classification.confidence:.0%})"
            )

            if classification.requires_sudo:
                self.output.add_warning("This request may require sudo privileges")

            # Step 3: ALL requests go through intelligent orchestration first
            # The orchestrator will use LLM to create an appropriate plan
            self.output.add_info("Creating intelligent execution plan...")
            logger.info(f"[PATH] Starting intelligent request handling for: {request[:50]}...")

            result = await self._handle_intelligent_request(request, classification)

            # Log what we got back
            logger.info(f"[PATH] Intelligent request result: success={result.success if result else 'None'}, "
                       f"generated_files={result.generated_files if result else 'None'}")

            # Check if orchestrator determined code generation is needed
            if result and result.generated_files and any(f.startswith("__CODE_GEN__") or f == "__USE_CODE_GEN_PIPELINE__" for f in result.generated_files):
                self.output.add_info("Plan requires code generation pipeline...")
                logger.info("[PATH] Proceeding to CODE GENERATION PIPELINE (orchestrator indicated code gen needed)")
            else:
                # Orchestrator handled the request completely
                logger.info("[PATH] Request completed by orchestrator - NOT using code gen pipeline")
                self.output.add_info("Request handled by intelligent orchestrator")
                return

            # Fall through to code generation only if orchestrator says it's needed
            self.output.add_info("Proceeding with code generation pipeline...")
            logger.info("[PATH] === ENTERING OLD CODE GENERATION PIPELINE ===")
            self.output.add_separator()

            # Import and initialize the agent
            self.output.add_info("Importing CLICodingAgent...")
            
            # Monkeypatch setup_agent_logging BEFORE importing/using CLICodingAgent
            # This is critical to prevent the console handler from being attached during init
            # which causes a deadlock with the TUI capturing stdout
            import logging
            import agents.common.agent_utils as agent_utils
            original_setup_logging = agent_utils.setup_agent_logging

            # Use shared utility for patching logger
            from agents.common.agent_utils import get_patched_logger

            def patched_setup_logging(*args, **kwargs):
                # Call original to get the logger
                logger = original_setup_logging(*args, **kwargs)
                return get_patched_logger(logger)

            # Apply patch to the common module
            agent_utils.setup_agent_logging = patched_setup_logging

            # Import the agent module
            from .. import cli_coding_agent as cli_agent_module
            from ..cli_coding_agent import CLICodingAgent, DevelopmentPhase

            # Also patch it in the agent module in case it was imported using 'from ... import ...'
            cli_agent_module.setup_agent_logging = patched_setup_logging

            # Create agent with TUI integration
            
            # Determine project setup based on classification
            use_existing_project = False
            project_name = None

            if classification.primary_type == RequestType.CODE_DEBUG:
                # Check if current directory has content
                has_content = any(self._project_dir.iterdir()) if self._project_dir.exists() else False
                
                if has_content:
                    use_existing_project = True
                    self.output.add_info("Mode: In-Place Debugging (using current directory)")
                else:
                    # Empty dir but DEBUG requested - ask user
                    use_new = await self._ask_approval(
                        "No Project Found",
                        "Debug requested but current directory is empty. Create a new project instead?",
                        ["Yes, Create New", "No, Abort"]
                    )
                    if use_new != "Yes, Create New":
                        self.output.add_warning("Operation aborted by user")
                        return

            if not use_existing_project:
                # Use shared utility for semantic naming
                from agents.common.agent_utils import generate_semantic_name
                project_name = generate_semantic_name(request)
                self.output.add_info(f"Creating project: {project_name}")

            # Run initialization in a separate thread to avoid blocking the TUI loop
            # This ensures that even if there is some IO, it doesn't freeze the interface
            self._agent = await asyncio.to_thread(
                CLICodingAgent,
                project_name=project_name,
                output_dir=str(self._project_dir),
                verbose=True,
                use_existing_project=use_existing_project
            )
            
            self.output.add_success("Agent initialized")

            # Restore output patch (legacy, but good to keep)
            self._patch_agent_output()

            # Run the agent
            self.output.add_info("Starting development phases...")
            
            await self._run_agent_phases(request)

        except Exception as e:
            self.output.add_error(f"Agent error: {e}")
            import traceback
            self.output.add_error(traceback.format_exc())
            logger.exception("Agent failed")
        finally:
            self._is_processing = False
            self.prompt.clear_waiting()
            self.prompt.set_prompt("Enter another request or Ctrl+C to quit:")

    async def _init_llm_client(self) -> None:
        """Initialize the LLM client for orchestrator use."""
        try:
            from ..llm_client import CodeGenLLMClient
            # Run constructor in thread to avoid blocking event loop
            self._llm_client = await asyncio.to_thread(CodeGenLLMClient)
            self.output.add_success("LLM client initialized")
        except Exception as e:
            self.output.add_warning(f"LLM client init failed: {e}")
            self._llm_client = None

    async def _handle_intelligent_request(self, request: str, classification):
        """
        Handle ANY request through intelligent LLM-based planning.

        This is the unified entry point for all requests. The orchestrator will:
        1. Use LLM to understand what the user actually wants
        2. Create a step-by-step plan (investigate, check capabilities, execute, verify)
        3. Execute each step, adapting based on results
        4. Only invoke code generation if the plan determines it's needed

        Returns:
            OrchestratorResult with execution details
        """
        self.output.add_phase_header("INTELLIGENT PLANNING", 1)

        # Create orchestrator with callbacks
        callbacks = OrchestratorCallbacks(
            on_output=self._orchestrator_output,
            on_approval_needed=self._orchestrator_approval,
            on_user_input=self._orchestrator_input,
            on_plan_ready=self._orchestrator_plan_approval,
            on_step_start=self._orchestrator_step_start,
            on_step_complete=self._orchestrator_step_complete,
        )

        orchestrator = Orchestrator(
            llm_client=self._llm_client,
            project_dir=self._project_dir,
            callbacks=callbacks,
            allow_sudo=self._allow_sudo
        )

        # Execute with intelligent planning
        result = await orchestrator.handle_request_intelligently(request, classification)

        # Show results
        self.output.add_separator()
        if result.success:
            self.output.add_success(f"Request completed successfully")
            if result.steps_completed > 0:
                self.output.add_info(f"Steps completed: {result.steps_completed}")
        else:
            if result.error:
                self.output.add_error(f"Request issue: {result.error}")
            if result.steps_failed > 0:
                self.output.add_info(f"Steps completed: {result.steps_completed}, failed: {result.steps_failed}")

        self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")

        return result

    async def _handle_system_request(self, request: str, classification) -> None:
        """Handle system query or system task requests using the orchestrator."""
        self.output.add_phase_header("SYSTEM OPERATION", 1)

        # Create orchestrator with callbacks
        callbacks = OrchestratorCallbacks(
            on_output=self._orchestrator_output,
            on_approval_needed=self._orchestrator_approval,
            on_user_input=self._orchestrator_input,
            on_plan_ready=self._orchestrator_plan_approval,
            on_step_start=self._orchestrator_step_start,
            on_step_complete=self._orchestrator_step_complete,
        )

        orchestrator = Orchestrator(
            llm_client=self._llm_client,
            project_dir=self._project_dir,
            callbacks=callbacks,
            allow_sudo=self._allow_sudo
        )

        # Execute the request
        result = await orchestrator.handle_request(request)

        # Show results
        self.output.add_separator()
        if result.success:
            self.output.add_success(f"Request completed successfully")
            self.output.add_info(f"Steps completed: {result.steps_completed}")
        else:
            self.output.add_error(f"Request failed: {result.error or 'Unknown error'}")
            self.output.add_info(f"Steps completed: {result.steps_completed}, failed: {result.steps_failed}")

        self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")

    async def _handle_hybrid_request(self, request: str, classification) -> None:
        """Handle hybrid requests that need both system ops and code generation."""
        self.output.add_phase_header("HYBRID REQUEST", 1)
        self.output.add_info("This request requires both system operations and code generation.")

        # First, handle system operations with orchestrator
        callbacks = OrchestratorCallbacks(
            on_output=self._orchestrator_output,
            on_approval_needed=self._orchestrator_approval,
            on_user_input=self._orchestrator_input,
            on_plan_ready=self._orchestrator_plan_approval,
            on_step_start=self._orchestrator_step_start,
            on_step_complete=self._orchestrator_step_complete,
        )

        orchestrator = Orchestrator(
            llm_client=self._llm_client,
            project_dir=self._project_dir,
            callbacks=callbacks,
            allow_sudo=self._allow_sudo
        )

        # Execute system steps first
        result = await orchestrator.handle_request(request)

        if not result.success:
            self.output.add_error(f"System operations failed: {result.error}")
            # Ask if user wants to continue with code generation anyway
            continue_anyway = await self._ask_approval(
                "Continue?",
                "System operations failed. Continue with code generation anyway?",
                ["Yes, continue", "No, abort"]
            )
            if continue_anyway != "Yes, continue":
                return

        # Check if code generation is needed
        if result.generated_files and "__CODE_GEN__" in str(result.generated_files):
            self.output.add_separator()
            self.output.add_info("Now proceeding with code generation...")

            # Continue with code generation pipeline
            # Re-call the code gen part of _start_agent
            await self._run_code_generation(request, classification)

    async def _run_code_generation(self, request: str, classification) -> None:
        """Run the code generation pipeline (extracted from _start_agent)."""
        import logging
        import agents.common.agent_utils as agent_utils

        original_setup_logging = agent_utils.setup_agent_logging

        from agents.common.agent_utils import get_patched_logger

        def patched_setup_logging(*args, **kwargs):
            logger = original_setup_logging(*args, **kwargs)
            return get_patched_logger(logger)

        agent_utils.setup_agent_logging = patched_setup_logging

        from .. import cli_coding_agent as cli_agent_module
        from ..cli_coding_agent import CLICodingAgent

        cli_agent_module.setup_agent_logging = patched_setup_logging

        # Determine project setup based on classification
        use_existing_project = False
        project_name = None

        if classification.primary_type == RequestType.CODE_DEBUG:
            # Check if current directory has content
            has_content = any(self._project_dir.iterdir()) if self._project_dir.exists() else False
            
            if has_content:
                use_existing_project = True
                self.output.add_info("Mode: In-Place Debugging (using current directory)")
            else:
                # Empty dir but DEBUG requested - ask user
                use_new = await self._ask_approval(
                    "No Project Found",
                    "Debug requested but current directory is empty. Create a new project instead?",
                    ["Yes, Create New", "No, Abort"]
                )
                if use_new != "Yes, Create New":
                    self.output.add_warning("Operation aborted by user")
                    return

        if not use_existing_project:
            from agents.common.agent_utils import generate_semantic_name
            project_name = generate_semantic_name(request)
            self.output.add_info(f"Creating project: {project_name}")

        self._agent = await asyncio.to_thread(
            CLICodingAgent,
            project_name=project_name,
            output_dir=str(self._project_dir),
            verbose=True,
            use_existing_project=use_existing_project
        )

        self.output.add_success("Agent initialized")
        self._patch_agent_output()

        await self._run_agent_phases(request)

    # === Orchestrator Callbacks ===

    async def _orchestrator_output(self, message: str, msg_type: str) -> None:
        """Handle orchestrator output messages."""
        # Store in history for copy/save
        self._output_history.append(f"[{msg_type.upper()}] {message}")

        if msg_type == "error":
            self.output.add_error(message)
        elif msg_type == "warning":
            self.output.add_warning(message)
        elif msg_type == "success":
            self.output.add_success(message)
        elif msg_type == "phase":
            self.output.add_phase_header(message, 1)
        elif msg_type == "command":
            self.output.add_info(f"$ {message}")
        elif msg_type == "output":
            # Command output - show in a code block style
            self.output.add_code(message, language="text")
        elif msg_type == "llm_response":
            self.output.add_llm_response(message, "LLM")
        else:
            self.output.add_info(message)

    async def _orchestrator_approval(self, command: str, description: str, risk: CommandRisk) -> bool:
        """Handle orchestrator approval requests."""
        risk_indicator = "⚠️ HIGH RISK" if risk in [CommandRisk.HIGH, CommandRisk.CRITICAL] else ""

        response = await self._ask_approval(
            f"Approve Command? {risk_indicator}",
            f"Command: {command}\n\nDescription: {description}",
            ["Approve", "Deny"]
        )
        return response == "Approve"

    async def _orchestrator_input(self, prompt: str) -> str:
        """Handle orchestrator input requests."""
        return await self._ask_question(prompt)

    async def _orchestrator_plan_approval(self, plan) -> bool:
        """Handle orchestrator plan approval."""
        # Show plan summary
        summary_lines = [f"Execution Plan: {len(plan.steps)} steps"]
        for i, step in enumerate(plan.steps[:5], 1):
            sudo = "[SUDO]" if step.requires_sudo else ""
            summary_lines.append(f"  {i}. {step.title} {sudo}")
        if len(plan.steps) > 5:
            summary_lines.append(f"  ... and {len(plan.steps) - 5} more steps")

        response = await self._ask_approval(
            "Approve Execution Plan?",
            "\n".join(summary_lines),
            ["Approve", "Deny"]
        )
        return response == "Approve"

    async def _orchestrator_step_start(self, step) -> None:
        """Handle orchestrator step start notification."""
        # self.status.set_status(f"Step: {step.title}") # Removed during TUI simplification
        pass

    async def _orchestrator_step_complete(self, step, success: bool) -> None:
        """Handle orchestrator step complete notification."""
        if success:
            self.output.add_success(f"✓ {step.title}")
        else:
            self.output.add_error(f"✗ {step.title}")

    def _patch_agent_output(self) -> None:
        """Patch agent to use TUI output instead of print."""
        if not self._agent:
            return

        # Store reference to TUI
        agent = self._agent
        output = self.output
        # Store reference to TUI
        agent = self._agent
        output = self.output

        # Patch the print header method
        original_print_header = agent._print_header

        def tui_print_header(text: str, char: str = "="):
            output.add_phase_header(text.strip(), 1)

        agent._print_header = tui_print_header

        # Patch builtins.print to prevent stdout deadlocks and capture output
        import builtins
        original_print = builtins.print

        def tui_print(*args, **kwargs):
            # Format arguments like print does
            text = " ".join(str(arg) for arg in args)
            
            # Filter out some noise if needed, or just log everything to info
            # We don't want to double-log things that go through the agent's logger (which writes to file)
            # But the agent uses print() for user-facing output in CLI mode
            
            if text.strip():
                # Avoid capturing TUI's own logs/prints if any exist
                output.add_info(text)
                
        # Only patch if not already patched (to avoid recursion if re-initialized)
        if builtins.print != tui_print:
            builtins.print = tui_print
            
            # Store original so we can restore on exit if needed
            self._original_print = original_print

    async def _llm_call(self, prompt: str, task_name: str = "LLM Call") -> str:
        """
        Make an LLM call with task tracking.

        Args:
            prompt: The prompt to send to the LLM
            task_name: Description for the task tracker

        Returns:
            The LLM response content
        """
        agent = self._agent

        # Register task
        # task_id = self.status.register_task(task_name, f"Calling {agent._provider} LLM")

        try:
            response = await asyncio.to_thread(
                agent.llm_client.generate, prompt
            )

            # Complete task
            # self.status.complete_task(task_id)

            content = response.content if hasattr(response, 'content') else str(response)
            return content

        except Exception as e:
            # self.status.complete_task(task_id, success=False)
            raise
        finally:
            # self.status.remove_task(task_id)
            pass

    async def _run_agent_phases(self, request: str) -> None:
        """Run through agent phases with TUI integration."""
        from ..cli_coding_agent import DevelopmentPhase

        agent = self._agent
        phases = [
            (DevelopmentPhase.REQUIREMENTS, "Analyzing Requirements"),
            (DevelopmentPhase.PLANNING, "Creating Plan"),
            (DevelopmentPhase.ARCHITECTURE, "Designing Architecture"),
            (DevelopmentPhase.DESIGN, "Specifying Design"),
            (DevelopmentPhase.INTERFACE_GENERATION, "Generating Interfaces"),
            (DevelopmentPhase.CODING, "Writing Code"),
            (DevelopmentPhase.DEBUGGING, "Debugging"),
            (DevelopmentPhase.TESTING, "Testing"),
        ]

        total_phases = len(phases)
        agent.context.original_request = request

        for idx, (phase, phase_name) in enumerate(phases):
            if self._paused:
                self.output.add_warning("Agent paused. Press Ctrl+R to resume.")
                while self._paused:
                    await asyncio.sleep(0.5)

            # Update status
            progress = (idx / total_phases) * 100
            # Update status
            progress = (idx / total_phases) * 100
            # self.status.set_phase(phase.name, agent.context.iteration)
            # self.status.set_progress(progress, f"Phase: {phase_name}")

            # Show phase header
            self.output.add_phase_header(phase.name, agent.context.iteration)

            # Register task for this phase
            # task_id = self.status.register_task(phase_name, f"Executing {phase.name} phase")

            try:
                # Execute phase
                agent.current_phase = phase
                success = await self._execute_phase(phase, phase_name)

                # Complete task
                # Complete task
                # self.status.complete_task(task_id, success)
                # self.status.remove_task(task_id)

                if success:
                    self.output.add_success(f"{phase_name} complete")
                else:
                    self.output.add_warning(f"{phase_name} completed with issues")

                # Trigger hooks if available
                if agent.hook_manager and hasattr(agent, 'hook_manager'):
                    try:
                        from ..hooks.hook_manager import HookTrigger
                        await agent.hook_manager.trigger(
                            HookTrigger.PHASE_END,
                            {
                                'phase': phase.name,
                                'project_dir': agent.project_dir,
                                'context': agent.context
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Hook trigger failed: {e}")

                # Save state if available
                if agent.state_persistence:
                    agent.state_persistence.save_state(
                        phase=phase.name,
                        iteration=agent.context.iteration,
                        original_request=request,
                        refined_requirements=agent.context.refined_requirements,
                        generated_files={
                            str(f.path): f.content
                            for f in agent.context.generated_files
                        } if agent.context.generated_files else {}
                    )

            except Exception as e:
                # Mark task as failed
                # self.status.complete_task(task_id, success=False)
                # self.status.remove_task(task_id)

                self.output.add_error(f"Phase {phase_name} failed: {e}")
                logger.exception(f"Phase {phase.name} failed")

                # Ask if user wants to continue
                should_continue = await self._ask_approval(
                    "Phase Failed",
                    f"The {phase_name} phase encountered an error:\n{str(e)[:200]}",
                    ["Continue", "Retry", "Abort"]
                )

                if should_continue == "Abort":
                    break
                elif should_continue == "Retry":
                    idx -= 1  # Will retry this phase
                    continue

        # Check if user wants to launch/run the project
        if self._should_launch_project(request):
            self.output.add_phase_header("LAUNCH", agent.context.iteration)
            await self._launch_project()

        # Complete
        # Complete
        # self.status.set_phase("COMPLETE", agent.context.iteration)
        # self.status.set_progress(100, "Project complete!")
        self._show_completion_summary()

    async def _execute_phase(self, phase, phase_name: str) -> bool:
        """Execute a single phase with progress updates."""
        from ..cli_coding_agent import DevelopmentPhase

        agent = self._agent

        try:
            if phase == DevelopmentPhase.REQUIREMENTS:
                return await self._phase_requirements()
            elif phase == DevelopmentPhase.PLANNING:
                return await self._phase_planning()
            elif phase == DevelopmentPhase.ARCHITECTURE:
                return await self._phase_architecture()
            elif phase == DevelopmentPhase.DESIGN:
                return await self._phase_design()
            elif phase == DevelopmentPhase.INTERFACE_GENERATION:
                return await self._phase_interfaces()
            elif phase == DevelopmentPhase.CODING:
                return await self._phase_coding()
            elif phase == DevelopmentPhase.DEBUGGING:
                return await self._phase_debugging()
            elif phase == DevelopmentPhase.TESTING:
                return await self._phase_testing()
            else:
                return True

        except Exception as e:
            self.output.add_error(f"Phase execution error: {e}")
            return False

    async def _phase_requirements(self) -> bool:
        """Execute requirements phase."""
        agent = self._agent
        request = agent.context.original_request

        self.output.add_info("Analyzing your request...")

        # Call LLM to extract requirements
        prompt = f"""Analyze this coding request and extract clear requirements.

REQUEST: {request}

Extract:
1. Core functional requirements (what it must do)
2. Technical requirements (language, frameworks)
3. Any implicit requirements
4. Constraints or limitations

Format each requirement as a clear, actionable item."""

        try:
            # Call LLM with tracking
            content = await self._llm_call(prompt, "Analyzing Requirements")
            self.output.add_llm_response(content[:1500], agent._provider)

            # Parse requirements (simplified)
            requirements = [
                line.strip().lstrip('0123456789.-) ')
                for line in content.split('\n')
                if line.strip() and len(line.strip()) > 10
            ][:10]

            agent.context.refined_requirements = requirements

            self.output.add_success(f"Extracted {len(requirements)} requirements")

            # Ask for confirmation
            approval = await self._ask_approval(
                "Requirements Review",
                f"I found {len(requirements)} requirements:\n" +
                "\n".join(f"• {r[:60]}..." if len(r) > 60 else f"• {r}" for r in requirements[:5]) +
                ("\n..." if len(requirements) > 5 else ""),
                ["Approve", "Modify", "Add More"]
            )

            if approval == "Modify":
                new_reqs = await self._ask_question(
                    "Enter modified requirements (one per line, or 'done' to finish):"
                )
                if new_reqs and new_reqs.lower() != 'done':
                    agent.context.refined_requirements = [
                        r.strip() for r in new_reqs.split('\n') if r.strip()
                    ]

            return True

        except Exception as e:
            self.output.add_error(f"Requirements analysis failed: {e}")
            return False

    async def _phase_planning(self) -> bool:
        """Execute planning phase."""
        agent = self._agent

        self.output.add_info("Creating implementation plan...")

        # Use iterative planner if available
        if agent.iterative_planner:
            try:
                plan = await agent.iterative_planner.create_plan(
                    agent.context.refined_requirements,
                    project_type='python'
                )

                self.output.add_success(f"Created plan with {len(plan.steps)} steps")

                for step in plan.steps[:5]:
                    self.output.add_info(f"  • {step.action}")

                if plan.warnings:
                    for warning in plan.warnings:
                        self.output.add_warning(f"  ⚠ {warning}")

                agent.context.plan_steps = [s.action for s in plan.steps]
                return True

            except Exception as e:
                self.output.add_warning(f"Iterative planner failed, using fallback: {e}")

        # Fallback to LLM-based planning
        prompt = f"""Create an implementation plan for these requirements:

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements)}

Create a step-by-step implementation plan with:
1. Ordered steps
2. Files to create
3. Key functions/classes"""

        try:
            response = await asyncio.to_thread(
                agent.llm_client.generate, prompt
            )

            content = response.content if hasattr(response, 'content') else str(response)
            self.output.add_llm_response(content[:1000], agent._provider)

            # Simple plan parsing
            steps = [
                line.strip().lstrip('0123456789.-) ')
                for line in content.split('\n')
                if line.strip() and len(line.strip()) > 5
            ][:15]

            agent.context.plan_steps = steps
            self.output.add_success(f"Created plan with {len(steps)} steps")
            return True

        except Exception as e:
            self.output.add_error(f"Planning failed: {e}")
            return False

    async def _phase_architecture(self) -> bool:
        """Execute architecture phase."""
        agent = self._agent

        self.output.add_info("Designing system architecture...")

        prompt = f"""Design the architecture for this project:

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements[:5])}

PLAN:
{chr(10).join(f'- {s}' for s in agent.context.plan_steps[:5])}

Define:
1. Architecture pattern (modular, layered, etc.)
2. Main components/modules
3. Key interactions
4. File structure"""

        try:
            response = await asyncio.to_thread(
                agent.llm_client.generate, prompt
            )

            content = response.content if hasattr(response, 'content') else str(response)
            self.output.add_llm_response(content[:1000], agent._provider)

            agent.context.architecture = content
            self.output.add_success("Architecture designed")
            return True

        except Exception as e:
            self.output.add_error(f"Architecture design failed: {e}")
            return False

    async def _phase_design(self) -> bool:
        """Execute design phase."""
        agent = self._agent

        self.output.add_info("Creating detailed design...")

        prompt = f"""Create detailed file specifications:

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements[:5])}

ARCHITECTURE:
{agent.context.architecture[:500] if hasattr(agent.context, 'architecture') else 'Standard modular design'}

Specify each file to create with:
1. Filename
2. Purpose
3. Key classes/functions
4. Dependencies"""

        try:
            response = await asyncio.to_thread(
                agent.llm_client.generate, prompt
            )

            content = response.content if hasattr(response, 'content') else str(response)
            self.output.add_llm_response(content[:1000], agent._provider)

            # Parse file specifications
            agent.context.file_specs = content
            self.output.add_success("Design specifications complete")
            return True

        except Exception as e:
            self.output.add_error(f"Design failed: {e}")
            return False

    async def _phase_interfaces(self) -> bool:
        """Execute interface generation phase."""
        self.output.add_info("Generating interfaces...")
        # Simplified - actual implementation would generate interface definitions
        self.output.add_success("Interfaces defined")
        return True

    async def _phase_coding(self) -> bool:
        """Execute coding phase - generate actual code files."""
        agent = self._agent

        self.output.add_info("Generating code files...")

        # Determine files to generate dynamically
        self.output.add_info("Determining necessary files...")
        
        file_list_prompt = f"""
PROJECT: {agent.context.original_request}

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements[:10])}

DESIGN:
{agent.context.file_specs if hasattr(agent.context, 'file_specs') else 'Standard implementation'}

Based on the requirements and design, list the files that need to be created.
Include ALL necessary files (e.g., html, css, js, py, requirements.txt, etc.).
Return ONLY a valid JSON list of strings.
Example: ["index.html", "styles.css", "script.js"]
"""
        
        try:
            response = await asyncio.to_thread(agent.llm_client.generate, file_list_prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # extract json list
            import json
            import re
            
            # Find JSON array in output
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                try:
                    files_to_generate = json.loads(match.group(0))
                except json.JSONDecodeError:
                    # Fallback if specific parse fails, try to just split lines or use defaults
                    self.output.add_warning("Failed to parse file list JSON, checking for line-based list...")
                    files_to_generate = [line.strip().strip('- *') for line in content.splitlines() if '.' in line]
            else:
                self.output.add_warning("No JSON list found, using heuristic parsing...")
                files_to_generate = [line.strip().strip('- *') for line in content.splitlines() if '.' in line and not line.endswith(':')]

            # Sanity check
            if not files_to_generate:
                self.output.add_warning("Could not determine files, falling back to basic structure.")
                files_to_generate = ["main.py", "requirements.txt"]
            
            self.output.add_info(f"Files to generate: {', '.join(files_to_generate)}")

        except Exception as e:
            self.output.add_error(f"Failed to determine file list: {e}")
            files_to_generate = ["main.py", "requirements.txt"]

        for i, filename in enumerate(files_to_generate):
            self.output.add_info(f"Generating {filename}...")

            prompt = f"""You are an Expert Senior Full Stack Developer.

PROJECT: {agent.context.original_request}

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements[:5])}

CONTEXT:
This file is part of a larger project. Ensure it integrates well with other files like {', '.join([f for f in files_to_generate if f != filename])}.

Generate COMPLETE, WORKING content for {filename}.

CRITICAL REQUIREMENTS:
1.  **NO TRUNCATION**: Do not use placeholders like `... rest of code ...`. Write every single line.
2.  **SYNTAX SAFETY**: Ensure all brackets {{}}, parentheses (), and tags <></> are properly closed.
3.  **BEST PRACTICES**: Use modern patterns (e.g., semantic HTML5, ES6+ JavaScript, Type-Hinted Python).
4.  **ROBUSTNESS**: Include error handling and edge case management.
5.  **DOCUMENTATION**: Add helpful comments and docstrings.

Output ONLY the code/content wrapped in a code block, no explanations."""

            try:
                response = await asyncio.to_thread(
                    agent.llm_client.generate, prompt
                )

                content = response.content if hasattr(response, 'content') else str(response)

                # Extract code from response
                code = self._extract_code(content)

                if code:
                    # Save file
                    file_path = agent.project_dir / filename
                    # Ensure parent dirs exist
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(code)

                    self.output.add_file_generated(filename, len(code))
                    self._files_generated += 1

                    # Show code preview
                    from agents.common.config_defaults import PREVIEW_LANGUAGES
                    preview_lang = filename.split('.')[-1]
                    if preview_lang not in PREVIEW_LANGUAGES:
                        preview_lang = 'text'
                        
                    self.output.add_code(code[:500] + "..." if len(code) > 500 else code,
                                        language=preview_lang, filename=filename)

            except Exception as e:
                self.output.add_error(f"Failed to generate {filename}: {e}")

        self.output.add_success("Coding complete")
        self._logger.info("Coding phase complete. Generated %d files.", self._files_generated)
        return True

    async def _phase_debugging(self) -> bool:
        """Execute debugging phase - validates code using shared linter logic."""
        agent = self._agent

        self.output.add_info("Reviewing code for issues...")
        self._logger.info("Starting debugging phase")

        files_checked = 0
        issues_found = []
        
        # Use shared linter logic
        from agents.coding_agent.hooks.builtin_hooks import run_linter
        
        # Define what languages to check
        languages_to_check = ['python', 'javascript', 'typescript']
        
        for lang in languages_to_check:
            self._logger.debug("Running linter for %s", lang)
            result = await run_linter(agent.project_dir, lang)
            
            if result.get('skipped'):
                continue
                
            if not result.get('success', False):
                self._logger.error("Linter failed for %s: %s", lang, result.get('error'))
                self.output.add_error(f"Linter error ({lang}): {result.get('error')}")
                continue
                
            files_checked += 1 # Count loosely as one check per language
            
            if result.get('has_issues'):
                issues_msg = result.get('issues', '').strip()
                if issues_msg:
                    issues_found.append(f"{lang.title()} Issues:\n{issues_msg}")
                    self.output.add_warning(f"⚠ Found {lang} issues")
                    self.output.add_code(issues_msg[:1000], language='text')
            else:
                self.output.add_success(f"✓ {lang.title()} checks passed")

        # Summary
        if files_checked == 0:
            self.output.add_info("No lintable code found")
            self._logger.info("No lintable code found")
        elif issues_found:
            self.output.add_warning(f"Found issues in {len(issues_found)} languages")
            self._logger.warning("Found issues in %d languages", len(issues_found))
        else:
            self.output.add_success("All checks passed")
            self._logger.info("All checks passed")

        return True

    async def _phase_testing(self) -> bool:
        """Execute testing phase - generates appropriate tests based on project type."""
        agent = self._agent

        self.output.add_info("Analyzing project type for testing...")

        # Detect project type based on generated files
        generated_files = list(agent.project_dir.glob("*"))
        file_extensions = {f.suffix.lower() for f in generated_files if f.is_file()}

        # Determine project type
        is_web_frontend = any(ext in file_extensions for ext in ['.html', '.css'])
        is_javascript = '.js' in file_extensions
        is_python = '.py' in file_extensions

        # For pure HTML/CSS projects, skip automated tests
        if is_web_frontend and not is_python and not is_javascript:
            self.output.add_info("Static HTML/CSS project detected - no automated tests needed")
            self.output.add_success("Manual browser testing recommended:")
            self.output.add_info("  1. Open index.html in a browser")
            self.output.add_info("  2. Verify layout and styling")
            self.output.add_info("  3. Test responsive design at different screen sizes")
            return True

        # For JavaScript projects, suggest Jest or manual testing
        if is_javascript and not is_python:
            self.output.add_info("JavaScript project detected")
            self.output.add_success("Testing recommendations:")
            self.output.add_info("  1. Open in browser and test functionality")
            self.output.add_info("  2. Check browser console for errors")
            self.output.add_info("  3. For unit tests, consider adding Jest")
            return True

        # For Python projects, generate pytest tests
        if is_python:
            self.output.add_info("Python project detected - generating pytest tests...")

            test_prompt = f"""Generate pytest tests for this Python project.

PROJECT: {agent.context.original_request}

Create comprehensive tests covering:
1. Main functionality
2. Edge cases
3. Error handling

Output complete test code."""

            try:
                response = await asyncio.to_thread(
                    agent.llm_client.generate, test_prompt
                )

                content = response.content if hasattr(response, 'content') else str(response)
                test_code = self._extract_code(content)

                if test_code:
                    test_path = agent.project_dir / "test_main.py"
                    test_path.write_text(test_code)
                    self.output.add_file_generated("test_main.py", len(test_code))

                self.output.add_success("Tests generated")
                return True

            except Exception as e:
                self.output.add_error(f"Test generation failed: {e}")
                return False

        # Fallback for other project types
        self.output.add_info("Project type not recognized - skipping automated test generation")
        return True

    def _should_launch_project(self, request: str) -> bool:
        """
        Detect if user's request indicates they want to run/launch the project.

        Args:
            request: Original user request

        Returns:
            True if user wants to launch the project
        """
        from agents.common.config_defaults import LAUNCH_KEYWORDS
        launch_keywords = LAUNCH_KEYWORDS
        request_lower = request.lower()
        return any(keyword in request_lower for keyword in launch_keywords)

    async def _launch_project(self) -> None:
        """
        Launch the project based on its type.
        Opens HTML in browser, runs Python scripts, etc.
        """
        import webbrowser
        import subprocess
        import platform

        agent = self._agent
        self._logger.info("Launching project in %s", agent.project_dir)
        project_dir = agent.project_dir

        # Detect project type
        html_files = list(project_dir.glob("*.html"))
        py_files = list(project_dir.glob("*.py"))
        js_files = list(project_dir.glob("*.js"))

        # Priority: HTML (web project) > Python > others
        if html_files:
            # Find the main HTML file
            main_html = None
            for name in ['index.html', 'main.html', 'home.html']:
                candidate = project_dir / name
                if candidate.exists():
                    main_html = candidate
                    break
            if not main_html:
                main_html = html_files[0]  # Use first HTML file

            self.output.add_info(f"Launching {main_html.name} in default browser...")

            try:
                # Use webbrowser module for cross-platform support
                file_url = main_html.as_uri()  # Converts to file:// URL
                webbrowser.open(file_url)
                self.output.add_success(f"✓ Opened {main_html.name} in browser")

                # Also try system-specific commands as fallback
                system = platform.system()
                if system == 'Linux':
                    # Try xdg-open as well for better desktop integration
                    try:
                        subprocess.Popen(['xdg-open', str(main_html)],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                    except FileNotFoundError:
                        pass  # xdg-open not available, webbrowser should have worked
                elif system == 'Darwin':  # macOS
                    subprocess.Popen(['open', str(main_html)],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                elif system == 'Windows':
                    subprocess.Popen(['start', '', str(main_html)],
                                   shell=True,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)

            except Exception as e:
                self.output.add_error(f"Failed to open browser: {e}")
                self.output.add_info(f"Manually open: {main_html}")

        elif py_files:
            # Find the main Python file
            main_py = None
            for name in ['main.py', 'app.py', 'run.py', '__main__.py']:
                candidate = project_dir / name
                if candidate.exists():
                    main_py = candidate
                    break
            if not main_py:
                main_py = py_files[0]

            self.output.add_info(f"To run the Python project:")
            self.output.add_info(f"  cd {project_dir}")
            self.output.add_info(f"  python {main_py.name}")

            # Ask if user wants to run it
            run_it = await self._ask_approval(
                "Run Python Script?",
                f"Would you like to run {main_py.name}?",
                ["Yes, run it", "No, skip"]
            )

            if run_it == "Yes, run it":
                self.output.add_info(f"Running {main_py.name}...")
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ['python3', str(main_py)],
                        cwd=str(project_dir),
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.stdout:
                        self.output.add_info("Output:")
                        self.output.add_code(result.stdout[:1000], language="text")
                    if result.stderr:
                        self.output.add_warning("Stderr:")
                        self.output.add_code(result.stderr[:500], language="text")
                    if result.returncode == 0:
                        self.output.add_success("✓ Script completed successfully")
                    else:
                        self.output.add_error(f"Script exited with code {result.returncode}")
                except subprocess.TimeoutExpired:
                    self.output.add_warning("Script timed out after 30 seconds")
                except Exception as e:
                    self.output.add_error(f"Failed to run script: {e}")

        elif js_files:
            self.output.add_info("JavaScript project - open HTML file in browser to run")
            self.output.add_info(f"Project location: {project_dir}")

        else:
            self.output.add_info(f"Project created at: {project_dir}")
            self.output.add_info("Check the generated files to run the project")

    def _show_completion_summary(self) -> None:
        """Show project completion summary."""
        if not self._agent:
            return

        agent = self._agent

        summary = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                          ✅ PROJECT COMPLETE                                   ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Project: {agent.project_name:<63} ║
║  Location: {str(agent.project_dir):<62} ║
║  Files: {self._files_generated:<65} ║
║  Iterations: {agent.context.iteration:<60} ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
        self.output.write(Text(summary, style="green"))

    def _extract_code(self, content: str) -> str:
        """Extract code from LLM response."""
        import re

        # Try to find code block with ANY language identifier
        # Matches ```python, ```html, ```css, ```javascript, or just ```
        match = re.search(r'```[\w\-\.\+]*\n(.*?)```', content, re.DOTALL)
        if match:
            return match.group(1).strip()

        # If no code block, return content if it looks like code
        if content.strip().startswith(('import ', 'from ', 'def ', 'class ', '#', '<html', '<!DOCTYPE', 'body {', 'function ')):
            return content.strip()

        return content.strip()

    async def _ask_question(self, question: str) -> str:
        """Ask user a question and wait for response."""
        self._pending_question = asyncio.Future()

        self.prompt.ask_question(question)
        self.output.add_info(f"❓ {question}")

        try:
            result = await self._pending_question
            self.output.add_info(f"   → {result}")
            return result
        finally:
            self._pending_question = None
            # Safely reset prompt, detecting if widget is still available
            try:
                self.prompt.reset()
            except Exception:
                # Ignore errors during cleanup/shutdown (e.g. widget not found)
                pass

    async def _ask_approval(
        self,
        title: str,
        content: str,
        options: List[str]
    ) -> str:
        """Show approval request and get user choice via chat."""
        self.output.add_separator()
        self.output.add_info(f"📋 {title}")
        self.output.add_info(content)
        self.output.add_info("\nPlease select an option:")
        
        for i, option in enumerate(options):
            self.output.add_info(f"  {i+1}. {option}")
            
        self.output.add_separator()
        
        while True:
            # wait for input
            response = await self._ask_question(f"Select option (1-{len(options)}):")
            
            # clean input
            cleaned = response.strip()
            
            # Check for direct match with option text
            if cleaned in options:
                self.output.add_success(f"Selected: {cleaned}")
                return cleaned
                
            # Check for index
            try:
                idx = int(cleaned) - 1
                if 0 <= idx < len(options):
                    result = options[idx]
                    self.output.add_success(f"Selected: {result}")
                    return result
            except ValueError:
                pass
                
            self.output.add_error(f"Invalid selection. Please enter a number 1-{len(options)} or the option name.")

    async def action_quit(self) -> None:
        """Quit the application."""
        # Cancel any running task first
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            self._current_task = None

        if self._is_processing:
            # If we were processing, we already cancelled above, but let's be double sure
            # or if this action_quit was triggered by a binding while running
            pass 

        # Auto-save prompt history on exit
        self._save_prompt_history()
        self.exit()

    def on_unmount(self) -> None:
        """Cleanup on unmount."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    async def action_pause(self) -> None:
        """Pause the agent."""
        if self._is_processing and not self._paused:
            self._paused = True
            self.output.add_warning("⏸️  Agent paused")

    async def action_resume(self) -> None:
        """Resume the agent."""
        if self._paused:
            self._paused = False
            self.output.add_success("▶️  Agent resumed")

    def save_state(self) -> None:
        """Save current application state to disk."""
        try:
            state = {
                'timestamp': datetime.now().isoformat(),
                'project_dir': str(self._project_dir),
                'logs': [line.text if hasattr(line, 'text') else str(line) for line in self.output.lines],
                'files_generated': self._files_generated
            }
            
            if self._orchestrator:
                state['orchestrator'] = self._orchestrator.get_state()
                
            StateManager.save_state(self._project_dir, state)
            self.output.add_success("Application state saved")
            
        except Exception as e:
            # Don't let save failure crash the exit process
            logger.error(f"Failed to save state on exit: {e}")

    async def action_save(self) -> None:
        """Save current state including prompt history."""
        saved_items = []

        # Save agent state if available
        if self._agent and self._agent.state_persistence:
            self._agent.state_persistence.create_checkpoint(
                "manual_save",
                self._agent.current_phase.name,
                self._agent.context.iteration,
                {"request": self._agent.context.original_request}
            )
            saved_items.append("agent state")

        # Always save prompt history
        self._save_prompt_history()
        saved_items.append("prompt history")

        self.output.add_success(f"Saved: {', '.join(saved_items)}")

    def _save_prompt_history(self) -> None:
        """Save prompt history to file."""
        import json
        history_file = self._project_dir / ".prompt_history.json"
        try:
            history = self.prompt.get_history()
            # Keep last 100 entries
            history = history[-100:]
            history_file.write_text(json.dumps(history, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save prompt history: {e}")

    def _load_prompt_history(self) -> None:
        """Load prompt history from file."""
        import json
        history_file = self._project_dir / ".prompt_history.json"
        try:
            if history_file.exists():
                history = json.loads(history_file.read_text())
                if isinstance(history, list):
                    # Restore history to prompt panel
                    self.prompt._history = history
                    self.prompt._history_index = len(history)
                    logger.info(f"Loaded {len(history)} history entries")
        except Exception as e:
            logger.warning(f"Failed to load prompt history: {e}")

    async def action_clear(self) -> None:
        """Clear output."""
        self.output.clear()
        self._show_welcome()

    async def action_interrupt(self) -> None:
        """Interrupt current operation (Ctrl+C or Escape)."""
        if self._pending_question and not self._pending_question.done():
            # Cancel pending question
            self._pending_question.set_result("")
            self.output.add_warning("Input cancelled")
            return

        if self._current_task and not self._current_task.done():
            # Cancel running agent task
            self._current_task.cancel()
            self._is_processing = False
            self.output.add_warning("Agent task interrupted")
            self.prompt.clear_waiting()
            self.prompt.set_prompt("Enter your coding request:")
            return

        # Nothing to interrupt
        self.output.add_info("Nothing to interrupt. Use Ctrl+Q to force quit.")

    async def action_force_quit(self) -> None:
        """Force quit the application (Ctrl+Q)."""
        self._save_prompt_history()  # Save history even on force quit
        self.save_state()  # Save application state
        self.output.add_warning("Force quitting...")
        self.exit()

    def action_scroll_up(self) -> None:
        """Scroll output panel up."""
        self.output.scroll_page_up()

    def action_scroll_down(self) -> None:
        """Scroll output panel down."""
        self.output.scroll_page_down()

    def action_scroll_top(self) -> None:
        """Scroll output panel to top."""
        self.output.scroll_home()

    def action_scroll_bottom(self) -> None:
        """Scroll output panel to bottom."""
        self.output.scroll_end()

    async def action_save_output(self) -> None:
        """Save all output to a file (Ctrl+O)."""
        from datetime import datetime

        if not self._output_history:
            self.output.add_warning("No output to save")
            return

        # Create output file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self._project_dir / f"raica_output_{timestamp}.txt"

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text("\n".join(self._output_history))
            self.output.add_success(f"Output saved to: {output_file}")
        except Exception as e:
            self.output.add_error(f"Failed to save output: {e}")

    async def action_copy_output(self) -> None:
        """Copy last output section to clipboard (Ctrl+Y)."""
        if not self._output_history:
            self.output.add_warning("No output to copy")
            return

        # Get last 50 lines or all if less
        recent_output = "\n".join(self._output_history[-50:])

        try:
            # Try using xclip (Linux)
            import subprocess
            process = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            process.communicate(recent_output.encode('utf-8'))

            if process.returncode == 0:
                self.output.add_success("Last 50 lines copied to clipboard")
            else:
                raise Exception("xclip failed")

        except FileNotFoundError:
            # xclip not available, try xsel
            try:
                process = subprocess.Popen(
                    ['xsel', '--clipboard', '--input'],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                process.communicate(recent_output.encode('utf-8'))
                self.output.add_success("Last 50 lines copied to clipboard")
            except FileNotFoundError:
                # No clipboard tool available
                self.output.add_warning("No clipboard tool (xclip/xsel). Use Ctrl+O to save to file.")
        except Exception as e:
            self.output.add_warning(f"Clipboard copy failed: {e}. Use Ctrl+O to save to file.")

    async def action_help(self) -> None:
        """Show help."""
        help_text = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                    HELP                                        ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  KEYBOARD SHORTCUTS:                                                           ║
║    Ctrl+C     Interrupt current operation                                     ║
║    Ctrl+Q     Force quit application                                          ║
║    Ctrl+O     Save output to file                                             ║
║    Ctrl+Y     Copy last 50 lines to clipboard                                 ║
║    Ctrl+P     Pause agent execution                                           ║
║    Ctrl+R     Resume agent execution                                          ║
║    Ctrl+S     Save current state                                              ║
║    Ctrl+L     Clear output display                                            ║
║    F1         Show this help                                                  ║
║    Escape     Cancel current operation                                        ║
║    PageUp/Dn  Scroll output                                                   ║
║                                                                               ║
║  DEVELOPMENT PHASES:                                                          ║
║    1. REQUIREMENTS  - Analyze and extract requirements                        ║
║    2. PLANNING      - Create implementation plan                              ║
║    3. ARCHITECTURE  - Design system structure                                 ║
║    4. DESIGN        - Specify file details                                    ║
║    5. INTERFACES    - Generate interfaces                                     ║
║    6. CODING        - Write actual code                                       ║
║    7. DEBUGGING     - Review and fix issues                                   ║
║    8. TESTING       - Generate and run tests                                  ║
║                                                                               ║
║  The agent will ask for your input at key decision points.                    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
        self.output.write(Text(help_text, style="cyan"))


def run_interactive_agent(config: Optional[Dict[str, Any]] = None):
    """
    Entry point for the interactive agent.

    Args:
        config: Optional configuration dict with keys:
            - project_dir: Project directory path
            - resume: Whether to resume previous session
            - hooks_enabled: Enable/disable automated hooks
            - knowledge_enabled: Enable/disable RAICA knowledge server
            - verification_enabled: Enable/disable 90% success verification
            - model_override: Override LLM model
            - raica_server_url: RAICA server URL
            - verbose: Enable verbose output
    """
    app = InteractiveAgentApp(config)
    app.run()


if __name__ == "__main__":
    run_interactive_agent()
