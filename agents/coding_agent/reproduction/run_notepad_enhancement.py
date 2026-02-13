#!/usr/bin/env python3
"""
Run RAICA Enhancement Controller on the Notepad project.

Enhancement: Change note's background to notepad yellow with red lines,
use mono-spaced fonts size 12-14 throughout.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directories to path
script_dir = Path(__file__).parent
agent_dir = script_dir.parent
agents_dir = agent_dir.parent
project_root = agents_dir.parent

sys.path.insert(0, str(project_root))
sys.path.insert(0, str(agents_dir))
sys.path.insert(0, str(agent_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)7s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Reduce noise
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


def output_callback(message: str):
    """Callback to print output with formatting."""
    print(f"\033[36m[RAICA]\033[0m {message}")


async def run_enhancement():
    """Run enhancement on the notepad project."""

    print("=" * 70)
    print("RAICA Enhancement Controller - Notepad Styling")
    print("=" * 70)
    print()

    from coding_agent.autonomous.enhancement_controller import AutonomousEnhancementController
    from coding_agent.llm_client import CodeGenLLMClient

    # Target project
    notepad_project = Path.home() / "Development/notepad/journaling_notepad_standalone_application_on_0518"

    if not notepad_project.exists():
        print(f"ERROR: Project not found at {notepad_project}")
        return

    print(f"Project: {notepad_project}")
    print()

    # Initialize LLM client
    print("Initializing LLM client...")
    llm_client = CodeGenLLMClient()
    print(f"  Primary provider: {llm_client.primary_provider}")
    print()

    # Enhancement request
    enhancement_request = """
    Fix and Enhancement Request:

    1. Change the note editor's background to NOTEPAD YELLOW (legal pad yellow color ~#FFFACD or similar)
       with RED HORIZONTAL LINES like ruled paper (red line color ~#CC0000)

    2. Ensure all fonts throughout the application are MONO-SPACED (like Courier New or similar)
       with font sizes of 12px or 14px consistently

    The editor component is in editor.py with a custom paintEvent that draws the background.
    The styles are in styles.qss.

    Make the notepad look like a classic yellow legal pad with red ruled lines.
    """

    print(f"Enhancement Request:\n{enhancement_request}")
    print()
    print("-" * 70)
    print()

    # Initialize controller
    controller = AutonomousEnhancementController(
        llm_client=llm_client,
        project_dir=notepad_project,
        output_callback=output_callback,
        max_iterations=5
    )

    # Run enhancement
    try:
        result = await controller.enhance(
            enhancement_description=enhancement_request,
            resume=False
        )

        print()
        print("=" * 70)
        print("ENHANCEMENT SESSION COMPLETE")
        print("=" * 70)
        print()
        print(f"Outcome: {result.outcome.value}")
        print(f"Iterations: {result.iterations}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Success: {result.success}")
        print()

        if result.success:
            print("Files Modified:", result.files_modified)
            print()
            print("Summary:")
            print(result.fix_summary)
        else:
            print("Blocked Reason:", result.blocked_reason)

    except Exception as e:
        logger.exception("Enhancement session failed")
        print(f"\033[31mERROR: {e}\033[0m")


if __name__ == "__main__":
    asyncio.run(run_enhancement())
