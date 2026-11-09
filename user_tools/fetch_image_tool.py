"""fetch_image — bring a real picture from the web into the answer, credited to its source.

Owner request 2026-11-09 (NewX post 10240): asked to "POST an Image of the book", Ask had no way to obtain a real
picture, so it drew a cover with matplotlib. The owner's expected order: take a real one from the sources first; if
that fails, say so and only then make one. Method: give the model the capability and let it choose
(docs/DESIGN_fetch_image_and_public_fetch.md).

Flow: url (model-chosen) → utils/public_fetch (public addresses only; redirects and the connected peer checked) →
Pillow decode under a pixel cap → re-encode from pixels as PNG (a crafted file never reaches a browser as-is) →
utils/chart_publisher.publish_chart (NewX's chart upload) → a [[chart:…]] marker this tool writes itself, captioned
with the source. Failures come back as reasons, so the model can decide what to do next.
Disabled unless user_tools.fetch_image.enabled is true.
"""
import asyncio
import io
import logging
from typing import Any, Dict
from urllib.parse import urlparse

try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool

try:
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker
except ImportError:  # loaded outside the server process
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker

logger = logging.getLogger(__name__)

_FAILED_NEXT = (" Tell the user plainly that you could not bring in a real picture from that source and why. You may "
                "try another source, or — if a picture is still useful — draw one with run_python_analysis, saying in "
                "the answer that it is a drawing made after the real one could not be retrieved.")


def load_settings():
    from utils.config_loader import config_loader
    cfg = (config_loader.load_config().get('user_tools') or {}).get('fetch_image')
    if not isinstance(cfg, dict):
        raise RuntimeError("user_tools.fetch_image is not configured")
    return cfg


def to_png(data, max_pixels, max_side):
    """Decode `data` as a picture and re-encode it as PNG from its pixels; ValueError when it is not one."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > max_pixels:      # header only: checked BEFORE any pixel is decoded
                raise ValueError(f"the picture is too large ({im.width}×{im.height})")
            im.load()
            im = im.convert('RGBA' if im.mode in ('RGBA', 'LA', 'P') else 'RGB')
            im.thumbnail((max_side, max_side))
            out = io.BytesIO()
            im.save(out, 'PNG', optimize=True)
            return out.getvalue(), im.size
    except (Image.DecompressionBombError, Image.UnidentifiedImageError, OSError) as e:
        raise ValueError(f"the file is not a readable picture ({type(e).__name__})") from e


def _caption(text, max_chars):
    """One line of plain text that cannot close or split the marker; cut on a word boundary, marked with '…'."""
    s = ' '.join(str(text or '').replace('|', '/').replace('[', '(').replace(']', ')').replace('*', '').split())
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rsplit(' ', 1)[0].rstrip(' ,;:(') + '…'


class FetchImageTool(BaseUserTool):

    @property
    def name(self) -> str:
        return "fetch_image"

    @property
    def description(self) -> str:
        return (
            "Bring a REAL picture from the web into your answer — a book cover, a photograph of a place, person, "
            "object or artwork, a published figure — taken from a source that has it. Give the picture's own address "
            "(`url`) and the page you found it on (`source_page`). Find addresses with lookup_website, which lists "
            "the pictures on each page it reads with the page's own descriptions, starting with the page's preview "
            "picture; choose the one that actually shows what the user asked for. You get a [[chart:…]] marker to "
            "place in your answer as given, captioned with its source, plus the source addresses: say in the answer "
            "where the picture comes from. If it fails you get the reason; then say you could not retrieve a real "
            "picture. A picture drawn by run_python_analysis is a DRAWING, never the real thing: if you draw one, say "
            "so in the answer, and say what you tried first."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The picture's own address (http or https)."},
                "source_page": {"type": "string",
                                "description": "The page the picture appears on, to credit and cite."},
                "caption": {"type": "string",
                            "description": "Short plain-text caption (no markdown) saying what the picture shows, "
                                           "e.g. 'Cover of Inventing God's Law (Oxford University Press, 2009)'."},
            },
            "required": ["url", "source_page"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        try:
            cfg = load_settings()
        except Exception as e:  # noqa: BLE001 — a missing section is a configuration fault, reported as such
            return {"success": False, "error": f"fetch_image: not configured ({e})"}
        if cfg.get('enabled') is not True:
            return {"success": False, "error": "fetch_image is not enabled on this server." + _FAILED_NEXT}
        url = str(kwargs.get('url') or '').strip()
        page = str(kwargs.get('source_page') or '').strip()
        if not url or not page:
            return {"success": False, "error": "fetch_image: `url` and `source_page` are both required."}
        caption = _caption(kwargs.get('caption'), int(cfg['max_caption_chars'])) or 'Picture'
        try:
            data, size = await asyncio.to_thread(self._download_and_encode, url, cfg)
        except Exception as e:  # noqa: BLE001 — every failure becomes a reason the model can act on
            logger.info("🖼️ fetch_image: %s — %s", url[:120], e)
            return {"success": False, "error": f"fetch_image: {url} could not be used — {e}." + _FAILED_NEXT}
        host = urlparse(page).hostname or urlparse(url).hostname or 'the web'
        published = await asyncio.to_thread(publish_chart, data, 'picture')
        if not published:
            return {"success": False, "error": "fetch_image: the picture was retrieved but could not be published "
                                               "on this site." + _FAILED_NEXT}
        logger.info("🖼️ fetch_image: published %s (%d×%d) from %s", published, size[0], size[1], url[:120])
        marker = _marker(published, f"{caption} — source: {host}")
        return {"success": True, "result": (
            f"{marker}\nA REAL picture, retrieved from {url} (found on {page}), {size[0]}×{size[1]} pixels, now "
            f"stored on this site. Place the marker above in your answer as given and cite {page} as its source.")}

    @staticmethod
    def _download_and_encode(url, cfg):
        from utils.public_fetch import get as public_get, read_capped
        r = public_get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                     "Accept": "image/*"},
                       timeout=int(cfg['timeout_seconds']), stream=True)
        if r.status_code >= 400:
            r.close()
            raise ValueError(f"the server answered HTTP {r.status_code}")
        data, cut = read_capped(r, int(cfg['max_bytes']))
        if cut:
            raise ValueError(f"the file is larger than {int(cfg['max_bytes']):,} bytes")
        return to_png(data, int(cfg['max_pixels']), int(cfg['max_side']))
