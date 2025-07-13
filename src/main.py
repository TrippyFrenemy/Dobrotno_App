import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.exc import IntegrityError

import redis.asyncio as redis

from src.auth.dependencies import get_current_user
from src.users.models import User, UserRole

from src.auth.router import router as auth_router
from src.users.router import router as users_router

from src.database import async_session_maker
from passlib.context import CryptContext
from sqlalchemy import select

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_admin_user()
    yield
    # Cleanup actions can be added here if needed

app = FastAPI(lifespan=lifespan, title="Dobrotno App", description="A FastAPI application for Dobrotno Shop", version="0.0.1")

templates = Jinja2Templates(directory="src/templates")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
# app.mount("/media", StaticFiles(directory="src/media"), name="media")
# app.mount("/uploads", StaticFiles(directory="src/uploads"), name="uploads")

origins = [
    "http://localhost",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],  # "GET", "POST", "OPTIONS", "DELETE", "PATCH", "PUT"
    allow_headers=["*"]   # "Content-Type", "Set-Cookie", "Access-Control-Allow-Headers",
                          # "Access-Control-Allow-Origin", "Authorization"
)

@app.get("/", response_class=HTMLResponse)
async def public_root(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

app.include_router(
    router=auth_router,
    prefix="/auth",
    tags=["Auth"],
)

app.include_router(
    router=users_router,
    prefix="/users",
    tags=["Users"],
)
