"""
User Model
==========

SQLAlchemy model for users table.
"""

from sqlalchemy import Column
from sqlalchemy.orm import relationship
from sqlalchemy import Boolean, DateTime, String, UUID
from sqlalchemy import ForeignKey
from app.db.base import Base


class User(Base):
    """
    Application user accounts.
    """
    __tablename__ = "users"

    id = Column(UUID, primary_key=True, nullable=False, default="uuid_generate_v4()")
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default="func.now()")
    updated_at = Column(DateTime, nullable=False, default="func.now()")

    # Relationships
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id})>"
