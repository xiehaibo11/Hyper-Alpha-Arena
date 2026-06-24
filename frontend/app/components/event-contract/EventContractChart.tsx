import { useEffect, useRef } from 'react'
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type SeriesMarker, type Time,
} from 'lightweight-charts'
import { getSignalHistory } from '@/lib/eventContractApi'

interface Props {
  exchange: string
  symbol: string
  expiry: number
}

// Candlestick chart with NON-REPAINTING signal arrows. Arrows come from
// EventContractOrder rows, which the backend only writes on a CLOSED 1m candle
// once the signal is confirmed — so an arrow never appears mid-candle and never
// moves. Up arrow (below bar) = long, down arrow (above bar) = short; colored by
// outcome once settled (win green / loss red / pending neutral).
export default function EventContractChart({ exchange, symbol, expiry }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const chart: IChartApi = createChart(el, {
      height: 360,
      width: el.clientWidth,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#888' },
      grid: { vertLines: { color: 'rgba(128,128,128,0.1)' }, horzLines: { color: 'rgba(128,128,128,0.1)' } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: 'rgba(128,128,128,0.2)' },
      rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
      crosshair: { mode: 0 },
    })
    const series: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })
    const markersApi = createSeriesMarkers(series, [])

    let alive = true
    const tick = async () => {
      try {
        const data = await getSignalHistory(exchange, symbol, expiry)
        if (!alive) return
        series.setData(
          data.candles.map((c) => ({
            time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close,
          })),
        )
        const markers: SeriesMarker<Time>[] = data.markers.map((m) => {
          const long = m.direction === 'long'
          const color = m.result === 'win' ? '#22c55e'
            : m.result === 'loss' ? '#ef4444'
            : long ? '#16a34a' : '#dc2626'
          return {
            time: m.time as Time,
            position: long ? 'belowBar' : 'aboveBar',
            shape: long ? 'arrowUp' : 'arrowDown',
            color,
            text: long ? '多' : '空',
          }
        })
        markersApi.setMarkers(markers)
      } catch {
        /* ignore transient fetch errors */
      }
    }
    tick()
    const id = window.setInterval(tick, 15000)

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(el)

    return () => {
      alive = false
      window.clearInterval(id)
      ro.disconnect()
      chart.remove()
    }
  }, [exchange, symbol, expiry])

  return <div ref={containerRef} className="w-full" />
}
