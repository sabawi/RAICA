import sys
import os

# Add the parent directory to sys.path to allow importing stages
sys.path.append('/home/sabawi/Development/flaskserver/agents/website_deployer')

from stages.intelligent_generators.tech_stack_config import TechStackConfig

def test_tech_stack_config():
    print("Testing TechStackConfig...")

    # Test Python/FastAPI
    print("\n--- Testing Python/FastAPI ---")
    config = TechStackConfig('python', 'fastapi')
    print(f"Tech Key: {config.tech_key}")
    print(f"Extension: {config.get_file_extension()}")
    print(f"Dependency File: {config.get_dependency_file_name()}")
    print(f"ORM: {config.get_orm_library()}")
    
    assert config.get_file_extension() == '.py'
    assert config.get_dependency_file_name() == 'requirements.txt'
    assert config.get_orm_library() == 'sqlalchemy'
    print("✅ Python/FastAPI passed")

    # Test PHP/Laravel
    print("\n--- Testing PHP/Laravel ---")
    config = TechStackConfig('php', 'laravel')
    print(f"Tech Key: {config.tech_key}")
    print(f"Extension: {config.get_file_extension()}")
    print(f"Dependency File: {config.get_dependency_file_name()}")
    print(f"ORM: {config.get_orm_library()}")

    assert config.get_file_extension() == '.php'
    assert config.get_dependency_file_name() == 'composer.json'
    assert config.get_orm_library() == 'eloquent'
    print("✅ PHP/Laravel passed")

    # Test Node.js/Express
    print("\n--- Testing Node.js/Express ---")
    config = TechStackConfig('nodejs', 'express')
    print(f"Tech Key: {config.tech_key}")
    print(f"Extension: {config.get_file_extension()}")
    print(f"Dependency File: {config.get_dependency_file_name()}")
    print(f"ORM: {config.get_orm_library()}")

    assert config.get_file_extension() == '.js'
    assert config.get_dependency_file_name() == 'package.json'
    assert config.get_orm_library() == 'sequelize'
    print("✅ Node.js/Express passed")

    # Test Prompt Loading
    print("\n--- Testing Prompt Loading ---")
    config = TechStackConfig('python', 'fastapi')
    prompt = config.get_prompt_template('model_prompt')
    print(f"Model Prompt Preview: {prompt[:50]}...")
    assert "Generate SQLAlchemy model" in prompt
    print("✅ Prompt loading passed")

if __name__ == "__main__":
    test_tech_stack_config()
