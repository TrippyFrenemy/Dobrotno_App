from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from src.database import Base


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class StoreShiftRecord(Base):
    __tablename__ = "store_shift_records"

    id = Column(Integer, primary_key=True)
    store_id = Column(ForeignKey("stores.id"), nullable=False)
    date = Column(Date, nullable=False)
    cash = Column(Numeric(10, 2), nullable=False, default=0)
    cash_on_hand = Column(Numeric(10, 2), nullable=False, default=0)
    terminal = Column(Numeric(10, 2), nullable=False, default=0)
    salary_expenses = Column(Numeric(10, 2), nullable=False, default=0)

    store = relationship("Store", backref="records")
    employees = relationship("StoreShiftEmployee", back_populates="shift")


class StoreShiftEmployee(Base):
    __tablename__ = "store_shift_employees"

    id = Column(Integer, primary_key=True)
    shift_id = Column(ForeignKey("store_shift_records.id"), nullable=False)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    is_warehouse = Column(Boolean, default=False, nullable=False)

    shift = relationship("StoreShiftRecord", back_populates="employees")
    user = relationship("User")
    