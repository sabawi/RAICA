"""
Coding Agent TUI Application
============================

Main Textual application for interactive CLI Coding Agent.
Features split-pane layout with scrolling output and static prompt.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Any, Awaitable

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static
from textual.binding import Binding
from textual.message import Message

from .widgets.output_panel import OutputPanel
from .widgets.prompt_panel import PromptPanel
from .widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


class CodingAgentApp(App):
    """
    Interactive TUI for CLI Coding Agent.

    Layout:
    - Header: Title and clock
    - Output Panel (80%): Scrollable output for phases and LLM responses
    - Status Bar: Phase, iteration, progress
    - Prompt Panel (20%): Static input area
    - Footer: Keybinding hints
    """

    TITLE = "CLI Coding Agent v2.1"
    SUB_TITLE = "Interactive Code Generation"

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: 1fr;
    }

    #output-container {
        height: 4fr;
    }

    #status-container {
        height: auto;
    }

    #prompt-container {
        height: 1fr;
        max-height: 8;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+p", "pause", "Pause"),
        Binding("ctrl+r", "resume", "Resume"),
        Binding("ctrl+s", "save_state", "Save"),
        Binding("ctrl+l", "clear_output", "Clear"),
        Binding("f1", "help", "Help"),
        Binding("escape", "cancel_phase", "Cancel"),
    ]

    class AgentMessage(Message):
        """Message for agent events."""
        def __init__(self, event_type: str, data: Any = None):
            self.event_type = event_type
            self.data = data
            super().__init__()

    def __init__(
        self,
        *,
        on_prompt_submit: Optional[Callable[[str], Awaitable[None]]] = None,
        on_pause: Optional[Callable[[], Awaitable[None]]] = None,
        on_resume: Optional[Callable[[], Awaitable[None]]] = None,
        on_cancel: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        """
        Initialize the TUI application.

        Args:
            on_prompt_submit: Callback for when user submits prompt
            on_pause: Callback for pause action
            on_resume: Callback for resume action
            on_cancel: Callback for cancel action
        """
        super().__init__()

        self._on_prompt_submit = on_prompt_submit
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_cancel = on_cancel
        self._paused = False

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header(show_clock=True)

        yield Container(
            Vertical(
                Container(
                    OutputPanel(id="output"),
                    id="output-container"
                ),
                Container(
                    StatusBar(id="status"),
                    id="status-container"
                ),
                Container(
                    PromptPanel(id="prompt"),
                    id="prompt-container"
                ),
            ),
            id="main-container"
        )

        yield Footer()

    @property
    def output_panel(self) -> OutputPanel:
        """Get the output panel widget."""
        return self.query_one("#output", OutputPanel)

    @property
    def status_bar(self) -> StatusBar:
        """Get the status bar widget."""
        return self.query_one("#status", StatusBar)

    @property
    def prompt_panel(self) -> PromptPanel:
        """Get the prompt panel widget."""
        return self.query_one("#prompt", PromptPanel)

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.output_panel.add_info("CLI Coding Agent TUI initialized")
        self.output_panel.add_info("Use Ctrl+C to quit, F1 for help")
        self.output_panel.add_separator()
        self.prompt_panel.set_prompt("Enter your code generation request:")

    async def on_prompt_panel_prompt_submitted(
        self,
        event: PromptPanel.PromptSubmitted
    ) -> None:
        """Handle prompt submission."""
        if not event.value:
            return

        self.output_panel.add_info(f"Request: {event.value}")

        if self._on_prompt_submit:
            self.prompt_panel.set_waiting("Processing request...")
            try:
                await self._on_prompt_submit(event.value)
            finally:
                self.prompt_panel.clear_waiting()

    async def on_prompt_panel_prompt_cancelled(
        self,
        event: PromptPanel.PromptCancelled
    ) -> None:
        """Handle prompt cancellation."""
        self.output_panel.add_warning("Input cancelled")

    # === Public API for Agent Integration ===

    def set_phase(self, phase: str, iteration: int = 1) -> None:
        """
        Set the current development phase.

        Args:
            phase: Phase name
            iteration: Current iteration
        """
        self.status_bar.set_phase(phase, iteration)
        self.output_panel.add_phase_header(phase, iteration)

    def set_progress(self, progress: float, message: str = "") -> None:
        """
        Set progress percentage.

        Args:
            progress: Progress 0-100
            message: Optional status message
        """
        self.status_bar.set_progress(progress, message)

    def add_output(self, content: str, style: str = "info") -> None:
        """
        Add output to the panel.

        Args:
            content: Content to display
            style: One of 'info', 'success', 'warning', 'error'
        """
        if style == "success":
            self.output_panel.add_success(content)
        elif style == "warning":
            self.output_panel.add_warning(content)
        elif style == "error":
            self.output_panel.add_error(content)
        else:
            self.output_panel.add_info(content)

    def add_llm_response(self, response: str, provider: str = "LLM") -> None:
        """
        Add LLM response to output.

        Args:
            response: Response content
            provider: LLM provider name
        """
        self.output_panel.add_llm_response(response, provider)

    def add_code(
        self,
        code: str,
        language: str = "python",
        filename: Optional[str] = None
    ) -> None:
        """
        Add a code block to output.

        Args:
            code: Code content
            language: Programming language
            filename: Optional filename
        """
        self.output_panel.add_code(code, language, filename)

    def add_file_generated(self, filepath: str, size: int = 0) -> None:
        """
        Notify that a file was generated.

        Args:
            filepath: Path to generated file
            size: File size in bytes
        """
        self.output_panel.add_file_generated(filepath, size)
        self.status_bar.increment_files()

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.output_panel.add_error(message)
        self.status_bar.increment_errors()

    async def ask_question(
        self,
        question: str,
        options: Optional[list] = None
    ) -> str:
        """
        Ask the user a question and wait for response.

        Args:
            question: Question to ask
            options: Optional list of valid options

        Returns:
            User's response
        """
        response_future: asyncio.Future = asyncio.Future()

        def on_response(value: str):
            if not response_future.done():
                response_future.set_result(value)

        self.prompt_panel.ask_question(
            question,
            options=options,
            on_submit=on_response
        )

        return await response_future

    def set_waiting(self, message: str = "Processing...") -> None:
        """Set prompt to waiting mode."""
        self.prompt_panel.set_waiting(message)

    def clear_waiting(self) -> None:
        """Clear waiting mode."""
        self.prompt_panel.clear_waiting()

    # === Actions ===

    async def action_quit(self) -> None:
        """Quit the application."""
        self.output_panel.add_warning("Exiting...")
        self.exit()

    async def action_pause(self) -> None:
        """Pause the agent."""
        if self._paused:
            return

        self._paused = True
        self.status_bar.phase = "PAUSED"
        self.output_panel.add_warning("Agent paused. Press Ctrl+R to resume.")

        if self._on_pause:
            await self._on_pause()

    async def action_resume(self) -> None:
        """Resume the agent."""
        if not self._paused:
            return

        self._paused = False
        self.output_panel.add_success("Agent resumed")

        if self._on_resume:
            await self._on_resume()

    async def action_cancel_phase(self) -> None:
        """Cancel current phase."""
        self.output_panel.add_warning("Cancelling current phase...")

        if self._on_cancel:
            await self._on_cancel()

    async def action_save_state(self) -> None:
        """Save current state."""
        self.output_panel.add_info("Saving state...")
        self.post_message(self.AgentMessage("save_state"))

    async def action_clear_output(self) -> None:
        """Clear the output panel."""
        self.output_panel.clear()
        self.output_panel.add_info("Output cleared")

    async def action_help(self) -> None:
        """Show help."""
        help_text = """
╔═══════════════════════════════════════════════════════════════╗
║                     CLI Coding Agent Help                      ║
╠═══════════════════════════════════════════════════════════════╣
║  Keybindings:                                                  ║
║    Ctrl+C    - Quit the application                           ║
║    Ctrl+P    - Pause the agent                                ║
║    Ctrl+R    - Resume the agent                               ║
║    Ctrl+S    - Save current state                             ║
║    Ctrl+L    - Clear output                                   ║
║    F1        - Show this help                                 ║
║    Escape    - Cancel current phase                           ║
║    PageUp    - Scroll output up                               ║
║    PageDown  - Scroll output down                             ║
║    Up/Down   - Navigate command history                       ║
║                                                                ║
║  Phases:                                                       ║
║    REQUIREMENTS → PLANNING → ARCHITECTURE → DESIGN →          ║
║    INTERFACE_GENERATION → CODING → DEBUGGING → TESTING →      ║
║    COMPLETE                                                    ║
╚═══════════════════════════════════════════════════════════════╝
"""
        self.output_panel.add_info(help_text)


# Standalone runner for testing
def run_tui_standalone():
    """Run the TUI application standalone for testing."""
    async def handle_submit(prompt: str):
        print(f"Received: {prompt}")

    app = CodingAgentApp(on_prompt_submit=handle_submit)
    app.run()


if __name__ == "__main__":
    run_tui_standalone()
