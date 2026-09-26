"""Mount feature-owned public and administrator HTTP routes."""

from fastapi import APIRouter

from app.api.corpus import routes as corpus
from app.api.documents import admin as document_admin, routes as documents
from app.api.evaluations import results, routes as evaluations
from app.api.review import preset_routes, previews, routes as review, streaming
from app.api.snapshots import admin as snapshot_admin, routes as snapshots
from app.api.system import jobs, settings, usage

api_router = APIRouter()
for feature in (documents, review, results, snapshots, streaming):
    api_router.include_router(feature.router)

admin_router = APIRouter()
for feature in (
    corpus,
    document_admin,
    evaluations,
    snapshot_admin,
    jobs,
    usage,
    previews,
    settings,
    preset_routes,
):
    admin_router.include_router(feature.router)
