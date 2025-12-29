#!/usr/bin/env python3
"""Frontend Generator - HTML templates with Alpine.js + Tailwind"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class FrontendGenerator:
    """Generates frontend HTML templates."""

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        files = []
        pages = architecture.get("frontend", {}).get("pages", [])

        # Generate base template
        base_file = project_dir / "app" / "templates" / "base.html"
        with open(base_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}App{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body class="bg-gray-100">
    <nav class="bg-white shadow-lg">
        <div class="max-w-7xl mx-auto px-4">
            <div class="flex justify-between h-16">
                <div class="flex items-center">
                    <span class="text-xl font-bold">App</span>
                </div>
            </div>
        </div>
    </nav>
    <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
''')
        files.append(str(base_file.relative_to(project_dir)))

        # Generate index.html
        index_file = project_dir / "app" / "templates" / "index.html"
        with open(index_file, 'w') as f:
            f.write('''{% extends "base.html" %}
{% block title %}Home{% endblock %}
{% block content %}
<div class="bg-white shadow rounded-lg p-6" x-data="{ message: 'Welcome to the app!' }">
    <h1 class="text-3xl font-bold mb-4" x-text="message"></h1>
    <p class="text-gray-600">This is a generated application.</p>
</div>
{% endblock %}
''')
        files.append(str(index_file.relative_to(project_dir)))

        logger.info(f"✅ Generated {len(files)} frontend files")
        return files
