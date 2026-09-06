from fastapi import APIRouter

from app.api import documents, ingest, retrieve, review, runs, traces

api_router = APIRouter()
for _module in (retrieve, documents, ingest, review, runs, traces):
    api_router.include_router(_module.router)
