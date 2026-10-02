"""
utils/embeddings_api.py — backs POST /v1/embeddings (NewX profiling P1).

No real provider is called: http_helpers.pooled_post is replaced. Each test names the failure it
prevents. Run: ./venv/bin/python -m pytest -q tests/unit/test_embeddings_api.py
"""
import asyncio
import copy
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils import embeddings_api as E  # noqa: E402

BASE_CFG = {
    'embeddings_api': {'enabled': True, 'max_inputs': 3, 'max_chars_per_input': 20,
                       'local': {'provider': 'ollama', 'model_name': 'all-minilm', 'dimension': 4,
                                 'service': {'base_url': 'http://127.0.0.1:11434'},
                                 'timeout': {'embedding_request': 5}}},
    'document_interrogator': {'embedding': {
        'provider': 'openai', 'model_name': 'text-embedding-3-small', 'dimension': 4,
        'service': {'base_url': 'https://provider.invalid/v1', 'api_key': 'k-123'},
        'timeout': {'embedding_request': 5}}},
}


def _cfg(mutate=None, profile=None):
    c = copy.deepcopy(BASE_CFG)
    if mutate:
        mutate(c)
    with mock.patch('utils.config_loader.config_loader.load_config', return_value=c):
        return E.load_embeddings_api_config(profile)


def _resp(vectors, status=200, tokens=7):
    body = {'data': [{'index': i, 'embedding': v} for i, v in enumerate(vectors)],
            'usage': {'prompt_tokens': tokens}}
    return {'status_code': status, 'text': json.dumps(body)}


def _run(coro):
    return asyncio.run(coro)


def test_config_is_read_strictly():
    c = _cfg()
    assert c['model'] == 'text-embedding-3-small' and c['dimension'] == 4 and c['max_inputs'] == 3


@pytest.mark.parametrize('path', ['embeddings_api', 'embeddings_api.max_inputs',
                                  'document_interrogator.embedding.model_name',
                                  'document_interrogator.embedding.dimension',
                                  'document_interrogator.embedding.service.api_key'])
def test_missing_config_fails_fast_never_falls_back(path):
    """No hardcoded fallback (PROJECT_CONFIGURATION_DIRECTIVE): a missing value is an error, not a
    default — a default MODEL would silently put vectors in a different space."""
    def drop(c):
        parts = path.split('.')
        cur = c
        for p in parts[:-1]:
            cur = cur[p]
        del cur[parts[-1]]
    with pytest.raises(E.EmbeddingsConfigError):
        _cfg(drop)


def test_unset_env_key_is_a_config_error():
    """`${OPENAI_API_KEY}` left unexpanded must not be sent as a bearer token."""
    with pytest.raises(E.EmbeddingsConfigError):
        _cfg(lambda c: c['document_interrogator']['embedding']['service'].__setitem__('api_key', '${OPENAI_API_KEY}'))


def test_input_validation_bounds():
    c = _cfg()
    assert E.validate_inputs('hello', c) == ['hello']
    assert E.validate_inputs(['a', 'b'], c) == ['a', 'b']
    for bad in (None, '', [], ['a', ''], ['a', 1], ['a'] * 4, ['x' * 21], {'a': 1}):
        with pytest.raises(ValueError):
            E.validate_inputs(bad, c)


def test_openai_path_returns_vectors_in_order_with_tokens():
    c = _cfg()
    resp = _resp([[0.1, 0.2, 0.3, 0.4], [1, 2, 3, 4]])
    body = json.loads(resp['text']); body['data'].reverse(); resp['text'] = json.dumps(body)
    with mock.patch('http_helpers.pooled_post', new=mock.AsyncMock(return_value=resp)) as p:
        vecs, tokens = _run(E.embed_texts(['a', 'b'], c))
    assert vecs == [[0.1, 0.2, 0.3, 0.4], [1.0, 2.0, 3.0, 4.0]] and tokens == 7
    sent = p.call_args.kwargs
    assert sent['json'] == {'model': 'text-embedding-3-small', 'input': ['a', 'b'], 'dimensions': 4}
    assert sent['headers'] == {'Authorization': 'Bearer k-123'}


@pytest.mark.parametrize('resp,needle', [
    (_resp([[0.1, 0.2, 0.3, 0.4]]), 'returned 1 vectors for 2 inputs'),
    (_resp([[0.1, 0.2, 0.3], [1, 2, 3, 4]]), 'dimension 3, configured 4'),
    (_resp([], status=429), 'HTTP 429'),
    ({'status_code': 200, 'text': 'not json'}, 'unreadable'),
])
def test_provider_problems_raise_instead_of_returning_bad_vectors(resp, needle):
    """A wrong count, a wrong dimension, a provider error or an unreadable body must never come
    back as vectors."""
    c = _cfg()
    with mock.patch('http_helpers.pooled_post', new=mock.AsyncMock(return_value=resp)):
        with pytest.raises(E.EmbeddingsProviderError) as ei:
            _run(E.embed_texts(['a', 'b'], c))
    assert needle in str(ei.value), str(ei.value)


def test_ollama_path_one_batched_call_that_truncates():
    """/api/embed with truncate: the legacy endpoint refused any text longer than the model's
    context (HTTP 500), failing the whole batch — found by the first real NewX index run."""
    c = _cfg(lambda c: c['document_interrogator']['embedding'].__setitem__('provider', 'ollama'))
    r = {'status_code': 200, 'text': json.dumps({'embeddings': [[0.5] * 4, [0.25] * 4],
                                                 'prompt_eval_count': 7})}
    with mock.patch('http_helpers.pooled_post', new=mock.AsyncMock(return_value=r)) as p:
        vecs, tokens = _run(E.embed_texts(['a', 'b'], c))
    assert vecs == [[0.5] * 4, [0.25] * 4] and p.call_count == 1 and tokens == 7
    assert p.call_args.args[0].endswith('/api/embed')
    assert p.call_args.kwargs['json'] == {'model': 'text-embedding-3-small', 'input': ['a', 'b'],
                                          'truncate': True}


def test_ollama_count_mismatch_is_an_error():
    c = _cfg(lambda c: c['document_interrogator']['embedding'].__setitem__('provider', 'ollama'))
    r = {'status_code': 200, 'text': json.dumps({'embeddings': [[0.5] * 4]})}
    with mock.patch('http_helpers.pooled_post', new=mock.AsyncMock(return_value=r)):
        with pytest.raises(E.EmbeddingsProviderError):
            _run(E.embed_texts(['a', 'b'], c))


# ── the on-box profile (NewX semantic search: the member's query never leaves the machine) ──
def test_local_profile_reads_its_own_section_and_needs_no_key():
    c = _cfg(profile='local')
    assert c['provider'] == 'ollama' and c['model'] == 'all-minilm' and c['dimension'] == 4
    assert c['base_url'] == 'http://127.0.0.1:11434' and 'api_key' not in c
    assert c['max_inputs'] == 3, 'request limits are shared'


def test_local_profile_missing_fails_fast():
    """No silent fallback to the default provider: that would send the query OFF the box."""
    with pytest.raises(E.EmbeddingsConfigError):
        _cfg(lambda c: c['embeddings_api'].pop('local'), profile='local')


@pytest.mark.parametrize('requested,expected', [(None, None), ('', None), ('local', 'local'),
                                                ('all-minilm', 'local')])
def test_model_field_selects_the_profile(requested, expected):
    with mock.patch('utils.config_loader.config_loader.load_config', return_value=copy.deepcopy(BASE_CFG)):
        assert E.resolve_profile(requested) == expected


@pytest.mark.parametrize('requested', ['text-embedding-3-large', 'gpt-4', 'LOCAL', 123])
def test_unknown_model_is_refused_never_substituted(requested):
    with mock.patch('utils.config_loader.config_loader.load_config', return_value=copy.deepcopy(BASE_CFG)):
        with pytest.raises(ValueError):
            E.resolve_profile(requested)


def test_local_profile_calls_the_on_box_daemon():
    c = _cfg(profile='local')
    r = {'status_code': 200, 'text': json.dumps({'embeddings': [[0.1, 0.2, 0.3, 0.4]]})}
    with mock.patch('http_helpers.pooled_post', new=mock.AsyncMock(return_value=r)) as p:
        vecs, _ = _run(E.embed_texts(['a query'], c))
    assert vecs == [[0.1, 0.2, 0.3, 0.4]]
    assert p.call_args.args[0] == 'http://127.0.0.1:11434/api/embed'
    assert p.call_args.kwargs['json'] == {'model': 'all-minilm', 'input': ['a query'], 'truncate': True}
