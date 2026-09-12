import Link from "next/link";
import { api } from "@/lib/api";
import { formatDateTimeEt, formatShortDate, formatScore, timeAgo } from "@/lib/format";
import { explanationToFactors } from "@/lib/explanation";
import { ConfidencePill } from "@/components/ConfidencePill";
import { DirectionBadge, ResultBadge, SignedValue } from "@/components/ResultBadge";
import { StatTile } from "@/components/StatTile";
import { AiScoreCountUp } from "@/components/AiScoreCountUp";
import { RankChangeBadge } from "@/components/RankChangeBadge";

async function loadPreviousRank(ticker: string): Promise<number | null> {
  const predictions = await api.stockPredictions(ticker, 2);
  return predictions?.predictions?.[1]?.rank ?? null;
}

export default async function DashboardPage() {
  const [ranking, history, performance] = await Promise.all([
    api.latestRanking(),
    api.rankingHistory(7),
    api.performanceSummary("7d"),
  ]);

  if (!ranking) {
    return (
      <div className="rounded-2xl border border-panel-border bg-panel p-10 text-center text-ink-soft">
        No finalized prediction snapshot exists yet — check back after the next
        prediction run.
      </div>
    );
  }

  const featured = ranking.top5[0];
  const factors = featured ? explanationToFactors(featured.explanation) : [];
  const previousRanks = await Promise.all(ranking.top5.map((item) => loadPreviousRank(item.ticker)));

  return (
    <div>
      <div className="font-display text-[22px] tracking-tight text-ink mb-3">
        AI EQUITY RANKINGS
      </div>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft">
          US Equities &middot; S&amp;P 100
        </div>
        <div className="font-mono-tabular text-xs text-ink-faint">
          {formatDateTimeEt(ranking.generated_at)}
        </div>
      </div>

      <div className="rounded-2xl border border-panel-border bg-panel mb-4 overflow-hidden">
        <div className="grid grid-cols-[40px_1fr_70px_90px_110px_90px] px-5 py-3 border-b border-panel-border text-[10.5px] font-bold uppercase tracking-wider text-ink-faint">
          <div>#</div>
          <div>Symbol</div>
          <div>Rank Δ</div>
          <div>AI Score</div>
          <div>Confidence</div>
          <div>Direction</div>
        </div>
        {ranking.top5.map((item, i) => (
          <Link
            key={item.ticker}
            href={`/stocks/${item.ticker}`}
            className="grid grid-cols-[40px_1fr_70px_90px_110px_90px] items-center px-5 py-4 border-b border-row-border last:border-b-0 no-underline text-ink row-hover"
          >
            <div className="font-mono-tabular text-sm text-ink-dim">
              {String(item.rank).padStart(2, "0")}
            </div>
            <div>
              <div className="font-display text-base text-ink">{item.ticker}</div>
              <div className="text-xs text-ink-soft mt-0.5">{item.company_name}</div>
            </div>
            <div>
              <RankChangeBadge currentRank={item.rank} previousRank={previousRanks[i]} />
            </div>
            <div className="font-display text-xl text-green">
              {formatScore(item.ai_score)}
              <span className="font-mono-tabular text-xs text-ink-dim">/100</span>
            </div>
            <div>
              <ConfidencePill confidence={item.confidence} />
            </div>
            <div>
              <DirectionBadge />
            </div>
          </Link>
        ))}
      </div>

      {featured && (
        <div className="grid grid-cols-[380px_1fr] gap-4 mb-4">
          <div className="rounded-2xl bg-gradient-to-br from-green-grad-from to-green-grad-to text-hero-ink p-7 flex flex-col justify-between stat-tile-interactive tile-green">
            <div className="relative z-[1]">
              <div className="font-display text-xl">{featured.ticker}</div>
              <div className="text-xs opacity-75 mt-0.5">{featured.company_name}</div>
            </div>
            <div className="relative z-[1]">
              <div className="font-display text-[88px] leading-[0.85]">
                <AiScoreCountUp value={featured.ai_score} />
              </div>
              <div className="font-sans font-bold text-[11.5px] uppercase tracking-wide mt-2 opacity-75">
                AI Score &middot; Confidence {featured.confidence}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-panel-border bg-panel p-7">
            <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-3.5">
              Prediction horizon: next regular trading session
            </div>
            <div className="flex flex-wrap gap-2">
              {factors.map((factor) => (
                <span
                  key={factor}
                  className="text-xs font-semibold text-ink bg-[#191b1f] border border-[#2a2d33] rounded-full px-3.5 py-1.5 factor-tag-interactive"
                >
                  {factor}
                </span>
              ))}
            </div>
            {featured.related_news.length > 0 && (
              <div className="mt-3.5">
                {featured.related_news.slice(0, 2).map((news) => (
                  <div
                    key={news.id}
                    className="text-sm text-ink-news py-2.5 border-t border-row-border first:border-t-0 row-hover rounded-lg px-2 -mx-2"
                  >
                    <a href={news.url} target="_blank" rel="noreferrer">
                      {news.title}
                    </a>
                    <div className="font-mono-tabular text-[11px] text-ink-faint mt-0.5">
                      {news.source} &middot; {timeAgo(news.published_time)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex items-center gap-2.5 rounded-xl border border-panel-border bg-[#0c0d0e] px-5 py-3.5 mb-6 text-xs text-ink-soft">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9195A0" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        Model-generated research signal, not investment advice. Not a guarantee of future returns.{" "}
        <Link href="/methodology" className="text-ink-soft underline hover:text-ink">
          See Methodology.
        </Link>
      </div>

      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-3">
        Last 7 Days
      </div>
      <div className="rounded-2xl border border-panel-border bg-panel mb-4 overflow-hidden">
        <div className="grid grid-cols-[90px_90px_90px_90px_1fr_110px] px-5 py-3 border-b border-panel-border text-[10px] font-bold uppercase tracking-wider text-ink-faint">
          <div>Date</div>
          <div>Pick</div>
          <div>AI Score</div>
          <div>Actual</div>
          <div>Result</div>
          <div>vs S&amp;P 500</div>
        </div>
        {history && history.items.length > 0 ? (
          history.items.map((day) => (
            <Link
              key={day.target_session_date}
              href={`/day/${day.target_session_date}`}
              className="grid grid-cols-[90px_90px_90px_90px_1fr_110px] items-center px-5 py-3 border-b border-row-border last:border-b-0 font-mono-tabular text-xs text-ink-news no-underline row-hover"
            >
              <div>{formatShortDate(day.target_session_date)}</div>
              <div>{day.top_pick?.ticker ?? "—"}</div>
              <div>{day.top_pick ? `${formatScore(day.top_pick.ai_score)}/100` : "—"}</div>
              <div>
                <SignedValue value={day.top_pick?.actual_return ?? null} />
              </div>
              <div>
                <ResultBadge correct={day.top_pick?.direction_correct ?? null} />
              </div>
              <div>
                <SignedValue value={day.top_pick?.vs_benchmark ?? null} />
              </div>
            </Link>
          ))
        ) : (
          <div className="px-5 py-6 text-sm text-ink-soft">No evaluated days yet.</div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3.5">
        <StatTile
          value={performance?.hit_rate !== undefined ? `${Math.round(performance.hit_rate * 100)}%` : "—"}
          label="7-day hit rate"
          variant="green"
        />
        <StatTile
          value={
            performance?.mean_excess_return !== undefined
              ? `${performance.mean_excess_return >= 0 ? "+" : "−"}${Math.abs(performance.mean_excess_return * 100).toFixed(1)}%`
              : "—"
          }
          label="avg excess return"
          variant="blue"
        />
        <StatTile
          value={
            performance?.directional_accuracy !== undefined
              ? `${Math.round(performance.directional_accuracy * 100)}%`
              : "—"
          }
          label="directional accuracy"
          variant="white"
        />
      </div>
    </div>
  );
}
