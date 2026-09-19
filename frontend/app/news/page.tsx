import Link from "next/link";
import { api } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import { NewsPicksTabs } from "@/components/NewsPicksTabs";
import { StatTile } from "@/components/StatTile";

export const metadata = {
  title: "News Picks",
};

export default async function NewsPage() {
  const [latest, history] = await Promise.all([api.newsPicksLatest(), api.newsPicksHistory(7)]);
  const performance = history?.performance;

  return (
    <div>
      <div className="font-display text-[22px] tracking-tight text-ink mb-3">NEWS PICKS</div>
      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-4">
        Top 5 stocks by net-positive news &middot; locked 09:15 AM ET, before the open
      </div>

      <div className="flex items-center gap-2.5 rounded-xl border border-panel-border bg-[#0c0d0e] px-5 py-3.5 mb-6 text-xs text-ink-soft">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9195A0" strokeWidth="2" className="flex-none">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        <span>
          Ranked only from classified headlines since the previous close, independent of the AI Score model. A
          research signal, not investment advice, not a guarantee of future returns.{" "}
          <Link href="/methodology" className="text-ink-soft underline hover:text-ink">
            See Methodology.
          </Link>
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3.5 mb-6">
        <StatTile
          value={performance?.hit_rate != null ? `${Math.round(performance.hit_rate * 100)}%` : "—"}
          label="7-day hit rate"
          variant="green"
        />
        <StatTile
          value={performance?.mean_excess_return != null ? formatPercent(performance.mean_excess_return) : "—"}
          label="avg excess return"
          variant="blue"
        />
        <StatTile value={String(performance?.n_graded ?? 0)} label="picks graded" variant="white" />
      </div>

      <NewsPicksTabs latest={latest} history={history?.runs ?? []} />
    </div>
  );
}
