import type { Time } from 'lightweight-charts'
import { formatChartTime } from '@/lib/dateTime'
import { getMarkerParticleColor } from './TradingViewChartUtils'

export interface ChartOverlayMarker {
  key: string
  x: number
  y: number
  marker: any
}

export function buildOverlayMarkers({
  chart,
  series,
  container,
  chartData,
  eventMarkers,
}: {
  chart: any
  series: any
  container: HTMLDivElement
  chartData: any[]
  eventMarkers: any[]
}): ChartOverlayMarker[] {
  if (!chart || !series || !container || !chartData.length) return []

  const findNearestPoint = (chartTime: number) => {
    let best = chartData[0]
    let bestDiff = Math.abs(chartData[0].time - chartTime)
    for (let i = 1; i < chartData.length; i += 1) {
      const diff = Math.abs(chartData[i].time - chartTime)
      if (diff < bestDiff) {
        best = chartData[i]
        bestDiff = diff
      }
    }
    return best
  }

  const nextMarkers: ChartOverlayMarker[] = []
  const grouped = new Map<string, Array<{ marker: any; candle: any; position: string }>>()

  for (const marker of eventMarkers) {
    const chartTime = formatChartTime(marker.time / 1000) as number
    const candle = findNearestPoint(chartTime)
    const key = `${candle.time}:${marker.position}`
    const existing = grouped.get(key) || []
    existing.push({ marker, candle, position: marker.position })
    grouped.set(key, existing)
  }

  grouped.forEach((entries, groupKey) => {
    const [candleTimeRaw] = groupKey.split(':')
    const candle = entries[0]?.candle
    if (!candle) return
    const x = chart.timeScale().timeToCoordinate(candle.time as Time)
    if (x === null || x === undefined) return

    const containerWidth = container.clientWidth || 0
    const containerHeight = container.clientHeight || 0
    const safeLeft = 16
    const safeRight = Math.max(safeLeft + 1, containerWidth - 92)
    if (x < safeLeft) return

    const sorted = [...entries].sort((a, b) => a.marker.time - b.marker.time)
    sorted.forEach(({ marker }, index) => {
      const row = index % 3
      const column = Math.floor(index / 3)
      const xOffset = column === 0 ? 0 : (column % 2 === 1 ? column * 7 : -column * 7)
      const baseY = series.priceToCoordinate(candle.low)
      if (baseY === null || baseY === undefined) return
      const y = Math.min(baseY + 22 + row * 12, Math.max(48, containerHeight - 36))
      nextMarkers.push({
        key: marker.id || `${marker.kind || 'event'}-${marker.time}-${index}`,
        x: Math.min(Math.max(x + xOffset, safeLeft), safeRight),
        y,
        marker: {
          ...marker,
          chartTime: Number(candleTimeRaw),
        },
      })
    })
  })

  return nextMarkers
}

export function drawOverlayMarkerParticles({
  canvas,
  container,
  overlayMarkers,
  hoveredMarkerCandleTime,
  hoveredCandleTime,
  activeEventMarkerId,
}: {
  canvas: HTMLCanvasElement
  container: HTMLDivElement
  overlayMarkers: ChartOverlayMarker[]
  hoveredMarkerCandleTime: number | null
  hoveredCandleTime: number | null
  activeEventMarkerId?: string
}) {
  const width = container.clientWidth
  const height = container.clientHeight
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1

  canvas.width = Math.max(1, Math.floor(width * dpr))
  canvas.height = Math.max(1, Math.floor(height * dpr))
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, width, height)

  overlayMarkers.forEach((item) => {
    const marker = item.marker
    const isCandleActive = (hoveredMarkerCandleTime ?? hoveredCandleTime) === marker.chartTime
    const isSelected = activeEventMarkerId === marker.id
    const radius = marker.kind === 'news' ? 3.2 : 4.2
    const glow = isSelected ? 18 : isCandleActive ? 13 : 9
    const alpha = isSelected ? 0.96 : isCandleActive ? 0.78 : 0.42
    const color = getMarkerParticleColor(marker)

    ctx.save()
    ctx.fillStyle = color
    ctx.globalAlpha = alpha
    ctx.shadowColor = color
    ctx.shadowBlur = glow
    ctx.beginPath()
    ctx.arc(item.x, item.y, radius, 0, Math.PI * 2)
    ctx.fill()

    if (isSelected || isCandleActive) {
      ctx.globalAlpha = isSelected ? 0.34 : 0.22
      ctx.beginPath()
      ctx.arc(item.x, item.y, radius + 5, 0, Math.PI * 2)
      ctx.fill()
    }

    ctx.restore()
  })
}
