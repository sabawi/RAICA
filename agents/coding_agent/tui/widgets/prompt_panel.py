"""
Prompt Panel Widget
===================

Static input panel at the bottom of the TUI for user interaction.
Handles user input, command history, and question prompts.
"""

import subprocess
import shutil
from textual.widgets import TextArea, Static
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual.message import Message
from textual.events import Key
import logging

from rich.text import Text
from typing import Optional, List, Callable, Any

from agents.common.agent_utils import get_patched_logger, ClipboardHelper

logger = get_patched_logger(logging.getLogger(__name__))


class PromptInput(TextArea):
    """Custom TextArea that handles submission on Enter."""
    
    # Explicitly remove bindings to avoid conflicts, we handle keys manually
    BINDINGS = []

    class Submitted(Message):
        """Posted when the input is submitted."""
        def __init__(self, value: str):
            self.value = value
            super().__init__()

    async def _on_key(self, event: Key) -> None:
        """Handle key events explicitly."""

        # Handle Enter for submission
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self.text))
            return

        # Handle Shift+Enter, Alt+Enter, Ctrl+Enter, Ctrl+J for newline
        # Some terminals send 'enter' for shift+enter, so having alternatives is crucial
        if event.key in ["shift+enter", "alt+enter", "ctrl+enter", "ctrl+j"]:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        # Handle Copy (Ctrl+Shift+C, Ctrl+C when text selected, or Alt+C)
        # Note: Ctrl+Shift+C may be intercepted by terminal, so Alt+C is fallback
        if event.key in ["ctrl+shift+c", "alt+c", "ctrl+y"]:
            event.stop()
            event.prevent_default()
            text = self.selected_text or self.text
            if text and ClipboardHelper.copy(text):
                self.app.notify("Copied to clipboard", timeout=1)
            elif text:
                self.app.notify("Clipboard not available (install xclip)", severity="warning", timeout=2)
            return

        # Handle Paste (Ctrl+Shift+V, or Alt+V)
        if event.key in ["ctrl+shift+v", "alt+v"]:
            event.stop()
            event.prevent_default()
            text = ClipboardHelper.paste()
            if text:
                self.insert(text)
                self.app.notify("Pasted", timeout=1)
            return

        # Allow other keys to propagate to TextArea default handler
        await super()._on_key(event)


# ClipboardHelper class removed - using shared one from agent_utils


class PromptPanel(Vertical):
    """
    Static prompt input panel at bottom of TUI.

    Features:
    - Command input with history
    - Question/answer prompts
    - Mode indicator (input/waiting)
    - Tab completion support (future)
    """

    DEFAULT_CSS = """
    PromptPanel {
        height: auto;
        max-height: 8;
        border: solid $accent;
        padding: 0 1;
    }

    PromptPanel > #prompt-label {
        height: 1;
        padding: 0 1;
    }

    PromptPanel > PromptInput {
        height: 1fr;
        min-height: 3;
        border: none;
    }

    PromptPanel > #prompt-hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    class PromptSubmitted(Message):
        """Message sent when user submits input."""
        def __init__(self, value: str, prompt_id: Optional[str] = None):
            self.value = value
            self.prompt_id = prompt_id
            super().__init__()

    class PromptCancelled(Message):
        """Message sent when user cancels input."""
        def __init__(self, prompt_id: Optional[str] = None):
            self.prompt_id = prompt_id
            super().__init__()

    BINDINGS = [
        Binding("up", "history_prev", "Previous", show=False),
        Binding("down", "history_next", "Next", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+shift+c", "copy_input", "Copy", show=False),
        Binding("ctrl+shift+v", "paste_input", "Paste", show=False),
    ]

    def __init__(
        self,
        *,
        default_prompt: str = "Enter your request:",
        placeholder: str = "Type here...",
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        """
        Initialize prompt panel.

        Args:
            default_prompt: Default prompt label
            placeholder: Input placeholder text
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)

        self._default_prompt = default_prompt
        self._placeholder = placeholder
        self._history: List[str] = []
        self._history_index = -1
        self._current_prompt_id: Optional[str] = None
        self._waiting = False
        self._on_submit: Optional[Callable[[str], Any]] = None

    def compose(self):
        """Compose the prompt panel widgets."""
        yield Static(self._default_prompt, id="prompt-label")
        yield PromptInput(id="prompt-input")
        yield Static("Ctrl+J=Newline | Enter=Submit | Alt+C=Copy | Alt+V=Paste", id="prompt-hint")

    @property
    def input_widget(self) -> PromptInput:
        """Get the input widget."""
        return self.query_one("#prompt-input", PromptInput)

    @property
    def label_widget(self) -> Static:
        """Get the label widget."""
        return self.query_one("#prompt-label", Static)

    @property
    def hint_widget(self) -> Static:
        """Get the hint widget."""
        return self.query_one("#prompt-hint", Static)

    def set_prompt(
        self,
        prompt: str,
        hint: Optional[str] = None,
        prompt_id: Optional[str] = None,
        default_value: str = ""
    ) -> None:
        """
        Set the prompt text and optionally a hint.

        Args:
            prompt: Prompt label text
            hint: Optional hint text
            prompt_id: Optional ID for this prompt
            default_value: Default input value
        """
        self.label_widget.update(prompt)
        self._current_prompt_id = prompt_id

        if hint:
            self.hint_widget.update(hint)

        self.input_widget.text = default_value
        self.input_widget.focus()

    def ask_question(
        self,
        question: str,
        options: Optional[List[str]] = None,
        prompt_id: Optional[str] = None,
        on_submit: Optional[Callable[[str], Any]] = None
    ) -> None:
        """
        Ask the user a question.

        Args:
            question: Question to ask
            options: Optional list of valid options
            prompt_id: Optional ID for tracking
            on_submit: Optional callback for when answered
        """
        # CRITICAL: Clear waiting state and enable input for question
        self._waiting = False
        self.input_widget.disabled = False

        self._current_prompt_id = prompt_id
        self._on_submit = on_submit

        if options:
            options_text = " | ".join(options)
            self.label_widget.update(f"❓ {question}")
            self.hint_widget.update(f"Options: {options_text}")
        else:
            self.label_widget.update(f"❓ {question}")
            self.hint_widget.update("Press Enter to submit")

        self.input_widget.text = ""
        self.input_widget.focus()

    def set_waiting(self, message: str = "Processing...") -> None:
        """
        Set the panel to waiting mode.

        Args:
            message: Message to display while waiting
        """
        self._waiting = True
        self.label_widget.update(f"⏳ {message}")
        self.hint_widget.update("Please wait... (Ctrl+C to interrupt)")
        # Instead, we check self._waiting in _submit_input to ignore input
        # self.input_widget.placeholder = "Processing..." # TextArea doesn't have placeholder prompt property the same way

    def clear_waiting(self) -> None:
        """Clear waiting mode and restore input."""
        self._waiting = False
        self.label_widget.update(self._default_prompt)
        self.hint_widget.update("Enter=Submit | Esc=Cancel | Ctrl+C/V=Copy/Paste")
        # self.input_widget.placeholder = self._placeholder
        self.input_widget.focus()

    def reset(self) -> None:
        """Reset prompt to default state."""
        self._current_prompt_id = None
        self._on_submit = None
        self._waiting = False
        self.label_widget.update(self._default_prompt)
        self.hint_widget.update("Press Enter to submit, Escape to cancel")
        self.input_widget.text = ""
        # self.input_widget.placeholder = self._placeholder

    def on_key(self, event: Key) -> None:
        """Handle key events."""
        # Enter handling is now done via PromptInput bindings and Submitted message
        
        # Clear Input (Ctrl+L)
        if event.key == "ctrl+l":
            self.action_clear_input()
            event.prevent_default()
            event.stop()
            return

        # History Navigation
        # Check explicit bindings first
        is_history_prev = event.key in ["alt+up", "ctrl+up"]
        is_history_next = event.key in ["alt+down", "ctrl+down"]
        
        # Check implicit bindings (cursor at boundary)
        if not (is_history_prev or is_history_next) and event.key in ["up", "down"]:
             cursor_row, _ = self.input_widget.cursor_location
             if event.key == "up" and cursor_row == 0:
                 is_history_prev = True
             elif event.key == "down":
                 # Check if at last row
                 # Textual TextArea has a document property
                 if hasattr(self.input_widget, 'document'):
                     last_row = self.input_widget.document.line_count - 1
                     if cursor_row >= last_row:
                         is_history_next = True

        if is_history_prev:
            self.action_history_prev()
            event.prevent_default()
            event.stop()
        elif is_history_next:
            self.action_history_next()
            event.prevent_default()
            event.stop()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle submission from custom input widget."""
        event.stop()
        self._submit_input()

    def _submit_input(self) -> None:
        """Handle input submission manually."""
        if self._waiting:
            return

        value = self.input_widget.text.strip()
        
        # Don't submit empty unless waiting for simple ack
        if not value:
            return

        # Add to history if non-empty
        if value and (not self._history or self._history[-1] != value):
            self._history.append(value)
            self._history_index = len(self._history)

        # Call callback if set
        if self._on_submit:
            self._on_submit(value)
            self._on_submit = None

        # Post message
        self.post_message(self.PromptSubmitted(value, self._current_prompt_id))

        # Clear input
        self.input_widget.text = ""

    def action_history_prev(self) -> None:
        """Go to previous history item."""
        if not self._history:
            return

        if self._history_index > 0:
            self._history_index -= 1
            self.input_widget.text = self._history[self._history_index]
            self.input_widget.cursor_location = (len(self._history[self._history_index]), 0) # Basic cursor placement, TextArea uses (row, col)

    def action_history_next(self) -> None:
        """Go to next history item."""
        if not self._history:
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.input_widget.text = self._history[self._history_index]
        else:
            self._history_index = len(self._history)
            self.input_widget.text = ""

    def action_cancel(self) -> None:
        """Cancel current prompt."""
        if self._waiting:
            return

        self.input_widget.text = ""
        self.post_message(self.PromptCancelled(self._current_prompt_id))

    def get_history(self) -> List[str]:
        """Get command history."""
        return self._history.copy()

    def clear_history(self) -> None:
        """Clear command history."""
        self._history.clear()
        self._history_index = -1

    def action_clear_input(self) -> None:
        """Clear the input area."""
        self.input_widget.text = ""
        self.app.notify("Input cleared")

    async def action_copy_input(self) -> None:
        """Copy input content to clipboard (Ctrl+Shift+C)."""
        # TextArea has built-in copy, but we can enhance it or rely on it.
        # This action might be redundant if we map standard keys.
        text = self.input_widget.selected_text or self.input_widget.text
        if text:
            if ClipboardHelper.copy(text):
                # Brief visual feedback - could flash the input or show notification
                self.app.notify("Copied to clipboard", timeout=1)
            else:
                self.app.notify("Clipboard not available (install xclip)", severity="warning", timeout=2)
        else:
            self.app.notify("Nothing to copy", timeout=1)

    def action_paste_input(self) -> None:
        """Paste from clipboard into input (Ctrl+Shift+V)."""
        text = ClipboardHelper.paste()
        if text:
            # Insert at cursor position or replace selection
            # self.input_widget.insert(text) - TextArea has insert method
            self.input_widget.insert(text)
            # clean_text is not needed for multi-line TextArea
            self.app.notify("Pasted from clipboard", timeout=1)
        else:
            self.app.notify("Clipboard empty or not available", severity="warning", timeout=2)
