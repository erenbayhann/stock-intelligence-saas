# API Endpoint List & Database Schema

Companion to `ai-stock-ranking-mvp-spec.md` (§17 Database, §18 Backend) and `data-ingestion-plan.md`. Fills the two concrete gaps flagged during planning: the REST API surface and the full table/column definitions. Written as a language-neutral spec — translate directly into SQLAlchemy models + Alembic migrations and FastAPI routers.

## 1. REST API

Prefix every route with `/api/v1/` from day one — versioning costs nothing now and avoids breaking the frontend later. Jobs (news ingestion, prediction generation, evaluation, training) run inside the same backend process/codebase and call the service layer directly — they do **not** need to go through HTTP, only the frontend does. Keep it that way; don't add internal HTTP endpoints for job-to-backend communication, it's unnecessary indirection for a monolith.

**Rankings (today's live view + history)**
```
GET  /api/v1/rankings/latest
     → the most recent FINAL prediction snapshot: top 5, ai_score, confidence, rank,
       explanation, related news, generated_at, model_version.
       Never includes actual_return/benchmark_return (see §13 of the master spec —
       those don't exist yet for a live/current prediction).

GET  /api/v1/rankings/{date}          (date = YYYY-MM-DD)
     → a specific past day's full detail: the same top-5 fields as /latest, PLUS
       actual_return, benchmark_return (that session's S&P 500 move), vs_benchmark,
       direction_correct, and that day's notable news. 404 if that date has no
       finalized prediction.

GET  /api/v1/rankings/history?limit=7&before={date}
     → paginated list of past dates with a finalized prediction (for the "Last 7 Days"
       nav) — each entry is a lightweight summary (date, hit rate that day, avg excess
       return that day), not the full ranking. Use this to populate the list; fetch
       /rankings/{date} for the detail view when one is opened.
       Amended during Phase 9 (frontend): also includes the day's #1 pick
       (ticker, ai_score, actual_return, direction_correct, only populated once
       evaluated) — the approved Main dashboard mockup's "Last 7 Days" table
       reads at a glance (date/pick/score/actual/result), which the original
       aggregate-only shape couldn't support. Still one extra column on an
       existing per-day join, not a second query per row, so the "lightweight
       summary, not the full ranking" intent is unchanged.
```

**Stocks**
```
GET  /api/v1/stocks/{ticker}
     → company info, current rank/score if the ticker is in today's top 5 (null
       otherwise — most of the S&P 100 won't be), latest fundamentals snapshot.

GET  /api/v1/stocks/{ticker}/prices?from={date}&to={date}&session=regular|pre|after|all
     → OHLCV series for the charting library (lightweight-charts consumes this
       directly). Default range: last 90 days, regular session only.

GET  /api/v1/stocks/{ticker}/news?limit=20
     → recent news_articles linked to this security, newest first.

GET  /api/v1/stocks/{ticker}/predictions?limit=30
     → this ticker's own history of past predictions + outcomes (rank, ai_score,
       confidence, actual_return, vs_benchmark, direction_correct once evaluated;
       only appears when the ticker was actually in the top 5 that day — most
       days it won't have an entry, which is expected and correct, not a bug).
```

**Performance / transparency**
```
GET  /api/v1/performance/summary?window=7d|30d|all
     → aggregate metrics per §14: hit rate, mean actual return, mean excess return,
       MAE/RMSE, directional accuracy, ranking correlation, Precision@K. Must be
       computed only from prediction_results rows that are actually populated
       (evaluated_at IS NOT NULL) — never silently include still-open predictions.
```

**Model transparency (supports the Methodology page)**
```
GET  /api/v1/model/versions
     → list of model_versions with status (champion/challenger/retired), promoted_at,
       headline validation metrics.

GET  /api/v1/model/versions/{id}
     → one model version's full detail: training_run info, hyperparameters, full
       metrics — this is what makes a historical prediction traceable back to its
       model, per §25.
```

**Operational**
```
GET  /api/v1/health
     → liveness/readiness check (DB reachable, last successful run per job_name from
       `job_runs` — see §2 schema) for the observability layer in §25.
```

**Admin (owner-only — spec §15/§16; every route below requires a valid admin session)**
```
POST /api/v1/admin/login
     → body: { password }. Compares against the single admin credential in the
       ADMIN_PASSWORD env var (constant-time compare, never logged). On success,
       issues a short-lived signed session token (JWT, signed with an ADMIN_JWT_SECRET
       env var; no server-side session table needed — stateless, verified by expiry +
       signature) set as an httpOnly cookie. This is the entire auth system (§16) —
       no registration, no per-user accounts.

GET  /api/v1/admin/challengers/pending
     → every model_versions row with status='challenger' awaiting a decision, each
       with its own metrics (JSONB) alongside the current champion's metrics for
       side-by-side comparison, and its feature_set (news-free vs. news-inclusive,
       §12) so both lineages are distinguishable in the same list.

POST /api/v1/admin/challengers/{id}/approve
     → promotes this model_version to champion: sets status='champion',
       promoted_at=now(); the previous champion's status flips to 'retired'.
       Application-layer transaction, never two simultaneous champions.

POST /api/v1/admin/challengers/{id}/reject
     → sets status='retired' without promotion. Row is kept (never deleted) for
       audit/reproducibility, per §17.

GET  /api/v1/admin/jobs
     → one row per job_name from `job_runs`: last started_at/finished_at/status,
       for the "Job health" admin panel card (§15).

GET  /api/v1/admin/alerts?limit=50&unacknowledged_only=true
     → `data_quality_alerts` rows, newest first, for the "Data quality alerts" card
       (§15) — provider errors (e.g. an FMP 402 on a given ticker), missing data,
       other anomalies.

POST /api/v1/admin/alerts/{id}/acknowledge
     → marks an alert reviewed (sets acknowledged_at); does not delete it.

GET  /api/v1/admin/news-rollout-progress
     → real news coverage over the trailing 60-trading-day window: days covered,
       percentage, the 80%-over-60-days threshold, and (once estimable) a projected
       date the threshold will be met at the current coverage rate — backs the
       "News-feature rollout progress" admin panel card (§15). Once the threshold is
       met this endpoint reports eligible:true and the card is no longer shown.

POST /api/v1/admin/credit-topups
     → body: { amount_usd, topped_up_at, note? }. Records a manual top-up of the
       Anthropic API's prepaid balance (there is no "current balance" endpoint to
       read this from automatically — see `api_credit_topups` below).

GET  /api/v1/admin/credit-status
     → estimated remaining balance (sum of `api_credit_topups.amount_usd` minus
       cumulative LLM spend logged per §5's job_runs.metadata convention, below),
       trailing daily/monthly burn rate, an estimated days-until-depleted figure,
       and whether that figure is under the low-balance warning threshold (default
       14 days) — backs the "LLM/API credit balance" admin panel card (§15). Crossing
       the threshold also writes a `data_quality_alerts` row so it surfaces there too.
```

Model version history (the admin panel's 4th card, §15) reuses the existing public
`GET /api/v1/model/versions` / `GET /api/v1/model/versions/{id}` above — no separate
admin endpoint needed, since model transparency is intentionally public (§14).

## 2. Database Schema

PostgreSQL. Types are Postgres types; adapt straightforwardly to SQLAlchemy columns. Every `timestamptz` is stored in UTC; convert to ET only at the display layer. `jsonb` is used only where the master spec explicitly calls for flexibility (feature vectors, model metadata) — every other field that has a known shape gets a real column, per §17's instruction to avoid unstructured JSON where relational columns make sense.

```sql
-- ─────────────────────────────────────────────────────────────
-- Universe
-- ─────────────────────────────────────────────────────────────

CREATE TABLE companies (
  id              BIGSERIAL PRIMARY KEY,
  cik             TEXT UNIQUE,              -- SEC CIK, for FilingsProvider lookups
  name            TEXT NOT NULL,
  sector          TEXT,
  industry        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE securities (
  id                      BIGSERIAL PRIMARY KEY,
  company_id              BIGINT NOT NULL REFERENCES companies(id),
  ticker                  TEXT NOT NULL UNIQUE,
  exchange                TEXT NOT NULL,          -- 'NASDAQ' | 'NYSE'
  is_active               BOOLEAN NOT NULL DEFAULT true,   -- false if dropped from S&P 100
  added_to_universe_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  removed_from_universe_at TIMESTAMPTZ
);
CREATE INDEX idx_securities_ticker ON securities(ticker);

-- ─────────────────────────────────────────────────────────────
-- News
-- ─────────────────────────────────────────────────────────────

CREATE TABLE news_articles (
  id                  BIGSERIAL PRIMARY KEY,
  source              TEXT NOT NULL,           -- 'gdelt' | 'marketaux' (default MVP; 'finnhub' reserved if ever added later, see data-ingestion-plan.md §1/§5)
  source_article_id   TEXT,                    -- provider's own id, for exact-match dedup
  title               TEXT NOT NULL,
  url                 TEXT NOT NULL,
  published_time      TIMESTAMPTZ NOT NULL,    -- from the provider — NEVER received_time
  received_time       TIMESTAMPTZ NOT NULL DEFAULT now(),
  sentiment           NUMERIC(4,3),            -- -1.000 .. 1.000
  event_category      TEXT,                    -- Earnings|Guidance|M&A|... |Other (§5)
  importance          NUMERIC(4,3),            -- 0.000 .. 1.000
  is_duplicate_of      BIGINT REFERENCES news_articles(id),  -- null = canonical/original
  raw_payload         JSONB,                   -- full provider response, for reproducibility
  UNIQUE (source, source_article_id)
);
CREATE INDEX idx_news_published_time ON news_articles(published_time);

CREATE TABLE news_company_links (
  id                BIGSERIAL PRIMARY KEY,
  news_article_id   BIGINT NOT NULL REFERENCES news_articles(id),
  security_id       BIGINT NOT NULL REFERENCES securities(id),
  relevance         NUMERIC(4,3),              -- optional weighting for multi-company articles
  UNIQUE (news_article_id, security_id)
);

-- ─────────────────────────────────────────────────────────────
-- Market data
-- ─────────────────────────────────────────────────────────────

CREATE TABLE market_prices (
  id             BIGSERIAL PRIMARY KEY,
  security_id    BIGINT NOT NULL REFERENCES securities(id),
  ts             TIMESTAMPTZ NOT NULL,         -- bar start time
  session_type   TEXT NOT NULL,                -- 'regular' | 'pre' | 'after'
  open           NUMERIC(14,4) NOT NULL,
  high           NUMERIC(14,4) NOT NULL,
  low            NUMERIC(14,4) NOT NULL,
  close          NUMERIC(14,4) NOT NULL,
  volume         BIGINT NOT NULL,
  source         TEXT NOT NULL,                -- 'alpaca_iex' | 'fmp' | ...
  received_time  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (security_id, ts, session_type, source)   -- idempotency: safe to re-run ingestion
);
CREATE INDEX idx_market_prices_security_ts ON market_prices(security_id, ts);

-- ─────────────────────────────────────────────────────────────
-- Fundamentals & macro
-- ─────────────────────────────────────────────────────────────

CREATE TABLE fundamentals (
  id                  BIGSERIAL PRIMARY KEY,
  security_id         BIGINT NOT NULL REFERENCES securities(id),
  period_end          DATE NOT NULL,           -- the fiscal period this describes
  filed_at            TIMESTAMPTZ NOT NULL,    -- ACTUAL publication time — the point-in-time field (§3)
  source              TEXT NOT NULL,           -- 'fmp' | 'sec_edgar' | 'alpha_vantage'
  revenue_growth      NUMERIC(8,4),
  earnings_growth     NUMERIC(8,4),
  eps                 NUMERIC(10,4),
  pe_ratio            NUMERIC(10,4),
  price_to_book       NUMERIC(10,4),
  ev_ebitda           NUMERIC(10,4),
  debt_equity         NUMERIC(10,4),
  net_debt_ebitda     NUMERIC(10,4),
  roe                 NUMERIC(8,4),
  operating_margin    NUMERIC(8,4),
  free_cash_flow      NUMERIC(18,2),
  market_cap          NUMERIC(18,2),
  dividend_yield      NUMERIC(8,4),
  raw_payload         JSONB,
  UNIQUE (security_id, period_end, source)
);
CREATE INDEX idx_fundamentals_filed_at ON fundamentals(security_id, filed_at);

CREATE TABLE filings (
  id                  BIGSERIAL PRIMARY KEY,
  security_id         BIGINT NOT NULL REFERENCES securities(id),
  filing_type         TEXT NOT NULL,           -- '8-K' | '10-Q' | '10-K' | '4' | ...
  accession_number     TEXT NOT NULL,          -- SEC EDGAR's own unique id for the filing
  filed_at            TIMESTAMPTZ NOT NULL,    -- EDGAR's own metadata — the point-in-time field (§3/§4), NEVER the period the statement describes
  period_of_report    DATE,                    -- the period the filing covers, informational only
  url                 TEXT NOT NULL,
  source               TEXT NOT NULL DEFAULT 'sec_edgar',
  raw_payload         JSONB,                   -- filing metadata / XBRL facts payload, for reproducibility
  received_time       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (security_id, accession_number)        -- idempotency: safe to re-run the filings poll
);
CREATE INDEX idx_filings_filed_at ON filings(security_id, filed_at);

CREATE TABLE macro_data (
  id               BIGSERIAL PRIMARY KEY,
  series_id        TEXT NOT NULL,              -- FRED series code, e.g. 'DGS10'
  observation_date DATE NOT NULL,
  value            NUMERIC(18,6) NOT NULL,
  realtime_start   DATE NOT NULL,              -- FRED's own point-in-time vintage fields —
  realtime_end     DATE NOT NULL,              -- use these, never the observation_date alone (§4)
  source           TEXT NOT NULL DEFAULT 'fred',
  UNIQUE (series_id, observation_date, realtime_start)
);

-- ─────────────────────────────────────────────────────────────
-- Feature snapshots, models, training
-- ─────────────────────────────────────────────────────────────

CREATE TABLE model_versions (
  id                BIGSERIAL PRIMARY KEY,
  version_label     TEXT NOT NULL UNIQUE,      -- e.g. 'v1.4.2'
  algorithm         TEXT NOT NULL,             -- 'linear' | 'random_forest' | 'xgboost' | ...
  feature_set       TEXT NOT NULL,             -- 'price_fundamentals_macro' | 'price_fundamentals_macro_news' -- which challenger lineage (spec §12); lets two parallel lineages be tracked in the same table
  trained_at        TIMESTAMPTZ NOT NULL,
  status            TEXT NOT NULL,             -- 'champion' | 'challenger' | 'retired'
  promoted_at       TIMESTAMPTZ,
  hyperparameters   JSONB,                     -- includes recency_weight_halflife_days (default
                                                -- 252, spec §12) alongside any algorithm-specific
                                                -- hyperparameters (tree depth, regularization, etc.)
  metrics           JSONB                      -- validation/backtest metrics summary
);

CREATE TABLE training_runs (
  id                          BIGSERIAL PRIMARY KEY,
  started_at                  TIMESTAMPTZ NOT NULL,
  finished_at                 TIMESTAMPTZ,
  train_window_start          DATE NOT NULL,
  train_window_end            DATE NOT NULL,
  validation_window_start     DATE NOT NULL,
  validation_window_end       DATE NOT NULL,
  test_window_start           DATE,
  test_window_end             DATE,
  resulting_model_version_id  BIGINT REFERENCES model_versions(id),
  status                      TEXT NOT NULL,   -- 'running' | 'completed' | 'failed'
  notes                       TEXT
);

CREATE TABLE feature_snapshots (
  id                  BIGSERIAL PRIMARY KEY,
  security_id         BIGINT NOT NULL REFERENCES securities(id),
  as_of               TIMESTAMPTZ NOT NULL,    -- the point-in-time cutoff used to build this
  features            JSONB NOT NULL,          -- the computed feature vector
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_feature_snapshots_security_asof ON feature_snapshots(security_id, as_of);

-- ─────────────────────────────────────────────────────────────
-- Predictions (immutable once created — never UPDATE these rows)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE prediction_runs (
  id                   BIGSERIAL PRIMARY KEY,
  generated_at         TIMESTAMPTZ NOT NULL,
  model_version_id     BIGINT NOT NULL REFERENCES model_versions(id),
  run_type             TEXT NOT NULL,          -- 'draft' (~03:30 ET, optional) | 'final' (~09:00-09:15 ET)
  target_session_date  DATE NOT NULL,          -- which regular session this predicts
  status               TEXT NOT NULL DEFAULT 'completed'
);
CREATE UNIQUE INDEX idx_one_final_run_per_day ON prediction_runs(target_session_date)
  WHERE run_type = 'final';   -- enforces: only one FINAL run per target session (idempotency)

CREATE TABLE predictions (
  id                          BIGSERIAL PRIMARY KEY,
  prediction_run_id           BIGINT NOT NULL REFERENCES prediction_runs(id),
  security_id                 BIGINT NOT NULL REFERENCES securities(id),
  rank                        SMALLINT NOT NULL,     -- 1..5 (top-5 scope, §14)
  ai_score                    NUMERIC(5,2) NOT NULL, -- 0.00 .. 100.00, user-facing
  raw_predicted_excess_return NUMERIC(8,5) NOT NULL, -- stored, never displayed directly (§1)
  confidence                  TEXT NOT NULL,         -- 'High' | 'Medium' | 'Low'
  explanation                 TEXT NOT NULL,
  feature_snapshot_id         BIGINT NOT NULL REFERENCES feature_snapshots(id),
  price_at_prediction         NUMERIC(14,4) NOT NULL,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (prediction_run_id, security_id)
);

CREATE TABLE prediction_news_links (
  id              BIGSERIAL PRIMARY KEY,
  prediction_id   BIGINT NOT NULL REFERENCES predictions(id),
  news_article_id BIGINT NOT NULL REFERENCES news_articles(id)
);

-- prediction_results is a SEPARATE table populated only after the session closes (§13) —
-- a live prediction has NO row here yet; that's what makes the "no live benchmark_return" rule enforceable.
CREATE TABLE prediction_results (
  id                    BIGSERIAL PRIMARY KEY,
  prediction_id         BIGINT NOT NULL UNIQUE REFERENCES predictions(id),
  actual_return         NUMERIC(8,5),
  benchmark_return      NUMERIC(8,5),
  actual_excess_return  NUMERIC(8,5),
  prediction_error      NUMERIC(8,5),
  direction_correct     BOOLEAN,
  evaluated_at          TIMESTAMPTZ            -- NULL until the ~16:15 ET evaluation job runs
);

-- ─────────────────────────────────────────────────────────────
-- Admin observability (backs the admin panel, spec §15 — no `users` table:
-- the product has no accounts at all, §16; the single admin credential lives
-- only in an env var, never in this database)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE job_runs (
  id             BIGSERIAL PRIMARY KEY,
  job_name       TEXT NOT NULL,        -- 'news_ingestion' | 'market_data_ingestion' |
                                        -- 'feature_generation' | 'prediction_generation' |
                                        -- 'result_evaluation' | 'weekly_training' | 'model_evaluation' |
                                        -- 'champion_performance_check' | 'llm_credit_check' (spec §20)
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ,
  status         TEXT NOT NULL,        -- 'running' | 'success' | 'failed'
  error_message  TEXT,
  metadata       JSONB                 -- e.g. rows processed, tickers skipped; for job_name=
                                        -- 'news_ingestion' also carries the LLM cost of that run
                                        -- as {"llm_tokens_in": N, "llm_tokens_out": N, "llm_cost_usd": N}
                                        -- (spec §5) -- this is what /api/v1/admin/credit-status
                                        -- sums to compute cumulative spend, no separate usage table
);
CREATE INDEX idx_job_runs_name_started ON job_runs(job_name, started_at DESC);

CREATE TABLE api_credit_topups (
  id             BIGSERIAL PRIMARY KEY,
  amount_usd     NUMERIC(10,2) NOT NULL,
  topped_up_at   TIMESTAMPTZ NOT NULL,
  note           TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE data_quality_alerts (
  id               BIGSERIAL PRIMARY KEY,
  job_run_id       BIGINT REFERENCES job_runs(id),  -- nullable: not every alert traces to one job run
  severity         TEXT NOT NULL,      -- 'info' | 'warning' | 'error'
  category         TEXT NOT NULL,      -- 'provider_error' | 'missing_data' | 'anomaly' |
                                        -- 'llm_provider_error' (spec §5, detail distinguishes
                                        -- insufficient_credit | rate_limited | provider_error) |
                                        -- 'champion_performance_degraded' (spec §14) |
                                        -- 'low_credit_balance' (spec §15) | ...
  message          TEXT NOT NULL,      -- e.g. "FMP returned 402 for ticker XYZ, skipped"
  detail           JSONB,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  acknowledged_at  TIMESTAMPTZ         -- NULL until reviewed in the admin panel
);
CREATE INDEX idx_dq_alerts_created ON data_quality_alerts(created_at DESC);
```

**Design notes baked into the schema above:**
- `market_prices` and `prediction_runs` both carry a `UNIQUE` constraint that doubles as the idempotency guard §20 asks for — re-running a job is always safe, it just conflicts/no-ops on the duplicate instead of creating a second row.
- `predictions` rows are written once and never updated (§11's immutability rule) — enforce this at the application layer (no `UPDATE predictions` anywhere in the codebase) since Postgres itself won't stop an UPDATE statement.
- `prediction_results` being a separate, nullable-until-populated table is what makes §13's "no benchmark_return on a live prediction" rule structurally true, not just a frontend convention that could be violated by a bug.
