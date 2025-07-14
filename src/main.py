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

from src.auth.dependencies import get_admin_user, get_current_user
from src.users.models import User, UserRole

from src.auth.router import router as auth_router
from src.users.router import router as users_router
from src.orders.router import router as orders_router
from src.returns.router import router as returns_router
from src.shifts.router import router as shifts_router
from src.reports.router import router as reports_router
from src.utils.create_admin import create_admin_user

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
    router=orders_router,
    prefix="/orders",
    tags=["Orders"],
)

app.include_router(
    router=returns_router,
    prefix="/returns",
    tags=["Returns"],
)

app.include_router(
    router=shifts_router,
    prefix="/shifts",
    tags=["Shifts"],
)

app.include_router(
    router=reports_router, 
    prefix="/reports", 
    tags=["Reports"],
    dependencies=[Depends(get_admin_user)]
)
