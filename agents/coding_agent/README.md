# CLI Coding Agent

**Version:** 1.0.0

## Overview

The CLI Coding Agent is an autonomous code generation tool that iterates through the complete software development lifecycle:

```
Requirements → Planning → Architecture → Design → Coding → Debugging → Testing
```

Unlike simple code generators, this agent:
- **Understands requirements** by extracting and refining user intentions
- **Plans implementation** with proper dependency ordering
- **Designs architecture** appropriate to project size
- **Generates complete files** with proper structure
- **Debugs issues** by reviewing and fixing problems
- **Creates tests** for validation
- **Iterates** until requirements are met or max iterations reached

## Configuration

All configuration is loaded from `config/agents_config.yaml`. See [Agent Configuration Guide](../../docs/AGENT_CONFIGURATION_GUIDE.md) for details.

### Key Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `server.base_url` | `http://localhost:5000/v1` | RAICA server URL |
| `llm.model` | `RAICA-Model1` | LLM model for code generation |
| `llm.temperature` | `0.3` | Lower for deterministic code output |
| `llm.max_tokens` | `8192` | Larger for complete code files |
| `execution.max_iterations` | `10` | Maximum debug/test iterations |

## Quick Start

### Test Server Connection
```bash
cd /home/sabawi/Development/flaskserver
python agents/coding_agent/cli_coding_agent.py --test
```

### Generate a Simple Project
```bash
python agents/coding_agent/cli_coding_agent.py "Create a Python script to calculate fibonacci numbers"
```

### Generate with Custom Project Name
```bash
python agents/coding_agent/cli_coding_agent.py "Build a REST API for user management" --project my-api
```

### Verbose Mode
```bash
python agents/coding_agent/cli_coding_agent.py "Create a web scraper" --verbose
```

### Show Configuration
```bash
python agents/coding_agent/cli_coding_agent.py --show-config
```

## Command-Line Options

```
positional arguments:
  request               Your coding request (what you want to build)

optional arguments:
  -h, --help            Show help message and exit
  --project, -p NAME    Project name (default: auto-generated timestamp)
  --output, -o DIR      Output directory for generated projects (default: generated_projects)
  --server URL          Override server URL from config
  --max-iterations N    Maximum development iterations (default: 10)
  --verbose, -v         Enable verbose logging
  --test                Test server connection and exit
  --show-config         Show configuration and exit
```

## Development Phases

### Phase 1: Requirements
The agent analyzes your request and extracts:
- Clear, actionable requirements
- Implicit requirements
- Assumptions made
- Constraints identified

**Output:** Refined requirements list

### Phase 2: Planning
Creates an implementation plan with:
- Ordered implementation steps
- Complexity estimates
- Technology stack decisions
- Risk identification

**Output:** Step-by-step implementation plan

### Phase 3: Architecture
Defines high-level system design:
- Architecture type (modular, layered, etc.)
- Major components
- Component interactions
- Design patterns

**Output:** Architecture decisions and components

### Phase 4: Design
Detailed file specifications:
- File structure
- File purposes
- Content outlines
- Dependencies

**Output:** File specifications list

### Phase 5: Coding
Generates actual code:
- Complete implementations
- Proper imports
- Docstrings and comments
- Error handling

**Output:** Generated source files

### Phase 6: Debugging
Reviews and fixes code:
- Identifies bugs and issues
- Checks for missing imports
- Validates logic
- Applies fixes

**Output:** Fixed code files

### Phase 7: Testing
Generates and validates tests:
- Unit test generation
- Edge case coverage
- Error handling tests

**Output:** Test files

## Iteration Control

The agent automatically iterates when:
- Critical issues remain after debugging
- Tests fail

Iteration stops when:
- All requirements are met
- No critical issues remain
- Max iterations reached

## Example Output

```
================================================================================
 🤖 CLI CODING AGENT v1.0.0
================================================================================
Project: fibonacci_calculator
Output: /home/user/flaskserver/generated_projects/fibonacci_calculator
Request: Create a Python script to calculate fibonacci numbers...

🔌 Testing server connection...
✅ Server connected

================================================================================
 📋 PHASE: REQUIREMENTS (Iteration 1)
================================================================================

✅ Extracted 4 requirements
   • R1: Implement function to calculate fibonacci numbers
   • R2: Support both iterative and recursive approaches
   • R3: Handle edge cases (negative numbers, zero)
   • R4: Provide command-line interface

================================================================================
 📝 PHASE: PLANNING (Iteration 1)
================================================================================

✅ Created plan with 5 steps
   • Step 1: Create main fibonacci module
   • Step 2: Implement iterative fibonacci function
   • Step 3: Implement recursive fibonacci function
   • Step 4: Add CLI argument parsing
   • Step 5: Add input validation

[... more phases ...]

================================================================================
 ✅ DEVELOPMENT COMPLETE
================================================================================

Project: fibonacci_calculator
Location: /home/user/flaskserver/generated_projects/fibonacci_calculator
Iterations: 1

Files generated:
   • fibonacci.py (1234 bytes)
   • test_fibonacci.py (856 bytes)

Requirements: 4 items | Plan: 5 steps | Components: 2 | Files: 2 | Tests: 1/1 passed

Context saved: /home/user/.../project_context.json
```

## Output Structure

Generated projects are organized as:

```
generated_projects/
└── project_name/
    ├── project_context.json    # Project context and metadata
    ├── main.py                 # Main source files
    ├── module/                 # Additional modules
    │   └── utils.py
    └── test_main.py           # Generated tests
```

## Context Management

The agent maintains a `ProjectContext` that tracks:
- Original request
- Refined requirements
- Implementation plan
- Architecture decisions
- Generated files
- Issues found
- Test results
- Iteration count

This context is saved to `project_context.json` for reference and potential resumption.

## Best Practices

### 1. Clear Requests
Be specific about what you want:
- ❌ "Make a calculator"
- ✅ "Create a Python command-line calculator that supports add, subtract, multiply, divide operations with proper error handling"

### 2. Iterative Refinement
Start with simpler requests and iterate:
1. First generate basic functionality
2. Then add features incrementally
3. Review and refine

### 3. Review Output
Always review generated code before use:
- Check for security issues
- Verify logic correctness
- Test in isolated environment

### 4. Use Verbose Mode
When debugging issues:
```bash
python cli_coding_agent.py "..." --verbose
```

## Troubleshooting

### Server Connection Failed
```bash
# Check if server is running
curl http://localhost:5000/health

# Start server if needed
./start_complete.sh
```

### Empty Responses
- Server may be overloaded
- Try again with `--verbose` to see details
- Check server logs

### Code Quality Issues
- Increase `--max-iterations` for more refinement
- Be more specific in your request
- Review generated files and provide feedback

## Future Enhancements

- [ ] Interactive mode for real-time feedback
- [ ] Project resumption from saved context
- [ ] Multi-file refactoring
- [ ] Integration with version control
- [ ] Custom prompt templates
- [ ] External test execution

## Version History

### 1.0.0 (Initial Release)
- 7-phase development lifecycle
- State machine for phase transitions
- Iterative debugging and testing
- Context-efficient prompting
- CLI interface with rich output
- Configuration via agents_config.yaml
