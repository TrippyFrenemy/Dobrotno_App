from sqlalchemy import Column, Index, Integer, Date, Enum, ForeignKey, Numeric, DateTime, Boolean, text
from sqlalchemy.orm import relationship
from datetime import datetime
from src.database import Base, metadata
import enum


class RoleType(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"
    STORE_WORKER = "store_worker"
    WAREHOUSE_WORKER = "warehouse_worker"

class Location(str, enum.Enum):
    TikTok = "TikTok"
    Store = "Store"
    Other  = "Other"


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (Index("ix_payouts_date_user_id", "date", "user_id"),)
    
    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)  # за какой день
    location = Column(Enum(Location, name="location_enum"), nullable=False)
    role_type = Column(Enum(RoleType), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    paid_at = Column(DateTime, default=datetime.now)
    is_manual = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("now()"), default=datetime.now)

    user = relationship("User", backref="payouts")
