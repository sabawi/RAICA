#!/usr/bin/env python3
"""
LABELED evaluation corpus for intent classification — Phase 3a baseline
(docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md).

Unlike the Phase-0 characterization golden (which pins what the LEGACY classifier *currently* does,
bugs and all), this corpus carries GROUND TRUTH — what a correct classifier *should* decide — so we
can measure legacy-vs-truth AND llm-vs-truth and justify a per-category cutover.

Each case:
  id        : stable id
  category  : grouping for per-category accuracy
  prompt    : the user prompt. Multi-turn cases embed conversation context using the same markers real
              OpenWebUI/NewX requests use ("=== CONVERSATION HISTORY ===" / "=== CURRENT REQUEST ===").
  truth_delivery : ground-truth — does this need ANY post-generation delivery/packaging action?
  truth_kinds    : ground-truth set of delivery KINDS needed: {"file","email","publish","image"}.
                   (Kinds, not exact tool names, so scoring is robust to tool naming / registry.)
  note      : why (esp. for edge cases)

The "kind" abstraction: a classifier's tool names are mapped to kinds by the harness, so e.g.
sandboxed_executor/pdf_generator→file, secure_email_sender→email, social_media_*→publish,
analytical_visualizer→image.
"""

# Realistic multi-turn helper
def _turn(history: str, current: str) -> str:
    return (f"=== CONVERSATION HISTORY ===\n{history}\n"
            f"=== CURRENT REQUEST ===\n{current}")


# A realistic NewX @Ask system preamble whose "DO NOT CREATE OR GENERATE FILES" line caused a live
# false-negative (v1.0.0.85 validation): the classifier obeyed the platform directive and dropped a
# user's explicit email-a-file request. A correct classifier ignores platform policy and reads the
# user's intent.
_NEWX_SYS = ("=== SYSTEM INSTRUCTIONS ===\nYou are a knowledge-seeking AI Agent on the NewX platform. "
             "Use your search tools to verify facts and cite sources. CRITICAL: BE AWARE OF THE TIME "
             "AND DATE. DO NOT CREATE OR GENERATE FILES.\n")


def _newx(history: str, current: str) -> str:
    return _NEWX_SYS + _turn(history, current)


_WAR_ANSWER = ("ASSISTANT: TL;DR: No one is winning. The US and Israel achieved tactical military "
               "degradation of Iran's forces but failed strategically; Iran retains Strait of Hormuz "
               "leverage. The conflict is a costly stalemate. [~20k chars of analysis followed]")


CASES = [
    # ── information-only (truth: no delivery) ──────────────────────────────────────────────────
    {"id": "info_capital", "category": "info_only", "prompt": "What is the capital of France?",
     "truth_delivery": False, "truth_kinds": set(), "note": "pure fact"},
    {"id": "info_rsa", "category": "info_only", "prompt": "Explain how RSA encryption works.",
     "truth_delivery": False, "truth_kinds": set(), "note": "explanation"},
    {"id": "info_research_tell", "category": "info_only",
     "prompt": "Research the history of jazz and tell me about it.",
     "truth_delivery": False, "truth_kinds": set(), "note": "research-and-report-back is an ANSWER, not delivery"},
    {"id": "info_list", "category": "info_only", "prompt": "List the top 5 programming languages in 2026.",
     "truth_delivery": False, "truth_kinds": set(), "note": "list in chat"},

    # ── plain creative answer (truth: no delivery) ─────────────────────────────────────────────
    {"id": "plain_poem", "category": "plain_answer", "prompt": "Write a short poem about autumn leaves.",
     "truth_delivery": False, "truth_kinds": set(), "note": "LEGACY FALSE-POSITIVE ('write a')"},
    {"id": "plain_haiku", "category": "plain_answer", "prompt": "Write a haiku about the ocean.",
     "truth_delivery": False, "truth_kinds": set(), "note": "creative answer in chat"},
    {"id": "plain_draft_tweet", "category": "plain_answer",
     "prompt": "Draft a tweet about our product launch (just show me the text).",
     "truth_delivery": False, "truth_kinds": set(),
     "note": "EDGE: 'tweet' keyword but DRAFT-in-chat, not publish"},

    # ── pure email (truth: email) ──────────────────────────────────────────────────────────────
    {"id": "email_hello", "category": "pure_email",
     "prompt": "Send an email to bob@example.com saying hello.",
     "truth_delivery": True, "truth_kinds": {"email"}, "note": "email, no attachment"},
    {"id": "email_notes", "category": "pure_email",
     "prompt": "Email john@example.com the meeting notes from above.",
     "truth_delivery": True, "truth_kinds": {"email"}, "note": "email existing content"},

    # ── file + email (truth: file+email) ───────────────────────────────────────────────────────
    {"id": "fe_html_above", "category": "file_email",
     "prompt": "Email the above response as a HTML document.",
     "truth_delivery": True, "truth_kinds": {"file", "email"},
     "note": "emailing a DOCUMENT implies creating the file first"},
    {"id": "fe_pdf_ev", "category": "file_email",
     "prompt": "Create a PDF report on electric vehicles and email it to me.",
     "truth_delivery": True, "truth_kinds": {"file", "email"}, "note": "compose+file+email"},
    {"id": "fe_save_send", "category": "file_email",
     "prompt": "Save this as a PDF and send it to sara@example.com.",
     "truth_delivery": True, "truth_kinds": {"file", "email"}, "note": "file then email"},

    # ── file only (truth: file) ────────────────────────────────────────────────────────────────
    {"id": "file_pdf", "category": "file_only", "prompt": "Save the analysis to a PDF file.",
     "truth_delivery": True, "truth_kinds": {"file"}, "note": "file, no email"},
    {"id": "file_html", "category": "file_only", "prompt": "Create an HTML file of this summary.",
     "truth_delivery": True, "truth_kinds": {"file"}, "note": "file, no email"},

    # ── publish (truth: publish) ───────────────────────────────────────────────────────────────
    {"id": "pub_wordpress", "category": "publish", "prompt": "Publish this article to my WordPress blog.",
     "truth_delivery": True, "truth_kinds": {"publish"}, "note": "publish"},
    {"id": "pub_substack", "category": "publish", "prompt": "Post this to Substack.",
     "truth_delivery": True, "truth_kinds": {"publish"}, "note": "publish"},
    {"id": "pub_tweet", "category": "publish", "prompt": "Tweet this summary to my followers.",
     "truth_delivery": True, "truth_kinds": {"publish"}, "note": "publish via twitter"},

    # ── image / visualization (truth: image [+email]) ──────────────────────────────────────────
    {"id": "img_chart", "category": "image", "prompt": "Create a chart of these quarterly revenue numbers.",
     "truth_delivery": True, "truth_kinds": {"image"}, "note": "visualization artifact"},
    {"id": "img_email", "category": "image",
     "prompt": "Generate a visualization of the trend and email it to me.",
     "truth_delivery": True, "truth_kinds": {"image", "email"}, "note": "image+email"},

    # ── meta-task / housekeeping (truth: no delivery) ──────────────────────────────────────────
    {"id": "meta_title", "category": "meta_task",
     "prompt": "Generate a concise, 3-5 word title with an emoji summarizing the chat history.",
     "truth_delivery": False, "truth_kinds": set(), "note": "OpenWebUI housekeeping"},
    {"id": "meta_tags", "category": "meta_task",
     "prompt": "Generate 1-3 broad tags categorizing the main themes of the chat history.",
     "truth_delivery": False, "truth_kinds": set(), "note": "OpenWebUI housekeeping"},

    # ── edge / tricky (truth varies) ───────────────────────────────────────────────────────────
    {"id": "edge_negation", "category": "edge",
     "prompt": "Don't email this to anyone — just show me the result here.",
     "truth_delivery": False, "truth_kinds": set(), "note": "NEGATION: 'email' present but explicitly refused"},
    {"id": "edge_howto_email", "category": "edge",
     "prompt": "How do I email a PDF attachment in Outlook?",
     "truth_delivery": False, "truth_kinds": set(), "note": "INFO about emailing, not an email request"},
    {"id": "edge_howto_publish", "category": "edge",
     "prompt": "Tell me how to publish a post to Substack.",
     "truth_delivery": False, "truth_kinds": set(), "note": "INFO about publishing, not a publish request"},
    {"id": "edge_printable", "category": "edge",
     "prompt": "I need a printable copy of this report.",
     "truth_delivery": True, "truth_kinds": {"file"}, "note": "FORMAT SYNONYM: 'printable copy' = file, no 'pdf' keyword"},
    {"id": "edge_word_doc", "category": "edge",
     "prompt": "Make me a Word document of the summary.",
     "truth_delivery": True, "truth_kinds": {"file"}, "note": "FORMAT SYNONYM: 'Word document', no pdf/html keyword"},

    # ── multi-turn / high-complexity (embedded history) ────────────────────────────────────────
    {"id": "mt_email_above", "category": "multi_turn",
     "prompt": _turn(f"USER: Do a deep analysis of the US-Israel-Iran war and tell me who is winning.\n{_WAR_ANSWER}",
                     "Email the above response as a HTML document."),
     "truth_delivery": True, "truth_kinds": {"file", "email"},
     "note": "REAL NewX incident — current turn references prior answer"},
    {"id": "mt_now_tweet", "category": "multi_turn",
     "prompt": _turn("USER: Write a market brief on lithium supply.\nASSISTANT: [a 1500-word brief on lithium]",
                     "Now also tweet a one-paragraph summary of it."),
     "truth_delivery": True, "truth_kinds": {"publish"}, "note": "follow-up publish referencing prior content"},
    {"id": "mt_both_pdfs", "category": "multi_turn",
     "prompt": _turn("USER: Compare the Q1 and Q2 results.\nASSISTANT: [analysis of Q1] ... [analysis of Q2]",
                     "Email both of them to me as PDFs."),
     "truth_delivery": True, "truth_kinds": {"file", "email"}, "note": "compound: two files + email"},
    {"id": "mt_thanks", "category": "multi_turn",
     "prompt": _turn("USER: Email me the report.\nASSISTANT: 📎 Delivery: the document was emailed to you.",
                     "Thanks, that's perfect!"),
     "truth_delivery": False, "truth_kinds": set(), "note": "follow-up acknowledgement — NO action"},
    {"id": "mt_distractor", "category": "multi_turn",
     "prompt": _turn("USER: Summarize our email-marketing strategy doc.\nASSISTANT: [summary mentioning email campaigns, publishing cadence, PDF reports]",
                     "What did you mean by the second point?"),
     "truth_delivery": False, "truth_kinds": set(),
     "note": "DISTRACTOR: history is full of 'email/publish/PDF' words; current turn is a pure question"},
    {"id": "mt_compound_cc", "category": "multi_turn",
     "prompt": _turn("USER: Hi.\nASSISTANT: Hello! How can I help?",
                     "Research the competitor landscape, write a 2000-word brief, save it as a PDF, and "
                     "email it to me and cc my manager."),
     "truth_delivery": True, "truth_kinds": {"file", "email"},
     "note": "HIGH-COMPLEXITY compound: research(answer) + file + email (research is NOT a delivery kind)"},

    # ── system-directive bias (the v1.0.0.85 live false-negative) ──────────────────────────────
    {"id": "mt_newx_email_file", "category": "multi_turn",
     "prompt": _newx("USER: get me the latest tech news\nASSISTANT: [5 headlines with source URLs]",
                     "email the above to me in an HTML formatted file"),
     "truth_delivery": True, "truth_kinds": {"file", "email"},
     "note": "REGRESSION: delivery request under a NewX 'DO NOT CREATE OR GENERATE FILES' system "
             "preamble — the classifier MUST ignore the platform directive and read the user's intent"},
    {"id": "mt_newx_info_only", "category": "multi_turn",
     "prompt": _newx("USER: hello\nASSISTANT: Hi!", "what's the weather in Paris today?"),
     "truth_delivery": False, "truth_kinds": set(),
     "note": "control: same NewX preamble but a pure question — must stay no-delivery"},
]
