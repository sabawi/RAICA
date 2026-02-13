
import unittest
import asyncio
import shutil
import tempfile
import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from agents.coding_agent.code_debug_agent import CodeDebugAgent

# Mock Response Object
class MockResponse:
    def __init__(self, content):
        self.success = True
        self.content = content
        self.error = None

# Smart mock for LLM
class MockLLM:
    """Smart mock that responds to prompts with specific tool calls or valid JSON."""
    def __init__(self):
        self.primary_provider = "mock"
        self.primary_model = "mock-model"

    # NOTE: The CodeDebugAgent/Controllers use asyncio.to_thread(self.llm_client.generate)
    # So this method must be SYNCHRONOUS (blocking), not async.
    def generate(self, prompt, system_prompt=None, **kwargs):
        # 1. Classification
        if "Classify this request" in prompt:
            return MockResponse('{"classification": "bug", "confidence": 0.9}')
            
        # 2. Decomposition (Debug Controller)
        if "Break down this bug" in prompt:
            return MockResponse('{"units": [{"id": "U1", "description": "Fix bug in calculator", "affected_files": ["calculator.py"], "test_approach": "unit", "dependencies": []}]}')
            
        # 3. Test Generation
        if "Generate a targeted reproduction test" in prompt:
            return MockResponse("""```python
import pytest
from calculator import add
def test_add():
    assert add(1, 2) == 3
```""")

        # 4. Tool Execution (The Core Phase 5 Logic)
        if "Fix the bug in unit 'U1'" in prompt or "Fix the bug in unit 'main_fix'" in prompt:
            # Return a tool call to fix the file
            return MockResponse(json.dumps({
                "tool_calls": [{
                    "tool": "replace_file_content",
                    "args": {
                        "TargetFile": "calculator.py",
                        "TargetContent": "return a - b",
                        "ReplacementContent": "return a + b",
                        "StartLine": 2,
                        "EndLine": 2,
                        "CodeMarkdownLanguage": "python",
                        "Complexity": 1,
                        "Description": "Fix subtraction to addition",
                        "Instruction": "Fix bug",
                        "AllowMultiple": False
                    }
                }]
            }))
            
        # Fallback
        return MockResponse('{"done": true}')

class TestAgentSimulation(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Create temp workspace
        self.test_dir = Path(tempfile.mkdtemp())
        self.project_dir = self.test_dir / "project"
        self.project_dir.mkdir()
        
        # Setup files
        self.calc_file = self.project_dir / "calculator.py"
        self.calc_file.write_text("def add(a, b):\n    return a - b\n") # The bug
        
        # Initialize Git (required by tracking)
        import subprocess
        subprocess.run(["git", "init"], cwd=self.project_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.project_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=self.project_dir, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=self.project_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.project_dir, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    async def test_full_debug_flow(self):
        """Simulate a full fix flow from AgentRunner down to Disk."""
        
        mock_llm = MockLLM()
        agent = CodeDebugAgent(self.project_dir, mock_llm)
        
        # Override output to print to stdout for visibility
        agent._output = lambda msg, type: print(f"[{type}] {msg}")
        
        # Run the agent
        print("\n--- Starting Simulation ---")
        # Avoid "add" to prevent enhancement classification
        result = await agent.run("The calculator plus function subtracts. Error detected.")
        print("\n--- Simulation Complete ---")
        
        # VERIFICATION
        
        # 1. Check if file was actually modified on disk
        content = self.calc_file.read_text()
        print(f"Final file content:\n{content}")
        self.assertIn("return a + b", content)
        self.assertNotIn("return a - b", content)
        
        # 2. Check result object
        # Note: CodeDebugAgent.run returns DebugResult or EnhancementResult
        # Both assume success boolean
        self.assertTrue(result.success)

if __name__ == "__main__":
    unittest.main()
