import unittest
from unittest.mock import MagicMock, AsyncMock
from agents.coding_agent.services.guidance_planner import GuidancePlanner

class MockLLMResponse:
    def __init__(self, content):
        self.content = content

class TestPhaseTransition(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.planner = GuidancePlanner(self.mock_llm)

    async def test_validate_proceed(self):
        """Test validation when we can proceed."""
        # Mock LLM response
        response = MockLLMResponse(
            '```json\n{"can_proceed": true, "reason": "Root cause found"}\n```'
        )
        # Configure generate to be an AsyncMock that returns the response
        self.mock_llm.generate = AsyncMock(return_value=response)
        
        result = await self.planner.validate_phase_transition("Root cause identified in line 42")
        
        self.assertTrue(result['can_proceed'])
        self.assertEqual(result['reason'], "Root cause found")
        
        # Verify prompt contained context
        args, kwargs = self.mock_llm.generate.call_args
        self.assertIn("Root cause identified in line 42", kwargs['prompt'])

    async def test_validate_cannot_proceed(self):
        """Test validation when we cannot proceed."""
        response = MockLLMResponse(
            '{"can_proceed": false, "reason": "Need more info", "missing_info": "Check utils.py"}'
        )
        self.mock_llm.generate = AsyncMock(return_value=response)
        
        result = await self.planner.validate_phase_transition("Still investigating")
        
        self.assertFalse(result['can_proceed'])
        self.assertEqual(result['missing_info'], "Check utils.py")

    async def test_invalid_json_handling(self):
        """Test handling of invalid JSON from LLM."""
        response = MockLLMResponse(
            "I think we can proceed but here is no json"
        )
        self.mock_llm.generate = AsyncMock(return_value=response)
        
        result = await self.planner.validate_phase_transition("Context")
        
        self.assertFalse(result['can_proceed'])
        self.assertIn("Failed to parse", result['reason'])

if __name__ == '__main__':
    unittest.main()
