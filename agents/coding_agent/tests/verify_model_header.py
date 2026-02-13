
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Mock environment
sys.path.append('/home/sabawi/Development/RAICA/agents/coding_agent')
# We need to mock yaml load if config missing, but let's try import first
try:
    from llm_client import CodeGenLLMClient, LLMResponse
except ImportError:
    print("Could not import llm_client")
    sys.exit(1)

def test_header():
    print("Testing Model Header Integration...")
    
    # Mock config loading to avoid file dependency issues during test
    CodeGenLLMClient._load_config = MagicMock(return_value={
        'providers': {'dummy': {'model': 'test-model'}}, 
        'fallback': {'enabled': True, 'order': ['dummy']}
    })
    
    client = CodeGenLLMClient(config_path=Path("dummy.yaml"))
    
    client._provider_dispatch['dummy'] = lambda c, p, cfg, **kw: LLMResponse(
        content="Hello World this is a sufficiently long response to pass the validation check which requires at least 50 characters for code context or 30 for others.",
        provider='dummy',
        model='test-v1',
        success=True
    )
    
    # Bypass client validation
    client._get_provider_client = MagicMock(return_value="mock_client")
    
    # Call generate
    response = client.generate("Test")
    
    print("-" * 20)
    print(response.content)
    print("-" * 20)
    
    expected_header = "> **dummy/test-v1**\n\n"
    if response.content.startswith(expected_header):
        print("✅ Success: Header is present.")
    else:
        print(f"❌ Failure: Header missing. Got: {response.content[:20]}...")

if __name__ == "__main__":
    test_header()
