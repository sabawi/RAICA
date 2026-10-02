"""
Embeddings for other services — backs `POST /v1/embeddings` (OpenAI-compatible).

Why it exists: NewX's adaptive-profiling phase P1 turns each public post (caption + vision tags)
into a vector. RAICA already owns an embedding provider (`document_interrogator.embedding` in
config/llm_config.yaml), so NewX reaches it through RAICA instead of holding its own key and model
choice (NewX docs/DESIGN_adaptive_profiling.md D7).

Pure infrastructure: no interpretation of text, no lists, no special cases — it forwards text to
the configured provider and returns vectors.

FAIL FAST (docs/PROJECT_CONFIGURATION_DIRECTIVE.md): every value comes from llm_config.yaml; a
missing one raises EmbeddingsConfigError. Unlike the document interrogator's loader, this NEVER
falls back to another model — vectors from a different model live in a different space, so a silent
fallback would quietly corrupt every similarity a caller computes. The model actually used is
returned with every response so callers can refuse to mix models.
"""
import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class EmbeddingsConfigError(RuntimeError):
    """llm_config.yaml lacks a value this endpoint needs."""


class EmbeddingsProviderError(RuntimeError):
    """The provider failed or answered with something unusable."""


def _req(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur or cur[part] in (None, ''):
            raise EmbeddingsConfigError('llm_config.yaml: missing %s' % path)
        cur = cur[part]
    return cur


LOCAL_PROFILE = 'local'


def load_embeddings_api_config(profile: str = None) -> Dict[str, Any]:
    """Everything the endpoint needs, read strictly from llm_config.yaml.

    `profile` None = the default provider (document_interrogator.embedding). 'local' = the on-box
    model under embeddings_api.local (NewX semantic search: a member's query never leaves the box).
    Each profile is its own vector space; a caller selects one explicitly and never gets the other."""
    from utils.config_loader import config_loader
    cfg = config_loader.load_config() or {}
    api = _req(cfg, 'embeddings_api')
    if not isinstance(api, dict):
        raise EmbeddingsConfigError('llm_config.yaml: embeddings_api must be a mapping')
    if profile == LOCAL_PROFILE:
        emb = _req(cfg, 'embeddings_api.local')
    elif profile is None:
        emb = _req(cfg, 'document_interrogator.embedding')
    else:
        raise EmbeddingsConfigError('unknown embeddings profile %r' % profile)
    out = {
        'enabled': bool(_req(api, 'enabled')),
        'max_inputs': int(_req(api, 'max_inputs')),
        'max_chars_per_input': int(_req(api, 'max_chars_per_input')),
        'provider': str(_req(emb, 'provider')),
        'model': str(_req(emb, 'model_name')),
        'dimension': int(_req(emb, 'dimension')),
        'base_url': str(_req(emb, 'service.base_url')).rstrip('/'),
        'timeout': float(_req(emb, 'timeout.embedding_request')),
    }
    if out['provider'] != 'ollama':
        out['api_key'] = str(_req(emb, 'service.api_key'))
        if out['api_key'].startswith('${'):
            raise EmbeddingsConfigError('llm_config.yaml: service.api_key references an unset '
                                        'environment variable')
    if out['max_inputs'] < 1 or out['max_chars_per_input'] < 1 or out['dimension'] < 1:
        raise EmbeddingsConfigError('llm_config.yaml: embeddings_api limits must be positive')
    return out


def resolve_profile(requested: Any) -> str:
    """The profile a request's `model` field selects: absent = default (None); 'local' or the
    configured local model name = 'local'. Anything else is refused (ValueError) — never a silent
    substitution, since vectors from another model would sit in another space."""
    if requested in (None, ''):
        return None
    if requested == LOCAL_PROFILE:
        return LOCAL_PROFILE
    try:
        local = load_embeddings_api_config(LOCAL_PROFILE)['model']
    except EmbeddingsConfigError:
        local = None
    if local and requested == local:
        return LOCAL_PROFILE
    raise ValueError('unknown model %r (use "%s" for the on-box model, or omit for the default)'
                     % (requested, LOCAL_PROFILE))


def validate_inputs(raw: Any, cfg: Dict[str, Any]) -> List[str]:
    """The request's `input` as a list of strings, or ValueError with a reason for the caller."""
    texts = [raw] if isinstance(raw, str) else raw
    if not isinstance(texts, list) or not texts:
        raise ValueError('`input` must be a non-empty string or list of strings')
    if len(texts) > cfg['max_inputs']:
        raise ValueError('at most %d inputs per request (got %d)' % (cfg['max_inputs'], len(texts)))
    for i, t in enumerate(texts):
        if not isinstance(t, str) or not t.strip():
            raise ValueError('input[%d] must be a non-empty string' % i)
        if len(t) > cfg['max_chars_per_input']:
            raise ValueError('input[%d] exceeds %d characters' % (i, cfg['max_chars_per_input']))
    return texts


async def embed_texts(texts: List[str], cfg: Dict[str, Any]) -> Tuple[List[List[float]], int]:
    """Vectors for `texts` from the configured provider, in order, plus prompt tokens (0 if the
    provider does not report them). Raises EmbeddingsProviderError on any failure or on a
    response whose count or dimension does not match the configuration."""
    from http_helpers import pooled_post
    vectors: List[List[float]] = []
    tokens = 0
    if cfg['provider'] == 'ollama':
        for t in texts:
            r = await pooled_post(cfg['base_url'] + '/api/embeddings',
                                  json={'model': cfg['model'], 'prompt': t},
                                  timeout=cfg['timeout'])
            if r.get('status_code') != 200:
                raise EmbeddingsProviderError('provider HTTP %s: %s'
                                              % (r.get('status_code'), str(r.get('text'))[:200]))
            try:
                vectors.append([float(x) for x in json.loads(r['text'])['embedding']])
            except Exception as e:                       # noqa: BLE001
                raise EmbeddingsProviderError('unreadable provider response: %s' % type(e).__name__)
    else:
        r = await pooled_post(cfg['base_url'] + '/embeddings',
                              json={'model': cfg['model'], 'input': texts,
                                    'dimensions': cfg['dimension']},
                              headers={'Authorization': 'Bearer ' + cfg['api_key']},
                              timeout=cfg['timeout'])
        if r.get('status_code') != 200:
            raise EmbeddingsProviderError('provider HTTP %s: %s'
                                          % (r.get('status_code'), str(r.get('text'))[:200]))
        try:
            body = json.loads(r['text'])
            rows = sorted(body['data'], key=lambda d: d['index'])
            vectors = [[float(x) for x in d['embedding']] for d in rows]
            tokens = int((body.get('usage') or {}).get('prompt_tokens') or 0)
        except Exception as e:                           # noqa: BLE001
            raise EmbeddingsProviderError('unreadable provider response: %s' % type(e).__name__)
    if len(vectors) != len(texts):
        raise EmbeddingsProviderError('provider returned %d vectors for %d inputs'
                                      % (len(vectors), len(texts)))
    bad = [i for i, v in enumerate(vectors) if len(v) != cfg['dimension']]
    if bad:
        raise EmbeddingsProviderError('vector %d has dimension %d, configured %d'
                                      % (bad[0], len(vectors[bad[0]]), cfg['dimension']))
    return vectors, tokens
