from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey, DateTime, text
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime

class Return(Base):
    __tablename__ = "returnings"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String, nullable=True)
    created_by = Column(ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))

    created_by_user = relationship("User", backref="returnings", lazy="joined")
