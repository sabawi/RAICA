"""
Task Model
==========

SQLAlchemy model for tasks table.
"""

from sqlalchemy import Column
from sqlalchemy.orm import relationship
from sqlalchemy import Boolean, Date, DateTime, String, Text, UUID
from sqlalchemy import ForeignKey
from app.db.base import Base


class Task(Base):
    """
    User's task items.
    """
    __tablename__ = "tasks"

    id = Column(UUID, primary_key=True, nullable=False, default="uuid_generate_v4()")
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    is_complete = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default="func.now()")
    updated_at = Column(DateTime, nullable=False, default="func.now()")

    # Relationships
    user = relationship("User", back_populates="tasks")

    def __repr__(self):
        return f"<Task(id={self.id})>"
