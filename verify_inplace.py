
import shutil
from pathlib import Path
from agents.coding_agent.cli_coding_agent import CLICodingAgent

TEST_DIR = Path("test_inplace_debug")

# Clean up previous run
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
TEST_DIR.mkdir()

print("Test 1: Standard initialization (should create subdirectory)")
agent1 = CLICodingAgent(output_dir=str(TEST_DIR), verbose=True)
print(f"Agent 1 Project Dir: {agent1.project_dir}")
if agent1.project_dir == TEST_DIR:
    print("FAILED: Standard init used root dir")
else:
    print("PASSED: Standard init created subdir")

print("\nTest 2: In-place initialization (should use root directory)")
agent2 = CLICodingAgent(output_dir=str(TEST_DIR), use_existing_project=True, verbose=True)
print(f"Agent 2 Project Dir: {agent2.project_dir}")
if agent2.project_dir == TEST_DIR:
    print("PASSED: In-place init used root dir")
else:
    print(f"FAILED: In-place init created subdir: {agent2.project_dir}")

# Clean up
shutil.rmtree(TEST_DIR)
