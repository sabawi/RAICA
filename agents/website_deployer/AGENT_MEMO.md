# Website Deployment Agent - Development Memo

**Date:** November 28, 2025
**Author:** Qwen Code Assistant
**Project:** Website Deployment Agent
**Location:** /home/sabawi/Development/flaskserver/agents/website_deployer

## Project Overview

The Website Deployment Agent is an AI-powered system that transforms natural language specifications into fully deployed production websites. It supports multiple technology stacks and uses a 7-stage intelligent generation pipeline.

### Core Capabilities
- Natural language to production website transformation
- Multi-stack support (Python/FastAPI, PHP/Laravel, Node.js/Express, etc.)
- SSH-based deployment to remote servers
- Multi-provider LLM integration with automatic fallback
- Quality-focused generation with intelligent retry mechanisms

### Technology Stacks Supported
1. **Python/FastAPI** - Primary stack with SQLAlchemy ORM
2. **PHP/Laravel** - Complete Laravel implementation with Eloquent ORM
3. **Node.js/Express** - Full Express.js support with Sequelize ORM
4. **PHP/Apache** - Plain PHP with Apache configuration
5. **PHP/Plain** - Basic PHP implementation

## Architecture Overview

### 7-Stage Intelligent Generation Pipeline
1. **Prompt Analysis** - Parse natural language into structured requirements
2. **Requirement Elaboration** - Expand requirements into technical specifications
3. **Workflow Planning** - Create dependency-aware generation workflow
4. **LLM Code Generation** - Generate code files with context awareness
5. **Assembly Coordination** - Assemble project structure for different tech stacks
6. **Consistency Verification** - Validate code integrity across all tech stacks
7. **Deployment** - SSH-based deployment with multi-stack support

### Key Components

#### LLM Integration
- **Primary Provider:** Gemini 2.5 Pro
- **Fallback Order:** gemini → ollama → anthropic → openai → qwen
- **Supported Models:** 
  - Gemini 2.5 Pro (primary)
  - Ollama qwen3-coder:480b-cloud (fallback)
  - Claude 3.5 Sonnet
  - GPT-4o
  - Qwen Max

#### Configuration Files
- `config/llm_config.yaml` - LLM provider settings
- `config/tech_stack_registry.yaml` - Technology stack definitions
- `config/prompt_templates.yaml` - Stack-specific LLM prompts

#### Core Modules
- `stages/intelligent_code_generator.py` - Main orchestrator
- `stages/llm_client.py` - Multi-provider LLM client
- `stages/deployment_orchestrator.py` - SSH deployment system
- `stages/intelligent_generators/` - Generation pipeline stages

## Multi-Stack Implementation Details

### Tech Stack Configuration
Located in `config/tech_stack_registry.yaml`:
- Directory structures and file paths
- File extensions (.py, .php, .js)
- Dependency managers (pip, composer, npm)
- ORMs (SQLAlchemy, Eloquent, Sequelize)
- Entry points and migration tools

### Prompt Templates
Located in `config/prompt_templates.yaml`:
- Stack-specific prompts for models, APIs, schemas, CRUD
- Role-based system prompts for different file types
- Technology-aware guidance for LLM generation

### Generation Pipeline
1. **Prompt Analyzer** - Identifies tech stack from user requirements
2. **Requirement Elaborator** - Creates tech stack-aware specifications
3. **Workflow Planner** - Plans generation with stack-specific files
4. **LLM Code Generator** - Generates code with stack-specific prompts
5. **Assembly Coordinator** - Assembles project with correct structure
6. **Consistency Verifier** - Validates across all tech stacks

### Deployment Modules
- Package installation for different tech stacks
- Database setup (PostgreSQL, SQLite, MySQL)
- Web server configuration (Apache2, Nginx)
- Systemd service creation for different languages

## Key Implementation Patterns

### Technology Stack Resolution
- Tech stack determined from user requirements
- Configuration loaded dynamically from YAML
- Prompt templates selected based on stack
- File extensions and paths resolved per stack

### LLM Prompt Engineering
- Role-based system prompts for expertise context
- Technology-specific generation guidance
- Stack-aware validation and error handling
- Context-aware file generation with dependencies

### Deployment Orchestration
- SSH connection management with multiple auth methods
- Stack-specific package installation commands
- Database configuration per technology
- Web server virtual host setup
- Service management with systemd

## Areas for Enhancement

### Additional Technology Stacks
- Ruby on Rails support
- Java Spring Boot support
- Go/Gin support
- .NET Core support

### Database Support Expansion
- MongoDB integration
- Redis caching layer
- Elasticsearch integration

### Frontend Framework Support
- React component generation
- Vue.js component generation
- Svelte/Angular support

### Advanced Deployment Features
- Docker containerization
- Kubernetes orchestration
- Load balancer configuration
- SSL certificate management

## Development Guidelines

### Adding New Technology Stacks
1. Add entry to `config/tech_stack_registry.yaml`
2. Create prompt templates in `config/prompt_templates.yaml`
3. Update workflow planner for stack-specific files
4. Add deployment modules if needed
5. Test with full pipeline

### LLM Integration Best Practices
- Use role-based prompting for expertise context
- Provide technology-specific examples
- Include validation feedback in prompts
- Use deterministic generation (temperature=0.0)

### Code Generation Quality
- Focus on production-ready code
- Include proper error handling
- Follow framework best practices
- Ensure security considerations

## Testing and Validation

### Automated Testing
- Unit tests for each stage
- Integration tests for full pipeline
- Multi-stack compatibility tests
- Deployment verification tests

### Quality Assurance
- Consistency verification across files
- Dependency validation
- Security scanning
- Performance benchmarking

## Recent Updates

### Qwen Configuration (November 28, 2025)
- Added Qwen provider to `config/llm_config.yaml`
- Configured with DashScope API endpoint
- Set as final fallback in provider order
- Model: qwen-max with 6000 max tokens

### Gemini 2.5 Pro Integration
- Set as primary LLM provider
- Increased max tokens to 32768
- Added safety filter configuration
- Implemented response validation

## Quick Reference Commands

### Running Full Deployment
```bash
python examples/full_deployment_demo.py
```

### SSH Authentication Options
```bash
# Key-based authentication
export DEPLOYMENT_SSH_HOST="192.168.1.100"
export DEPLOYMENT_SSH_USER="deployer"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/deployment_key"

# Password authentication
python examples/full_deployment_demo.py --ssh-host-user "user@192.168.1.100"
```

### LLM Provider Configuration
```bash
# Set API keys in environment
export GEMINI_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export QWEN_API_KEY="your-key"
```

## File Structure Quick Reference

```
agents/website_deployer/
├── config/                    # Configuration files
│   ├── llm_config.yaml       # LLM provider settings
│   ├── tech_stack_registry.yaml # Tech stack definitions
│   └── prompt_templates.yaml # LLM prompt templates
├── stages/                    # Generation pipeline stages
│   ├── intelligent_code_generator.py # Main orchestrator
│   ├── llm_client.py         # Multi-provider LLM client
│   ├── deployment_orchestrator.py # SSH deployment system
│   └── intelligent_generators/ # Pipeline stage modules
├── ssh/                       # SSH connection management
├── examples/                  # Usage examples
├── tests/                     # Test suite
└── generated_projects/        # Output directory
```

## Common Development Tasks

### Adding a New Technology Stack
1. Edit `config/tech_stack_registry.yaml`
2. Add prompt templates to `config/prompt_templates.yaml`
3. Update `tech_stack_config.py` if needed
4. Test with `examples/full_deployment_demo.py`

### Modifying LLM Configuration
1. Edit `config/llm_config.yaml`
2. Update provider order as needed
3. Test with appropriate API keys
4. Verify fallback behavior

### Extending Deployment Modules
1. Add new modules in `stages/deployment_modules/`
2. Update `deployment_orchestrator.py` to use new modules
3. Test with actual deployment scenarios
4. Document new capabilities

---
*This memo is automatically maintained by Qwen Code Assistant. Last updated: November 28, 2025*