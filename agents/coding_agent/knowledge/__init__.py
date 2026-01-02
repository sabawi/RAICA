"""
Knowledge Module - RAICA Server API integration for knowledge lookup.

Components:
- raica_client.py: Client for RAICA Server API (web search, document search, API docs)
"""

from .raica_client import RAICAKnowledgeClient

__all__ = ['RAICAKnowledgeClient']
