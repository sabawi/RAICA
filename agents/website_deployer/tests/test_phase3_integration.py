#!/usr/bin/env python3
"""
Test Phase 3 - LLMCodeGenerator Refactoring
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stages.intelligent_generators.tech_stack_config import TechStackConfig
from stages.intelligent_generators.llm_code_generator import LLMCodeGenerator

def test_role_prompt_retrieval():
    """Test that role prompts are retrieved from TechStackConfig."""
    print("=" * 60)
    print("TEST 1: Role Prompt Retrieval")
    print("=" * 60)
    
    # Test Python/FastAPI
    tech_config_py = TechStackConfig("python", "fastapi")
    generator_py = LLMCodeGenerator(tech_config=tech_config_py)
    
    role_prompt = generator_py._get_role_system_prompt("model")
    print(f"✓ Python/FastAPI model role prompt: {len(role_prompt)} chars")
    assert "SQLAlchemy" in role_prompt, "Should mention SQLAlchemy for Python"
    assert "database architect" in role_prompt.lower(), "Should mention database architect role"
    
    # Test PHP/Laravel
    tech_config_php = TechStackConfig("php", "laravel")
    generator_php = LLMCodeGenerator(tech_config=tech_config_php)
    
    role_prompt_php = generator_php._get_role_system_prompt("model")
    print(f"✓ PHP/Laravel model role prompt: {len(role_prompt_php)} chars")
    assert "Eloquent" in role_prompt_php, "Should mention Eloquent for PHP"
    assert "database architect" in role_prompt_php.lower(), "Should mention database architect role"
    
    # Test Node.js/Express
    tech_config_node = TechStackConfig("nodejs", "express")
    generator_node = LLMCodeGenerator(tech_config=tech_config_node)
    
    role_prompt_node = generator_node._get_role_system_prompt("model")
    print(f"✓ Node.js/Express model role prompt: {len(role_prompt_node)} chars")
    assert "Sequelize" in role_prompt_node, "Should mention Sequelize for Node.js"
    
    print()

def test_language_instructions():
    """Test that language instructions are tech-specific."""
    print("=" * 60)
    print("TEST 2: Language-Specific Instructions")
    print("=" * 60)
    
    # Test Python
    tech_config_py = TechStackConfig("python", "fastapi")
    generator_py = LLMCodeGenerator(tech_config=tech_config_py)
    
    instructions_py = generator_py._get_language_instructions("model")
    print(f"✓ Python instructions: {len(instructions_py)} chars")
    assert "Python Standards" in instructions_py, "Should have Python standards"
    assert "type hints" in instructions_py.lower(), "Should mention type hints"
    
    # Test PHP
    tech_config_php = TechStackConfig("php", "laravel")
    generator_php = LLMCodeGenerator(tech_config=tech_config_php)
    
    instructions_php = generator_php._get_language_instructions("model")
    print(f"✓ PHP instructions: {len(instructions_php)} chars")
    assert "PHP Standards" in instructions_php, "Should have PHP standards"
    assert "PHPDoc" in instructions_php, "Should mention PHPDoc"
    
    # Test Node.js
    tech_config_node = TechStackConfig("nodejs", "express")
    generator_node = LLMCodeGenerator(tech_config=tech_config_node)
    
    instructions_node = generator_node._get_language_instructions("model")
    print(f"✓ Node.js instructions: {len(instructions_node)} chars")
    assert "Node.js" in instructions_node or "JavaScript" in instructions_node, "Should have Node.js/JS standards"
    
    print()

def test_validation_logic():
    """Test that validation logic is tech-aware."""
    print("=" * 60)
    print("TEST 3: Tech-Aware Validation")
    print("=" * 60)
    
    # Test Python validation
    tech_config_py = TechStackConfig("python", "fastapi")
    generator_py = LLMCodeGenerator(tech_config=tech_config_py)
    
    valid_python = "def hello():\n    return 'world'\n"
    is_valid, errors = generator_py._validate_generated_code("model", valid_python)
    print(f"✓ Python validation: valid={is_valid}, errors={len(errors)}")
    assert is_valid, "Valid Python code should pass validation"
    
    # Test PHP validation (currently returns True as placeholder)
    tech_config_php = TechStackConfig("php", "laravel")
    generator_php = LLMCodeGenerator(tech_config=tech_config_php)
    
    php_code = "<?php\nclass User {}\n"
    is_valid_php, errors_php = generator_php._validate_generated_code("model", php_code)
    print(f"✓ PHP validation: valid={is_valid_php}, errors={len(errors_php)}")
    # PHP validation is placeholder, so it should return True
    assert is_valid_php, "PHP validation should pass (placeholder)"
    
    # Test Node.js validation
    tech_config_node = TechStackConfig("nodejs", "express")
    generator_node = LLMCodeGenerator(tech_config=tech_config_node)
    
    js_code = "const user = { name: 'John' };\n"
    is_valid_js, errors_js = generator_node._validate_generated_code("model", js_code)
    print(f"✓ Node.js validation: valid={is_valid_js}, errors={len(errors_js)}")
    
    print()

def test_fallback_behavior():
    """Test fallback behavior when tech_config is not provided."""
    print("=" * 60)
    print("TEST 4: Fallback Behavior")
    print("=" * 60)
    
    # Create generator without tech_config
    generator = LLMCodeGenerator(tech_config=None)
    
    # Should return generic role prompt
    role_prompt = generator._get_role_system_prompt("model")
    print(f"✓ Fallback role prompt: {len(role_prompt)} chars")
    assert "Senior Software Engineer" in role_prompt, "Should use generic role"
    
    # Should return generic instructions
    instructions = generator._get_language_instructions("model")
    print(f"✓ Fallback instructions: {len(instructions)} chars")
    assert "best practices" in instructions.lower(), "Should mention best practices"
    
    # Should default to Python validation
    valid_python = "def hello():\n    return 'world'\n"
    is_valid, errors = generator._validate_generated_code("model", valid_python)
    print(f"✓ Fallback validation: valid={is_valid}")
    assert is_valid, "Should default to Python validation"
    
    print()

def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "PHASE 3 INTEGRATION TEST SUITE" + " " * 18 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    try:
        # Test 1: Role prompt retrieval
        test_role_prompt_retrieval()
        
        # Test 2: Language instructions
        test_language_instructions()
        
        # Test 3: Validation logic
        test_validation_logic()
        
        # Test 4: Fallback behavior
        test_fallback_behavior()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print()
        
    except Exception as e:
        print("=" * 60)
        print("❌ TEST FAILED")
        print("=" * 60)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
