#!/usr/bin/env python3
"""Test new safety classification patterns."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ssh import CommandSafetyClassifier

# Test the new patterns
test_commands = [
    ("hostname", "READ_ONLY"),
    ("python3 --version", "READ_ONLY"),
    ("node --version", "READ_ONLY"),
    ("git --version", "READ_ONLY"),
    ("nginx -v", "READ_ONLY"),
    ("uname -a", "READ_ONLY"),
]

print("Testing new safety classification patterns:\n")
for cmd, expected_level in test_commands:
    result = CommandSafetyClassifier.classify(cmd)
    actual_level = result.safety_level.name
    status = "✅" if actual_level == expected_level else "❌"
    print(f"{status} {cmd:25} -> {actual_level:12} (expected: {expected_level})")
    print(f"   Reason: {result.reason}")

print("\n✅ All new patterns tested!")
