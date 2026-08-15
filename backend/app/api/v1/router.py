from fastapi import APIRouter

from app.api.v1 import auth, chat, connectors, documents, invitations, workspaces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(connectors.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(workspaces.router)
api_router.include_router(invitations.router)
