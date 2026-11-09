# CHANGELOG v1.0.0.356 — 2026-11-09

## Ask sees picture sizes before it fetches, so it can choose past a thumbnail

The first real production use of `fetch_image` (NewX @Ask, 2026-11-09 15:07 UTC, the *Inventing God's Law* request)
posted a real cover, credited to books.google.com, at **128×195 pixels**: Google Books' thumbnail.

### Diagnosis (measured, local, NewX `call_raica` with Ask's whitelist and prompt)
- A wording-only change (tell the model the size it got and the site's display size, "look for a larger copy") was
  tried first: **0/3** — every run still posted the 128×195 thumbnail. Reason in the log: the fetch happens in the
  LAST gather round (`gather-gate STOPPED reason=max_rounds`, then the one extra round runs fetch_image with "no
  further rounds"), so a size reported after fetching arrives too late to act on.
- The Google Books page itself declares the cover `<img width="128">`; Wikipedia declares `og:image:width/height`
  and offers larger versions in `srcset`. Ask could have known before fetching, but lookup_website did not say.
- Owner: "go with A, tell Ask the picture sizes".

### Changed — lookup_website lists sizes as data
- Each listed picture now carries the size the PAGE declares (`og:image:width/height` for the preview picture,
  the `<img>` width/height otherwise; pixel values only — `100%`/`auto` are dropped; "size not stated" when absent)
  and the other sizes the page offers for the same picture (its `srcset`/`data-srcset`, with `960w`/`2x`
  descriptors; any other descriptor text is dropped, so page markup cannot put free text in the prompt).
- `_describe_page_image()` renders one line per picture; the listing header names the new columns.
- Nothing in code decides which size is big enough: the model compares.

### Changed — fetch_image wording
- Description: sources often offer the same picture in several sizes; fetch the largest one offered.
- Success result: the size it got plus the size the site shows (`user_tools.fetch_image.max_side`, from config), and
  that it may look for a larger copy and then place only the marker of the picture it uses. Kept because it costs
  nothing and helps when a round remains; it is NOT what fixes the thumbnail case (see diagnosis).
- A picture fetched and then replaced stays as an unreferenced file in NewX's media store, like an unused chart.

### Not changed
NewX `Ask.yaml` PICTURES directive: says nothing about size, so it does not conflict (checked for one voice).
Gather round limits: unchanged. Option B (owner: "go with B too, measure it with 3 runs") was measured and NOT
adopted: local site value `max_gather_rounds` 3 → 4, the book prompt 3× on the same path: **1/3** large (OUP, 362×550,
fetched in round 2, so it did not need the extra round), **2/3** the 128×195 Google thumbnail. In both thumbnail runs
round 4 WAS available and the gate judged the thumbnail `sufficient` (`STOPPED reason=sufficient rounds=4`); one run
fetched the same thumbnail again in the second round. The extra round is not the binding limit: the gate's judgement
is. The local value was restored to 3 (file `cmp`-identical to its backup). Note: `second_round.max_extra_rounds` is
read only as `> 0` (the second round always runs once), so raising it would change nothing.

### Tests
- `tests/utilities/test_lookup_website_images.py`: sizes and srcset versions listed; the model-facing line; only
  pixel sizes and well-formed descriptors reach the model. The first two fail on 1.0.0.355; the third went red with
  each of its two filters removed (planted, restored from disk, `cmp`-checked).
- `tests/utilities/test_fetch_image_tool.py`: the result names the size got and the configured display size.

### Evidence (real path: NewX `call_raica`, Ask's whitelist and prompt, local RAICA; the book prompt 3×)
- The sizes reach the model: all 12 picture listings in the runs carried the new columns; the Google Books cover
  was listed as "128 wide".
- Outcome: **1/3** posted a large cover (Open Library, 328×500); **2/3** still posted the 128×195 Google thumbnail
  (wording-only before this: 0/3). In both thumbnail runs the Google Books page was the only source with a cover in
  view, it offered no larger size, and the gather loop was in its last round. 1/3 vs 0/3 is within run-to-run
  variation, so this release does NOT claim the thumbnail case is fixed: it makes sizes visible when a page states
  them. Getting a larger copy from another source needs a round to spare (option B, not chosen).
- Local mail, posts, replies, notifications and settings unchanged on every run; no model 429.
- `make smoke` passed; unit suite 1146 passed, the 4 known failures; version sync passed.
- Tier 1 (`make benchmark-full`, run 20261109T232157Z): every CODE check PASS (citations 13/13, vision, DR delivery,
  8-ticker charts 20/20). PERF flagged S2 `dr_synthesize_s` 89.4 s and `dr_latency_s` 292 s against a 42.4/141 s
  baseline: inside the range of all 17 archived runs (synth 61–112 s, latency 197–400 s), the same flag as both
  earlier runs today (354, 355), and Deep Research uses none of the changed code (`research/`: no reference). Open
  as SI-063 (baseline below every observed run), not a 356 regression. 86 rate-limit responses (normal), no model 429.
