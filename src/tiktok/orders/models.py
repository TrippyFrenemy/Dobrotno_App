from sqlalchemy import Column, Index, Integer, String, Date, Numeric, ForeignKey, DateTime, text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime


class OrderOrderType(Base):
    """Many-to-many relationship between orders and order types with amount per type"""
    __tablename__ = "order_order_types"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    order_type_id = Column(Integer, ForeignKey("order_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    # Relationships
    order = relationship("Order", back_populates="order_types_detail")
    order_type = relationship("OrderType")

    # Constraints
    __table_args__ = (
        UniqueConstraint('order_id', 'order_type_id', name='uq_order_type_per_order'),
        CheckConstraint('amount > 0', name='check_amount_positive'),
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_date_created_by", "date", "created_by"),)
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    phone_number = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))
    created_by = Column(ForeignKey("users.id"))
    type_id = Column(ForeignKey("order_types.id"), nullable=True)  # DEPRECATED: kept for backward compatibility

    # Relationships
    created_by_user = relationship("User", backref="orders", lazy="joined")
    order_type = relationship("OrderType", foreign_keys=[type_id], lazy="joined")  # DEPRECATED: for legacy orders

    # NEW: Many-to-many relationship through order_order_types
    order_types_detail = relationship(
        "OrderOrderType",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="joined"
    )

    @property
    def order_types(self):
        """Convenient access to order types"""
        return [oot.order_type for oot in self.order_types_detail]

    @property
    def is_legacy_order(self):
        """Check if this is a legacy order (created before multiple types feature)"""
        return len(self.order_types_detail) == 0 and self.type_id is not None
    