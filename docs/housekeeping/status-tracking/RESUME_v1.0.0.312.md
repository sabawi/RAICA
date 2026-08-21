# ✅ COMPLETE — v1.0.0.312 work shipped as v1.0.0.313

**This note is closed.** It was written 2026-08-18 when a session was interrupted mid-audit, with
v1.0.0.312 verified but uncommitted and its mandatory adversarial audit unfinished. That audit was
completed on 2026-08-21 and found a real defect in the .312 fix itself.

**Outcome:** SI-085, SI-086 and the newly-found **SI-087** all ship in **v1.0.0.313**.
v1.0.0.312 was never released as its own commit.

Full record: **`CHANGELOG_v1.0.0.313.md`** (this directory). Defect detail: `SUSPECTED_ISSUES.md`,
entries SI-085 / SI-086 / SI-087.

## The three attack hypotheses, all answered

| # | attack | verdict |
|---|---|---|
| 1 | Append-in-a-loop (oscillation) in the SI-086 fix | **CLEARED** — append site has no enclosing loop; cycle 2 impossible |
| 2 | `.startswith()` on a non-string crashes the SI-086 fix | **CLEARED** — all 5 return paths yield `str`/`None`; a non-`str` would already die on the pre-existing slice 3 lines earlier; 0 crashes in 966 calls |
| 3 | Punctuation in legitimate plain labels | **CONFIRMED** → SI-087, fixed in .313 |

## Final gates

| gate | result |
|---|---|
| full unit suite | **886 passed, 4 failed** — the same 4 pre-existing, unrelated to this work |
| new SI-087 tests | 21 pass; **9 fail on pre-fix code** |
| production replay tests | 145 pass; **49 fail on pre-SI-085 HEAD** |
| monotonicity (966 pairs) | 0 narrowed, 0 altered, 0 crashed, 3 intended widenings |
| version sync | 11/11 |

## Still outstanding after this release

- **SI-086 has never been verified end-to-end.** Its guard branch has not fired in production; it is
  covered by unit test only. Watch for `🚨 ARBITRATOR: correction FAILED — keeping the N chars` and
  confirm the delivered answer is complete.
- The `/home/sabawi` paths at `fastapi_server_complete.py:2710/9305/10690` remain the known open
  action item (pre-existing; not introduced here).
