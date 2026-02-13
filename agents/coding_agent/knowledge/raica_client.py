"""
RAICA Knowledge Client
======================

Client for RAICA Server API knowledge lookup.
Uses RAICA's agentic tools for web search, document search, and API documentation.

Features:
- Web search via RAICA's search_web tool
- Document search via document_search tool
- API documentation lookup via lookup_website tool
- Result caching to avoid redundant queries
"""

import asyncio
import httpx
import logging
import json
import hashlib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    content: str
    source: str
    relevance: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeQueryResult:
    """Result from a knowledge query."""
    success: bool
    query: str
    results: List[SearchResult]
    error: Optional[str] = None
    cached: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ResultCache:
    """Simple in-memory cache for query results."""

    def __init__(self, ttl_minutes: int = 30):
        self._cache: Dict[str, KnowledgeQueryResult] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def _make_key(self, query_type: str, query: str) -> str:
        """Create a cache key."""
        content = f"{query_type}:{query}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, query_type: str, query: str) -> Optional[KnowledgeQueryResult]:
        """Get cached result if valid."""
        key = self._make_key(query_type, query)

        if key not in self._cache:
            return None

        result = self._cache[key]

        # Check if expired
        cached_time = datetime.fromisoformat(result.timestamp)
        if datetime.now() - cached_time > self._ttl:
            del self._cache[key]
            return None

        result.cached = True
        return result

    def set(self, query_type: str, query: str, result: KnowledgeQueryResult):
        """Cache a result."""
        key = self._make_key(query_type, query)
        self._cache[key] = result

    def clear(self):
        """Clear all cached results."""
        self._cache.clear()


class RAICAKnowledgeClient:
    """
    Client for RAICA Server API knowledge lookup.

    Uses the OpenAI-compatible chat completions endpoint with agentic tools
    to perform web searches, document lookups, and API documentation retrieval.
    """

    DEFAULT_MODEL = "RAICA-Model1"
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        enable_cache: bool = True,
        cache_ttl_minutes: int = 30
    ):
        """
        Initialize RAICA knowledge client.

        Args:
            base_url: RAICA server URL
            model: Model to use (default: RAICA-Model1)
            timeout: Request timeout in seconds
            enable_cache: Whether to cache results
            cache_ttl_minutes: Cache TTL in minutes
        """
        self.base_url = base_url.rstrip('/')
        self.chat_endpoint = f"{self.base_url}/v1/chat/completions"
        self.health_endpoint = f"{self.base_url}/health"
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout
        self._cache = ResultCache(cache_ttl_minutes) if enable_cache else None
        self._client: Optional[httpx.AsyncClient] = None

        logger.debug(f"RAICAKnowledgeClient initialized: {base_url}")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        """Close the client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def is_available(self) -> bool:
        """Check if RAICA server is available."""
        try:
            client = await self._get_client()
            response = await client.get(self.health_endpoint, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"RAICA server not available: {e}")
            return False

    async def _query_raica(
        self,
        prompt: str,
        system_message: Optional[str] = None
    ) -> Optional[str]:
        """
        Send a query to RAICA and get the response.

        Args:
            prompt: User prompt
            system_message: Optional system message

        Returns:
            Response content or None on error
        """
        try:
            messages = []

            if system_message:
                messages.append({"role": "system", "content": system_message})

            messages.append({"role": "user", "content": prompt})

            client = await self._get_client()
            response = await client.post(
                self.chat_endpoint,
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False
                    # max_tokens uses server default from llm_config.yaml
                }
            )

            if response.status_code != 200:
                logger.error(f"RAICA query failed: {response.status_code}")
                return None

            data = response.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            return content

        except Exception as e:
            logger.error(f"RAICA query error: {e}")
            return None

    def _parse_search_results(self, content: str) -> List[SearchResult]:
        """Parse search results from response content."""
        results = []

        # Try to parse as pure JSON first
        try:
            data = json.loads(content)
            return self._extract_results_from_json(data)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks (```json ... ``` or ``` ... ```)
        import re
        json_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
        matches = re.findall(json_block_pattern, content)
        for match in matches:
            try:
                data = json.loads(match.strip())
                extracted = self._extract_results_from_json(data)
                if extracted:
                    logger.debug(f"Extracted {len(extracted)} results from markdown JSON block")
                    return extracted
            except json.JSONDecodeError:
                continue

        # Try to find JSON array anywhere in content (starts with [ and ends with ])
        json_array_pattern = r'\[\s*\{[\s\S]*?\}\s*\]'
        matches = re.findall(json_array_pattern, content)
        for match in matches:
            try:
                data = json.loads(match)
                extracted = self._extract_results_from_json(data)
                if extracted:
                    logger.debug(f"Extracted {len(extracted)} results from inline JSON array")
                    return extracted
            except json.JSONDecodeError:
                continue

        # Fallback: treat as plain text result (but warn)
        if content:
            logger.warning("Could not parse JSON from RAICA response, using raw text fallback")
            results.append(SearchResult(
                title="Search Result",
                content=content[:2000],
                source="RAICA"
            ))

        return results

    def _extract_results_from_json(self, data) -> List[SearchResult]:
        """Extract SearchResult objects from parsed JSON data."""
        results = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    results.append(SearchResult(
                        title=item.get('title', 'Untitled'),
                        content=item.get('content', item.get('snippet', '')),
                        source=item.get('source', item.get('url', '')),
                        relevance=float(item.get('relevance', 0.0))
                    ))
        elif isinstance(data, dict) and 'results' in data:
            for item in data['results']:
                if isinstance(item, dict):
                    results.append(SearchResult(
                        title=item.get('title', 'Untitled'),
                        content=item.get('content', item.get('snippet', '')),
                        source=item.get('source', item.get('url', '')),
                        relevance=float(item.get('relevance', 0.0))
                    ))

        return results

    async def search_web(self, query: str, max_results: int = 5) -> KnowledgeQueryResult:
        """
        Search the web via RAICA's search_web tool.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            KnowledgeQueryResult with search results
        """
        # Check cache
        if self._cache:
            cached = self._cache.get('web', query)
            if cached:
                logger.debug(f"Cache hit for web search: {query[:50]}")
                return cached

        prompt = f"""Use the search_web tool to find information about:
{query}

Return the top {max_results} most relevant results as a JSON array with objects containing:
- title: Page title
- content: Brief summary of relevant content
- source: URL or source name
- relevance: Score from 0.0 to 1.0"""

        content = await self._query_raica(prompt)

        if content is None:
            return KnowledgeQueryResult(
                success=False,
                query=query,
                results=[],
                error="Failed to query RAICA server"
            )

        results = self._parse_search_results(content)

        result = KnowledgeQueryResult(
            success=True,
            query=query,
            results=results[:max_results]
        )

        # Cache result
        if self._cache:
            self._cache.set('web', query, result)

        return result

    async def search_documents(
        self,
        query: str,
        max_results: int = 5
    ) -> KnowledgeQueryResult:
        """
        Search documents via RAICA's document_search tool.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            KnowledgeQueryResult with document results
        """
        # Check cache
        if self._cache:
            cached = self._cache.get('doc', query)
            if cached:
                logger.debug(f"Cache hit for doc search: {query[:50]}")
                return cached

        prompt = f"""Use the document_search tool to find relevant documentation about:
{query}

Return the most relevant documents as a JSON array with objects containing:
- title: Document or section title
- content: Relevant content excerpt
- source: Document path or name
- relevance: Score from 0.0 to 1.0"""

        content = await self._query_raica(prompt)

        if content is None:
            return KnowledgeQueryResult(
                success=False,
                query=query,
                results=[],
                error="Failed to query RAICA server"
            )

        results = self._parse_search_results(content)

        result = KnowledgeQueryResult(
            success=True,
            query=query,
            results=results[:max_results]
        )

        # Cache result
        if self._cache:
            self._cache.set('doc', query, result)

        return result

    async def lookup_api_docs(
        self,
        api_name: str,
        specific_topic: Optional[str] = None
    ) -> KnowledgeQueryResult:
        """
        Look up API documentation via RAICA's lookup_website tool.

        Args:
            api_name: Name of the API or library
            specific_topic: Optional specific topic to focus on

        Returns:
            KnowledgeQueryResult with API documentation
        """
        query = f"{api_name} API"
        if specific_topic:
            query += f" {specific_topic}"

        # Check cache
        if self._cache:
            cached = self._cache.get('api', query)
            if cached:
                logger.debug(f"Cache hit for API lookup: {query[:50]}")
                return cached

        prompt = f"""Use the lookup_website tool to get documentation for the {api_name} API.
{f'Specifically focus on: {specific_topic}' if specific_topic else ''}

Provide a comprehensive summary including:
1. Key API endpoints or methods
2. Required parameters
3. Return values
4. Usage examples
5. Common patterns and best practices

Format as JSON with structure:
{{
    "results": [
        {{
            "title": "Section name",
            "content": "Documentation content",
            "source": "Documentation URL"
        }}
    ]
}}"""

        content = await self._query_raica(prompt)

        if content is None:
            return KnowledgeQueryResult(
                success=False,
                query=query,
                results=[],
                error="Failed to query RAICA server"
            )

        results = self._parse_search_results(content)

        result = KnowledgeQueryResult(
            success=True,
            query=query,
            results=results
        )

        # Cache result
        if self._cache:
            self._cache.set('api', query, result)

        return result

    async def search_patterns(
        self,
        requirements: List[str],
        language: str = "python"
    ) -> KnowledgeQueryResult:
        """
        Search for implementation patterns relevant to requirements.

        Args:
            requirements: List of requirements to find patterns for
            language: Programming language

        Returns:
            KnowledgeQueryResult with pattern suggestions
        """
        # Combine requirements into search query
        query = f"{language} implementation patterns for: " + "; ".join(requirements[:3])

        # Check cache
        if self._cache:
            cached = self._cache.get('pattern', query)
            if cached:
                logger.debug(f"Cache hit for pattern search: {query[:50]}")
                return cached

        prompt = f"""Search for best practices and implementation patterns for the following requirements in {language}:

{chr(10).join(f'- {r}' for r in requirements)}

Find and summarize:
1. Common design patterns used
2. Library recommendations
3. Code structure suggestions
4. Potential pitfalls to avoid

Return as JSON array of relevant patterns and recommendations."""

        content = await self._query_raica(prompt)

        if content is None:
            return KnowledgeQueryResult(
                success=False,
                query=query,
                results=[],
                error="Failed to query RAICA server"
            )

        results = self._parse_search_results(content)

        result = KnowledgeQueryResult(
            success=True,
            query=query,
            results=results
        )

        # Cache result
        if self._cache:
            self._cache.set('pattern', query, result)

        return result

    def clear_cache(self):
        """Clear the result cache."""
        if self._cache:
            self._cache.clear()
            logger.debug("Knowledge cache cleared")


# Convenience function
async def quick_search(
    query: str,
    search_type: str = "web",
    base_url: str = "http://localhost:5000"
) -> List[SearchResult]:
    """
    Quick search helper function.

    Args:
        query: Search query
        search_type: 'web', 'doc', or 'api'
        base_url: RAICA server URL

    Returns:
        List of SearchResult objects
    """
    client = RAICAKnowledgeClient(base_url)

    try:
        if search_type == "web":
            result = await client.search_web(query)
        elif search_type == "doc":
            result = await client.search_documents(query)
        elif search_type == "api":
            result = await client.lookup_api_docs(query)
        else:
            return []

        return result.results if result.success else []

    finally:
        await client.close()
