#!/usr/bin/env python3
"""
FastAPI Backend Generator
==========================

Generates FastAPI application with all endpoints.

Author: RAICA Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class FastAPIGenerator:
    """Generates FastAPI backend code."""

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate FastAPI application files."""
        files_generated = []

        # Generate main.py
        main_file = self._generate_main(project_dir, architecture)
        files_generated.append(main_file)

        # Generate core config
        config_file = self._generate_config(project_dir, architecture)
        files_generated.append(config_file)

        # Generate API router
        router_file = self._generate_api_router(project_dir, architecture)
        files_generated.append(router_file)

        # Generate endpoint files
        endpoints = architecture.get("api_endpoints", [])
        endpoint_files = self._generate_endpoints(project_dir, endpoints)
        files_generated.extend(endpoint_files)

        # Generate schemas
        schema_files = self._generate_schemas(project_dir, architecture)
        files_generated.extend(schema_files)

        # Generate CRUD operations
        crud_files = self._generate_crud(project_dir, architecture)
        files_generated.extend(crud_files)

        logger.info(f"✅ Generated {len(files_generated)} FastAPI files")
        return files_generated

    def _generate_main(self, project_dir: Path, architecture: Dict[str, Any]) -> str:
        """Generate main FastAPI application."""
        project_name = architecture.get("project_name", "app")

        content = f'''"""
Main FastAPI Application
=========================

Entry point for {project_name}.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.api import api_router

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{{settings.API_V1_STR}}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    """Root endpoint."""
    return {{"message": "Welcome to {{settings.PROJECT_NAME}}"}}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {{"status": "healthy"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

        file_path = project_dir / "app" / "main.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _generate_config(self, project_dir: Path, architecture: Dict[str, Any]) -> str:
        """Generate core configuration."""
        project_name = architecture.get("project_name", "app")
        security = architecture.get("security", {})
        cors = security.get("cors", {})

        origins = cors.get("allow_origins", ["http://localhost:3000"])
        # Create comma-separated string for default value
        origins_default = ','.join(origins)

        content = f'''"""
Core Configuration
==================

Application settings and configuration.
"""

from typing import List, Union
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Project
    PROJECT_NAME: str = "{project_name}"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost/dbname"

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis (if using background workers or caching)
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS - can be comma-separated string or list
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default="{origins_default}"
    )

    @field_validator('CORS_ORIGINS', mode='after')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from comma-separated string to list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        # Don't try to parse strings as JSON
        env_parse_none_str='null'
    )


settings = Settings()
'''

        file_path = project_dir / "app" / "core" / "config.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _generate_api_router(self, project_dir: Path, architecture: Dict[str, Any]) -> str:
        """Generate main API router."""
        content = '''"""
API Router
==========

Main API router combining all endpoint routers.
"""

from fastapi import APIRouter
from app.api.endpoints import auth

api_router = APIRouter()

# Include endpoint routers
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])

# Add more routers here as generated
'''

        file_path = project_dir / "app" / "api" / "api.py"
        with open(file_path, 'w') as f:
            f.write(content)

        return str(file_path.relative_to(project_dir))

    def _generate_endpoints(self, project_dir: Path, endpoints: List[Dict[str, Any]]) -> List[str]:
        """Generate endpoint files (placeholder - auth endpoints generated separately)."""
        # Auth endpoints are generated by AuthGenerator
        # Other endpoints would be generated here
        return []

    def _generate_schemas(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate Pydantic schemas."""
        files = []

        # Generate base schemas
        content = '''"""
Base Schemas
============

Base Pydantic models for request/response.
"""

from typing import Optional
from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Standard message response."""
    message: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
'''

        file_path = project_dir / "app" / "schemas" / "base.py"
        with open(file_path, 'w') as f:
            f.write(content)
        files.append(str(file_path.relative_to(project_dir)))

        return files

    def _generate_crud(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate CRUD operations."""
        files = []

        # Generate base CRUD
        content = '''"""
Base CRUD Operations
====================

Generic CRUD operations for database models.
"""

from typing import Generic, TypeVar, Type, Optional, List
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """Base CRUD operations."""

    def __init__(self, model: Type[ModelType]):
        self.model = model

    def get(self, db: Session, id: int) -> Optional[ModelType]:
        """Get by ID."""
        return db.query(self.model).filter(self.model.id == id).first()

    def get_multi(self, db: Session, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Get multiple records."""
        return db.query(self.model).offset(skip).limit(limit).all()

    def create(self, db: Session, obj_in: CreateSchemaType) -> ModelType:
        """Create new record."""
        obj_data = obj_in.dict()
        db_obj = self.model(**obj_data)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update(self, db: Session, db_obj: ModelType, obj_in: UpdateSchemaType) -> ModelType:
        """Update record."""
        obj_data = obj_in.dict(exclude_unset=True)
        for field in obj_data:
            setattr(db_obj, field, obj_data[field])
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, id: int) -> Optional[ModelType]:
        """Delete record."""
        obj = db.query(self.model).get(id)
        if obj:
            db.delete(obj)
            db.commit()
        return obj
'''

        file_path = project_dir / "app" / "crud" / "base.py"
        with open(file_path, 'w') as f:
            f.write(content)
        files.append(str(file_path.relative_to(project_dir)))

        return files
