"""
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
