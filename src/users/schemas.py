from pydantic import BaseModel, EmailStr
from enum import Enum
from decimal import Decimal
from datetime import datetime

class RoleEnum(str, Enum):
    admin = "admin"
    manager = "manager"
    employee = "employee"

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: RoleEnum
    default_rate: Decimal = 0.0

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: RoleEnum
    default_rate: Decimal
    created_at: datetime

    class Config:
        orm_mode = True
        