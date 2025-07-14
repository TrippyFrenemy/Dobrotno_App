from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from src.database import Base, metadata

class UserLog(Base):
    __tablename__ = "user_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    path = Column(String, nullable=True)

    user = relationship("User", backref="logs")
