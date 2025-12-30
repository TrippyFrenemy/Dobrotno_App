from sqlalchemy import Column, Integer, Date, Enum, ForeignKey, text, Time, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from src.users.models import UserRole
import enum
from datetime import datetime, time

# Импорт для регистрации модели TikTokBranch в SQLAlchemy до использования ForeignKey
from src.tiktok.branches.models import TikTokBranch  # noqa: F401


class ShiftLocation(str, enum.Enum):
    tiktok = "TikTok"
    other = "Other"


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        # Уникальность: одна смена на дату + точку
        UniqueConstraint('date', 'branch_id', name='uq_shift_date_branch'),
    )

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    location = Column(Enum(ShiftLocation), nullable=False)
    # TikTok точка (nullable для обратной совместимости, NULL = главная точка)
    branch_id = Column(Integer, ForeignKey("tiktok_branches.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(ForeignKey("users.id"))
    created_at = Column(Date, default=datetime.now, server_default=text("now()"))

    created_by_user = relationship("User", backref="created_shifts")
    branch = relationship("TikTokBranch", backref="shifts")


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
