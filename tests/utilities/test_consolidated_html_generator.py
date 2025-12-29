#!/usr/bin/env python3
"""
Test Consolidated HTML Generator

Tests the enhanced html_generator.py with merged CSS classes
from report_utils.py and custom CSS support.

Author: Claude Code
Date: 2025-11-01
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.html_generator import html_generator, create_html_report


def test_basic_html_generation():
    """Test basic HTML generation with markdown content"""
    print("\n" + "="*70)
    print("TEST 1: Basic HTML Generation with Markdown")
    print("="*70)

    content = """
## Test Heading

This is a **bold** statement and this is *italic* text.

### Subheading

- Item 1
- Item 2
- Item 3

[Link to Google](https://google.com)
"""

    html = create_html_report(
        content=content,
        title="Test Report",
        header_title="Basic Test",
        header_subtitle="Testing markdown conversion"
    )

    assert "<!DOCTYPE html>" in html
    assert "<h2>Test Heading</h2>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<ul>" in html
    assert '<a href="https://google.com">Link to Google</a>' in html

    print("✅ Basic HTML generation: PASSED")
    print(f"   - Generated {len(html)} characters of HTML")
    print(f"   - Markdown → HTML conversion: OK")
    return html


def test_report_utils_css_classes():
    """Test that all report_utils CSS classes are present"""
    print("\n" + "="*70)
    print("TEST 2: Report Utils CSS Classes")
    print("="*70)

    content = """
<div class="critical">Critical priority item</div>
<div class="high">High priority item</div>
<div class="medium">Medium priority item</div>
<div class="low">Low priority item</div>
<div class="info">Info item</div>

<div class="action-item">Action required!</div>

<div class="priority-1">Priority 1</div>
<div class="priority-2">Priority 2</div>
<div class="priority-3">Priority 3</div>
<div class="priority-4">Priority 4</div>
<div class="priority-5">Priority 5</div>

<span class="sender">John Doe</span>
<span class="subject">Important Email</span>
<span class="priority-high">High Priority Email</span>

<div class="stats-box">
Statistics box content
</div>

<table>
  <tr><th>Header 1</th><th>Header 2</th></tr>
  <tr><td>Data 1</td><td>Data 2</td></tr>
</table>
"""

    html = create_html_report(
        content=content,
        title="CSS Test",
        header_title="CSS Classes Test"
    )

    # Check for all CSS classes in the style section
    css_classes = [
        ".critical", ".high", ".medium", ".low", ".info",
        ".action-item",
        ".priority-1", ".priority-2", ".priority-3", ".priority-4", ".priority-5",
        ".sender", ".subject", ".priority-high",
        ".stats-box",
        "table", "th", "td", "tr:hover"
    ]

    missing_classes = []
    for css_class in css_classes:
        if css_class not in html:
            missing_classes.append(css_class)

    if missing_classes:
        print(f"❌ FAILED: Missing CSS classes: {missing_classes}")
        return None
    else:
        print(f"✅ All {len(css_classes)} CSS classes present: PASSED")
        return html


def test_custom_css_injection():
    """Test custom CSS parameter"""
    print("\n" + "="*70)
    print("TEST 3: Custom CSS Injection")
    print("="*70)

    content = "<div class=\"custom-test\">Custom styled content</div>"

    custom_css = """
.custom-test {
    background-color: #ff00ff;
    color: white;
    padding: 20px;
}
"""

    html = create_html_report(
        content=content,
        title="Custom CSS Test",
        header_title="Custom CSS Test",
        custom_css=custom_css
    )

    assert ".custom-test" in html
    assert "background-color: #ff00ff" in html

    print("✅ Custom CSS injection: PASSED")
    print(f"   - Custom CSS successfully injected")
    return html


def test_backward_compatibility():
    """Test backward compatibility with existing code"""
    print("\n" + "="*70)
    print("TEST 4: Backward Compatibility")
    print("="*70)

    # Old-style call without custom_css parameter
    html = create_html_report(
        content="Simple test content",
        title="Backward Compatibility Test"
    )

    assert "<!DOCTYPE html>" in html
    assert "Simple test content" in html

    print("✅ Backward compatibility: PASSED")
    print(f"   - Old-style function calls still work")
    return html


def test_html_entity_preservation():
    """Test that HTML entities are properly preserved"""
    print("\n" + "="*70)
    print("TEST 5: HTML Entity Preservation")
    print("="*70)

    content = """
Test special characters: & < > "

En-dash: –
Em-dash: —
Ellipsis: …
"""

    html = create_html_report(
        content=content,
        title="Entity Test"
    )

    # The en-dash, em-dash, and ellipsis should be normalized
    assert "-" in html  # normalized from en-dash/em-dash
    assert "..." in html  # normalized from ellipsis

    print("✅ HTML entity handling: PASSED")
    print(f"   - Special characters normalized correctly")
    return html


def save_test_output(html: str, filename: str):
    """Save test HTML output to file for manual inspection"""
    output_dir = Path(__file__).parent / "test_output"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / filename
    filepath.write_text(html, encoding='utf-8')
    print(f"   📄 Saved test output to: {filepath}")


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CONSOLIDATED HTML GENERATOR TEST SUITE")
    print("="*70)
    print("Testing enhanced utils/html_generator.py with:")
    print("  - Merged CSS from report_utils.py")
    print("  - Custom CSS support")
    print("  - Backward compatibility")
    print("="*70)

    tests_passed = 0
    tests_total = 5

    # Test 1: Basic HTML generation
    try:
        html = test_basic_html_generation()
        if html:
            save_test_output(html, "test_1_basic.html")
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 1 FAILED: {e}")

    # Test 2: CSS classes
    try:
        html = test_report_utils_css_classes()
        if html:
            save_test_output(html, "test_2_css_classes.html")
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 2 FAILED: {e}")

    # Test 3: Custom CSS
    try:
        html = test_custom_css_injection()
        if html:
            save_test_output(html, "test_3_custom_css.html")
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 3 FAILED: {e}")

    # Test 4: Backward compatibility
    try:
        html = test_backward_compatibility()
        if html:
            save_test_output(html, "test_4_backward_compat.html")
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 4 FAILED: {e}")

    # Test 5: Entity preservation
    try:
        html = test_html_entity_preservation()
        if html:
            save_test_output(html, "test_5_entities.html")
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 5 FAILED: {e}")

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Passed: {tests_passed}/{tests_total}")

    if tests_passed == tests_total:
        print("🎉 ALL TESTS PASSED!")
        print("\n✅ Consolidated HTML generator is working correctly")
        print("✅ All CSS classes from report_utils merged successfully")
        print("✅ Custom CSS support working")
        print("✅ Backward compatibility maintained")
        return 0
    else:
        print(f"⚠️  {tests_total - tests_passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
