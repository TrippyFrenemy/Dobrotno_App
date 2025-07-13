from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from src.database import Base, metadata

class Return(Base):
    __tablename__ = "returnings"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String, nullable=True)
    created_by = Column(ForeignKey("users.id"))

    created_by_user = relationship("User", backref="returnings", lazy="joined")
