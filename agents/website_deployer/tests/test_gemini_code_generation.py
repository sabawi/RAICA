#!/usr/bin/env python3
"""
Test Gemini 2.5 Pro with realistic code generation prompt.

This tests whether Gemini can handle actual code generation workloads,
not just simple "hello world" prompts.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from stages.llm_client import LLMClient

def test_gemini_code_generation():
    """Test Gemini with a realistic code generation prompt."""

    # Initialize LLM client (will use config from llm_config.yaml)
    llm = LLMClient()

    # Realistic code generation prompt (similar to what intelligent generator uses)
    prompt = """Generate a Python FastAPI endpoint for user registration.

Requirements:
- POST endpoint at /api/auth/register
- Accept JSON body with: email, password, username
- Validate email format
- Hash password with bcrypt
- Return 201 on success with user_id
- Return 400 on validation errors
- Include proper error handling

Generate ONLY the Python code, no explanations."""

    print("=" * 60)
    print("TESTING GEMINI 2.5 PRO WITH CODE GENERATION PROMPT")
    print("=" * 60)
    print(f"\nPrompt: {prompt[:100]}...")
    print("\nCalling Gemini API...\n")

    # Test with explicit provider
    response = llm.generate(prompt, provider='gemini')

    print("=" * 60)
    print("RESULT")
    print("=" * 60)
    print(f"Provider: {response.provider}")
    print(f"Model: {response.model}")
    print(f"Success: {response.success}")

    if response.success:
        print(f"\n✅ GEMINI WORKING - Generated {len(response.content)} characters")
        print("\nFirst 500 characters of response:")
        print("-" * 60)
        print(response.content[:500])
        print("-" * 60)
    else:
        print(f"\n❌ GEMINI FAILED: {response.error}")
        print("\nThis means fallback to Ollama will be used for code generation.")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_gemini_code_generation()
