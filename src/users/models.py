from datetime import datetime, time
from enum import Enum

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum as SqlEnum, Numeric, Time
from sqlalchemy.orm import relationship
from src.database import Base, metadata

class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    COFFEE = "coffee"
    STORE_WORKER = "store_worker"
    WAREHOUSE_WORKER = "warehouse_worker"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(SqlEnum(UserRole), nullable=False, default=UserRole.EMPLOYEE)
    default_rate = Column(Numeric(10, 2), default=0.0)
    default_percent = Column(Numeric(10, 2), default=1.0)

    shift_start = Column(Time, default=time(10, 0))
    shift_end = Column(Time, default=time(20, 0))

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
