from fastapi import FastAPI

from app.api.v1.health import router as health_router
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

app.include_router(health_router, prefix="/api/v1", tags=["operational"])
