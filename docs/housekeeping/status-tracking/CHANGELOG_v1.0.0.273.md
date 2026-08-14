# CHANGELOG — v1.0.0.273

**Date:** 2026-08-14
**Type:** Checkpoint — first Tier-1 benchmark result recorded (docs only; no code change)

---

## The Tier-1 gate finally ran

The pre-commit hook has asked for `make benchmark-full` on every core-workflow change and it went
**unrun across thirteen consecutive releases** (v1.0.0.259–272). It has now run against v1.0.0.272.

### Every CODE metric passed

| scenario | result |
|---|---|
| S1_news_citation | citation_count 12 (base 13), specific_url_ratio 1.0 — PASS |
| S3_vision | vision_ran ✓, description_keyword_hits 1 — PASS |
| S2_dr_delivery | dr_completed ✓, attachment_count 2, pdf_valid ✓, html_self_contained ✓ — PASS |

**No correctness regression** across thirteen releases of changes to the tool-execution path. That
is the claim that could not be made before this ran.

### Two PERF regressions, cause NOT attributed

```
REGRESSION  PERF  dr_synthesize_s   368   (base 42.4)   8.7x
REGRESSION  PERF  dr_latency_s      621   (base 141)    4.4x
PASS        PERF  dr_verify_s        80   (base 53.8)
```

Logged as **SI-039**. Concentrated in synthesis; verify passed. Two candidates — something in this
session's work (which sits on the **non-DR** path and should not touch DR synthesis at all), or a
stale `baseline.json` sampled at `repeats=1`. Attributing it needs an S2 run against the
pre-session commit, which is the next task and is deliberately not guessed at here.

### And the suite's own cost is a finding

Logged as **SI-040**. It advertises ~15 min and took 30+. A gate that expensive will not be run
before a deploy — which is how it went unrun for thirteen releases. `S4_multi_ticker_8` also has
**no baseline entries**, so it cannot fail however bad its numbers get.

## Deployment note

Production was already at `dae6dec` / v1.0.0.272 before this commit — all code from this session is
live. This checkpoint is documentation only.
