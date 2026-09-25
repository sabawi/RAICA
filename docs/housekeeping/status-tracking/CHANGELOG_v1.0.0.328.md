# CHANGELOG v1.0.0.328

**Date:** 2026-09-25
**Theme:** the tool model can finally see the tools — and the weather answers get their temperature

## Fixed

- **Ollama tool payload was double-wrapped (SI-102) — since v1.0.0.1.** `llm_providers/ollama.py` wrapped every
  tool as `{"type": "function", "function": tool}`, but callers already send that shape. Ollama cannot read the
  buried name, so every Ollama-served tool model saw NO schemas and could only call tools the system prompt names
  in prose. Measured: single-wrapped weather tool → called; double-wrapped → "I don't have access to a real-time
  weather tool". Now pre-wrapped definitions pass through unchanged — the same check the OpenAI provider makes.
- **`weather_info` (SI-101)** — `plugins/handlers/weather_info.py`: city is URL-encoded (New York / São Paulo
  failed); `units` is honoured (metric used to come back in °F); output states the units and carries a citable
  source link; an unknown place is a failure, detected by the service's HTTP status (it used to be returned as
  the "weather").
- **Tool-calling instructions** — `pre_tool_model_system_prompt.txt`: a DEDICATED-TOOL RULE — read all tool
  descriptions; when a tool returns exactly the live data asked for (weather, flights, SEC filings, a quote), call
  it; `search_web` is context, not a substitute. General policy, not a weather keyword route.

## Verified

- Real path, configured tool model (deepseek-v4-pro), 1 run each: Paris weather → `weather_info`, 27°C, 14 s;
  multi-part (Tokyo weather + Microsoft price + √7921) → `weather_info` 25°C + stock + `compute`, complete, 11 s.
  Before: `search_web` or invented `get_weather`; temperature 0/3 on multi-part.
- `tests/unit/test_ollama_tool_wrapping.py` (new): 2 behaviour tests fail on the pre-fix provider, the control
  passes. Unit suite 992 passed / the same 4 pre-existing failures. `make smoke` passed. Handler exercised directly:
  Tokyo/New York/São Paulo metric + imperial, unknown place → failure.

## Cost / risk — read before relying on it

- Tool-call input: ~17k → ~26–29k tokens per call (the schemas are now really sent). Fewer calls per request were
  observed, but the net effect is not yet measured.
- **Broader regression NOT run** (owner decision, quota at ~78% of the week): every tool family's selection can
  shift now that schemas are visible. Run the 14-case evaluation when quota allows (SI-102).

## Breaking changes / migration

None in interfaces. Behaviour: tool selection on Ollama lanes changes (by design).
