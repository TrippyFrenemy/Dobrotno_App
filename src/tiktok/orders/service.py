"""Business logic for orders"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from sqlalchemy.orm import joinedload
from decimal import Decimal
from datetime import date

from src.tiktok.orders.models import Order, OrderOrderType
from src.tiktok.orders.schemas import OrderCreate, OrderTypeItem
from src.tiktok.order_types.models import OrderType


async def check_duplicates(
    session: AsyncSession,
    phone_number: str,
    date_: date,
    amount: Decimal,
    order_types: list[OrderTypeItem],
    exclude_order_id: int = None
) -> dict:
    """
    Check for duplicate orders

    Returns:
        {
            "exact_duplicate": Order | None,  # Exact duplicate
            "similar_orders": list[Order]     # Similar orders (same phone, date, amount but different types)
        }
    """
    # Find orders with same phone, date, amount
    filters = [
        Order.phone_number == phone_number,
        Order.date == date_,
        Order.amount == amount
    ]

    # Exclude current order when editing
    if exclude_order_id:
        filters.append(Order.id != exclude_order_id)

    stmt = select(Order).where(and_(*filters)).options(
        joinedload(Order.order_types_detail).joinedload(OrderOrderType.order_type),
        joinedload(Order.created_by_user),
        joinedload(Order.order_type)  # For legacy orders
    )
    result = await session.execute(stmt)
    potential_duplicates = result.scalars().unique().all()

    if not potential_duplicates:
        return {"exact_duplicate": None, "similar_orders": []}

    # Create dict of new types for comparison
    new_types_dict = {
        ot.order_type_id: ot.amount
        for ot in order_types
    }

    exact_duplicate = None
    similar_orders = []

    for existing_order in potential_duplicates:
        # Create dict of existing types
        if existing_order.is_legacy_order:
            # Legacy order with single type_id
            existing_types_dict = {
                existing_order.type_id: existing_order.amount
            } if existing_order.type_id else {}
        else:
            # New order with multiple types
            existing_types_dict = {
                oot.order_type_id: oot.amount
                for oot in existing_order.order_types_detail
            }

        # Check for exact match
        if existing_types_dict == new_types_dict:
            exact_duplicate = existing_order
        else:
            # Similar order (same amount, but different types)
            similar_orders.append(existing_order)

    return {
        "exact_duplicate": exact_duplicate,
        "similar_orders": similar_orders
    }


async def create_order(
    session: AsyncSession,
    order_data: OrderCreate,
    user_id: int
) -> Order:
    """Create order with multiple types"""

    # Validate that all types exist and are active
    type_ids = [ot.order_type_id for ot in order_data.order_types]
    stmt = select(OrderType).where(
        and_(
            OrderType.id.in_(type_ids),
            OrderType.is_active == True
        )
    )
    result = await session.execute(stmt)
    existing_types = result.scalars().all()

    if len(existing_types) != len(type_ids):
        raise ValueError("Some order types are invalid or inactive")

    # Create order
    new_order = Order(
        phone_number=order_data.phone_number,
        date=order_data.date,
        amount=order_data.amount,
        created_by=user_id,
        type_id=None  # No longer used
    )
    session.add(new_order)
    await session.flush()  # Get order ID

    # Create order-type relationships
    for ot_data in order_data.order_types:
        order_type_link = OrderOrderType(
            order_id=new_order.id,
            order_type_id=ot_data.order_type_id,
            amount=ot_data.amount
        )
        session.add(order_type_link)

    await session.commit()
    await session.refresh(new_order)

    return new_order


async def update_order(
    session: AsyncSession,
    order_id: int,
    phone_number: str,
    date_: date,
    amount: Decimal,
    order_types: list[OrderTypeItem]
) -> Order:
    """Update order with multiple types"""

    # Get order
    order = await session.get(Order, order_id)
    if not order:
        raise ValueError("Order not found")

    # Validate that all types exist and are active
    type_ids = [ot.order_type_id for ot in order_types]
    stmt = select(OrderType).where(
        and_(
            OrderType.id.in_(type_ids),
            OrderType.is_active == True
        )
    )
    result = await session.execute(stmt)
    existing_types = result.scalars().all()

    if len(existing_types) != len(type_ids):
        raise ValueError("Some order types are invalid or inactive")

    # Update order fields
    order.phone_number = phone_number
    order.date = date_
    order.amount = amount
    order.type_id = None  # Clear legacy field

    # Delete existing order type relationships
    stmt = select(OrderOrderType).where(OrderOrderType.order_id == order_id)
    result = await session.execute(stmt)
    existing_links = result.scalars().all()
    for link in existing_links:
        await session.delete(link)

    # Create new order type relationships
    for ot_data in order_types:
        order_type_link = OrderOrderType(
            order_id=order.id,
            order_type_id=ot_data.order_type_id,
            amount=ot_data.amount
        )
        session.add(order_type_link)

    await session.commit()
    await session.refresh(order)

    return order
