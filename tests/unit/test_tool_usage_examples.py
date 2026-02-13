import unittest
from unittest.mock import MagicMock
from agents.coding_agent.services.tool_calling_client import ToolCallingClient
from agents.coding_agent.services.debug_toolkit import DebugToolkit
from agents.coding_agent.services.tool_usage_examples import TOOL_USAGE_EXAMPLES

class TestToolUsageExamples(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_toolkit = MagicMock(spec=DebugToolkit)
        self.mock_toolkit.get_tool_schema.return_value = [{"name": "test_tool"}]
        self.client = ToolCallingClient(self.mock_llm, self.mock_toolkit)

    def test_examples_in_system_prompt(self):
        """Verify that examples are injected into the system prompt."""
        prompt = self.client._build_system_prompt()
        
        # Check for key phrases from the examples
        self.assertIn("EXAMPLES OF CORRECT TOOL USAGE", prompt)
        self.assertIn("DEPENDENCY CHECK & INSTALL", prompt)
        self.assertIn("LINTING & FIXING", prompt)
        
        # Verify strict JSON formatting is preserved (no f-string errors)
        self.assertIn("tool_calls", prompt)
    
    def test_examples_content(self):
        """Verify the examples module contains valid content."""
        self.assertTrue(isinstance(TOOL_USAGE_EXAMPLES, str))
        self.assertGreater(len(TOOL_USAGE_EXAMPLES), 100)
        self.assertIn("check_lint", TOOL_USAGE_EXAMPLES)
        self.assertIn("create_test", TOOL_USAGE_EXAMPLES)

if __name__ == '__main__':
    unittest.main()
