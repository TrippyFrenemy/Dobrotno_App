from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Date, Numeric, ForeignKey, Boolean, Time
from sqlalchemy.dialects.postgresql import JSONB
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
    changed_price = Column(Numeric(10, 2), nullable=False, default=0)
    discount = Column(Numeric(10, 2), nullable=False, default=0)
    promotion = Column(Numeric(10, 2), nullable=False, default=0)
    to_store = Column(Numeric(10, 2), nullable=False, default=0)
    refund = Column(Numeric(10, 2), nullable=False, default=0)
    service = Column(Numeric(10, 2), nullable=False, default=0)
    receipt = Column(Numeric(10, 2), nullable=False, default=0)
    expenses = Column(Numeric(10, 2), nullable=False, default=0)
    salary_expenses = Column(Numeric(10, 2), nullable=False, default=0)
    comments = Column(JSONB, nullable=False, default=dict)

    store = relationship("Store", backref="records")
    employees = relationship("StoreShiftEmployee", back_populates="shift")
    
    @property
    def expense_total(self) -> Numeric:
        return (self.to_store or 0) + (self.service or 0) + (self.expenses or 0)
    
    @property
    def cash_total(self) -> Numeric:
        return (self.cash or 0) - (self.changed_price or 0) - (self.discount or 0) - (self.refund or 0) + (self.receipt or 0)

class StoreShiftEmployee(Base):
    __tablename__ = "store_shift_employees"

    id = Column(Integer, primary_key=True)
    shift_id = Column(ForeignKey("store_shift_records.id"), nullable=False)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    is_warehouse = Column(Boolean, default=False, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    salary = Column(Numeric(10, 2), nullable=False, default=0)
    
    shift = relationship("StoreShiftRecord", back_populates="employees")
    user = relationship("User")
    

class StoreVacation(Base):
    __tablename__ = "store_vacations"

    id = Column(Integer, primary_key=True)
    store_id = Column(ForeignKey("stores.id"), nullable=False)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    store = relationship("Store", backref="vacations")
    user = relationship("User")
