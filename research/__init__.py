"""RAICA Deep Research package — minimal-scaffolding, LLM-driven research engine.

Stage 1 (engine.py): plan -> dispatch -> iterative gather loop -> evidence pool.
Stage 2 (synthesis.py): credibility grading -> grounded synthesis -> claim verification
        -> multi-model arbitration -> trustworthy answer.
"""
from research.engine import DeepResearchEngine, ResearchPlanner, extract_json_object
from research.synthesis import ResearchSynthesizer

__all__ = ["DeepResearchEngine", "ResearchPlanner", "ResearchSynthesizer", "extract_json_object"]
