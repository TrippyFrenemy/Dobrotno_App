from src.database import async_session_maker
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.users.models import User, UserRole

async def create_user(email, name, role, password, default_rate=1000.0, default_percent=0.0):
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"✅ {role} уже существует, пропускаем создание")
            return

        try:
            user = User(
                email=email,
                name=name,
                role=UserRole(role.lower()),
                hashed_password=pwd_context.hash(password),
                default_rate=default_rate,
                default_percent=default_percent,
            )
            session.add(user)
            await session.commit()
            print(f"✅ {role} создан")
        except IntegrityError:
            print(f"⚠️ {role} уже есть (integrity check)")
