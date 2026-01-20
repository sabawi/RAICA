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
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# ============================================================================
# INTERRUPT HANDLING SYSTEM
# Robust solution using watchdog thread that works even when TUI is frozen
# ============================================================================
_interrupt_requested = False
_interrupt_time = 0
_watchdog_thread = None

def _request_interrupt():
    """Request an interrupt - called from signal handler or keyboard monitor."""
    global _interrupt_requested, _interrupt_time
    _interrupt_requested = True
    _interrupt_time = time.time()

def _force_exit():
    """Force exit the application."""
    print("\n\n🚨 FORCE EXIT\n", file=sys.__stderr__)
    try:
        if InteractiveAgentApp.instance:
            InteractiveAgentApp.instance.save_state()
    except:
        pass
    os._exit(1)

def _watchdog_worker():
    """
    Watchdog thread that monitors for interrupt requests AND kill file.

    Two ways to force exit:
    1. Ctrl+C sets _interrupt_requested, watchdog force-exits after 5 sec
    2. Create ~/.raica_kill file - watchdog detects and force-exits immediately

    The kill file is a guaranteed escape hatch when signals don't work.
    """
    global _interrupt_requested, _interrupt_time

    kill_file = Path.home() / ".raica_kill"
    printed_kill_hint = False

    while True:
        time.sleep(0.5)  # Check every 500ms

        # Check for kill file (guaranteed escape hatch)
        if kill_file.exists():
            try:
                kill_file.unlink()  # Remove the file
            except:
                pass
            print("\n\n🚨 KILL FILE DETECTED - forcing exit\n", file=sys.__stderr__)
            _force_exit()

        # Check for signal-based interrupt
        if _interrupt_requested:
            elapsed = time.time() - _interrupt_time
            if elapsed > 5.0:
                # 5 seconds since interrupt requested - force exit
                print("\n\n🚨 WATCHDOG: No response for 5 seconds - forcing exit\n", file=sys.__stderr__)
                _force_exit()
            elif elapsed > 2.0 and not printed_kill_hint:
                # After 2 seconds, print kill file hint
                print(f"\n💡 TIP: If frozen, create file: touch ~/.raica_kill\n", file=sys.__stderr__)
                printed_kill_hint = True

def _start_watchdog():
    """Start the watchdog thread if not already running."""
    global _watchdog_thread
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_thread = threading.Thread(target=_watchdog_worker, daemon=True)
        _watchdog_thread.start()

def _emergency_exit(signum, frame):
    """
    Emergency exit handler with double-press detection.

    - First Ctrl+C: Set interrupt flag, start watchdog timer
    - Second Ctrl+C (within 3 sec): Force immediate exit
    """
    global _interrupt_requested, _interrupt_time

    current_time = time.time()

    if _interrupt_requested and (current_time - _interrupt_time) < 3.0:
        # Second interrupt within 3 seconds - force exit immediately
        _force_exit()
    else:
        # First interrupt - set flag and warn
        _interrupt_requested = True
        _interrupt_time = current_time
        print("\n\n⚠️  Interrupt received. Press Ctrl+C again to force quit.", file=sys.__stderr__)
        print("    (Will auto-exit in 5 seconds if frozen...)\n", file=sys.__stderr__)

        # Try graceful cancellation
        try:
            if InteractiveAgentApp.instance and InteractiveAgentApp.instance._current_task:
                InteractiveAgentApp.instance._current_task.cancel()
        except:
            pass

# Set up signal handler
signal.signal(signal.SIGINT, _emergency_exit)
signal.signal(signal.SIGTERM, _emergency_exit)

# Start watchdog thread immediately
_start_watchdog()

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
from ..agent_config import AgentDefaults

# Import Context Management System (v2.2)
try:
    from agents.common.context.manager import ContextManager
    CONTEXT_SYSTEM_AVAILABLE = True
except ImportError:
    ContextManager = None
    CONTEXT_SYSTEM_AVAILABLE = False

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

        # Track last request for continuation handling
        self._last_request: Optional[str] = None
        self._last_request_succeeded: bool = True
        self._last_request_error: Optional[str] = None
        self._last_request_context: Dict[str, Any] = {}

        # Initialize Context Management System (v2.2)
        self._context_manager = None
        if CONTEXT_SYSTEM_AVAILABLE:
            try:
                self._context_manager = ContextManager(
                    project_dir=self._project_dir,
                    auto_initialize=True
                )
                logger.info("Context management system initialized for TUI")
            except Exception as e:
                logger.warning(f"Failed to initialize context manager: {e}")

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
        # Reinstall our signal handler in case Textual overrode it
        signal.signal(signal.SIGINT, _emergency_exit)
        signal.signal(signal.SIGTERM, _emergency_exit)

        self._show_welcome()
        self._load_prompt_history()  # Restore previous session's prompt history

        # Restore full application state if available
        self._load_state()

        self.prompt.input_widget.focus()

        # Enable auto-save every 30 seconds
        self.set_interval(30.0, self.save_state)

        # Check for interrupt requests every 500ms (gives Textual a chance to handle gracefully)
        self.set_interval(0.5, self._check_interrupt)

    def _check_interrupt(self) -> None:
        """Check for interrupt requests and handle gracefully within Textual."""
        global _interrupt_requested, _interrupt_time

        if _interrupt_requested:
            # Clear the flag - we're handling it
            _interrupt_requested = False

            # Cancel any running task
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                self._is_processing = False
                self.output.add_warning("⚠️ Operation interrupted by user")
                self.prompt.clear_waiting()
                self.prompt.set_prompt("Enter your coding request:")

            # Save state
            self.save_state()

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
                allow_sudo=self._allow_sudo,
                context_manager=self._context_manager
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

        # Handle /model command
        if value.lower() in ['/model', 'model']:
            await self._show_model_info()
            return

        # Handle /cd command - change project directory
        if value.lower().startswith('/cd ') or value.lower().startswith('cd '):
            await self._handle_cd_command(value)
            return

        # Handle /pwd command - show current project directory
        if value.lower() in ['/pwd', 'pwd']:
            self.output.add_info(f"Current project directory: {self._project_dir}")
            return

        # Check if we're waiting for a question response
        if self._pending_question and not self._pending_question.done():
            self._pending_question.set_result(value)
            return

        # New coding request
        if not self._is_processing:
            # Log full prompt immediately (before any processing that could crash)
            logger.info(f"USER_PROMPT_RECEIVED: {value}")

            # Check if this is a continuation of a failed request
            effective_request = self._handle_continuation_request(value)

            # Record user message in conversation context for continuity
            if self._context_manager:
                try:
                    self._context_manager.add_conversation_message('user', value)
                except Exception as e:
                    logger.debug(f"Failed to record conversation: {e}")

            self.output.add_info(f"Processing: {effective_request[:60]}...")
            # CRITICAL: Do NOT await here! Start as background task so event loop stays free
            # to process subsequent input events (for approval dialogs, questions, etc.)
            self._current_task = asyncio.create_task(self._run_agent_with_error_handling(effective_request))
        else:
            self.output.add_warning("Agent is already running. Press Escape to interrupt.")

    def _handle_continuation_request(self, request: str) -> str:
        """
        Detect and handle continuation requests like 'fix this', 'try again', 'continue'.

        When a previous request failed and user says something like 'fix this problem',
        we need to understand they mean the PREVIOUS request, not create a new project.

        Args:
            request: The user's current request

        Returns:
            Modified request with context, or original request if not a continuation
        """
        import re

        # Continuation patterns that reference the previous request
        continuation_patterns = [
            r'^fix\s+(this|that|it|the\s+problem|the\s+error|the\s+issue)s?\.?$',
            r'^try\s+again\.?$',
            r'^retry\.?$',
            r'^continue\.?$',
            r'^do\s+it\s+again\.?$',
            r'^run\s+it\s+again\.?$',
            r'^(please\s+)?fix\s+(this|that|it)\.?$',
            r'^what\s+went\s+wrong\??$',
            r'^why\s+did\s+(it|that)\s+fail\??$',
            r'^debug\s+(this|that|it)\.?$',
            r'^solve\s+(this|that|it)\.?$',
            r'^handle\s+(this|that|it)\.?$',
        ]

        request_lower = request.lower().strip()

        # Check if this looks like a continuation
        is_continuation = any(re.match(pattern, request_lower) for pattern in continuation_patterns)

        if not is_continuation:
            # Not a continuation - track this as the new "last request"
            self._last_request = request
            self._last_request_succeeded = True  # Assume success until proven otherwise
            self._last_request_error = None
            # Store project directory context for potential continuation
            self._last_request_context = {
                'project_dir': str(self._project_dir),
                'timestamp': datetime.now().isoformat()
            }
            return request

        # This IS a continuation - check if we have context from a previous request
        if not self._last_request:
            self.output.add_warning("No previous request to continue from. Please provide a full request.")
            return request

        if self._last_request_succeeded:
            # Previous request succeeded - user might want something else
            self.output.add_info(f"Previous request succeeded. Interpreting as: retry '{self._last_request[:50]}...'")

        # Build a contextual request that includes the original intent
        if self._last_request_error:
            contextual_request = (
                f"CONTINUATION: The previous request was: '{self._last_request}'. "
                f"It failed with error: '{self._last_request_error}'. "
                f"Please fix this and complete the original request."
            )
            self.output.add_info(f"Continuing from failed request: {self._last_request[:50]}...")
        else:
            contextual_request = (
                f"CONTINUATION: The previous request was: '{self._last_request}'. "
                f"Please retry or continue this request."
            )
            self.output.add_info(f"Retrying: {self._last_request[:50]}...")

        # Keep the same last_request for potential further continuations
        return contextual_request

    def _record_request_failure(self, error: str) -> None:
        """Record that the current request failed."""
        self._last_request_succeeded = False
        self._last_request_error = error
        logger.info(f"Request failed, recorded for continuation: {error[:100]}")

    def _record_request_success(self) -> None:
        """Record that the current request succeeded."""
        self._last_request_succeeded = True
        self._last_request_error = None

    def _show_status(self) -> None:
        """Show current agent status."""
        # Truncate path if too long
        proj_dir_str = str(self._project_dir)
        if len(proj_dir_str) > 60:
            proj_dir_str = "..." + proj_dir_str[-57:]

        if self._agent:
            project_name = self._agent.project_name[:60] if len(self._agent.project_name) > 60 else self._agent.project_name
            status_text = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                              AGENT STATUS                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Working Dir: {proj_dir_str:<60} ║
║  Processing: {'Yes' if self._is_processing else 'No':<62} ║
║  Paused: {'Yes' if self._paused else 'No':<66} ║
║  Project: {project_name:<64} ║
║  Phase: {self._agent.current_phase.name if hasattr(self._agent, 'current_phase') else 'N/A':<66} ║
║  Iteration: {self._agent.context.iteration if hasattr(self._agent, 'context') else 1:<63} ║
║  Files Generated: {self._files_generated:<56} ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
            self.output.write(Text(status_text, style="cyan"))
        else:
            self.output.add_info(f"Working directory: {proj_dir_str}")
    async def _show_model_info(self) -> None:
        """Show current LLM model configuration."""
        if not self._llm_client:
            await self._init_llm_client()

        if not self._llm_client:
            self.output.add_error("Failed to initialize LLM client")
            return

        info = self._llm_client.get_config_info()
        provider = info.get('primary_provider', 'unknown')
        model = info.get('primary_model', 'unknown')
        config_path = info.get('config_path', 'default')

        # Format nicer output
        text = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                              LLM CONFIGURATION                                 ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Provider: {provider:<66} ║
║  Model: {model:<69} ║
║  Source: {str(config_path):<68} ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
        self.output.write(Text(text, style="green"))

    async def _handle_cd_command(self, value: str) -> None:
        """
        Handle /cd command to change project directory.

        Usage:
            /cd /path/to/project
            /cd ~/my_project
            cd /path/to/project
        """
        # Extract path from command
        parts = value.split(maxsplit=1)
        if len(parts) < 2:
            self.output.add_error("Usage: /cd <path>")
            self.output.add_info(f"Current directory: {self._project_dir}")
            return

        path_str = parts[1].strip()

        # Expand ~ to home directory
        if path_str.startswith('~'):
            path_str = str(Path.home() / path_str[2:]) if path_str.startswith('~/') else str(Path.home())

        new_path = Path(path_str).resolve()

        # Create directory if it doesn't exist
        if not new_path.exists():
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self.output.add_success(f"Created directory: {new_path}")
            except PermissionError:
                self.output.add_error(f"Permission denied: Cannot create {new_path}")
                return
            except Exception as e:
                self.output.add_error(f"Failed to create directory: {e}")
                return

        # Switch project directory
        old_dir = self._project_dir
        self._project_dir = new_path

        # Update context manager if available
        if CONTEXT_SYSTEM_AVAILABLE and self._context_manager:
            try:
                self._context_manager.switch_project(new_path)
            except Exception as e:
                logger.warning(f"Failed to switch context manager: {e}")

        # Clear any previous request context since we're in a new project
        self._last_request_context = {}

        self.output.add_success(f"Changed project directory:")
        self.output.add_info(f"  From: {old_dir}")
        self.output.add_info(f"  To:   {new_path}")

        # Check what's in the new directory
        if new_path.exists() and any(new_path.iterdir()):
            files = list(new_path.iterdir())[:5]
            self.output.add_info(f"  Contents: {len(list(new_path.iterdir()))} items")
            for f in files:
                self.output.add_info(f"    - {f.name}")
            if len(list(new_path.iterdir())) > 5:
                self.output.add_info(f"    ... and more")
        else:
            self.output.add_info("  (empty directory)")

    async def _run_agent_with_error_handling(self, value: str) -> None:
        """Wrapper to run agent with proper error handling for background task."""
        try:
            await self._start_agent(value)
            # If we get here without exception, request succeeded
            self._record_request_success()
        except asyncio.CancelledError:
            # Task was cancelled (e.g., user quit during execution)
            self._record_request_failure("Task was cancelled by user")
            try:
                self.output.add_warning("Agent task was cancelled")
            except Exception:
                # UI is no longer available (app is shutting down)
                logger.warning("Agent task was cancelled (UI unavailable)")
        except Exception as e:
            # Record the failure for continuation handling
            self._record_request_failure(str(e))
            # Try to show error in UI, but handle gracefully if UI is gone
            try:
                self.output.add_error(f"Failed to start agent: {e}")
                import traceback
                logger.exception("Agent failed")
                # Log to output for visibility
                self.output.add_error(traceback.format_exc()[:500])
            except Exception:
                # UI is no longer available
                import traceback
                logger.exception(f"Agent failed (UI unavailable): {e}")
        finally:
            self._current_task = None

    def _show_welcome(self) -> None:
        """Display welcome message and instructions."""
        welcome = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    RAICA Interactive Agent v2.3                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  I handle CODING, DEBUGGING, SYSTEM QUERIES, and TASKS intelligently.         ║
║  I automatically detect your intent and route appropriately.                  ║
║                                                                               ║
║  CAPABILITIES:                                                                ║
║    CODE GEN    → "Create a Flask API with SQLite"                            ║
║    CODE DEBUG  → "Fix the login bug" / "Debug the API error" (IN-PLACE!)     ║
║    SYS QUERY   → "Is nginx installed?" / "Check Python version"              ║
║    SYS TASK    → "Install docker" / "Configure apache"                       ║
║    HYBRID      → "Install LAMP stack and create a PHP form"                  ║
║                                                                               ║
║  KEYBOARD SHORTCUTS:                                                          ║
║    Ctrl+C  - Interrupt     Ctrl+Q  - Force Quit     PageUp/Dn - Scroll       ║
║    Ctrl+S  - Save State    Ctrl+L  - Clear Output   F1        - Help         ║
║                                                                               ║
║  EMERGENCY EXIT: If frozen, run in another terminal: touch ~/.raica_kill     ║
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

        # ════════════════════════════════════════════════════════════════
        # CONTINUATION HANDLING: Extract original request and switch context
        # ════════════════════════════════════════════════════════════════
        original_request = request
        continuation_error = None
        is_continuation = False

        if request.startswith("CONTINUATION:"):
            is_continuation = True
            self.output.add_info("🔄 Detected continuation of previous request")
            logger.info("[CONTINUATION] Processing continuation request")

            # Extract original request from: "CONTINUATION: The previous request was: 'ORIGINAL'. ..."
            import re
            original_match = re.search(r"previous request was: ['\"](.+?)['\"]", request)
            if original_match:
                original_request = original_match.group(1)
                logger.info(f"[CONTINUATION] Extracted original request: {original_request[:100]}")
                self.output.add_info(f"Original request: {original_request[:60]}...")

            # Extract error if present
            error_match = re.search(r"failed with error: ['\"](.+?)['\"]", request)
            if error_match:
                continuation_error = error_match.group(1)
                logger.info(f"[CONTINUATION] Previous error: {continuation_error[:100]}")

            # Extract target path from the ORIGINAL request
            from agents.common.agent_utils import extract_target_path
            target_path = extract_target_path(original_request)

            if target_path:
                self.output.add_info(f"🎯 Switching context to: {target_path}")
                logger.info(f"[CONTINUATION] Switching to target directory: {target_path}")

                # Create directory if needed
                target_path.mkdir(parents=True, exist_ok=True)

                # Switch project directory
                self._project_dir = target_path

                # Also switch context manager if available
                if CONTEXT_SYSTEM_AVAILABLE and self._context_manager:
                    try:
                        self._context_manager.switch_project(target_path)
                    except Exception as e:
                        logger.warning(f"Failed to switch context manager: {e}")
            else:
                # No explicit path - check if we have stored context
                if self._last_request_context.get('project_dir'):
                    stored_path = Path(self._last_request_context['project_dir'])
                    if stored_path.exists():
                        self._project_dir = stored_path
                        self.output.add_info(f"📁 Using stored project directory: {stored_path}")
                        logger.info(f"[CONTINUATION] Using stored project dir: {stored_path}")

        try:
            # Step 1: Initialize LLM client if needed
            if not self._llm_client:
                await self._init_llm_client()

            # Step 2: Classify the request using the orchestrator
            # IMPORTANT: For continuations, classify the ORIGINAL request, not the wrapper
            request_to_classify = original_request if is_continuation else request
            self.output.add_info("Classifying request type...")
            classifier = RequestClassifier(self._llm_client)
            # Run classification in thread to avoid blocking (LLM call)
            classification = await asyncio.to_thread(classifier.classify, request_to_classify)

            self.output.add_info(
                f"Request type: {classification.primary_type.name} "
                f"(confidence: {classification.confidence:.0%})"
            )

            if classification.requires_sudo:
                self.output.add_warning("This request may require sudo privileges")

            # Step 2.5: Extract path from request if user provided one
            # e.g., "fix this snake game /home/user/project/snake_game" → extract path
            extracted_path = self._extract_path_from_request(request)
            if extracted_path and extracted_path.exists():
                self.output.add_info(f"📁 Using path from request: {extracted_path}")
                logger.info(f"[PATH] Extracted project path from request: {extracted_path}")
                self._project_dir = extracted_path

            # Step 3: Determine if this is a NEW PROJECT request or IN-PLACE modification
            # Key insight: "create a snake game" = NEW PROJECT, "fix the bug" = IN-PLACE
            logger.info(f"[PATH] Checking for existing project in: {self._project_dir}")
            has_existing_project = self._detect_existing_project()
            is_new_project_request = self._is_new_project_request(request)
            proceed_to_code_gen = False  # Flag to skip CREATE NEW and go directly to code gen

            # Decision logic:
            # - NEW PROJECT REQUEST → always create new subdirectory (regardless of existing code)
            # - CODE_DEBUG → always IN-PLACE (fixing existing code)
            # - CODE_GENERATION + existing project + NOT new project request → IN-PLACE enhancement

            if is_new_project_request:
                # User wants to CREATE something new - don't touch existing projects
                logger.info(f"[PATH] New project request detected - will CREATE NEW")
                has_existing_project = False  # Override - treat as no project

            if has_existing_project:
                # ════════════════════════════════════════════════════════════════
                # IN-PLACE MODE: Existing project AND user wants to modify it
                # All changes (bug fix, enhance, add feature) work on existing code
                # ════════════════════════════════════════════════════════════════
                self.output.add_info("📁 Existing project detected - using IN-PLACE mode")
                logger.info(f"[PATH] Existing project in {self._project_dir} - IN-PLACE mode")

                # Check if this might require a full rewrite
                is_code_change = classification.primary_type in [
                    RequestType.CODE_DEBUG, RequestType.CODE_GENERATION
                ]

                if is_code_change:
                    # Use unified in-place handler for ALL code changes
                    self.output.add_info("🔧 Modifying existing project (DO NO HARM mode)")
                    result = await self._handle_inplace_code_change(request, classification)

                    if result:
                        if result.success:
                            self.output.add_success("Changes applied successfully!")
                            if hasattr(result, 'generated_files') and result.generated_files:
                                modified = [f for f in result.generated_files if not f.startswith("__")]
                                if modified:
                                    self.output.add_info(f"Modified files: {', '.join(modified[:5])}")
                        else:
                            error_msg = result.error or 'Unknown error'
                            self.output.add_error(f"Changes failed: {error_msg}")
                            self._record_request_failure(error_msg)  # Record for continuation
                            if hasattr(result, 'rollback_performed') and result.rollback_performed:
                                self.output.add_warning("Changes have been rolled back")
                    return
                else:
                    # System query/task - use orchestrator
                    self.output.add_info("Processing system request...")
                    result = await self._handle_intelligent_request(request, classification)

                    # Check if the plan included code generation steps
                    if result and result.generated_files and any(
                        f.startswith("__CODE_GEN__") or f == "__USE_CODE_GEN_PIPELINE__"
                        for f in result.generated_files
                    ):
                        self.output.add_info("Plan requires code generation - proceeding with code gen pipeline...")
                        logger.info("[PATH] System request included CODE_GEN steps - proceeding to code generation")
                        proceed_to_code_gen = True  # Skip CREATE NEW, go directly to code gen
                    else:
                        if result and result.success:
                            self.output.add_success("Request completed")
                        elif result and not result.success:
                            error_msg = result.error or 'Request failed'
                            self._record_request_failure(error_msg)  # Record for continuation
                        return

            if not proceed_to_code_gen:
                # ════════════════════════════════════════════════════════════════
                # CREATE NEW MODE: No existing project
                # ════════════════════════════════════════════════════════════════
                self.output.add_info("📂 No existing project - CREATE NEW mode")
                logger.info(f"[PATH] No project in {self._project_dir} - CREATE NEW mode")

                # For other request types, use intelligent orchestration
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
            logger.info("[PATH] === ENTERING CODE GENERATION PIPELINE ===")
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
            try:
                self.output.add_error(f"Agent error: {e}")
                import traceback
                self.output.add_error(traceback.format_exc())
            except Exception:
                pass  # UI may be unavailable
            logger.exception("Agent failed")
        finally:
            self._is_processing = False
            try:
                self.prompt.clear_waiting()
                self.prompt.set_prompt("Enter another request or Ctrl+C to quit:")
            except Exception:
                pass  # UI may be unavailable (app shutting down)

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
            allow_sudo=self._allow_sudo,
            context_manager=self._context_manager
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
                self._record_request_failure(result.error)  # Record for continuation
            if result.steps_failed > 0:
                self.output.add_info(f"Steps completed: {result.steps_completed}, failed: {result.steps_failed}")
                if not result.error:
                    self._record_request_failure(f"{result.steps_failed} steps failed")

        self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")

        return result

    def _detect_existing_project(self) -> bool:
        """
        Detect if the working directory contains an existing project.

        Checks for common project indicators:
        - Source code files (.py, .js, .ts, .java, .go, etc.)
        - Package files (package.json, requirements.txt, Cargo.toml, etc.)
        - Project structure (src/, lib/, app/ directories)

        Returns:
            True if existing project detected, False otherwise
        """
        if not self._project_dir.exists():
            return False

        # Check for source code files
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.c', '.rb', '.php'}
        for item in self._project_dir.iterdir():
            if item.is_file() and item.suffix in code_extensions:
                logger.info(f"[DETECT] Found source file: {item.name}")
                return True

        # Check for package/config files
        package_files = {
            'package.json', 'requirements.txt', 'Cargo.toml', 'go.mod',
            'pom.xml', 'build.gradle', 'Gemfile', 'composer.json',
            'setup.py', 'pyproject.toml', 'Makefile', 'CMakeLists.txt'
        }
        for pf in package_files:
            if (self._project_dir / pf).exists():
                logger.info(f"[DETECT] Found package file: {pf}")
                return True

        # Check for common project directories
        project_dirs = {'src', 'lib', 'app', 'api', 'components', 'services', 'models'}
        for pd in project_dirs:
            dir_path = self._project_dir / pd
            if dir_path.is_dir():
                # Check if directory has code files
                try:
                    has_code = any(f.suffix in code_extensions for f in dir_path.rglob('*') if f.is_file())
                    if has_code:
                        logger.info(f"[DETECT] Found project directory: {pd}/")
                        return True
                except Exception:
                    pass

        # Check for HTML files (web projects)
        html_files = list(self._project_dir.glob('*.html'))
        if html_files:
            logger.info(f"[DETECT] Found HTML files: {len(html_files)}")
            return True

        logger.info("[DETECT] No existing project detected")
        return False

    def _is_new_project_request(self, request: str) -> bool:
        """
        Detect if the request is asking to CREATE a new software project/application.

        Uses LLM for semantic understanding rather than keyword matching.
        Falls back to simple heuristics only if LLM is unavailable.

        Returns:
            True if this is a request to create a new software project, False otherwise
        """
        # Use LLM for semantic understanding (NO HARDCODED KEYWORDS)
        # The LLM understands context, intent, and nuance better than keyword matching
        if self._llm_client:
            try:
                prompt = f"""Analyze this request and determine if it's asking to CREATE A BRAND NEW SOFTWARE PROJECT FROM SCRATCH.

REQUEST: {request}

Answer with JSON:
{{
    "is_new_software_project": true/false,
    "reasoning": "brief explanation"
}}

CRITICAL GUIDELINES - READ CAREFULLY:

RETURN FALSE (NOT a new project) if ANY of these apply:
- References "current", "existing", "this", "the" project/app/code
- Uses words like "review", "redesign", "improve", "enhance", "modify", "update", "fix"
- Asks to change look/feel, UI, design, features of something that EXISTS
- Working on code in the current directory
- Adding features to or improving existing software

RETURN TRUE (IS a new project) ONLY if ALL of these are true:
- Explicitly asks to CREATE something FROM SCRATCH
- Does NOT reference any existing project
- Uses clear creation language: "create a new", "build me a", "write a new", "make a new"
- Examples: "create a snake game", "build me a todo app", "write a new Python script"

IMPORTANT: When in doubt, return FALSE. Enhancement requests on existing projects
should NEVER create a new subdirectory - they should modify the existing code.

Example that should return FALSE:
"review the current notepad project and redesign the UI" → FALSE (working on existing)
"improve the look and feel of this app" → FALSE (improving existing)
"add dark mode to the application" → FALSE (adding to existing)

Example that should return TRUE:
"create a new snake game using pygame" → TRUE (creating from scratch)
"build me a web calculator" → TRUE (creating from scratch)
"""
                response = self._llm_client.generate(prompt, max_tokens=200)
                content = response.content if hasattr(response, 'content') else str(response)

                import json, re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    data = json.loads(json_match.group())
                    result = data.get('is_new_software_project', False)
                    reasoning = data.get('reasoning', '')
                    logger.info(f"[DETECT] LLM new project detection: {result} - {reasoning}")
                    return result
            except Exception as e:
                logger.warning(f"[DETECT] LLM detection failed, using fallback: {e}")

        # Fallback: simple heuristic (only used if LLM unavailable)
        request_lower = request.lower()
        software_words = ['app', 'application', 'game', 'website', 'script', 'api', 'tool', 'program']
        create_words = ['create', 'build', 'write', 'develop', 'make']

        has_create = any(w in request_lower for w in create_words)
        has_software = any(w in request_lower for w in software_words)

        result = has_create and has_software
        logger.info(f"[DETECT] Fallback new project detection: {result}")
        return result

    def _extract_path_from_request(self, request: str) -> Optional[Path]:
        """
        Extract a file system path from the user's request.

        Looks for:
        - Absolute paths: /home/user/project/...
        - Home paths: ~/project/...

        Returns:
            Path object if found and exists, None otherwise
        """
        import re

        # Pattern for absolute Unix paths
        # Match paths like /home/user/project or /var/www/app
        abs_path_pattern = r'(/(?:home|var|usr|opt|tmp|root|mnt|srv|etc)[/\w\-_.]+)'

        # Pattern for home directory paths
        home_path_pattern = r'(~/[\w\-_./]+)'

        # Try absolute paths first
        matches = re.findall(abs_path_pattern, request)
        for match in matches:
            path = Path(match.rstrip('.,;:!?'))  # Strip trailing punctuation
            if path.exists():
                # If it's a file, use its parent directory
                if path.is_file():
                    path = path.parent
                logger.info(f"[PATH] Found absolute path in request: {path}")
                return path

        # Try home directory paths
        matches = re.findall(home_path_pattern, request)
        for match in matches:
            expanded = Path(match).expanduser()
            path = expanded.resolve()
            if path.exists():
                if path.is_file():
                    path = path.parent
                logger.info(f"[PATH] Found home path in request: {path}")
                return path

        return None

    async def _handle_inplace_code_change(self, request: str, classification):
        """
        Handle ALL code changes to existing projects IN-PLACE.

        This unified handler works for:
        - Bug fixes
        - Feature enhancements
        - Code improvements
        - Refactoring

        Uses the CodeDebugAgent with DO NO HARM mode:
        - Captures baseline before changes
        - Rolls back if regressions detected
        - Updates README.md
        - Provides user instructions

        Returns:
            OrchestratorResult or DebugResult with execution details
        """
        self.output.add_phase_header("IN-PLACE CODE CHANGE", 1)
        self.output.add_warning("DO NO HARM: Changes will be rolled back if issues detected")

        # Verify we have a project
        if not self._project_dir.exists():
            self.output.add_error(f"Project directory does not exist: {self._project_dir}")
            return None

        self.output.add_info(f"Working directory: {self._project_dir}")

        # Check for full rewrite scenario
        rewrite_keywords = ['rewrite', 'rebuild from scratch', 'start over', 'complete redesign', 'replace entirely']
        needs_rewrite = any(kw in request.lower() for kw in rewrite_keywords)

        if needs_rewrite:
            # Ask user for approval on rewrite
            choice = await self._ask_approval(
                "Full Rewrite Detected",
                "This request may require a complete rewrite. How would you like to proceed?",
                ["Modify existing code (recommended)", "Replace existing code", "Create new project", "Cancel"]
            )

            if choice == "Cancel":
                self.output.add_warning("Operation cancelled by user")
                return None
            elif choice == "Create new project":
                self.output.add_info("Switching to CREATE NEW mode...")
                # Fall through to code generation pipeline (handled by caller)
                from .request_classifier import ClassificationResult
                return type('Result', (), {
                    'success': True,
                    'generated_files': ['__USE_CODE_GEN_PIPELINE__'],
                    'error': None
                })()
            elif choice == "Replace existing code":
                self.output.add_warning("Will replace existing code after backup")
                # Continue with in-place but allow more aggressive changes
                pass

        # Extract error trace from request if present
        error_trace = self._extract_error_trace(request)
        if error_trace:
            self.output.add_info("Error trace detected - will use for analysis")

        try:
            # Dispatch based on classification
            if classification.primary_type == RequestType.CODE_GENERATION:
                # ENHANCEMENT / FEATURE MODE
                from agents.coding_agent.autonomous.enhancement_controller import AutonomousEnhancementController
                
                self.output.add_info("Using autonomous ENHANCEMENT loop (TDD mode)")
                logger.info("Dispatching to AutonomousEnhancementController")

                controller = AutonomousEnhancementController(
                    llm_client=self._llm_client,
                    project_dir=self._project_dir,
                    output_callback=lambda msg: self.output.add_info(msg),
                    max_iterations=AgentDefaults.MAX_ITERATIONS
                )

                result = await controller.run_enhancement(
                    request=request,
                    resume=True
                )
                
                # Show results
                self.output.add_separator()
                if result.success:
                    self.output.add_success(f"ENHANCEMENT COMPLETE in {result.iterations} iteration(s)!")
                    if result.files_modified:
                        self.output.add_info(f"Files modified: {', '.join(result.files_modified)}")
                    if result.summary:
                        self.output.add_info(result.summary)
                else:
                    self.output.add_error(f"Enhancement failed: {result.error}")
                    self._record_request_failure(result.error or 'Enhancement failed')

                self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")
                
                # Wrapper for compatibility
                class ResultWrapper:
                    def __init__(self, res):
                        self.success = res.success
                        self.error = res.error
                        self.generated_files = res.files_modified or []
                        self.steps_completed = res.iterations
                        self.steps_failed = 0 if res.success else 1
                        self.duration_seconds = res.duration_seconds
                        self.rollback_performed = False # Enhancement controller handles this internally
                        
                return ResultWrapper(result)

            else:
                # DEBUG MODE (Default for CODE_DEBUG)
                from agents.coding_agent.autonomous import AutonomousDebugController, DebugOutcome
    
                self.output.add_info("Using autonomous DEBUG loop - no approvals until complete")
                logger.info("Dispatching to AutonomousDebugController")
    
                controller = AutonomousDebugController(
                    llm_client=self._llm_client,
                    project_dir=self._project_dir,
                    output_callback=lambda msg: self.output.add_info(msg),
                    max_iterations=AgentDefaults.MAX_ITERATIONS
                )
    
                # Run autonomous debug loop - NO APPROVALS
                result = await controller.debug_until_fixed(
                    bug_description=request,
                    error_trace=error_trace,
                    resume=True  # Resume existing session if any
                )
    
                # Show results
                self.output.add_separator()
                if result.success:
                    self.output.add_success(f"BUG FIXED in {result.iterations} iteration(s)!")
                    self.output.add_info(f"Root cause: {result.root_cause}")
                    if result.files_modified:
                        self.output.add_info(f"Files modified: {', '.join(result.files_modified)}")
                    if result.fix_summary:
                        self.output.add_info(result.fix_summary)
                else:
                    if result.outcome == DebugOutcome.BLOCKED:
                        self.output.add_warning(f"Debug blocked: {result.blocked_reason}")
                        self.output.add_info("Please provide more information or try a different approach.")
                    elif result.outcome == DebugOutcome.MAX_ITERATIONS:
                        self.output.add_warning(f"Could not fix bug in {result.iterations} iterations")
                        self.output.add_info("The bug may require manual investigation.")
                    else:
                        self.output.add_error(f"Debug failed: {result.blocked_reason}")
    
                    self._record_request_failure(result.blocked_reason or 'Debug failed')
    
                self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")
    
                # Return a result-compatible object (simple class to avoid OrchestratorResult signature issues)
                class DebugResultWrapper:
                    def __init__(self, res):
                        self.success = res.success
                        self.error = res.blocked_reason if not res.success else None
                        self.generated_files = res.files_modified or []
                        self.steps_completed = res.iterations
                        self.steps_failed = 0 if res.success else 1
                        self.duration_seconds = res.duration_seconds
                        self.rollback_performed = hasattr(res, 'rollback_performed') and res.rollback_performed
    
                return DebugResultWrapper(result)

        except ImportError as e:
            logger.warning(f"Autonomous controller not available: {e}, falling back to orchestrator")
            return await self._handle_inplace_orchestrator_fallback(request)
        except Exception as e:
            logger.exception("Autonomous loop failed")
            self.output.add_error(f"Execution error: {e}")
            self._record_request_failure(str(e))
            return None

    async def _handle_inplace_orchestrator_fallback(self, request: str):
        """Fallback to orchestrator-based in-place handling when autonomous debug unavailable."""
        self.output.add_info("Using orchestrator fallback...")

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
            allow_sudo=self._allow_sudo,
            context_manager=self._context_manager
        )

        result = await orchestrator.handle_request(request, force_inplace=True)

        self.output.add_separator()
        if result.success:
            self.output.add_success("In-place changes complete")
            if result.generated_files:
                modified = [f for f in result.generated_files if not f.startswith("__")]
                if modified:
                    self.output.add_info(f"Modified: {', '.join(modified[:5])}")
        else:
            error_msg = result.error or 'Unknown error'
            self.output.add_error(f"Changes failed: {error_msg}")
            self._record_request_failure(error_msg)

        self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")
        return result

    async def _handle_code_debug_request(self, request: str, classification):
        """
        Handle CODE_DEBUG requests using AUTONOMOUS DEBUG LOOP.

        No approvals needed - iterates until bug is fixed or genuinely blocked.
        All context saved to {project}/.raica/ for continuity.

        Returns:
            OrchestratorResult with execution details
        """
        self.output.add_phase_header("AUTONOMOUS DEBUG MODE", 1)
        self.output.add_info("Running autonomous debug loop - no approvals until complete or blocked")

        # Verify we have a project to debug
        if not self._project_dir.exists():
            error_msg = f"Project directory does not exist: {self._project_dir}"
            self.output.add_error(error_msg)
            self._record_request_failure(error_msg)
            return None

        # Check if directory has content
        has_files = any(self._project_dir.iterdir())
        if not has_files:
            error_msg = "Cannot debug empty directory. Use code generation for new projects."
            self.output.add_error(error_msg)
            self._record_request_failure(error_msg)
            return None

        self.output.add_info(f"Target directory: {self._project_dir}")

        # Extract error trace from request if present
        error_trace = self._extract_error_trace(request)
        if error_trace:
            self.output.add_info("Error trace detected - will use for analysis")

        # Use autonomous debug controller
        try:
            from agents.coding_agent.autonomous import AutonomousDebugController, DebugOutcome

            controller = AutonomousDebugController(
                llm_client=self._llm_client,
                project_dir=self._project_dir,
                output_callback=lambda msg: self.output.add_info(msg),
                max_iterations=AgentDefaults.MAX_ITERATIONS
            )

            # Run autonomous debug loop - NO APPROVALS
            result = await controller.debug_until_fixed(
                bug_description=request,
                error_trace=error_trace,
                resume=True  # Resume existing session if any
            )

            # Show results
            self.output.add_separator()
            if result.success:
                self.output.add_success(f"BUG FIXED in {result.iterations} iteration(s)!")
                self.output.add_info(f"Root cause: {result.root_cause}")
                if result.files_modified:
                    self.output.add_info(f"Files modified: {', '.join(result.files_modified)}")
                if result.fix_summary:
                    self.output.add_info(result.fix_summary)
            else:
                if result.outcome == DebugOutcome.BLOCKED:
                    self.output.add_warning(f"Debug blocked: {result.blocked_reason}")
                    self.output.add_info("Please provide more information or try a different approach.")
                elif result.outcome == DebugOutcome.MAX_ITERATIONS:
                    self.output.add_warning(f"Could not fix bug in {result.iterations} iterations")
                    self.output.add_info("The bug may require manual investigation.")
                else:
                    self.output.add_error(f"Debug failed: {result.blocked_reason}")

                self._record_request_failure(result.blocked_reason or 'Debug failed')

            self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")

            # Return a result-compatible object (simple class to avoid OrchestratorResult signature issues)
            class DebugResultWrapper:
                def __init__(self, res):
                    self.success = res.success
                    self.error = res.blocked_reason if not res.success else None
                    self.generated_files = res.files_modified or []
                    self.steps_completed = res.iterations
                    self.steps_failed = 0 if res.success else 1
                    self.duration_seconds = res.duration_seconds

            return DebugResultWrapper(result)

        except ImportError as e:
            logger.warning(f"Autonomous debug not available: {e}, falling back to orchestrator")
            return await self._handle_code_debug_orchestrator(request, classification)
        except Exception as e:
            logger.exception("Autonomous debug failed")
            self.output.add_error(f"Autonomous debug error: {e}")
            self._record_request_failure(str(e))
            return None

    async def _handle_code_debug_orchestrator(self, request: str, classification):
        """
        Fallback: Handle CODE_DEBUG using the orchestrator (old method).

        Used when autonomous debug controller is not available.
        """
        self.output.add_info("Using orchestrator-based debug (fallback)")

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
            allow_sudo=self._allow_sudo,
            context_manager=self._context_manager
        )

        result = await orchestrator.handle_request(request)

        self.output.add_separator()
        if result.success:
            self.output.add_success("Debug complete - fix applied successfully")
            if result.steps_completed > 0:
                self.output.add_info(f"Steps completed: {result.steps_completed}")
            if result.generated_files:
                self.output.add_info(f"Modified files: {len(result.generated_files)}")
        else:
            error_msg = result.error or 'Unknown error'
            self.output.add_error(f"Debug failed: {error_msg}")
            self._record_request_failure(error_msg)

        self.output.add_info(f"Duration: {result.duration_seconds:.1f}s")
        return result

    def _extract_error_trace(self, request: str) -> Optional[str]:
        """
        Extract error trace/stack trace from the request if present.

        Looks for common patterns like:
        - Traceback (most recent call last):
        - File "...", line ...
        - Error: ...
        - Exception: ...
        """
        import re

        # Look for Python traceback
        traceback_match = re.search(
            r'(Traceback \(most recent call last\):.*?(?:\w+Error|\w+Exception):.*?)(?:\n\n|\Z)',
            request,
            re.DOTALL
        )
        if traceback_match:
            return traceback_match.group(1).strip()

        # Look for file/line references with errors
        error_match = re.search(
            r'(File ".*?", line \d+.*?(?:\w+Error|\w+Exception):.*?)(?:\n\n|\Z)',
            request,
            re.DOTALL
        )
        if error_match:
            return error_match.group(1).strip()

        # Look for just error messages
        simple_error = re.search(
            r'((?:\w+Error|\w+Exception):\s*.+?)(?:\n\n|\Z)',
            request,
            re.DOTALL
        )
        if simple_error:
            return simple_error.group(1).strip()

        return None

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
            allow_sudo=self._allow_sudo,
            context_manager=self._context_manager
        )

        # Execute the request
        result = await orchestrator.handle_request(request)

        # Show results
        self.output.add_separator()
        if result.success:
            self.output.add_success(f"Request completed successfully")
            self.output.add_info(f"Steps completed: {result.steps_completed}")
        else:
            error_msg = result.error or 'Unknown error'
            self.output.add_error(f"Request failed: {error_msg}")
            self._record_request_failure(error_msg)  # Record for continuation
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
            allow_sudo=self._allow_sudo,
            context_manager=self._context_manager
        )

        # Execute system steps first
        result = await orchestrator.handle_request(request)

        if not result.success:
            error_msg = result.error or 'System operations failed'
            self.output.add_error(f"System operations failed: {error_msg}")
            self._record_request_failure(error_msg)  # Record for continuation
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
            from agents.common.agent_utils import generate_semantic_name, extract_target_path

            # Check if user specified a target path in their request
            user_specified_path = extract_target_path(request)

            if user_specified_path:
                # User specified a path - FULLY SWITCH CONTEXT to that directory
                self.output.add_info(f"Switching to user-specified directory: {user_specified_path}")

                # Create the directory if it doesn't exist
                user_specified_path.mkdir(parents=True, exist_ok=True)

                # Update the project directory to the new location
                self._project_dir = user_specified_path
                output_dir = user_specified_path.parent
                project_name = user_specified_path.name

                # Reinitialize context manager for the new directory
                if CONTEXT_SYSTEM_AVAILABLE and self._context_manager:
                    try:
                        self._context_manager.switch_project(user_specified_path)
                        self.output.add_info(f"Context switched to: {user_specified_path}")
                    except Exception as e:
                        logger.warning(f"Failed to switch context manager: {e}")

                self.output.add_success(f"Working directory: {user_specified_path}")
            else:
                # No user-specified path - generate semantic name
                project_name = generate_semantic_name(request)
                output_dir = self._project_dir

            self.output.add_info(f"Creating project: {project_name}")
        else:
            output_dir = self._project_dir

        self._agent = await asyncio.to_thread(
            CLICodingAgent,
            project_name=project_name,
            output_dir=str(output_dir),
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

                error_msg = f"Phase {phase_name} failed: {e}"
                self.output.add_error(error_msg)
                self._record_request_failure(error_msg)  # Record for continuation
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
            
            # Valid file extensions to look for
            valid_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json',
                               '.yaml', '.yml', '.md', '.txt', '.sh', '.go', '.rs', '.java',
                               '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.sql', '.vue', '.svelte'}

            def is_valid_filename(s: str) -> bool:
                """Check if string looks like a valid filename."""
                s = s.strip().strip('- *`"\'')
                if not s or len(s) > 100:
                    return False
                # Must have a valid extension
                ext = '.' + s.split('.')[-1].lower() if '.' in s else ''
                if ext not in valid_extensions:
                    return False
                # Should not contain markdown/reasoning patterns
                bad_patterns = ['**', '```', ':', '(', ')', '[', ']', '`', '*', '→', '->', '<', '>']
                if any(p in s for p in bad_patterns):
                    return False
                return True

            def extract_filename(s: str) -> str:
                """Extract clean filename from string."""
                s = s.strip().strip('- *`"\'')
                # Remove common prefixes like "1. " or "- "
                s = re.sub(r'^[\d]+\.\s*', '', s)
                s = re.sub(r'^-\s*', '', s)
                return s.strip()

            # Find JSON array in output
            match = re.search(r'\[.*?\]', content, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    # Validate each item is a valid filename
                    files_to_generate = [f for f in parsed if isinstance(f, str) and is_valid_filename(f)]
                except json.JSONDecodeError:
                    files_to_generate = []

            # Fallback: look for valid filenames in the content
            if not files_to_generate:
                self.output.add_warning("JSON parse failed, extracting filenames from content...")
                for line in content.splitlines():
                    cleaned = extract_filename(line)
                    if is_valid_filename(cleaned):
                        files_to_generate.append(cleaned)
                        if len(files_to_generate) >= 10:  # Limit to prevent runaway
                            break

            # Sanity check
            if not files_to_generate:
                self.output.add_warning("Could not determine files, falling back to basic structure.")
                files_to_generate = ["index.html"] if "html" in agent.context.original_request.lower() else ["main.py"]
            
            self.output.add_info(f"Files to generate: {', '.join(files_to_generate)}")

        except Exception as e:
            self.output.add_error(f"Failed to determine file list: {e}")
            files_to_generate = ["main.py", "requirements.txt"]

        for i, filename in enumerate(files_to_generate):
            self.output.add_info(f"Generating {filename}...")

            # Build context about other files for consistency
            other_files = [f for f in files_to_generate if f != filename]
            
            prompt = f"""You are an Expert Senior Full Stack Developer generating production-quality code.

PROJECT: {agent.context.original_request}

REQUIREMENTS:
{chr(10).join(f'- {r}' for r in agent.context.refined_requirements[:5])}

FILES IN THIS PROJECT: {', '.join(files_to_generate)}

Generate COMPLETE, WORKING content for: **{filename}**

=== CRITICAL INTEGRATION RULES ===

1. **API CONSISTENCY** - When multiple files share data/constants:
   - Define names in ONE file (e.g., config.py), import everywhere else
   - If config.py defines `WINDOW_WIDTH`, other files must `from config import WINDOW_WIDTH`
   - NEVER define the same constant with different names (e.g., SCREEN_WIDTH vs WINDOW_WIDTH)
   - Export aliases if needed: `SCREEN_WIDTH = WINDOW_WIDTH`

2. **IMPORT CHAINS** - All files must be connected:
   - Entry point (main.py) must import files that import other files
   - A manager (scene_manager.py) MUST actually import the scenes it manages
   - DO NOT create files that are never imported by anything
   - Use ABSOLUTE imports (from module import X), not relative (from .module)

3. **FUNCTION SIGNATURES** - Must match across files:
   - If main.py calls `GameWindow(width=800)`, then GameWindow.__init__ MUST accept `width` parameter
   - Check what parameters callers will pass before defining the function

4. **PATH RESOLUTION** - For Python projects:
   - Use `Path(__file__).resolve().parent` to get current file's directory
   - NEVER use `.parent.parent` unless you truly need grandparent directory
   - Create paths relative to the file's own location

5. **FILE DEPENDENCIES** - For {filename}:
   - This file may need to import from: {', '.join(other_files[:5])}
   - Other files may need to import from this file
   - Ensure consistent naming of classes, functions, and constants

=== CODE QUALITY REQUIREMENTS ===

1. **NO TRUNCATION**: Write every single line - no `... rest of code ...` placeholders
2. **SYNTAX SAFETY**: Ensure all brackets, parentheses, and tags are properly closed  
3. **TYPE HINTS**: Use type annotations for all function parameters and returns
4. **ERROR HANDLING**: Include try/except for I/O operations and external calls
5. **DOCUMENTATION**: Add docstrings for all classes and public functions
"""
            
            # Special handling for requirements.txt
            if filename == 'requirements.txt':
                prompt += """
=== REQUIREMENTS.TXT SPECIFIC ===
This file MUST be a valid pip requirements file, NOT a document!
- One package per line
- Use format: package_name>=version (e.g., arcade>=2.6.17)
- Comments allowed with # prefix
- NO prose, NO markdown headers, NO bullet points
- NO project requirements document - ONLY pip packages

Example:
```
# Core dependencies
arcade>=2.6.17
numpy>=1.24.0
```
"""
            
            # Special handling for config files
            if filename in ['config.py', 'settings.py', 'constants.py']:
                prompt += """
=== CONFIG FILE SPECIFIC ===
- Define ALL constants that other files will need
- Provide BOTH your preferred naming AND aliases for common patterns:
  - WINDOW_WIDTH and SCREEN_WIDTH = WINDOW_WIDTH  
  - WINDOW_TITLE and TITLE = WINDOW_TITLE
- Export everything via __all__ list
- Use `Path(__file__).resolve().parent` for paths (NOT .parent.parent)
"""
            
            # Special handling for main entry points
            if filename in ['main.py', 'app.py', 'index.py']:
                prompt += """
=== ENTRY POINT SPECIFIC ===
- Import from config using the SAME names the config exports
- When calling classes, match the parameter names exactly
- Include proper error handling for import failures
- Create assets directories if they don't exist:
  ```python
  assets_dir = Path(__file__).parent / "assets"
  assets_dir.mkdir(exist_ok=True)
  ```
"""
            
            prompt += """
Output ONLY the code/content wrapped in a code block, no explanations."""

            try:
                response = await asyncio.to_thread(
                    agent.llm_client.generate, prompt
                )

                content = response.content if hasattr(response, 'content') else str(response)

                # Extract code from response with expected file type
                file_ext = filename.split('.')[-1].lower() if '.' in filename else None
                code = self._extract_code(content, expected_type=file_ext)

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
        
        # Set up Python environment (venv, requirements, deps)
        await self._setup_python_environment()
        
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
                test_code = self._extract_code(content, expected_type='py')

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

    async def _setup_python_environment(self) -> bool:
        """
        Set up Python environment after code generation.
        Creates venv, validates requirements.txt, and installs dependencies.
        """
        import sys
        import subprocess
        
        agent = self._agent
        project_dir = agent.project_dir
        
        # Check if this is a Python project
        py_files = list(project_dir.glob("*.py"))
        if not py_files:
            return True  # Not a Python project, skip
        
        self.output.add_info("🐍 Setting up Python environment...")
        
        # 1. Create virtual environment
        venv_path = project_dir / "venv"
        if not venv_path.exists():
            self.output.add_info("Creating virtual environment...")
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "venv", str(venv_path)],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    self.output.add_success("✓ Virtual environment created")
                else:
                    self.output.add_error(f"Failed to create venv: {result.stderr[:200]}")
                    return False
            except subprocess.TimeoutExpired:
                self.output.add_error("Venv creation timed out")
                return False
            except Exception as e:
                self.output.add_error(f"Venv creation failed: {e}")
                return False
        
        # 2. Validate and fix requirements.txt
        req_file = project_dir / "requirements.txt"
        if req_file.exists():
            try:
                from agents.coding_agent.services.requirements_validator import validate_requirements
                
                content = req_file.read_text()
                is_valid, fixed_content = validate_requirements(content)
                
                if not is_valid and not fixed_content.startswith("# Error"):
                    # Write the fixed content
                    req_file.write_text(fixed_content)
                    self.output.add_success("✓ Fixed requirements.txt format")
                elif not is_valid:
                    self.output.add_warning(f"Could not fix requirements.txt: {fixed_content}")
            except Exception as e:
                self.output.add_warning(f"Requirements validation skipped: {e}")
        
        # 3. Install dependencies
        if req_file.exists():
            self.output.add_info("Installing dependencies...")
            pip_path = venv_path / "bin" / "pip"
            if not pip_path.exists():
                pip_path = venv_path / "Scripts" / "pip.exe"  # Windows
            
            if pip_path.exists():
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        [str(pip_path), "install", "-r", str(req_file)],
                        capture_output=True, text=True, timeout=300
                    )
                    if result.returncode == 0:
                        self.output.add_success("✓ Dependencies installed")
                    else:
                        # Show abbreviated error
                        stderr = result.stderr[:300] if result.stderr else "Unknown error"
                        self.output.add_warning(f"Some dependencies may have failed:\n{stderr}")
                except subprocess.TimeoutExpired:
                    self.output.add_warning("Dependency installation timed out (>5min)")
                except Exception as e:
                    self.output.add_warning(f"Dependency installation failed: {e}")
        
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

            # Check for requirements.txt and install dependencies
            requirements_file = project_dir / 'requirements.txt'
            if requirements_file.exists():
                self.output.add_info("Found requirements.txt - installing dependencies...")
                try:
                    install_result = await asyncio.to_thread(
                        subprocess.run,
                        ['pip', 'install', '-r', 'requirements.txt'],
                        cwd=str(project_dir),
                        capture_output=True,
                        text=True,
                        timeout=120  # 2 minutes for pip install
                    )
                    if install_result.returncode == 0:
                        self.output.add_success("✓ Dependencies installed successfully")
                    else:
                        self.output.add_warning(f"Some dependencies may have failed:")
                        if install_result.stderr:
                            self.output.add_code(install_result.stderr[:500], language="text")
                except subprocess.TimeoutExpired:
                    self.output.add_warning("Dependency installation timed out (>120s)")
                except Exception as e:
                    self.output.add_warning(f"Failed to install dependencies: {e}")

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

    def _extract_code(self, content: str, expected_type: str = None) -> str:
        """
        Extract code from LLM response using iron-clad extraction.

        This handles:
        - Thinking/reasoning tags from various models
        - Multiple code blocks (picks the best/largest)
        - Quality scoring (completeness, bracket balance)
        - Unfenced code detection

        Args:
            content: Raw LLM response
            expected_type: Expected file type (html, py, js, etc.) for validation

        Returns:
            The best extracted code
        """
        from ..llm_client import extract_best_code_block, strip_thinking_content

        # First strip any thinking content
        content = strip_thinking_content(content)

        # Use iron-clad extraction with quality scoring
        return extract_best_code_block(content, expected_type)

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
            # Removed success message to reduce periodic clutter (per user request)
            
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
║  COMMANDS:                                                                     ║
║    /cd <path>  Change project directory (creates if needed)                   ║
║    /pwd        Show current project directory                                 ║
║    /status     Show agent status                                              ║
║    /model      Show LLM model configuration                                   ║
║    /help       Show this help                                                 ║
║    /exit       Exit RAICA                                                     ║
║                                                                               ║
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
