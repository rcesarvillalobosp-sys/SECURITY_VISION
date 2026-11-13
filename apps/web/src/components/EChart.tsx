import { useEffect, useRef } from "react";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

export const CHART_BASE = {
  backgroundColor: "transparent",
  textStyle: { fontFamily: "IBM Plex Sans, sans-serif", color: "#93a1b2" },
  grid: { left: 44, right: 16, top: 28, bottom: 28 },
  tooltip: { trigger: "axis", backgroundColor: "#0f151d", borderColor: "#2a3644", textStyle: { color: "#dbe3ec" } },
};
export const AXIS = {
  axisLine: { lineStyle: { color: "#2a3644" } },
  axisLabel: { color: "#6b7a8c", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
  splitLine: { lineStyle: { color: "#1e2834" } },
};

export function EChart({ option, height = 240 }: { option: echarts.EChartsCoreOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);
  return <div ref={ref} style={{ height }} className="w-full" />;
}
