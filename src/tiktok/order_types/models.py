from sqlalchemy import Boolean, Column, Integer, Numeric, String
from src.database import Base, metadata


class OrderType(Base):
    """Модель типа заказа TikTok (Парфюм, Амазон, Лидл и т.д.)"""

    __tablename__ = "order_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    commission_percent = Column(Numeric(10, 2), default=100.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
