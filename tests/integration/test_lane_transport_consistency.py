"""Tier-0 gate (SI-056): every lane's MODEL must belong to its own BASE_URL's transport.

FAILURE THIS PREVENTS
---------------------
The Ollama->DeepInfra migration moved some lanes and left others behind, producing configs
where the model name and the endpoint disagreed. Nothing detected it:

  arbitrator:  model: zai-org/GLM-5.2          <- a DeepInfra slug
               base_url: http://127.0.0.1:11434/v1   <- the LOCAL OLLAMA proxy

Verified by invoking it: HTTP 404 {"message":"model 'zai-org/GLM-5.2' not found"}. Measured
over one night: 178 arbitrator attempts, 1 success, 34 runs exhausting all 5 tries. A failing
arbitrator regenerates tools up to 5x per request, and that loop is what surfaced SI-048/051/052.

The existing parity contract asserts a provider CONSUMES the parameters callers pass. It says
nothing about whether a lane's model is SERVED BY its endpoint. This closes that gap.

WHY STRUCTURAL AND NOT A LIVE PROBE
-----------------------------------
Tier-0 is the deterministic, offline, pre-commit floor. A network probe here would make commits
fail on someone else's rate limiter — the SI-054 trap. So this asserts the structural invariant
only; live reachability belongs in `make smoke`, which already invokes things for real.

THE INVARIANT
-------------
The two ecosystems name models differently, and the shapes do not overlap:
  * Ollama       -> "name:tag"        (a colon, never a slash)   e.g. minimax-m3:cloud
  * OpenAI-compat-> "vendor/model"    (a slash)                  e.g. zai-org/GLM-5.2
A local Ollama endpoint therefore must not be given a slashed vendor slug, and a remote
OpenAI-compatible endpoint must not be given a ":cloud"-style Ollama tag.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utils.config_loader import config_loader  # noqa: E402


def _lanes():
    """(lane_name, model, resolved_base_url) for EVERY active lane.

    SI-057 — this used to walk `llm.*`, `arbitrator` and `vision` by hand and read each
    block's OWN base_url. That inventory missed every lane which INHERITS the primary
    endpoint, which is exactly where six broken lanes were hiding:
      deep_research.engine.model/.heavy_model, convergence.shadow_classifier,
      convergence.intent_classifier, code_generation.selected_model/.classification_model
    All six carried Ollama `name:cloud` slugs while resolving to DeepInfra, and all six
    returned HTTP 404 on every call.

    Now it reuses the configurator's own discovery and endpoint resolution, so this gate,
    `lanes`, `doctor` and `convert` share ONE inventory and cannot disagree about what a
    lane is or where it points.
    """
    from config_server_cli import ModelAliasManager
    manager = ModelAliasManager()
    cfg = manager._load_llm_config()
    primary = manager._primary_endpoint(cfg)
    return [(lane["path"], lane["model"], lane["own_endpoint"] or primary or "")
            for lane in manager._discover_lanes(cfg) if not lane["inert"]]


def _is_local_ollama(base_url: str) -> bool:
    return ("11434" in base_url) or ("localhost:11434" in base_url)


def test_no_lane_pairs_a_remote_slug_with_the_local_ollama_endpoint():
    """THE SI-056 defect: a `vendor/model` slug sent to 127.0.0.1:11434 is a guaranteed 404."""
    bad = [(l, m, b) for l, m, b in _lanes() if _is_local_ollama(b) and "/" in m]
    assert not bad, (
        "lane(s) point a vendor/model slug at the LOCAL OLLAMA endpoint, which cannot serve it: "
        + "; ".join(f"{l}: model={m!r} base_url={b!r}" for l, m, b in bad)
    )


def test_no_lane_pairs_an_ollama_tag_with_a_remote_endpoint():
    """The mirror defect: `name:cloud` sent to a vendor API is equally unservable."""
    bad = [(l, m, b) for l, m, b in _lanes()
           if b and not _is_local_ollama(b) and ":" in m and "/" not in m]
    assert not bad, (
        "lane(s) point an Ollama-style name:tag at a REMOTE endpoint: "
        + "; ".join(f"{l}: model={m!r} base_url={b!r}" for l, m, b in bad)
    )


def test_every_remote_lane_carries_an_api_key():
    """A remote endpoint with no key fails closed at request time, not at config time."""
    cfg = config_loader.load_config()
    missing = []
    for lane in ("arbitrator", "vision"):
        c = (cfg.get(lane) or {}).get("config") or {}
        b = c.get("base_url") or ""
        if b and not _is_local_ollama(b) and not c.get("api_key"):
            missing.append(lane)
    for lane, node in (cfg.get("llm") or {}).items():
        c = (node or {}).get("config") or {}
        b = c.get("base_url") or ""
        if b and not _is_local_ollama(b) and not c.get("api_key"):
            missing.append(f"llm.{lane}")
    assert not missing, f"remote lane(s) configured without an api_key: {missing}"


def test_every_lane_declares_a_base_url():
    """A lane with no endpoint silently inherits someone else's default."""
    bad = [(l, m) for l, m, b in _lanes() if not b]
    assert not bad, f"lane(s) with no base_url: {bad}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
