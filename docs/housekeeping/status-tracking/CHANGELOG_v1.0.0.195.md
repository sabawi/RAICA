# Changelog — v1.0.0.195

**Date:** 2026-07-19
**Scope:** DR claim-verifier — stop false-flagging RAICA-computed values. The "Claims to scrutinize"
audit was marking RAICA's OWN deterministic computations (technical indicators + dated events, DCF,
projections) as `unverified`/`not_in_evidence` because the verifier requires `>= min_corroborating_sources`
(2) independent sources and no web page repeats RAICA's computed numbers. Surfaced/amplified by the
Phase-5 event sub-charts (which add dated technical claims like "death cross · 2026-01-22").

## Changed — `research/synthesis.py` verify() system prompt
Added a policy directive (LLM-judged; no hardcoded routing) telling the fact-checker that
**RAICA-computed sources are single-source authoritative** for their own values:
- Recognized by their labels — `RAICA — pandas-ta-classic indicators` (SMA/RSI/MACD/ADX + dated
  crossover events), `RAICA MODEL ESTIMATE` (DCF), `Historical-CAGR Extrapolation` (projections).
- A claim that FAITHFULLY RELAYS a value/date/state from such a source is `supported` by that source
  ALONE — no ≥2-web-source corroboration; not flagged `unverified` just because web pages don't repeat it.
- Not `contradicted` when a web source reports a slightly different figure by rounding or a marginally
  different lookback window (e.g. 52-week range/percentile/return) — RAICA computes from primary OHLCV;
  reserve `contradicted` for MATERIAL disagreement or an actual misquote of the RAICA source.
- The attached Yahoo chart/quote URL is a convenience link, NOT the origin of the computed value.

Audited for the no-inconsistency clause against the existing synthesis "MODEL ESTIMATES vs SOURCED DATA"
directive (line ~954) — both treat RAICA-computed sources as legitimate/authoritative and both note the
Yahoo URL isn't the true origin; they speak with one voice.

## Verification (live @Ask, MSFT-vs-ORCL 5-month query)
- Before (TSLA/IBM): 57/72 supported; ALL ~10 RAICA technical values + every event date + DCF flagged.
- After: **91/106 supported**; **zero** RAICA technical values/dates/DCF in "Claims to scrutinize".
  Remaining `unverified` are legitimate web-claim gaps (un-retrieved Morgan Stanley content, outdated
  dividend articles). The residual `contradicted` (52-week-range/percentile rounding-vs-web) is what the
  second clause above closes — pending one more live re-test.

## No new dependencies.
