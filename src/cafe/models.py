from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey, DateTime, text
from sqlalchemy.orm import relationship
from src.database import Base, metadata
from datetime import datetime

class CoffeeShop(Base):
    __tablename__ = "coffee_shops"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    records = relationship("CoffeeShiftRecord", back_populates="shop")


class CoffeeShiftRecord(Base):
    __tablename__ = "coffee_shift_records"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    
    total_cash = Column(Numeric(10, 2), nullable=False)  # суммарная касса
    terminal = Column(Numeric(10, 2), nullable=False)
    cash = Column(Numeric(10, 2), nullable=False)
    expenses = Column(Numeric(10, 2), nullable=False)

    shop_id = Column(ForeignKey("coffee_shops.id"), nullable=False)
    barista_id = Column(ForeignKey("users.id"), nullable=False)

    shop = relationship("CoffeeShop", back_populates="records")
    barista = relationship("User")

    created_at = Column(DateTime, default=datetime.now, server_default=text("now()"))

