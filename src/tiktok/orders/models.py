from sqlalchemy import Column, Index, Integer, String, Date, Numeric, ForeignKey, DateTime, text, UniqueConstraint
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime


class OrderOrderType(Base):
    """Связь заказа с типами (many-to-many) с распределением суммы"""
    __tablename__ = "order_order_types"
    __table_args__ = (
        UniqueConstraint('order_id', 'order_type_id', name='uq_order_order_type'),
        Index("ix_order_order_types_order_id", "order_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    order_type_id = Column(ForeignKey("order_types.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)  # Сумма для этого конкретного типа

    # Relationships
    order = relationship("Order", back_populates="order_order_types")
    order_type = relationship("OrderType")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_date_created_by", "date", "created_by"),)
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    phone_number = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))
    created_by = Column(ForeignKey("users.id"))
    type_id = Column(ForeignKey("order_types.id"), nullable=True)  # Оставляем для обратной совместимости

    created_by_user = relationship("User", backref="orders", lazy="joined")
    order_type = relationship("OrderType", foreign_keys=[type_id], lazy="joined")  # Старая схема
    order_order_types = relationship("OrderOrderType", back_populates="order", lazy="selectin", cascade="all, delete-orphan")  # Новая схема - selectin избегает дубликатов
