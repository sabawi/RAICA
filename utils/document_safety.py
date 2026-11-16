"""Generated documents carry only safe content, and their PDF renderer reads only the public internet (SI-119).

A generated document's body is model-written, so anything in it is attacker-influenceable: a member asking a bot for a
PDF, or a web page the model read. Measured 2026-11-16 (v1.0.0.357): content containing
`<a rel="attachment" href="file:///…">` made WeasyPrint embed that server file in the PDF (WeasyPrint was called with
no url_fetcher, so it read file:// and any network address), and `<script>` / `<img onerror=…>` stayed live in the
.html file.

Two guards, each needed on its own:
  * url_fetcher(): what WeasyPrint may read while rendering. data: URLs, and http(s) only through utils/public_fetch
    (public addresses, every redirect hop checked), capped at fetch_max_bytes. Anything else raises: WeasyPrint skips
    that resource and still builds the PDF.
  * sanitize_body(): the document body cut down to the configured allow-list before BOTH formats are written.
    remove_with_content elements are dropped whole; any other tag outside the list is dropped with its text kept.

Settings: `document_safety` in config/llm_config.yaml (fail fast when missing: no hardcoded fallbacks). No off switch.
"""
import logging
from email.message import Message
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_KEYS = ('fetch_max_bytes', 'allowed_tags', 'allowed_attributes', 'link_protocols', 'image_protocols',
         'remove_with_content')


class DocumentFetchRefused(Exception):
    """The PDF renderer asked for a resource that is not a data: URL or a public http(s) address."""


def settings():
    from utils.config_loader import config_loader
    cfg = config_loader.load_config().get('document_safety')
    if not isinstance(cfg, dict) or any(k not in cfg for k in _KEYS):
        raise RuntimeError("document_safety is not configured (config/llm_config.yaml: document_safety."
                           + ", document_safety.".join(_KEYS) + ")")
    return cfg


def _scheme(value):
    return (urlparse((value or '').strip()).scheme or '').lower()


def url_fetcher(url, timeout=10, ssl_context=None, http_headers=None):
    """WeasyPrint url_fetcher (same signature as weasyprint.default_url_fetcher). Never reads the local disk or an
    internal address."""
    scheme = _scheme(url)
    if scheme == 'data':
        from weasyprint.urls import default_url_fetcher
        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context, http_headers=http_headers)
    if scheme not in ('http', 'https'):
        logger.warning("[DOC-SAFETY] PDF renderer refused %s:// resource (only data: and public http(s))",
                       scheme or '(none)')
        raise DocumentFetchRefused(f"refused: a document may only load data: or public http(s) resources "
                                   f"(got '{scheme or '?'}')")
    from utils import public_fetch
    cfg = settings()
    try:
        r = public_fetch.get(url, headers=http_headers, stream=True)
    except public_fetch.PublicFetchRefused as e:
        logger.warning("[DOC-SAFETY] PDF renderer refused %s: %s", url[:200], e)
        raise DocumentFetchRefused(str(e)) from e
    data, cut = public_fetch.read_capped(r, int(cfg['fetch_max_bytes']))
    if cut:
        logger.warning("[DOC-SAFETY] PDF renderer skipped %s: larger than %s bytes", url[:200], cfg['fetch_max_bytes'])
        raise DocumentFetchRefused(f"refused: resource larger than {cfg['fetch_max_bytes']} bytes")
    m = Message()
    m['content-type'] = r.headers.get('Content-Type', '')
    out = {'string': data, 'redirected_url': r.url}
    if m.get_content_type() and r.headers.get('Content-Type'):
        out['mime_type'] = m.get_content_type()
    if m.get_param('charset'):
        out['encoding'] = m.get_param('charset')
    return out


def sanitize_body(html):
    """The body HTML with only the allow-listed tags, attributes, link/picture addresses and safe inline CSS."""
    import bleach
    from bleach.css_sanitizer import CSSSanitizer
    from bs4 import BeautifulSoup

    cfg = settings()
    soup = BeautifulSoup(html or '', 'html.parser')
    for el in soup.find_all([str(t).lower() for t in cfg['remove_with_content']]):
        el.decompose()

    allowed = {str(k): {str(a).lower() for a in v} for k, v in (cfg['allowed_attributes'] or {}).items()}
    link_ok = {str(p).lower() for p in cfg['link_protocols']}
    image_ok = {str(p).lower() for p in cfg['image_protocols']}

    def attr_ok(tag, name, value):
        name = name.lower()
        if name not in allowed.get('*', set()) and name not in allowed.get(tag, set()):
            return False
        if tag == 'img' and name == 'src':
            s = _scheme(value)
            return value.strip().lower().startswith('data:image/') if s == 'data' else (s in image_ok or not s)
        if name == 'href':
            s = _scheme(value)
            return not s or s in link_ok
        return True

    cleaner = bleach.Cleaner(
        tags={str(t).lower() for t in cfg['allowed_tags']},
        attributes=attr_ok,
        protocols=link_ok | image_ok | {'data'},      # data: survives bleach only where attr_ok allowed it (img src)
        strip=True, strip_comments=True,
        css_sanitizer=CSSSanitizer())
    return cleaner.clean(str(soup))


def safe_css(css):
    """Caller-supplied CSS for the document's <style> block, or '' when it could close that block (`<`)."""
    if css and '<' in css:
        logger.warning("[DOC-SAFETY] custom CSS dropped: it contains '<' (could close the <style> block)")
        return ''
    return css or ''
