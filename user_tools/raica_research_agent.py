"""
RAICA Research Agent - Sub-Agent Tool
=====================================

Delegates complex research, web search, and summarization tasks to the RAICA server API.

The RAICA server has full access to:
- Web search capabilities
- News aggregation
- Document search
- Research paper lookup
- Summarization and analysis

This tool allows the coding agent to delegate complex research tasks to the RAICA server
as a sub-agent, rather than trying to implement them locally.
"""

import sys
from pathlib import Path

# Add RAICA root to path for imports
raica_root = Path(__file__).parent.parent
sys.path.insert(0, str(raica_root))

from user_tools.base_user_tool import BaseUserTool
from agents.coding_agent.knowledge.raica_client import RAICAKnowledgeClient
import asyncio


class RAICAResearchAgent(BaseUserTool):
    """
    RAICA Research Agent - Delegates complex tasks to RAICA server API.

    Use this tool for:
    - Multi-step workflows ("research news and email it to X")
    - Web searches ("latest news on...", "current information about...")
    - Research and summarization ("research X and summarize")
    - Email sending with research ("find Y and email results to Z")
    - File creation with content ("create PDF with stock analysis")
    - Any complex task requiring multiple steps or external services

    The RAICA server has access to ALL tools (web search, news APIs, email sender,
    PDF generator, etc.) and can orchestrate complete multi-step workflows end-to-end.
    """

    name = "raica_research_agent"
    description = "Delegate complex multi-step tasks to RAICA server as a sub-agent. RAICA server has access to ALL tools and capabilities including web search, news lookup, email sending (via secure_email_sender), file creation, research, summarization, and more. Can handle complete workflows end-to-end. Use for ANY task that requires multiple steps, web access, external services, or complex orchestration. Simply pass the entire user request - RAICA server will break it down, execute all steps, and complete the full workflow."
    category = "research"

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The complete task or workflow to delegate to RAICA server. Can be a simple query ('latest news') or a complex multi-step request ('research news and email summary to user@example.com'). Be specific and include ALL requirements."
            },
            "task_type": {
                "type": "string",
                "enum": ["web_search", "news_lookup", "research", "summarize", "multi_step_workflow", "general"],
                "description": "Type of task: 'multi_step_workflow' for complex requests with multiple steps (research + email, etc.), 'web_search'/'news_lookup'/'research'/'summarize' for focused tasks, 'general' for anything else",
                "default": "general"
            }
        },
        "required": ["query"]
    }

    def __init__(self):
        """Initialize the RAICA research agent."""
        # Default to Docker bridge IP for RAICA server
        # This allows the agent to call the server even from inside containers
        self.base_url = "http://172.17.0.1:5000"
        self.client = None

    async def _get_client(self) -> RAICAKnowledgeClient:
        """Get or create RAICA client."""
        if self.client is None:
            self.client = RAICAKnowledgeClient(
                base_url=self.base_url,
                model="RAICA-Model1",
                timeout=120.0,  # Research can take time
                enable_cache=True
            )
        return self.client

    def _extract_metadata(self, response_text: str) -> dict:
        """
        Extract structured metadata from LLM response.

        Looks for ## AGENT_METADATA section with JSON block.
        Returns parsed metadata dict or empty dict if not found.
        """
        import re
        import json

        try:
            # Look for metadata block in response
            # Pattern: ## AGENT_METADATA followed by ```json {...} ```
            pattern = r'## AGENT_METADATA\s*```json\s*(\{.*?\})\s*```'
            match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)

            if match:
                json_str = match.group(1)
                metadata = json.loads(json_str)

                # Validate metadata structure
                if isinstance(metadata, dict):
                    print(f"✅ Extracted metadata from server response: {list(metadata.keys())}")
                    return metadata
                else:
                    print(f"⚠️ Metadata found but not a dict: {type(metadata)}")
                    return {}
            else:
                # LLM didn't include metadata - this is OK, fallback to fuzzy matching
                print(f"ℹ️ No structured metadata in response (will use fuzzy matching for files)")
                return {}

        except json.JSONDecodeError as e:
            print(f"⚠️ Failed to parse metadata JSON: {e}")
            return {}
        except Exception as e:
            print(f"⚠️ Error extracting metadata: {e}")
            return {}

        return {}

    async def execute(self, query: str, task_type: str = "general") -> dict:
        """
        Delegate a research task to the RAICA server.

        Args:
            query: The research query or task
            task_type: Type of research (web_search, news_lookup, research, summarize, general)

        Returns:
            dict with 'success', 'result', and optional 'error'
        """
        try:
            client = await self._get_client()

            # Check if RAICA server is available
            available = await client.is_available()
            if not available:
                return {
                    'success': False,
                    'error': f'RAICA server not available at {self.base_url}. Make sure the server is running.'
                }

            # Build system message based on task type
            # CRITICAL: For agent-to-agent communication, request structured metadata in final response
            metadata_instruction = '''

CRITICAL - FINAL RESPONSE FORMAT:
After completing all work, your FINAL response to the calling agent MUST include a structured metadata block at the END:

## AGENT_METADATA
```json
{
  "files_created": ["exact_filename1.html", "exact_filename2.pdf"],
  "files_modified": ["existing_file.txt"],
  "email_sent": {
    "to": ["recipient@example.com"],
    "subject": "Email subject",
    "attachments": ["exact_filename1.html"]
  },
  "task_completed": true
}
```

Rules for metadata:
- Use EXACT filenames (with extensions) as created/saved
- Include full relative paths if files are in subdirectories
- If no files created, use empty array: "files_created": []
- If no email sent, omit "email_sent" key
- This metadata is for the calling AGENT to parse, not for human display
'''

            system_messages = {
                'web_search': 'You are a web research assistant. Search the web for current information and provide comprehensive results.' + metadata_instruction,
                'news_lookup': 'You are a news researcher. Find and summarize the latest news on the requested topic.' + metadata_instruction,
                'research': 'You are a research assistant. Conduct thorough research and provide well-sourced findings.' + metadata_instruction,
                'summarize': 'You are a summarization expert. Provide concise, accurate summaries of complex information.' + metadata_instruction,
                'multi_step_workflow': 'You are a multi-step workflow orchestrator with access to ALL tools (web search, news APIs, email sender, PDF generator, etc.). Break down the complete request into steps, execute each step using available tools, and complete the entire workflow end-to-end.' + metadata_instruction,
                'general': 'You are a helpful assistant with access to ALL tools including web search, news APIs, email sending, file creation, and more. Complete the entire request end-to-end using whatever tools are needed.' + metadata_instruction
            }

            system_message = system_messages.get(task_type, system_messages['general'])

            # Query RAICA server
            result = await client._query_raica(query, system_message=system_message)

            if result is None:
                return {
                    'success': False,
                    'error': 'RAICA server returned no response. Check server logs for details.'
                }

            # Extract structured metadata from response (if LLM included it)
            metadata = self._extract_metadata(result)

            response = {
                'success': True,
                'result': result,
                'source': 'RAICA-Model1',
                'base_url': self.base_url
            }

            # Include metadata if found
            if metadata:
                response['metadata'] = metadata

            return response

        except Exception as e:
            return {
                'success': False,
                'error': f'Error calling RAICA research agent: {str(e)}'
            }
        finally:
            # Don't close client - reuse for future requests
            pass


# For standalone testing
async def test_raica_research_agent():
    """Test the RAICA research agent."""
    agent = RAICAResearchAgent()

    print(f"Testing RAICA Research Agent at {agent.base_url}")
    print("=" * 60)

    # Test 1: Simple query
    print("\nTest 1: Web search")
    result = await agent.execute(
        query="What are the latest developments in AI in 2026?",
        task_type="web_search"
    )

    if result['success']:
        print(f"✅ Success!")
        print(f"Result: {result['result'][:200]}...")
    else:
        print(f"❌ Failed: {result.get('error')}")

    # Test 2: News lookup
    print("\nTest 2: News lookup")
    result = await agent.execute(
        query="Latest national news in the United States today",
        task_type="news_lookup"
    )

    if result['success']:
        print(f"✅ Success!")
        print(f"Result: {result['result'][:200]}...")
    else:
        print(f"❌ Failed: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(test_raica_research_agent())
