"""config_version 2 — the LLM admin API's settings (RAICA v1.0.0.340): `admin_ui` (which config nodes are not legs,
and the labels the NewX admin page shows) and `offered_models` (the models the admin offers to bots, empty).

Both are ADDITIONS: the migrator adds them from the defaults to every site file; no existing value moves or changes.
"""
VERSION = 2
MOVES = {}
REMOVES = []
