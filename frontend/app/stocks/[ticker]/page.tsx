import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { formatCompactUsd, formatPercent, formatScore, formatShortDate, formatDateTimeEt } from "@/lib/format";
import { explanationToFactors } from "@/lib/explanation";
import { ConfidencePill } from "@/components/ConfidencePill";
import { ResultBadge, SignedValue } from "@/components/ResultBadge";
import { PriceChart } from "@/components/PriceChart";

export default async function StockDetailPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  const upperTicker = ticker.toUpperCase();

  const [detail, prices, news, predictions] = await Promise.all([
    api.stockDetail(upperTicker),
    api.stockPrices(upperTicker),
    api.stockNews(upperTicker),
    api.stockPredictions(upperTicker),
  ]);

  if (!detail) notFound();

  const fundamentals = detail.latest_fundamentals;
  const factors = detail.explanation ? explanationToFactors(detail.explanation) : [];

  return (
    <div>
      <Link
        href="/"
        className="flex items-center gap-1.5 font-mono-tabular text-xs text-ink-faint no-underline mb-5 w-fit hover:text-ink-soft"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Rankings
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <div className="font-display text-4xl tracking-tight">{detail.ticker}</div>
          <div className="text-sm text-ink-soft mt-0.5">{detail.company_name}</div>
          {detail.sector && (
            <div className="font-mono-tabular text-[11px] text-ink-faint border border-panel-border rounded-full px-3 py-1 inline-block mt-2.5">
              {detail.sector}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-[1fr_320px] gap-4 my-5">
        <div className="rounded-2xl border border-panel-border bg-panel p-6">
          <PriceChart bars={prices?.bars ?? []} />
        </div>

        <div className="rounded-2xl bg-gradient-to-br from-green-grad-from to-green-grad-to text-hero-ink p-6 flex flex-col justify-between">
          <div>
            {detail.current_rank !== null ? (
              <span className="font-display text-sm bg-hero-ink text-green px-2.5 py-1 rounded-full inline-block">
                RANK #{detail.current_rank} TODAY
              </span>
            ) : (
              <span className="font-display text-sm bg-hero-ink text-green px-2.5 py-1 rounded-full inline-block">
                NOT IN TODAY&rsquo;S TOP 5
              </span>
            )}
          </div>
          <div>
            <div className="font-display text-6xl leading-[0.85]">{formatScore(detail.ai_score)}</div>
            <div className="font-sans font-bold text-[11px] uppercase tracking-wide mt-2 opacity-75">
              AI Score{detail.confidence ? ` · Confidence ${detail.confidence}` : ""}
            </div>
            {factors.length > 0 && (
              <div className="text-xs leading-relaxed mt-3.5 opacity-85">
                {factors.slice(0, 3).join(", ")}.
              </div>
            )}
          </div>
        </div>
      </div>

      {fundamentals && (
        <div className="grid grid-cols-6 gap-3 mb-5">
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px]">{formatCompactUsd(fundamentals.market_cap)}</div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">Market Cap</div>
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px]">{fundamentals.pe_ratio?.toFixed(1) ?? "—"}</div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">P / E</div>
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px]">
              {fundamentals.eps !== null ? `$${fundamentals.eps.toFixed(2)}` : "—"}
            </div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">EPS</div>
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px] text-green">
              {formatPercent(fundamentals.revenue_growth)}
            </div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">
              Revenue Growth
            </div>
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px]">{formatPercent(fundamentals.operating_margin)}</div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">
              Operating Margin
            </div>
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel p-4">
            <div className="font-display text-[19px]">{formatPercent(fundamentals.dividend_yield, 2)}</div>
            <div className="font-mono-tabular text-[10px] text-ink-faint uppercase tracking-wide mt-1.5">
              Dividend Yield
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-between items-baseline mt-7 mb-3">
        <h2 className="font-sans font-bold text-[15px] m-0">Recent news</h2>
      </div>
      <div className="rounded-2xl border border-panel-border bg-panel px-5 mb-2">
        {news && news.articles.length > 0 ? (
          news.articles.slice(0, 5).map((article) => (
            <div key={article.id} className="text-sm text-ink-news py-3.5 border-t border-row-border first:border-t-0">
              <a href={article.url} target="_blank" rel="noreferrer">
                {article.title}
              </a>
              <div className="font-mono-tabular text-[11px] text-ink-faint mt-0.5">
                {article.source} &middot; {formatDateTimeEt(article.published_time)}
              </div>
            </div>
          ))
        ) : (
          <div className="text-sm text-ink-soft py-4">No recent news for this ticker.</div>
        )}
      </div>

      <div className="flex justify-between items-baseline mt-7 mb-3">
        <h2 className="font-sans font-bold text-[15px] m-0">Prediction history for {detail.ticker}</h2>
      </div>
      <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
        <div className="grid grid-cols-[110px_70px_90px_96px_100px_110px_130px] items-center px-5 py-3 border-b border-panel-border text-[10px] font-bold uppercase tracking-wider text-ink-faint">
          <div>Date</div>
          <div>Rank</div>
          <div>AI Score</div>
          <div>Confidence</div>
          <div>Actual</div>
          <div>vs S&amp;P 500</div>
          <div>Result</div>
        </div>
        {predictions && predictions.predictions.length > 0 ? (
          predictions.predictions.map((p) => (
            <div
              key={p.target_session_date}
              className="grid grid-cols-[110px_70px_90px_96px_100px_110px_130px] items-center px-5 py-3.5 border-b border-row-border last:border-b-0"
            >
              <div className="font-mono-tabular text-sm">{formatShortDate(p.target_session_date)}</div>
              <div className="font-mono-tabular text-sm">#{p.rank}</div>
              <div className="font-display text-base text-green">
                {formatScore(p.ai_score)}
                <span className="font-mono-tabular text-[11px] text-ink-dim">/100</span>
              </div>
              <div>
                <ConfidencePill confidence={p.confidence} />
              </div>
              <div>
                <SignedValue value={p.actual_return} />
              </div>
              <div>
                <SignedValue value={p.vs_benchmark} />
              </div>
              <div>
                <ResultBadge correct={p.direction_correct} />
              </div>
            </div>
          ))
        ) : (
          <div className="px-5 py-6 text-sm text-ink-soft">
            {detail.ticker} hasn&rsquo;t appeared in the top 5 yet.
          </div>
        )}
      </div>
    </div>
  );
}
