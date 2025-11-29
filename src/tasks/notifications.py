from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from celery import shared_task
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from src.database import async_session_maker
from src.notifications.models import Notification, NotificationType
from src.tiktok.orders.models import Order
from src.tiktok.returns.models import Return
from src.users.models import User, UserRole


@shared_task
def send_daily_order_summary():
    """Отправка ежедневной сводки по заказам администратору"""
    asyncio.run(_send_daily_order_summary())


async def _send_daily_order_summary():
    """Создает уведомление с ежедневной статистикой заказов для админов"""
    async with async_session_maker() as session:
        # Статистика за вчера
        yesterday = date.today() - timedelta(days=1)

        # Подсчитываем заказы и возвраты за вчера
        stmt_orders = (
            select(
                func.count(Order.id).label("total_count"),
                func.sum(Order.amount).label("total_amount"),
            )
            .where(Order.date == yesterday)
        )
        result_orders = await session.execute(stmt_orders)
        orders_data = result_orders.first()

        stmt_returns = (
            select(
                func.count(Return.id).label("total_count"),
                func.sum(Return.amount).label("total_amount"),
            )
            .where(Return.date == yesterday)
        )
        result_returns = await session.execute(stmt_returns)
        returns_data = result_returns.first()

        total_orders = orders_data.total_count or 0
        total_orders_amount = orders_data.total_amount or Decimal("0")
        total_returns = returns_data.total_count or 0
        total_returns_amount = returns_data.total_amount or Decimal("0")

        # Получаем всех админов
        stmt_admins = select(User.id).where(User.role == UserRole.ADMIN, User.is_active == True)
        result_admins = await session.execute(stmt_admins)
        admin_ids = [row[0] for row in result_admins.all()]

        if not admin_ids:
            return

        # Формируем сообщение
        title = f"📊 Сводка за {yesterday.strftime('%d.%m.%Y')}"
        message = (
            f"Заказы: {total_orders} шт на сумму {total_orders_amount:.2f} грн\n"
            f"Возвраты: {total_returns} шт на сумму {total_returns_amount:.2f} грн\n"
            f"Чистая выручка: {total_orders_amount - total_returns_amount:.2f} грн"
        )

        # Создаем уведомления для каждого админа
        for admin_id in admin_ids:
            notification = Notification(
                user_id=admin_id,
                title=title,
                message=message,
                type=NotificationType.INFO,
                related_url="/orders/all/list",
            )
            session.add(notification)

        await session.commit()


@shared_task
def send_high_value_order_alert(order_id: int):
    """Уведомление о заказе с высокой суммой"""
    asyncio.run(_send_high_value_order_alert(order_id))


async def _send_high_value_order_alert(order_id: int):
    """Создает уведомление администраторам о заказе с суммой выше порога"""
    async with async_session_maker() as session:
        # Получаем заказ
        stmt_order = (
            select(Order)
            .options(selectinload(Order.created_by), selectinload(Order.order_type))
            .where(Order.id == order_id)
        )
        result_order = await session.execute(stmt_order)
        order = result_order.scalar()

        if not order or order.amount < 5000:  # Порог 5000 грн
            return

        # Получаем всех админов и менеджеров
        stmt_users = select(User.id).where(
            User.role == UserRole.ADMIN,
            User.is_active == True
        )
        result_users = await session.execute(stmt_users)
        user_ids = [row[0] for row in result_users.all()]

        if not user_ids:
            return

        # Формируем сообщение
        type_name = order.order_type.name if order.order_type else "Без типа"
        creator_name = order.created_by.name if order.created_by else "Неизвестный"

        title = f"💰 Крупный заказ: {order.amount:.0f} грн"
        message = (
            f"Создан заказ на сумму {order.amount:.2f} грн\n"
            f"Тип: {type_name}\n"
            f"Менеджер: {creator_name}\n"
            f"Дата: {order.date.strftime('%d.%m.%Y')}"
        )

        # Создаем уведомления
        for user_id in user_ids:
            notification = Notification(
                user_id=user_id,
                title=title,
                message=message,
                type=NotificationType.SUCCESS,
                related_url=f"/orders/all/list?day={order.date.day}&month={order.date.month}&year={order.date.year}",
            )
            session.add(notification)

        await session.commit()


@shared_task
def send_penalty_notification(return_id: int):
    """Уведомление о назначении штрафа"""
    asyncio.run(_send_penalty_notification(return_id))


async def _send_penalty_notification(return_id: int):
    """Создает уведомления сотрудникам о назначенных штрафах"""
    async with async_session_maker() as session:
        # Получаем возврат
        stmt_return = select(Return).where(Return.id == return_id)
        result_return = await session.execute(stmt_return)
        ret = result_return.scalar()

        if not ret or not ret.penalty_distribution:
            return

        # Для каждого сотрудника с штрафом создаем уведомление
        for user_id_str, penalty_amount in ret.penalty_distribution.items():
            user_id = int(user_id_str)
            penalty = Decimal(str(penalty_amount))

            if penalty <= 0:
                continue

            title = f"⚠️ Назначен штраф: {penalty:.0f} грн"
            message = (
                f"Вам назначен штраф на сумму {penalty:.2f} грн\n"
                f"Дата: {ret.date.strftime('%d.%m.%Y')}\n"
                f"Причина: {ret.reason or 'Не указана'}"
            )

            notification = Notification(
                user_id=user_id,
                title=title,
                message=message,
                type=NotificationType.WARNING,
                related_url="/users/cabinet",
            )
            session.add(notification)

        await session.commit()


@shared_task
def send_weekly_performance_summary():
    """Отправка еженедельной сводки по производительности менеджерам"""
    asyncio.run(_send_weekly_performance_summary())


async def _send_weekly_performance_summary():
    """Создает уведомления менеджерам с их еженедельной статистикой"""
    async with async_session_maker() as session:
        # Период: последние 7 дней
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=6)

        # Получаем всех активных менеджеров
        stmt_managers = select(User).where(
            User.role == UserRole.ADMIN,
            User.is_active == True
        )
        result_managers = await session.execute(stmt_managers)
        managers = result_managers.scalars().all()

        for manager in managers:
            # Статистика заказов менеджера за неделю
            stmt_orders = (
                select(
                    func.count(Order.id).label("total_count"),
                    func.sum(Order.amount).label("total_amount"),
                )
                .where(
                    Order.creator_id == manager.id,
                    Order.date >= start_date,
                    Order.date <= end_date
                )
            )
            result_orders = await session.execute(stmt_orders)
            orders_data = result_orders.first()

            total_orders = orders_data.total_count or 0
            total_amount = orders_data.total_amount or Decimal("0")

            if total_orders == 0:
                continue  # Не отправляем уведомление если нет заказов

            avg_order = total_amount / total_orders if total_orders > 0 else Decimal("0")

            title = f"📈 Ваша статистика за неделю"
            message = (
                f"Период: {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}\n\n"
                f"Создано заказов: {total_orders} шт\n"
                f"Общая сумма: {total_amount:.2f} грн\n"
                f"Средний чек: {avg_order:.2f} грн\n\n"
                f"Продолжайте в том же духе! 💪"
            )

            notification = Notification(
                user_id=manager.id,
                title=title,
                message=message,
                type=NotificationType.INFO,
                related_url="/users/cabinet",
            )
            session.add(notification)

        await session.commit()
