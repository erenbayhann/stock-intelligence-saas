"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import type { PriceBar } from "@/lib/api";

const RANGES = [
  { key: "1M", days: 30 },
  { key: "3M", days: 90 },
  { key: "1Y", days: 365 },
  { key: "ALL", days: Infinity },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

export function PriceChart({ bars }: { bars: PriceBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [range, setRange] = useState<RangeKey>("3M");

  const sorted = useMemo(
    () => [...bars].sort((a, b) => a.ts.localeCompare(b.ts)),
    [bars]
  );

  const filtered = useMemo(() => {
    const rangeDef = RANGES.find((r) => r.key === range)!;
    if (!Number.isFinite(rangeDef.days) || sorted.length === 0) return sorted;
    const cutoff = Date.now() - rangeDef.days * 24 * 60 * 60 * 1000;
    return sorted.filter((bar) => new Date(bar.ts).getTime() >= cutoff);
  }, [sorted, range]);

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

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#12E28A",
      downColor: "#FF6B5E",
      borderVisible: false,
      wickUpColor: "#12E28A",
      wickDownColor: "#FF6B5E",
    });
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return;
    seriesRef.current.setData(
      filtered.map((bar) => ({
        time: bar.ts.slice(0, 10),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    );
    chartRef.current.timeScale().fitContent();
  }, [filtered]);

  const latest = filtered[filtered.length - 1];
  const first = filtered[0];
  const deltaPct = latest && first && first.close !== 0 ? ((latest.close - first.close) / first.close) * 100 : null;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
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
      {filtered.length === 0 ? (
        <div className="h-[220px] flex items-center justify-center text-sm text-ink-soft">
          No price history available for this range.
        </div>
      ) : (
        <div ref={containerRef} className="w-full h-[220px]" />
      )}
    </div>
  );
}
