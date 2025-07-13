from pydantic import BaseModel
from datetime import date
from decimal import Decimal

class OrderCreate(BaseModel):
    phone_number: str
    date: date
    amount: Decimal
