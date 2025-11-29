from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.tiktok.orders.models import Order
from src.tiktok.returns.models import Return
from src.tiktok.shifts.models import Shift, ShiftAssignment
from src.users.models import User, UserRole
from src.payouts.models import Payout, RoleType, Location


def get_half_month_periods(month: int, year: int):
    """Старая логика (для совместимости): 1-15, 16-конец месяца"""
    first_half = (date(year, month, 1), date(year, month, 15))
    if month == 12:
        end_of_month = date(year, 12, 31)
    else:
        end_of_month = date(year, month + 1, 1) - timedelta(days=1)
    second_half = (date(year, month, 16), end_of_month)
    return first_half, second_half


def get_weekly_periods(month: int, year: int):
    """Новая логика: 1-7, 8-14, 15-21, 22-последний день месяца"""
    # Определяем последний день месяца
    if month == 12:
        end_of_month = date(year, 12, 31)
    else:
        end_of_month = date(year, month + 1, 1) - timedelta(days=1)

    period1 = (date(year, month, 1), date(year, month, 7))
    period2 = (date(year, month, 8), date(year, month, 14))
    period3 = (date(year, month, 15), date(year, month, 21))
    period4 = (date(year, month, 22), end_of_month)

    return period1, period2, period3, period4


async def get_monthly_report(
    session: AsyncSession,
    start: date,
    end: date,
    current_user: User
):

    users_q = await session.execute(select(User))
    users = {u.id: u for u in users_q.scalars().all()}

    # Загружаем все заказы с типами для учета комиссии
    orders_q = await session.execute(
        select(Order)
        .where(Order.date >= start, Order.date <= end)
        .options(selectinload(Order.order_type))
    )
    all_orders = orders_q.scalars().all()

    # Загружаем все типы заказов для справочника
    from src.tiktok.order_types.models import OrderType
    types_q = await session.execute(select(OrderType))
    order_types = {t.id: t for t in types_q.scalars().all()}

    # Группируем заказы по дате и создателю
    orders_map = defaultdict(lambda: defaultdict(lambda: {'amount': Decimal('0'), 'orders': []}))
    for order in all_orders:
        orders_map[order.date][order.created_by]['amount'] += order.amount
        orders_map[order.date][order.created_by]['orders'].append(order)

    # Загружаем возвраты с штрафами
    returns_q = await session.execute(
        select(Return)
        .where(Return.date >= start, Return.date <= end)
    )
    all_returns = returns_q.scalars().all()

    # Группируем возвраты по дате
    returns_map = defaultdict(Decimal)
    penalties_map_by_date = defaultdict(lambda: defaultdict(lambda: Decimal('0')))

    for ret in all_returns:
        returns_map[ret.date] += ret.amount

        # Собираем штрафы по сотрудникам (штрафы привязаны к дате возврата)
        if ret.penalty_distribution:
            for user_id_str, penalty_amount in ret.penalty_distribution.items():
                penalties_map_by_date[ret.date][int(user_id_str)] += Decimal(str(penalty_amount))

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
    current = start

    while current <= end:
        shifts = shifts_by_date.get(current, [])
        day_orders = orders_map.get(current, {})
        returns = returns_map.get(current, Decimal("0.00"))
        total_orders = sum(order_data['amount'] for order_data in day_orders.values())
        cashbox = total_orders - returns

        # Статистика по типам заказов
        orders_by_type = defaultdict(lambda: {'amount': Decimal('0'), 'count': 0})
        if current_user.role != UserRole.MANAGER:
            for uid, order_data in day_orders.items():
                for order in order_data['orders']:
                    type_id = order.type_id
                    type_name = order_types[type_id].name if type_id and type_id in order_types else "Без типа"
                    orders_by_type[type_name]['amount'] += order.amount
                    orders_by_type[type_name]['count'] += 1

        # Статистика по создателям (менеджерам)
        # Для MANAGER этот блок скрываем полностью (таблица "💼 Касса по менеджерам" не отображается).
        orders_by_creator = {}
        if current_user.role != UserRole.MANAGER:
            for uid, order_data in day_orders.items():
                user = users.get(uid)
                if user:
                    orders_by_creator[uid] = {
                        'name': user.name,
                        'amount': order_data['amount'],
                        'count': len(order_data['orders'])
                    }

        fixed = defaultdict(Decimal)
        percent = defaultdict(Decimal)
        employee_details = []
        shift_id = shifts[0].id if shifts else None

        # Сотрудники по сменам
        for shift in shifts:
            assignments = [a for a in shift.assignments if a.user.role == UserRole.EMPLOYEE]
            
            if not assignments:
                continue

            if shift.location == Location.TikTok:
                ratios = {}
                total_ratio = Decimal("0")
                for a in assignments:
                    def_hours = (
                        datetime.combine(date.today(), a.user.shift_end)
                        - datetime.combine(date.today(), a.user.shift_start)
                    ).total_seconds() / 3600 or 1
                    work_hours = (
                        datetime.combine(date.today(), a.end_time)
                        - datetime.combine(date.today(), a.start_time)
                    ).total_seconds() / 3600
                    ratio = Decimal(work_hours) / Decimal(def_hours)
                    ratios[a.user_id] = ratio
                    total_ratio += ratio
                    fixed[a.user_id] += Decimal(a.salary)
                    employee_details.append(
                        {
                            "user_id": a.user_id,
                            "start_time": a.start_time,
                            "end_time": a.end_time,
                            "salary": a.salary,
                        }
                    )

                for a in assignments:
                    cashbox_perc = cashbox / len(employee_details)
                    percent[a.user_id] += round((cashbox_perc * a.user.default_percent) / 100)
            else:
                for a in assignments:
                    fixed[a.user_id] += Decimal(a.salary)
                    employee_details.append(
                        {
                            "user_id": a.user_id,
                            "start_time": a.start_time,
                            "end_time": a.end_time,
                            "salary": a.salary,
                        }
                    )

        # Менеджеры/админы по заказам с учетом комиссии типа
        for uid, order_data in day_orders.items():
            user = users.get(uid)
            if user and user.role in [UserRole.ADMIN, UserRole.MANAGER]:
                fixed[uid] += user.default_rate

                # Рассчитываем процент с учетом комиссии каждого типа заказа
                total_commission_amount = Decimal('0')
                for order in order_data['orders']:
                    # Комиссия типа заказа (по умолчанию 100% если тип не указан)
                    commission = order.order_type.commission_percent if order.order_type else Decimal('100')
                    # Прибыль от заказа с учетом комиссии
                    order_profit = order.amount * commission / 100
                    total_commission_amount += order_profit

                # Вычитаем возвраты пропорционально и применяем процент менеджера
                manager_profit = total_commission_amount - returns
                percent[uid] += round(manager_profit * user.default_percent / 100)

        # Финальные суммы с вычетом штрафов
        salary_by_user = {}
        salary_fixed_by_user = {}
        salary_percent_by_user = {}
        penalties_by_user = {}

        day_penalties = penalties_map_by_date.get(current, {})

        for uid in set(fixed) | set(percent) | set(day_penalties):
            if current_user.role == UserRole.MANAGER and users.get(uid) and users.get(uid).role == UserRole.ADMIN:
                continue

            # Вычитаем штрафы из зарплаты
            penalty = day_penalties.get(uid, Decimal('0'))
            total_salary = fixed[uid] + percent[uid] - penalty

            salary_by_user[uid] = total_salary
            salary_fixed_by_user[uid] = fixed[uid]
            salary_percent_by_user[uid] = percent[uid]
            penalties_by_user[uid] = penalty

        result.append({
            "date": current,
            "orders": total_orders,
            "returns": returns,
            "cashbox": cashbox,
            "salary_by_user": salary_by_user,
            "salary_fixed_by_user": salary_fixed_by_user,
            "salary_percent_by_user": salary_percent_by_user,
            "penalties_by_user": penalties_by_user,
            "employees": employee_details,
            "creators": list(day_orders.keys()),
            "shift_id": shift_id,
            "orders_by_type": dict(orders_by_type),
            "orders_by_creator": orders_by_creator,
        })

        current += timedelta(days=1)

    return result


async def get_payouts_for_period(session: AsyncSession, start: date, end: date, current_user: User):
    stmt = (
        select(Payout.user_id, func.sum(Payout.amount))
        .join(User, User.id == Payout.user_id)
        .where(Payout.date >= start, Payout.date <= end, Payout.location == Location.TikTok))

    if current_user.role == UserRole.MANAGER:
        stmt = stmt.where(User.role != UserRole.ADMIN)

    stmt = stmt.group_by(Payout.user_id)
    q = await session.execute(stmt)
    return dict(q.all())


def summarize_period(days: list[dict], payouts: dict[int, Decimal]):
    total_orders = Decimal("0")
    total_returns = Decimal("0")
    salary_acc = defaultdict(lambda: {"fixed": Decimal("0"), "percent": Decimal("0"), "penalties": Decimal("0")})

    # Агрегация по типам заказов
    types_acc = defaultdict(lambda: {"amount": Decimal("0"), "count": 0})
    # Агрегация по создателям
    creators_acc = defaultdict(lambda: {"name": "", "amount": Decimal("0"), "count": 0})

    for day in days:
        total_orders += day["orders"]
        total_returns += day["returns"]

        for uid, amount in day["salary_fixed_by_user"].items():
            salary_acc[uid]["fixed"] += amount
        for uid, amount in day["salary_percent_by_user"].items():
            salary_acc[uid]["percent"] += amount
        for uid, amount in day.get("penalties_by_user", {}).items():
            salary_acc[uid]["penalties"] += amount

        # Агрегируем статистику по типам
        for type_name, type_data in day.get("orders_by_type", {}).items():
            types_acc[type_name]["amount"] += type_data["amount"]
            types_acc[type_name]["count"] += type_data["count"]

        # Агрегируем статистику по создателям
        for uid, creator_data in day.get("orders_by_creator", {}).items():
            creators_acc[uid]["name"] = creator_data["name"]
            creators_acc[uid]["amount"] += creator_data["amount"]
            creators_acc[uid]["count"] += creator_data["count"]

    salaries = []
    for uid, parts in salary_acc.items():
        fixed = parts["fixed"]
        percent = parts["percent"]
        penalties = parts["penalties"]
        total = fixed + percent - penalties
        paid = payouts.get(uid, Decimal("0"))
        salaries.append(
            {
                "user_id": uid,
                "fixed": fixed,
                "percent": percent,
                "penalties": penalties,
                "total": total,
                "paid": paid,
                "remaining": total - paid,
            }
        )

    # Преобразуем aggregated data в отсортированные списки
    types_breakdown = [
        {"type_name": type_name, "amount": data["amount"], "count": data["count"]}
        for type_name, data in sorted(types_acc.items(), key=lambda x: x[1]["amount"], reverse=True)
    ]

    creators_breakdown = [
        {"user_id": uid, "name": data["name"], "amount": data["amount"], "count": data["count"]}
        for uid, data in sorted(creators_acc.items(), key=lambda x: x[1]["amount"], reverse=True)
    ]

    return {
        "days": days,
        "totals": {
            "orders": total_orders,
            "returns": total_returns,
            "cashbox": total_orders - total_returns,
        },
        "salaries": salaries,
        "types_breakdown": types_breakdown,
        "creators_breakdown": creators_breakdown,
    }
