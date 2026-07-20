# DESIGN: Unified Non-Text Artifact Pathway (RAICA)

**Status:** Design draft (2026-07-20). No code yet. Isolated on branch `feature/unified-artifacts`.
**Owner:** RAICA server + DR pipeline (RAICA↔NewX artifact contract).
**Supersedes/absorbs:** the data-charting integration (`docs/DESIGN_data_charts.md`) — the chart fix lands
**inside** this pathway rather than as a bespoke path.
**Method note (mandatory gate):** this design is grounded in a traced read of the ACTUAL request pathway
(file:line anchors throughout), not an assumed model — after an earlier data-charting design failed because
it assumed the planner sees the full request when Phase-1 decompose strips it first.

---

## 1. Why (the problem)

Non-text artifacts today travel **fragmented** paths, and each reaches only ONE output target:

- **Charts** ride the CHAT reply only: `[[chart:…]]` marker → `utils/chart_publisher.publish_chart` uploads
  the PNG to NewX `/internal/chart-upload` → same-origin URL → NewX renders a **card**. Synthesis only
  *relays* the marker (`research/synthesis.py:37`, completeness pass `:681-740`); the marker→`<img>`
  rendering is **NewX-only**.
- **Files (PDF/HTML/generated images)** ride the EMAIL/attachment target only: `_artifact_snapshot()` diffs
  the sandbox before/after a tool runs (`fastapi_server_complete.py:7938, :8686-8708`), captures **any**
  file **any** tool wrote (LLM-policy-clean, no per-tool parsing), and `secure_email_sender` attaches it
  (`:2297` auto-bind). Delivery runs in `_run_dr_delivery` (`:7582`) AFTER synthesis; non-file/email actions
  are "generic actions" dispatched post-write (`:7607`).
- **Inbound artifacts** (user-attached) are recognized but never echoed to output: images →
  `images` field (`:274`) → `set_image_context` (`:528`) → auto-injected into `image_to_text`/vision
  (`:2204`); documents → `document_interrogator` (`:2437`).

**Two load-bearing gaps** (surfaced by the acceptance prompts below):
- **G1 — an artifact renders in one target but not the other.** A `[[chart:]]` in an answer that is *also*
  emailed as HTML would appear as **raw `[[chart:…]]` text** in the file (RAICA's file-packaging,
  `user_tools/pdf_generator_tool.py`, has no chart-marker rendering).
- **G2 — inbound artifacts can't flow to output.** No mechanism places an attached photo into the email
  body or the reply.

Plus the routing bug the data-charting work exposed:
- **G3 — content misrouted to delivery.** Phase-1 `_decompose_request` (`research/pipeline.py:218`, prompt
  `:242-247`) treats "generating images/infographics/diagrams" as delivery/packaging and **strips** an
  explicit "chart X" out of `research_request` into `deliverable_spec`/`actions` — so the planner never
  gathers the chart and the marker never reaches the answer.

## 2. Acceptance matrix (the design MUST satisfy these)

| # | Prompt | Inbound | Generated | Content | Delivery |
|---|--------|---------|-----------|---------|----------|
| 1 | "chart the population of Egypt since 1960 with explanation and email it as HTML file to sabawi@gmail.com" | — | chart | explanation + chart in answer | email HTML **with the chart image** |
| 2 | "write a funny caption to the attached photo and email it (in the email body) to sabawi@gmail.com" | photo | — | caption + photo in answer | email; photo inline in **body** |
| 3 | prompt 1 **without** delivery | — | chart | explanation + chart | none (chat card) |
| 4 | prompt 2 **without** delivery | photo | — | caption + photo | none (chat) |

3/4 are 1/2 with an empty delivery lane — proving **content and delivery are separate lanes**.

## 3. The unified model — three abstractions

### (A) One Artifact Registry — capture ANY artifact once, address it once
Every non-text artifact — **inbound** (uploaded photo/doc) OR **generated** (chart/image/PDF/diagram) —
is registered once and gets `{artifact_id, kind, same-origin url, local path, mime, meta}`.
- **Generalizes the two capture mechanisms that already exist:** `chart_publisher` (render→upload→url) for
  generated visuals + `_artifact_snapshot` (sandbox diff) for files. The registry is the single choke-point:
  register → (upload to NewX media, reusing the `/internal/chart-upload` path, generalized to any media) →
  keep the local path for email attachment.
- **Numbers-by-reference / no-fabrication carries over:** a generated chart's data still comes from a real
  source (the data-charting rule); the registry stores the produced bytes, never LLM-typed content.

### (B) RAICA emits markers (placement); NewX OWNS rendering/style — closes G1
**Platform boundary (decided):** RAICA is the intelligent AGENT — it decides WHETHER, WHEN, and WHICH artifact
to include and emits a placement **marker**; it does **NOT** decide **style**. NewX is the UI PLATFORM — it OWNS
the marker→visual rendering (the *single* source of style), for the chat reply AND for delivered files.
- Content references artifacts by one small marker family: `[[chart:…]]` (exists) + `[[image:…]]` + `[[file:…]]`
  (new), one grammar. RAICA *places* them; it **never** converts them to styled HTML.
- **Chat target:** NewX renders markers → card/inline (as today for `[[chart:]]`), extended to image/file
  (`[[file:]]` → **inline preview**, decision §8.3).
- **Delivery target (the G1 fix):** the styled, self-contained HTML/PDF deliverable is ALSO produced by NewX's
  renderer — RAICA calls a **NewX render endpoint** with the answer+markers, receives the rendered self-
  contained HTML back, then packages/emails it (RAICA owns *delivery*: `secure_email_sender`, recipient lock).
  RAICA does NOT style the deliverable. (This is a NEW NewX capability: "render answer+markers → self-contained
  styled HTML"; the existing RAICA `pdf_generator` HTML template moves to / is owned by NewX so style lives in
  one place.)
- Result: ONE renderer (NewX), two outputs (chat + file) → a chart looks identical in the reply and in the
  emailed HTML, never raw `[[chart:…]]` text.

### (C) Content-vs-Delivery split — closes G3, enables 3/4 = 1/2 minus delivery
`_decompose_request` (`pipeline.py:218`) strips **only OUTBOUND DELIVERY** — save-as-file/PDF/HTML, email,
post, and recipients — from `research_request`. It **keeps** all *content* requirements, including "include
a chart/plot/graph/diagram of X" and "caption the photo." Rationale is already in its docstring (`:229`):
stripping exists so the engine never refuses over "can't email/PDF" — a **chart never triggers that**, so it
must not be stripped. Delivery (Phase-2, `_run_dr_delivery`) then operates on the FINISHED answer, whose
artifact markers are already rendered by (B), and packages/emails it.
- Inbound artifacts (G2): registered in (A) at ingest, and referenced from the answer by an `[[image:…]]`
  marker so they are echoed to output (chat and/or email body) — same renderer (B).

## 4. How each acceptance prompt flows (end-to-end, through the real stages)

**Prompt 1 — Egypt chart + email HTML**
1. Decompose (C): `research_request` = "research Egypt population since 1960 with an explanation **and a chart
   of the trend**"; `actions=[email→sabawi@gmail.com, format=HTML]`; recipient locked per
   `orchestration/policy.py:42`.
2. Planner routes a sub-question to `search_datasets` (gather source) → World Bank Egypt population → chart
   rendered → registered (A) → `[[chart:url]]` in the tool's evidence (`engine.py:496` dispatch → evidence).
3. Synthesize writes the explanation and **reproduces `[[chart:]]`** from evidence (existing relay).
4. Chat target: answer streams; NewX renders the chart card (B).
5. Delivery: `_run_dr_delivery` calls the **NewX render endpoint** (answer+markers → self-contained styled
   HTML **with the `<img>`**), then emails that file to the locked recipient (`secure_email_sender`). RAICA
   orchestrates delivery; NewX did the styling.

**Prompt 2 — caption attached photo + email body**
1. Ingest: photo → registry (A) → `[[image:url]]`; vision (`:2204`) lets the LLM "see" it.
2. Decompose (C): `research_request` = "write a funny caption for the attached photo"; `actions=[email→…,
   place photo/caption in body]`.
3. Synthesize writes the caption and references `[[image:url]]`.
4. Delivery: (B) renders the body (caption + inline photo) → email body to the recipient.

**Prompt 3 = 1 without delivery** → steps 1–4, delivery lane empty → chat card only.
**Prompt 4 = 2 without delivery** → ingest + caption + `[[image:]]` echoed to chat, no email.

## 5. Where the data-charting fix lands inside this
- Chart generation/data acquisition (`datasources/*`, `utils/data_chart_generator.py`, `search_datasets`
  tool) is unchanged — it feeds the **registry (A)** and emits a `[[chart:]]` marker like today.
- **Issue A** (tool self-disable) collapses into one shared `data_charts_enabled()` (single source; env +
  config) — a NO-INCONSISTENCY fix regardless.
- **Issue B / G3** is fixed by (C): the chart survives into `research_request` → planner gathers it →
  marker in evidence → synthesis. No post-synthesis actions path.
- The chart now also appears in a delivered HTML/PDF via (B) — which it never did before.

## 6. Component inventory (reuse vs build)
| Piece | Reuse | Build |
|---|---|---|
| Artifact capture | `chart_publisher.publish_chart` (upload), `_artifact_snapshot` (files) | thin **registry** wrapping both |
| Marker relay in synthesis | `synthesis.py:37,681-740` (already relays `[[chart:]]`) | extend to `[[image:]]`/`[[file:]]` |
| Marker→visual rendering (STYLE) | NewX chat renderer (charts) | **NewX owns it** — extend to image/file; add a NewX "render answer+markers → self-contained styled HTML" endpoint for deliverables. RAICA emits markers only, never styles. |
| Decompose split | `_decompose_request` (`pipeline.py:218`) | policy edit: strip delivery only, keep content/artifacts |
| Delivery | `_run_dr_delivery` (`:7582`), `secure_email_sender`, `authorize_delivery` (`policy.py:42`) | call the shared renderer before packaging |
| Inbound register | `set_image_context` (`:528`), vision (`:2204`) | register inbound artifacts into (A) + emit `[[image:]]` |

## 7. Constraints honored
- **LLM-policy gate:** artifact *kind* routing is data (registry metadata), not `if/elif` on meaning; the
  decomposer decides content-vs-delivery by policy language, not keyword lists. NO-INCONSISTENCY: one
  `data_charts_enabled()`; one renderer; decompose/synthesis/delivery speak with one voice about what is
  content vs delivery.
- **Config directive:** any new config under `config/llm_config.yaml` (single source of truth).
- **Security:** recipient-lock (`authorize_delivery`) unchanged — a restricted client (NewX bot) can only
  deliver to the server-authoritative user email; fail-closed otherwise.
- **Fail-closed:** no trusted artifact → no marker; a marker whose artifact is missing renders as nothing,
  never as broken/raw text.

## 8. Decisions (RESOLVED 2026-07-20)
1. **Renderer placement → NewX owns all rendering/style.** RAICA (the agent) decides whether/when/which
   artifact and emits a placement marker; NewX (the UI) renders it — for chat AND for delivered files (via a
   new NewX "render answer+markers → self-contained styled HTML" endpoint). RAICA never styles. (See §3B, §6.)
2. **Inbound echo → only when the prompt references it.** An attachment is registered for recognition
   (vision/doc), but echoed to output (chat/email body) ONLY when the prompt refers to it (e.g. "the attached
   photo") — not auto-echoed.
3. **`[[file:]]` chat affordance → inline preview** (not a download chip). NewX picks the preview by mime.
4. **Marker grammar for non-image files → DECIDED:** one grammar across kinds —
   `[[<kind>:<same-origin-url>|caption="…"|align=center|w=…]]` for chart/image; files add descriptive
   attributes NewX needs for an inline preview:
   `[[file:<url>|name="report.pdf"|mime="application/pdf"|size=74556|caption="…"]]`. NewX chooses the inline
   affordance from `mime` (pdf preview, image, etc.); RAICA only fills the attributes (facts, not style).

## 9. Incremental build plan (each step verified through the REAL entry point, per the gate)
1. **Content-vs-delivery split (C) + Issue A** — smallest fix that makes prompt 3 (chart in chat) work
   end-to-end. Verify via a real `/v1` DR run (not an isolated stub).
2. **Registry (A)** wrapping the two existing capture paths; generated-chart path first.
3. **Shared marker renderer (B)** + RAICA file-packaging integration → prompt 1 (chart in emailed HTML).
4. **Inbound artifact register + `[[image:]]`** → prompts 2 & 4.
5. NewX-side `[[image:]]`/`[[file:]]` rendering as needed.

## 10. Acceptance tests
The 4 prompts above, each asserted through the real `/v1` entry point end-to-end:
- Chat: the answer contains the correct rendered artifact (card/inline), not raw markers.
- Delivery: the emailed HTML/body contains the real `<img>`/file — verified by fetching the delivered file,
  not by parsing a log.
- With/without delivery toggles the delivery lane only; content is identical.

## 11. Back-out
Branch `feature/unified-artifacts`; each increment flag-gated where it changes live behavior. Drop the branch
to abandon. `main` and prod untouched until a benchmarked, end-to-end-verified merge.
