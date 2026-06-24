import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries, ColorType, createChart,
  type IChartApi, type ISeriesApi, type Time,
} from 'lightweight-charts'
import { getKlineHistory } from '@/lib/eventContractApi'

interface Props { exchange: string; symbol: string; period?: string; limit?: number }

// 历史 K 线图：默认日线 365 根 ≈ 过去一年走势，用于看大趋势/历史形态。
export default function HistoryChart({ exchange, symbol, period = '1d', limit = 365 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [count, setCount] = useState(0)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const chart: IChartApi = createChart(el, {
      height: 320,
      width: el.clientWidth,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#888' },
      grid: { vertLines: { color: 'rgba(128,128,128,0.1)' }, horzLines: { color: 'rgba(128,128,128,0.1)' } },
      timeScale: { timeVisible: false, borderColor: 'rgba(128,128,128,0.2)' },
      rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
      crosshair: { mode: 0 },
    })
    const series: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })

    let alive = true
    ;(async () => {
      try {
        const data = await getKlineHistory(symbol, exchange, period, limit)
        if (!alive) return
        setCount(data.count)
        series.setData(data.candles.map((c) => ({
          time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close,
        })))
        chart.timeScale().fitContent()
      } catch { /* transient */ }
    })()

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(el)
    return () => { alive = false; ro.disconnect(); chart.remove() }
  }, [exchange, symbol, period, limit])

  return (
    <div>
      <div ref={containerRef} className="w-full" />
      {count === 0 && <div className="text-xs text-muted-foreground text-center py-4">暂无历史 K 线数据</div>}
    </div>
  )
}
