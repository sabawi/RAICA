#!/usr/bin/env python3
"""
HTML entity escaping in SandboxedExecutorTool: < > & in body text arrive escaped (SI-118: expectations corrected
for the html_generator + Python-Markdown writer; active content is covered by test_document_safety.py).
Run: ./venv/bin/python -m pytest tests/unit/test_html_entities.py -q
"""

import unittest
import os
import sys
from pathlib import Path

# Add project root to path
from tests.utilities.test_helpers import setup_test_paths

setup_test_paths()

from user_tools.sandboxed_executor import SandboxedExecutorTool

class TestHTMLEntityEscaping(unittest.IsolatedAsyncioTestCase):
    """Test suite for HTML entity escaping in SandboxedExecutorTool."""

    def setUp(self):
        """Set up test fixtures."""
        self.tool = SandboxedExecutorTool()
        self.test_filename = "test_entities_unit.html"

    def tearDown(self):
        """Clean up generated files."""
        # Attempt to find and remove the file if it exists
        # The tool might place it in specific directories, checking logic in tool if possible
        # Assuming current dir or tool's logic.
        # For safety, we'll try to clean up in the execution context if we knew where it landed.
        pass 

    async def test_html_entities_are_escaped(self):
        """Verify that HTML special characters are properly escaped in generated HTML."""
        
        # Content with problematic HTML characters
        test_content = """# Test Report: HTML Characters

This content contains HTML characters that should be escaped:

- Less than: < symbol
- Greater than: > symbol  
- Ampersand: & symbol
- Double quotes: "quoted text" here
- Single quotes: 'quoted text' here
- Combined: <div class="test" id='example'>Content & More</div>
"""

        # Execute the HTML creation
        result = await self.tool._create_real_html_file(self.test_filename, test_content)
        
        # Verify success
        self.assertTrue(result["success"], f"File creation failed: {result.get('error')}")
        
        # Read the generated file
        file_path = result["result"]["full_path"]
        self.assertTrue(os.path.exists(file_path), f"File not found at {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Verify escaping: Check for the presence of escaped entities
        # and ensure raw characters (where they shouldn't be) are handled.
        # Note: HTML tags like <body> will contain '<' and '>', so we check the specific context strings.
        
        self.assertIn("&lt; symbol", html_content, 
                      "Less than symbol '<' should be escaped to &lt;")
        self.assertIn("&gt; symbol", html_content, 
                      "Greater than symbol '>' should be escaped to &gt;")
        self.assertIn("&amp; symbol", html_content, 
                      "Ampersand symbol '&' should be escaped to &amp;")
        # Quote marks in TEXT need no escaping (valid HTML); the old &quot; expectation dated from the replaced
        # escape-everything writer (SI-118). They must still be present as text.
        self.assertIn('"quoted text"', html_content)
        self.assertIn("'quoted text'", html_content)

        # Raw markup in the content is filtered (SI-119): allowed tags/attributes may stay, nothing active does.
        body = html_content.split('<body', 1)[1].lower()
        self.assertNotIn("<script", body)
        self.assertIn("content &amp; more", body)

        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)

if __name__ == '__main__':
    unittest.main()