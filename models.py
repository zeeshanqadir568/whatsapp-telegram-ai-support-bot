"""SQLAlchemy models for conversation history and lead capture.
"""

import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from database import Base


class Conversation(Base):
    """Stores conversation messages across WhatsApp, Telegram, and API channels."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    channel = Column(String(50), default="api", nullable=False)  # whatsapp, telegram, api
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Lead(Base):
    """Stores contact and intent details extracted during support interactions."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    channel = Column(String(50), default="api", nullable=False)
    name = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(100), nullable=True)
    intent = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
