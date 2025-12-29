#!/usr/bin/env python3
"""Auth Generator - JWT authentication system"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class AuthGenerator:
    """Generates JWT authentication system."""

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        files = []

        # Generate JWT utilities
        jwt_file = project_dir / "app" / "core" / "security.py"
        with open(jwt_file, 'w') as f:
            f.write('''"""Security utilities for JWT and password hashing."""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash password."""
    return pwd_context.hash(password)
''')
        files.append(str(jwt_file.relative_to(project_dir)))

        # Generate auth endpoints
        auth_file = project_dir / "app" / "api" / "endpoints" / "auth.py"
        with open(auth_file, 'w') as f:
            f.write('''"""Authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.security import create_access_token, verify_password, get_password_hash
from app.db.base import get_db

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

@router.post("/register")
async def register(email: str, password: str, db: Session = Depends(get_db)):
    """Register new user."""
    # Implementation here
    return {"message": "User registered successfully"}

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login and get access token."""
    # Implementation here
    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}
''')
        files.append(str(auth_file.relative_to(project_dir)))

        logger.info(f"✅ Generated {len(files)} auth files")
        return files
