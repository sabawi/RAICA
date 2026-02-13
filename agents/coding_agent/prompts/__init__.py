"""
Prompts Package
===============

System prompts and templates for the coding agent.

Modules:
- request_interpreter: User request interpretation with feedback loop

Usage:
    from prompts import RequestInterpreter, UserFeedbackHandler
    interpreter = RequestInterpreter(llm_client)
    result = await interpreter.interpret_with_feedback(...)
"""

from .request_interpreter import (
    UserFeedback,
    TodoItem,
    InterpretationResult,
    MaxIterationsExceeded,
    UserFeedbackHandler,
    RequestInterpreter,
    REQUEST_INTERPRETER_PROMPT,
    ITERATION_PROMPT_TEMPLATE
)

__all__ = [
    'UserFeedback',
    'TodoItem',
    'InterpretationResult',
    'MaxIterationsExceeded',
    'UserFeedbackHandler',
    'RequestInterpreter',
    'REQUEST_INTERPRETER_PROMPT',
    'ITERATION_PROMPT_TEMPLATE'
]
