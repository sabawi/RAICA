#!/usr/bin/env python3
"""
Tool Details Provider - On-demand retrieval of user tool details

This module provides full tool schemas when the LLM requests them via INVESTIGATE.

Architecture:
- Layer 1 (First Contact): LLM sees tool catalog (name + description)
- Layer 2 (On-Demand): LLM requests details, gets full schema

This saves ~1900 tokens on first contact while keeping LLM fully informed.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


async def get_tool_details(tool_name: str) -> Dict[str, Any]:
    """
    Get full details for a specific user tool.

    This is called when LLM decides it wants to use a tool and requests:
      INVESTIGATE → get_tool_details <tool_name>

    Args:
        tool_name: Name of the tool to get details for

    Returns:
        Full tool definition with:
        - name: Tool name
        - description: Full description
        - parameters: Complete JSON schema for parameters
        - category: Tool category
        - usage_example: Example of how to use it (if available)

        Or error dict if tool not found:
        - error: Error message
        - available_tools: List of available tool names
    """
    try:
        # Add RAICA root to path
        raica_root = Path(__file__).parent.parent.parent.parent
        if str(raica_root) not in sys.path:
            sys.path.insert(0, str(raica_root))

        # Discover tools
        from user_tools.tool_discovery import discover_user_tools, get_user_tool_by_name

        tools = await discover_user_tools()
        tool = get_user_tool_by_name(tools, tool_name)

        if not tool:
            # Tool not found - provide helpful error
            available = [t.name for t in tools]
            return {
                "error": f"Tool not found: {tool_name}",
                "available_tools": available,
                "suggestion": f"Did you mean one of these? {', '.join(available[:5])}"
            }

        # Get full tool definition
        definition = tool.get_function_definition()

        # Add category if we can infer it
        definition['category'] = _infer_category(tool_name, definition.get('description', ''))

        # Add usage guidance
        definition['usage_guidance'] = _generate_usage_guidance(definition)

        logger.info(f"Retrieved details for tool: {tool_name}")

        return definition

    except Exception as e:
        logger.error(f"Failed to get tool details for {tool_name}: {e}")
        return {
            "error": f"Failed to retrieve tool details: {str(e)}",
            "tool_name": tool_name
        }


def _infer_category(tool_name: str, description: str) -> str:
    """Infer tool category from name and description."""
    tool_lower = tool_name.lower()
    desc_lower = description.lower()

    if any(kw in tool_lower or kw in desc_lower for kw in ['email', 'mail', 'calendar', 'social']):
        return 'communication'
    elif any(kw in tool_lower or kw in desc_lower for kw in ['pdf', 'document', 'image', 'text', 'ocr']):
        return 'document'
    elif any(kw in tool_lower or kw in desc_lower for kw in ['stock', 'sec', 'edgar', 'financial']):
        return 'finance'
    elif any(kw in tool_lower or kw in desc_lower for kw in ['paper', 'research', 'academic']):
        return 'research'
    elif any(kw in tool_lower or kw in desc_lower for kw in ['executor', 'process', 'sandbox', 'code']):
        return 'development'
    else:
        return 'utility'


def _generate_usage_guidance(definition: Dict[str, Any]) -> str:
    """Generate usage guidance from tool definition."""
    params = definition.get('parameters', {})
    properties = params.get('properties', {})
    required = params.get('required', [])

    if not properties:
        return "This tool has no parameters. Call it directly."

    # Build example call
    example_params = {}
    for param_name, param_info in properties.items():
        param_type = param_info.get('type', 'string')
        param_desc = param_info.get('description', '')

        # Generate example value based on type and description
        if param_type == 'string':
            if 'email' in param_name.lower() or 'email' in param_desc.lower():
                example_params[param_name] = "user@example.com"
            elif 'subject' in param_name.lower():
                example_params[param_name] = "Email subject here"
            elif 'body' in param_name.lower() or 'content' in param_name.lower():
                example_params[param_name] = "Message content here"
            else:
                example_params[param_name] = f"<{param_name}>"
        elif param_type == 'integer':
            example_params[param_name] = 10
        elif param_type == 'boolean':
            example_params[param_name] = True
        elif param_type == 'array':
            example_params[param_name] = []

    guidance = "Required parameters: " + ", ".join(required) if required else "No required parameters"
    guidance += f"\n\nExample call:\n{json.dumps(example_params, indent=2)}"

    return guidance


async def list_all_tools() -> Dict[str, Any]:
    """
    List all available user tools with basic info.

    Returns:
        Dict with:
        - total: Number of tools
        - tools: List of {name, description, category}
    """
    try:
        raica_root = Path(__file__).parent.parent.parent.parent
        if str(raica_root) not in sys.path:
            sys.path.insert(0, str(raica_root))

        from user_tools.tool_discovery import discover_user_tools

        tools = await discover_user_tools()

        tool_list = []
        for tool in tools:
            tool_list.append({
                'name': tool.name,
                'description': tool.description.split('\n')[0][:120],  # First line, max 120 chars
                'category': _infer_category(tool.name, tool.description)
            })

        return {
            'total': len(tool_list),
            'tools': sorted(tool_list, key=lambda x: (x['category'], x['name']))
        }

    except Exception as e:
        logger.error(f"Failed to list tools: {e}")
        return {
            'error': f"Failed to list tools: {str(e)}",
            'total': 0,
            'tools': []
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def test():
        print("="*70)
        print("TOOL DETAILS PROVIDER TEST")
        print("="*70)

        # Test 1: Get details for a specific tool
        print("\n1. Getting details for secure_email_sender...")
        details = await get_tool_details('secure_email_sender')
        print(json.dumps(details, indent=2))

        # Test 2: Try a non-existent tool
        print("\n2. Trying non-existent tool...")
        error_result = await get_tool_details('nonexistent_tool')
        print(json.dumps(error_result, indent=2))

        # Test 3: List all tools
        print("\n3. Listing all tools...")
        all_tools = await list_all_tools()
        print(f"Total tools: {all_tools['total']}")
        for tool in all_tools['tools'][:5]:
            print(f"  - [{tool['category']}] {tool['name']}: {tool['description'][:60]}...")

        print("\n" + "="*70)
        print("TEST COMPLETE")
        print("="*70)

    asyncio.run(test())
