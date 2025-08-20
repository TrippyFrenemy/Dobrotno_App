from sqlalchemy import Column, Index, Integer, String, Date, Numeric, ForeignKey, DateTime, text
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_date_created_by", "date", "created_by"),)
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    phone_number = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))
    created_by = Column(ForeignKey("users.id"))
    
    created_by_user = relationship("User", backref="orders", lazy="joined")
    