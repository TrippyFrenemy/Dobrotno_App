from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from decimal import Decimal
from typing import Optional

from src.auth.dependencies import get_admin_user
from src.database import get_async_session
from src.users.models import User, UserRole
from src.utils.csrf import generate_csrf_token, verify_csrf_token
from src.tiktok.branches.models import TikTokBranch, UserBranchAssignment, OrderTypeBranch
from src.tiktok.order_types.models import OrderType

router = APIRouter(prefix="/branches", tags=["TikTok Branches"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def list_branches(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Список всех TikTok точек"""
    csrf_token = await generate_csrf_token(current_user.id)

    stmt = select(TikTokBranch).order_by(TikTokBranch.name)
    result = await session.execute(stmt)
    branches = result.scalars().all()

    return templates.TemplateResponse(
        "tiktok/branches/list.html",
        {"request": request, "branches": branches, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.get("/create", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def create_branch_form(
    request: Request,
    current_user: User = Depends(get_admin_user),
):
    """Форма создания новой точки"""
    csrf_token = await generate_csrf_token(current_user.id)

    return templates.TemplateResponse(
        "tiktok/branches/form.html",
        {"request": request, "branch": None, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.post("/create", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def create_branch(
    request: Request,
    name: str = Form(...),
    is_active: bool = Form(True),
    is_default: bool = Form(False),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Создание новой TikTok точки"""
    await verify_csrf_token(csrf_token, current_user.id)

    # Проверка уникальности имени
    stmt = select(TikTokBranch).where(TikTokBranch.name == name)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Точка с таким названием уже существует")

    # Если новая точка станет default, убираем флаг у остальных
    if is_default:
        await session.execute(
            select(TikTokBranch).where(TikTokBranch.is_default == True)
        )
        for branch in (await session.execute(select(TikTokBranch).where(TikTokBranch.is_default == True))).scalars().all():
            branch.is_default = False

    branch = TikTokBranch(
        name=name,
        is_active=is_active,
        is_default=is_default
    )
    session.add(branch)
    await session.commit()

    return RedirectResponse(url="/branches/?success=created", status_code=303)


@router.get("/{branch_id}/edit", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def edit_branch_form(
    branch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Форма редактирования точки"""
    csrf_token = await generate_csrf_token(current_user.id)

    stmt = select(TikTokBranch).where(TikTokBranch.id == branch_id)
    result = await session.execute(stmt)
    branch = result.scalar_one_or_none()

    if not branch:
        raise HTTPException(status_code=404, detail="Точка не найдена")

    return templates.TemplateResponse(
        "tiktok/branches/form.html",
        {"request": request, "branch": branch, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.post("/{branch_id}/edit", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def update_branch(
    branch_id: int,
    request: Request,
    name: str = Form(...),
    is_active: bool = Form(True),
    is_default: bool = Form(False),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Обновление TikTok точки"""
    await verify_csrf_token(csrf_token, current_user.id)

    stmt = select(TikTokBranch).where(TikTokBranch.id == branch_id)
    result = await session.execute(stmt)
    branch = result.scalar_one_or_none()

    if not branch:
        raise HTTPException(status_code=404, detail="Точка не найдена")

    # Проверка уникальности имени (исключаем текущую)
    stmt = select(TikTokBranch).where(TikTokBranch.name == name, TikTokBranch.id != branch_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Точка с таким названием уже существует")

    # Если эта точка станет default, убираем флаг у остальных
    if is_default and not branch.is_default:
        for other in (await session.execute(select(TikTokBranch).where(TikTokBranch.is_default == True))).scalars().all():
            other.is_default = False

    branch.name = name
    branch.is_active = is_active
    branch.is_default = is_default

    await session.commit()

    return RedirectResponse(url="/branches/?success=updated", status_code=303)


@router.post("/{branch_id}/delete", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def delete_branch(
    branch_id: int,
    request: Request,
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Удаление TikTok точки"""
    await verify_csrf_token(csrf_token, current_user.id)

    stmt = select(TikTokBranch).where(TikTokBranch.id == branch_id)
    result = await session.execute(stmt)
    branch = result.scalar_one_or_none()

    if not branch:
        raise HTTPException(status_code=404, detail="Точка не найдена")

    if branch.is_default:
        raise HTTPException(status_code=400, detail="Нельзя удалить главную точку")

    await session.delete(branch)
    await session.commit()

    return RedirectResponse(url="/branches/?success=deleted", status_code=303)


@router.get("/{branch_id}/settings", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def branch_settings(
    branch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Настройки точки: привязка пользователей и типов заказов"""
    csrf_token = await generate_csrf_token(current_user.id)

    # Загружаем точку
    stmt = select(TikTokBranch).where(TikTokBranch.id == branch_id)
    result = await session.execute(stmt)
    branch = result.scalar_one_or_none()

    if not branch:
        raise HTTPException(status_code=404, detail="Точка не найдена")

    # Загружаем всех менеджеров
    stmt = select(User).where(User.role == UserRole.MANAGER, User.is_active == True).order_by(User.name)
    result = await session.execute(stmt)
    managers = result.scalars().all()

    # Загружаем привязки пользователей к этой точке
    stmt = select(UserBranchAssignment).where(UserBranchAssignment.branch_id == branch_id)
    result = await session.execute(stmt)
    user_assignments = {a.user_id: a for a in result.scalars().all()}

    # Формируем данные для отображения
    user_settings = []
    for user in managers:
        assignment = user_assignments.get(user.id)
        user_settings.append({
            "user_id": user.id,
            "user_name": user.name,
            "default_percent": user.default_percent,
            "custom_percent": assignment.custom_percent if assignment else None,
            "is_allowed": assignment.is_allowed if assignment else True,
            "is_primary": assignment.is_primary if assignment else False,
        })

    # Загружаем все типы заказов
    stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    # Загружаем привязки типов к этой точке
    stmt = select(OrderTypeBranch).where(OrderTypeBranch.branch_id == branch_id)
    result = await session.execute(stmt)
    type_assignments = {a.order_type_id: a for a in result.scalars().all()}

    # Формируем данные для отображения
    type_settings = []
    for ot in order_types:
        assignment = type_assignments.get(ot.id)
        type_settings.append({
            "order_type_id": ot.id,
            "order_type_name": ot.name,
            "is_allowed": assignment.is_allowed if assignment else True,
        })

    return templates.TemplateResponse(
        "tiktok/branches/settings.html",
        {
            "request": request,
            "branch": branch,
            "user_settings": user_settings,
            "type_settings": type_settings,
            "current_user": current_user,
            "csrf_token": csrf_token
        },
    )


@router.post("/{branch_id}/settings", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def save_branch_settings(
    branch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Сохранение настроек точки"""
    form = await request.form()
    csrf_token = form.get("csrf_token")
    await verify_csrf_token(csrf_token, current_user.id)

    # Проверяем существование точки
    stmt = select(TikTokBranch).where(TikTokBranch.id == branch_id)
    result = await session.execute(stmt)
    branch = result.scalar_one_or_none()

    if not branch:
        raise HTTPException(status_code=404, detail="Точка не найдена")

    # Загружаем всех менеджеров
    stmt = select(User).where(User.role == UserRole.MANAGER, User.is_active == True)
    result = await session.execute(stmt)
    managers = result.scalars().all()

    # Обрабатываем настройки пользователей
    for user in managers:
        percent_str = form.get(f"user_{user.id}_percent", "").strip()
        is_allowed = form.get(f"user_{user.id}_allowed") == "on"
        is_primary = form.get(f"user_{user.id}_primary") == "on"

        custom_percent = Decimal(percent_str) if percent_str else None

        # Ищем существующую привязку
        stmt = select(UserBranchAssignment).where(
            UserBranchAssignment.user_id == user.id,
            UserBranchAssignment.branch_id == branch_id
        )
        result = await session.execute(stmt)
        assignment = result.scalar_one_or_none()

        if assignment:
            assignment.custom_percent = custom_percent
            assignment.is_allowed = is_allowed
            assignment.is_primary = is_primary
        else:
            # Создаём только если есть нестандартные настройки
            if custom_percent is not None or not is_allowed or is_primary:
                assignment = UserBranchAssignment(
                    user_id=user.id,
                    branch_id=branch_id,
                    custom_percent=custom_percent,
                    is_allowed=is_allowed,
                    is_primary=is_primary
                )
                session.add(assignment)

    # Загружаем все активные типы заказов
    stmt = select(OrderType).where(OrderType.is_active == True)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    # Обрабатываем настройки типов заказов
    for ot in order_types:
        is_allowed = form.get(f"type_{ot.id}_allowed") == "on"

        # Ищем существующую привязку
        stmt = select(OrderTypeBranch).where(
            OrderTypeBranch.order_type_id == ot.id,
            OrderTypeBranch.branch_id == branch_id
        )
        result = await session.execute(stmt)
        type_assignment = result.scalar_one_or_none()

        if type_assignment:
            type_assignment.is_allowed = is_allowed
        else:
            # Создаём только если тип запрещён
            if not is_allowed:
                type_assignment = OrderTypeBranch(
                    order_type_id=ot.id,
                    branch_id=branch_id,
                    is_allowed=is_allowed
                )
                session.add(type_assignment)

    await session.commit()

    return RedirectResponse(url=f"/branches/{branch_id}/settings?success=saved", status_code=303)
