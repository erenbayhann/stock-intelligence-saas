# Stock Hyperion
AI-powered stock ranking platform that ranks S&P 100 equities using market data, news, fundamentals, and machine learning. (Repo/working name: `stock-intelligence-saas`.)

See `docs/ai-stock-ranking-mvp-spec.md` for the full product spec, `docs/data-ingestion-plan_1.md` for provider/schedule details, and `docs/api-and-schema-plan.md` for the API surface and database schema.

## Running (Phase 1)

Requires Docker Desktop.

```
cp .env.example .env   # then fill in real values (see the repo owner for API keys)
docker compose up -d db
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.jobs.seed_universe
docker compose run --rm backend python -m app.jobs.backfill_market_data
docker compose up backend
```

Then `GET http://localhost:8000/api/v1/health`.

Run tests (against a real Postgres test database, never SQLite):

```
docker compose run --rm backend pytest
```

