import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { formatLongDate, formatDateTimeEt, formatScore } from "@/lib/format";
import { ConfidencePill } from "@/components/ConfidencePill";
import { ResultBadge, SignedValue } from "@/components/ResultBadge";
import { StatTile } from "@/components/StatTile";

export default async function DayDetailPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;
  const detail = await api.rankingForDate(date);
  if (!detail) notFound();

  const evaluated = detail.top5.filter((item) => item.direction_correct !== null);
  const dayHitRate = detail.hit_rate;
  const dayMeanExcess =
    evaluated.length > 0
      ? evaluated.reduce((sum, item) => sum + (item.vs_benchmark ?? 0), 0) / evaluated.length
      : null;

  return (
    <div>
      <Link
        href="/"
        className="flex items-center gap-1.5 font-mono-tabular text-xs text-ink-faint no-underline mb-4 w-fit hover:text-ink-soft"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Last 7 Days
      </Link>

      <div className="flex items-end justify-between mb-1.5">
        <div className="font-display text-3xl tracking-tight">{formatLongDate(detail.target_session_date)}</div>
        <div className="font-mono-tabular text-xs text-ink-faint">
          Generated {formatDateTimeEt(detail.generated_at)}
        </div>
      </div>
      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft">
        US Equities &middot; S&amp;P 100 universe &middot; top 5 picks &amp; outcome
      </div>

      <div className="grid grid-cols-[1fr_220px_220px] gap-3.5 my-6">
        <div className="rounded-2xl border border-panel-border bg-panel p-5">
          <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-2">
            That session
          </div>
          <div className="text-sm text-ink-news leading-relaxed">
            100 stocks scored before open; only the top 5 are surfaced here.
            Outcomes below reflect the official close.
          </div>
        </div>
        <div className="rounded-2xl bg-blue text-blue-ink p-5 stat-tile-interactive tile-blue">
          <div className="font-display text-3xl leading-none relative z-[1]">
            <SignedValue value={detail.benchmark_return} />
          </div>
          <div className="font-sans font-bold text-[10.5px] uppercase tracking-wide mt-2 opacity-75 relative z-[1]">
            S&amp;P 500 that session
          </div>
        </div>
        <div className="rounded-2xl bg-gradient-to-br from-green-grad-from to-green-grad-to text-hero-ink p-5 stat-tile-interactive tile-green">
          <div className="font-display text-3xl leading-none relative z-[1]">
            {dayHitRate !== null ? `${Math.round(dayHitRate * 100)}%` : "—"}
          </div>
          <div className="font-sans font-bold text-[10.5px] uppercase tracking-wide mt-2 opacity-75 relative z-[1]">
            Hit rate that day
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-panel-border bg-panel mb-4 overflow-hidden">
        <div className="grid grid-cols-[36px_1fr_80px_96px_100px_110px_130px] items-center px-5 py-3 border-b border-panel-border text-[10px] font-bold uppercase tracking-wider text-ink-faint">
          <div>#</div>
          <div>Symbol</div>
          <div>AI Score</div>
          <div>Confidence</div>
          <div>Actual</div>
          <div>vs S&amp;P 500</div>
          <div>Result</div>
        </div>
        {detail.top5.map((item) => (
          <Link
            key={item.ticker}
            href={`/stocks/${item.ticker}`}
            className={
              "grid grid-cols-[36px_1fr_80px_96px_100px_110px_130px] items-center px-5 py-3.5 border-b border-row-border last:border-b-0 no-underline text-ink row-hover " +
              (item.direction_correct === true ? "border-l-2 border-l-green" : "border-l-2 border-l-transparent")
            }
          >
            <div className="font-mono-tabular text-sm text-ink-dim">
              {String(item.rank).padStart(2, "0")}
            </div>
            <div>
              <div className="font-display text-[15px]">{item.ticker}</div>
              <div className="text-xs text-ink-soft mt-px">{item.company_name}</div>
            </div>
            <div className="font-display text-base text-green">
              {formatScore(item.ai_score)}
              <span className="font-mono-tabular text-[11px] text-ink-dim">/100</span>
            </div>
            <div>
              <ConfidencePill confidence={item.confidence} />
            </div>
            <div>
              <SignedValue value={item.actual_return} />
            </div>
            <div>
              <SignedValue value={item.vs_benchmark} />
            </div>
            <div className={item.direction_correct === true ? "result-correct-highlight" : undefined}>
              <ResultBadge correct={item.direction_correct} />
            </div>
          </Link>
        ))}
      </div>

      {detail.notable_news.length > 0 && (
        <>
          <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-3">
            Notable news that day
          </div>
          <div className="rounded-2xl border border-panel-border bg-panel px-5 mb-5">
            {detail.notable_news.map((news) => (
              <div
                key={news.id}
                className="text-sm text-ink-news py-3.5 border-t border-row-border first:border-t-0 row-hover rounded-lg px-2 -mx-2"
              >
                {news.title}
                <div className="font-mono-tabular text-[11px] text-ink-faint mt-0.5">
                  {news.source} &middot; {formatDateTimeEt(news.published_time)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-3">
        That day&rsquo;s aggregate
      </div>
      <div className="grid grid-cols-3 gap-3.5">
        <StatTile
          value={dayHitRate !== null ? `${Math.round(dayHitRate * 100)}%` : "—"}
          label="hit rate"
          variant="green"
        />
        <StatTile
          value={
            dayMeanExcess !== null
              ? `${dayMeanExcess >= 0 ? "+" : "−"}${Math.abs(dayMeanExcess * 100).toFixed(1)}%`
              : "—"
          }
          label="avg excess return"
          variant="blue"
        />
        <StatTile
          value={dayHitRate !== null ? `${Math.round(dayHitRate * 100)}%` : "—"}
          label="directional accuracy"
          variant="white"
        />
      </div>
    </div>
  );
}
