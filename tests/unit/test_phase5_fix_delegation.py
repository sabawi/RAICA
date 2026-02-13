
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
import asyncio

# Assuming standard imports
from agents.coding_agent.autonomous.debug_controller import AutonomousDebugController, DebugUnit

class TestFixDelegation(unittest.IsolatedAsyncioTestCase):
    async def test_apply_fix_and_lint_delegates(self):
        """Verify _apply_fix_and_lint calls _apply_unit_fix."""
        
        # Mock dependencies
        mock_llm = MagicMock()
        mock_project_dir = Path("/tmp/mock_project")
        mock_tool_client = MagicMock()
        
        # Instantiate controller
        controller = AutonomousDebugController(
            mock_llm, 
            mock_project_dir, 
            tool_client=mock_tool_client,
            output_callback=MagicMock()
        )
        # Mock session
        controller._session = MagicMock()
        controller._session.bug_description = "Test bug"
        controller._session.error_trace = None
        controller._session.bug_test_path = "/tmp/test.py"
        
        # Mock methods to avoid real IO
        controller.output = MagicMock()
        controller.context = MagicMock()
        controller.linter_service = MagicMock()
        
        # Mock _apply_unit_fix to track call
        controller._apply_unit_fix = AsyncMock(return_value={
            'success': True, 
            'files_modified': ['file1.py'], 
            'description': 'Delegated fix'
        })
        
        # Setup test data
        analysis = {
            'affected_files': ['file1.py'],
            'hypothesis': 'Test hypothesis'
        }
        
        # Create dummy file to avoid read errors if method checks existence
        with patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data="content")):
            
            # RUN
            result = await controller._apply_fix_and_lint(analysis)
            
            # VERIFY
            self.assertTrue(result['success'])
            self.assertEqual(result['description'], 'Delegated fix')
            
            # Check if _apply_unit_fix was called
            controller._apply_unit_fix.assert_called_once()
            
            # Check arguments
            args, _ = controller._apply_unit_fix.call_args
            unit = args[0]
            self.assertIsInstance(unit, DebugUnit)
            self.assertEqual(unit.unit_id, "main_fix")
            self.assertEqual(unit.affected_files, ['file1.py'])

if __name__ == "__main__":
    unittest.main()
