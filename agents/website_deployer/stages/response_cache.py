#!/usr/bin/env python3
"""
Response Cache System
=====================

Caches LLM responses to enable deterministic replay and avoid repeated API costs.

Usage:
    # Save responses during first run
    cache = ResponseCache(mode="record")
    # ... run code generation ...
    cache.save_to_file("responses.json")
    
    # Replay responses in subsequent run
    cache = ResponseCache.load_from_file("responses.json")
    # ... replay will use cached responses ...
"""

import json
import hashlib
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CachedResponse:
    """A cached LLM response."""
    prompt_hash: str
    prompt_preview: str  # First 100 chars for debugging
    response: str
    provider: str
    model: str
    timestamp: str


class ResponseCache:
    """
    Caches LLM prompts and responses for deterministic replay.
    
    Modes:
    - "record": Records all LLM calls to cache
    - "replay": Returns cached responses, errors if not found
    - "passthrough": Does nothing (default LLM behavior)
    """
    
    def __init__(self, mode: str = "passthrough"):
        """
        Initialize response cache.
        
        Args:
            mode: "record", "replay", or "passthrough"
        """
        if mode not in ["record", "replay", "passthrough"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'record', 'replay', or 'passthrough'")
        
        self.mode = mode
        self.cache: Dict[str, CachedResponse] = {}
        self._call_order = []  # Track order of calls for debugging
        logger.info(f"ResponseCache initialized in '{mode}' mode")
    
    def get(self, prompt: str) -> Optional[str]:
        """
        Get cached response for a prompt.
        
        Args:
            prompt: The LLM prompt
        
        Returns:
            Cached response if found, None otherwise
        """
        if self.mode != "replay":
            return None
        
        prompt_hash = self._hash_prompt(prompt)
        
        if prompt_hash in self.cache:
            cached = self.cache[prompt_hash]
            logger.info(f"✅ Cache HIT for prompt: {cached.prompt_preview}")
            return cached.response
        else:
            logger.error(f"❌ Cache MISS for prompt: {prompt[:100]}...")
            logger.error(f"   Available hashes: {list(self.cache.keys())[:5]}")
            raise KeyError(f"No cached response for prompt hash: {prompt_hash}")
    
    def save(self, prompt: str, response: str, provider: str = "unknown", model: str = "unknown"):
        """
        Save a response to the cache.
        
        Args:
            prompt: The LLM prompt
            response: The LLM response
            provider: LLM provider name
            model: Model name
        """
        if self.mode != "record":
            return
        
        prompt_hash = self._hash_prompt(prompt)
        
        from datetime import datetime
        cached = CachedResponse(
            prompt_hash=prompt_hash,
            prompt_preview=prompt[:100],
            response=response,
            provider=provider,
            model=model,
            timestamp=datetime.now().isoformat()
        )
        
        self.cache[prompt_hash] = cached
        self._call_order.append(prompt_hash)
        logger.debug(f"💾 Cached response for prompt: {cached.prompt_preview}")
    
    def save_to_file(self, filepath: str):
        """
        Save cache to JSON file.
        
        Args:
            filepath: Path to save cache
        """
        data = {
            "mode": self.mode,
            "call_order": self._call_order,
            "total_calls": len(self.cache),
            "responses": {
                hash_key: asdict(response)
                for hash_key, response in self.cache.items()
            }
        }
        
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"💾 Saved {len(self.cache)} cached responses to {filepath}")
    
    @classmethod
    def load_from_file(cls, filepath: str) -> "ResponseCache":
        """
        Load cache from JSON file.
        
        Args:
            filepath: Path to load cache from
        
        Returns:
            ResponseCache instance in replay mode
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        cache = cls(mode="replay")
        
        # Load responses
        for hash_key, response_data in data["responses"].items():
            cache.cache[hash_key] = CachedResponse(**response_data)
        
        cache._call_order = data.get("call_order", [])
        
        logger.info(f"📂 Loaded {len(cache.cache)} cached responses from {filepath}")
        logger.info(f"   Cache was recorded in '{data.get('mode', 'unknown')}' mode")
        
        return cache
    
    def _hash_prompt(self, prompt: str) -> str:
        """
        Generate a deterministic hash for a prompt.
        
        Args:
            prompt: The prompt to hash
        
        Returns:
            SHA256 hash of the prompt
        """
        # Normalize whitespace for consistent hashing
        normalized = ' '.join(prompt.split())
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "mode": self.mode,
            "total_cached": len(self.cache),
            "call_order_length": len(self._call_order)
        }


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Recording mode
    print("=== Recording Mode ===")
    cache = ResponseCache(mode="record")
    cache.save("What is Python?", "Python is a programming language", "anthropic", "claude-3")
    cache.save("What is FastAPI?", "FastAPI is a web framework", "anthropic", "claude-3")
    cache.save_to_file("test_cache.json")
    
    # Replay mode
    print("\n=== Replay Mode ===")
    replay_cache = ResponseCache.load_from_file("test_cache.json")
    print(replay_cache.get("What is Python?"))
    print(replay_cache.get("What is FastAPI?"))
