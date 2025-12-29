from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from typing import Dict, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.tiktok.orders.models import Order, OrderOrderType
from src.tiktok.returns.models import Return
from src.tiktok.shifts.models import Shift, ShiftAssignment
from src.users.models import User, UserRole
from src.payouts.models import Payout, RoleType, Location
from src.tiktok.order_types.models import OrderType, UserOrderTypeSetting
from src.tiktok.branches.models import TikTokBranch, UserBranchAssignment


def get_employee_percent_for_branch(
    user: User,
    branch_id: Optional[int],
    branch_assignments_map: Dict[tuple, UserBranchAssignment]
) -> Decimal:
    """
    Получить процент для сотрудника на конкретной точке.
    Приоритет:
    1. UserBranchAssignment.custom_percent (если задан)
    2. User.default_percent
    """
    if branch_id is None:
        return user.default_percent

    assignment = branch_assignments_map.get((user.id, branch_id))
    if assignment and assignment.custom_percent is not None:
        return assignment.custom_percent

    return user.default_percent


def get_employee_percent_for_order_type(
    user: User,
    order_type: Optional[OrderType],
    user_settings_map: Dict[tuple, UserOrderTypeSetting],
    branch_id: Optional[int] = None,
    branch_assignments_map: Optional[Dict[tuple, UserBranchAssignment]] = None
) -> Decimal:
    """
    Получить процент для сотрудника с учётом приоритетов:
    1. Индивидуальная настройка (UserOrderTypeSetting.custom_percent)
    2. Процент по умолчанию для типа заказа (OrderType.default_employee_percent)
    3. Индивидуальный процент для точки (UserBranchAssignment.custom_percent)
    4. Процент по умолчанию для пользователя (User.default_percent)
    """
    # Базовый процент с учётом точки
    if branch_id and branch_assignments_map:
        base_percent = get_employee_percent_for_branch(user, branch_id, branch_assignments_map)
    else:
        base_percent = user.default_percent

    if order_type is None:
        # Заказ без типа — используем базовый процент
        return base_percent

    # 1. Проверяем индивидуальную настройку для типа заказа
    setting = user_settings_map.get((user.id, order_type.id))
    if setting and setting.custom_percent is not None:
        return setting.custom_percent

    # 2. Проверяем процент по умолчанию для типа заказа
    if order_type.default_employee_percent is not None:
        return order_type.default_employee_percent

    # 3. Fallback на базовый процент (точки или пользователя)
    return base_percent


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
    current_user: User,
    branch_id: Optional[int] = None
):
    """
    Получить отчёт за период.

    Args:
        branch_id: ID точки для фильтрации. None = все точки (совместимость со старыми данными).
    """
    users_q = await session.execute(select(User))
    users = {u.id: u for u in users_q.scalars().all()}

    # Загружаем привязки пользователей к точкам
    branch_assignments_q = await session.execute(select(UserBranchAssignment))
    branch_assignments_map = {
        (a.user_id, a.branch_id): a
        for a in branch_assignments_q.scalars().all()
    }

    # Загружаем все заказы с типами для учета комиссии (поддержка обеих схем)
    orders_stmt = (
        select(Order)
        .where(Order.date >= start, Order.date <= end)
        .options(
            selectinload(Order.order_type),  # Старая схема (type_id)
            selectinload(Order.order_order_types).selectinload(OrderOrderType.order_type)  # Новая схема (many-to-many)
        )
    )
    # Фильтрация по точке
    if branch_id is not None:
        orders_stmt = orders_stmt.where(Order.branch_id == branch_id)

    orders_q = await session.execute(orders_stmt)
    all_orders = orders_q.unique().scalars().all()

    # Загружаем все типы заказов для справочника
    types_q = await session.execute(select(OrderType))
    order_types = {t.id: t for t in types_q.scalars().all()}

    # Загружаем индивидуальные настройки типов заказов для пользователей
    settings_q = await session.execute(select(UserOrderTypeSetting))
    user_settings_map = {
        (s.user_id, s.order_type_id): s
        for s in settings_q.scalars().all()
    }

    # Группируем заказы по дате и создателю
    orders_map = defaultdict(lambda: defaultdict(lambda: {'amount': Decimal('0'), 'orders': []}))
    for order in all_orders:
        orders_map[order.date][order.created_by]['amount'] += order.amount
        orders_map[order.date][order.created_by]['orders'].append(order)

    # Загружаем возвраты с штрафами и связанными заказами (с типами)
    returns_q = await session.execute(
        select(Return)
        .where(Return.date >= start, Return.date <= end)
        .options(
            selectinload(Return.order).selectinload(Order.order_order_types).selectinload(OrderOrderType.order_type),
            selectinload(Return.order).selectinload(Order.order_type)
        )
    )
    all_returns = returns_q.scalars().all()

    # Группируем возвраты по дате
    returns_map = defaultdict(Decimal)
    returns_details_map = defaultdict(list)  # Детали возвратов для отображения
    penalties_map_by_date = defaultdict(lambda: defaultdict(lambda: Decimal('0')))

    # Возвраты привязанные к конкретным заказам (по менеджерам)
    # Структура: {date: {manager_id: Decimal}}
    returns_by_manager = defaultdict(lambda: defaultdict(Decimal))
    # Возвраты без привязки к заказу (для равномерного распределения)
    # Структура: {date: Decimal}
    returns_unassigned = defaultdict(Decimal)

    for ret in all_returns:
        returns_map[ret.date] += ret.amount

        # Собираем типы заказа для возврата
        order_types_info = []
        if ret.order:
            if ret.order.order_order_types:
                # Новая схема: несколько типов
                for oot in ret.order.order_order_types:
                    order_types_info.append({
                        'name': oot.order_type.name if oot.order_type else "?",
                        'amount': oot.amount
                    })
            elif ret.order.order_type:
                # Старая схема: один тип
                order_types_info.append({
                    'name': ret.order.order_type.name,
                    'amount': ret.order.amount
                })

        returns_details_map[ret.date].append({
            'amount': ret.amount,
            'order_id': ret.order_id,
            'order_types': order_types_info,
            'reason': ret.reason
        })

        # Определяем как распределить возврат
        if ret.order_id and ret.order:
            # Возврат привязан к заказу - вычитаем у владельца заказа
            returns_by_manager[ret.date][ret.order.created_by] += ret.amount
        else:
            # Возврат без привязки - будет распределен равномерно
            returns_unassigned[ret.date] += ret.amount

        # Собираем штрафы по сотрудникам (штрафы привязаны к дате возврата)
        if ret.penalty_distribution:
            for user_id_str, penalty_amount in ret.penalty_distribution.items():
                penalties_map_by_date[ret.date][int(user_id_str)] += Decimal(str(penalty_amount))

    # Все смены с назначениями
    shifts_stmt = (
        select(Shift)
        .where(Shift.date >= start, Shift.date <= end)
        .options(selectinload(Shift.assignments).selectinload(ShiftAssignment.user))
    )
    # Фильтрация по точке
    if branch_id is not None:
        shifts_stmt = shifts_stmt.where(Shift.branch_id == branch_id)

    shifts_q = await session.execute(shifts_stmt)
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

        # Рассчитываем кассу для сотрудников (только типы с include_in_employee_salary=True)
        employee_orders_total = Decimal('0')
        for uid, order_data in day_orders.items():
            for order in order_data['orders']:
                # НОВАЯ СХЕМА: несколько типов
                if order.order_order_types:
                    for order_type_link in order.order_order_types:
                        ot = order_type_link.order_type
                        # Включаем только если include_in_employee_salary=True (или если типа нет)
                        if ot is None or ot.include_in_employee_salary:
                            employee_orders_total += order_type_link.amount
                # СТАРАЯ СХЕМА: один тип
                elif order.type_id and order.type_id in order_types:
                    ot = order_types[order.type_id]
                    if ot.include_in_employee_salary:
                        employee_orders_total += order.amount
                # БЕЗ ТИПА — включаем (обратная совместимость)
                else:
                    employee_orders_total += order.amount
        employee_cashbox = employee_orders_total - returns

        # Статистика по типам заказов (только для админов, менеджеры не видят)
        orders_by_type = defaultdict(lambda: {'amount': Decimal('0'), 'count': 0})
        if current_user.role != UserRole.MANAGER:
            for uid, order_data in day_orders.items():
                for order in order_data['orders']:
                    # НОВАЯ СХЕМА: несколько типов
                    if order.order_order_types:
                        for order_type_link in order.order_order_types:
                            type_name = order_type_link.order_type.name if order_type_link.order_type else "Без типа"
                            orders_by_type[type_name]['amount'] += order_type_link.amount
                            # Каждый заказ считается ЦЕЛИКОМ (даже если несколько типов)
                            orders_by_type[type_name]['count'] += 1
                    # СТАРАЯ СХЕМА: один тип
                    elif order.type_id:
                        type_name = order_types[order.type_id].name if order.type_id in order_types else "Без типа"
                        orders_by_type[type_name]['amount'] += order.amount
                        orders_by_type[type_name]['count'] += 1
                    # БЕЗ ТИПА
                    else:
                        orders_by_type["Без типа"]['amount'] += order.amount
                        orders_by_type["Без типа"]['count'] += 1

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
                    # Используем employee_cashbox (только типы с include_in_employee_salary=True)
                    cashbox_perc = employee_cashbox / len(employee_details) if employee_details else Decimal('0')
                    # Используем процент с учётом точки смены
                    shift_branch_id = shift.branch_id or branch_id
                    emp_percent = get_employee_percent_for_branch(a.user, shift_branch_id, branch_assignments_map)
                    percent[a.user_id] += round((cashbox_perc * emp_percent) / 100)
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
        # Сначала собираем всех менеджеров за день для равномерного распределения возвратов
        day_managers = []
        for uid, order_data in day_orders.items():
            user = users.get(uid)
            if user and user.role in [UserRole.ADMIN, UserRole.MANAGER]:
                day_managers.append(uid)

        # Получаем возвраты за день
        day_returns_by_manager = returns_by_manager.get(current, {})
        day_returns_unassigned = returns_unassigned.get(current, Decimal('0'))

        # Равномерная доля нераспределённых возвратов на каждого менеджера
        unassigned_per_manager = Decimal('0')
        if day_managers and day_returns_unassigned > 0:
            unassigned_per_manager = day_returns_unassigned / len(day_managers)

        for uid, order_data in day_orders.items():
            user = users.get(uid)
            if user and user.role in [UserRole.ADMIN, UserRole.MANAGER]:
                fixed[uid] += user.default_rate

                # Рассчитываем процент с учетом комиссии каждого типа заказа
                # и индивидуальных процентов для типов
                total_percent_amount = Decimal('0')
                for order in order_data['orders']:
                    # branch_id заказа (может быть None для старых данных)
                    order_branch_id = order.branch_id or branch_id
                    # НОВАЯ СХЕМА: несколько типов с распределением суммы
                    if order.order_order_types:
                        for order_type_link in order.order_order_types:
                            type_amount = order_type_link.amount
                            order_type = order_type_link.order_type
                            commission = order_type.commission_percent if order_type else Decimal('100')
                            order_profit = type_amount * commission / 100

                            # Получаем процент для этого типа заказа с учётом приоритетов
                            employee_percent = get_employee_percent_for_order_type(
                                user, order_type, user_settings_map,
                                order_branch_id, branch_assignments_map
                            )
                            total_percent_amount += order_profit * employee_percent / 100
                    # СТАРАЯ СХЕМА: один тип на весь заказ
                    elif order.order_type:
                        commission = order.order_type.commission_percent
                        order_profit = order.amount * commission / 100

                        # Получаем процент для этого типа заказа с учётом приоритетов
                        employee_percent = get_employee_percent_for_order_type(
                            user, order.order_type, user_settings_map,
                            order_branch_id, branch_assignments_map
                        )
                        total_percent_amount += order_profit * employee_percent / 100
                    # СОВСЕМ СТАРЫЕ ЗАКАЗЫ: без типа (100% комиссия)
                    else:
                        # Для заказов без типа используем базовый процент (с учётом точки)
                        base_percent = get_employee_percent_for_branch(
                            user, order_branch_id, branch_assignments_map
                        )
                        total_percent_amount += order.amount * base_percent / 100

                # Вычитаем возвраты: персональные + равномерная доля от нераспределённых
                # Возвраты вычитаются пропорционально базовому проценту (с учётом точки)
                manager_returns = day_returns_by_manager.get(uid, Decimal('0')) + unassigned_per_manager
                base_percent = get_employee_percent_for_branch(user, branch_id, branch_assignments_map)
                returns_deduction = manager_returns * base_percent / 100
                percent[uid] += round(total_percent_amount - returns_deduction)
    
        # Статистика по создателям (менеджерам)
        # Для MANAGER этот блок скрываем полностью (таблица "💼 Касса по менеджерам" не отображается).
        orders_by_creator = {}
        if current_user.role != UserRole.MANAGER:
            for uid, order_data in day_orders.items():
                user = users.get(uid)
                if user:
                    # Возвраты менеджера = персональные + доля от нераспределённых
                    manager_returns = day_returns_by_manager.get(uid, Decimal('0')) + unassigned_per_manager
                    orders_by_creator[uid] = {
                        'name': user.name,
                        'amount': order_data['amount'],
                        'count': len(order_data['orders']),
                        'returns': manager_returns
                    }

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
            "returns_details": returns_details_map.get(current, []),  # Детали возвратов с типами заказов
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
    creators_acc = defaultdict(lambda: {"name": "", "amount": Decimal("0"), "count": 0, "returns": Decimal("0")})

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
            creators_acc[uid]["returns"] += creator_data.get("returns", Decimal("0"))

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
        {"user_id": uid, "name": data["name"], "amount": data["amount"], "count": data["count"], "returns": data["returns"]}
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
