"""Fetch a URL a model chose — but only from the public internet (docs/DESIGN_fetch_image_and_public_fetch.md §3).

Every URL a model names is attacker-chosen: anyone who can post @Ask, and any page or document the model reads, can
steer it. Measured 2026-11-09: `trafilatura.fetch_url` and `requests.get` both read a loopback-only service, and
`lookup_website` checked nothing first, so RAICA's and NewX's internal answers (or a cloud metadata service) could
be read back into a public reply.

Three checks, each needed on its own:
  1. before connecting: the scheme is http/https and EVERY address the host resolves to is global;
  2. after connecting, before a byte is sent: the socket's actual peer address is global (defeats DNS rebinding,
     where the name answers public at check time and private at connect time);
  3. redirects are followed here, one hop at a time, and each hop goes through 1 and 2 (`max_redirects`).
Proxy variables are ignored (trust_env=False), so traffic cannot be routed around the checks.

Settings: `public_fetch` in config/llm_config.yaml (fail fast when missing — no hardcoded fallbacks).
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool


class PublicFetchRefused(Exception):
    """The URL (or a redirect, or the connected peer) is not on the public internet, or the scheme is not http(s)."""


class HostUnresolved(PublicFetchRefused):
    """The host name did not resolve: not known to be internal, just unreachable now (a lenient caller may keep it)."""


def settings():
    from utils.config_loader import config_loader
    cfg = config_loader.load_config().get('public_fetch')
    if not isinstance(cfg, dict) or any(k not in cfg for k in ('max_redirects', 'timeout_seconds', 'connect_retries')):
        raise RuntimeError("public_fetch is not configured (config/llm_config.yaml: public_fetch.max_redirects, "
                           "public_fetch.timeout_seconds, public_fetch.connect_retries)")
    return cfg


def _is_public(ip_text):
    ip = ipaddress.ip_address(ip_text.split('%', 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url(url):
    """Raise PublicFetchRefused unless `url` is http(s) and its host resolves only to global addresses."""
    p = urlparse(url)
    if p.scheme not in ('http', 'https'):
        raise PublicFetchRefused(f"refused: only http and https addresses can be fetched (got '{p.scheme or '?'}')")
    host = p.hostname
    if not host:
        raise PublicFetchRefused("refused: the address has no host name")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise HostUnresolved(f"refused: the host '{host}' could not be resolved ({e})") from e
    addrs = {i[4][0] for i in infos}
    private = sorted(a for a in addrs if not _is_public(a))
    if not addrs or private:
        raise PublicFetchRefused(f"refused: '{host}' is not a public internet address — only public sites can be "
                                 f"fetched")


def _check_peer(sock, host):
    try:
        peer = sock.getpeername()[0]
    except OSError as e:
        sock.close()
        raise PublicFetchRefused(f"refused: could not confirm the address connected to for '{host}'") from e
    if not _is_public(peer):
        sock.close()
        raise PublicFetchRefused(f"refused: '{host}' connected to a non-public address — only public sites can be "
                                 f"fetched")


class _PublicHTTPConnection(HTTPConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        _check_peer(sock, self.host)
        return sock


class _PublicHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        _check_peer(sock, self.host)
        return sock


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)
        self.poolmanager.pool_classes_by_scheme = {'http': _PublicHTTPPool, 'https': _PublicHTTPSPool}


def session(connect_retries=0):
    s = requests.Session()
    s.trust_env = False                      # no proxy variables: traffic cannot be routed around the checks
    adapter = _PublicAdapter(max_retries=connect_retries)   # a refusal is not an OSError: never retried
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    return s


def get(url, headers=None, timeout=None, stream=False, method='GET'):
    """requests-style GET (or HEAD) that reaches only public addresses; redirects followed and checked hop by hop.
    Returns the final `requests.Response` (the caller closes it when `stream=True`)."""
    cfg = settings()
    timeout = timeout if timeout is not None else cfg['timeout_seconds']
    s = session(int(cfg['connect_retries']))
    current = url
    for _ in range(int(cfg['max_redirects']) + 1):
        check_url(current)
        r = s.request(method, current, headers=headers, timeout=timeout, stream=True, allow_redirects=False)
        if r.is_redirect and r.headers.get('Location'):
            nxt = urljoin(current, r.headers['Location'])
            r.close()
            current = nxt
            continue
        if not stream:
            r.content                         # read it now, as requests.get would
        return r
    raise PublicFetchRefused(f"refused: more than {cfg['max_redirects']} redirects")


def read_capped(response, max_bytes):
    """(bytes, cut) — at most `max_bytes` of the body; `cut` is True when there was more."""
    raw = response.raw.read(max_bytes + 1, decode_content=True) or b''
    response.close()
    return raw[:max_bytes], len(raw) > max_bytes
