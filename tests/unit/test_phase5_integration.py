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
        self.assertIn("Fix bug in calculation", instruction)    # the unit's description (prompt wording changed)
        self.assertIn("edit_file", instruction)
        self.assertIn(test_code, instruction)   # SI-118: the model sees the test it must pass (was dropped)
        
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

    def _controller(self, project_dir, dirty_seq):
        tool_client = AsyncMock(spec=ToolCallingClient)
        tool_client.execute_and_continue.return_value = ExecutionResult(success=True, results=[], errors=[])
        c = AutonomousDebugController(llm_client=MagicMock(), project_dir=Path(project_dir), tool_client=tool_client,
                                      toolkit=MagicMock(spec=DebugToolkit))
        c.git_tracker = MagicMock()
        c.git_tracker.get_dirty_files.side_effect = dirty_seq
        return c, tool_client

    async def test_a_file_dirty_before_the_fix_is_not_counted_as_fixed(self):
        """SI-118: the git fallback took EVERY dirty file. A tree with an unrelated uncommitted change, and an agent
        that changed nothing, read as a successful fix."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'main.py').write_text('def add(a, b): return a - b')
            Path(d, 'notes.txt').write_text('owner was editing this')
            c, _ = self._controller(d, [['notes.txt'], ['notes.txt']])
            unit = DebugUnit(unit_id="U1", description="desc", affected_files=["main.py"], test_approach="unit")
            result = await c._apply_unit_fix(unit, {"main.py": "def add(a, b): return a - b"}, "")
        self.assertFalse(result['success'], result)
        self.assertEqual(result['files_modified'], [])

    async def test_an_edit_to_an_already_dirty_file_is_detected(self):
        """edit_file reports 'Edited <path>: ...', not the write_file pattern, and git status cannot tell a second
        change to a dirty file: the content hash must."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, 'main.py')
            f.write_text('def add(a, b): return a - b')
            c, tool_client = self._controller(d, [['main.py'], ['main.py']])

            async def edit(**kwargs):
                f.write_text('def add(a, b): return a + b')
                return ExecutionResult(success=True, results=[], errors=[])
            tool_client.execute_and_continue.side_effect = edit
            unit = DebugUnit(unit_id="U1", description="desc", affected_files=["main.py"], test_approach="unit")
            result = await c._apply_unit_fix(unit, {"main.py": "def add(a, b): return a - b"}, "")
        self.assertTrue(result['success'], result)
        self.assertEqual(result['files_modified'], ['main.py'])

    async def test_no_test_section_when_there_is_no_test(self):
        """The caller at the plan stage passes test_code="": the prompt must not carry an empty test section."""
        c, tool_client = self._controller('/tmp/si118-none', [[], []])
        unit = DebugUnit(unit_id="U1", description="desc", affected_files=["main.py"], test_approach="unit")
        await c._apply_unit_fix(unit, {"main.py": "x"}, "")
        instruction = tool_client.execute_and_continue.call_args.kwargs['instruction']
        self.assertNotIn("THE TEST THIS FIX MUST PASS", instruction)

if __name__ == '__main__':
    unittest.main()
