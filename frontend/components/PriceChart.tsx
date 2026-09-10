"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import type { PriceBar } from "@/lib/api";
import { formatDateTimeEt, isTodayEt } from "@/lib/format";

const RANGES = [
  { key: "1M", days: 30 },
  { key: "3M", days: 90 },
  { key: "1Y", days: 365 },
  { key: "ALL", days: Infinity },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

interface Tooltip {
  x: number;
  y: number;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function sortByTime(bars: PriceBar[]): PriceBar[] {
  return [...bars].sort((a, b) => a.ts.localeCompare(b.ts));
}

function filterByRange(bars: PriceBar[], range: RangeKey): PriceBar[] {
  const rangeDef = RANGES.find((r) => r.key === range)!;
  if (!Number.isFinite(rangeDef.days) || bars.length === 0) return bars;
  const cutoff = Date.now() - rangeDef.days * 24 * 60 * 60 * 1000;
  return bars.filter((bar) => new Date(bar.ts).getTime() >= cutoff);
}

export function PriceChart({ bars, benchmarkBars }: { bars: PriceBar[]; benchmarkBars?: PriceBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const benchmarkSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [range, setRange] = useState<RangeKey>("3M");
  const [compareMode, setCompareMode] = useState(false);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);

  const sorted = useMemo(() => sortByTime(bars), [bars]);
  const filtered = useMemo(() => filterByRange(sorted, range), [sorted, range]);

  const sortedBenchmark = useMemo(() => sortByTime(benchmarkBars ?? []), [benchmarkBars]);
  const filteredBenchmark = useMemo(() => filterByRange(sortedBenchmark, range), [sortedBenchmark, range]);

  const latestBarTs = sorted.length > 0 ? sorted[sorted.length - 1].ts : null;

  // The crosshair handler is registered once on mount but needs the latest
  // `filtered` bars (for volume lookup) without re-subscribing every render.
  const filteredRef = useRef(filtered);
  filteredRef.current = filtered;

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#6C707B",
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "#1B1C1F" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
      height: 220,
      autoSize: true,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#12E28A",
      downColor: "#FF6B5E",
      borderVisible: false,
      wickUpColor: "#12E28A",
      wickDownColor: "#FF6B5E",
    });
    candleSeriesRef.current = candleSeries;

    const handleCrosshairMove = (param: MouseEventParams<Time>) => {
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
        setTooltip(null);
        return;
      }
      const point = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined;
      if (!point) {
        setTooltip(null);
        return;
      }
      const matchedBar = filteredRef.current.find((bar) => bar.ts.slice(0, 10) === point.time);
      setTooltip({
        x: param.point.x,
        y: param.point.y,
        date: String(point.time),
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
        volume: matchedBar?.volume ?? 0,
      });
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      benchmarkSeriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !chartRef.current) return;

    const firstClose = filtered[0]?.close;
    const indexFactor = compareMode && firstClose ? 100 / firstClose : 1;
    const todayTs = latestBarTs && isTodayEt(latestBarTs) ? latestBarTs.slice(0, 10) : null;

    candleSeriesRef.current.setData(
      filtered.map((bar) => {
        const time = bar.ts.slice(0, 10) as Time;
        const isProvisional = todayTs !== null && time === todayTs;
        return {
          time,
          open: bar.open * indexFactor,
          high: bar.high * indexFactor,
          low: bar.low * indexFactor,
          close: bar.close * indexFactor,
          ...(isProvisional
            ? { color: "#6C707B", borderColor: "#9195A0", wickColor: "#6C707B" }
            : {}),
        };
      })
    );

    if (compareMode && filteredBenchmark.length > 0) {
      if (!benchmarkSeriesRef.current) {
        benchmarkSeriesRef.current = chartRef.current.addSeries(LineSeries, {
          color: "#2F5BFF",
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });
      }
      const firstBenchmarkClose = filteredBenchmark[0].close;
      benchmarkSeriesRef.current.setData(
        filteredBenchmark.map((bar) => ({
          time: bar.ts.slice(0, 10) as Time,
          value: (bar.close / firstBenchmarkClose) * 100,
        }))
      );
    } else if (benchmarkSeriesRef.current) {
      chartRef.current.removeSeries(benchmarkSeriesRef.current);
      benchmarkSeriesRef.current = null;
    }

    chartRef.current.timeScale().fitContent();
  }, [filtered, filteredBenchmark, compareMode, latestBarTs]);

  const latest = filtered[filtered.length - 1];
  const first = filtered[0];
  const deltaPct = latest && first && first.close !== 0 ? ((latest.close - first.close) / first.close) * 100 : null;
  const isLatestProvisional = latestBarTs !== null && isTodayEt(latestBarTs);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-baseline">
          <div className="font-display text-2xl">
            {latest ? `$${latest.close.toFixed(2)}` : "—"}
          </div>
          {deltaPct !== null && (
            <div className={"font-mono-tabular text-[13px] ml-2 " + (deltaPct >= 0 ? "text-green" : "text-negative")}>
              {deltaPct >= 0 ? "+" : ""}
              {deltaPct.toFixed(2)}%
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {benchmarkBars && benchmarkBars.length > 0 && (
            <button
              onClick={() => setCompareMode((v) => !v)}
              className={
                "flex items-center gap-1.5 font-mono-tabular text-[11px] px-2.5 py-1 rounded-full border " +
                (compareMode ? "border-blue text-blue-ink bg-blue/20" : "border-panel-border text-ink-faint")
              }
            >
              <span
                className={
                  "inline-block w-2 h-2 rounded-full " + (compareMode ? "bg-blue" : "bg-ink-dim")
                }
              />
              S&amp;P 500 ile karşılaştır
            </button>
          )}
          <div className="flex gap-1.5">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={
                  "font-mono-tabular text-[11px] px-2.5 py-1 rounded-full border " +
                  (range === r.key
                    ? "bg-green text-hero-ink border-green"
                    : "text-ink-faint border-panel-border")
                }
              >
                {r.key}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between mb-3">
        <div className="font-mono-tabular text-[11px] text-ink-faint">
          {latestBarTs ? `Fiyat verisi son ${formatDateTimeEt(latestBarTs)} itibariyle` : "Fiyat verisi yok"}
        </div>
        {isLatestProvisional && (
          <div className="font-mono-tabular text-[11px] text-ink-faint flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full border border-ink-faint" />
            Gün içi, henüz kapanmadı
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="h-[220px] flex items-center justify-center text-sm text-ink-soft">
          No price history available for this range.
        </div>
      ) : (
        <div className="relative">
          <div ref={containerRef} className="w-full h-[220px]" />
          {tooltip && (
            <div
              className="pointer-events-none absolute z-10 rounded-lg border border-panel-border bg-[#0c0d0e] px-3 py-2 text-[11px] font-mono-tabular text-ink-news shadow-lg"
              style={{
                left: Math.min(tooltip.x + 12, 480),
                top: Math.max(tooltip.y - 70, 0),
              }}
            >
              <div className="text-ink-faint mb-1">{tooltip.date}</div>
              <div>O {tooltip.open.toFixed(2)} &middot; H {tooltip.high.toFixed(2)}</div>
              <div>L {tooltip.low.toFixed(2)} &middot; C {tooltip.close.toFixed(2)}</div>
              <div className="text-ink-faint mt-1">Vol {tooltip.volume.toLocaleString()}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
