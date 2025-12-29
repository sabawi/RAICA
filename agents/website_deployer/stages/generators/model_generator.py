#!/usr/bin/env python3
"""
SQLAlchemy Model Generator
===========================

Generates SQLAlchemy ORM models from database schema specification.

Author: RAICA Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelGenerator:
    """Generates SQLAlchemy models from architecture specification."""

    # SQLAlchemy type mapping
    TYPE_MAPPING = {
        "Integer": "Integer",
        "String": "String",
        "Text": "Text",
        "Boolean": "Boolean",
        "DateTime": "DateTime",
        "Date": "Date",
        "Time": "Time",
        "Float": "Float",
        "Numeric": "Numeric",
        "JSON": "JSON",
        "UUID": "UUID",
        "LargeBinary": "LargeBinary",
    }

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """
        Generate SQLAlchemy model files.

        Args:
            project_dir: Project root directory
            architecture: Architecture specification

        Returns:
            List of generated file paths
        """
        files_generated = []

        schema = architecture.get("database_schema", {})
        tables = schema.get("tables", [])
        relationships = schema.get("relationships", [])

        if not tables:
            logger.warning("No database tables to generate")
            return files_generated

        # Generate base.py
        base_file = self._generate_base(project_dir)
        files_generated.append(base_file)

        # Generate individual model files
        for table in tables:
            model_file = self._generate_model(project_dir, table, relationships)
            files_generated.append(model_file)

        # Generate models/__init__.py
        init_file = self._generate_models_init(project_dir, tables)
        files_generated.append(init_file)

        logger.info(f"✅ Generated {len(files_generated)} model files")
        return files_generated

    def _generate_base(self, project_dir: Path) -> str:
        """Generate database base configuration."""
        content = '''"""
Database Base Configuration
============================

SQLAlchemy declarative base and session management.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create declarative base
Base = declarative_base()


def get_db():
    """
    Get database session.

    Yields database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

        file_path = project_dir / "app" / "db" / "base.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _generate_model(
        self,
        project_dir: Path,
        table: Dict[str, Any],
        relationships: List[Dict[str, Any]]
    ) -> str:
        """Generate individual model file."""
        table_name = table["name"]
        model_name = self._table_to_model_name(table_name)

        # Generate imports
        imports = set(['from sqlalchemy import Column'])
        column_types = set()

        # Collect column types
        for col in table.get("columns", []):
            col_type = col["type"]
            if col_type in self.TYPE_MAPPING:
                column_types.add(self.TYPE_MAPPING[col_type])

        # Add relationship import if needed
        model_relationships = [r for r in relationships if r.get("model") == model_name]
        if model_relationships:
            imports.add('from sqlalchemy.orm import relationship')

        # Build imports string
        imports_str = '\n'.join(sorted(imports))
        types_str = ', '.join(sorted(column_types))

        content = f'''"""
{model_name} Model
{'=' * (len(model_name) + 6)}

SQLAlchemy model for {table_name} table.
"""

{imports_str}
from sqlalchemy import {types_str}
from sqlalchemy import ForeignKey
from app.db.base import Base


class {model_name}(Base):
    """
    {table.get('description', f'{model_name} model')}.
    """
    __tablename__ = "{table_name}"

'''

        # Generate columns
        for col in table.get("columns", []):
            col_def = self._generate_column_definition(col)
            content += f"    {col_def}\n"

        # Generate relationships
        if model_relationships:
            content += "\n    # Relationships\n"
            for rel in model_relationships:
                rel_def = self._generate_relationship_definition(rel)
                content += f"    {rel_def}\n"

        content += "\n"
        content += f'''    def __repr__(self):
        return f"<{model_name}(id={{self.id}})>"
'''

        # Write file
        file_path = project_dir / "app" / "models" / f"{table_name}.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _generate_column_definition(self, col: Dict[str, Any]) -> str:
        """Generate SQLAlchemy column definition."""
        col_name = col["name"]
        col_type = col["type"]

        # Get SQLAlchemy type
        sa_type = self.TYPE_MAPPING.get(col_type, "String")

        # Build column arguments
        args = []

        # Add max_length for String types
        if sa_type == "String" and "max_length" in col:
            sa_type = f"String({col['max_length']})"

        # Add ForeignKey if present
        if "foreign_key" in col:
            fk = col["foreign_key"]
            args.append(f'ForeignKey("{fk["references"]}", ondelete="{fk.get("ondelete", "CASCADE")}")')

        # Add primary_key
        if col.get("primary_key"):
            args.append("primary_key=True")

        # Add nullable
        if "nullable" in col:
            args.append(f"nullable={str(col['nullable'])}")

        # Add unique
        if col.get("unique"):
            args.append("unique=True")

        # Add index
        if col.get("indexed"):
            args.append("index=True")

        # Add default
        if "default" in col:
            default_val = col["default"]
            if isinstance(default_val, str):
                args.append(f'default="{default_val}"')
            elif isinstance(default_val, bool):
                args.append(f'default={default_val}')
            else:
                args.append(f'default={default_val}')

        # Build column definition
        args_str = ", ".join(args)
        return f'{col_name} = Column({sa_type}, {args_str})'

    def _generate_relationship_definition(self, rel: Dict[str, Any]) -> str:
        """Generate SQLAlchemy relationship definition."""
        rel_name = rel["relationship_name"]
        target_model = rel["target_model"]
        back_populates = rel.get("back_populates")

        args = [f'"{target_model}"']

        if back_populates:
            args.append(f'back_populates="{back_populates}"')

        if rel.get("cascade"):
            args.append(f'cascade="{rel["cascade"]}"')

        args_str = ", ".join(args)
        return f'{rel_name} = relationship({args_str})'

    def _generate_models_init(self, project_dir: Path, tables: List[Dict[str, Any]]) -> str:
        """Generate models/__init__.py with all model imports."""
        content = '''"""
Models Package
==============

All SQLAlchemy models.
"""

from app.db.base import Base

'''

        # Import all models
        for table in tables:
            table_name = table["name"]
            model_name = self._table_to_model_name(table_name)
            content += f"from app.models.{table_name} import {model_name}\n"

        # Add __all__
        content += "\n__all__ = [\n"
        content += '    "Base",\n'
        for table in tables:
            model_name = self._table_to_model_name(table["name"])
            content += f'    "{model_name}",\n'
        content += "]\n"

        file_path = project_dir / "app" / "models" / "__init__.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _table_to_model_name(self, table_name: str) -> str:
        """Convert table name to model name (PascalCase)."""
        # Remove plural 's' and convert to PascalCase
        if table_name.endswith('s') and table_name != 'status':
            singular = table_name[:-1]
        else:
            singular = table_name

        # Convert snake_case to PascalCase
        return ''.join(word.capitalize() for word in singular.split('_'))
