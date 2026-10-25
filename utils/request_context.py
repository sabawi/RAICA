"""The text of the request being answered, for tools whose input is written by another model.

A tool's arguments are the tool-calling model's paraphrase of the request, and a paraphrase can drop or decide what
the user left open (NewX post 9091, 2026-10-25: the user asked for a STEERABLE sail; the task the writer received said
"sail acceleration is radially outward", so no program could steer it). Set once per request, before any tool runs;
contextvars carry it into every tool call of that request, sequential or gathered. Unset → None, and tools behave as
before.
"""
import contextvars
from typing import Optional

_request_text: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("raica_request_text", default=None)


def set_request_text(text) -> None:
    _request_text.set(str(text) if text else None)


def get_request_text() -> Optional[str]:
    return _request_text.get()
