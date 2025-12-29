from datetime import datetime
from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, DateTime
from sqlalchemy.orm import relationship
from src.database import Base


class TikTokBranch(Base):
    """TikTok точка/филиал"""

    __tablename__ = "tiktok_branches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)  # "TikTok Центр", "TikTok Левый берег"
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)  # Главная точка (для старых данных)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    user_assignments = relationship("UserBranchAssignment", back_populates="branch", cascade="all, delete-orphan")
    order_type_assignments = relationship("OrderTypeBranch", back_populates="branch", cascade="all, delete-orphan")


class UserBranchAssignment(Base):
    """Привязка пользователя к TikTok точке с индивидуальными настройками"""

    __tablename__ = "user_branch_assignments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("tiktok_branches.id", ondelete="CASCADE"), nullable=False, index=True)

    # Индивидуальный процент для этого пользователя на этой точке
    # NULL = использовать user.default_percent
    custom_percent = Column(Numeric(10, 2), nullable=True)

    # Является ли эта точка основной для пользователя
    is_primary = Column(Boolean, default=False, nullable=False)

    # Разрешён ли доступ к этой точке
    is_allowed = Column(Boolean, default=True, nullable=False)

    # Связи
    user = relationship("User", backref="branch_assignments")
    branch = relationship("TikTokBranch", back_populates="user_assignments")


class OrderTypeBranch(Base):
    """Привязка типа заказа к TikTok точке"""

    __tablename__ = "order_type_branches"

    id = Column(Integer, primary_key=True, index=True)
    order_type_id = Column(Integer, ForeignKey("order_types.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("tiktok_branches.id", ondelete="CASCADE"), nullable=False, index=True)

    # Можно ли использовать этот тип заказа на этой точке
    is_allowed = Column(Boolean, default=True, nullable=False)

    # Связи
    order_type = relationship("OrderType", backref="branch_assignments")
    branch = relationship("TikTokBranch", back_populates="order_type_assignments")
