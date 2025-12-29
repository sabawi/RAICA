
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add agent directory to path
sys.path.append('/home/sabawi/Development/flaskserver/agents/coding_agent')

from llm_client import CodeGenLLMClient, LLMResponse

class TestAutoContinuation(unittest.TestCase):
    def setUp(self):
        # Mock _load_config to avoid file access
        with patch.object(CodeGenLLMClient, '_load_config') as mock_load:
            mock_load.return_value = {
                'providers': {
                    'test_provider': {
                        'model': 'test_model',
                        'api_key': 'test_key'
                    }
                },
                'fallback': {'enabled': False}
            }
            self.client = CodeGenLLMClient(provider_override="test_provider")

    def test_continuation_logic(self):
        # Mock _get_provider_client to avoid "Unsupported provider" error
        with patch.object(self.client, '_get_provider_client') as mock_get_client, \
             patch.object(self.client, '_call_provider') as mock_call:
            
            mock_get_client.return_value = MagicMock()
            
            # Setup sequence of responses:
            # 1. Truncated response with marker (to trigger detection)
            # 2. Final response
            
            part1 = "def hello():\n    print('Start')\n    # ...[truncated]"
            part2 = "\n    print('End')\n    return True"
            
            response1 = LLMResponse(
                content=part1,
                success=True,
                error=None,
                provider="test_provider",
                model="test_model"
            )
            
            response2 = LLMResponse(
                content=part2,
                success=True,
                error=None,
                provider="test_provider",
                model="test_model"
            )
            
            mock_call.side_effect = [response1, response2]
            
            final_response = self.client.generate("Write hello function", provider="test_provider")
            
            # Behavior after fix:
            # 1. generate() gets response1.
            # 2. _validate_response detected truncation.
            # 3. Code STRIPS the marker from part1.
            # 4. Appends part2.
            
            clean_part1 = part1.replace("...[truncated]", "")
            expected_content = clean_part1 + part2
            
            if final_response.content != expected_content:
                print(f"FAILED: Content mismatch.\nExpected: '{expected_content}'\nGot: '{final_response.content}'")
            
            self.assertEqual(final_response.content, expected_content)
            self.assertEqual(mock_call.call_count, 2)
            print("✅ Auto-continuation verified successfully")
