"""
Test Communication Hub - Basic Email Flow

Tests the complete Communication Hub architecture:
- Hub initialization
- Email channel loading
- Security validation
- Email sending with attachments
"""

import sys
import asyncio
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from communication_hub import CommunicationHub, ChannelType, CommunicationPriority


async def test_hub_initialization():
    """Test 1: Hub initialization and channel loading"""
    print("=" * 80)
    print("TEST 1: Communication Hub Initialization")
    print("=" * 80)

    try:
        # Initialize hub with config
        config_path = project_root / "config" / "communication_hub.yaml"
        print(f"📂 Config path: {config_path}")
        print(f"   Config exists: {config_path.exists()}")

        hub = CommunicationHub(config_path=str(config_path))

        print(f"\n✅ Hub initialized successfully")
        print(f"   Available channels: {hub.get_available_channels()}")

        # Get channel status
        status = hub.get_channel_status()
        print(f"\n📊 Channel Status:")
        for channel_name, channel_status in status.items():
            print(f"   {channel_name}:")
            print(f"      enabled: {channel_status.get('enabled')}")
            print(f"      supports_attachments: {channel_status.get('supports_attachments')}")
            print(f"      max_content_length: {channel_status.get('max_content_length')}")
            print(f"      rate_limits: {channel_status.get('rate_limits')}")

        return hub, True

    except Exception as e:
        print(f"\n❌ Hub initialization FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None, False


async def test_email_validation(hub):
    """Test 2: Email validation and security checks"""
    print("\n" + "=" * 80)
    print("TEST 2: Email Validation and Security")
    print("=" * 80)

    try:
        # Test recipient validation
        recipients = ["valid@example.com", "invalid-email", "another@test.com"]
        print(f"🔍 Testing recipient validation: {recipients}")

        email_channel = hub._channels.get(ChannelType.EMAIL)
        if email_channel:
            validation_results = await email_channel.verify_recipients(recipients)
            print(f"\n📧 Validation Results:")
            for email, is_valid in validation_results.items():
                status = "✅ VALID" if is_valid else "❌ INVALID"
                print(f"   {email}: {status}")

            return True
        else:
            print("❌ Email channel not loaded")
            return False

    except Exception as e:
        print(f"\n❌ Validation test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_file_validation(hub):
    """Test 3: File attachment validation"""
    print("\n" + "=" * 80)
    print("TEST 3: File Attachment Validation")
    print("=" * 80)

    try:
        # Create a test file
        test_file = project_root / "sandbox_workspace" / "test_communication_hub.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("This is a test file for Communication Hub validation")

        print(f"📄 Created test file: {test_file}")

        # Test file validation
        files_to_validate = [
            str(test_file),  # Existing file
            "/nonexistent/file.txt",  # Non-existent file
        ]

        print(f"\n🔍 Testing file validation: {files_to_validate}")

        validation = await hub.security.validate_files(files_to_validate)

        print(f"\n📊 Validation Results:")
        print(f"   Valid: {validation['valid']}")
        print(f"   Errors: {validation.get('errors', [])}")
        print(f"   Validated paths: {validation.get('validated_paths', [])}")

        return validation['valid']  # Should be False because one file doesn't exist

    except Exception as e:
        print(f"\n❌ File validation test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_send_email(hub):
    """Test 4: Send test email through Hub"""
    print("\n" + "=" * 80)
    print("TEST 4: Send Test Email Through Hub")
    print("=" * 80)

    try:
        # Get sender email from environment
        sender_email = os.getenv("GMAIL_PRIMARY_EMAIL", "test@example.com")
        print(f"📧 Sender: {sender_email}")

        # Create test file if doesn't exist
        test_file = project_root / "sandbox_workspace" / "test_communication_hub.txt"
        if not test_file.exists():
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("This is a test file sent through Communication Hub")

        print(f"📎 Attachment: {test_file}")

        # Send email through Hub
        print(f"\n🚀 Sending email through Communication Hub...")

        result = await hub.send(
            channel=ChannelType.EMAIL,
            recipients=[sender_email],  # Send to self for testing
            content="This is a test email sent through the new Communication Hub architecture.\n\n"
                   "Features tested:\n"
                   "- Unified configuration\n"
                   "- Security validation\n"
                   "- File attachment handling\n"
                   "- Centralized error handling\n\n"
                   "If you receive this email with the attachment, the Communication Hub is working!",
            subject="Communication Hub Test Email",
            attachments=[str(test_file)],
            priority=CommunicationPriority.NORMAL
        )

        print(f"\n📊 Send Result:")
        print(f"   Success: {result['success']}")
        print(f"   Message ID: {result.get('message_id')}")
        print(f"   Channel: {result.get('channel')}")
        print(f"   Recipients: {result.get('recipients')}")
        print(f"   Attachments: {result.get('attachments')}")
        if result.get('error'):
            print(f"   Error: {result['error']}")
        if result.get('details'):
            print(f"   Details: {result['details']}")

        return result['success']

    except Exception as e:
        print(f"\n❌ Send email test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_rate_limiting(hub):
    """Test 5: Rate limiting"""
    print("\n" + "=" * 80)
    print("TEST 5: Rate Limiting")
    print("=" * 80)

    try:
        # Check rate limit status
        rate_check = await hub.security.check_rate_limit(ChannelType.EMAIL)
        print(f"📊 Rate Limit Check:")
        print(f"   Allowed: {rate_check['allowed']}")
        if not rate_check['allowed']:
            print(f"   Reason: {rate_check.get('reason')}")

        # Reset rate limits for clean state
        print(f"\n🔄 Resetting rate limits...")
        hub.reset_rate_limits()

        # Check again after reset
        rate_check = await hub.security.check_rate_limit(ChannelType.EMAIL)
        print(f"📊 Rate Limit Check (after reset):")
        print(f"   Allowed: {rate_check['allowed']}")

        return True

    except Exception as e:
        print(f"\n❌ Rate limiting test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n🧪 Communication Hub Test Suite")
    print("=" * 80)

    results = {}

    # Test 1: Initialization
    hub, success = await test_hub_initialization()
    results['Initialization'] = success

    if not success or not hub:
        print("\n❌ Cannot proceed - Hub initialization failed")
        return

    # Test 2: Email validation
    results['Email Validation'] = await test_email_validation(hub)

    # Test 3: File validation
    results['File Validation'] = await test_file_validation(hub)

    # Test 4: Send email (only if email is configured)
    sender_email = os.getenv("GMAIL_PRIMARY_EMAIL")
    if sender_email and sender_email != "test@example.com":
        results['Send Email'] = await test_send_email(hub)
    else:
        print("\n⚠️ Skipping email send test - GMAIL_PRIMARY_EMAIL not configured")
        results['Send Email'] = None

    # Test 5: Rate limiting
    results['Rate Limiting'] = await test_rate_limiting(hub)

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for v in results.values() if v is True)
    skipped = sum(1 for v in results.values() if v is None)
    failed = sum(1 for v in results.values() if v is False)

    for test_name, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is None:
            status = "⚠️ SKIPPED"
        else:
            status = "❌ FAILED"
        print(f"   {test_name}: {status}")

    print(f"\n📊 Results: {passed} passed, {failed} failed, {skipped} skipped")

    if failed == 0:
        print("\n🎉 All tests PASSED!")
    else:
        print(f"\n❌ {failed} test(s) FAILED")


if __name__ == "__main__":
    asyncio.run(main())
