# DESIGN — real pictures from the web (`fetch_image`), and public-only fetching

Status: **APPROVED (owner, 2026-11-09: "go ahead with 1-3 and cover lookup_website too").** Built OFF by default.

## 1. What the owner asked for

NewX post 10240: "Summarize David Wright's book … POST an Image of the book in your response!" @Ask had no way to
obtain a real picture (no tool fetches images; `run_python_analysis` has no network; NewX shows only pictures stored
on the site), so it drew a typographic cover with matplotlib and captioned it a mock-up. The owner did not object to
the drawing — he was impressed — but expected the rational order a person would follow:

> a) take the easy route and upload one from the sources (which have it); b) if it cannot, or none is available,
> say explicitly that it tried to find a real one and, AFTER failing, decided to make one up.

and the method: **"give it the tools and the freedom to think through which way to go"** — capabilities and context,
not rules in code (CLAUDE.md: the LLM decides, RAICA executes).

## 2. What is built

1. **`fetch_image`** (`user_tools/fetch_image_tool.py`): the model names an image URL and the page it came from;
   RAICA downloads it (public addresses only, size and time limits from config), proves it is a picture by decoding
   it, re-encodes it from pixels (Pillow, bounded dimensions — a crafted file never reaches a browser as-is),
   publishes it through `utils/chart_publisher.publish_chart` (the same NewX upload as charts) and returns a
   `[[chart:…]]` marker whose caption credits the source, plus the source URLs as text. On failure it returns the
   reason (refused address, not a picture, too large, HTTP error, publishing off) so the model can decide what next.
2. **`lookup_website` shows the page's own pictures**: the page's declared preview image (`og:image`, via
   trafilatura metadata) and the images in it with their alt text, as absolute URLs, at most
   `lookup_website.max_images_listed`. Plain data; nothing in code decides what a "cover" or "photo" is.
3. **Policy wording, not code**: the tool descriptions say what each route gives (a real picture from a source vs a
   drawing by a program) and require the answer to say where any picture came from — and, when it drew one, that it
   did and why (what it tried first). Which route to take is the model's decision. Reconciled with the other layers
   the model receives (RAICA prompts, NewX Ask.yaml preamble, the citation guard) — §6.
4. **`utils/public_fetch.py`: every fetch of a URL a model can choose goes only to public addresses.** Used by
   `fetch_image` and by all four of `lookup_website`'s fetch paths (content-type probe, PDF, web page, data file).

## 3. Threat model (public_fetch)

The URL comes from the model, and the model takes instructions from anyone who can post `@Ask` and from any text it
reads (a fetched page, a document, a quoted reply). So every URL is attacker-chosen. Confirmed 2026-11-09 before this
work: `trafilatura.fetch_url` and `requests.get` both read a loopback-only service and returned its text, and
`lookup_website` checked nothing first — so "read http://127.0.0.1:5000/…" or a page that redirects there would put
RAICA's or NewX's internal answers (or the cloud metadata service at 169.254.169.254) into a public reply.

Controls (each a named test that goes red with the control removed — §8). Pages and PDFs are read up to `lookup_website.max_page_bytes` (trafilatura.fetch_url's own 20 MB cap, kept).

| Attack | Control |
|---|---|
| URL names a private/loopback/link-local/reserved address or `localhost` | resolve the host; refuse unless EVERY resolved address `is_global` (IPv4 and IPv6, incl. IPv4-mapped) |
| Public URL that redirects to an internal one | redirects followed by us, one hop at a time, each hop checked; at most `max_redirects` |
| DNS rebinding (the name resolves public at check time, private at connect time) | the socket's actual peer address is checked after connect, before any byte is sent (custom urllib3 connection classes) |
| Non-HTTP schemes (`file:`, `gopher:`, `ftp:`) | only `http`/`https` |
| Proxy environment variables silently routing traffic | `trust_env = False` |
| Huge or endless response (memory) | streamed, cut at the caller's byte cap, disclosed |
| Decompression bomb / crafted image | pixel count read from the header and refused over `max_pixels` BEFORE decoding (Pillow's process-wide limit is left alone) + full decode + re-encode; non-images refused |

Limits are in `config/llm_config.yaml` (`public_fetch`, `user_tools.fetch_image`) — no hardcoded values.

## 4. Data flow (fetch_image)

```
model: fetch_image(url, source_page, caption)
  → config enabled? → public_fetch.get(url, stream, max_bytes) [address checks + peer check + redirect checks]
  → Pillow: open (pixel cap) → load → convert → shrink to max_side → PNG bytes
  → publish_chart(png) → NewX /internal/chart-upload → /static/images/media/<file>
  → result: [[chart:url|caption="<caption> — source: <host>"]] + "retrieved from <url>, found on <source_page>"
```

NewX needs no change: the picture arrives as an uploaded file, shown only to signed-in members (media_access), and
its feed card shows it as the first in-text picture (NewX 1.0.0.580).

## 5. Switches and rollout

- `user_tools.fetch_image.enabled` — default **false** (shipped defaults); the tool answers "not enabled" otherwise.
- `public_fetch` has no off switch: refusing internal addresses is not optional.
- NewX: `fetch_image` joins `Ask.yaml` `allowed_tools` only after the real-path runs and the audit.

| Phase | What | Exit |
|---|---|---|
| P0 | `public_fetch` + `lookup_website` on it + page images; tests | red-team tests blocked, each red with its control removed; tool smoke green |
| P1 | `fetch_image` + policy wording, local, switch ON locally | real path (NewX `call_raica`, Ask's whitelist + fetch_image), the book prompt 3× + a no-picture case 3× |
| P2 | security audit (NewX `docs/SECURITY_SPEC_AND_AUDIT.md` §5) | entry written |
| P3 | live: deploy RAICA, switch ON, Ask.yaml whitelist + directive | first real request read in the log |

## 6. One voice — the layers the model receives

Checked: RAICA's primary/tool prompts (no rule about pictures), NewX Ask.yaml (STOCK & DATA CHARTS and PROGRAMS
directives cover chart markers; a new PICTURES directive states the same policy as the tool descriptions), NewX's
citation guard (a fetched picture comes with its source page URL, so the answer has a URL to cite).

## 7. Known siblings (not changed here — owner decision)

Other fetchers of URLs the model or the web can influence still have no address check: `search_web` and
`get_news_summaries` (they fetch result/feed pages), and `research/link_liveness.py` (HEAD/GET on every cited URL —
a blind request, the response is not shown). `lookup_website_old` is unreferenced dead code. Each can move to
`public_fetch` the same way.

## 8. Tests

`tests/utilities/test_public_fetch.py`, `tests/utilities/test_fetch_image_tool.py`, `tests/utilities/test_lookup_website_images.py` —
loopback / 10.x / 169.254 / ::1 / IPv4-mapped / `localhost` refused; redirect to loopback refused; rebinding (check
passes, connect lands on loopback) refused at the peer check; `file:` refused; byte cap; non-image refused; pixel
bomb refused; a real image re-encoded and published (publisher stubbed — no NewX write in tests); disabled switch.
