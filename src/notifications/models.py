from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Enum as SqlEnum
from sqlalchemy.orm import relationship
from src.database import Base, metadata


class NotificationType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    SUCCESS = "success"
    ERROR = "error"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(SqlEnum(NotificationType), nullable=False, default=NotificationType.INFO)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    read_at = Column(DateTime, nullable=True)

    # Опциональная ссылка на связанный объект
    related_url = Column(String(500), nullable=True)

    # Relationship
    user = relationship("User", backref="notifications")
