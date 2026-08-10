"""Contract for `config_server_cli.py convert` — provider change is NOT model change.

WHY THIS COMMAND EXISTS
-----------------------
Converting RAICA between providers by hand meant editing 9+ model settings across
several config blocks. Done manually on 2026-08-09 it went wrong twice:

  1. Five models were SUBSTITUTED rather than mapped (deepseek-v4-pro -> V3.1,
     DR-heavy -> GLM-5.2, minimax-m3 -> Qwen3-VL, ...) without checking whether the
     target served the originals. It served every one. The substitution confounded
     the A/B (provider AND model changed at once) and manufactured a truncation
     ceiling that did not exist — `max_answer_tokens: 32000` was tuned to the
     ORIGINAL model, so a different model blew through it and cost 12/16 then 4/24
     chart markers.
  2. Two lanes were MISSED entirely (deep_research.engine on the first pass, and
     convergence.intent_classifier/shadow_classifier were never converted at all).

So the command enforces what a human doing this under time pressure does not:
same-model-or-refuse, whole-config discovery, verification by invocation, and a
before/after table that matches what actually gets written.

These tests FAIL if any of those guarantees regress.
"""
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config_server_cli import ModelAliasManager  # noqa: E402

CANON = ModelAliasManager._canonical_model


# ------------------------------------------------------- identity normalisation
@pytest.mark.parametrize("ollama,deepinfra", [
    ("deepseek-v4-pro:cloud", "deepseek-ai/DeepSeek-V4-Pro"),
    ("deepseek-v4-flash:cloud", "deepseek-ai/DeepSeek-V4-Flash"),
    ("glm-5.2:cloud", "zai-org/GLM-5.2"),
    ("gpt-oss:120b-cloud", "openai/gpt-oss-120b"),
    ("minimax-m3:cloud", "MiniMaxAI/MiniMax-M3"),
    ("kimi-k2.6:cloud", "moonshotai/Kimi-K2.6"),
])
def test_same_model_maps_across_providers(ollama, deepinfra):
    """The SAME model expressed by two providers must collapse to one identity."""
    assert CANON(ollama) == CANON(deepinfra), (
        f"{ollama!r} and {deepinfra!r} are the same model but normalise to "
        f"{CANON(ollama)!r} vs {CANON(deepinfra)!r} — the converter would report "
        f"'not served' and refuse a conversion that is actually possible."
    )


@pytest.mark.parametrize("a,b", [
    # Variant tokens are IDENTITY, not packaging. Stripping 'turbo' once made the
    # converter silently pick gpt-oss-120b-Turbo in place of gpt-oss-120b.
    ("openai/gpt-oss-120b", "openai/gpt-oss-120b-Turbo"),
    ("deepseek-ai/DeepSeek-V4-Flash", "deepseek-ai/DeepSeek-V4-Flash-0731"),
    ("deepseek-ai/DeepSeek-V4-Pro", "deepseek-ai/DeepSeek-V4-Flash"),
    ("zai-org/GLM-5.2", "zai-org/GLM-4.6"),
])
def test_distinct_models_do_not_collide(a, b):
    """Different models must NEVER share an identity key."""
    assert CANON(a) != CANON(b), (
        f"{a!r} and {b!r} both normalise to {CANON(a)!r}. The converter picks "
        f"whichever the catalog lists first — a SILENT model substitution, which is "
        f"the single thing this command exists to prevent."
    )


# ------------------------------------------------------------ lane discovery
def test_discovery_covers_the_whole_config_not_just_the_llm_block():
    """vision / arbitrator / deep_research / code_generation are TOP-LEVEL keys.

    Walking only `llm:` finds 3 lanes and silently leaves Deep Research, vision and
    the classifiers on the old provider — the exact miss made by hand.
    """
    cfg = yaml.safe_load((ROOT / "config" / "llm_config.yaml").read_text())
    mgr = ModelAliasManager()

    llm_only = mgr._discover_lanes(cfg.get("llm", {}))
    whole = mgr._discover_lanes(cfg)

    assert len(whole) > len(llm_only) * 3, (
        f"whole-config discovery found {len(whole)} lanes vs {len(llm_only)} under "
        f"llm: — discovery is not reaching the top-level blocks"
    )
    paths = {lane["path"] for lane in whole}
    for required in ("vision.config.model", "arbitrator.config.model",
                     "deep_research.engine.model",
                     "deep_research.engine.heavy_model"):
        assert required in paths, f"{required} not discovered — it would be left behind"


def test_inert_lanes_are_classified_as_inert():
    """model_presets / fallback / providers must not count as ACTIVE lanes."""
    cfg = yaml.safe_load((ROOT / "config" / "llm_config.yaml").read_text())
    lanes = ModelAliasManager()._discover_lanes(cfg)
    inert_paths = {l["path"] for l in lanes if l["inert"]}
    assert any("model_presets" in p for p in inert_paths)
    assert any("fallback" in p for p in inert_paths)


# ------------------------------------------------------------ secret expansion
def test_secret_expansion_reads_dotenv():
    """${VAR} must resolve from .env, or every probe 401s and reports 'inconclusive'.

    That misreads "we never authenticated" as "cannot verify the model" — the SI-009
    failure mode, in a new place.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        pytest.skip(".env not present in this environment")
    names = [l.split("=", 1)[0] for l in env_file.read_text().splitlines()
             if "=" in l and not l.startswith("#")]
    if not names:
        pytest.skip(".env has no assignments")
    resolved = ModelAliasManager._expand_secret("${%s}" % names[0])
    assert not resolved.startswith("${"), (
        f"${{{names[0]}}} did not expand from .env — probes will send no credentials"
    )


# ------------------------------------------------------- write/revert round-trip
def test_revert_tag_round_trips(tmp_path):
    """A converted line must carry its ORIGINAL value so --revert needs no backup."""
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    original = (
        "llm:\n"
        "  primary:\n"
        "    config:\n"
        "      model: deepseek-v4-pro:cloud   # keep this comment\n"
    )
    cfg.write_text(original)
    mgr.llm_config_file = cfg

    written = mgr._write_conversion(
        [{"path": "llm.primary.config.model",
          "model": "deepseek-v4-pro:cloud",
          "new": "deepseek-ai/DeepSeek-V4-Pro", "status": "same"}],
        "deepinfra")
    assert written == 1
    after = cfg.read_text()
    assert "deepseek-ai/DeepSeek-V4-Pro" in after
    assert "(was deepseek-v4-pro:cloud)" in after, "no revert tag written"
    assert "# keep this comment" in after, (
        "the original comment was destroyed — this writer exists precisely because "
        "yaml.dump() discards comments (SI-011)"
    )

    mgr.convert_revert(assume_yes=True)
    assert cfg.read_text() == original, "revert is not byte-identical to the original"


# ------------------------------------------------- transport must move with the model
def test_converting_rewrites_transport_not_just_model_names(tmp_path):
    """A lane's type/base_url must move too, or the config is broken.

    Rewriting model NAMES alone leaves `type: ollama` and the Ollama `base_url` in
    place, so the config sends the new provider's model ids to the OLD endpoint and
    every call 404s. The first version of this command did exactly that and produced
    a config that looked converted and could not serve a single request.
    """
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    cfg.write_text(
        "llm:\n"
        "  primary:\n"
        "    type: ollama\n"
        "    config:\n"
        "      model: deepseek-v4-pro:cloud\n"
        "      base_url: http://127.0.0.1:11434\n"
        "  providers:\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
        "      api_key: ${DEEPINFRA_API_KEY}\n"
    )
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "llm.primary.config.model", "model": "deepseek-v4-pro:cloud",
          "new": "deepseek-ai/DeepSeek-V4-Pro", "status": "same"}], "deepinfra")

    out = yaml.safe_load(cfg.read_text())
    assert out["llm"]["primary"]["type"] == "deepinfra", "type: was not converted"
    assert "deepinfra.com" in out["llm"]["primary"]["config"]["base_url"], \
        "base_url still points at the OLD provider"


def test_provider_definition_blocks_are_never_rewritten(tmp_path):
    """`providers:` blocks DEFINE each provider — converting them is destructive.

    An unscoped transport rewrite pointed the ollama, openai AND openrouter provider
    definitions all at the target's base_url, which destroys the definitions and makes
    --revert impossible.
    """
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    cfg.write_text(
        "llm:\n"
        "  primary:\n"
        "    type: ollama\n"
        "    config:\n"
        "      model: deepseek-v4-pro:cloud\n"
        "  providers:\n"
        "    ollama:\n"
        "      base_url: http://127.0.0.1:11434\n"
        "    openai:\n"
        "      base_url: https://api.openai.com/v1\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
    )
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "llm.primary.config.model", "model": "deepseek-v4-pro:cloud",
          "new": "deepseek-ai/DeepSeek-V4-Pro", "status": "same"}], "deepinfra")

    providers = yaml.safe_load(cfg.read_text())["llm"]["providers"]
    assert providers["ollama"]["base_url"] == "http://127.0.0.1:11434"
    assert providers["openai"]["base_url"] == "https://api.openai.com/v1"


def test_revert_restores_transport_keys_too(tmp_path):
    """Reverting only `model:` leaves the config HALF-migrated.

    New model ids still pointed at the new endpoint is neither the old state nor the
    new one — arguably worse than either, because it looks reverted.
    """
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    original = (
        "llm:\n"
        "  primary:\n"
        "    type: ollama\n"
        "    config:\n"
        "      model: deepseek-v4-pro:cloud\n"
        "      base_url: http://127.0.0.1:11434\n"
        "  providers:\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
    )
    cfg.write_text(original)
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "llm.primary.config.model", "model": "deepseek-v4-pro:cloud",
          "new": "deepseek-ai/DeepSeek-V4-Pro", "status": "same"}], "deepinfra")
    assert yaml.safe_load(cfg.read_text())["llm"]["primary"]["type"] == "deepinfra"

    mgr.convert_revert(assume_yes=True)
    assert cfg.read_text() == original, (
        "revert is not byte-identical — transport keys were left converted"
    )


# ------------------------------- SI-017: keyless -> credentialed provider
def test_converts_a_lane_that_has_NO_api_key_line(tmp_path):
    """A lane with no api_key must GAIN one when moving to a credentialed provider.

    The writer could only REWRITE an existing api_key line, never INSERT one. `vision`
    is exactly that case — a local Ollama endpoint needs no key — so converting it to
    DeepInfra left it uncredentialed and every image call returned
    `401 missing API key`. The A/B's whole vision case (0/3, BOTH arms) was voided partly
    by this.

    The earlier fixture HAD an api_key line, so the tests exercised the rewrite path and
    never the insert path. This one deliberately has none.
    """
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    cfg.write_text(
        "vision:\n"
        "  type: ollama\n"
        "  config:\n"
        "    model: minimax-m3:cloud\n"
        "    base_url: http://127.0.0.1:11434\n"
        "    fallback_model: kimi-k2.6:cloud\n"          # the line that broke adjacency
        "llm:\n"
        "  providers:\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
        "      api_key: ${DEEPINFRA_API_KEY}\n"
    )
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "vision.config.model", "model": "minimax-m3:cloud",
          "new": "MiniMaxAI/MiniMax-M3", "status": "same"}], "deepinfra")

    vision = yaml.safe_load(cfg.read_text())["vision"]["config"]
    assert vision.get("api_key"), (
        "vision has no api_key after conversion — every call will 401. The insert must "
        "key off BLOCK MEMBERSHIP, not on api_key happening to follow base_url: here "
        "`fallback_model` sits between them, which defeated the first attempt."
    )


def test_revert_DELETES_an_inserted_api_key_rather_than_restoring_a_literal(tmp_path):
    """An inserted line did not exist before, so reverting must remove it.

    Restoring the literal string 'ABSENT' would leave a bogus credential behind and
    break the byte-identical round-trip that makes --revert trustworthy.
    """
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    original = (
        "vision:\n"
        "  type: ollama\n"
        "  config:\n"
        "    model: minimax-m3:cloud\n"
        "    base_url: http://127.0.0.1:11434\n"
        "llm:\n"
        "  providers:\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
        "      api_key: ${DEEPINFRA_API_KEY}\n"
    )
    cfg.write_text(original)
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "vision.config.model", "model": "minimax-m3:cloud",
          "new": "MiniMaxAI/MiniMax-M3", "status": "same"}], "deepinfra")
    assert yaml.safe_load(cfg.read_text())["vision"]["config"].get("api_key")

    mgr.convert_revert(assume_yes=True)
    assert cfg.read_text() == original, "revert did not remove the inserted api_key line"
    assert "ABSENT" not in cfg.read_text()


def test_existing_api_key_is_not_duplicated(tmp_path):
    """A lane that already has a key must be rewritten, not given a second one."""
    mgr = ModelAliasManager()
    cfg = tmp_path / "llm_config.yaml"
    cfg.write_text(
        "arbitrator:\n"
        "  type: openai\n"
        "  config:\n"
        "    model: glm-5.2:cloud\n"
        "    api_key: \"ollama\"\n"
        "    base_url: http://127.0.0.1:11434/v1\n"
        "llm:\n"
        "  providers:\n"
        "    deepinfra:\n"
        "      base_url: https://api.deepinfra.com/v1/openai\n"
        "      api_key: ${DEEPINFRA_API_KEY}\n"
    )
    mgr.llm_config_file = cfg
    mgr._write_conversion(
        [{"path": "arbitrator.config.model", "model": "glm-5.2:cloud",
          "new": "zai-org/GLM-5.2", "status": "same"}], "deepinfra")

    assert cfg.read_text().count("api_key:") == 2, "api_key was duplicated"
