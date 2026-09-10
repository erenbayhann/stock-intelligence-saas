from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.admin import router as admin_router
from app.api.v1.health import router as health_router
from app.api.v1.model import router as model_router
from app.api.v1.performance import router as performance_router
from app.api.v1.rankings import router as rankings_router
from app.api.v1.stocks import router as stocks_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Stock Intelligence & Ranking API",
    description=(
        "AI-powered research and decision-support platform for the S&P 100 "
        "universe. Not a trading bot; never gives personalized investment advice."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1", tags=["operational"])
app.include_router(rankings_router, prefix="/api/v1", tags=["rankings"])
app.include_router(stocks_router, prefix="/api/v1", tags=["stocks"])
app.include_router(performance_router, prefix="/api/v1", tags=["performance"])
app.include_router(model_router, prefix="/api/v1", tags=["model"])
app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
