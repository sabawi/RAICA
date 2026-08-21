"""SI-094 — a bot must never say it cannot post, because its reply IS the post.

THE FAILURE THIS PREVENTS
-------------------------
Live, @scibot on NewX, 2026-08-21 14:04 UTC. Asked to write a post, it replied:

    "I can't create or publish a social media post — outbound posting actions aren't
     available for this request. However, here is the post content you asked for,
     written and ready to copy."

…followed by a complete, well-sourced article on a JWST black-hole result. NewX then
published the whole thing verbatim, so the published post OPENED BY DENYING IT WAS A POST.

CAUSE. `_NEG_DELIVERY_AWARENESS` is injected whenever `allow_delivery` is false, which is
always for a NewX bot (they send an `allowed_tools` whitelist, so `_dr_delivery_permitted`
never auto-trusts them). It listed "posting" among the unavailable outbound actions. The
model obeyed a prohibition that was never true of THIS platform.

NOTHING ENFORCED IT. `allow_delivery` gates outbound TOOLS — email, file creation,
scheduling. The reply is not an action RAICA takes: NewX's scheduler does
`Post(content=html_content, ...); db.session.commit()` on whatever RAICA returns. There is
no code path where a bot tries to post and is refused. Traced end to end before the wording
was changed, per the LLM-policy no-inconsistency clause — a prompt fix here cannot be
defeated by a code gate, because there is no gate.

WHAT MUST NOT REGRESS. The other prohibitions are load-bearing:
  * "never claim an email was sent" fixed a real defect (v1.0.0.120 — a non-delivery bot
    reporting "✅ sent" for a delivery that failed);
  * the citation requirement is enforced downstream — NewX discards a sourceless
    autonomous post outright (`_is_sourceless_research_output(..., strict=True)`), so an
    answer that drops its sources is never published at all.
"""
import pytest

from fastapi_server_complete import (_NEG_DELIVERY_AWARENESS, _POS_DELIVERY_AWARENESS,
                                     _build_enhanced_primary_system_prompt)


# ------------------------------------------------- the fix

def test_the_directive_states_the_reply_is_the_delivery():
    """FAILS pre-SI-094: 'posting' was listed as unavailable, full stop."""
    t = _NEG_DELIVERY_AWARENESS.lower()
    assert "your reply is delivered automatically" in t
    assert "composing it is the delivery" in t


def test_it_forbids_claiming_inability_to_post_here():
    t = _NEG_DELIVERY_AWARENESS.lower()
    assert "never say you are unable to post" in t


def test_it_forbids_the_content_to_copy_framing():
    """The exact shape of the live failure — presenting the post as something to copy."""
    assert "content to copy" in _NEG_DELIVERY_AWARENESS.lower()


def test_posting_is_no_longer_listed_as_flatly_unavailable():
    """The old text put bare 'posting' in the unavailable list. It must now be qualified
    as OTHER platforms, or the model reads it as 'cannot post at all' again."""
    t = _NEG_DELIVERY_AWARENESS
    assert "posting outside this platform) are NOT available" not in t
    assert "posting to OTHER platforms" in t


# ------------------------------------------------- what must NOT regress

def test_email_files_and_scheduling_are_still_refused():
    """Asserts the CONCEPT survives, not my phrasing.

    The first version of this test demanded the exact string "creating or saving files"
    and so FAILED on the pre-fix directive, which said "creating/saving files" — a
    must-not-regress test that reported a regression where none existed. A test asserting
    the wording of the change it accompanies discriminates nothing."""
    t = _NEG_DELIVERY_AWARENESS.lower()
    for concept in ("email", "file", "scheduling"):
        assert concept in t, f"{concept!r} must still be named as unavailable"
    assert "not available for this request" in t


def test_false_success_claims_are_still_forbidden():
    """v1.0.0.120: a non-delivery bot claimed an email was sent when it was not."""
    t = _NEG_DELIVERY_AWARENESS.lower()
    assert "never claim or imply that an email was sent" in t
    assert "a file was created or attached" in t


def test_citations_are_still_required_in_the_fallback_answer():
    """NewX discards a sourceless autonomous post, so dropping sources means no post."""
    assert "source citations" in _NEG_DELIVERY_AWARENESS.lower()


def test_raw_file_content_is_still_forbidden():
    assert "do not produce the file itself" in _NEG_DELIVERY_AWARENESS.lower()


# ------------------------------------------------- wiring

def test_the_negative_form_is_used_only_when_delivery_is_denied():
    denied = _build_enhanced_primary_system_prompt("sys", allow_delivery=False)
    allowed = _build_enhanced_primary_system_prompt("sys", allow_delivery=True)
    assert _NEG_DELIVERY_AWARENESS in denied
    assert _NEG_DELIVERY_AWARENESS not in allowed
    assert _POS_DELIVERY_AWARENESS in allowed


def test_the_two_forms_do_not_contradict_each_other_about_posting():
    """One voice. Neither form may tell the model it cannot post on this platform."""
    for form in (_NEG_DELIVERY_AWARENESS, _POS_DELIVERY_AWARENESS):
        low = form.lower()
        assert "cannot post" not in low
        assert "unable to post" not in low.replace("never say you are unable to post", "")
