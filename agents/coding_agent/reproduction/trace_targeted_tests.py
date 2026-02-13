#!/usr/bin/env python3
"""
Trace what identify_relevant_tests returns and how run_targeted_tests executes.
"""

import asyncio
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

from coding_agent.autonomous.bug_test_generator import BugTestGenerator

async def main():
    test_project = script_dir / "buggy_calculator"

    print("=" * 60)
    print("Tracing identify_relevant_tests and run_targeted_tests")
    print("=" * 60)
    print(f"Project Dir: {test_project}")
    print()

    # Create a mock LLM client (we don't need it for this test)
    class MockLLMClient:
        pass

    generator = BugTestGenerator(MockLLMClient(), test_project)

    # Test identify_relevant_tests
    modified_files = ["calculator.py"]
    print(f"Modified files: {modified_files}")

    relevant_tests = generator.identify_relevant_tests(modified_files)

    print(f"\nidentify_relevant_tests returned {len(relevant_tests)} tests:")
    for t in relevant_tests:
        print(f"  - {t}")
        print(f"    Type: {type(t)}")
        print(f"    Exists: {t.exists()}")
        print(f"    As string: {str(t)}")
    print()

    # Now let's see what command would be run
    print("Command that would be run by run_targeted_tests:")
    cmd = ["python", "-m", "pytest", "-v", "--tb=short"]
    cmd.extend([str(p) for p in relevant_tests])
    print(f"  {' '.join(cmd)}")
    print(f"  cwd: {test_project}")
    print()

    # Actually run the targeted tests
    print("Running targeted tests now...")
    result = await generator.run_targeted_tests(relevant_tests)

    print(f"\nResult:")
    print(f"  Passed: {result.passed}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    if result.error:
        print(f"  Error: {result.error[:500]}")
    if result.output:
        print(f"  Output (first 1000 chars):\n{result.output[:1000]}")

if __name__ == "__main__":
    asyncio.run(main())
