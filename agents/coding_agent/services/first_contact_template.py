#!/usr/bin/env python3
"""
First Contact Template - Rich context prompt for initial LLM contact

Philosophy:
- Give LLM COMPLETE picture on first contact
- Subsequent iterations: only deltas (discoveries, results)
- Token-efficient: structured but concise
"""

from typing import Dict, Any
import json


def build_first_contact_prompt(context: 'Context') -> str:
    """
    Build rich first-contact prompt with complete context.

    This is the ONLY time we send full context.
    Subsequent iterations only send:
    - Last decision and result
    - New discoveries
    - Next question

    Token Budget:
    - Context: ~1000-1500 tokens
    - Prompt structure: ~300-500 tokens
    - Total: ~1500-2000 tokens (reasonable for first contact)

    Args:
        context: Complete context from ContextBuilder

    Returns:
        Formatted prompt with full context
    """

    system_dict = context.system.to_compact_dict() if context.system else {}
    user_dict = context.user.to_compact_dict() if context.user else {}
    project_dict = context.project.to_compact_dict() if context.project else {'has_project': False}

    # Build prompt sections
    sections = []

    # Header
    sections.append(f"""# SYSTEM TASK: {context.request}

You are an intelligent task executor with complete knowledge of the system, user, and project context.
Your goal: Accomplish the user's request by discovering, innovating, and adapting as needed.

You can:
- Execute any system command
- Create scripts/tools
- Fix existing code
- Install packages
- Investigate and learn

Keep trying different approaches until the task is accomplished.
""")

    # System Profile
    sections.append(f"""## SYSTEM PROFILE

Operating System: {system_dict.get('os', 'Unknown')}
Shell: {system_dict.get('shell', 'Unknown')}
Python: {system_dict.get('python', 'Unknown')}
Working Directory: {system_dict.get('cwd', 'Unknown')}

Available Tools:
{_format_tools(system_dict.get('tools', {}))}
""")

    # User Profile
    sections.append(f"""## USER PROFILE

Name: {user_dict.get('name', 'Unknown')}
Email: {user_dict.get('email', 'Not configured')}
Current Directory: {user_dict.get('cwd', 'Unknown')}
""")

    # User Tools (if available)
    user_tools_dict = context.user_tools.to_compact_dict() if context.user_tools else None
    if user_tools_dict and user_tools_dict.get('available', 0) > 0:
        sections.append(_format_user_tools_catalog(user_tools_dict))

    # Project Profile (if exists)
    if project_dict.get('has_project', False):
        sections.append(_format_project_context(project_dict))
    else:
        sections.append("""## PROJECT CONTEXT

No project context (not working in a project directory).
This is a standalone system task.
""")

    # Decision Framework
    sections.append("""## YOUR TASK

Analyze the request and decide how to accomplish it.

Decision Types Available:
1. **EXECUTE** - Run a system command immediately
   - Use when: Command exists and you know exactly what to run
   - Example: Send email, download file, check status
   - Format: Provide shell command(s) to execute

2. **CREATE** - Create a new script/tool
   - Use when: Task requires custom code or no existing tool fits
   - Example: Generate a script to process data
   - Format: Provide code and filename

3. **FIX** - Modify existing code
   - Use when: Fixing bugs or updating existing files
   - Example: Fix a bug in validation.py
   - Format: Provide file path and changes

4. **INSTALL** - Install dependencies
   - Use when: Required tools/packages are missing
   - Example: Install a Python package
   - Format: Provide installation commands

5. **INVESTIGATE** - Gather more information
   - Use when: Need to understand the situation before acting
   - Example: Read a file, check logs, search for information
   - Format: Provide investigation commands

## RESPONSE FORMAT

Respond with JSON:
```json
{
    "decision_type": "EXECUTE | CREATE | FIX | INSTALL | INVESTIGATE",
    "reasoning": "Brief explanation of why this approach",
    "action": {
        // Type-specific fields:
        // EXECUTE: {"commands": ["cmd1", "cmd2"]}
        // CREATE: {"filename": "script.py", "code": "..."}
        // FIX: {"file_path": "path/to/file.py", "changes": "..."}
        // INSTALL: {"commands": ["pip install X"]}
        // INVESTIGATE: {"commands": ["cat file", "grep pattern"]}
    },
    "expected_outcome": "What should happen if this succeeds?",
    "fallback_plan": "If this fails, what's the next approach to try?"
}
```

## IMPORTANT GUIDELINES

1. **Be Specific**: Exact commands, exact file paths, exact parameters
2. **Discover Dynamically**: If you need to know something (like a file location), use INVESTIGATE first
3. **Keep Trying**: If one approach fails, try another. Don't give up easily.
4. **Use Context**: The system profile shows what tools are available
5. **Adapt**: If you discover new information, adjust your approach

Now analyze the request and provide your decision in JSON format.
""")

    return "\n".join(sections)


def _format_tools(tools: Dict[str, str]) -> str:
    """Format tools for display."""
    if not tools:
        return "  (No tools discovered)"

    lines = []
    for name, info in sorted(tools.items()):
        lines.append(f"  • {name}: {info}")

    return "\n".join(lines)


def _format_user_tools_catalog(user_tools_dict: Dict[str, Any]) -> str:
    """
    Format user tools catalog for first contact.

    Highlights communication hub tools (email, calendar, social media).
    Organizes by category for easy scanning.
    """
    catalog = user_tools_dict.get('catalog', {})
    comm_hub = user_tools_dict.get('communication_hub', [])
    total = user_tools_dict.get('available', 0)

    if not catalog:
        return ""

    sections = []

    sections.append(f"""## RAICA USER TOOLS

You have access to {total} user-defined tools on the RAICA server.
These are professional, production-ready tools with full functionality.

**IMPORTANT:** Tool catalog shows name + description only.
To USE a tool, first request its full details:
  Decision: INVESTIGATE
  Action: {{"commands": ["get_tool_details <tool_name>"]}}

This returns the complete parameter schema needed to call the tool.
""")

    # Group tools by category
    by_category = {}
    for tool_name, tool_info in catalog.items():
        category = tool_info.get('category', 'utility')
        if category not in by_category:
            by_category[category] = []
        by_category[category].append((tool_name, tool_info))

    # Communication Hub first (HIGHLIGHTED!)
    if 'communication' in by_category:
        sections.append("### 🌟 Communication Hub (Email, Calendar, Social Media)")
        for tool_name, tool_info in sorted(by_category['communication']):
            desc = tool_info.get('description', 'No description')
            marker = "⭐ " if tool_name in comm_hub else "  "
            sections.append(f"{marker}• **{tool_name}**: {desc}")
        sections.append("")

    # Documents
    if 'document' in by_category:
        sections.append("### 📄 Documents (PDF, OCR, Search)")
        for tool_name, tool_info in sorted(by_category['document']):
            desc = tool_info.get('description', 'No description')
            sections.append(f"  • **{tool_name}**: {desc}")
        sections.append("")

    # Finance
    if 'finance' in by_category:
        sections.append("### 💰 Finance (Stock Analysis, SEC Data)")
        for tool_name, tool_info in sorted(by_category['finance']):
            desc = tool_info.get('description', 'No description')
            sections.append(f"  • **{tool_name}**: {desc}")
        sections.append("")

    # Research
    if 'research' in by_category:
        sections.append("### 🔬 Research (Academic Papers)")
        for tool_name, tool_info in sorted(by_category['research']):
            desc = tool_info.get('description', 'No description')
            sections.append(f"  • **{tool_name}**: {desc}")
        sections.append("")

    # Development
    if 'development' in by_category:
        sections.append("### 💻 Development (Code Execution, Process Management)")
        for tool_name, tool_info in sorted(by_category['development']):
            desc = tool_info.get('description', 'No description')
            sections.append(f"  • **{tool_name}**: {desc}")
        sections.append("")

    # Utility (everything else)
    if 'utility' in by_category:
        sections.append("### 🔧 Utility Tools")
        for tool_name, tool_info in sorted(by_category['utility']):
            desc = tool_info.get('description', 'No description')
            sections.append(f"  • **{tool_name}**: {desc}")
        sections.append("")

    sections.append("""**Usage Pattern:**
1. See a tool you want to use above
2. Request details: INVESTIGATE → get_tool_details <tool_name>
3. Receive full parameter schema
4. Call tool with proper parameters

Example:
  You see: "secure_email_sender: Send professional emails..."
  You request: get_tool_details secure_email_sender
  You receive: Full schema with parameters (to, subject, body, etc.)
  You execute: Call tool with all required parameters
""")

    return "\n".join(sections)


def _format_project_context(project_dict: Dict[str, Any]) -> str:
    """Format project context section."""
    sections = []

    sections.append(f"""## PROJECT CONTEXT

Project Directory: {project_dict.get('project_dir', 'Unknown')}
""")

    # CLAUDE.md (project directives - CRITICAL!)
    if project_dict.get('claude_md'):
        claude_md = project_dict['claude_md']
        sections.append(f"""### Project Directives (CLAUDE.md)

CRITICAL: These are mandatory rules for this project. You MUST follow them.

{claude_md}
""")

    # README (project overview)
    if project_dict.get('readme'):
        readme = project_dict['readme']
        sections.append(f"""### Project Overview (README.md)

{readme}
""")

    # Architecture
    if project_dict.get('architecture'):
        architecture = project_dict['architecture']
        sections.append(f"""### Architecture Documentation

{architecture}
""")

    # File tree (project structure)
    if project_dict.get('file_tree'):
        file_tree = project_dict['file_tree']
        sections.append(f"""### Project Structure

```
{file_tree}
```
""")

    return "\n".join(sections)


# =============================================================================
# ITERATION PROMPT - Much lighter than first contact
# =============================================================================

def build_iteration_prompt(
    request: str,
    iteration_num: int,
    last_decision: Dict[str, Any],
    last_result: Dict[str, Any],
    discoveries: list
) -> str:
    """
    Build prompt for iteration N (N > 1).

    Much lighter than first contact:
    - LLM already has full context from first contact
    - Just show what we tried, what happened, what we learned
    - Ask: What's next?

    Token Budget:
    - Much smaller: ~200-500 tokens
    """

    success = last_result.get('success', False)
    outcome = last_result.get('output', 'No output')

    prompt = f"""# SYSTEM TASK (Iteration {iteration_num}): {request}

## PREVIOUS ATTEMPT

Decision Type: {last_decision.get('decision_type', 'Unknown')}
Reasoning: {last_decision.get('reasoning', 'Not provided')}

Action Taken:
{_format_action(last_decision.get('action', {}))}

Result: {'✅ SUCCESS' if success else '❌ FAILED'}
Output:
```
{outcome}
```

## DISCOVERIES

{_format_discoveries(discoveries)}

## WHAT'S NEXT?

{'The previous attempt succeeded!' if success else 'The previous attempt failed.'}

{_format_continuation_guidance(success, last_decision, last_result)}

Provide your next decision in JSON format (same structure as before).
"""

    return prompt


def _format_action(action: Dict[str, Any]) -> str:
    """Format action for display."""
    if not action:
        return "  (No action)"

    lines = []
    for key, value in action.items():
        if key == 'commands' and isinstance(value, list):
            lines.append(f"  Commands:")
            for cmd in value:
                lines.append(f"    - {cmd}")
        elif key == 'code':
            lines.append(f"  Code: {len(value)} characters")
        else:
            lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def _format_discoveries(discoveries: list) -> str:
    """Format discoveries."""
    if not discoveries:
        return "  (No new discoveries yet)"

    lines = []
    for i, discovery in enumerate(discoveries, 1):
        lines.append(f"{i}. {discovery}")

    return "\n".join(lines)


def _format_continuation_guidance(
    success: bool,
    last_decision: Dict[str, Any],
    last_result: Dict[str, Any]
) -> str:
    """Provide guidance for continuation."""
    if success:
        return """The task may be complete, or there may be follow-up work needed.

Options:
- If task is fully accomplished: Return decision_type "COMPLETE" with success summary
- If follow-up needed: Decide next action"""

    # Failed - provide guidance
    error_msg = last_result.get('error', 'Unknown error')

    return f"""The attempt failed with error:
{error_msg}

Consider:
1. Was the approach correct but execution failed? (Try fixing the command)
2. Was the approach wrong? (Try a different decision type)
3. Do you need more information? (Use INVESTIGATE)
4. Refer to your fallback plan: {last_decision.get('fallback_plan', 'No fallback provided')}

Choose your next approach and try again.
"""


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    from context_builder import Context, SystemProfile, UserProfile, ProjectProfile, ToolInfo

    # Test context
    context = Context(
        system=SystemProfile(
            os_info="Linux Ubuntu 22.04",
            shell="bash",
            python_version="3.12.3",
            working_directory="/home/user/project",
            tools={
                'mail': ToolInfo(name='mail', path='/usr/bin/mail', exists=True, category='email'),
                'curl': ToolInfo(name='curl', path='/usr/bin/curl', exists=True, category='web'),
            }
        ),
        user=UserProfile(
            name="Test User",
            email="test@example.com",
            working_directory="/home/user/project"
        ),
        project=ProjectProfile(
            has_project=False
        ),
        request="Send an email to user@example.com saying 'Hello World'"
    )

    # Build first contact prompt
    prompt = build_first_contact_prompt(context)

    print("="*70)
    print("FIRST CONTACT PROMPT")
    print("="*70)
    print(prompt)
    print("="*70)
    print(f"Estimated length: {len(prompt)} chars (~{len(prompt)//4} tokens)")
    print("="*70)
