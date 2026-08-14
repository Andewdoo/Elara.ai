from app.routes.auth import router as auth_router
from app.routes.demo_runs import router as demo_runs_router
from app.routes.verifications import router as verifications_router
from app.routes.history import router as history_router
from app.routes.uploads import router as uploads_router

__all__ = ["auth_router", "demo_runs_router", "history_router", "uploads_router", "verifications_router"]
