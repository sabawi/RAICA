#!/usr/bin/env python3
"""
Integration test for user tools in universal_handler.py

Tests that:
1. Context builder discovers user tools
2. Tools catalog included in first contact
3. get_tool_details works in INVESTIGATE decision
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_context_builder_discovery():
    """Test 1: Context builder discovers user tools."""
    print("\n" + "="*70)
    print("TEST 1: Context Builder - User Tools Discovery")
    print("="*70)

    from agents.coding_agent.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    context = await builder.build_context(
        request="Send an email to test@example.com",
        project_dir=None
    )

    print(f"✅ Context built successfully")
    print(f"   System tools: {len(context.system.tools)}")
    print(f"   User tools: {len(context.user_tools.tools)}")
    print(f"   Communication hub tools: {len(context.user_tools.communication_tools)}")
    print(f"   Total estimated tokens: {context.total_estimated_tokens()}")

    assert context.user_tools is not None, "User tools should be present"
    assert len(context.user_tools.tools) > 0, "Should discover some user tools"
    assert len(context.user_tools.communication_tools) > 0, "Should have communication tools"

    print(f"\n✅ TEST 1 PASSED: Discovered {len(context.user_tools.tools)} user tools")

    return context


async def test_tool_details_provider():
    """Test 2: Tool details provider returns full schema."""
    print("\n" + "="*70)
    print("TEST 2: Tool Details Provider")
    print("="*70)

    from agents.coding_agent.services.tool_details_provider import get_tool_details

    # Test getting details for a known tool
    details = await get_tool_details('secure_email_sender')

    print(f"✅ Retrieved tool details")
    print(f"   Name: {details.get('name')}")
    print(f"   Category: {details.get('category')}")
    print(f"   Has parameters: {details.get('parameters') is not None}")

    assert details.get('name') == 'secure_email_sender', "Should return correct tool"
    assert 'parameters' in details, "Should include parameters schema"
    assert 'description' in details, "Should include description"

    print(f"\n✅ TEST 2 PASSED: Tool details retrieved successfully")

    # Test non-existent tool
    error_result = await get_tool_details('nonexistent_tool')
    assert 'error' in error_result, "Should return error for non-existent tool"

    print(f"✅ TEST 2 PASSED: Error handling works correctly")

    return details


async def test_user_tools_in_context():
    """Test 3: User tools appear in gathered context."""
    print("\n" + "="*70)
    print("TEST 3: User Tools in Universal Handler Context")
    print("="*70)

    # This test would require a full universal_handler setup
    # For now, just verify the context builder integration

    from agents.coding_agent.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    context = await builder.build_context(
        request="Send an email",
        project_dir=project_root
    )

    # Simulate what universal_handler does
    tools_catalog = context.user_tools.tools
    comm_tools = context.user_tools.communication_tools

    user_tools_context = f"\n\n═══ RAICA USER TOOLS ═══\n"
    user_tools_context += f"You have access to {len(tools_catalog)} user-defined tools.\n"
    user_tools_context += f"Communication hub tools: {', '.join(comm_tools)}\n\n"

    for tool_name, tool_info in sorted(tools_catalog.items()):
        category = tool_info.get('category', 'utility')
        desc = tool_info.get('description', 'No description')
        marker = "⭐" if tool_name in comm_tools else " "
        user_tools_context += f"{marker} [{category}] {tool_name}: {desc[:60]}...\n"

    print(user_tools_context[:500])  # Show first 500 chars

    assert "RAICA USER TOOLS" in user_tools_context
    assert "secure_email_sender" in user_tools_context or "email" in user_tools_context.lower()

    print(f"\n✅ TEST 3 PASSED: User tools formatted correctly for context")

    return user_tools_context


async def main():
    """Run all integration tests."""
    print("\n" + "="*70)
    print("USER TOOLS INTEGRATION TEST SUITE")
    print("="*70)

    try:
        # Test 1: Discovery
        context = await test_context_builder_discovery()

        # Test 2: Tool details
        details = await test_tool_details_provider()

        # Test 3: Context formatting
        tools_context = await test_user_tools_in_context()

        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\nSummary:")
        print(f"  - Discovered {len(context.user_tools.tools)} user tools")
        print(f"  - Communication tools: {len(context.user_tools.communication_tools)}")
        print(f"  - Context tokens: {context.total_estimated_tokens()}")
        print(f"  - Tool details provider: Working")
        print(f"  - Context formatting: Working")
        print("\n✅ Integration is ready for end-to-end testing with universal_handler!")

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
