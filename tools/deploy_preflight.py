#!/usr/bin/env python3
"""Pre-deploy gate: what a target host will RUN after the pull, vs what it CAN run.

FAILURE THIS PREVENTS (SI-060)
------------------------------
A deploy is usually described as "pull the fixes", and the fixes are code. But a pull
carries `config/llm_config.yaml` too, so it also silently carries whatever provider the
last local experiment left committed.

Measured on 2026-08-16, this repo was one `git pull` away from a total production outage:

    live  (2f5a2e6) : every lane on Ollama at 127.0.0.1:11434     -- healthy
    HEAD            : every lane on https://api.deepinfra.com     -- from a LOCAL trial
    live .env       : DEEPINFRA_API_KEY  ->  ABSENT

Deploying "the fixes" would have repointed every lane at a vendor the host holds no
credential for: 401 on every LLM call, i.e. the whole server dead, from a change nobody
intended and no code review would flag -- the diff looks like config, and the secret that
makes it work lives outside the repo.

WHY NO EXISTING CHECK CAUGHT IT
-------------------------------
Everything we had validates the config against the machine it is ON. `doctor`, the lane
suite and the Tier-0 transport gate all passed locally, because locally the key exists.
Not one of them asks the question that matters at deploy time: *does the config that is
about to LAND work on the host it is landing on?*

WHAT THIS ASSERTS
-----------------
1. PROVIDER MIGRATION -- a deploy must never change a lane's provider by accident. Any
   lane whose endpoint host differs between the target's current config and the incoming
   one is reported, because that is a decision, not a side effect.
2. CREDENTIAL REACHABILITY -- every ${VAR} an incoming ACTIVE lane depends on must be
   present and non-empty on the target host.

Both are derived generically from the config: secret names are read from the config's own
${VAR} references and providers from endpoint hostnames, so a provider added tomorrow is
covered with no edit here.

USAGE
    tools/deploy_preflight.py --target-ssh 'ssh -i KEY user@host' --target-dir '~/RAICA'
    tools/deploy_preflight.py --incoming-ref HEAD --target-ssh ... --target-dir ...
    tools/deploy_preflight.py --incoming-file /tmp/c.yaml --target-config /tmp/live.yaml \
                              --target-env /tmp/live.env

Exit 0 = GO. Exit 1 = NO-GO (missing credentials). Exit 2 = GO WITH DECISION (a provider
migration is included; a human must confirm it is intended).
"""
import argparse
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from config_server_cli import ModelAliasManager  # noqa: E402

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _sh(cmd, timeout=90):
    """Run a shell command, returning (rc, stdout). Never raises on a non-zero rc."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


def _host_of(endpoint):
    """Comparable identity for an endpoint: its host (and port), or '' if unset."""
    if not endpoint:
        return ""
    parsed = urlparse(endpoint if "//" in endpoint else "//" + endpoint)
    return parsed.netloc or endpoint


def _lane_view(cfg):
    """{lane path -> {model, endpoint, secrets}} for every ACTIVE lane in `cfg`.

    Reuses the configurator's own discovery on purpose: `lanes`, `doctor`, `convert`, the
    Tier-0 gate and this check must share ONE inventory. A hand-rolled second inventory is
    what let SI-057 hide six broken lanes behind a clean bill of health.
    """
    mgr = ModelAliasManager()
    view = {}
    for lane in mgr._discover_lanes(cfg):
        if lane.get("inert"):
            continue
        endpoint = lane.get("own_endpoint") or mgr._primary_endpoint(cfg)
        view[lane["path"]] = {
            "model": lane["model"],
            "endpoint": endpoint or "",
            "secrets": set(_VAR.findall(_secrets_blob(cfg, lane, endpoint))),
        }
    return view


def _secrets_blob(cfg, lane, endpoint):
    """Config text a lane's credentials actually come from.

    Scoped to the lane's OWN block plus the ONE provider block serving the endpoint the
    lane resolves to -- matched by host, so it holds for any provider.

    An earlier version dumped every provider block for every lane. It was 'safe' in the
    sense of never missing a secret, but it reported OPENROUTER_*/ANTHROPIC_API_KEY as
    'required by 11 lanes' when no active lane used either. That is not conservatism, it
    is a false alarm on 5 of 7 rows -- and a gate whose headline is mostly wrong is a gate
    people learn to skip, which costs exactly the outage it was written to stop.
    """
    parts = []
    want = _host_of(endpoint)
    for provider in (cfg.get("llm", {}).get("providers", {}) or {}).values():
        if isinstance(provider, dict) and _host_of(provider.get("base_url", "")) == want:
            parts.append(str(provider.get("api_key", "")))

    # Only the lane's OWN api_key fields -- never a subtree dump. Dumping the enclosing
    # block swept up nested model CATALOGUES: `code_generation` lists Claude presets, so a
    # lane serving DeepSeek was reported as needing ANTHROPIC_API_KEY.
    node = cfg
    for seg in lane["path"].split(".")[:-1]:
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            node = None
            break
    if isinstance(node, dict):
        parts.append(str(node.get("api_key", "")))
        cfg_child = node.get("config")
        if isinstance(cfg_child, dict):
            parts.append(str(cfg_child.get("api_key", "")))
    return "\n".join(parts)


def _active_secrets(view):
    """Secrets actually required, i.e. referenced by a lane whose endpoint uses them."""
    needed = {}
    for path, lane in view.items():
        for secret in lane["secrets"]:
            needed.setdefault(secret, []).append(path)
    return needed


def main():
    ap = argparse.ArgumentParser(description="Pre-deploy config/credential gate.")
    ap.add_argument("--incoming-ref", default="HEAD",
                    help="git ref whose config the target will receive (default HEAD)")
    ap.add_argument("--incoming-file", help="use this config file instead of a git ref")
    ap.add_argument("--target-ssh", help="ssh command prefix for the target host")
    ap.add_argument("--target-dir", default="~/RAICA", help="repo dir on the target")
    ap.add_argument("--target-config", help="target's current config (skips ssh)")
    ap.add_argument("--target-env", help="target's .env (skips ssh)")
    ap.add_argument("--config-path", default="config/llm_config.yaml")
    args = ap.parse_args()

    # ---- incoming config: what the target WILL have after the pull
    if args.incoming_file:
        incoming_raw = open(args.incoming_file).read()
        incoming_label = args.incoming_file
    else:
        rc, incoming_raw = _sh(f"git show {args.incoming_ref}:{args.config_path}")
        if rc != 0 or not incoming_raw.strip():
            print(f"NO-GO: cannot read {args.config_path} at ref {args.incoming_ref}")
            return 1
        incoming_label = f"{args.incoming_ref}:{args.config_path}"

    # ---- target's current config + env
    if args.target_config:
        target_raw = open(args.target_config).read()
        env_raw = open(args.target_env).read() if args.target_env else ""
        target_label = args.target_config
    else:
        if not args.target_ssh:
            print("NO-GO: need --target-ssh or --target-config")
            return 1
        rc, target_raw = _sh(f"{args.target_ssh} 'cat {args.target_dir}/{args.config_path}'")
        if rc != 0 or not target_raw.strip():
            print(f"NO-GO: cannot read the target's {args.config_path} (rc={rc})")
            return 1
        # Names only -- values are never transferred or printed.
        _, env_raw = _sh(args.target_ssh +
                         f" 'grep -oE \"^[A-Za-z_][A-Za-z0-9_]*=.\" {args.target_dir}/.env "
                         "| sed \"s/=.$//\"'")
        target_label = "live"

    incoming = _lane_view(yaml.safe_load(incoming_raw))
    current = _lane_view(yaml.safe_load(target_raw))
    present = {line.strip() for line in env_raw.splitlines() if line.strip()}

    print("=" * 78)
    print("DEPLOY PREFLIGHT")
    print(f"  incoming : {incoming_label}")
    print(f"  target   : {target_label}")
    print("=" * 78)

    # ---- 1. provider migration
    migrations = []
    for path, lane in sorted(incoming.items()):
        was = current.get(path)
        if not was:
            continue
        if _host_of(was["endpoint"]) != _host_of(lane["endpoint"]):
            migrations.append((path, was, lane))

    if migrations:
        print(f"\n⚠️  PROVIDER MIGRATION — {len(migrations)} lane(s) change endpoint:\n")
        print(f"  {'LANE':<44}{'NOW':<26}{'AFTER DEPLOY'}")
        for path, was, now in migrations:
            print(f"  {path:<44}{_host_of(was['endpoint']):<26}{_host_of(now['endpoint'])}")
    else:
        print("\n✓ No provider migration — every lane keeps its current endpoint.")

    # ---- 2. credential reachability
    needed = _active_secrets(incoming)
    missing = {s: p for s, p in needed.items() if s not in present}

    print(f"\nCREDENTIALS required by incoming active lanes: "
          f"{', '.join(sorted(needed)) or '(none)'}")
    if not present:
        print("  ⚠️  could not read the target's env — credential check INCONCLUSIVE")
    for secret in sorted(needed):
        mark = "✓" if secret in present else "✗ ABSENT ON TARGET"
        print(f"  {mark} {secret}  ({len(needed[secret])} lane(s))")

    print("\n" + "=" * 78)
    if missing:
        print("❌ NO-GO — deploying this would break lanes the target cannot authenticate:")
        for secret, paths in sorted(missing.items()):
            print(f"     {secret} missing → {len(paths)} lane(s), e.g. {paths[0]}")
        print("\n   Fix: set the secret on the target, or convert the config back to the "
              "provider\n   the target already runs:  ./config_server_cli.py convert --to "
              "<provider> --yes")
        return 1
    if migrations:
        print("⚠️  GO WITH DECISION — credentials are present, but this deploy CHANGES")
        print("   provider for the lanes listed above. Confirm that is intended.")
        return 2
    print("✅ GO — no provider change, all required credentials present on the target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
