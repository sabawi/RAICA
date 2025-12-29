# Multi-Provider LLM Support Guide

**Version:** 1.0.0
**Date:** 2025-11-23

---

## Overview

The Website Deployment Agent now supports **5 LLM providers** with automatic fallback:

1. **Anthropic Claude** - High-quality structured output
2. **OpenAI GPT** - Reliable and fast
3. **Google Gemini** - Large context window
4. **Qwen** - Alibaba's strong coding model
5. **Local Ollama** - Privacy-focused local models

All configuration is centralized in `/config/llm_config.yaml` under the `code_generation:` section.

---

## Configuration

### Location

```
/config/llm_config.yaml
```

### Structure

```yaml
code_generation:
  type: anthropic  # Active provider

  fallback:
    enabled: true
    order:
      - anthropic
      - openai
      - gemini
      - ollama
      - qwen

  providers:
    anthropic:
      model: claude-sonnet-4-20250514
      api_key: ${ANTHROPIC_API_KEY}
      base_url: https://api.anthropic.com
      timeout: 120
      temperature: 0.0
      max_tokens: 4096

    # ... other providers (see config file)
```

---

## Switching Providers

### Method 1: Change Primary Provider

Edit `/config/llm_config.yaml`:

```yaml
code_generation:
  type: openai  # Change from anthropic to openai
```

Then uncomment the OpenAI section:

```yaml
providers:
  # anthropic:
  #   model: claude-sonnet-4-20250514
  #   ... (commented out)

  openai:  # Uncomment this section
    model: gpt-4o
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
    timeout: 120
    temperature: 0.0
    max_tokens: 4096
```

### Method 2: Enable All Providers (Automatic Fallback)

Keep all providers uncommented and enable fallback:

```yaml
code_generation:
  type: anthropic  # Try this first

  fallback:
    enabled: true  # If anthropic fails, try others
    order:
      - anthropic
      - openai
      - gemini
      - ollama
      - qwen

  providers:
    anthropic:
      # ... config
    openai:
      # ... config
    gemini:
      # ... config
```

---

## Environment Variables

Set API keys in `/home/sabawi/Development/flaskserver/.env`:

```bash
# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-api03-...

# OpenAI GPT
OPENAI_API_KEY=sk-proj-...

# Google Gemini
GEMINI_API_KEY=AIzaSy...

# Qwen (Alibaba DashScope)
QWEN_API_KEY=sk-...

# Ollama (local - no API key needed)
# Just ensure Ollama is running: ollama serve
```

---

## Provider Comparison

| Provider | Best For | Pros | Cons | Cost |
|----------|----------|------|------|------|
| **Anthropic Claude** | Structured output | Best JSON formatting, reliable | Requires credits | $$$ |
| **OpenAI GPT** | General purpose | Fast, reliable, good docs | Less precise JSON | $$ |
| **Google Gemini** | Large context | Huge context window (2M tokens) | Sometimes verbose | $ |
| **Qwen** | Coding tasks | Strong at code generation | Less known, Chinese focus | $ |
| **Ollama** | Privacy/offline | Free, private, local | Requires GPU, slower | Free |

---

## Testing Different Providers

### 1. Test with Anthropic (Default)

```bash
# Set API key
export ANTHROPIC_API_KEY="your-key"

# Run tests
python tests/test_requirement_analyzer.py -v
```

### 2. Test with OpenAI

Edit `/config/llm_config.yaml`:
```yaml
code_generation:
  type: openai  # Change here
```

```bash
# Set API key
export OPENAI_API_KEY="your-key"

# Run tests
python tests/test_requirement_analyzer.py -v
```

### 3. Test with Local Ollama

```bash
# Start Ollama (if not running)
ollama serve

# Pull a coding model
ollama pull qwen2.5:72b

# Edit config to use ollama
# type: ollama

# Run tests (no API key needed!)
python tests/test_requirement_analyzer.py -v
```

### 4. Test Automatic Fallback

```bash
# Set multiple API keys
export ANTHROPIC_API_KEY="invalid-key"  # This will fail
export OPENAI_API_KEY="valid-key"       # This will work

# Enable fallback in config
# fallback:
#   enabled: true

# Run tests - should automatically fall back to OpenAI
python tests/test_requirement_analyzer.py -v
```

---

## Usage in Code

### Basic Usage (Automatic Provider Selection)

```python
from stages import RequirementAnalyzer, ArchitectureDesigner

# Uses provider configured in llm_config.yaml
analyzer = RequirementAnalyzer()
result = analyzer.analyze(specification)

designer = ArchitectureDesigner()
architecture = designer.design(requirements)
```

### Advanced: Direct LLM Client Usage

```python
from stages.llm_client import LLMClient

# Initialize client (reads config automatically)
client = LLMClient()

# Generate with primary provider
response = client.generate("Your prompt here")

if response.success:
    print(f"Used: {response.provider} / {response.model}")
    print(f"Response: {response.content}")
else:
    print(f"Error: {response.error}")

# Force specific provider
response = client.generate("Your prompt", provider="ollama")
```

---

## Troubleshooting

### Problem: "All providers failed"

**Cause:** No valid API keys or all providers returned errors

**Solution:**
1. Check API keys are set in `.env`
2. Verify API keys are valid
3. Check provider has credits/quota
4. Enable fallback to try multiple providers

### Problem: "Provider 'X' not configured"

**Cause:** Provider section is commented out in `llm_config.yaml`

**Solution:** Uncomment the provider's section in the config file

### Problem: "ANTHROPIC_API_KEY not set in environment"

**Cause:** API key not loaded from `.env` file

**Solution:**
1. Add key to `/home/sabawi/Development/flaskserver/.env`
2. Ensure `.env` is being loaded (tests now do this automatically)
3. Or export manually: `export ANTHROPIC_API_KEY="your-key"`

### Problem: Ollama fails with connection error

**Cause:** Ollama server not running

**Solution:**
```bash
# Start Ollama
ollama serve

# Verify it's running
curl http://127.0.0.1:11434/api/tags
```

---

## Performance Tips

### For Speed: Use OpenAI or Gemini
```yaml
code_generation:
  type: openai
  providers:
    openai:
      model: gpt-4o-mini  # Faster, cheaper
```

### For Quality: Use Anthropic Claude
```yaml
code_generation:
  type: anthropic
  providers:
    anthropic:
      model: claude-sonnet-4-20250514  # Best quality
```

### For Privacy: Use Local Ollama
```yaml
code_generation:
  type: ollama
  providers:
    ollama:
      model: qwen2.5:72b  # Good coding model
      base_url: http://127.0.0.1:11434
```

### For Cost: Use Gemini Flash
```yaml
code_generation:
  type: gemini
  providers:
    gemini:
      model: gemini-2.0-flash-exp  # Cheapest option
```

---

## Example: Complete Workflow

```bash
# 1. Set up environment
cd /home/sabawi/Development/flaskserver
source venv/bin/activate

# 2. Configure provider in config/llm_config.yaml
# (Choose your preferred provider)

# 3. Set API key in .env
echo "OPENAI_API_KEY=your-key" >> .env

# 4. Run deployment agent
cd agents/website_deployer
python examples/full_deployment_demo.py

# The agent will:
# - Analyze requirements using configured LLM
# - Design architecture using same LLM
# - Generate code
# - Deploy to server
```

---

## Migration from Old API

### Before (Anthropic Only)

```python
analyzer = RequirementAnalyzer(anthropic_api_key=api_key)
designer = ArchitectureDesigner(anthropic_api_key=api_key)
```

### After (Multi-Provider)

```python
# API key comes from config/llm_config.yaml and .env
analyzer = RequirementAnalyzer()
designer = ArchitectureDesigner()
```

---

## Files Changed

1. ✅ `/config/llm_config.yaml` - Added `code_generation:` section
2. ✅ `stages/llm_client.py` - New multi-provider LLM client
3. ✅ `stages/requirement_analyzer.py` - Uses LLMClient
4. ✅ `stages/architecture_designer.py` - Uses LLMClient
5. ✅ `requirements.txt` - Added all provider libraries
6. ✅ `tests/*.py` - Updated for new API
7. ✅ `examples/*.py` - Updated for new API

---

## Summary

✅ **5 LLM providers supported**
✅ **Automatic fallback enabled**
✅ **Centralized configuration**
✅ **No code changes needed to switch providers**
✅ **Tests updated and working**

Switch providers by editing one line in `/config/llm_config.yaml`!

---

**Questions?** Check the test files for usage examples or refer to the main README.md
