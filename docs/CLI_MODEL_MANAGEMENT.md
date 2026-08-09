# Server Configuration CLI Tool - Quick Reference Guide

## Overview

The `config_server_cli.py` CLI tool provides easy management of LLM model configurations through named aliases. Instead of manually editing YAML files, you can quickly switch between different model configurations using simple commands.

## Features

- **Create model aliases** with full configuration (provider, model, timeout, temperature, etc.)
- **List all configured aliases** with active status indicators
- **Switch models** for primary, tool_calling, or arbitrator roles
- **Update/delete aliases** as needed
- **View current active models** at a glance
- **Color-coded output** for better readability

## Quick Start

### 1. Check Current Active Models
```bash
./config_server_cli.py status
```

### 2. List All Aliases
```bash
./config_server_cli.py ls
```

### 3. Create Your First Alias
```bash
# Local Ollama model
./config_server_cli.py add --alias my_local_qwen \
  --provider ollama \
  --model qwen3:8b \
  --description "My local Qwen model"

# OpenRouter model
./config_server_cli.py add --alias my_deepseek \
  --provider openrouter \
  --model deepseek/deepseek-r1 \
  --timeout 3600 \
  --temperature 0.7

# OpenAI model
./config_server_cli.py add --alias gpt4_mini \
  --provider openai \
  --model gpt-4o-mini \
  --timeout 120 \
  --temperature 0.1

# Gemini model
./config_server_cli.py add --alias gemini_flash \
  --provider gemini \
  --model gemini-flash-latest \
  --timeout 120 \
  --temperature 0.7
```

### 4. Set an Alias as Active
```bash
# Set as primary LLM
./config_server_cli.py set --alias my_local_qwen --as primary

# Set as tool calling LLM
./config_server_cli.py set --alias gpt4_mini --as tool_calling

# Set as arbitrator
./config_server_cli.py set --alias gpt4_mini --as arbitrator

# Set as vision model
./config_server_cli.py set --alias gemini_flash --as vision
```

## Command Reference

### `doctor` - Check Every Lane's Model Against Its Endpoint

```bash
./config_server_cli.py doctor                      # static checks only (free, offline)
./config_server_cli.py doctor --probe              # also INVOKE each active lane's model
./config_server_cli.py doctor --probe --aliases    # also INVOKE every saved alias's model
```

Catches a model/endpoint mismatch **before** it 404s in production. Exits non-zero when it finds a
problem, so it can gate a deploy.

- **Without flags** it runs advisory naming checks only — no network, no cost.
- **`--probe` / `--aliases`** send a real **1-token generation** to each model. This **costs one
  request per distinct model** (aliases are deduped by endpoint+model), which is why it is opt-in.

#### Why it invokes instead of reading the model list

Availability can only be established by **invoking** the model. A registry listing (`/api/tags`,
`/models`) is evidence in **neither** direction, and reading one produces confidently wrong verdicts
in both:

| Model | What the listing said | Reality |
|---|---|---|
| `gemma4:31b-cloud` | absent → "not served" | **works** (never pulled locally; `/api/tags` only lists *pulled* models) |
| `kimi-k2.7-code:cloud` | absent → "not served" | **works** |
| `qwen3-vl:235b-cloud` | listed → "healthy" | **HTTP 410, retired 2026-06-16** |

The listing check therefore passed the one genuinely dead model — the exact failure the command
exists to catch — and failed two working ones. It was replaced with real invocation in v1.0.0.233.

#### Reading the output

| Mark | Meaning |
|---|---|
| `✓` | The model generated a token. It works. |
| `✗` | The endpoint **answered and rejected the model** — HTTP `404` (no such model) or `410` (retired). This is a real verdict and is counted as a problem. |
| `?` | Inconclusive — the probe could not reach a verdict *about the model*: connection failure, auth (`401`/`403`), billing (`402`), rate limit (`429`), or a generic `400`. The server's message is shown. **Not** counted as a dead model. |

A `?` still deserves attention — it usually means a credential or account problem — but it is
deliberately never reported as "model retired", because that conflation is what produced the false
claims above.

**Example:**
```bash
$ ./config_server_cli.py doctor --probe --aliases
  ✓ llm.primary.config.model          deepseek-v4-pro:cloud   @ http://127.0.0.1:11434
  ✓ vision.config.model               minimax-m3:cloud        @ http://127.0.0.1:11434
  ✗ deepseek_ollama_cloud  deepseek-v3.1:671b-cloud  HTTP 410: deepseek-v3.1:671b was retired at 2026-07-15
  ? gemini_pro_25          gemini-2.5-pro            probe failed: HTTP 400: Please pass a valid API key
```

Run this after any model swap, and before a deploy that touches an LLM lane.

### `ls` - List All Aliases
```bash
./config_server_cli.py ls
```
Shows all configured model aliases with:
- Provider and model name
- Configuration parameters (timeout, temperature, max tokens)
- Active status (PRIMARY, TOOL_CALLING, ARBITRATOR, VISION)
- Creation date

### `add` - Create New Alias
```bash
./config_server_cli.py add --alias NAME --provider TYPE --model MODEL [OPTIONS]
```

**Required Parameters:**
- `--alias NAME` - Unique name for this alias
- `--provider TYPE` - Provider type: `ollama`, `openai`, `openrouter`, `deepinfra`, `qwen`, `gemini`
- `--model MODEL` - Model identifier

**Optional Parameters:**
- `--timeout N` - Timeout in seconds (default: provider-specific)
- `--temperature N` - Temperature 0.0-2.0 (default: provider-specific)
- `--max-tokens N` - Max tokens to generate (default: provider-specific)
- `--context-window N` - Context window size
- `--think` - Enable think mode (Ollama reasoning models like DeepSeek)
- `--no-think` - Disable think mode (Ollama reasoning models)
- `--description TEXT` - Human-readable description

**Examples:**
```bash
# Minimal Ollama alias
./config_server_cli.py add --alias local_llama \
  --provider ollama \
  --model llama3.2:3b

# Full OpenRouter configuration
./config_server_cli.py add --alias cloud_deepseek \
  --provider openrouter \
  --model deepseek/deepseek-r1 \
  --timeout 3600 \
  --temperature 0.7 \
  --max-tokens 16384 \
  --context-window 32768 \
  --description "DeepSeek R1 for reasoning tasks"

# OpenAI with custom settings
./config_server_cli.py add --alias gpt4_turbo \
  --provider openai \
  --model gpt-4-turbo-preview \
  --timeout 300 \
  --temperature 0.3 \
  --max-tokens 4096

# Gemini model for vision tasks
./config_server_cli.py add --alias gemini_vision \
  --provider gemini \
  --model gemini-flash-latest \
  --timeout 120 \
  --temperature 0.7 \
  --max-tokens 8192 \
  --description "Gemini Flash for vision processing"

# DeepSeek reasoning model with think mode disabled
./config_server_cli.py add --alias deepseek_cloud \
  --provider ollama \
  --model deepseek-v3.1:671b-cloud \
  --timeout 600 \
  --max-tokens 16384 \
  --no-think \
  --description "DeepSeek V3.1 via Ollama without reasoning display"
```

### `update` - Update Existing Alias
```bash
./config_server_cli.py update --alias NAME [OPTIONS]
```

Update any parameter of an existing alias:
```bash
# Change model version
./config_server_cli.py update --alias local_llama --model llama3.2:7b

# Adjust timeout and temperature
./config_server_cli.py update --alias cloud_deepseek \
  --timeout 1800 \
  --temperature 0.5

# Update description
./config_server_cli.py update --alias gpt4_turbo \
  --description "GPT-4 Turbo for complex tasks"
```

### `delete` - Remove Alias
```bash
./config_server_cli.py delete --alias NAME [--force]
```

- Prevents deletion if alias is currently active (unless `--force` used)
- Permanently removes alias from configuration

**Examples:**
```bash
# Safe delete (fails if in use)
./config_server_cli.py delete --alias old_model

# Force delete (even if active)
./config_server_cli.py delete --alias old_model --force
```

### `show` - Show Alias Details
```bash
./config_server_cli.py show --alias NAME
```

Displays complete configuration for an alias:
```bash
./config_server_cli.py show --alias my_local_qwen
```

Output shows all parameters including timestamps and provider-specific settings.

### `convert` - Switch ALL lanes to another provider

```bash
./config_server_cli.py convert --to deepinfra --dry-run   # preview, writes nothing
./config_server_cli.py convert --to deepinfra             # apply, with confirmation
./config_server_cli.py convert --revert                   # undo
```

**A provider change is a TRANSPORT change, not a model change.** `deepseek-v4-pro:cloud`
(Ollama) and `deepseek-ai/DeepSeek-V4-Pro` (DeepInfra) are the same model reached a
different way, and that is the only mapping made automatically.

Substituting a model silently changes the system under test: it confounds any A/B
(provider *and* model changed, so a difference cannot be attributed) and it invalidates
tuned config, because caps were fitted to the ORIGINAL model. Real case 2026-08-09:
swapping the DR heavy model made `max_answer_tokens: 32000` truncate on 2/2 runs, losing
12/16 then 4/24 chart markers — a ceiling that vanished once the correct model was restored.

**What it does**

1. **Discovers every model-bearing lane in the WHOLE config** — `vision`, `arbitrator`,
   `deep_research` and `code_generation` are top-level keys, not under `llm:`. Doing this
   by hand missed Deep Research and both `convergence` classifiers.
2. **Maps same-model-only.** Vendor namespace and `:cloud` suffix are normalised away;
   variant tokens (`-Turbo`, `-Instruct`, `-FP8`) are NOT — they are model identity.
3. **Refuses to guess.** If the target does not serve a model, it stops, names the lane,
   and asks for an admin decision. Nothing is written.
4. **Verifies by INVOKING** each target model — a catalog listing is evidence in neither
   direction. Skip with `--no-verify` (not recommended).
5. **Prints a before/after table** and requires confirmation. The table discloses inert
   lines (presets/fallback) that will also change, so predicted lines == written lines.
6. **Preserves comments** — surgical line edits, not a `yaml.dump()` round-trip (SI-011).
   Each rewritten line is tagged `# CONVERTED -> <provider> (was <original>)`, so
   `--revert` needs no external backup and round-trips byte-identically.

**Example**

```
lane                                 current provider:model     deepinfra:model
llm.primary.config.model             deepseek-v4-pro:cloud      deepseek-ai/DeepSeek-V4-Pro  [same]
deep_research.engine.heavy_model     deepseek-v4-pro:cloud      deepseek-ai/DeepSeek-V4-Pro  [same]
vision.config.model                  minimax-m3:cloud           MiniMaxAI/MiniMax-M3         [same]
  + 6 inert line(s) naming the same models will also be updated
  TOTAL LINES TO CHANGE: 17  (11 active lane(s) + 6 inert)
```

### `set` - Set Active Model
```bash
./config_server_cli.py set --alias NAME --as ROLE
```

> **⚠️ KNOWN DEFECT — `set` deletes every comment in `config/llm_config.yaml`**
> (tracked as **SI-011**, confirmed 2026-08-09). The writer round-trips the file
> through `yaml.safe_load()` → `yaml.dump()`, and PyYAML discards comments because
> they are not part of the YAML data model. One `set` removed all 525 comment
> markers — every "was X — retired" breadcrumb and every scaling note. Key order
> survives, so the file still *looks* correct and the loss is easy to miss.
>
> **Until this is fixed, back up before switching:**
> ```bash
> cp config/llm_config.yaml /tmp/llm_config.bak
> ./config_server_cli.py set --alias NAME --as ROLE
> diff /tmp/llm_config.bak config/llm_config.yaml   # review what else changed
> ```

**Roles:**
- `primary` - Main LLM for user queries
- `tool_calling` - LLM that decides which tools to call
- `arbitrator` - LLM that analyzes tool execution and optimizes
- `vision` - LLM for image and visual content processing

**Examples:**
```bash
# Switch primary to local model
./config_server_cli.py set --alias local_llama --as primary

# Use GPT-4 mini for tool calling
./config_server_cli.py set --alias gpt4_mini --as tool_calling

# Set arbitrator
./config_server_cli.py set --alias gpt4_mini --as arbitrator

# Set vision model
./config_server_cli.py set --alias gemini_vision --as vision
```

### `status` - Show Active Models
```bash
./config_server_cli.py status
```

Displays currently active models for each role:
- PRIMARY - Main LLM
- TOOL_CALLING - Tool selection LLM
- ARBITRATOR - Optimization LLM
- VISION - Visual content processing LLM

## Provider-Specific Defaults

### Ollama
- **Base URL:** `http://127.0.0.1:11434`
- **Timeout:** 600s
- **Temperature:** 0.7
- **Max Tokens:** 4096
- **No API key required**

### OpenAI
- **Base URL:** `https://api.openai.com/v1`
- **Timeout:** 120s
- **Temperature:** 0.1
- **Max Tokens:** 2048
- **API Key:** Reads from `$OPENAI_API_KEY`

### OpenRouter
- **Base URL:** `https://openrouter.ai/api/v1`
- **Timeout:** 600s
- **Temperature:** 0.7
- **Max Tokens:** 4096
- **API Key:** Reads from `$OPENROUTER_API_KEY`
- **Custom Headers:** HTTP-Referer, X-Title for rankings

### DeepInfra
- **Base URL:** `https://api.deepinfra.com/v1/openai`
- **Timeout:** 600s
- **Temperature:** 0.7
- **Max Tokens:** 4096
- **API Key:** Reads from `$DEEPINFRA_API_KEY`
- **Model naming:** `organization/model-name` (e.g. `deepseek-ai/DeepSeek-V3.1`,
  `zai-org/GLM-5.2`, `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`)
- **Note:** OpenAI-compatible — driven by `llm_providers/openai.py`, no provider
  module of its own (same arrangement as OpenRouter).
- **⚠️ No free tier.** Inference returns `HTTP 402 "You need positive balance to do
  inference"` until the account is funded. A 402 confirms the slug and credentials
  are valid; a nonexistent slug returns `404 model_not_found` instead, so the two
  codes can be used to validate model names at zero cost.

### Qwen (Alibaba Cloud)
- **Base URL:** `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **Timeout:** 300s
- **Temperature:** 0.7
- **Max Tokens:** 4096
- **API Key:** Reads from `$DASHSCOPE_API_KEY`

### Gemini (Google)
- **Timeout:** 120s
- **Temperature:** 0.7
- **Max Tokens:** 8192
- **API Key:** Reads from `$GEMINI_API_KEY`
- **Note:** Uses native Gemini API, not OpenAI-compatible endpoint

## Common Workflows

### Switching from Cloud to Local
```bash
# Check current setup
./config_server_cli.py status

# Create local alias if not exists
./config_server_cli.py add --alias qwen_local_fast \
  --provider ollama \
  --model qwen3:8b

# Switch primary to local
./config_server_cli.py set --alias qwen_local_fast --as primary

# Verify change
./config_server_cli.py status
```

### Creating a New OpenRouter Model
```bash
# Add alias with full configuration
./config_server_cli.py add --alias my_claude \
  --provider openrouter \
  --model anthropic/claude-3.5-sonnet \
  --timeout 600 \
  --temperature 0.8 \
  --max-tokens 8192 \
  --description "Claude 3.5 Sonnet via OpenRouter"

# Set as primary
./config_server_cli.py set --alias my_claude --as primary
```

### Testing Different Temperatures
```bash
# Create multiple aliases with same model, different temps
./config_server_cli.py add --alias gpt4_creative \
  --provider openai \
  --model gpt-4o \
  --temperature 1.2

./config_server_cli.py add --alias gpt4_precise \
  --provider openai \
  --model gpt-4o \
  --temperature 0.1

# Switch between them as needed
./config_server_cli.py set --alias gpt4_creative --as primary
./config_server_cli.py set --alias gpt4_precise --as primary
```

## Configuration Files

### Model Aliases Database
- **Location:** `config/model_aliases.json`
- **Format:** JSON
- **Backup:** Recommended before major changes
- **Manual Edit:** Possible but not recommended

### LLM Configuration
- **Location:** `config/llm_config.yaml`
- **Modified by:** `set` command
- **Preserved:** Comments and other sections
- **Format:** YAML

## Tips and Best Practices

1. **Use Descriptive Alias Names**
   ```bash
   # Good
   ./config_server_cli.py add --alias local_qwen_8b_reasoning ...

   # Less clear
   ./config_server_cli.py add --alias model1 ...
   ```

2. **Add Descriptions**
   - Helps remember what each alias is for
   - Shows in `ls` output
   ```bash
   --description "Fast local model for quick queries"
   ```

3. **Check Status Regularly**
   ```bash
   ./config_server_cli.py status
   ```
   Know which models are active before testing

4. **List Before Switching**
   ```bash
   ./config_server_cli.py ls
   ```
   See what's available and their configurations

5. **Backup Aliases**
   ```bash
   cp config/model_aliases.json config/model_aliases.backup.json
   ```

6. **Test After Switching**
   - Restart server after changing models
   - Test with simple query first
   ```bash
   ./stop_complete.sh && ./start_complete.sh
   ```

## Troubleshooting

### Alias Already Exists
```bash
Error: Alias 'my_model' already exists.
Use './config_server_cli.py update --alias my_model' to modify it.
```
**Solution:** Use `update` instead of `add`, or choose a different name

### Alias Not Found
```bash
Error: Alias 'nonexistent' not found.
```
**Solution:** Check spelling, use `./config_server_cli.py ls` to see available aliases

### Cannot Delete Active Alias
```bash
Warning: Alias 'my_model' is currently active for: primary
Use --force to delete anyway.
```
**Solution:** Switch to different model first, or use `--force`

### Provider Not Supported
```bash
Error: Unknown provider 'custom'
Supported providers: ollama, openai, openrouter, qwen, gemini
```
**Solution:** Use one of the supported providers

## Integration with Server

After changing model configurations:

1. **Stop the server:**
   ```bash
   ./stop_complete.sh
   ```

2. **Verify configuration:**
   ```bash
   ./config_server_cli.py status
   ```

3. **Start the server:**
   ```bash
   ./start_complete.sh
   ```

4. **Test with a simple query:**
   ```bash
   curl -X POST http://localhost:5000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "primary", "messages": [{"role": "user", "content": "Hello"}]}'
   ```

## Version Information

- **Tool Name:** config_server_cli.py
- **Version:** 1.0.1
- **Last Updated:** 2025-10-25
- **Compatibility:** RAICA Server v1.0.3.26+
- **Python:** 3.8+
- **Dependencies:** PyYAML

## See Also

- [LLM Configuration Guide](LLM_CONFIGURATION_GUIDE.md) - Detailed configuration documentation
- [Administrator Guide](production/ADMINISTRATOR_GUIDE.md) - Server management
- [Project Configuration Directive](PROJECT_CONFIGURATION_DIRECTIVE.md) - Configuration rules
