#!/usr/bin/env python3
"""
Test HTML entity escaping in SandboxedExecutorTool
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
        self.assertIn("&quot;quoted text&quot;", html_content, 
                      "Double quotes should be escaped to &quot;")
        
        # Single quotes might be &#39; or &apos; depending on implementation
        has_single_escape = "&#39;quoted text&#39;" in html_content or "&apos;quoted text&apos;" in html_content
        self.assertTrue(has_single_escape, 
                       "Single quotes should be escaped to &#39; or &apos;")

        # Check for the combined example
        self.assertIn("&lt;div class=&quot;test&quot; id='example'&gt;Content &amp; More&lt;/div>", html_content,
                      "Combined tags and content should be properly escaped")

        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)

if __name__ == '__main__':
    unittest.main()