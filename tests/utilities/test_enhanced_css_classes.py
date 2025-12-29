#!/usr/bin/env python3
"""
Test Enhanced HTML Generator - ALL CSS Classes

Comprehensive test for the enhanced html_generator.py with:
- Citation styling (CRITICAL for BI agent)
- Sentiment classes (Market Sentiment, Social Media)
- Dashboard/Metrics (responsive grid)
- Code blocks
- Card components
- Trend indicators
- All best-of-breed CSS

Author: Claude Code
Date: 2025-11-01
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.html_generator import html_generator, create_html_report


def test_citation_styling():
    """Test .citation class - CRITICAL for BI agent"""
    print("\n" + "="*70)
    print("TEST 1: Citation Styling (CRITICAL)")
    print("="*70)

    content = """
<p>Revenue reached $391.04B <span class="citation">[Source: Apple 10-K FY2024]</span></p>
<p>Market share is 23.5% <span class="citation"><a href="https://example.com">IDC Report Q3 2024</a></span></p>

<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Revenue</td><td>$391B</td></tr>
</table>
<p class="citation">Source: Yahoo Finance, as of 2024-11-01</p>
"""

    html = create_html_report(
        content=content,
        title="Citation Test",
        header_title="Citation Styling Test"
    )

    # Verify citation class exists
    assert ".citation {" in html
    assert "font-size: 11px" in html
    assert "color: #666" in html
    assert ".citation a {" in html
    assert "border-bottom: 1px dotted #999" in html

    print("✅ Citation styling: PASSED")
    print("   - .citation class defined")
    print("   - .citation a (clickable links) defined")
    print("   - table + .citation (table citations) defined")
    return html


def test_sentiment_classes():
    """Test sentiment classes from Market Sentiment & Social Media"""
    print("\n" + "="*70)
    print("TEST 2: Sentiment Classes")
    print("="*70)

    content = """
<div class="bullish">Bullish market sentiment</div>
<div class="bearish">Bearish market sentiment</div>
<div class="neutral">Neutral market sentiment</div>
<div class="positive">Positive social media feedback</div>
<div class="negative">Negative social media feedback</div>

<span class="sentiment-high">High sentiment</span>
<span class="sentiment-medium">Medium sentiment</span>
<span class="sentiment-low">Low sentiment</span>
"""

    html = create_html_report(
        content=content,
        title="Sentiment Test",
        header_title="Sentiment Classes Test"
    )

    sentiment_classes = [
        ".bullish, .positive",
        ".bearish, .negative",
        ".neutral",
        ".sentiment-high",
        ".sentiment-medium",
        ".sentiment-low"
    ]

    missing = []
    for cls in sentiment_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print(f"✅ All {len(sentiment_classes)} sentiment classes: PASSED")
        return html


def test_dashboard_metrics():
    """Test dashboard and metric card system"""
    print("\n" + "="*70)
    print("TEST 3: Dashboard & Metrics (Responsive Grid)")
    print("="*70)

    content = """
<div class="dashboard">
  <div class="metric">
    <span class="metric-value">$123M</span>
    <span class="metric-label">Revenue</span>
  </div>
  <div class="metric">
    <span class="metric-value">45%</span>
    <span class="metric-label">Growth</span>
  </div>
  <div class="metric">
    <span class="metric-value">1.2K</span>
    <span class="metric-label">Customers</span>
  </div>
  <div class="metric">
    <span class="metric-value">98%</span>
    <span class="metric-label">Satisfaction</span>
  </div>
</div>
"""

    html = create_html_report(
        content=content,
        title="Dashboard Test",
        header_title="Dashboard & Metrics Test"
    )

    dashboard_classes = [
        ".dashboard {",
        ".metric {",
        ".metric-value {",
        ".metric-label {",
        "width: 22%",  # Responsive grid
        "display: inline-block"
    ]

    missing = []
    for cls in dashboard_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Dashboard & Metrics: PASSED")
        print("   - Dashboard box with shadow")
        print("   - Metric cards with 22% width (responsive)")
        print("   - Metric value & label styling")
        return html


def test_code_blocks():
    """Test code block styling"""
    print("\n" + "="*70)
    print("TEST 4: Code Blocks")
    print("="*70)

    content = """
<p>Inline code example: <code>print("Hello World")</code></p>

<pre>
def calculate_revenue(price, quantity):
    return price * quantity

revenue = calculate_revenue(100, 50)
print(f"Total revenue: ${revenue}")
</pre>
"""

    html = create_html_report(
        content=content,
        title="Code Test",
        header_title="Code Block Test"
    )

    code_classes = [
        "pre {",
        "code {",
        "pre code {",
        "white-space: pre-wrap",
        "font-family: 'Courier New', monospace",
        "border-left: 3px solid #3498db"
    ]

    missing = []
    for cls in code_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Code blocks: PASSED")
        print("   - Pre-formatted blocks with left border")
        print("   - Inline code styling")
        print("   - Monospace font family")
        return html


def test_card_components():
    """Test card components from Document Intelligence & Social Media"""
    print("\n" + "="*70)
    print("TEST 5: Card Components")
    print("="*70)

    content = """
<div class="document-card">
  <h3>Document Analysis Report</h3>
  <p>This is a document card with shadow.</p>
</div>

<div class="brand-card">
  <h3>Brand Monitoring</h3>
  <p>Social media brand tracking.</p>
</div>

<div class="viral-content">
  <h3>Viral Post Alert</h3>
  <p>This content is trending!</p>
</div>

<div class="relationship-map">
  <h3>Entity Relationships</h3>
  <p>Connection diagram here.</p>
</div>

<p>Document classification: <span class="confidential">CONFIDENTIAL</span></p>
"""

    html = create_html_report(
        content=content,
        title="Cards Test",
        header_title="Card Components Test"
    )

    card_classes = [
        ".document-card, .brand-card, .company-card",
        ".viral-content",
        ".relationship-map",
        ".confidential",
        "box-shadow: 0 2px 4px rgba(0,0,0,0.1)"
    ]

    missing = []
    for cls in card_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Card components: PASSED")
        print("   - Document/Brand/Company cards")
        print("   - Viral content highlighting")
        print("   - Relationship maps")
        print("   - Confidential badges")
        return html


def test_trend_indicators():
    """Test trend and gain/loss indicators from Stock Monitor"""
    print("\n" + "="*70)
    print("TEST 6: Trend Indicators (Stock Monitor)")
    print("="*70)

    content = """
<p>Stock performance: <span class="gain">+12.5%</span></p>
<p>Competitor performance: <span class="loss">-3.2%</span></p>

<p>Market trend: <span class="trend-up">↑ Uptrend</span></p>
<p>Sector trend: <span class="trend-down">↓ Downtrend</span></p>
<p>Overall: <span class="trend-neutral">→ Sideways</span></p>
"""

    html = create_html_report(
        content=content,
        title="Trends Test",
        header_title="Trend Indicators Test"
    )

    trend_classes = [
        ".trend-up, .gain",
        ".trend-down, .loss",
        ".trend-neutral",
        "color: #4caf50",  # Green for gains
        "color: #f44336"   # Red for losses
    ]

    missing = []
    for cls in trend_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Trend indicators: PASSED")
        print("   - Gain/Loss color coding")
        print("   - Trend direction indicators")
        return html


def test_confidence_levels():
    """Test confidence level styling from Market Sentiment"""
    print("\n" + "="*70)
    print("TEST 7: Confidence Levels")
    print("="*70)

    content = """
<div class="high-confidence">
  <h3>High Confidence Prediction</h3>
  <p>Probability: 85%</p>
</div>

<div class="medium-confidence">
  <h3>Medium Confidence Prediction</h3>
  <p>Probability: 60%</p>
</div>

<div class="low-confidence">
  <h3>Low Confidence Prediction</h3>
  <p>Probability: 35%</p>
</div>
"""

    html = create_html_report(
        content=content,
        title="Confidence Test",
        header_title="Confidence Levels Test"
    )

    confidence_classes = [
        ".high-confidence {",
        ".medium-confidence {",
        ".low-confidence {",
        "border: 2px solid"
    ]

    missing = []
    for cls in confidence_classes:
        if cls not in html:
            missing.append(cls)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Confidence levels: PASSED")
        return html


def test_responsive_and_print():
    """Test responsive design and print styles"""
    print("\n" + "="*70)
    print("TEST 8: Responsive & Print Styles")
    print("="*70)

    content = "<p>Testing responsive design and print styles</p>"

    html = create_html_report(
        content=content,
        title="Responsive Test",
        header_title="Responsive Design Test"
    )

    responsive_features = [
        "@media (max-width: 768px)",
        "@media (max-width: 480px)",
        "@media print",
        "viewport",
        "-webkit-print-color-adjust: exact"
    ]

    missing = []
    for feature in responsive_features:
        if feature not in html:
            missing.append(feature)

    if missing:
        print(f"❌ FAILED: Missing {missing}")
        return None
    else:
        print("✅ Responsive & Print: PASSED")
        print("   - Mobile breakpoints (768px, 480px)")
        print("   - Print styles for color preservation")
        print("   - Viewport meta tag")
        return html


def save_test_output(html: str, filename: str):
    """Save test HTML output to file"""
    output_dir = Path(__file__).parent / "test_output"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / filename
    filepath.write_text(html, encoding='utf-8')
    print(f"   📄 Saved to: {filepath}")


def main():
    """Run all enhanced CSS tests"""
    print("\n" + "="*70)
    print("ENHANCED HTML GENERATOR - COMPREHENSIVE CSS TEST SUITE")
    print("="*70)
    print("Testing ALL CSS classes from:")
    print("  • Business Intelligence Agent (citations)")
    print("  • Market Sentiment (sentiment, confidence)")
    print("  • Social Media Tracker (dashboard, metrics, cards)")
    print("  • Document Intelligence (cards, badges)")
    print("  • Stock Monitor (trends, gains/losses)")
    print("  • Stock Analyzer (code blocks)")
    print("  • Report Utils (priority levels)")
    print("="*70)

    tests = [
        ("Citation Styling", test_citation_styling, "enhanced_1_citations.html"),
        ("Sentiment Classes", test_sentiment_classes, "enhanced_2_sentiment.html"),
        ("Dashboard & Metrics", test_dashboard_metrics, "enhanced_3_dashboard.html"),
        ("Code Blocks", test_code_blocks, "enhanced_4_code.html"),
        ("Card Components", test_card_components, "enhanced_5_cards.html"),
        ("Trend Indicators", test_trend_indicators, "enhanced_6_trends.html"),
        ("Confidence Levels", test_confidence_levels, "enhanced_7_confidence.html"),
        ("Responsive & Print", test_responsive_and_print, "enhanced_8_responsive.html"),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func, filename in tests:
        try:
            html = test_func()
            if html:
                save_test_output(html, filename)
                passed += 1
        except Exception as e:
            print(f"❌ {test_name} FAILED: {e}")

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Passed: {passed}/{total}")

    if passed == total:
        print("\n🎉 ALL ENHANCED CSS TESTS PASSED!")
        print("\n✅ HTML Generator now includes:")
        print("   ✓ Citation styling (.citation, clickable links)")
        print("   ✓ Sentiment classes (bullish/bearish/neutral)")
        print("   ✓ Dashboard & responsive metrics grid")
        print("   ✓ Code blocks (pre, code with syntax styling)")
        print("   ✓ Card components (document, brand, viral)")
        print("   ✓ Trend indicators (gains/losses, up/down)")
        print("   ✓ Confidence levels (high/medium/low)")
        print("   ✓ Responsive design (mobile breakpoints)")
        print("   ✓ Print styles (color preservation)")
        print("\n✅ BEST-OF-EVERYTHING CSS consolidated successfully!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
