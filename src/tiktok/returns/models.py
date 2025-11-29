from sqlalchemy import Column, Index, Integer, String, Date, Numeric, ForeignKey, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime

class Return(Base):
    __tablename__ = "returnings"
    __table_args__ = (Index("ix_returnings_date", "date"),)

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String, nullable=True)
    created_by = Column(ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))

    # Новые поля для штрафов
    order_id = Column(ForeignKey("orders.id"), nullable=True)  # Привязка к заказу (опционально)
    penalty_amount = Column(Numeric(10, 2), default=0.0, server_default='0.0', nullable=False)  # Сумма штрафа
    penalty_distribution = Column(JSONB, default=dict, server_default='{}', nullable=False)  # {user_id: amount}

    created_by_user = relationship("User", backref="returnings", lazy="joined")
    order = relationship("Order", backref="returns", lazy="joined")
