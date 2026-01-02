"""
TUI Module - Interactive Terminal User Interface
=================================================

Provides a Rich + Textual based interactive interface for the CLI Coding Agent.

Components:
- app.py: Main Textual application with split-pane layout
- agent_runner.py: Interactive agent runner (main entry point)
- widgets/: Custom widgets (output_panel, prompt_panel, status_bar)

Usage:
    from agents.coding_agent.tui import run_interactive_agent
    run_interactive_agent()

Or from command line:
    raica
"""

from .app import CodingAgentApp
from .agent_runner import InteractiveAgentApp, run_interactive_agent

__all__ = ['CodingAgentApp', 'InteractiveAgentApp', 'run_interactive_agent']
