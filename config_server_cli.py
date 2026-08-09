#!/usr/bin/env python3
"""
Server Configuration CLI Tool
==============================

Easy-to-use CLI for managing LLM model aliases and configurations.

Usage:
    ./config_server_cli.py ls                                    # List all model aliases
    ./config_server_cli.py add --alias NAME --provider TYPE --model MODEL [options]
    ./config_server_cli.py update --alias NAME [options]
    ./config_server_cli.py delete --alias NAME
    ./config_server_cli.py set --alias NAME --as primary|tool_calling|arbitrator
    ./config_server_cli.py show --alias NAME                     # Show alias details
    ./config_server_cli.py status                                # Show current active models

Examples:
    # Add a new model alias
    ./config_server_cli.py add --alias qwen_local --provider ollama --model qwen3:8b

    # Add Gemini model
    ./config_server_cli.py add --alias gemini_flash --provider gemini --model gemini-flash-latest

    # Add OpenRouter model with custom settings
    ./config_server_cli.py add --alias openrouter_deepseek --provider openrouter \\
        --model deepseek/deepseek-r1 --timeout 600 --temperature 0.7

    # Set an alias as primary LLM
    ./config_server_cli.py set --alias gemini_flash --as primary

    # List all aliases
    ./config_server_cli.py ls

    # Show details of an alias
    ./config_server_cli.py show --alias gemini_flash

    # Delete an alias
    ./config_server_cli.py delete --alias openrouter_deepseek

Author: RAICA Development Team
Version: 1.0.1
"""

import argparse
import json
import os
import re
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Configuration
CONFIG_DIR = Path(__file__).parent / "config"
ALIASES_FILE = CONFIG_DIR / "model_aliases.json"
LLM_CONFIG_FILE = CONFIG_DIR / "llm_config.yaml"

# Provider defaults
PROVIDER_DEFAULTS = {
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "timeout": 600,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "timeout": 120,
        "temperature": 0.1,
        "max_tokens": 2048,
        "stream": True
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "timeout": 600,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
        "headers": {
            "HTTP-Referer": "${OPENROUTER_SITE_URL}",
            "X-Title": "${OPENROUTER_SITE_NAME}"
        }
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "timeout": 300,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True
    },
    "deepinfra": {
        # OpenAI-compatible; driven by llm_providers/openai.py (no module of its own).
        "base_url": "https://api.deepinfra.com/v1/openai",
        "timeout": 600,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True
    },
    "gemini": {
        "timeout": 120,
        "temperature": 0.7,
        "max_tokens": 8192,
        "stream": True
    }
}

# API key environment variable mappings
API_KEY_ENV_VARS = {
    "ollama": None,  # Ollama doesn't need API key
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY"
}


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class ModelAliasManager:
    """Manages model aliases and configurations"""

    def __init__(self):
        self.aliases_file = ALIASES_FILE
        self.llm_config_file = LLM_CONFIG_FILE
        self.aliases = self._load_aliases()

    def _load_aliases(self) -> Dict[str, Any]:
        """Load model aliases from JSON file"""
        if not self.aliases_file.exists():
            return {}

        try:
            with open(self.aliases_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"{Colors.FAIL}Error loading aliases file: {e}{Colors.ENDC}")
            return {}

    def _save_aliases(self):
        """Save model aliases to JSON file"""
        self.aliases_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.aliases_file, 'w') as f:
            json.dump(self.aliases, f, indent=2)
        print(f"{Colors.OKGREEN}✓ Aliases saved to {self.aliases_file}{Colors.ENDC}")

    def _load_llm_config(self) -> Dict[str, Any]:
        """Load LLM configuration YAML"""
        if not self.llm_config_file.exists():
            print(f"{Colors.FAIL}Error: LLM config file not found: {self.llm_config_file}{Colors.ENDC}")
            sys.exit(1)

        with open(self.llm_config_file, 'r') as f:
            return yaml.safe_load(f)

    def _save_llm_config(self, config: Dict[str, Any]):
        """Save LLM configuration YAML"""
        with open(self.llm_config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        print(f"{Colors.OKGREEN}✓ LLM config updated: {self.llm_config_file}{Colors.ENDC}")

    def list_aliases(self):
        """List all model aliases"""
        if not self.aliases:
            print(f"{Colors.WARNING}No model aliases configured.{Colors.ENDC}")
            print(f"Use '{Colors.BOLD}./config_server_cli.py add{Colors.ENDC}' to create your first alias.")
            return

        # Load current config to show active models
        llm_config = self._load_llm_config()
        active_primary = llm_config.get('llm', {}).get('primary', {})
        active_tool = llm_config.get('llm', {}).get('tool_calling', {})
        active_arb = llm_config.get('arbitrator', {})
        active_vision = llm_config.get('vision', {})

        print(f"\n{Colors.HEADER}{Colors.BOLD}Model Aliases{Colors.ENDC}")
        print("=" * 80)

        for alias, config in sorted(self.aliases.items()):
            # Check if this alias is active
            active_roles = []
            if (active_primary.get('type') == config.get('provider') and
                active_primary.get('config', {}).get('model') == config.get('model')):
                active_roles.append(f"{Colors.OKGREEN}PRIMARY{Colors.ENDC}")

            if (active_tool.get('type') == config.get('provider') and
                active_tool.get('config', {}).get('model') == config.get('model')):
                active_roles.append(f"{Colors.OKCYAN}TOOL_CALLING{Colors.ENDC}")

            if (active_arb.get('type') == config.get('provider') and
                active_arb.get('config', {}).get('model') == config.get('model')):
                active_roles.append(f"{Colors.OKBLUE}ARBITRATOR{Colors.ENDC}")

            if (active_vision.get('type') == config.get('provider') and
                active_vision.get('config', {}).get('model') == config.get('model')):
                active_roles.append(f"{Colors.WARNING}VISION{Colors.ENDC}")

            status = f" [{', '.join(active_roles)}]" if active_roles else ""

            print(f"\n{Colors.BOLD}{alias}{Colors.ENDC}{status}")
            print(f"  Provider:    {config.get('provider')}")
            print(f"  Model:       {config.get('model')}")
            print(f"  Timeout:     {config.get('timeout')}s")
            print(f"  Temperature: {config.get('temperature')}")
            print(f"  Max Tokens:  {config.get('max_tokens')}")
            if config.get('context_window_size'):
                print(f"  Context:     {config.get('context_window_size')}")
            if config.get('fallback_model'):
                print(f"  Fallback:    {config.get('fallback_model')}")
            if config.get('think') is not None:
                print(f"  Think:       {config.get('think')}")
            if config.get('stream') is not None:
                print(f"  Stream:      {config.get('stream')}")
            if config.get('base_url'):
                print(f"  Base URL:    {config.get('base_url')}")
            if config.get('api_key'):
                print(f"  API Key:     {config.get('api_key')}")
            if config.get('headers'):
                print(f"  Headers:     {config.get('headers')}")
            if config.get('description'):
                print(f"  Description: {config.get('description')}")
            if config.get('created_at'):
                print(f"  Created:     {config.get('created_at')}")
            if config.get('updated_at'):
                print(f"  Updated:     {config.get('updated_at')}")

        print()

    def add_alias(self, alias: str, provider: str, model: str,
                  timeout: Optional[int] = None,
                  temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  context_window: Optional[int] = None,
                  think: Optional[bool] = None,
                  no_think: Optional[bool] = None,
                  description: Optional[str] = None,
                  fallback_model: Optional[str] = None,
                  base_url: Optional[str] = None,
                  api_key_env: Optional[str] = None):
        """Add a new model alias.

        `base_url` overrides the provider default. Without it the tool cannot
        express an OpenAI-compatible endpoint that is not OpenAI's own — e.g.
        Google's https://generativelanguage.googleapis.com/v1beta/openai, which
        is the only way to get Gemini models onto the tool_calling lane (the
        native gemini provider has no function-calling support).
        """

        # Validate provider
        provider = provider.lower()
        if provider not in PROVIDER_DEFAULTS:
            print(f"{Colors.FAIL}Error: Unknown provider '{provider}'{Colors.ENDC}")
            print(f"Supported providers: {', '.join(PROVIDER_DEFAULTS.keys())}")
            sys.exit(1)

        # Check if alias already exists
        if alias in self.aliases:
            print(f"{Colors.FAIL}Error: Alias '{alias}' already exists.{Colors.ENDC}")
            print(f"Use '{Colors.BOLD}./config_server_cli.py update --alias {alias}{Colors.ENDC}' to modify it.")
            sys.exit(1)

        # Get defaults for provider
        defaults = PROVIDER_DEFAULTS[provider].copy()

        # Build configuration
        config = {
            "provider": provider,
            "model": model,
            "base_url": base_url if base_url is not None else defaults.get("base_url"),
            "timeout": timeout if timeout is not None else defaults.get("timeout"),
            "temperature": temperature if temperature is not None else defaults.get("temperature"),
            "max_tokens": max_tokens if max_tokens is not None else defaults.get("max_tokens"),
            "stream": defaults.get("stream", True),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        if context_window:
            config["context_window_size"] = context_window

        # Handle think parameter (for Ollama reasoning models)
        if think:
            config["think"] = True
        elif no_think:
            config["think"] = False

        if description:
            config["description"] = description

        if fallback_model:
            config["fallback_model"] = fallback_model

        # Add API key reference if needed.
        # The provider name selects the PROTOCOL, not necessarily the credentials:
        # an `openai` alias aimed at Google's OpenAI-compatible endpoint speaks the
        # OpenAI protocol but must authenticate with GEMINI_API_KEY. Defaulting to
        # the provider's env var silently produced ${OPENAI_API_KEY} against Google,
        # which is a 401 that no static check would explain. So: honour an explicit
        # --api-key-env, otherwise infer from the endpoint host, and only then fall
        # back to the provider default.
        api_key_var = api_key_env or self._api_key_env_for_endpoint(
            config.get("base_url")) or API_KEY_ENV_VARS.get(provider)
        if api_key_var:
            config["api_key"] = f"${{{api_key_var}}}"

        # Add provider-specific settings
        if provider == "openrouter":
            config["headers"] = defaults.get("headers", {})

        # Save alias
        self.aliases[alias] = config
        self._save_aliases()

        print(f"\n{Colors.OKGREEN}✓ Created model alias '{alias}'{Colors.ENDC}")
        print(f"\nTo use this alias:")
        print(f"  {Colors.BOLD}./config_server_cli.py set --alias {alias} --as primary{Colors.ENDC}")

    def update_alias(self, alias: str, **kwargs):
        """Update an existing model alias"""
        if alias not in self.aliases:
            print(f"{Colors.FAIL}Error: Alias '{alias}' not found.{Colors.ENDC}")
            print(f"Use '{Colors.BOLD}./config_server_cli.py ls{Colors.ENDC}' to see available aliases.")
            sys.exit(1)

        # Update fields
        config = self.aliases[alias]
        updated = False

        for key, value in kwargs.items():
            if value is not None and key in ['model', 'timeout', 'temperature', 'max_tokens',
                                              'context_window', 'description', 'fallback_model',
                                              'base_url']:
                if key == 'context_window':
                    config['context_window_size'] = value
                else:
                    config[key] = value
                updated = True

        # Handle think parameter separately
        if 'think' in kwargs and kwargs['think']:
            config['think'] = True
            updated = True
        elif 'no_think' in kwargs and kwargs['no_think']:
            config['think'] = False
            updated = True

        if updated:
            config['updated_at'] = datetime.now().isoformat()
            self.aliases[alias] = config
            self._save_aliases()
            print(f"{Colors.OKGREEN}✓ Updated alias '{alias}'{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}No changes made to alias '{alias}'{Colors.ENDC}")

    def delete_alias(self, alias: str, force: bool = False):
        """Delete a model alias"""
        if alias not in self.aliases:
            print(f"{Colors.FAIL}Error: Alias '{alias}' not found.{Colors.ENDC}")
            sys.exit(1)

        # Check if alias is currently in use
        llm_config = self._load_llm_config()
        config = self.aliases[alias]

        in_use = []
        if (llm_config.get('llm', {}).get('primary', {}).get('type') == config.get('provider') and
            llm_config.get('llm', {}).get('primary', {}).get('config', {}).get('model') == config.get('model')):
            in_use.append('primary')

        if (llm_config.get('llm', {}).get('tool_calling', {}).get('type') == config.get('provider') and
            llm_config.get('llm', {}).get('tool_calling', {}).get('config', {}).get('model') == config.get('model')):
            in_use.append('tool_calling')

        if (llm_config.get('arbitrator', {}).get('type') == config.get('provider') and
            llm_config.get('arbitrator', {}).get('config', {}).get('model') == config.get('model')):
            in_use.append('arbitrator')

        if (llm_config.get('vision', {}).get('type') == config.get('provider') and
            llm_config.get('vision', {}).get('config', {}).get('model') == config.get('model')):
            in_use.append('vision')

        if in_use and not force:
            print(f"{Colors.WARNING}Warning: Alias '{alias}' is currently active for: {', '.join(in_use)}{Colors.ENDC}")
            print(f"Use --force to delete anyway.")
            sys.exit(1)

        del self.aliases[alias]
        self._save_aliases()
        print(f"{Colors.OKGREEN}✓ Deleted alias '{alias}'{Colors.ENDC}")

    def show_alias(self, alias: str):
        """Show detailed information about an alias"""
        if alias not in self.aliases:
            print(f"{Colors.FAIL}Error: Alias '{alias}' not found.{Colors.ENDC}")
            sys.exit(1)

        config = self.aliases[alias]

        print(f"\n{Colors.HEADER}{Colors.BOLD}Alias: {alias}{Colors.ENDC}")
        print("=" * 80)

        for key, value in sorted(config.items()):
            print(f"{key:20s}: {value}")

        print()

    def set_alias(self, alias: str, role: str, with_dependents: bool = False,
                  force: bool = False):
        """Set an alias as primary, tool_calling, or arbitrator.

        Switching PRIMARY also silently re-points every lane that has no
        base_url of its own (deep_research, the convergence classifiers,
        code_generation…). Their model names stay put while the endpoint under
        them changes, so they start returning
            404 models/<name> is not found
        at runtime with nothing at config time to warn you. This refuses to make
        that change blindly: use --with-dependents to move them too, or --force
        to accept the breakage knowingly.
        """
        if alias not in self.aliases:
            print(f"{Colors.FAIL}Error: Alias '{alias}' not found.{Colors.ENDC}")
            sys.exit(1)

        role = role.lower()
        if role not in ['primary', 'tool_calling', 'arbitrator', 'vision']:
            print(f"{Colors.FAIL}Error: Invalid role '{role}'{Colors.ENDC}")
            print("Valid roles: primary, tool_calling, arbitrator, vision")
            sys.exit(1)

        # Load current config
        llm_config = self._load_llm_config()
        alias_config = self.aliases[alias]

        # Build new configuration section
        new_config = {
            "type": alias_config["provider"],
            "config": {
                "model": alias_config["model"],
                "timeout": alias_config["timeout"],
                "temperature": alias_config["temperature"],
                "max_tokens": alias_config["max_tokens"],
                "stream": alias_config.get("stream", True)
            }
        }

        # Add context_window_size if present
        if "context_window_size" in alias_config:
            new_config["config"]["context_window_size"] = alias_config["context_window_size"]

        # Add provider-specific settings
        if alias_config["provider"] in ["openai", "openrouter", "qwen", "deepinfra"]:
            new_config["config"]["base_url"] = alias_config["base_url"]
            if "api_key" in alias_config:
                new_config["config"]["api_key"] = alias_config["api_key"]

        if alias_config["provider"] == "gemini":
            if "api_key" in alias_config:
                new_config["config"]["api_key"] = alias_config["api_key"]

        if alias_config["provider"] == "openrouter" and "headers" in alias_config:
            new_config["config"]["headers"] = alias_config["headers"]

        # Add think parameter if present (for Ollama reasoning models)
        if "think" in alias_config:
            new_config["config"]["think"] = alias_config["think"]

        # The tool_calling lane is the one role with a hard provider requirement:
        # the provider must actually implement function calling. Assigning one that
        # does not leaves a config that looks correct and fails only when a tool is
        # first needed — which, for a citation-required bot, surfaces as replies
        # being discarded for "missing sources" rather than as a tool error.
        if role == "tool_calling" and not force:
            supports_tools = self._provider_supports_tools(alias_config["provider"])
            if supports_tools is False:
                print(f"\n{Colors.FAIL}{Colors.BOLD}Refusing: provider "
                      f"'{alias_config['provider']}' cannot do tool calling.{Colors.ENDC}")
                print(f"llm_providers/{alias_config['provider']}.py declares "
                      f"supports_function_calling: False, so this lane would fail on the")
                print(f"first tool call regardless of which model you pick.\n")
                print(f"{Colors.BOLD}Workaround{Colors.ENDC} — reach the same models through an "
                      f"OpenAI-compatible endpoint,")
                print(f"which RAICA's openai provider drives with full tool support:")
                print(f"  ./config_server_cli.py add --alias {alias}_openai --provider openai \\")
                print(f"      --model {alias_config['model']} \\")
                print(f"      --base-url https://generativelanguage.googleapis.com/v1beta/openai")
                print(f"  ./config_server_cli.py set --alias {alias}_openai --as tool_calling\n")
                print(f"Or re-run with {Colors.BOLD}--force{Colors.ENDC} to assign it anyway.\n")
                sys.exit(1)

        # Switching primary drags every endpoint-less lane along with it — resolve
        # that BEFORE writing anything, so a refusal leaves the config untouched.
        dependent_updates = []
        if role == "primary":
            # Resolve through the provider block, not just the lane — Ollama aliases
            # carry no base_url of their own (see _resolve_endpoint).
            new_endpoint = self._resolve_endpoint(llm_config,
                                                  alias_config["provider"],
                                                  new_config["config"])
            broken = [
                lane for lane in self._dependent_lanes(llm_config)
                if self._lane_mismatch(lane['model'], new_endpoint)
            ]

            if broken and not (with_dependents or force):
                print(f"\n{Colors.FAIL}{Colors.BOLD}Refusing: {len(broken)} lane(s) would break."
                      f"{Colors.ENDC}")
                print(f"These lanes have no endpoint of their own, so they follow primary to")
                print(f"{Colors.BOLD}{new_endpoint or '(none)'}{Colors.ENDC} — where their model "
                      f"names are not valid:\n")
                for lane in broken:
                    print(f"  {Colors.FAIL}✗{Colors.ENDC} {lane['path']:<44} {lane['model']}")
                print(f"\nChoose one:")
                print(f"  {Colors.BOLD}--with-dependents{Colors.ENDC}  also set them to "
                      f"'{alias_config['model']}' (then tune individually)")
                print(f"  {Colors.BOLD}--force{Colors.ENDC}            switch anyway and leave "
                      f"them broken")
                print(f"\nRun '{Colors.BOLD}lanes{Colors.ENDC}' to see every lane, "
                      f"'{Colors.BOLD}doctor{Colors.ENDC}' to re-check afterwards.\n")
                sys.exit(1)

            if broken and with_dependents:
                for lane in broken:
                    dependent_updates.append((lane['path'], lane['model'],
                                              alias_config['model']))
                    self._set_lane_model(llm_config, lane['path'], alias_config['model'])
            elif broken and force:
                print(f"\n{Colors.WARNING}⚠ --force: leaving {len(broken)} dependent lane(s) "
                      f"pointing at models this endpoint does not serve.{Colors.ENDC}")
                for lane in broken:
                    print(f"    {lane['path']:<44} {lane['model']}")

        # Update appropriate section
        if role == "arbitrator":
            llm_config["arbitrator"] = new_config
        elif role == "vision":
            llm_config["vision"] = new_config
        else:
            if "llm" not in llm_config:
                llm_config["llm"] = {}
            llm_config["llm"][role] = new_config

        # Save updated config
        self._save_llm_config(llm_config)

        if dependent_updates:
            print(f"\n{Colors.OKGREEN}✓ Moved {len(dependent_updates)} dependent lane(s) "
                  f"with primary:{Colors.ENDC}")
            for path, old_model, new_model in dependent_updates:
                print(f"    {path:<44} {old_model}  →  {new_model}")

        print(f"{Colors.OKGREEN}✓ Set '{alias}' as {role.upper()} LLM{Colors.ENDC}")
        print(f"\nCurrent {role} configuration:")
        print(f"  Provider: {alias_config['provider']}")
        print(f"  Model:    {alias_config['model']}")

    def show_status(self):
        """Show current active models"""
        llm_config = self._load_llm_config()

        print(f"\n{Colors.HEADER}{Colors.BOLD}Current Active Models{Colors.ENDC}")
        print("=" * 80)

        # Primary
        primary = llm_config.get('llm', {}).get('primary', {})
        print(f"\n{Colors.OKGREEN}PRIMARY:{Colors.ENDC}")
        print(f"  Provider: {primary.get('type', 'Not set')}")
        print(f"  Model:    {primary.get('config', {}).get('model', 'Not set')}")

        # Tool Calling
        tool = llm_config.get('llm', {}).get('tool_calling', {})
        print(f"\n{Colors.OKCYAN}TOOL_CALLING:{Colors.ENDC}")
        print(f"  Provider: {tool.get('type', 'Not set')}")
        print(f"  Model:    {tool.get('config', {}).get('model', 'Not set')}")

        # Arbitrator
        arb = llm_config.get('arbitrator', {})
        print(f"\n{Colors.OKBLUE}ARBITRATOR:{Colors.ENDC}")
        print(f"  Provider: {arb.get('type', 'Not set')}")
        print(f"  Model:    {arb.get('config', {}).get('model', 'Not set')}")

        # Vision
        vision = llm_config.get('vision', {})
        print(f"\n{Colors.WARNING}VISION:{Colors.ENDC}")
        print(f"  Provider: {vision.get('type', 'Not set')}")
        print(f"  Model:    {vision.get('config', {}).get('model', 'Not set')}")

        print()

    # ------------------------------------------------------------------
    # Lane inventory & health check
    #
    # llm_config.yaml drives MANY independent LLM lanes, not just the four
    # `status` reports. Crucially, a lane with no `base_url` of its own
    # INHERITS llm.primary's endpoint — so its model name must belong to
    # whatever provider primary currently points at. Switching primary
    # without updating those lanes yields, at runtime and only at runtime:
    #     404 models/<ollama-name> is not found for API version v1main
    # which silently disables deep research while everything else looks fine.
    #
    # The lane list is WALKED FROM THE YAML rather than hardcoded, so adding a
    # lane to the config surfaces it here automatically instead of quietly
    # creating a blind spot.
    # ------------------------------------------------------------------

    # Path segments that mark a model entry as a MENU rather than an active lane:
    # presets and fallback chains are inert until something selects them.
    _INERT_SEGMENTS = {'model_presets', 'fallback', 'providers'}

    # Advisory only — naming conventions per endpoint host. `doctor --probe`
    # is the authoritative check; this table just gives instant feedback.
    _ENDPOINT_MODEL_PREFIXES = {
        'generativelanguage.googleapis.com': ('gemini-',),
        'api.openai.com': ('gpt-', 'o1-', 'o3-', 'o4-'),
        'dashscope.aliyuncs.com': ('qwen',),
    }

    def _discover_lanes(self, llm_config):
        """Walk the config for every model-bearing lane.

        Returns a list of dicts: path, model, container, own_endpoint, inert.
        A lane is 'own_endpoint' when its own block (or its nested `config`)
        supplies base_url; otherwise it resolves through llm.primary.
        """
        lanes = []

        def container_endpoint(container):
            if not isinstance(container, dict):
                return None
            if 'base_url' in container:
                return container.get('base_url')
            cfg = container.get('config')
            if isinstance(cfg, dict) and 'base_url' in cfg:
                return cfg.get('base_url')
            return None

        def walk(node, path=(), parents=()):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, str) and (
                        key == 'model' or key.endswith('_model') or key == 'selected_model'
                    ):
                        # Nearest enclosing block that could carry an endpoint.
                        endpoint = container_endpoint(node)
                        if endpoint is None and parents:
                            endpoint = container_endpoint(parents[-1])
                        lanes.append({
                            'path': '.'.join(path + (key,)),
                            'model': value,
                            'own_endpoint': endpoint,
                            'inert': bool(set(path) & self._INERT_SEGMENTS),
                        })
                    else:
                        walk(value, path + (key,), parents + (node,))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, path + (f'[{index}]',), parents + (node,))

        walk(llm_config)
        return lanes

    def _resolve_endpoint(self, llm_config, provider_type, lane_config=None):
        """Effective endpoint for a lane, mirroring how the loader merges config.

        utils/config_loader.py:113 starts from llm.providers.<type> and lets the
        lane's own `config` override it — so a lane with no base_url of its own
        still HAS an endpoint, inherited from its provider block. Reading only
        the lane's base_url reports '' for every Ollama lane (the CLI never
        writes one for Ollama), which made an earlier version of the dependent
        check silently pass on exactly the switch it exists to catch.
        """
        if lane_config and lane_config.get('base_url'):
            return lane_config['base_url']
        provider = (llm_config.get('llm', {})
                    .get('providers', {})
                    .get(provider_type, {}))
        return provider.get('base_url', '')

    def _primary_endpoint(self, llm_config):
        primary = llm_config.get('llm', {}).get('primary', {})
        return self._resolve_endpoint(llm_config,
                                      primary.get('type', ''),
                                      primary.get('config', {}))

    def _lane_mismatch(self, model, endpoint):
        """Return a reason string if `model` does not belong to `endpoint`, else None.

        Advisory naming check shared by `doctor` and `set` so the two can never
        disagree about what counts as a broken lane. `doctor --probe` is the
        authoritative test; this is the instant one.
        """
        endpoint = endpoint or ''
        for host, prefixes in self._ENDPOINT_MODEL_PREFIXES.items():
            if host in endpoint:
                if not model.startswith(prefixes):
                    return f"model does not look like a {prefixes[0]}* model for this endpoint"
                return None

        # Ollama addresses models as name:tag; a bare cloud-style name here is
        # usually a lane whose endpoint moved but whose model name did not.
        if '11434' in endpoint and ':' not in model:
            return "Ollama endpoint but model has no :tag"
        return None

    # Endpoint host -> the env var whose credentials that host accepts. Consulted
    # when a lane speaks one provider's protocol against another vendor's endpoint.
    _ENDPOINT_KEY_ENV = {
        'generativelanguage.googleapis.com': 'GEMINI_API_KEY',
        'api.openai.com': 'OPENAI_API_KEY',
        'openrouter.ai': 'OPENROUTER_API_KEY',
        'dashscope.aliyuncs.com': 'DASHSCOPE_API_KEY',
        'api.deepinfra.com': 'DEEPINFRA_API_KEY',
    }

    def _api_key_env_for_endpoint(self, base_url):
        """Env var name whose key the given endpoint accepts, or None if unknown."""
        for host, env_var in self._ENDPOINT_KEY_ENV.items():
            if host in (base_url or ''):
                return env_var
        return None

    def _provider_supports_tools(self, provider_type):
        """Does llm_providers/<provider_type>.py declare function-calling support?

        Returns True / False, or None when it cannot be determined.

        Read from the PROVIDER'S OWN declaration so this can never disagree with
        the implementation: each provider reports `supports_function_calling` in
        its get_provider_info() dict (gemini.py:213 = False, openai/ollama/qwen =
        True). We parse rather than import because constructing a provider needs
        real credentials and has side effects (GeminiProvider.__init__ calls
        genai.configure). Note the base class defaults the method to True, so the
        dict literal — not the method — is the authoritative signal.

        Unknown returns None and the caller allows the change: this guard exists
        to catch a KNOWN incompatibility, not to block on ignorance.
        """
        import ast

        module = Path(__file__).parent / 'llm_providers' / f'{provider_type}.py'
        if not module.exists():
            return None

        try:
            tree = ast.parse(module.read_text())
        except (SyntaxError, OSError):
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant)
                        and key.value == 'supports_function_calling'
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, bool)):
                    return value.value
        return None

    def _dependent_lanes(self, llm_config):
        """Active lanes with no endpoint of their own — they follow llm.primary.

        These are the lanes that break silently when primary switches provider,
        because their model name stays valid-looking while the endpoint beneath
        them changes. Returned so `set` can offer to move them together.
        """
        return [lane for lane in self._discover_lanes(llm_config)
                if not lane['inert'] and not lane['own_endpoint']
                and not lane['path'].startswith('llm.primary')]

    def _set_lane_model(self, llm_config, dotted_path, model):
        """Write `model` into a lane addressed by its dotted discovery path."""
        node = llm_config
        parts = dotted_path.split('.')
        for part in parts[:-1]:
            if part.startswith('[') and part.endswith(']'):
                node = node[int(part[1:-1])]
            else:
                node = node[part]
        node[parts[-1]] = model

    def show_lanes(self):
        """Print every model-bearing lane and how its endpoint resolves."""
        llm_config = self._load_llm_config()
        lanes = self._discover_lanes(llm_config)
        primary_endpoint = self._primary_endpoint(llm_config)

        print(f"\n{Colors.HEADER}{Colors.BOLD}LLM Lane Inventory{Colors.ENDC}")
        print("=" * 100)
        print(f"{Colors.BOLD}llm.primary endpoint:{Colors.ENDC} {primary_endpoint or 'not set'}")
        print(f"Lanes WITHOUT their own base_url inherit that endpoint.\n")

        active = [lane for lane in lanes if not lane['inert']]
        inert = [lane for lane in lanes if lane['inert']]

        print(f"{Colors.BOLD}{'LANE':<48} {'MODEL':<26} ENDPOINT{Colors.ENDC}")
        print("-" * 100)
        for lane in active:
            if lane['own_endpoint']:
                where = f"own: {lane['own_endpoint']}"
                color = Colors.OKGREEN
            else:
                where = f"{Colors.WARNING}INHERITS primary{Colors.ENDC}"
                color = Colors.OKCYAN
            print(f"{color}{lane['path']:<48}{Colors.ENDC} {lane['model']:<26} {where}")

        if inert:
            print(f"\n{Colors.BOLD}Inert (menus/fallback chains — only used if selected):{Colors.ENDC}")
            for lane in inert:
                print(f"  {lane['path']:<58} {lane['model']}")

        print(f"\n{len(active)} active lane(s), {len(inert)} inert entry(ies).")
        print(f"Run '{Colors.BOLD}doctor{Colors.ENDC}' to check each model against its endpoint.\n")

    def doctor(self, probe=False, check_aliases=False):
        """Flag lanes whose model name does not match the endpoint it resolves to.

        Static checks are advisory (naming conventions). `--probe` asks each
        distinct endpoint whether the model actually exists, which is the
        authoritative answer and catches everything the heuristics miss.

        Returns the number of problems found so callers can use the exit code.
        """
        llm_config = self._load_llm_config()
        lanes = self._discover_lanes(llm_config)
        primary_endpoint = self._primary_endpoint(llm_config)

        print(f"\n{Colors.HEADER}{Colors.BOLD}LLM Config Doctor{Colors.ENDC}")
        print("=" * 100)

        problems = []
        for lane in [lane for lane in lanes if not lane['inert']]:
            endpoint = lane['own_endpoint'] or primary_endpoint or ''
            reason = self._lane_mismatch(lane['model'], endpoint)
            if reason:
                problems.append((lane['path'], lane['model'], endpoint, reason))

        # Credentials must match the ENDPOINT, not the provider protocol. An
        # openai-type lane aimed at Google needs GEMINI_API_KEY; taking the
        # provider default there yields ${OPENAI_API_KEY} and a 401 that looks
        # nothing like a config error. Checked separately from the model/endpoint
        # test because a lane can pass that one and still fail to authenticate.
        problems.extend(self._credential_mismatches(llm_config))

        if problems:
            print(f"{Colors.FAIL}{Colors.BOLD}{len(problems)} problem(s) found:{Colors.ENDC}\n")
            for path, model, endpoint, why in problems:
                print(f"  {Colors.FAIL}✗{Colors.ENDC} {Colors.BOLD}{path}{Colors.ENDC}")
                print(f"      model:    {model}")
                print(f"      endpoint: {endpoint or '(unresolved)'}")
                print(f"      {Colors.WARNING}{why}{Colors.ENDC}\n")
        else:
            print(f"{Colors.OKGREEN}✓ Every active lane's model matches its endpoint.{Colors.ENDC}\n")

        if probe:
            problems.extend(self._probe_endpoints(lanes, primary_endpoint))

        if check_aliases:
            problems.extend(self._probe_aliases())

        return len(problems)

    def _credential_mismatches(self, llm_config):
        """Lanes whose api_key env var does not belong to their endpoint's vendor."""
        problems = []
        for role, block in (('llm.primary', llm_config.get('llm', {}).get('primary')),
                            ('llm.tool_calling', llm_config.get('llm', {}).get('tool_calling')),
                            ('arbitrator', llm_config.get('arbitrator')),
                            ('vision', llm_config.get('vision'))):
            if not isinstance(block, dict):
                continue
            config = block.get('config', {})
            endpoint = self._resolve_endpoint(llm_config, block.get('type', ''), config)
            api_key = config.get('api_key', '')
            expected = self._api_key_env_for_endpoint(endpoint)
            if not expected or not api_key:
                continue
            if expected not in api_key:
                problems.append((
                    f'{role}.config.api_key', api_key, endpoint,
                    f'endpoint expects ${{{expected}}} — these credentials will not authenticate'
                ))
        return problems

    # Availability can ONLY be established by INVOKING the model. A registry listing
    # is evidence in NEITHER direction, and this probe used to read one:
    #   * a cloud model never pulled locally is ABSENT from /api/tags yet answers
    #     fine (gemma4:31b-cloud, kimi-k2.7-code:cloud);
    #   * a RETIRED model stays LISTED and returns HTTP 410 on use
    #     (qwen3-vl:235b-cloud).
    # Measured 2026-08-05: the listing check PASSED the one genuinely dead model and
    # FAILED two working ones — wrong in both directions, and blind to the exact
    # failure it exists to catch. It also put two false "unserved" claims into
    # llm_config.yaml that were then cited as a root cause (SI-005).
    # Cost of the real test is one 1-token generation per model, which is why the
    # whole thing stays behind an explicit --probe.
    _PROBE_OK = 'ok'
    _PROBE_DEAD = 'dead'
    _PROBE_UNREACHABLE = 'unreachable'

    # ==================================================================
    # PROVIDER CONVERSION (`convert`)
    # ==================================================================
    # A provider change is a TRANSPORT change, NOT a model change.
    # `deepseek-v4-pro:cloud` (Ollama) and `deepseek-ai/DeepSeek-V4-Pro`
    # (DeepInfra) are THE SAME MODEL reached a different way, and that is the
    # only mapping made automatically.
    #
    # Substituting a model silently changes the system under test. It breaks any
    # A/B (provider AND model both changed, so a difference cannot be
    # attributed) and it invalidates tuned config, because caps and thresholds
    # were fitted to the ORIGINAL model. Real case 2026-08-09: swapping the DR
    # heavy model for a different one made `max_answer_tokens: 32000` truncate
    # on 2/2 runs, losing 12/16 then 4/24 chart markers — a ceiling that did not
    # exist once the correct model was restored.
    #
    # So: same model or nothing. Where the target provider does not serve a
    # model, this REFUSES to guess and reports the lane for an admin decision.

    @staticmethod
    def _canonical_model(name):
        """Reduce a model id to a provider-independent identity key.

        Identity only — this is NOT semantic matching. It strips the vendor
        namespace, the Ollama `:cloud`/`:tag` suffix, and separators, so the
        same model expressed by two providers collapses to one key:
            deepseek-v4-pro:cloud        -> deepseekv4pro
            deepseek-ai/DeepSeek-V4-Pro  -> deepseekv4pro
            glm-5.2:cloud / zai-org/GLM-5.2 -> glm52
            gpt-oss:120b-cloud / openai/gpt-oss-120b -> gptoss120b
        """
        if not name:
            return ''
        text = str(name).split('/')[-1].lower()
        # Ollama expresses size/variant after a colon (gpt-oss:120b-cloud), so the
        # colon becomes a separator rather than being stripped — dropping everything
        # after it would lose the `120b` that distinguishes the model.
        text = text.replace(':', '-')
        # Strip ONLY deployment/packaging markers. Variant tokens like -Turbo,
        # -Instruct and -FP8 are part of model IDENTITY and must NOT be removed:
        # stripping 'turbo' collapsed gpt-oss-120b and gpt-oss-120b-Turbo to the same
        # key, and the converter then picked whichever the catalog listed first —
        # silently substituting a different model, the exact thing this refuses to do.
        for noise in ('cloud', 'latest'):
            text = text.replace(noise, '')
        return re.sub(r'[^a-z0-9]', '', text)

    @staticmethod
    def _expand_secret(value):
        """Expand ${VAR}, consulting .env — secrets live there, not in the shell.

        Without this the probe sends no credentials and every target model comes
        back 401 'inconclusive', which reads as "cannot verify" when the real
        answer is "we never authenticated". Same failure mode as SI-009.
        """
        text = os.path.expandvars(value or '')
        if not text.startswith('${'):
            return text
        name = text[2:-1]
        env_file = Path(__file__).parent / '.env'
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f'{name}='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
        return text

    def _provider_catalog(self, provider, llm_config):
        """Model ids the target provider actually serves. None if unreachable."""
        import json as _json
        import urllib.error
        import urllib.request

        providers = ((llm_config.get('llm') or {}).get('providers')
                     or llm_config.get('providers') or {})
        block = providers.get(provider) or {}
        base = block.get('base_url') or PROVIDER_DEFAULTS.get(provider, {}).get('base_url')
        if not base:
            return None
        api_key = self._expand_secret(block.get('api_key'))
        request = urllib.request.Request(base.rstrip('/') + '/models')
        if api_key and not api_key.startswith('${'):
            request.add_header('Authorization', f'Bearer {api_key}')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = _json.loads(response.read().decode('utf-8', 'replace'))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
            return None
        items = data.get('data') if isinstance(data, dict) else None
        if not isinstance(items, list):
            return None
        return [m.get('id') for m in items if isinstance(m, dict) and m.get('id')]

    def _plan_conversion(self, llm_config, target):
        """Resolve every active lane to the SAME model on `target`.

        Returns (rows, catalog_ok). Each row is a dict with path, old model,
        new model (or None) and a status:
            same       - identical model found on the target
            unresolved - target does not serve it -> ADMIN DECISION REQUIRED
            skip       - inert lane (presets / fallback / provider defaults)
        """
        catalog = self._provider_catalog(target, llm_config)
        if catalog is None:
            return [], False
        by_key = {}
        for model_id in catalog:
            by_key.setdefault(self._canonical_model(model_id), model_id)

        rows = []
        for lane in self._discover_lanes(llm_config):
            if lane['inert']:
                rows.append(dict(lane, new=None, status='skip'))
                continue
            match = by_key.get(self._canonical_model(lane['model']))
            rows.append(dict(lane, new=match,
                             status='same' if match else 'unresolved'))
        return rows, True

    @staticmethod
    def _print_conversion_table(rows, target, source_label='current'):
        """The before/after table. Printed BEFORE anything is written."""
        print(f"\n{Colors.HEADER}{Colors.BOLD}Provider conversion -> "
              f"{target}{Colors.ENDC}")
        print("=" * 108)
        print(f"{'lane':<40}{source_label + ' provider:model':<34}"
              f"{target + ':model'}")
        print("-" * 108)
        active = [r for r in rows if r['status'] != 'skip']
        for row in sorted(active, key=lambda r: r['path']):
            if row['status'] == 'same':
                mark = f"{Colors.OKGREEN}same{Colors.ENDC}"
                new = row['new']
            else:
                mark = f"{Colors.FAIL}NOT SERVED{Colors.ENDC}"
                new = '-- ADMIN DECISION REQUIRED --'
            print(f"{row['path'][:39]:<40}{str(row['model'])[:33]:<34}{new}  [{mark}]")
        # Inert lanes (model_presets / fallback / provider defaults) are not ACTIVE,
        # but the writer matches on model VALUE, so any inert line naming one of the
        # same models is rewritten too. That is correct — leaving presets pointing at
        # the old provider is how a stale slug gets re-adopted later — but it MUST be
        # disclosed here, or the table under-reports what will change and the
        # confirmation is worthless.
        converting = {r['model'] for r in active if r['status'] == 'same'}
        inert_hit = [r for r in rows
                     if r['status'] == 'skip' and r['model'] in converting]
        inert_untouched = [r for r in rows
                           if r['status'] == 'skip' and r['model'] not in converting]
        if inert_hit:
            print(f"\n{Colors.OKCYAN}  + {len(inert_hit)} inert line(s) naming the same "
                  f"models will also be updated (presets / fallback / provider "
                  f"defaults):{Colors.ENDC}")
            for row in sorted(inert_hit, key=lambda r: r['path'])[:8]:
                print(f"      {row['path'][:52]:<54}{row['model']}")
            if len(inert_hit) > 8:
                print(f"      ... and {len(inert_hit) - 8} more")
        if inert_untouched:
            print(f"\n  ({len(inert_untouched)} inert line(s) left alone — they name "
                  f"models this conversion does not touch)")
        print(f"\n{Colors.BOLD}  TOTAL LINES TO CHANGE: "
              f"{len(active) + len(inert_hit)}{Colors.ENDC}  "
              f"({len(active)} active lane(s) + {len(inert_hit)} inert)")
        return active

    def convert(self, target, dry_run=False, assume_yes=False, verify=True):
        """Convert every active lane to the same models on `target`."""
        llm_config = self._load_llm_config()
        # Walk the WHOLE document. Only `primary`/`tool_calling` live under `llm:`;
        # `vision`, `arbitrator`, `deep_research` and `code_generation` are TOP-LEVEL
        # keys with their own model settings. Converting just the `llm:` block was
        # exactly the miss that left Deep Research pointed at the old provider.
        rows, ok = self._plan_conversion(llm_config, target)
        if not ok:
            print(f"{Colors.FAIL}Cannot reach the {target} model catalog.{Colors.ENDC}")
            print("Check the provider block's base_url and that its API key env var is set.")
            return 1

        active = self._print_conversion_table(rows, target)
        unresolved = [r for r in active if r['status'] == 'unresolved']

        if unresolved:
            print(f"\n{Colors.FAIL}{Colors.BOLD}REFUSING to convert: "
                  f"{len(unresolved)} lane(s) have no equivalent on {target}."
                  f"{Colors.ENDC}")
            print("A provider change must not change WHICH MODEL runs. Substituting one")
            print("silently changes the system under test and invalidates config tuned to")
            print("the original model. These need an admin decision:\n")
            for row in unresolved:
                print(f"  {row['path']}  ->  {row['model']}")
            print("\nResolve each with an explicit choice, e.g.:")
            print(f"  ./config_server_cli.py set --alias <alias> --as <role>")
            print("Nothing was written.")
            return 1

        if verify:
            print(f"\n{Colors.BOLD}Verifying each target model by INVOKING it "
                  f"(a catalog listing is not evidence)...{Colors.ENDC}")
            block = (((llm_config.get('llm') or {}).get('providers')
                      or llm_config.get('providers') or {}).get(target) or {})
            base = block.get('base_url') or PROVIDER_DEFAULTS.get(target, {}).get('base_url')
            api_key = self._expand_secret(block.get('api_key'))
            seen, dead = {}, []
            for row in active:
                model = row['new']
                if model not in seen:
                    seen[model] = self._probe_model(base, model, api_key)
                status, detail = seen[model]
                if status == self._PROBE_DEAD:
                    dead.append((model, detail))
                    print(f"  {Colors.FAIL}x{Colors.ENDC} {model:<44} {detail[:44]}")
                elif status == self._PROBE_OK:
                    print(f"  {Colors.OKGREEN}v{Colors.ENDC} {model:<44} OK")
                else:
                    print(f"  {Colors.WARNING}?{Colors.ENDC} {model:<44} "
                          f"inconclusive: {detail[:38]}")
            if dead:
                print(f"\n{Colors.FAIL}REFUSING: {len(dead)} target model(s) are "
                      f"rejected by {target}.{Colors.ENDC} Nothing was written.")
                return 1

        if dry_run:
            print(f"\n{Colors.OKCYAN}--dry-run: nothing written.{Colors.ENDC}")
            return 0

        if not assume_yes:
            print(f"\n{Colors.BOLD}Apply this conversion? "
                  f"{len(active)} lane(s) [y/N]: {Colors.ENDC}", end='')
            try:
                if input().strip().lower() not in ('y', 'yes'):
                    print("Aborted. Nothing was written.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("\nAborted. Nothing was written.")
                return 1

        written = self._write_conversion(active, target)
        print(f"\n{Colors.OKGREEN}Converted {written} lane(s) to {target}."
              f"{Colors.ENDC}")
        print(f"Revert with: {Colors.BOLD}./config_server_cli.py convert --revert"
              f"{Colors.ENDC}")
        print("Restart the server for this to take effect.")
        return 0

    _CONVERT_TAG = '# CONVERTED'
    _KNOWN_PROVIDERS = {'ollama', 'openai', 'openrouter', 'deepinfra', 'qwen', 'gemini'}

    def _target_transport(self, target):
        """base_url / api_key the converted lanes must point at."""
        llm_config = self._load_llm_config()
        providers = ((llm_config.get('llm') or {}).get('providers')
                     or llm_config.get('providers') or {})
        block = providers.get(target) or {}
        defaults = PROVIDER_DEFAULTS.get(target, {})
        return {
            'base_url': block.get('base_url') or defaults.get('base_url'),
            'api_key': block.get('api_key') or (
                '${%s}' % API_KEY_ENV_VARS[target]
                if API_KEY_ENV_VARS.get(target) else None),
        }


    def _write_conversion(self, active, target):
        """Rewrite model values IN PLACE, line by line, preserving comments.

        Deliberately NOT a yaml.safe_load()/yaml.dump() round-trip: PyYAML
        discards comments, and this file carries ~575 of them including the
        retirement history that stops a dead slug being re-added (SI-011).
        Each rewritten line is tagged with its ORIGINAL value so `--revert`
        needs no external backup.
        """
        path = self.llm_config_file
        lines = path.read_text().split('\n')
        by_old = {}
        for row in active:
            by_old.setdefault(row['model'], row['new'])

        # A lane is only converted when its TRANSPORT moves too. Rewriting model
        # names alone leaves `type:` and `base_url:` pointing at the old provider,
        # so the config sends the new provider's model ids to the OLD endpoint and
        # every call 404s. The model name is the visible half; the transport is the
        # half that actually has to move.
        tgt_block = self._target_transport(target)
        written = 0
        # Track the YAML key path by indentation. Transport keys (type/base_url/
        # api_key) must ONLY be rewritten inside an ACTIVE LANE block. Rewriting them
        # blindly also hit the `providers:` DEFINITION blocks and pointed ollama,
        # openai and openrouter all at the target's base_url — which destroys the
        # provider definitions and makes --revert impossible.
        path_stack = []
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped and not stripped.startswith('#'):
                indent = len(line) - len(stripped)
                while path_stack and path_stack[-1][0] >= indent:
                    path_stack.pop()
                key_match = re.match(r'^([A-Za-z_][\w.\-]*):', stripped)
                if key_match:
                    path_stack.append((indent, key_match.group(1)))
            segments = {seg for _, seg in path_stack}
            in_definition_block = bool(segments & self._INERT_SEGMENTS)

            if self._CONVERT_TAG in line:
                continue

            match = re.match(r'^(\s*[a-z_]*model:\s*)(\S+)(.*)$', line)
            if match:
                head, old, tail = match.groups()
                new = by_old.get(old)
                if new and new != old:
                    lines[index] = (f"{head}{new}   {self._CONVERT_TAG} -> {target} "
                                    f"(was {old}){tail}")
                    written += 1
                continue

            # transport: `type:` on a converted lane
            m_type = re.match(r'^(\s*type:\s*)(\S+)(.*)$', line)
            if m_type and not in_definition_block \
                    and m_type.group(2) in self._KNOWN_PROVIDERS \
                    and m_type.group(2) != target:
                lines[index] = (f"{m_type.group(1)}{target}   {self._CONVERT_TAG} -> "
                                f"{target} (was {m_type.group(2)}){m_type.group(3)}")
                written += 1
                continue

            # transport: base_url / api_key on a converted lane
            m_url = re.match(r'^(\s*base_url:\s*)(\S+)(.*)$', line)
            if m_url and not in_definition_block and tgt_block.get('base_url') \
                    and m_url.group(2) != tgt_block['base_url'] \
                    and not m_url.group(2).endswith('/api/tags'):
                lines[index] = (f"{m_url.group(1)}{tgt_block['base_url']}   "
                                f"{self._CONVERT_TAG} -> {target} "
                                f"(was {m_url.group(2)}){m_url.group(3)}")
                written += 1
                continue

            m_key = re.match(r'^(\s*api_key:\s*)(\S+)(.*)$', line)
            if m_key and not in_definition_block and tgt_block.get('api_key') \
                    and m_key.group(2) != tgt_block['api_key']:
                lines[index] = (f"{m_key.group(1)}{tgt_block['api_key']}   "
                                f"{self._CONVERT_TAG} -> {target} "
                                f"(was {m_key.group(2)}){m_key.group(3)}")
                written += 1
        path.write_text('\n'.join(lines))
        return written

    def convert_revert(self, assume_yes=False):
        """Undo a conversion using the inline `# CONVERTED ... (was X)` tags."""
        path = self.llm_config_file
        lines = path.read_text().split('\n')
        # Matches ANY converted key, not just `model:` — the transport keys
        # (type / base_url / api_key) are converted too, and a revert that restores
        # only the model names leaves the config half-migrated: new model ids still
        # pointed at the new endpoint, which is neither the old state nor the new one.
        pattern = re.compile(
            r'^(\s*[A-Za-z_][\w.\-]*:\s*)(\S+)\s+' + re.escape(self._CONVERT_TAG) +
            r' -> \S+ \(was (\S+)\)(.*)$')
        planned = [(i, m) for i, l in enumerate(lines) if (m := pattern.match(l))]
        if not planned:
            print("No converted lanes found (no "
                  f"'{self._CONVERT_TAG}' tags). Nothing to revert.")
            return 0
        print(f"\n{Colors.HEADER}{Colors.BOLD}Revert conversion{Colors.ENDC}")
        print("=" * 88)
        print(f"{'current':<44}{'restore to'}")
        print("-" * 88)
        for _, m in planned:
            print(f"{m.group(2)[:43]:<44}{m.group(3)}")
        if not assume_yes:
            print(f"\n{Colors.BOLD}Revert {len(planned)} lane(s)? [y/N]: {Colors.ENDC}",
                  end='')
            try:
                if input().strip().lower() not in ('y', 'yes'):
                    print("Aborted. Nothing was written.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("\nAborted. Nothing was written.")
                return 1
        for index, m in planned:
            lines[index] = f"{m.group(1)}{m.group(3)}{m.group(4)}"
        path.write_text('\n'.join(lines))
        print(f"\n{Colors.OKGREEN}Reverted {len(planned)} lane(s).{Colors.ENDC}")
        print("Restart the server for this to take effect.")
        return 0

    def _probe_model(self, base, model, api_key='', timeout=60):
        """Invoke `model` at `base` with a 1-token generation.

        Returns (status, detail) where status is _PROBE_OK / _PROBE_DEAD /
        _PROBE_UNREACHABLE. Only a server that ANSWERS and rejects the model
        counts as dead — a connection failure or an auth error is a fact about
        the endpoint, not a verdict on the model, and must never be reported as
        one.
        """
        import json
        import urllib.error
        import urllib.request

        base = base.rstrip('/')
        # Same "try both shapes" idiom the listing probe used: OpenAI-compatible
        # servers take /chat/completions, Ollama native takes /api/generate. Tried
        # in order rather than keyed off a host->path table that would rot.
        attempts = (
            (base + '/chat/completions', {
                'model': model,
                'messages': [{'role': 'user', 'content': 'hi'}],
                'max_tokens': 1,
            }),
            (base + '/api/generate', {
                'model': model,
                'prompt': 'hi',
                'stream': False,
                'options': {'num_predict': 1},
            }),
        )

        def as_object(parsed):
            """Normalise a decoded JSON body to a dict.

            Google's OpenAI-compat endpoint returns errors as a single-element
            JSON ARRAY ([{"error": {...}}]) where Ollama returns an object, so
            indexing straight into .get() blows up on one provider but not the
            other. Anything unrecognised degrades to an empty dict rather than
            raising, since a malformed body is not a verdict about the model.
            """
            if isinstance(parsed, list):
                parsed = next((item for item in parsed if isinstance(item, dict)), {})
            return parsed if isinstance(parsed, dict) else {}

        detail = ''
        for url, payload in attempts:
            request = urllib.request.Request(
                url, data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'})
            if api_key and not api_key.startswith('${'):
                request.add_header('Authorization', f'Bearer {api_key}')
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = as_object(json.loads(
                        response.read().decode('utf-8', 'replace') or '{}'))
                # Ollama can answer HTTP 200 with an error field instead of a status.
                if body.get('error'):
                    return self._PROBE_DEAD, str(body['error'])[:70]
                return self._PROBE_OK, ''
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode('utf-8', 'replace')
                try:
                    parsed = as_object(json.loads(raw or '{}'))
                except ValueError:
                    # Not a JSON API response (e.g. an HTML 404 page) — this endpoint
                    # shape simply isn't served here. Try the next shape.
                    detail = f'HTTP {exc.code}'
                    continue
                err = parsed.get('error')
                message = (err.get('message') if isinstance(err, dict) else err) or raw
                summary = f'HTTP {exc.code}: {str(message)[:70]}'
                # ONLY a response that is unambiguously about the MODEL is a verdict on
                # the model. 404/410 mean it is gone. Auth (401/403), billing (402),
                # rate limits (429) and generic 400s are facts about the ACCOUNT or the
                # REQUEST — reporting those as "retired" would repeat the exact error
                # this probe was rewritten to fix, just one layer further out.
                if exc.code in (404, 410):
                    return self._PROBE_DEAD, summary
                return self._PROBE_UNREACHABLE, summary
            except (urllib.error.URLError, OSError, ValueError) as exc:
                detail = str(exc)[:70]
                continue

        return self._PROBE_UNREACHABLE, detail or 'no endpoint shape answered'

    def _probe_aliases(self):
        """Ask each alias's endpoint whether its model still works.

        Aliases rot independently of the active config: a provider retires a
        model and the alias sits there looking valid until someone selects it.
        Invoking the live endpoint is the only reliable test — a code comment
        claiming a model was retired proved wrong when actually probed.
        """
        import os
        import subprocess

        if not self.aliases:
            print(f"{Colors.WARNING}No aliases configured.{Colors.ENDC}\n")
            return []

        print(f"{Colors.BOLD}Invoking each alias's model at its endpoint…{Colors.ENDC}\n")
        gemini_compat = 'https://generativelanguage.googleapis.com/v1beta/openai'
        seen = {}
        found = []

        for name, config in sorted(self.aliases.items()):
            provider = config.get('provider', '')
            model = config.get('model', '')
            base = config.get('base_url') or (gemini_compat if provider == 'gemini' else '')

            env_var = API_KEY_ENV_VARS.get(provider)
            api_key = os.environ.get(env_var, '') if env_var else ''
            if provider == 'gemini' and not api_key:
                # The server resolves ${GEMINI_API_KEY} from its environment; mirror
                # that here so the probe is not a false negative on a shell that
                # simply has not sourced the profile.
                api_key = subprocess.run(
                    ['bash', '-lc', f'printf %s "${env_var}"'],
                    capture_output=True, text=True).stdout.strip()

            if not base:
                print(f"  {Colors.WARNING}?{Colors.ENDC} {name:<26} {model:<28} no endpoint")
                continue

            # Dedupe so two aliases on the same model cost one generation, not two.
            if (base, model) not in seen:
                seen[(base, model)] = self._probe_model(base, model, api_key)
            status, detail = seen[(base, model)]

            if status == self._PROBE_UNREACHABLE:
                print(f"  {Colors.WARNING}?{Colors.ENDC} {name:<26} {model:<28} "
                      f"probe failed: {detail}")
            elif status == self._PROBE_OK:
                print(f"  {Colors.OKGREEN}✓{Colors.ENDC} {name:<26} {model:<28} OK")
            else:
                print(f"  {Colors.FAIL}✗{Colors.ENDC} {name:<26} {model:<28} {detail}")
                found.append((f"alias:{name}", model, base,
                              detail or 'endpoint rejected this model'))

        print()
        return found

    def _probe_endpoints(self, lanes, primary_endpoint):
        """Invoke each lane's model at its endpoint to prove it still answers.

        Authoritative, unlike the naming heuristics AND unlike the registry
        listing this used to read — see _probe_model for why a listing is
        evidence in neither direction.
        """
        import os

        print(f"{Colors.BOLD}Invoking each lane's model at its endpoint…{Colors.ENDC}\n")
        found = []
        checked = set()

        for lane in [lane for lane in lanes if not lane['inert']]:
            endpoint = lane['own_endpoint'] or primary_endpoint or ''
            model = lane['model']
            if not endpoint or (endpoint, model) in checked:
                continue
            checked.add((endpoint, model))

            base = endpoint.rstrip('/')
            # Expand ${VAR} the same way the loader does, so a probe uses the real key.
            api_key = os.path.expandvars(
                '${GEMINI_API_KEY}' if 'googleapis' in endpoint else ''
            )

            status, detail = self._probe_model(base, model, api_key)

            if status == self._PROBE_UNREACHABLE:
                print(f"  {Colors.WARNING}?{Colors.ENDC} {lane['path']:<46} {model:<24} "
                      f"probe failed: {detail}")
                continue

            mark = (f"{Colors.OKGREEN}✓{Colors.ENDC}" if status == self._PROBE_OK
                    else f"{Colors.FAIL}✗{Colors.ENDC}")
            suffix = f" — {detail}" if status == self._PROBE_DEAD else ''
            print(f"  {mark} {lane['path']:<46} {model:<24} @ {endpoint}{suffix}")
            if status == self._PROBE_DEAD:
                found.append((lane['path'], model, endpoint,
                              detail or 'endpoint rejected this model'))

        print()
        return found


def main():
    parser = argparse.ArgumentParser(
        description="Server Configuration CLI Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ls
  %(prog)s add --alias qwen_local --provider ollama --model qwen3:8b
  %(prog)s add --alias gemini_flash --provider gemini --model gemini-flash-latest
  %(prog)s set --alias gemini_flash --as primary
  %(prog)s show --alias gemini_flash
  %(prog)s delete --alias qwen_local
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # List command
    subparsers.add_parser('ls', help='List all model aliases')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new model alias')
    add_parser.add_argument('--alias', required=True, help='Alias name')
    add_parser.add_argument('--provider', required=True,
                           choices=['ollama', 'openai', 'openrouter', 'deepinfra',
                                    'qwen', 'gemini'],
                           help='LLM provider')
    add_parser.add_argument('--model', required=True, help='Model name')
    add_parser.add_argument('--api-key-env', dest='api_key_env',
                           help='Env var holding the credentials for this endpoint '
                                '(e.g. GEMINI_API_KEY for an openai-protocol alias '
                                'pointed at Google). Inferred from --base-url if omitted.')
    add_parser.add_argument('--base-url', dest='base_url',
                           help='Override the provider default endpoint (e.g. Google\'s '
                                'OpenAI-compatible URL to get Gemini models onto tool_calling)')
    add_parser.add_argument('--timeout', type=int, help='Timeout in seconds')
    add_parser.add_argument('--temperature', type=float, help='Temperature (0.0-2.0)')
    add_parser.add_argument('--max-tokens', type=int, help='Max tokens to generate')
    add_parser.add_argument('--context-window', type=int, help='Context window size')
    add_parser.add_argument('--think', action='store_true', help='Enable think mode (Ollama reasoning models)')
    add_parser.add_argument('--no-think', action='store_true', help='Disable think mode (Ollama reasoning models)')
    add_parser.add_argument('--description', help='Description of this alias')
    add_parser.add_argument('--fallback-model', help='Fallback model to use')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update an existing alias')
    update_parser.add_argument('--alias', required=True, help='Alias name')
    update_parser.add_argument('--model', help='New model name')
    update_parser.add_argument('--base-url', dest='base_url', help='New endpoint URL')
    update_parser.add_argument('--timeout', type=int, help='New timeout')
    update_parser.add_argument('--temperature', type=float, help='New temperature')
    update_parser.add_argument('--max-tokens', type=int, help='New max tokens')
    update_parser.add_argument('--context-window', type=int, help='New context window')
    update_parser.add_argument('--think', action='store_true', help='Enable think mode')
    update_parser.add_argument('--no-think', action='store_true', help='Disable think mode')
    update_parser.add_argument('--description', help='New description')
    update_parser.add_argument('--fallback-model', help='New fallback model')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a model alias')
    delete_parser.add_argument('--alias', required=True, help='Alias name to delete')
    delete_parser.add_argument('--force', action='store_true',
                              help='Force delete even if in use')

    # Show command
    show_parser = subparsers.add_parser('show', help='Show alias details')
    show_parser.add_argument('--alias', required=True, help='Alias name')

    # Set command
    set_parser = subparsers.add_parser('set', help='Set an alias as primary/tool_calling/arbitrator')
    set_parser.add_argument('--alias', required=True, help='Alias name')
    set_parser.add_argument('--as', dest='role', required=True,
                           choices=['primary', 'tool_calling', 'arbitrator', 'vision'],
                           help='Role to assign')
    set_parser.add_argument('--with-dependents', action='store_true',
                           help='When setting primary, also move the lanes that inherit '
                                'its endpoint (deep_research, convergence, code_generation)')
    set_parser.add_argument('--force', action='store_true',
                           help='When setting primary, switch even though dependent lanes '
                                'would be left pointing at models the new endpoint lacks')

    # Status command
    subparsers.add_parser('status', help='Show current active models')

    # Lanes command — full inventory, walked from the YAML so it cannot go stale
    subparsers.add_parser('lanes',
                          help='List EVERY model lane and whether it inherits primary\'s endpoint')

    # Doctor command — catch model/endpoint mismatches before they 404 at runtime
    doctor_parser = subparsers.add_parser(
        'doctor', help='Check each lane\'s model against the endpoint it resolves to')
    doctor_parser.add_argument('--probe', action='store_true',
                               help='Also INVOKE each lane\'s model (1-token generation, '
                                    'costs one request per model) to prove it still answers')
    # Convert command
    convert_parser = subparsers.add_parser(
        'convert',
        help='Convert every active lane to the SAME models on another provider')
    convert_parser.add_argument('--to', dest='to_provider',
                                choices=['ollama', 'openai', 'openrouter',
                                         'deepinfra', 'qwen', 'gemini'],
                                help='Target provider')
    convert_parser.add_argument('--revert', action='store_true',
                                help='Undo a previous conversion using the inline '
                                     '"# CONVERTED ... (was X)" tags')
    convert_parser.add_argument('--dry-run', dest='dry_run', action='store_true',
                                help='Print the before/after table and exit without writing')
    convert_parser.add_argument('--yes', action='store_true',
                                help='Skip the confirmation prompt')
    convert_parser.add_argument('--no-verify', dest='no_verify', action='store_true',
                                help='Skip INVOKING each target model (not recommended — '
                                     'a catalog listing is not evidence it serves)')

    doctor_parser.add_argument('--aliases', action='store_true',
                               help='Also INVOKE every saved alias\'s model at its endpoint '
                                    '(same 1-token cost per distinct model)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize manager
    manager = ModelAliasManager()

    # Execute command
    try:
        if args.command == 'ls':
            manager.list_aliases()

        elif args.command == 'add':
            manager.add_alias(
                alias=args.alias,
                provider=args.provider,
                model=args.model,
                timeout=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                context_window=args.context_window,
                think=args.think,
                no_think=args.no_think,
                description=args.description,
                fallback_model=args.fallback_model,
                base_url=args.base_url,
                api_key_env=args.api_key_env
            )

        elif args.command == 'update':
            manager.update_alias(
                alias=args.alias,
                model=args.model,
                timeout=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                context_window=args.context_window,
                think=args.think,
                no_think=args.no_think,
                description=args.description,
                fallback_model=args.fallback_model,
                base_url=args.base_url
            )

        elif args.command == 'delete':
            manager.delete_alias(args.alias, force=args.force)

        elif args.command == 'show':
            manager.show_alias(args.alias)

        elif args.command == 'set':
            manager.set_alias(args.alias, args.role,
                              with_dependents=args.with_dependents,
                              force=args.force)

        elif args.command == 'status':
            manager.show_status()

        elif args.command == 'lanes':
            manager.show_lanes()

        elif args.command == 'convert':
            if args.revert:
                sys.exit(manager.convert_revert(assume_yes=args.yes))
            if not args.to_provider:
                print(f"{Colors.FAIL}--to <provider> is required (or --revert){Colors.ENDC}")
                sys.exit(1)
            sys.exit(manager.convert(args.to_provider, dry_run=args.dry_run,
                                     assume_yes=args.yes, verify=not args.no_verify))

        elif args.command == 'doctor':
            # Non-zero exit on problems so this can gate a deploy/CI step.
            sys.exit(1 if manager.doctor(probe=args.probe,
                                         check_aliases=args.aliases) else 0)

    except Exception as e:
        print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
