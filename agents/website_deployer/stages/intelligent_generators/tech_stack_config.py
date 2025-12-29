import yaml
import os
from typing import Dict, List, Any, Optional

class TechStackConfig:
    """
    Configuration manager for technology stacks.
    Loads settings from tech_stack_registry.yaml and prompt_templates.yaml.
    """

    def __init__(self, backend_language: str, backend_framework: str):
        self.backend_language = backend_language.lower()
        self.backend_framework = backend_framework.lower()
        self.config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
        self.registry = self._load_registry()
        self.prompts = self._load_prompts()
        self.tech_key = self._resolve_tech_key()
        self.config = self.registry.get('tech_stacks', {}).get(self.tech_key, {})

    def _load_registry(self) -> Dict[str, Any]:
        """Load tech stack registry."""
        registry_path = os.path.join(self.config_dir, 'tech_stack_registry.yaml')
        try:
            with open(registry_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Fallback for testing or if file missing
            return {"tech_stacks": {}}

    def _load_prompts(self) -> Dict[str, Any]:
        """Load prompt templates."""
        prompts_path = os.path.join(self.config_dir, 'prompt_templates.yaml')
        try:
            with open(prompts_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            return {}

    def _resolve_tech_key(self) -> str:
        """Resolve the tech stack key (e.g., 'python_fastapi') from language and framework."""
        # Simple mapping for now, could be more sophisticated
        if self.backend_language == 'python' and 'fastapi' in self.backend_framework:
            return 'python_fastapi'
        # PHP Fallbacks
        if self.backend_language == 'php':
            if 'laravel' in self.backend_framework:
                return 'php_laravel'
            elif 'apache' in self.backend_framework:
                return 'php_apache'
            else:
                return 'php_plain'

        # Default fallback or try to construct key
        return f"{self.backend_language}_{self.backend_framework}"

    def get_file_extension(self) -> str:
        """Returns .py, .php, .js, .rb, etc."""
        return self.config.get('file_extension', '.txt')

    def get_directory_structure(self) -> List[str]:
        """Returns tech-specific directory structure."""
        return self.config.get('directory_structure', [])

    def get_path(self, component: str) -> str:
        """Get path for a specific component (models, controllers, etc.)."""
        paths = self.config.get('paths', {})
        return paths.get(component, f"app/{component}")

    def get_models_dir(self) -> str:
        return self.get_path('models')

    def get_controllers_dir(self) -> str:
        return self.get_path('controllers')
    
    def get_schemas_dir(self) -> str:
        return self.get_path('schemas')
    
    def get_crud_dir(self) -> str:
        return self.get_path('crud')
    
    def get_config_dir(self) -> str:
        return self.get_path('config')
    
    def get_templates_dir(self) -> str:
        return self.get_path('templates')
    
    def get_static_dir(self) -> str:
        return self.get_path('static')

    def get_dependency_file_name(self) -> str:
        """Returns requirements.txt, composer.json, package.json, etc."""
        return self.config.get('dependency_file', 'requirements.txt')
    
    def get_dependency_manager(self) -> str:
        """Returns pip, composer, npm, etc."""
        return self.config.get('dependency_manager', 'pip')

    def get_prompt_template(self, prompt_type: str) -> str:
        """Returns tech-specific LLM prompt template."""
        # prompt_type e.g., 'model_prompt', 'api_endpoint_prompt'
        type_prompts = self.prompts.get(prompt_type, {})
        return type_prompts.get(self.tech_key, "")
    
    def get_role_prompt(self, file_type: str) -> str:
        """Returns tech-specific role-based system prompt for file type."""
        # file_type e.g., 'model', 'api_endpoint', 'schema', 'crud'
        role_prompts = self.prompts.get('role_prompts', {})
        type_prompts = role_prompts.get(file_type, {})
        return type_prompts.get(self.tech_key, "")

    def get_orm_library(self) -> str:
        """Returns sqlalchemy, eloquent, sequelize, activerecord, etc."""
        return self.config.get('orm', 'sqlalchemy')
    
    def get_validation_library(self) -> str:
        """Returns pydantic, form_requests, express_validator, etc."""
        return self.config.get('validation', 'pydantic')
    
    def get_tech_stack_description(self) -> str:
        """Returns a human readable description of the tech stack."""
        return f"{self.backend_language.capitalize()} with {self.backend_framework.capitalize()}"
