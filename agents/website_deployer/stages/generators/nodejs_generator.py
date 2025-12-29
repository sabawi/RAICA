#!/usr/bin/env python3
"""
Node.js Code Generator for Website Deployer Agent
==============================================

Generates production-ready Node.js code from architecture specifications.

Author: RAICA Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, List
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class NodeJSGenerator:
    """
    Generates complete Node.js application code from architecture specification.
    """

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """
        Generate Node.js backend code.

        Args:
            project_dir: The root directory of the project.
            architecture: The architecture specification.

        Returns:
            A list of generated files.
        """
        logger.info("Generating Node.js code...")
        files_generated = []

        # Create basic Node.js project structure
        self._create_directory_structure(project_dir)

        # Generate package.json
        package_json_path = self._generate_package_json(project_dir, architecture)
        files_generated.append(str(package_json_path))

        # Generate index.js
        index_js_path = self._generate_index_js(project_dir)
        files_generated.append(str(index_js_path))

        return files_generated

    def _create_directory_structure(self, project_dir: Path):
        """Create a basic Node.js project structure."""
        directories = [
            "src/api/routes",
            "src/api/controllers",
            "src/models",
            "src/config",
            "public"
        ]
        for dir_path in directories:
            (project_dir / dir_path).mkdir(parents=True, exist_ok=True)

    def _generate_package_json(self, project_dir: Path, architecture: Dict[str, Any]) -> Path:
        """Generates a package.json file."""
        project_name = architecture.get("project_name", "my-project")
        package_data = {
            "name": project_name.lower().replace(' ', '-'),
            "version": "1.0.0",
            "description": architecture.get("description", ""),
            "main": "src/index.js",
            "scripts": {
                "start": "node src/index.js",
                "test": "echo \"Error: no test specified\" && exit 1"
            },
            "dependencies": {
                "express": "^4.17.1"
            },
            "devDependencies": {},
            "author": "",
            "license": "ISC"
        }

        package_json_path = project_dir / "package.json"
        with open(package_json_path, 'w') as f:
            json.dump(package_data, f, indent=4)

        return package_json_path

    def _generate_index_js(self, project_dir: Path) -> Path:
        """Generates a src/index.js file."""
        index_js_content = """const express = require('express');
const app = express();
const port = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.send('<h1>Hello, World!</h1>');
});

app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});
"""
        index_js_path = project_dir / "src/index.js"
        with open(index_js_path, 'w') as f:
            f.write(index_js_content)

        return index_js_path
