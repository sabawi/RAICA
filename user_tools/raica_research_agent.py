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
    RAICA Research Agent - Delegates research tasks to RAICA server API.

    Use this tool for:
    - Web searches ("latest news on...", "current information about...")
    - Research and summarization ("research X and summarize")
    - News lookups ("latest national news in last 24 hours")
    - Complex queries requiring web access

    The RAICA server will use its full suite of tools (web search, news APIs,
    document search) to answer the query.
    """

    name = "raica_research_agent"
    description = "Delegate research, web search, news lookup, and summarization tasks to RAICA server as sub-agent. Use for ANY task requiring web access, current information, or research."
    category = "research"

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The research query or task to delegate to RAICA server. Be specific about what information you need."
            },
            "task_type": {
                "type": "string",
                "enum": ["web_search", "news_lookup", "research", "summarize", "general"],
                "description": "Type of research task (helps RAICA server optimize its approach)",
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
            system_messages = {
                'web_search': 'You are a web research assistant. Search the web for current information and provide comprehensive results.',
                'news_lookup': 'You are a news researcher. Find and summarize the latest news on the requested topic.',
                'research': 'You are a research assistant. Conduct thorough research and provide well-sourced findings.',
                'summarize': 'You are a summarization expert. Provide concise, accurate summaries of complex information.',
                'general': 'You are a helpful research assistant with access to web search, news APIs, and document search. Answer the query thoroughly.'
            }

            system_message = system_messages.get(task_type, system_messages['general'])

            # Query RAICA server
            result = await client._query_raica(query, system_message=system_message)

            if result is None:
                return {
                    'success': False,
                    'error': 'RAICA server returned no response. Check server logs for details.'
                }

            return {
                'success': True,
                'result': result,
                'source': 'RAICA-Model1',
                'base_url': self.base_url
            }

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
