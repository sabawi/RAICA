#!/usr/bin/env python3
"""
RAICA Debug Controller Test Harness
====================================

Runs the AutonomousDebugController against the buggy_calculator test case
to observe and validate the debug loop behavior.

Usage:
    python run_debug_test.py

Output will show each phase of the debug process.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directories to path for imports
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

# Reduce noise from some loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


def output_callback(message: str):
    """Callback to print debug output with formatting."""
    print(f"\033[36m[RAICA]\033[0m {message}")


async def run_debug_test():
    """Run the debug controller against the buggy calculator."""

    print("=" * 70)
    print("RAICA Autonomous Debug Controller - Test Harness")
    print("=" * 70)
    print()

    # Import the debug controller and LLM client
    try:
        from coding_agent.autonomous.debug_controller import AutonomousDebugController
        from coding_agent.llm_client import CodeGenLLMClient
    except ImportError as e:
        print(f"Import error: {e}")
        print("Trying alternative import path...")
        from autonomous.debug_controller import AutonomousDebugController
        from llm_client import CodeGenLLMClient

    # Set up the test project
    test_project = script_dir / "buggy_calculator"

    if not test_project.exists():
        print(f"ERROR: Test project not found at {test_project}")
        return

    print(f"Test Project: {test_project}")
    print()

    # Clean up any previous debug state
    raica_dir = test_project / ".raica"
    if raica_dir.exists():
        import shutil
        print("Cleaning up previous debug state...")
        shutil.rmtree(raica_dir)

    # Initialize LLM client
    print("Initializing LLM client...")
    try:
        llm_client = CodeGenLLMClient()
        print(f"  Primary provider: {llm_client.primary_provider}")
        print(f"  Fallback enabled: {llm_client.fallback_enabled}")
    except Exception as e:
        print(f"ERROR: Failed to initialize LLM client: {e}")
        return

    print()
    print("-" * 70)
    print("Starting Debug Session")
    print("-" * 70)
    print()

    # Initialize the debug controller
    controller = AutonomousDebugController(
        llm_client=llm_client,
        project_dir=test_project,
        output_callback=output_callback,
        max_iterations=5  # Override default of 3
    )

    # Define the bug description (what a user would provide)
    bug_description = """
    The calculator's divide function is returning wrong results.
    When I run the tests with 'python -m pytest tests/ -v', I get:

    FAILED tests/test_calculator.py::TestCalculatorBasic::test_divide_basic
    FAILED tests/test_calculator.py::TestCalculatorBasic::test_divide_decimal

    The test shows: Expected 5, got 20 when dividing 10 by 2.
    It seems like divide is multiplying instead of dividing.
    """

    print(f"Bug Description:\n{bug_description}")
    print()
    print("-" * 70)
    print()

    # Run the debug loop
    try:
        result = await controller.debug_until_fixed(
            bug_description=bug_description,
            error_trace=None,
            resume=False  # Start fresh
        )

        print()
        print("=" * 70)
        print("DEBUG SESSION COMPLETE")
        print("=" * 70)
        print()
        print(f"Outcome: {result.outcome.value}")
        print(f"Iterations: {result.iterations}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Success: {result.success}")
        print()

        if result.success:
            print("Root Cause:", result.root_cause)
            print("Files Modified:", result.files_modified)
            print()
            print("Fix Summary:")
            print(result.fix_summary)
        else:
            print("Blocked Reason:", result.blocked_reason)

        print()

        # Verify final state by running tests
        print("-" * 70)
        print("Post-Fix Test Verification")
        print("-" * 70)

        import subprocess
        test_result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=no"],
            cwd=str(test_project),
            capture_output=True,
            text=True
        )

        print(test_result.stdout)
        if test_result.returncode == 0:
            print("\033[32mALL TESTS PASSED!\033[0m")
        else:
            print(f"\033[31mTESTS STILL FAILING (exit code {test_result.returncode})\033[0m")

    except Exception as e:
        logger.exception("Debug session failed with exception")
        print(f"\033[31mERROR: {e}\033[0m")


if __name__ == "__main__":
    asyncio.run(run_debug_test())
