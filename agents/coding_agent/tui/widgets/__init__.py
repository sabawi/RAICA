"""
TUI Widgets - Custom Textual widgets for the coding agent.

Widgets:
- OutputPanel: Scrollable output panel (top 80%)
- PromptPanel: Static input panel (bottom 20%)
- StatusBar: Phase/iteration/progress display
"""

from .output_panel import OutputPanel
from .prompt_panel import PromptPanel
from .status_bar import StatusBar

__all__ = ['OutputPanel', 'PromptPanel', 'StatusBar']
