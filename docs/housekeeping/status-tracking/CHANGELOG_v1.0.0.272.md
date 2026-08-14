# CHANGELOG — v1.0.0.272

**Date:** 2026-08-14
**Type:** Bug fix — the gather gate was judging prose it could not see
**Found by:** the Phase-0 shadow sample, in three production requests

---

## The bug

The gate answered `needs_more` to *"who is the current UN Secretary-General"*, explaining:

> "The current Secretary-General's name is not explicitly stated in the **truncated** tool output"

It was reasoning correctly about a mutilated input. Prose was previewed at **400 characters**, so a
5,859-char search result reached the gate as 449 chars with the answer simply absent.

**The two output kinds are summarised for opposite reasons and must not share a budget:**

| | why it is summarised | correct budget |
|---|---|---|
| **table** | the answer is NOT in the rows — columns and a row count are what "do I have this?" needs | schema only (20,730 → 579 chars) |
| **prose** | the content **IS** the answer | must be large enough to contain it |

## Why the verdict alone was not enough to see it

The Phase-0 sample read **8 `needs_more` / 1 `sufficient`** — indistinguishable from the failure the
design predicted (§6: "a model asked *is this enough?* tends to agree"). Those two possibilities
need opposite fixes. Only the `missing` REASON separated them, which is why the gate logs it.

## The fix

Prose budget 400 → **6,000 chars**, with a **24,000 total** across outputs so several results cannot
compound. Table handling is unchanged.

**Head AND tail**, not head alone: in prose the answer often sits last — a summary line, a latest
value, a conclusion — so head-only truncation would move the blind spot rather than remove it. Two
thirds from the front, one third from the end, with the omission and its size disclosed:

```
[… 14000 characters omitted from the middle …]
[TRUNCATED: 6000 of 20000 characters shown, from the start and the end — if the answer is not
 above, say the retrieved text does not contain it rather than assuming it is missing]
```

That was caught by a test fixture with the answer in the final sentence, which failed against the
first version of this very fix.

## Also: the measurement harness was wrong

The suite reported three cases as "gate did not run". The gate ran every time — 9 verdicts, 0
unavailable. The harness regex required `missing='…'` in single quotes, and Python's `%r` switches
to double quotes when the text contains an apostrophe ("Secretary-General**'s** name"). An
instrument that silently drops observations reports a cleaner story than reality; the true
distribution was 8/1, not 5/3.

## Verification

| check | result |
|---|---|
| answer at the end of long prose is visible | ✓ (fails on pre-fix code) |
| tables still reduced to schema | ✓ 4,327 → 162 chars |
| truncation disclosed and actionable | ✓ |
| unit suite | **462 passed**, 4 pre-existing failures unchanged |

## What this does not settle

This is a *before/after* on the preview, not on the gate. Whether the gate genuinely discriminates
is decided by re-running the same suite against this build and comparing to the 8/1 baseline. If
`sufficient` does not rise on the four cases where it is correct, Phase 1 should not be built.
