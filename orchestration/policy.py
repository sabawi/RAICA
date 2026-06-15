"""
Shared delivery policy — ONE implementation of the cross-cutting concerns that were duplicated across
RAICA's several delivery paths (deep-research fan-out, legacy POST-LLM executor, email-interceptor).

See docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md (Phase 1, disconnects D2/D3, invariant I3).

This module is PURE (stdlib only — regex + dataclasses). It has NO dependency on the server module,
so every path may import it without circular-import risk. Phase 1 is **behavior-preserving**: each
function reproduces the exact logic of the call site(s) it replaces; the win is that the logic now
lives in exactly one place, so a future fix (or the eventual LLM-driven format resolution) lands
everywhere at once.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

# Single canonical e-mail validation regex (previously duplicated as inline patterns in _run_dr_delivery
# and the POST-LLM _send_secure_email chokepoint).
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def valid_email(email: Optional[str]) -> bool:
    """True iff `email` is a single well-formed address (full-match, trimmed)."""
    return bool(email) and bool(_EMAIL_RE.fullmatch((email or "").strip()))


@dataclass(frozen=True)
class DeliveryAuth:
    """Result of the unified delivery authorization decision.
      permitted        — may this request trigger delivery actions at all?
      recipient_locked — is the client RESTRICTED (sent an allowed_tools whitelist) → recipient must be
                         server-authoritative?
      locked_recipient — the server-authoritative recipient to lock to (only set when locking applies
                         AND delivery is permitted; else None)."""
    permitted: bool
    recipient_locked: bool
    locked_recipient: Optional[str]


def authorize_delivery(data: Dict[str, Any]) -> DeliveryAuth:
    """Unified 3-way delivery authorization + recipient-lock policy. Shared by the deep-research
    delivery path and the legacy POST-LLM path so both agree exactly.

    permitted: explicit `allow_delivery` (True/False) wins; else AUTO-TRUST iff there is NO
    `allowed_tools` whitelist (interactive internal clients, e.g. OpenWebUI). A client that sends an
    allowed_tools whitelist (e.g. a NewX bot) is RESTRICTED and is permitted only via the explicit
    flag — keeping bots locked unless the acting user is privileged.

    This reproduces `_dr_delivery_permitted` (for `permitted`) AND the POST-LLM whitelist's
    `_post_allow_delivery/_post_recipient_locked/_post_locked_recipient` computation, in one place.
    """
    explicit = data.get("allow_delivery", None)
    recipient_locked = data.get("allowed_tools", None) is not None
    permitted = bool(explicit) if explicit is not None else (not recipient_locked)
    locked_recipient = data.get("delivery_recipient") if (permitted and recipient_locked) else None
    return DeliveryAuth(permitted=permitted, recipient_locked=recipient_locked, locked_recipient=locked_recipient)


def resolve_locked_recipient(recipient_locked: bool, locked_recipient: Optional[str]) -> Tuple[Optional[str], bool]:
    """Shared recipient-lock decision (fail-closed). Returns (recipient_or_None, refused):
      • not locked            → (None, False)   — caller resolves recipients normally (prompt/args)
      • locked + valid lock   → (lock.strip(), False) — email ONLY this address; ignore prompt/LLM
      • locked + invalid lock → (None, True)    — REFUSE; never fall back to a prompt address

    This is the single source of truth for invariant I3 (recipient lock / fail-closed)."""
    if not recipient_locked:
        return (None, False)
    if valid_email(locked_recipient):
        return ((locked_recipient or "").strip(), False)
    return (None, True)


# ── Format resolution ────────────────────────────────────────────────────────────────────────────
# Parameterized so each existing call site keeps its EXACT current behavior (Phase 1 = no behavior
# change). The eventual convergence may unify these or make them LLM/deliverable-spec driven; doing it
# here means one edit changes every path.

def resolve_delivery_format(user_prompt: str, deliverable_format: str = "",
                            *, candidates: Sequence[Tuple[str, Sequence[str]]], default: str) -> str:
    """First candidate format whose ANY needle substring appears in `<deliverable_format> <user_prompt>`
    (lower-cased) wins; else `default`. Order of `candidates` matters (first match wins), matching the
    legacy if/elif chains."""
    hay = f"{deliverable_format or ''} {user_prompt or ''}".lower()
    for fmt, needles in candidates:
        if any(n in hay for n in needles):
            return fmt
    return default


def resolve_delivery_formats(user_prompt: str, deliverable_format: str = "",
                             *, candidates: Sequence[Tuple[str, Sequence[str]]], default: str) -> list:
    """Like resolve_delivery_format, but returns EVERY candidate format whose needle appears (in
    candidate order, de-duplicated), so a request for more than one — e.g. "an HTML file AND a PDF
    file" — yields all of them. Falls back to [default] when none match. Used by delivery paths that
    can attach multiple documents to a single email."""
    hay = f"{deliverable_format or ''} {user_prompt or ''}".lower()
    found = []
    for fmt, needles in candidates:
        if fmt not in found and any(n in hay for n in needles):
            found.append(fmt)
    return found or [default]


# Canonical candidate sets that reproduce the two legacy inline call sites exactly:
#  • Deep-research fan-out (_run_dr_delivery): pdf|html, default pdf, considers the deliverable_spec
#    format AND the user prompt.
DR_FORMAT_CANDIDATES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (("pdf", ("pdf",)), ("html", ("html",)))
DR_FORMAT_DEFAULT = "pdf"
#  • Legacy POST-LLM executor: pdf|html|md|txt, default html, considers the user prompt only.
POST_LLM_FORMAT_CANDIDATES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("pdf", ("pdf",)), ("html", ("html",)), ("md", ("markdown", "md")), ("txt", ("text", "txt")))
POST_LLM_FORMAT_DEFAULT = "html"
