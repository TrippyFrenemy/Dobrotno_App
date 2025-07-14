from src.database import async_session_maker
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.users.models import User, UserRole

async def create_admin_user():
    from src.config import ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME, ADMIN_ROLE
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            print("✅ Администратор уже существует, пропускаем создание")
            return

        try:
            user = User(
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                role=UserRole(ADMIN_ROLE.lower()),
                hashed_password=pwd_context.hash(ADMIN_PASSWORD),
            )
            session.add(user)
            await session.commit()
            print("✅ Администратор создан")
        except IntegrityError:
            print("⚠️ Администратор уже есть (integrity check)")
