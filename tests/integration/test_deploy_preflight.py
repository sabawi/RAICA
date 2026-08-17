"""SI-060 / SI-061 — a deploy must not silently change provider or strand a credential.

FAILURES THESE PREVENT
----------------------
SI-060: "deploy the fixes" means `git pull`, and a pull carries config/llm_config.yaml, so
it also carries whatever provider the last local experiment left committed. Measured
2026-08-16: live ran every lane on Ollama; HEAD pointed every lane at api.deepinfra.com;
live's .env had no DEEPINFRA_API_KEY. Deploying would have 401'd every LLM call -- a total
outage from a change nobody intended. Every check we had validated the config against the
machine it was ON (where the key exists), never against the host it was going TO.

SI-061: `convert --to <keyless provider>` left the PREVIOUS provider's credential behind,
because API_KEY_ENV_VARS['ollama'] is None and the writer skipped the api_key rewrite when
the target needed no key. deepinfra -> ollama therefore produced
`api_key: ${DEEPINFRA_API_KEY}` on a 127.0.0.1 endpoint. Harmless on Ollama, which ignores
it -- but the same code path strands DEEPINFRA_API_KEY on an OpenRouter endpoint (a 401),
and it drifts the repo config away from the deployed one. Exact mirror of SI-017, which
fixed the keyless -> keyed direction only.
"""
import os
import subprocess
import sys
import textwrap

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from config_server_cli import ModelAliasManager  # noqa: E402

PREFLIGHT = os.path.join(ROOT, "tools", "deploy_preflight.py")


def _cfg(endpoint, api_key_line, model="m:cloud"):
    """Minimal but STRUCTURALLY REAL config: a provider block plus an inheriting lane."""
    return textwrap.dedent(f"""
        llm:
          providers:
            p1:
              base_url: {endpoint}
              {api_key_line}
          primary:
            type: p1
            config:
              model: {model}
              base_url: {endpoint}
              {api_key_line}
    """)


def _run(inc, tgt, env):
    return subprocess.run(
        [sys.executable, PREFLIGHT, "--incoming-file", inc,
         "--target-config", tgt, "--target-env", env],
        capture_output=True, text=True, timeout=120)


@pytest.fixture
def env_file(tmp_path):
    def make(names):
        p = tmp_path / "env.txt"
        p.write_text("\n".join(names))
        return str(p)
    return make


# ─────────────────────────────────────────────────────────── SI-060
def test_migration_to_a_provider_the_target_cannot_authenticate_is_NO_GO(tmp_path, env_file):
    """THE outage. Incoming moves the lane to a keyed vendor the target has no secret for."""
    inc = tmp_path / "inc.yaml"
    inc.write_text(_cfg("https://api.vendor.example/v1", "api_key: ${VENDOR_KEY}"))
    tgt = tmp_path / "live.yaml"
    tgt.write_text(_cfg("http://127.0.0.1:11434", 'api_key: "local"'))

    r = _run(str(inc), str(tgt), env_file(["OPENAI_API_KEY"]))
    assert r.returncode == 1, f"expected NO-GO, got {r.returncode}\n{r.stdout}"
    assert "NO-GO" in r.stdout
    assert "VENDOR_KEY" in r.stdout, "did not name the missing secret"
    assert "PROVIDER MIGRATION" in r.stdout, "did not report the endpoint change"


def test_same_config_deployed_to_itself_is_GO(tmp_path, env_file):
    """CONTROL. Without this, a gate that always says NO-GO would look like it works."""
    same = _cfg("http://127.0.0.1:11434", 'api_key: "local"')
    inc = tmp_path / "inc.yaml"; inc.write_text(same)
    tgt = tmp_path / "live.yaml"; tgt.write_text(same)

    r = _run(str(inc), str(tgt), env_file([]))
    assert r.returncode == 0, f"expected GO, got {r.returncode}\n{r.stdout}"
    assert "No provider migration" in r.stdout


def test_migration_the_target_CAN_authenticate_is_a_decision_not_a_failure(tmp_path, env_file):
    """A credentialled migration is legitimate -- but it must never pass SILENTLY."""
    inc = tmp_path / "inc.yaml"
    inc.write_text(_cfg("https://api.vendor.example/v1", "api_key: ${VENDOR_KEY}"))
    tgt = tmp_path / "live.yaml"
    tgt.write_text(_cfg("http://127.0.0.1:11434", 'api_key: "local"'))

    r = _run(str(inc), str(tgt), env_file(["VENDOR_KEY"]))
    assert r.returncode == 2, f"expected GO-WITH-DECISION, got {r.returncode}\n{r.stdout}"
    assert "PROVIDER MIGRATION" in r.stdout


def test_a_secret_no_active_lane_uses_is_not_reported(tmp_path, env_file):
    """False alarms get gates ignored.

    The first version dumped every provider block for every lane, so it demanded
    OPENROUTER_* and ANTHROPIC_API_KEY for lanes serving neither -- 5 of 7 rows wrong.
    """
    inc = tmp_path / "inc.yaml"
    inc.write_text(_cfg("http://127.0.0.1:11434", 'api_key: "local"') + textwrap.dedent("""
              unused_vendor:
                base_url: https://api.unused.example/v1
                api_key: ${UNUSED_KEY}
    """))
    tgt = tmp_path / "live.yaml"
    tgt.write_text(_cfg("http://127.0.0.1:11434", 'api_key: "local"'))

    r = _run(str(inc), str(tgt), env_file([]))
    assert "UNUSED_KEY" not in r.stdout, "demanded a secret no active lane uses"
    assert r.returncode == 0


# ─────────────────────────────────────────────────────────── SI-061
def test_converting_to_a_keyless_provider_yields_a_usable_api_key():
    """FAILS PRE-FIX: _target_transport returned api_key=None for a keyless target, so the
    writer's rewrite branch never fired and the old provider's ${VAR} survived."""
    transport = ModelAliasManager()._target_transport("ollama")
    assert transport["api_key"], "keyless target produced no api_key -> rewrite is skipped"


def test_converting_to_a_keyless_provider_does_not_strand_another_vendors_secret():
    """The actual defect: the value must not reference a DIFFERENT provider's variable."""
    transport = ModelAliasManager()._target_transport("ollama")
    key = str(transport["api_key"])
    for var in ("DEEPINFRA_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        assert var not in key, f"keyless conversion would strand {var}"


def test_keyed_targets_still_get_their_own_variable():
    """The SI-061 fix must not disturb the direction that already worked."""
    for provider, expected in (("deepinfra", "DEEPINFRA_API_KEY"),
                               ("openrouter", "OPENROUTER_API_KEY")):
        key = str(ModelAliasManager()._target_transport(provider)["api_key"])
        assert expected in key, f"{provider} lost its own key var"


def test_the_shipped_config_has_no_stranded_credential():
    """Guards the REPO, not just the function -- this is how the drift was noticed.

    Any lane whose api_key references a provider variable must sit on that provider's
    endpoint. Derived from the config, so a new provider is covered without an edit.
    """
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "llm_config.yaml")))
    providers = (cfg.get("llm", {}).get("providers", {}) or {})
    var_to_host = {}
    for block in providers.values():
        if isinstance(block, dict) and block.get("api_key", "").startswith("${"):
            var_to_host[block["api_key"].strip("${}")] = block.get("base_url", "")

    mgr = ModelAliasManager()
    offenders = []
    for lane in mgr._discover_lanes(cfg):
        if lane.get("inert"):
            continue
        node = cfg
        for seg in lane["path"].split(".")[:-1]:
            node = node.get(seg, {}) if isinstance(node, dict) else {}
        key = str(node.get("api_key", "")) if isinstance(node, dict) else ""
        if not key.startswith("${"):
            continue
        var = key.strip("${}")
        endpoint = lane.get("own_endpoint") or mgr._primary_endpoint(cfg)
        home = var_to_host.get(var, "")
        if home and endpoint and home.split("//")[-1] != endpoint.split("//")[-1]:
            offenders.append(f"{lane['path']}: {key} but endpoint is {endpoint}")

    assert not offenders, "stranded credential(s):\n  " + "\n  ".join(offenders)
