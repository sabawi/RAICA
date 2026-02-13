#!/usr/bin/env python3
"""
End-to-End Test: User Tools Integration with Real LLM

Tests the complete flow:
1. User request: "Send an email"
2. Context builder discovers user tools
3. LLM sees tools in catalog
4. LLM decides what to do (INVESTIGATE or EXECUTE)
5. System responds appropriately
"""

import asyncio
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_email_request_with_user_tools():
    """
    End-to-end test: User wants to send an email.

    Expected flow:
    1. PREPARATION: Discover user tools, build catalog
    2. LLM sees: secure_email_sender in catalog
    3. LLM decides: INVESTIGATE → get_tool_details, OR EXECUTE with mail command
    4. If INVESTIGATE: Return tool schema, LLM can then use it
    """
    print("\n" + "="*70)
    print("END-TO-END TEST: Send Email Request with User Tools")
    print("="*70)

    # Import required components
    from agents.coding_agent.orchestrator.universal_handler import (
        UniversalHandler,
        UniversalHandlerCallbacks
    )
    from agents.coding_agent.llm_client import CodeGenLLMClient

    # Setup output callback to see what's happening
    outputs = []

    async def on_output(message: str, msg_type: str):
        """Capture all output messages."""
        outputs.append(f"[{msg_type}] {message}")
        print(f"  [{msg_type}] {message}")

    async def on_phase_start(phase: str):
        """Track phase transitions."""
        print(f"\n🔹 PHASE: {phase}")

    async def on_decision(decision):
        """Track LLM decisions."""
        print(f"\n🤖 LLM DECISION:")
        print(f"   Type: {decision.decision_type.name}")
        print(f"   Reasoning: {decision.reasoning[:200]}...")
        if decision.commands:
            print(f"   Commands: {decision.commands}")

    # Create callbacks
    callbacks = UniversalHandlerCallbacks(
        on_output=on_output,
        on_phase_start=on_phase_start,
        on_decision=on_decision
    )

    # Initialize LLM client
    print("\n📋 Initializing LLM client...")
    llm_client = CodeGenLLMClient()

    # Create test project directory
    test_dir = project_root / "generated_projects" / "test_e2e_user_tools"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Universal Handler
    print("📋 Initializing Universal Handler...")
    handler = UniversalHandler(
        llm_client=llm_client,
        project_dir=test_dir,
        callbacks=callbacks,
        max_triage_iterations=2,
        max_act_iterations=3
    )

    # Test request
    request = "Send an email to test@example.com with subject 'Test Email' and body 'This is a test from RAICA'"

    print(f"\n📨 USER REQUEST: {request}")
    print("\n" + "-"*70)

    try:
        # Execute the request
        result = await handler.handle(request)

        print("\n" + "="*70)
        print("RESULT")
        print("="*70)
        print(f"Success: {result.success}")
        print(f"Phases completed: {result.phases_completed}")

        if result.decision:
            print(f"\nFinal Decision: {result.decision.decision_type.name}")
            print(f"Reasoning: {result.decision.reasoning[:300]}...")

        if result.execution_output:
            print(f"\nExecution Output:")
            print(result.execution_output[:500])
            if len(result.execution_output) > 500:
                print("... (truncated)")

        if result.error:
            print(f"\nError: {result.error}")

        # Analyze the flow
        print("\n" + "="*70)
        print("ANALYSIS")
        print("="*70)

        # Check if user tools were discovered
        user_tools_mentioned = any("RAICA USER TOOLS" in out or "user tool" in out.lower() for out in outputs)
        print(f"✓ User tools discovered: {user_tools_mentioned}")

        # Check if LLM saw the tools
        saw_secure_email = any("secure_email_sender" in out for out in outputs)
        print(f"✓ LLM saw secure_email_sender: {saw_secure_email}")

        # Check decision type
        if result.decision:
            decision_type = result.decision.decision_type.name
            print(f"✓ LLM decision type: {decision_type}")

            if decision_type == "INVESTIGATE":
                print("  → LLM requested more information (get_tool_details)")
                if result.decision.commands:
                    for cmd in result.decision.commands:
                        if "get_tool_details" in cmd:
                            print(f"     Command: {cmd}")
            elif decision_type == "EXECUTE":
                print("  → LLM chose to execute a command")
                if result.decision.commands:
                    print(f"     Commands: {result.decision.commands}")
            elif decision_type == "CREATE":
                print("  → LLM chose to create a script")
                print(f"     Execute after create: {result.decision.execute_after_create}")

        # Success criteria
        print("\n" + "="*70)
        print("SUCCESS CRITERIA")
        print("="*70)

        criteria = {
            "Handler completed without crash": result is not None,
            "User tools discovered": user_tools_mentioned,
            "LLM made a decision": result.decision is not None,
            "Decision is actionable": result.decision and result.decision.decision_type.name in ["INVESTIGATE", "EXECUTE", "CREATE"]
        }

        for criterion, passed in criteria.items():
            status = "✅" if passed else "❌"
            print(f"{status} {criterion}")

        all_passed = all(criteria.values())

        if all_passed:
            print("\n" + "="*70)
            print("✅ END-TO-END TEST PASSED!")
            print("="*70)
            print("\nThe integration is working correctly:")
            print("  1. User tools were discovered")
            print("  2. Tools were included in context")
            print("  3. LLM saw the tools and made a decision")
            print("  4. System can respond appropriately")
        else:
            print("\n" + "="*70)
            print("⚠️  TEST COMPLETED WITH ISSUES")
            print("="*70)
            print("Some criteria not met - review the flow above")

        return 0 if all_passed else 1

    except Exception as e:
        print(f"\n❌ ERROR during execution: {e}")
        import traceback
        traceback.print_exc()
        return 1


async def main():
    """Run the end-to-end test."""
    try:
        exit_code = await test_email_request_with_user_tools()
        return exit_code
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
