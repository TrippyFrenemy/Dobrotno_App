from pydantic import BaseModel, field_validator, model_validator
from datetime import date as date_, datetime
from decimal import Decimal


class OrderTypeItem(BaseModel):
    """Single order type item with amount"""
    order_type_id: int
    amount: Decimal

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        return v


class OrderCreate(BaseModel):
    phone_number: str
    date: date_
    amount: Decimal
    order_types: list[OrderTypeItem]

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Order amount must be positive')
        return v

    @field_validator('order_types')
    @classmethod
    def validate_order_types_not_empty(cls, v):
        if not v or len(v) == 0:
            raise ValueError('Order must have at least one type')
        return v

    @model_validator(mode='after')
    def validate_amounts_sum(self):
        """Sum of all type amounts must equal total order amount"""
        total_types_amount = sum(ot.amount for ot in self.order_types)

        # Use tolerance for floating point comparison
        if abs(total_types_amount - self.amount) > Decimal('0.01'):
            raise ValueError(
                f'Sum of type amounts ({total_types_amount}) must equal order amount ({self.amount})'
            )

        # Check for duplicate types
        type_ids = [ot.order_type_id for ot in self.order_types]
        if len(type_ids) != len(set(type_ids)):
            raise ValueError('Order cannot have duplicate types')

        return self


class OrderUpdate(BaseModel):
    """Update order schema"""
    phone_number: str | None = None
    date: date_ | None = None # type: ignore
    amount: Decimal | None = None
    order_types: list[OrderTypeItem] | None = None

    @model_validator(mode='after')
    def validate_amounts_sum(self):
        """If updating types - validate sum"""
        if self.order_types is not None and self.amount is not None:
            total_types_amount = sum(ot.amount for ot in self.order_types)
            if abs(total_types_amount - self.amount) > Decimal('0.01'):
                raise ValueError(
                    f'Sum of type amounts ({total_types_amount}) must equal order amount ({self.amount})'
                )

            # Check for duplicate types
            type_ids = [ot.order_type_id for ot in self.order_types]
            if len(type_ids) != len(set(type_ids)):
                raise ValueError('Order cannot have duplicate types')

        return self


class OrderOrderTypeRead(BaseModel):
    """Order type detail for reading"""
    id: int
    order_type_id: int
    amount: Decimal

    class Config:
        from_attributes = True


class OrderRead(BaseModel):
    """Order read schema"""
    id: int
    phone_number: str
    date: date_
    amount: Decimal
    created_at: datetime
    created_by: int
    order_types_detail: list[OrderOrderTypeRead]
    is_legacy_order: bool

    class Config:
        from_attributes = True
