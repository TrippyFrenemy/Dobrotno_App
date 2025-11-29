from sqlalchemy import Column, Integer, Date, Enum, ForeignKey, text, Time, Numeric
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from src.users.models import UserRole
import enum
from datetime import datetime, time


class ShiftLocation(str, enum.Enum):
    tiktok = "TikTok"
    other = "Other"


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    location = Column(Enum(ShiftLocation), nullable=False)
    created_by = Column(ForeignKey("users.id"))
    created_at = Column(Date, default=datetime.now, server_default=text("now()"))

    created_by_user = relationship("User", backref="created_shifts")


class ShiftAssignment(Base):
    __tablename__ = "shift_assignments"

    id = Column(Integer, primary_key=True)
    shift_id = Column(ForeignKey("shifts.id"), nullable=False)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    created_by = Column(ForeignKey("users.id"), nullable=False)
    created_at = Column(Date, default=datetime.now, server_default=text("now()"))
    
    start_time = Column(Time, default=time(10, 0))
    end_time = Column(Time, default=time(20, 0))
    salary = Column(Numeric(10, 2), default=0.0)

    shift = relationship("Shift", backref="assignments")
    user = relationship("User", foreign_keys=[user_id])
    created_by_user = relationship("User", foreign_keys=[created_by])
