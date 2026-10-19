"""config_version 1 — the baseline (RAICA v1.0.0.336): llm_config.yaml becomes site-owned.

No structural change: this version only starts the numbering. The live file that existed on each installation
(production, developer machines) was a byte-identical copy of the tracked file at this release, so it becomes the
site's file with no value change. utils/config_migrate.py documents the rules.
"""
VERSION = 1
MOVES = {}       # {'old.dotted.path': 'new.dotted.path'} — carries the site's CURRENT value
REMOVES = []     # ['dotted.path'] — only in the release whose code no longer reads the key
