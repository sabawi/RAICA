# CHANGELOG v1.0.0.354 — 2026-11-09

## Real pictures from the web, and model-chosen URLs reach only the public internet

From NewX post 10240: asked to "POST an Image of the book", Ask drew a typographic cover with matplotlib, because no
tool could bring in a real picture. The owner's expected order: take a real one from the sources first; if that
fails, say so, and only then make one — "give it the tools and the freedom to think through which way to go".
Design: `docs/DESIGN_fetch_image_and_public_fetch.md`.

### Security — `utils/public_fetch.py`; `lookup_website` uses it on all four fetch paths
Measured before the change: `trafilatura.fetch_url` and `requests.get` read a loopback-only service and returned its
text, and `lookup_website` checked nothing, so a model-chosen URL (anyone can steer it) could read internal services
or a cloud metadata address into a public reply. Now: http/https only; every resolved address must be global
(IPv4, IPv6, IPv4-mapped); the CONNECTED peer is checked before a byte is sent (DNS rebinding); redirects are followed
hop by hop, each checked, at most `public_fetch.max_redirects`; proxy variables ignored. No off switch.
- Paths moved: content-type probe, PDF, web page (trafilatura now decodes what public_fetch fetched), data file;
  plus an up-front refusal with the reason. Siblings not moved (search_web, get_news_summaries, link_liveness): SI-116.
- Web pages and PDFs are read up to `lookup_website.max_page_bytes` (20 MB): trafilatura.fetch_url applied that cap
  itself, so replacing it without one would have let an endless page fill memory; the PDF path never had one.
- Tests: `tests/utilities/test_public_fetch.py` (23).

### Added — `lookup_website` lists the page's pictures
The page's declared preview picture (og:image) first, then its pictures with their alt text, absolute addresses, at
most `lookup_website.max_images_listed` (12). Data only. A missing setting lists nothing and logs an error; the page
text is unaffected. Tests: `tests/utilities/test_lookup_website_images.py` (6, incl. the page size cap).

### Added, OFF — `fetch_image` (`user_tools/fetch_image_tool.py`, `user_tools.fetch_image.enabled: false`)
Download through public_fetch (`max_bytes`, `timeout_seconds`), pixel count refused from the header over
`max_pixels` before decoding, decode, re-encode as PNG shrunk to `max_side`, publish through the chart upload, return
a `[[chart:…]]` marker captioned "<caption> — source: <host>" (plain text, `max_caption_chars`, cut on a word) and the
source addresses. Every failure is a reason, telling the model to say it could not bring in a real picture, and that
a picture drawn by run_python_analysis is a drawing. Tests: `tests/utilities/test_fetch_image_tool.py` (9).

### Changed — two existing tests moved to the new transport seam
`test_data_file_content_type.py` mocked `requests.get`, `test_si037_data_file_truncation.py` resolved example.org;
both now patch `utils.public_fetch` (same assertions).

### Evidence
- Planted defects: 16, each RED with its control removed (private addresses allowed, no peer check, library-followed
  redirects, proxy trusted, scheme unchecked, no up-front check, web page via trafilatura, pixel cap, shrink, caption,
  switch, byte cap, declared picture, listing not printed, missing limit, page size cap).
- Real path (NewX `call_raica`, Ask's whitelist + fetch_image, local, switch ON locally): the book prompt 4/4 placed
  the real cover (OUP ×3, Open Library ×1; files opened and checked by eye); a made-up novel 3/3 said it could not be
  found and refused to present a drawing as its cover. NewX side counts (posts, replies, notifications, mail, push,
  settings) unchanged on all runs.
- `lookup_website` through the real tool manager: Wikipedia lists its pictures; `http://127.0.0.1:5000/health`
  refused; the Treasury CSV still read. `make smoke` passed.
- Unit suite: 1183 passed, 4 failed — the same 4 as 1.0.0.352/353 (SUSPECTED_ISSUES ~line 130).

### Config
`config_migrate` adds `public_fetch`, `lookup_website.max_images_listed`, `lookup_website.max_page_bytes` and `user_tools.fetch_image` to an existing
site file (additions, config_version unchanged).
