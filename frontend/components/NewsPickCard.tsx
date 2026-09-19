import Link from "next/link";
import type { NewsPickItem } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { SentimentBadge } from "@/components/SentimentBadge";
import { ResultBadge, SignedValue } from "@/components/ResultBadge";

export function NewsPickList({ picks, emptyMessage }: { picks: NewsPickItem[]; emptyMessage: string }) {
  if (picks.length === 0) {
    return (
      <div className="rounded-2xl border border-panel-border bg-panel px-5 py-6 text-sm text-ink-soft">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
      {picks.map((pick) => (
        <NewsPickCard key={pick.ticker} pick={pick} />
      ))}
    </div>
  );
}

function NewsPickCard({ pick }: { pick: NewsPickItem }) {
  return (
    <div className="px-5 py-4 max-md:px-4 border-b border-row-border last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="font-mono-tabular text-sm text-ink-dim pt-0.5">
            {String(pick.rank).padStart(2, "0")}
          </span>
          <div>
            <Link
              href={`/stocks/${pick.ticker}`}
              className="font-display text-base text-ink no-underline hover:text-ink-soft"
            >
              {pick.ticker}
            </Link>
            <div className="text-xs text-ink-soft mt-0.5">{pick.company_name}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="font-display text-xl text-green">+{pick.news_score.toFixed(2)}</div>
          <div className="font-mono-tabular text-[10px] uppercase tracking-wide text-ink-faint">News score</div>
        </div>
      </div>

      <div className="font-mono-tabular text-[11px] text-ink-faint mt-2.5">
        {pick.article_count} headline{pick.article_count === 1 ? "" : "s"} &middot; {pick.positive_count} positive
        &middot; {pick.negative_count} negative &middot; avg sentiment {pick.avg_sentiment >= 0 ? "+" : "−"}
        {Math.abs(pick.avg_sentiment).toFixed(2)}
      </div>

      <div className="mt-1">
        {pick.evidence.map((item) => (
          <div
            key={item.url}
            className="flex items-start justify-between gap-3 py-2 border-t border-row-border first:border-t-0"
          >
            <div className="min-w-0">
              <a href={item.url} target="_blank" rel="noreferrer" className="text-sm text-ink-news hover:text-ink">
                {item.title}
              </a>
              <div className="font-mono-tabular text-[11px] text-ink-faint mt-0.5">
                {item.source} &middot; {timeAgo(item.published_time)}
              </div>
            </div>
            <div className="flex-none">
              <SentimentBadge sentiment={item.sentiment} />
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-5 mt-2.5 pt-2.5 border-t border-row-border">
        <div>
          <div className="text-[10px] text-ink-faint uppercase tracking-wide mb-0.5">{pick.ticker}</div>
          <SignedValue value={pick.actual_return} />
        </div>
        <div>
          <div className="text-[10px] text-ink-faint uppercase tracking-wide mb-0.5">S&amp;P 500</div>
          <SignedValue value={pick.benchmark_return} />
        </div>
        <div>
          <div className="text-[10px] text-ink-faint uppercase tracking-wide mb-0.5">Beat the S&amp;P 500?</div>
          <ResultBadge correct={pick.hit} />
        </div>
      </div>
    </div>
  );
}
