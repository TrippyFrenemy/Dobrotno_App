from pydantic import BaseModel, EmailStr
from enum import Enum
from decimal import Decimal
from datetime import datetime, time

class RoleEnum(str, Enum):
    admin = "admin"
    manager = "manager"
    employee = "employee"

class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: RoleEnum
    default_rate: Decimal = 0.0
    shift_start: time | None = None
    shift_end: time | None = None
    can_take_vacation: bool = False

class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: RoleEnum
    default_rate: Decimal
    shift_start: time | None
    shift_end: time | None
    can_take_vacation: bool
    created_at: datetime

    class Config:
        orm_mode = True
