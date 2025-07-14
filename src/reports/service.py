from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.orders.models import Order
from src.returns.models import Return
from src.shifts.models import Shift, ShiftAssignment, ShiftLocation
from src.users.models import User, UserRole
from src.payouts.models import Payout


def get_half_month_periods(month: int, year: int):
    first_half = (date(year, month, 1), date(year, month, 15))
    if month == 12:
        end_of_month = date(year, 12, 31)
    else:
        end_of_month = date(year, month + 1, 1) - timedelta(days=1)
    second_half = (date(year, month, 16), end_of_month)
    return first_half, second_half


async def get_cash_and_returns(session: AsyncSession, target_date: date):
    # Касса (сумма заказов)
    orders_q = await session.execute(
        select(func.sum(Order.amount)).where(Order.date == target_date)
    )
    orders = orders_q.scalar() or Decimal("0.00")

    # Возвраты
    returns_q = await session.execute(
        select(func.sum(Return.amount)).where(Return.date == target_date)
    )
    returns = returns_q.scalar() or Decimal("0.00")

    return orders, returns


async def calc_daily_salary(session: AsyncSession, target_date: date, orders_amount: Decimal, returns_amount: Decimal):
    shifts_q = await session.execute(
        select(Shift)
        .where(Shift.date == target_date)
        .options(selectinload(Shift.assignments).selectinload(ShiftAssignment.user))
    )
    shifts = shifts_q.scalars().all()

    cashbox = orders_amount - returns_amount

    fixed = defaultdict(Decimal)
    percent = defaultdict(Decimal)

    for shift in shifts:
        assignments = shift.assignments
        employees = [a for a in assignments if a.user.role == UserRole.EMPLOYEE]

        # 💰 Сотрудники TikTok — % от кассы
        if shift.location == ShiftLocation.tiktok:
            # if len(employees) == 1:
            #     employee = employees[0]
            #     fixed[employee.user_id] += employee.user.default_rate
            #     percent[employee.user_id] += round(cashbox * employee.user.default_percent * 2 / 100, 2)
            # elif len(employees) == 2:
            for e in employees:
                fixed[e.user_id] += e.user.default_rate
                percent[e.user_id] += round(cashbox * e.user.default_percent / 100)

        # 💼 Сотрудники обычных локаций — ставка
        else:
            for a in employees:
                fixed[a.user_id] += round(a.user.default_rate, 2)

        # 👤 Создатель смены — админ или менеджер
    orders_q = await session.execute(
        select(Order.created_by, func.sum(Order.amount))
        .where(Order.date == target_date)
        .group_by(Order.created_by)
    )
    order_creators = orders_q.all()

    for user_id, total_amount in order_creators:
        user_q = await session.execute(select(User).where(User.id == user_id))
        user = user_q.scalar_one_or_none()
        if not user:
            continue
        if user.role in [UserRole.ADMIN, UserRole.MANAGER]:
            fixed[user.id] += user.default_rate
            percent[user.id] += round((total_amount - returns_amount) * user.default_percent / 100)

    return {
        "fixed": dict(fixed),
        "percent": dict(percent)
    }

async def get_monthly_report(session: AsyncSession, start: date, end: date):
    users_q = await session.execute(select(User))
    users = {u.id: u for u in users_q.scalars().all()}

    # Суммы заказов по дате и пользователю
    orders_q = await session.execute(
        select(Order.date, Order.created_by, func.sum(Order.amount))
        .where(Order.date >= start, Order.date <= end)
        .group_by(Order.date, Order.created_by)
    )
    orders_map = defaultdict(lambda: defaultdict(Decimal))
    for dt, uid, amount in orders_q.all():
        orders_map[dt][uid] += amount

    # Суммы возвратов по дате
    returns_q = await session.execute(
        select(Return.date, func.sum(Return.amount))
        .where(Return.date >= start, Return.date <= end)
        .group_by(Return.date)
    )
    returns_map = {dt: amount for dt, amount in returns_q.all()}

    # Все смены с назначениями
    shifts_q = await session.execute(
        select(Shift)
        .where(Shift.date >= start, Shift.date <= end)
        .options(selectinload(Shift.assignments).selectinload(ShiftAssignment.user))
    )
    shifts_by_date = defaultdict(list)
    for shift in shifts_q.scalars().all():
        shifts_by_date[shift.date].append(shift)

    # Единый проход по дням
    result = []
    fixed_total = defaultdict(Decimal)
    percent_total = defaultdict(Decimal)
    current = start

    while current <= end:
        shifts = shifts_by_date.get(current, [])
        day_orders = orders_map.get(current, {})
        returns = returns_map.get(current, Decimal("0.00"))
        total_orders = sum(day_orders.values())
        cashbox = total_orders - returns

        fixed = defaultdict(Decimal)
        percent = defaultdict(Decimal)
        employees = set()

        # Сотрудники по сменам
        for shift in shifts:
            assignments = [a for a in shift.assignments if a.user.role == UserRole.EMPLOYEE]
            employees.update(a.user_id for a in assignments)

            if shift.location == ShiftLocation.tiktok:
                for a in assignments:
                    fixed[a.user_id] += a.user.default_rate
                    percent[a.user_id] += round(cashbox * a.user.default_percent / 100)
            else:
                for a in assignments:
                    fixed[a.user_id] += round(a.user.default_rate)

        # Менеджеры/админы по заказам
        for uid, amount in day_orders.items():
            user = users.get(uid)
            if user and user.role in [UserRole.ADMIN, UserRole.MANAGER]:
                fixed[uid] += user.default_rate
                percent[uid] += round((amount - returns) * user.default_percent / 100)

        # Финальные суммы
        salary_by_user = {
            uid: fixed[uid] + percent[uid] for uid in set(fixed) | set(percent)
        }
        for uid in salary_by_user:
            fixed_total[uid] += fixed[uid]
            percent_total[uid] += percent[uid]

        result.append({
            "date": current,
            "orders": total_orders,
            "returns": returns,
            "cashbox": cashbox,
            "salary_by_user": salary_by_user,
            "salary_fixed_by_user": dict(fixed),
            "salary_percent_by_user": dict(percent),
            "employees": list(employees),
            "creators": list(day_orders.keys()),
        })

        current += timedelta(days=1)

    return result


async def get_payouts_for_period(session: AsyncSession, start: date, end: date):
    q = await session.execute(
        select(Payout.user_id, func.sum(Payout.amount))
        .where(and_(Payout.date >= start, Payout.date <= end))
        .group_by(Payout.user_id)
    )
    return dict(q.all())
