"""
Output Panel Widget
===================

Scrollable output panel for displaying agent phases, LLM responses, and progress.
Occupies the top 80% of the TUI.
"""

from textual.widgets import RichLog
from textual.binding import Binding
from rich.console import RenderableType
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
from datetime import datetime
from typing import Optional

from agents.common.agent_utils import ClipboardHelper


class OutputPanel(RichLog):
    """
    Scrollable output panel for agent activity display.

    Features:
    - Auto-scroll to bottom on new content
    - Syntax highlighting for code blocks
    - Phase-tagged output with timestamps
    - Color-coded message types (info, error, success, warning)
    """

    BINDINGS = [
        Binding("pageup", "page_up", "Page Up"),
        Binding("pagedown", "page_down", "Page Down"),
        Binding("home", "scroll_home", "Top"),
        Binding("end", "scroll_end", "Bottom"),
        Binding("ctrl+shift+c", "copy_all_output", "Copy All"),
    ]

    DEFAULT_CSS = """
    OutputPanel {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
        overflow-x: hidden;  /* Prevent horizontal scroll, rely on wrapping */
        overflow-y: auto;    /* Allow vertical scroll */
    }
    """

    def __init__(
        self,
        *,
        highlight: bool = True,
        markup: bool = True,
        auto_scroll: bool = True,
        wrap: bool = True,  # Enable word wrapping
        show_timestamps: bool = True,
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        """
        Initialize the output panel.

        Args:
            highlight: Enable syntax highlighting
            markup: Enable Rich markup
            auto_scroll: Auto-scroll to bottom
            wrap: Enable word wrapping for long lines
            show_timestamps: Show timestamps on messages
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(
            highlight=highlight,
            markup=markup,
            auto_scroll=auto_scroll,
            wrap=wrap,  # Pass wrap parameter to RichLog
            name=name,
            id=id,
            classes=classes,
        )
        self.show_timestamps = show_timestamps
        self._current_phase = ""

    def _format_timestamp(self) -> str:
        """Format current timestamp."""
        return datetime.now().strftime("%H:%M:%S")

    def add_phase_header(self, phase: str, iteration: int = 1) -> None:
        """
        Add a phase header separator.

        Args:
            phase: Phase name
            iteration: Current iteration number
        """
        self._current_phase = phase

        header = Text()
        header.append("\n")
        header.append("═" * 60, style="bold cyan")
        header.append("\n")
        header.append(f"  Phase: {phase}", style="bold white on blue")
        if iteration > 1:
            header.append(f" (Iteration {iteration})", style="yellow")
        header.append("\n")
        header.append("═" * 60, style="bold cyan")
        header.append("\n")

        self.write(header)

    def add_phase_output(self, phase: str, content: RenderableType) -> None:
        """
        Add phase-tagged output with optional timestamp.

        Args:
            phase: Phase name (e.g., "PLANNING", "CODING")
            content: Content to display
        """
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append(f"[{phase}] ", style="bold cyan")

        if isinstance(content, str):
            output.append(content)
        else:
            self.write(output)
            self.write(content)
            return

        self.write(output)

    def add_info(self, message: str) -> None:
        """Add an info message."""
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append("ℹ️  ", style="blue")
        output.append(message)

        self.write(output)

    def add_success(self, message: str) -> None:
        """Add a success message."""
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append("✅ ", style="green")
        output.append(message, style="green")

        self.write(output)

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append("⚠️  ", style="yellow")
        output.append(message, style="yellow")

        self.write(output)

    def add_error(self, message: str) -> None:
        """Add an error message."""
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append("❌ ", style="red")
        output.append(message, style="red")

        self.write(output)

    def add_llm_response(
        self,
        response: str,
        provider: str = "LLM",
        truncate: int = 2000
    ) -> None:
        """
        Add LLM response with formatting.

        Args:
            response: Response content
            provider: LLM provider name
            truncate: Max characters to show
        """
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append(f"🤖 [{provider}] ", style="magenta")
        self.write(output)

        # Truncate if needed
        display_response = response
        if len(response) > truncate:
            display_response = response[:truncate] + f"\n... (truncated, {len(response)} chars total)"

        # Try to detect and syntax highlight code blocks
        if "```" in display_response:
            self._add_with_code_blocks(display_response)
        else:
            self.write(Text(display_response, style="dim white"))

    def _add_with_code_blocks(self, content: str) -> None:
        """Parse and display content with code blocks highlighted."""
        import re

        # Split by code blocks
        pattern = r'```(\w*)\n(.*?)```'
        last_end = 0

        for match in re.finditer(pattern, content, re.DOTALL):
            # Add text before code block
            if match.start() > last_end:
                self.write(Text(content[last_end:match.start()], style="dim white"))

            # Add code block with syntax highlighting
            language = match.group(1) or "text"
            code = match.group(2).strip()

            try:
                syntax = Syntax(
                    code,
                    language,
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True
                )
                self.write(Panel(syntax, title=f"📄 {language}", border_style="green"))
            except Exception:
                self.write(Text(code, style="on dark_green"))

            last_end = match.end()

        # Add remaining text
        if last_end < len(content):
            self.write(Text(content[last_end:], style="dim white"))

    def add_code(
        self,
        code: str,
        language: str = "python",
        filename: Optional[str] = None
    ) -> None:
        """
        Add a code block with syntax highlighting.

        Args:
            code: Code content
            language: Programming language
            filename: Optional filename to show in title
        """
        title = f"📄 {filename}" if filename else f"📄 {language}"

        try:
            syntax = Syntax(
                code,
                language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True
            )
            self.write(Panel(syntax, title=title, border_style="green"))
        except Exception:
            self.write(Panel(code, title=title, border_style="dim"))

    def add_file_generated(self, filepath: str, size: int = 0) -> None:
        """Add notification that a file was generated."""
        output = Text()

        if self.show_timestamps:
            output.append(f"[{self._format_timestamp()}] ", style="dim")

        output.append("📁 Generated: ", style="green")
        output.append(filepath, style="bold white")

        if size > 0:
            output.append(f" ({size} bytes)", style="dim")

        self.write(output)

    def add_progress(
        self,
        current: int,
        total: int,
        description: str = ""
    ) -> None:
        """
        Add a simple text progress indicator.

        Args:
            current: Current step
            total: Total steps
            description: Progress description
        """
        percentage = (current / total * 100) if total > 0 else 0
        bar_width = 30
        filled = int(bar_width * current / total) if total > 0 else 0

        bar = "█" * filled + "░" * (bar_width - filled)

        output = Text()
        output.append(f"[{bar}] ", style="cyan")
        output.append(f"{current}/{total} ", style="white")
        output.append(f"({percentage:.0f}%) ", style="dim")

        if description:
            output.append(description, style="dim")

        self.write(output)

    def add_separator(self, char: str = "─", style: str = "dim") -> None:
        """Add a visual separator line."""
        self.write(Text(char * 60, style=style))

    def add_blank(self, count: int = 1) -> None:
        """Add blank lines."""
        for _ in range(count):
            self.write("")

    def action_page_up(self) -> None:
        """Scroll up one page."""
        self.scroll_page_up()

    def action_page_down(self) -> None:
        """Scroll down one page."""
        self.scroll_page_down()

    def action_scroll_home(self) -> None:
        """Scroll to top."""
        self.scroll_home()

    def action_scroll_end(self) -> None:
        """Scroll to bottom."""
        self.scroll_end()

    async def action_copy_all_output(self) -> None:
        """Copy all output content to clipboard."""
        # Extract text from lines
        text_content = []
        for line in self.lines:
            # line is likely a Strip or similar Rich object
            # We can try to get its text. self.lines returns list of Strips in recent Textual
            # Or simplified: check if it has 'text' property or convert to string
            text_content.append(line.text if hasattr(line, 'text') else str(line))
        
        full_text = "\n".join(text_content)
        
        if not full_text:
            self.app.notify("No output to copy", severity="warning")
            return

        if ClipboardHelper.copy(full_text):
            self.app.notify(f"Copied {len(full_text)} characters to clipboard")
        else:
            self.app.notify("Clipboard copy failed (install xclip/xsel)", severity="error")

