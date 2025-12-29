import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from plugins.handlers import social_media_wordpress

async def main():
    """Main function to test the WordPress plugin."""
    # Simulate the plugin execution environment by setting the ENV variable names
    # This allows the plugin to know which variables to look for in the .env file
    os.environ['WORDPRESS_URL_ENV'] = 'WORDPRESS_URL'
    os.environ['WORDPRESS_USERNAME_ENV'] = 'WORDPRESS_USERNAME'
    os.environ['WORDPRESS_APP_PASSWORD_ENV'] = 'WORDPRESS_APP_PASSWORD'

    # Load environment variables from .env file
    load_dotenv()

    # Test data
    parameters = {
        "title": "Test Post from Raica - Formatting and Draft Test",
        "content": "# Main Heading\n\nThis is a paragraph with **bold text** and a [link to Google](https://google.com).\n\nThis is a second paragraph that should be separate.\n\n## Sub-heading\n\n* List item 1\n* List item 2",
        "status": "draft",  # Explicitly test that the post is created as a draft
        "categories": ["Technology", "AI", "Testing"],
        "tags": ["testing", "wordpress", "api", "gemini-test"]
    }

    print("--- Testing WordPress Plugin ---")
    result = await social_media_wordpress.execute(parameters)
    print("--- Result ---")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
