from decimal import Decimal
from pydantic import BaseModel, Field


class OrderTypeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    commission_percent: Decimal = Field(default=Decimal("0.0"), ge=0, le=100)
    is_active: bool = True


class OrderTypeCreate(OrderTypeBase):
    pass


class OrderTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    commission_percent: Decimal | None = Field(None, ge=0, le=100)
    is_active: bool | None = None


class OrderTypeRead(OrderTypeBase):
    id: int

    class Config:
        from_attributes = True
