"""
State Module - Full state persistence for session resumption.

Components:
- persistence.py: Save/load state and checkpoint management
"""

from .persistence import StatePersistence, Checkpoint

__all__ = ['StatePersistence', 'Checkpoint']
