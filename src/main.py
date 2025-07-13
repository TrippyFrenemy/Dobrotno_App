import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from redis import asyncio as aioredis

app = FastAPI(title="Dobrotno App", description="A FastAPI application for Dobrotno Shop", version="0.0.1")

templates = Jinja2Templates(directory="src/templates")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
app.mount("/media", StaticFiles(directory="src/media"), name="media")
app.mount("/uploads", StaticFiles(directory="src/uploads"), name="uploads")

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
async def read_root(request: Request):
    context = {
        "request": request,
        "title": "Dobrotno Shop",
        "status": 200, 
        "message": "Welcome to the Dobrotno App!"
        }
    return templates.TemplateResponse(
        "index.html", 
        request=request,
        context=context
    )
