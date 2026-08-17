from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .routers import admin, auth_routes, items, mapping, reports, uploads

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("excel-automation")

app = FastAPI(title="Excel Reconciliation App", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth_routes.router, admin.router, uploads.router,
               mapping.router, items.router, reports.router):
    app.include_router(router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Something went wrong on the server. Check the API logs."},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
