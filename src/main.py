import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.exc import IntegrityError

import redis.asyncio as redis

from src.auth.dependencies import get_admin_user, get_current_user, get_manager_or_admin
from src.users.models import User, UserRole

from src.auth.router import router as auth_router
from src.users.router import router as users_router
from src.tiktok.router import router as tiktok_router
from src.cafe.router import router as coffee_router
from src.logs.router import router as logs_router
from src.stores.router import router as stores_router

from src.utils.create_admin import create_admin_user

from src.logs.middleware import LogUserActionMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("tmp", exist_ok=True)
    os.makedirs("src/static", exist_ok=True)
    await create_admin_user()
    yield
    # Cleanup actions can be added here if needed

app = FastAPI(lifespan=lifespan, title="Dobrotno App", description="A FastAPI application for Dobrotno Shop", version="0.0.1")

templates = Jinja2Templates(directory="src/templates")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
# app.mount("/media", StaticFiles(directory="src/media"), name="media")
# app.mount("/uploads", StaticFiles(directory="src/uploads"), name="uploads")

app.add_middleware(LogUserActionMiddleware)

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

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    if exc.status_code == 401:
        return RedirectResponse("/")
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

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

app.include_router(
    router=tiktok_router,
    tags=["TikTok"],
)

app.include_router(
    router=coffee_router,
    prefix="/cafe",
    tags=["Cafe"],
    dependencies=[Depends(get_admin_user)]
)

app.include_router(
    router=stores_router,
    prefix="/stores",
    tags=["Stores"],
    dependencies=[Depends(get_manager_or_admin)]
)

app.include_router(
    router=logs_router,
    prefix="/logs",
    tags=["Logs"],
    dependencies=[Depends(get_admin_user)]
)
