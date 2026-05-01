from fastapi import APIRouter

from app.api.v1 import shell, shell_stream, supervisor, file

api_router = APIRouter()
api_router.include_router(shell.router, prefix="/shell", tags=["shell"])
# Mount the WS-based interactive pty under the same `/shell` prefix so
# clients hit `/api/v1/shell/stream` instead of inventing a new namespace.
# Distinct router because shell.py is HTTP-only and we keep that surface
# clean.
api_router.include_router(shell_stream.router, prefix="/shell", tags=["shell"])
api_router.include_router(supervisor.router, prefix="/supervisor", tags=["supervisor"])
api_router.include_router(file.router, prefix="/file", tags=["file"])
