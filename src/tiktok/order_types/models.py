from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from src.database import Base, metadata


class OrderType(Base):
    """Модель типа заказа TikTok (Парфюм, Амазон, Лидл и т.д.)"""

    __tablename__ = "order_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    commission_percent = Column(Numeric(10, 2), default=100.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    # Процент для сотрудников по умолчанию для этого типа заказа
    # NULL = использовать user.default_percent (обратная совместимость)
    default_employee_percent = Column(Numeric(10, 2), nullable=True)
    # Учитывать ли этот тип заказа в расчёте ЗП сотрудников (Employee)
    # True = включать в кассу для сотрудников, False = только для менеджеров
    include_in_employee_salary = Column(Boolean, default=True, nullable=False)

    # Связь с индивидуальными настройками пользователей
    user_settings = relationship("UserOrderTypeSetting", back_populates="order_type", cascade="all, delete-orphan")


class UserOrderTypeSetting(Base):
    """Индивидуальные настройки типа заказа для конкретного пользователя"""

    __tablename__ = "user_order_type_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_type_id = Column(Integer, ForeignKey("order_types.id", ondelete="CASCADE"), nullable=False, index=True)

    # Индивидуальный процент для этого пользователя и типа заказа
    # NULL = использовать order_type.default_employee_percent или user.default_percent
    custom_percent = Column(Numeric(10, 2), nullable=True)

    # Разрешён ли этот тип заказа для пользователя
    # False = тип не отображается в форме создания заказа
    is_allowed = Column(Boolean, default=True, nullable=False)

    # Связи
    user = relationship("User", backref="order_type_settings")
    order_type = relationship("OrderType", back_populates="user_settings")
