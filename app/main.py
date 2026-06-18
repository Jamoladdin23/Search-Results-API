import os
import time
import logging
from collections import defaultdict
from typing import Annotated

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.scraper import sanitize_query, search, MAX_QUERY_LENGTH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ALLOWED_ORIGIN: str = os.getenv("ALLOWED_ORIGIN", "*")
RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

_rate_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    if len(_rate_store[ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Max {RATE_LIMIT_REQUESTS} per {RATE_LIMIT_WINDOW}s.",
        )
    _rate_store[ip].append(now)


app = FastAPI(
    title="Search Scraper",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response


class SearchResult(BaseModel):
    position: int
    title: str
    url: str
    description: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class ErrorResponse(BaseModel):
    detail: str


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("static/index.html")


@app.get(
    "/search",
    response_model=SearchResponse,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def search_endpoint(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
):
    client_ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
    _check_rate_limit(client_ip)

    try:
        clean_query = sanitize_query(q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Search: ip=%s query=%r", client_ip, clean_query)

    results = search(clean_query)

    if results is None:
        raise HTTPException(status_code=503, detail="Search backend unavailable.")

    return SearchResponse(query=clean_query, results=results)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
