import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from agents.coding_agent.autonomous.debug_controller import AutonomousDebugController, DebugUnit
from agents.coding_agent.services.tool_calling_client import ToolCallingClient, ExecutionResult
from agents.coding_agent.services.debug_toolkit import DebugToolkit

class TestPhase5Integration(unittest.IsolatedAsyncioTestCase):
    async def test_apply_unit_fix_uses_tool_client(self):
        # Setup Mocks
        mock_llm = MagicMock()
        mock_project_dir = Path("/tmp/mock_project")
        mock_tool_client = AsyncMock(spec=ToolCallingClient)
        mock_toolkit = MagicMock(spec=DebugToolkit)
        mock_git_tracker = MagicMock()
        mock_git_tracker.get_dirty_files.return_value = []
        
        # Configure tool client to return success
        mock_tool_client.execute_and_continue.return_value = ExecutionResult(
            success=True,
            results=[],
            errors=[]
        )
        
        # Initialize Controller
        controller = AutonomousDebugController(
            llm_client=mock_llm,
            project_dir=mock_project_dir,
            tool_client=mock_tool_client,
            toolkit=mock_toolkit
        )
        # Inject mock git tracker directly
        controller.git_tracker = mock_git_tracker
        
        # Setup Test Data
        unit = DebugUnit(
            unit_id="U1",
            description="Fix bug in calculation",
            affected_files=["main.py"],
            test_approach="unit_test"
        )
        file_contents = {"main.py": "def add(a, b): return a - b"}
        test_code = "assert add(1, 2) == 3"
        
        # Execute
        result = await controller._apply_unit_fix(unit, file_contents, test_code)
        
        # Verify
        self.assertTrue(mock_tool_client.execute_and_continue.called)
        args, kwargs = mock_tool_client.execute_and_continue.call_args
        
        # Check instruction contents
        instruction = kwargs.get('instruction') or args[0]
        self.assertIn("Fix the bug in unit 'U1'", instruction)
        self.assertIn("edit_file", instruction)
        self.assertIn(test_code, instruction)
        
        # Check context
        context = kwargs.get('context', '')
        self.assertIn("CURRENT CODE", context)
        self.assertIn("def add(a, b)", context)

    async def test_apply_unit_fix_detects_modifications(self):
        # Setup Mocks
        mock_llm = MagicMock()
        mock_project_dir = Path("/tmp/mock_project")
        mock_tool_client = AsyncMock(spec=ToolCallingClient)
        mock_toolkit = MagicMock(spec=DebugToolkit)
        mock_git_tracker = MagicMock()
        
        # Mock git behavior: initially clean, then dirty after tool execution
        mock_git_tracker.get_dirty_files.side_effect = [[], ["main.py"]] 
        
        mock_tool_client.execute_and_continue.return_value = ExecutionResult(
            success=True,
            results=[],
            errors=[]
        )
        
        controller = AutonomousDebugController(
            llm_client=mock_llm,
            project_dir=mock_project_dir,
            tool_client=mock_tool_client,
            toolkit=mock_toolkit
        )
        controller.git_tracker = mock_git_tracker
        
        unit = DebugUnit(unit_id="U1", description="desc", affected_files=["main.py"], test_approach="unit")
        
        # Execute
        result = await controller._apply_unit_fix(unit, {"main.py": "content"}, "test")
        
        # Verify
        self.assertTrue(result['success'])
        self.assertEqual(result['files_modified'], ["main.py"])
        self.assertEqual(result['applied_patches'], 1)

if __name__ == '__main__':
    unittest.main()
