// Thin typed client over the Phase 8 backend API
// (docs/api-and-schema-plan.md §1). Server Components call the
// server-internal base URL (reachable inside the docker network); the
// browser (admin login/actions) uses the publicly published one.

export const SERVER_API_BASE =
  process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
export const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export interface NewsRef {
  id: number;
  title: string;
  url: string;
  source: string;
  published_time: string;
}

export interface RankingItem {
  rank: number;
  ticker: string;
  company_name: string;
  ai_score: number;
  confidence: string;
  explanation: string;
  related_news: NewsRef[];
}

export interface RankingItemWithResult extends RankingItem {
  actual_return: number | null;
  benchmark_return: number | null;
  vs_benchmark: number | null;
  direction_correct: boolean | null;
}

export interface RankingResponse {
  generated_at: string;
  model_version: string;
  top5: RankingItem[];
}

export interface RankingDetailResponse {
  target_session_date: string;
  generated_at: string;
  model_version: string;
  benchmark_return: number | null;
  hit_rate: number | null;
  top5: RankingItemWithResult[];
  notable_news: NewsRef[];
}

export interface RankingHistoryTopPick {
  ticker: string;
  ai_score: number;
  actual_return: number | null;
  vs_benchmark: number | null;
  direction_correct: boolean | null;
}

export interface RankingHistoryItem {
  target_session_date: string;
  hit_rate: number | null;
  mean_excess_return: number | null;
  top_pick: RankingHistoryTopPick | null;
}

export interface RankingHistoryResponse {
  items: RankingHistoryItem[];
}

export interface FundamentalsSummary {
  period_end: string;
  eps: number | null;
  pe_ratio: number | null;
  revenue_growth: number | null;
  operating_margin: number | null;
  market_cap: number | null;
  dividend_yield: number | null;
}

export interface StockDetailResponse {
  ticker: string;
  company_name: string;
  sector: string | null;
  current_rank: number | null;
  ai_score: number | null;
  confidence: string | null;
  explanation: string | null;
  latest_fundamentals: FundamentalsSummary | null;
}

export interface PriceBar {
  ts: string;
  session_type: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockPricesResponse {
  ticker: string;
  bars: PriceBar[];
}

export interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  published_time: string;
  sentiment: number | null;
  event_category: string | null;
}

export interface StockNewsResponse {
  ticker: string;
  articles: NewsItem[];
}

export interface StockPredictionItem {
  target_session_date: string;
  rank: number;
  ai_score: number;
  confidence: string;
  actual_return: number | null;
  vs_benchmark: number | null;
  direction_correct: boolean | null;
}

export interface StockPredictionsResponse {
  ticker: string;
  predictions: StockPredictionItem[];
}

export interface PerformanceSummary {
  window: string;
  n_predictions: number;
  n_days: number;
  hit_rate?: number;
  directional_accuracy?: number;
  mean_actual_return?: number;
  mean_excess_return?: number;
  mean_benchmark_return?: number;
  mae?: number;
  rmse?: number;
  mean_rank_ic?: number | null;
  hypothetical_portfolio?: Record<string, number> | null;
}

export interface ModelVersionSummary {
  id: number;
  version_label: string;
  algorithm: string;
  feature_set: string;
  status: string;
  trained_at: string;
  promoted_at: string | null;
  headline_metrics: Record<string, number>;
}

export interface ModelVersionListResponse {
  versions: ModelVersionSummary[];
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T | null> {
  const response = await fetch(url, { cache: "no-store", ...init });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Request to ${url} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  latestRanking: () => getJson<RankingResponse>(`${SERVER_API_BASE}/api/v1/rankings/latest`),
  rankingForDate: (date: string) =>
    getJson<RankingDetailResponse>(`${SERVER_API_BASE}/api/v1/rankings/${date}`),
  rankingHistory: (limit = 7) =>
    getJson<RankingHistoryResponse>(`${SERVER_API_BASE}/api/v1/rankings/history?limit=${limit}`),
  stockDetail: (ticker: string) =>
    getJson<StockDetailResponse>(`${SERVER_API_BASE}/api/v1/stocks/${ticker}`),
  stockPrices: (ticker: string, sinceDays?: number) => {
    const params = new URLSearchParams({ session: "regular" });
    if (sinceDays !== undefined) {
      const from = new Date(Date.now() - sinceDays * 24 * 60 * 60 * 1000);
      params.set("from", from.toISOString().slice(0, 10));
    }
    return getJson<StockPricesResponse>(`${SERVER_API_BASE}/api/v1/stocks/${ticker}/prices?${params}`);
  },
  stockNews: (ticker: string) =>
    getJson<StockNewsResponse>(`${SERVER_API_BASE}/api/v1/stocks/${ticker}/news`),
  stockPredictions: (ticker: string, limit = 30) =>
    getJson<StockPredictionsResponse>(`${SERVER_API_BASE}/api/v1/stocks/${ticker}/predictions?limit=${limit}`),
  performanceSummary: (window: "7d" | "30d" | "all" = "7d") =>
    getJson<PerformanceSummary>(`${SERVER_API_BASE}/api/v1/performance/summary?window=${window}`),
  modelVersions: () => getJson<ModelVersionListResponse>(`${SERVER_API_BASE}/api/v1/model/versions`),
};
