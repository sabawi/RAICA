# CHANGELOG — RAICA v1.0.0.152

**Date:** 2026-07-07
**Type:** Fix — surface canonical PRIMARY sources (Wikipedia bibliography) + allow prose attribution

## Summary
Operator insight: the canonical primary for the Byzantine/Khalid query — al-Tabari — is cited 12× in the
Wikipedia "Battle of Yarmouk" article, so it should be reachable on the first pass. Two gaps stopped it:
1. `wikipedia_query` returned ONLY `page.summary[:2000]` (the lead paragraph) — which never names the primary
   sources. The article's **"Primary sources"** section (naming al-Tabari, al-Baladhuri, Ibn Ishaq) was thrown away.
2. Even once surfaced, the primaries have NO clickable URL (they're bibliography entries), and the synthesis's
   strict "cite every claim as [Title](URL)" rule made the model OMIT them entirely.

## Changes
- **`fastapi_server_complete.py` `wikipedia_query`** — now returns the summary **plus** a budgeted article-body
  excerpt **plus** the article's own curated source sections ("Primary/Secondary sources", "Bibliography",
  "Sources", "Further reading"). That is Wikipedia's canonical-source list for the topic. Verified: the Battle
  of Yarmouk extraction now contains al-Tabari, al-Baladhuri, and Ibn Ishaq.
- **`research/synthesis.py`** PRIMARY-FIRST directive — when the evidence NAMES a canonical primary with no
  clickable URL (an ancient/medieval chronicle listed in a bibliography or attributed in the gathered text),
  the synthesis SHOULD attribute claims to it BY NAME in prose ("al-Tabari's account records…") — proper
  scholarship without a hyperlink, far better than omitting the primary. Attribute only to evidence-named
  primaries; never invent one.

## Verification (local, e2e — Byzantine DR)
- Before: 0 mentions of al-Tabari/Baladhuri/Theophanes. After: **al-Tabari ×3, al-Baladhuri ×3, Ibn Ishaq ×1,
  Theophanes ×3**, with scholarly caveats about their late composition. Full 28K report.

## Risk / rollback
- wikipedia_query returns more content (budgeted ~10K); prose-attribution is grounded (evidence-named only).
  Version → 1.0.0.152.
