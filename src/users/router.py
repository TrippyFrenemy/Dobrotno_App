from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from src.users import schemas
from src.users.models import User, UserRole
from src.database import get_async_session
from sqlalchemy.future import select

router = APIRouter(prefix="/users", tags=["Users"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/create", response_model=schemas.UserOut)
async def create_user(
    user_data: schemas.UserCreate,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(User).where(User.email == user_data.email)
    result = await session.execute(stmt)
    if result.scalar():
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = User(
        email=user_data.email,
        name=user_data.name,
        role=user_data.role,
        default_rate=user_data.default_rate,
        hashed_password=pwd_context.hash(user_data.password),
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return new_user
