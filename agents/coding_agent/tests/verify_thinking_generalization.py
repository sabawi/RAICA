
import sys
from unittest.mock import MagicMock
from pathlib import Path
import time

# Mock environment
sys.path.append('/home/sabawi/Development/RAICA/agents/coding_agent')
from llm_client import CodeGenLLMClient, LLMResponse

def test_thinking_generalization():
    print("Testing Thinking Mode Generalization...")
    
    # Mock config
    CodeGenLLMClient._load_config = MagicMock(return_value={
        'providers': {
            'ollama': {'model': 'deepseek-r1'},
            'qwen': {'model': 'qwen-max'}
        }
    })
    
    client = CodeGenLLMClient(config_path=Path("dummy.yaml"))
    
    # Bypass validation
    client._get_provider_client = MagicMock(return_value="mock_client")
    
    # 1. Test Ollama with 'thinking' field
    print("\n1. Testing Ollama (DeepSeek style)...")
    
    # Mock _call_ollama internals? No, we want to test _call_ollama logic itself.
    # So we need to mock the ollama.Client.chat return value.
    
    mock_ollama_client = MagicMock()
    mock_ollama_client.chat.return_value = {
        'message': {
            'content': "Final Answer",
            'thinking': "I am thinking deeply..."
        }
    }
    client._clients['ollama'] = mock_ollama_client
    
    # We need to manually call _call_ollama to test the logic, or mock the dispatch
    # Let's call _call_ollama directly to verify the formatting logic
    response = client._call_ollama(
        mock_ollama_client, 
        "prompt", 
        {'model': 'deepseek-r1'}
    )
    
    print("-" * 20)
    print(response.content)
    print("-" * 20)
    
    if "<details>" in response.content and "I am thinking deeply..." in response.content:
        print("✅ Ollama thinking captured correctly")
    else:
        print("❌ Ollama thinking missing")

    if "Thought for" in response.content:
        print("✅ Timer present")
    else:
        print("❌ Timer missing")

    # 2. Test Qwen with 'reasoning_content'
    print("\n2. Testing Qwen...")
    
    mock_qwen_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Qwen Answer"
    mock_message.reasoning_content = "Qwen Reasoning..."
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]
    
    mock_qwen_client.chat.completions.create.return_value = mock_response
    client._clients['qwen'] = mock_qwen_client
    
    response = client._call_qwen(
        mock_qwen_client,
        "prompt",
        {'model': 'qwen-max'}
    )
    
    print("-" * 20)
    print(response.content)
    print("-" * 20)
    
    if "<details>" in response.content and "Qwen Reasoning..." in response.content:
        print("✅ Qwen thinking captured correctly")
    else:
        print("❌ Qwen thinking missing")

if __name__ == "__main__":
    test_thinking_generalization()
