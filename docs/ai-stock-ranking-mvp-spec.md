# Stock Hyperion — Full MVP Specification

**Product name:** Stock Hyperion (finalized 2026-09-11; earlier planning/working title was "AI Stock Intelligence & Ranking Platform" — the repo directory name `stock-intelligence-saas` is unchanged).
**Status:** Planning complete, ready for Phase 1 implementation.
**Scope:** US equities, S&P 100 universe initially, architected for later expansion to S&P 500 / other markets.
**Not a trading bot.** This is a research and decision-support platform. It never executes trades and never gives personalized investment advice.

This document is the complete, consolidated specification — the original product brief plus every refinement made during planning. Read it top to bottom before writing code. Do not implement everything in one step: work phase by phase (see "Development Approach" near the end), run and test after each phase, and do not move to the next phase if the current one is broken.

---

## 1. Core Product Idea

When the regular US market is closed, the system collects and analyzes: financial news, company-specific news, SEC/company announcements, historical stock prices, OHLCV data, trading volume and volume changes, recent price momentum, volatility, company fundamentals, valuation metrics, earnings information, sector information, relevant macroeconomic indicators, market/index performance, and other useful publicly available signals.

The system combines these signals with machine learning to rank stocks by their expected performance during the next regular trading session.

The primary output is NOT "BUY NVDA". It looks like:

```
Stocks with the Highest Expected Positive Movement
1. NVDA — AI Score: 91/100
2. AMD — AI Score: 87/100
3. META — AI Score: 82/100
```

For every ranked stock, show the factors that influenced the ranking:

```
NVDA
AI Score: 91/100
Confidence: High
Prediction horizon: Next regular trading session
Main factors:
- Positive earnings surprise
- Strong after-hours momentum
- Positive company news
- Increased trading volume
- Strong sector momentum
- Healthy fundamentals
```

**Important display principle (settled during planning):** the product never shows a raw numeric "predicted return %" to end users (e.g. never "predicted: +2.1%"). The forward-looking output surfaced to users is always the AI Score (0–100), Confidence, and Rank — never a literal percentage forecast, which would read as an overconfident guarantee. The raw `predicted_excess_return` is still computed and stored internally (see §9 and §17) for evaluation and backtesting, it is simply not displayed as a headline number. Only realized, historical values (actual return, benchmark return, etc.) are shown as percentages, and only after the session that produced them has closed.

The platform must clearly state that these are model-generated research signals, not guaranteed investment returns or personalized investment advice.

## 2. Prediction Target

Avoid vague targets like "will this stock go up?". Use a measurable ML target:

```
next_session_stock_return - next_session_market_return
```

Benchmark initially = S&P 500. This estimates whether a stock is expected to outperform the broader market during the next regular trading session. Also store the raw next-session stock return.

Design the system so alternative prediction horizons can be added later (next 30 minutes, next 2 hours, next 5 trading days, etc.). For the MVP, use only the next regular trading session.

**Forward-looking note on "regular session":** Nasdaq has an SEC-approved proposal to extend US equities trading to 23 hours a day, 5 days a week ("Global Trading Hours"), targeting a December 2026 launch (a ~20:00–21:00 ET daily maintenance window would be the only closed period on weekdays; weekends stay fully closed). This does not need to be implemented now, but the "regular session" / prediction-horizon boundary must be a **configurable value**, not hardcoded, so the definition can be updated later without an architecture change.

## 3. Strict Point-in-Time Data

The system must NEVER use information that was unavailable when a prediction was generated. Every piece of data preserves timestamps: `event_time`, `published_time`, `received_time`, `prediction_time`.

Financial statements become available to the model only from their actual publication time, NOT from the historical period they describe. News published after a prediction must never appear in that prediction's feature set. The backtesting system must strictly prevent look-ahead bias and data leakage.

## 4. Data Ingestion Layer

Modular provider architecture. Do NOT tightly couple the application to one paid API. Use interfaces:

```
NewsProvider
├── ProviderA
├── ProviderB
└── FutureProvider
MarketDataProvider
├── ProviderA
└── FutureProvider
FundamentalsProvider
MacroDataProvider
FilingsProvider
```

All API keys in environment variables. Never hardcode secrets. Create `.env.example`, never commit `.env`.

**MVP provider decision (settled during planning — all free, no paid API required to start):**

- **FilingsProvider:** SEC EDGAR (fully free, no API key; requires a descriptive `User-Agent` header per SEC's fair-access policy). Also the source for raw XBRL company financial facts (`companyfacts` endpoint).
- **MacroDataProvider:** FRED (Federal Reserve Economic Data) — free, register for a free API key, effectively unlimited for this use case (interest rates, Treasury yields, CPI, etc.), with native point-in-time vintages.
- **MarketDataProvider:** Alpaca free tier (IEX feed, 200 calls/min, historical bars back to 2016) as primary, with FMP as a cross-check.
- **FundamentalsProvider:** SEC EDGAR XBRL `companyfacts` (free, no key beyond the same descriptive `User-Agent` as the FilingsProvider) as **primary**, with FMP kept configured as an opportunistic secondary/cross-check for whichever tickers it does serve. **Amended during Phase 3 implementation, evidence-based (spec §27: data quality over following a plan the evidence has since contradicted):** real calls against FMP's free tier during Phase 1/3 showed it returns HTTP 402 ("Premium Query Parameter") for roughly 60% of the S&P 100 universe — i.e. most of the universe is gated behind a paid plan, not just the exotic tickers. EDGAR XBRL is free and covers 100% of tickers, so it was promoted to primary instead. This did cost real extra engineering effort FMP wouldn't have required: XBRL companies never tag a standalone fact for fiscal Q4 (only Q1–Q3 are individually reported; Q4 has to be derived as annual − Q1 − Q2 − Q3), and the same financial concept (e.g. revenue) is frequently tagged under different XBRL element names in different years for the same company, so tag values must be pooled across known aliases rather than trusting whichever tag is found first. Both were real bugs hit and fixed during implementation, verified against real filings (Apple, ExxonMobil) before trusting the pipeline. *(Original MVP plan, kept for reference: FMP free tier — 250 calls/day, company ratios/financials + EOD price cross-check — as primary, with EDGAR XBRL as a structured backstop. That ordering turned out not to hold up against FMP's actual current free-tier access, hence the amendment above.)*
- **NewsProvider:** GDELT (free, no key, DOC 2.0 API) as primary for both per-ticker and thematic/macro news, plus Marketaux (100 requests/day) for broad market-wide sentiment context. **Finnhub is deliberately excluded from the default MVP** — its free tier is licensed for personal/non-commercial use only, and it's ambiguous (unconfirmed even at its paid Starter tier) whether that permits a deployed, publicly-reachable app. Since news-freshness needs are modest (the pipeline locks one prediction per day near open, not intraday), GDELT batched keyword queries + Marketaux cover this without that legal risk or added cost. See `data-ingestion-plan.md` §1/§3 for the exact provider→role map and schedule this implies, and Finnhub can be added later, behind the same `NewsProvider` interface, as a paid drop-in if higher-frequency per-ticker news is ever needed.
- Alpha Vantage (free tier: ~25 calls/day) is kept configured as a documented spot-check fallback only, not part of the scheduled pipeline. Polygon.io (free tier is 15-minute-delayed, 5 calls/min) was evaluated and is sandbox-only, not used.
- None of the providers in the default MVP require a paid plan. Every provider sits behind its interface, so swapping any one for a paid plan later (e.g. FMP Starter, or Finnhub once its commercial terms are confirmed) is a config change, not a rewrite.

## 5. News Processing

For each article identify: affected company/companies, ticker, publication time, source, title, URL/reference, sentiment, event category, estimated importance, novelty/duplicate status.

Event categories: Earnings, Guidance, M&A, New contract, Product launch, Lawsuit, Regulatory action, Management change, Analyst upgrade/downgrade, Dividend, Share buyback, Capital raise, Layoffs, Cybersecurity incident, Macroeconomic exposure, Other.

Use an LLM or financial NLP model primarily for information extraction and interpretation, not as the final stock-price predictor. Convert news into structured numerical/model features, e.g.:

```
news_sentiment = 0.81
news_importance = 0.92
positive_news_24h = 4
negative_news_24h = 1
earnings_event = 1
analyst_upgrade = 1
```

Implement duplicate detection so the same wire story republished by many outlets isn't counted as many independent signals.

**LLM choice (added during planning, finalized):** use a real LLM API — Claude Haiku 4.5 via the Anthropic API — rather than a hand-written heuristic/rule-based extractor. Rationale: sentiment/category/importance extraction from a short article is a well-bounded classification task Haiku handles reliably, real cost is small (~$3-5/month at the project's estimated news volume, verified against current published pricing), and using a genuine model from day one means the news signal's real usefulness can actually be measured (a heuristic's output wouldn't be trustworthy evidence either way). If backtest evidence later shows the news signal is valuable but extraction quality is the bottleneck, upgrading just this call to a larger model (e.g. Sonnet) is a one-line change — start cheap, upgrade only on evidence, never the reverse.

**LLM failure handling (added during planning, finalized):** an LLM call can fail for reasons outside the article's own quality — rate limiting, a transient provider error, or the API key's spend limit being hit (§15's admin credit tracking is meant to make the last one rare, not impossible). None of these may ever crash the news ingestion job or block the rest of the pipeline. On a failed extraction: store the article's raw fields (source, url, title, published_time) as usual, leave `sentiment`/`event_category`/`importance` NULL for that row, log a `data_quality_alerts` entry (severity `error`, category `llm_provider_error`, with the underlying error distinguished — e.g. `insufficient_credit` vs. `rate_limited` vs. `provider_error` — in `detail`), and let the job_run itself still finish with `status='success'` (a partial enrichment gap is a data-quality issue, not a job failure — the same job-succeeds-with-a-logged-alert pattern used for any other provider error, e.g. an FMP 402 on a given ticker, per the `data_quality_alerts` design in `api-and-schema-plan.md`). A day with a meaningful fraction of failed extractions simply doesn't count toward the news-feature rollout coverage window (§15) — the two mechanisms compose correctly with no special-casing needed.

## 6. Market Features

1-day / 5-day / 20-day / 60-day return, trading volume, relative volume, volume change, realized volatility, gap percentage, pre-market return (used — see §11), after-hours return, sector performance, benchmark performance, relative strength, moving averages, a small set of documented technical indicators. Keep the feature set interpretable — do not blindly create hundreds of indicators.

## 7. Fundamental Features

Revenue growth, earnings growth, EPS, P/E, price-to-book, EV/EBITDA, debt/equity, net debt/EBITDA, ROE, operating margin, free cash flow, market capitalization, dividend yield. Fundamentals change far less often than market/news data — cache/update accordingly.

## 8. Macro and Market Context

S&P 500 movement, Nasdaq movement, sector ETF/index movement, interest-rate information, Treasury yields, volatility index, FX where relevant, commodity prices where relevant. Architecture must allow more macro variables later.

## 9. Machine Learning

Do not start with deep learning. Build strong baselines first: linear/regularized regression baseline → Random Forest baseline → gradient boosting (XGBoost or LightGBM) if it earns its complexity.

The product's main output is a ranking — evaluate both prediction quality and ranking quality. Model output per ticker: `predicted_excess_return`, `prediction_score`, `confidence`, `rank`. Normalize the user-facing score to 0–100, but preserve the underlying raw model output (stored, not displayed — see the display principle in §1).

## 10. Explainability

Every ranked stock includes an explanation of why it received its score. Do NOT ask an LLM to invent reasons after the fact — use real feature importance / SHAP-style explanations, then optionally use an LLM only to turn those factual signals into readable prose. The LLM must only explain evidence actually provided to it.

## 11. Prediction Schedule (amended during planning)

Inference is separate from training. Predictions can update frequently without retraining.

- **News ingestion:** every 10–15 minutes when relevant.
- **Market data:** updated periodically while extended/regular markets are active.
- **Main prediction — timing (settled):** the process runs through the entire closed window, but the **final, official prediction snapshot is locked shortly before the regular session opens (~09:00–09:15 ET, i.e. 15–30 minutes before the 09:30 ET open)** — not before pre-market starts. This is deliberate: pre-market data (04:00–09:30 ET) is a genuinely strong signal for the next session (gap-up/gap-down forms there) and using it does not violate point-in-time correctness, because by 09:00–09:15 ET that pre-market activity has already happened — it is not future information relative to the still-unopened regular session. Sequence:
  1. 20:00–04:00 ET: fully closed window. Continuous news/SEC-filing ingestion. Optionally, a **draft/preview snapshot** may be published around ~03:30 ET for early transparency — clearly marked as non-final.
  2. 04:00–09:00 ET: pre-market session. Pre-market price/volume ingestion continues; features like `pre_market_return` and `gap_percentage` are computed and kept live.
  3. ~09:00–09:15 ET: feature snapshot is frozen for the last time, the model runs inference, and the **final prediction snapshot is written immutably and published**. This is the snapshot used for all downstream performance tracking.
  4. 09:30 ET: regular session opens — the predicted event begins. No further changes to the snapshot.

Each prediction snapshot contains: `prediction_id`, `generated_at`, `model_version`, `ticker`, `rank`, raw predicted return, normalized AI score, confidence, feature snapshot, explanation, relevant news IDs, price at prediction time. Once published, a snapshot is NEVER silently modified — a later prediction is a new version/snapshot, the old one is retained forever.

## 12. Model Training Schedule

Do not retrain on every news article. Daily: collect data, generate predictions, collect actual outcomes, calculate performance. Weekly: build an updated training dataset, train challenger model(s), run time-aware validation/backtesting, compare each challenger vs. current production (champion) model. Only promote a challenger if it passes defined performance and stability criteria — promotion is always a human (admin) decision (§15), never automatic. Champion/challenger architecture. Design for incremental/online learning experiments later, but do not make uncontrolled self-modification part of the MVP.

**Two parallel challenger lineages (added during planning, finalized):** a news-free challenger trains every week regardless of news-feature eligibility, on the full, ever-growing price/fundamentals/macro dataset, with recency weighting (below) — this lineage never stops. Once the news-feature rollout threshold is met (§15), a second, news-inclusive challenger also trains each week, on price/fundamentals/macro + news features, restricted to the (still growing) window where real news coverage exists — the same recency weighting applies once that window itself exceeds the half-life below. Both are compared against the current champion the same week; if more than one beats it, both appear in the admin approval queue and the owner decides which (if any) to promote. `model_versions.feature_set` (see `api-and-schema-plan.md`) records which lineage a given model belongs to.

**Recency-weighted training, not flat-weighted (added during planning, finalized):** training on the full history with every row weighted equally makes each week's retrain nearly a no-op once years of data have accumulated — one new week is a vanishingly small fraction of a multi-year dataset, so the model barely moves and weekly retraining stops earning its cost. The fix is not a shorter training window (that would silently stop using genuinely useful older data, still sitting untouched in the database) — it's exponential recency weighting: every row, all the way back to the earliest available data, stays in the training set, but its weight decays with age, `weight = exp(-age_in_days / halflife)`. Default **halflife: 252 trading days (~1 year)**. Grounded in real published practice, not guessed: MSCI/Barra's USE4 equity risk model methodology uses ~84-252 trading-day half-lives for the faster-moving quantity (volatility) and a longer ~504-trading-day (~2-year) half-life for the slower-moving one (factor correlation/return relationships) — precisely because volatility should react faster and return relationships should stay steadier. Our task (predicting returns from features) is the slower-moving kind, so 252 days is deliberately the more reactive end of that range rather than the full ~2 years, chosen for a single-owner MVP where staying visibly responsive matters more than in an institutional risk desk — this gives an effective operative window of roughly 2-3 years (weight drops to ~25% at 2 half-lives, ~12% at 3), long enough to span multiple market regimes without over-reacting to short-term noise. All standard regression/tree libraries (scikit-learn, XGBoost, LightGBM) accept a `sample_weight` argument directly — no custom training loop needed. The halflife value is recorded in `model_versions.hyperparameters` (see `api-and-schema-plan.md`) per trained model, so it's visible in the admin panel's model version history (§15) and can be revisited later against real backtest evidence, same as any other hyperparameter — not a permanent, unquestionable constant.

**"Champion" is a status, not a separate training method (added during planning, finalized):** there is no distinct "champion training process" versus "challenger training process" — every model in `model_versions`, whichever status it currently holds, is trained by the identical procedure above (weekly cadence, recency weighting, same feature_set rules per lineage). "Champion" simply means "the model currently holding that status after winning its promotion"; the very first model ever trained (before any promotion has happened) is trained the same way and becomes champion by default, having no incumbent to beat. A model's training methodology never changes when its status changes.

**Why weekly retraining remains correct given recency weighting:** daily would retrain on a single day's data, which is dominated by market noise rather than genuine signal, and would require the owner to review challenger promotions daily — not sustainable for a single-owner MVP. Monthly would leave the model stale for a month at a time (a month is long enough for a real regime shift — a Fed decision, an earnings season) and would be out of step with every other weekly mechanism already built (challenger comparison, job health, news-rollout tracking). Weekly is the balance: five trading days is enough new, non-trivial information to justify a refit, short enough that the model doesn't go stale, and light enough that a solo admin can sustain the review cadence. Recency weighting is what makes each weekly refit actually matter (§12 above) — switching the retraining cadence itself was never the right fix.

## 13. Feedback Loop (amended: display timing clarified)

After the predicted session finishes, retrieve actual market results. For every prediction store: `predicted_return`, `actual_return`, `benchmark_return`, `actual_excess_return`, `prediction_error`, `direction_correct`, `rank`, `model_version`.

**Clarification settled during planning:** these result fields belong to a separate table (`prediction_results`, populated only after the session closes — see §17) and are `NULL`/absent until then. A prediction generated before the market opens (see §11) has no `benchmark_return` or `actual_return` yet by construction — the live/current-day prediction view must never display these fields; only predictions from **past, already-closed sessions** show them. This was already implied by the original schema split between `predictions` and `prediction_results` (§17) and by §11's snapshot-content list (which does not include result fields) — stated explicitly here to avoid ambiguity.

Historical predictions and results are never deleted, even when wrong — they become future training data.

## 14. Performance Tracking

Radical transparency is a core product feature. The frontend prominently shows a **"Last 7 Days"** view: for each previous prediction — stock, rank, predicted movement (AI Score, not a raw %, per §1), actual movement, correct/incorrect direction, benchmark performance.

**Scope clarification settled during planning:** the platform ranks and displays its **top 5** picks per session (not the full 100-stock universe as a user-facing list) — the model may internally score more of the universe, but the product's surface area is the top-N ranking, consistently, both for the live daily view and for each past day's detail view. A past day's detail page shows those top 5 with their realized outcome (see §15 for the exact layout).

Aggregate metrics: Top-N hit rate, mean actual return of ranked stocks, mean excess return vs. benchmark, MAE/RMSE, directional accuracy, ranking correlation, Precision@K, maximum drawdown for a clearly defined hypothetical strategy, risk-adjusted performance where meaningful. Never cherry-pick only successful predictions. Clearly distinguish backtested performance, paper/live model predictions, and hypothetical portfolio performance.

**Absolute performance degradation monitoring (added during planning, finalized):** champion/challenger comparison (§12) is a *relative* check — a challenger only replaces the champion if it demonstrably beats it, so the system can never silently promote something worse. But it does not protect against the champion's own *absolute* performance drifting down over time in a changing market while no better challenger has yet emerged — that would currently only be visible if someone happens to look at the public "Last 7 Days" view. That's not good enough on its own. So: a scheduled check compares the champion's trailing 30-day hit rate/directional accuracy against its own historical baseline (e.g. its validation-time metrics, recorded in `model_versions.metrics`); if it drops meaningfully below that baseline (a configurable threshold, not a one-time guess), it writes a `data_quality_alerts` row (severity `warning`, category `champion_performance_degraded`) so it surfaces in the admin panel proactively, the same way a low LLM credit balance does. This never auto-replaces or auto-pauses the champion — same human-in-the-loop principle as promotion (§12) — it only guarantees the owner is told, rather than having to remember to check.

## 15. Frontend

Clean, modern financial dashboard. See §19 for the finalized visual design system — do not default to a generic template; follow it.

**Main page:**
1. Current prediction snapshot (today's top 5, AI Score, Confidence, expected-movement framing — never a raw % prediction, per §1)
2. Explanation per stock (real factors, from §10)
3. Important supporting news per stock
4. Prediction timestamp (`generated_at`) and model version
5. A visible, non-alarming disclaimer: model-generated research signal, not investment advice, no guarantee of returns (see §23 for exact language)
6. "Last 7 Days Performance" section (see §14)

**Past-day detail page** (opened from a specific date in "Last 7 Days" — settled during planning):
- Header: the date, that prediction's `generated_at` timestamp, `model_version` used.
- A small context row: that session's S&P 500 return (benchmark, single value for the whole day) and that day's hit rate.
- The day's top-5 ranking table, extended with realized outcome columns: `#`, Symbol + company, AI Score, Confidence, **Actual return**, **vs S&P 500 (excess)**, **Result** (correct/incorrect direction — visual check/x, not a raw predicted % — see §1 and §13).
- A "Notable news that day" section: the news items that were material inputs to that day's top picks (headline, related ticker, source, timestamp) — replaces any idea of listing the full universe; the product only ever surfaces the top 5 plus their supporting context.
- That day's aggregate stats (hit rate, avg excess return, directional accuracy) as a small stat-tile row.

**Stock detail page:** ticker/company, current ranking, AI score, confidence, explanation, recent relevant news, fundamental metrics, recent price/volume information (candlestick chart — see §19 for the charting library choice), historical predictions for that stock, actual outcomes.

Also include methodology and limitations pages.

**Admin panel (added during planning, finalized — owner-only, not part of the public dashboard):** a separate, gated section (e.g. under `/admin`) visible only to the product owner, never to end users. Contains:
- **Challenger approval queue** — for each challenger awaiting a decision (§12), its comparison metrics against the current champion, and Approve/Reject actions. In a given week this may show challengers from both lineages (news-free and, once eligible, news-inclusive — §12) side by side. MVP default is semi-automatic promotion: the system trains and evaluates challengers on schedule, but a human approves the actual promotion, at least until enough promotions have gone well to justify switching to fully automatic (a later, revisitable setting, not a one-time decision).
- **Job health** — last run time and status (success/fail) for every scheduled job in §20 (news ingestion, market data, feature generation, prediction generation, result evaluation, weekly training, model evaluation, champion performance check, LLM credit check).
- **Data quality alerts** — provider errors, missing data, and other anomalies surfaced here (feeds from the structured logging in §25).
- **Model version history** — every `model_versions` row (champion/challenger/retired), including which feature-set lineage it belongs to (news-free vs. news-inclusive, §12) and its metrics, for audit/reproducibility.
- **News-feature rollout progress** (added during planning) — before the news-inclusive lineage becomes eligible, show progress toward the rollout threshold below: real news coverage achieved so far within the trailing 60-trading-day window (e.g. "38/60 trading days covered, 63% — threshold is 80% coverage over 60 trading days"), and, once available, an estimated date the threshold will be met at the current coverage rate. Once eligible, this card is replaced by the news-inclusive lineage's entries in the challenger approval queue and model version history above.
- **LLM/API credit balance** (added during planning, finalized) — the Anthropic API used for news NLP (§5) is prepaid, and Anthropic exposes no direct "current balance" endpoint (only historical usage/cost). So: the admin records each top-up here (amount + date, a simple form); the system already knows the token cost of every LLM call it makes (§5) and logs it; the card shows estimated remaining balance (sum of recorded top-ups minus logged spend), the trailing daily/monthly burn rate, an estimated days-until-depleted figure, and a low-balance warning once that estimate drops under a configurable threshold (default 14 days) — which also feeds a `data_quality_alerts` entry so it isn't easy to miss.

**News-feature rollout rule (added during planning, finalized — resolves an open question about the news features defined in §5):** because historical news is deliberately not backfilled (see `data-ingestion-plan.md` §5 — backfilling from a different source than production would reintroduce train-serve skew), the first baseline model(s) train on price/fundamentals/macro features only. News-derived features (`news_sentiment`, `positive_news_24h`, etc., from §5) are only included in a challenger's training run once real, live-collected news coverage meets an explicit, data-driven bar — not a calendar date — real news coverage present for at least 80% of trading days across a minimum **60-trading-day** window (roughly a quarter of live operation). Rationale: 60 trading days isn't chosen for training-row volume (even 30 days already gives ~3,000 stock-day rows, plenty) — it's chosen so the held-out backtest window used to compare the news-inclusive challenger against the champion each week (§12) spans multiple market regimes (up/down/high-vol/low-vol) instead of being dominated by one noisy short stretch. Below that bar, a challenger's news features would be trained on data too sparse to trust, and any early comparison result would be statistically unreliable.

## 16. SaaS Architecture

**Fully public product, no user accounts (finalized during planning):** there is no FREE/PRO tiering, no login/signup flow, and no payments — this was considered and deliberately dropped, not deferred. Every visitor sees the same dashboard, past-day pages, and stock detail pages; nothing is gated behind an account. No Stripe or other payment provider integration. If a genuine reason to add accounts emerges later (e.g. a feature that is inherently per-user, not just a paywall), design it fresh at that time against real usage data rather than resurrecting this tiering scheme.

**Minimal admin auth (added during planning, finalized):** the only access-gated area in the whole product is the admin panel (§15). Keep it intentionally minimal for MVP: a single admin credential (or password) read from an environment variable, gating the `/admin` routes. This is not a user-accounts system — it exists solely to keep the admin panel owner-only, and does not need to evolve into anything more elaborate since there is no broader auth system it needs to later merge into.

## 17. Database

PostgreSQL for production. Proper tables/models for at least: `companies`, `securities`, `news_articles`, `news_company_links`, `market_prices`, `fundamentals`, `macro_data`, `filings`, `feature_snapshots`, `prediction_runs`, `predictions`, `prediction_news_links`, `prediction_results`, `model_versions`, `training_runs`, `job_runs`, `data_quality_alerts`, `api_credit_topups` (the last three back the admin panel, §15 — see `api-and-schema-plan.md`). No `users` table — the product has no accounts (see §16). Use migrations. Avoid unstructured JSON where relational columns make sense; JSON/JSONB is fine for flexible model metadata and feature snapshots.

Note (from §13): `prediction_results` is a separate table from `predictions`, populated only after the session closes, holding `actual_return`, `benchmark_return`, `actual_excess_return`, `prediction_error`, `direction_correct`.

## 18. Backend

Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Pydantic. Organize code into clear modules:

```
app/
├── api/
├── core/
├── db/
├── models/
├── schemas/
├── providers/
├── services/
├── ml/
├── jobs/
└── tests/
```

Keep data ingestion, feature engineering, ML training, ML inference, API routes, and database logic separated — never everything in one file.

## 19. Visual Design System & Frontend Stack (finalized during planning)

Next.js + TypeScript. **Styling:** Tailwind CSS + shadcn/ui components. **Charting:** TradingView's open-source `lightweight-charts` library for price/volume/candlestick visualizations — purpose-built for exactly this kind of chart, meaningfully better here than a generic charting library.

The visual identity is settled (built and approved as an interactive mockup during planning) — a bold, dark, "prediction-market instrument panel" aesthetic, deliberately not a generic AI-chatbot look:

**Color tokens:**
| Token | Hex | Usage |
|---|---|---|
| `bg` | `#070707` | Page background |
| `panel` | `#111214` | Card/panel background |
| `panel-border` | `#24262A` | Card borders, table row dividers (`#1B1C1F` for row dividers specifically) |
| `ink` | `#F4F5F6` | Primary text on dark |
| `ink-soft` | `#9195A0` | Secondary text / labels |
| `ink-faint` | `#6C707B` | Tertiary text (timestamps, table headers) |
| `ink-dim` | `#55585F` | Least prominent (row numbers, "/100" suffix) |
| `green` (gradient to `#0BAE6C`) | `#17F095` → `#0BAE6C` (hero card gradient); flat `#12E28A` (score numerals, pills, positive values) | AI Score numerals, positive values, "Bullish", "High" confidence pill, primary hero cards |
| `blue` | `#2F5BFF` | "Medium" confidence pill, benchmark/market-context stat cards, secondary accent |
| `negative` | `#FF6B5E` | Negative returns, "Incorrect" result |
| `white-card` | `#FFFFFF` bg / `#101114` text | Third stat-tile in a 3-tile row, for contrast against the green/blue tiles |

Confidence pills: "High" = solid green fill (`#12E28A`) with near-black text (`#06120C`); "Medium" = solid blue fill (`#2F5BFF`) with light text (`#EAF0FF`) — flat, fully-saturated fills, not muted/outlined.

**Typography:** `Archivo Black` (Google Fonts) for hero numerals (AI Score, big stat-tile numbers) and the wordmark — used sparingly, only for the most important number on a given card. `Archivo` (weights 500–800) for headers, labels, tags, body UI text. `IBM Plex Mono` (weights 400–600) for anything tabular: tickers' adjacent data, percentages, timestamps, table cells — use `font-variant-numeric: tabular-nums`.

**Components:** cards use `border-radius: 16px`; pills/badges use fully-rounded `border-radius: 20px`. The signature "hero card" pattern is a large card filled with the green gradient, holding one big `Archivo Black` number (used for the featured stock's AI Score, and for stat-tile rows like 7-day hit rate / avg excess return / directional accuracy — alternating green/blue/white fills across a row of 3, mirroring how a stat card grid reads at a glance). Icons are simple stroke-based inline SVG (never emoji).

A working interactive mockup (Main dashboard, a past-day detail page, a stock detail page, plus two rejected alternate directions kept for reference) was built and approved in this planning session. **If the coding agent cannot see that mockup directly, the color/type/component tokens above are the complete source of truth — build from them, not from memory or a generic dashboard template.** Attaching a screenshot of the approved mockup alongside this document is recommended as a visual reference but is not strictly required given the tokens above.

## 20. Background Jobs

Scheduled/background jobs needed: news ingestion, market-data ingestion, feature generation, prediction generation, result evaluation, weekly training, model evaluation, champion performance-degradation check (§14), and LLM credit-balance check (§15). Design them to be idempotent — prevent duplicate articles, duplicate predictions, duplicate price records. Choose the simplest reliable scheduler/worker architecture for the MVP, but isolate job logic so a heavier queue (Celery/Redis or similar) could be introduced later if actually needed.

## 21. Backtesting

Proper time-series backtesting. Never shuffle financial time-series data. Use chronological or walk-forward splits (e.g. train 2019–2023, validate 2024, test 2025, or a rolling equivalent). All features must reflect what was actually knowable at prediction time. Include transaction-cost assumptions when evaluating any hypothetical trading performance.

## 22. Security

Secrets only in environment variables, `.env` git-ignored, input validation, rate limiting where useful, secure admin-credential handling (the only auth surface — see §16), no secret API keys exposed to frontend JavaScript, HTTPS in production, dependency management, structured logging, safe error responses.

## 23. Legal / Product Language

Research and decision-support product. Never present outputs as guaranteed returns. No personalized portfolio recommendations. No automatic trading. Avoid: "Guaranteed winner", "Buy this stock now", "Risk-free return". Use: "Model ranking", "Expected positive-movement score", "Research signal", "Model confidence", "Historical model performance". Include disclaimers designed so legal/compliance review can modify the language later without a rebuild.

## 24. Testing

Tests for: timestamp correctness, prevention of look-ahead bias, duplicate news detection, feature generation, return calculations, ranking, prediction snapshot immutability, model versioning, API endpoints. Financial calculations must have unit tests.

## 25. Observability

Structured logs for: ingestion failures, provider/API errors, prediction jobs, model training, model promotion, missing data, unusual data quality. Store enough metadata that any historical prediction is traceable: prediction → model version → feature snapshot → underlying data → relevant news.

## 26. Development Approach

Work incrementally, in phases. Before major code: inspect the repo, explain the proposed architecture, make an implementation plan, identify which external APIs/data need credentials, separate what's implementable now from what needs external access. Then build in phases:

1. Project structure, PostgreSQL, company universe (S&P 100), historical market data.
2. News ingestion and normalization.
3. Feature engineering.
4. Historical dataset construction with strict point-in-time correctness.
5. Baseline ML model and backtesting.
6. Prediction pipeline and immutable prediction snapshots.
7. Result evaluation and 7-day performance tracking.
8. Backend API.
9. Frontend dashboard (using the design system in §19).
10. Scheduled jobs and deployment.
11. Champion/challenger training pipeline.
12. Testing, documentation, observability, security hardening.

At the end of every phase: run the code, run relevant tests, fix errors, explain what was implemented, commit logically separated changes, and do not proceed if the current phase is broken.

## 27. Engineering Principles

correctness > complexity · data quality > model complexity · point-in-time correctness > impressive backtests · transparent performance > marketing claims · modular architecture > vendor lock-in · simple baseline > premature deep learning · reproducibility > uncontrolled self-learning. Never fabricate API responses or pretend an integration works without real credentials/data — use a clearly labeled mock/demo provider behind the same interface if real data is unavailable during development.

## 28. MVP Success Criteria

The MVP succeeds when it can automatically: collect real market/news data; build point-in-time features; run a trained model; rank the S&P 100 universe (surfacing the top 5) before the next regular session; permanently store the prediction; explain the ranking with real underlying signals; observe the actual next-session result; compare prediction with reality; show the last 7 days of predictions and outcomes; retrain a challenger model on a schedule; evaluate challenger vs. champion; promote a model only under explicit controlled criteria; expose the system through the usable web dashboard described in §19.
