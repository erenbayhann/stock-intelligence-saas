import Link from "next/link";

export const metadata = {
  title: "Methodology & Limitations",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-sans font-bold text-base mb-3">{title}</h2>
      <div className="text-sm text-ink-news leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function MethodologyPage() {
  return (
    <div className="max-w-2xl">
      <Link
        href="/"
        className="flex items-center gap-1.5 font-mono-tabular text-xs text-ink-faint no-underline mb-6 w-fit hover:text-ink-soft"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Rankings
      </Link>

      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-2">
        Methodology &amp; Limitations
      </div>
      <h1 className="font-display text-3xl mb-6">How this ranking works</h1>

      <Section title="What this is">
        <p>
          A research and decision-support tool for the S&amp;P 100 universe. It is not a trading
          bot, does not execute trades, and never gives personalized investment advice. Rankings
          are a model-generated research signal, not a guarantee of future returns.
        </p>
      </Section>

      <Section title="How often data updates">
        <p>
          Market prices are <strong>daily bars</strong>, refreshed once per day after the regular
          session closes (~16:20 ET) — not tick-level or continuously streamed. The price chart on
          each stock&rsquo;s page shows the timestamp of the most recent bar it has; treat that
          timestamp as the data&rsquo;s actual freshness, not &ldquo;now.&rdquo;
        </p>
        <p>
          News is swept from providers at scheduled intervals overnight (roughly every 2-3 hours,
          7 times between market close and the next open), not polled continuously. A fast-breaking
          story between two sweeps won&rsquo;t appear until the next one runs.
        </p>
        <p>
          Exactly one prediction is generated and locked per trading day, shortly before the
          09:30 ET open, using only data available by that moment. There is no intraday
          re-prediction — the top 5 for a given session doesn&rsquo;t change after it&rsquo;s
          locked.
        </p>
      </Section>

      <Section title="Data sources">
        <p>
          Market data: Alpaca (IEX feed). Fundamentals: SEC EDGAR XBRL company filings. Macro
          series: FRED, with point-in-time vintages so later data revisions never leak backward
          into a past prediction. News: GDELT and Marketaux.
        </p>
      </Section>

      <Section title="Known limitations">
        <ul className="list-disc pl-5 space-y-2">
          <li>
            Alpaca&rsquo;s free plan serves IEX data only, not the full consolidated tape — volume
            and price figures somewhat under-represent true market-wide activity.
          </li>
          <li>
            News coverage depth is still growing; early history has sparser coverage than recent
            days.
          </li>
          <li>
            Predictions and their outcomes are never deleted or cherry-picked, including incorrect
            ones — the &ldquo;Last 7 Days&rdquo; view always reflects the full, real record.
          </li>
          <li>
            Model performance shown throughout this product (hit rate, directional accuracy, etc.)
            is measured out of sample on real predictions, not a backtest presented as if it were
            live performance — but past performance, real or backtested, still does not guarantee
            future results.
          </li>
        </ul>
      </Section>

      <Section title="Champion / challenger models">
        <p>
          The model making live predictions (the &ldquo;champion&rdquo;) is retrained periodically
          alongside experimental &ldquo;challenger&rdquo; models. A challenger only ever replaces
          the champion after a human reviews its measured performance — nothing is promoted
          automatically.
        </p>
      </Section>
    </div>
  );
}
