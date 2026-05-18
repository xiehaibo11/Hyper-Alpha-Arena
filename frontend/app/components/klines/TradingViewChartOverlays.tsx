import type { Dispatch, RefObject, SetStateAction } from 'react'
import { FLOW_LABELS } from './TradingViewChartUtils'

interface OverlayMarker {
  key: string
  x: number
  y: number
  marker: any
}

interface HoveredMarker {
  x: number
  y: number
  marker: any
}

interface TradingViewChartOverlaysProps {
  chartContainerRef: RefObject<HTMLDivElement>
  overlayCanvasRef: RefObject<HTMLCanvasElement>
  overlayMarkers: OverlayMarker[]
  hoveredMarker: HoveredMarker | null
  hoveredCandleTime: number | null
  hoveredMarkerCandleTime: number | null
  activeEventMarkerId?: string
  selectedIndicators: string[]
  selectedFlowIndicators: string[]
  activeSubplot: string | null
  activeFlowIndicator: string | null
  flowDataAvailableFrom: number | null
  indicatorPaneTop: number | null
  flowPaneTop: number | null
  loading: boolean
  hasData: boolean
  onEventMarkerClick?: (eventId: string) => void
  setHoveredMarker: Dispatch<SetStateAction<HoveredMarker | null>>
  setHoveredMarkerCandleTime: Dispatch<SetStateAction<number | null>>
  setActiveSubplot: Dispatch<SetStateAction<string | null>>
  setActiveFlowIndicator: Dispatch<SetStateAction<string | null>>
}

export default function TradingViewChartOverlays({
  chartContainerRef,
  overlayCanvasRef,
  overlayMarkers,
  hoveredMarker,
  hoveredCandleTime,
  hoveredMarkerCandleTime,
  activeEventMarkerId,
  selectedIndicators,
  selectedFlowIndicators,
  activeSubplot,
  activeFlowIndicator,
  flowDataAvailableFrom,
  indicatorPaneTop,
  flowPaneTop,
  loading,
  hasData,
  onEventMarkerClick,
  setHoveredMarker,
  setHoveredMarkerCandleTime,
  setActiveSubplot,
  setActiveFlowIndicator,
}: TradingViewChartOverlaysProps) {
  const subplotIndicators = selectedIndicators.filter(ind => ['RSI14', 'RSI7', 'MACD', 'ATR14', 'STOCH', 'OBV'].includes(ind))
  const currentActiveSubplot = activeSubplot || subplotIndicators[0]

  return (
    <>
      <div ref={chartContainerRef} className="w-full h-full" />
      <canvas ref={overlayCanvasRef} className="pointer-events-none absolute inset-0 z-[5]" />

      <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
        {overlayMarkers.map((item) => {
          const isCandleActive = (hoveredMarkerCandleTime ?? hoveredCandleTime) === item.marker.chartTime
          const isSelected = activeEventMarkerId === item.marker.id
          const scaleClass = isSelected
            ? 'scale-[1.2]'
            : isCandleActive
              ? 'scale-110'
              : 'scale-100'
          const opacityClass = isSelected || isCandleActive ? 'opacity-100' : 'opacity-70'

          return (
            <button
              key={item.key}
              type="button"
              className={`pointer-events-auto absolute z-10 h-6 w-6 -translate-x-1/2 -translate-y-1/2 rounded-full border border-transparent bg-transparent outline-none transition-all duration-150 ${isSelected ? 'ring-2 ring-sky-300/55 ring-offset-2 ring-offset-background' : ''} ${scaleClass} ${opacityClass}`}
              style={{ left: item.x, top: item.y }}
              onMouseEnter={() => {
                setHoveredMarker({ x: item.x, y: item.y, marker: item.marker })
                setHoveredMarkerCandleTime(item.marker.chartTime ?? null)
              }}
              onMouseLeave={() => {
                setHoveredMarker(null)
                setHoveredMarkerCandleTime(null)
              }}
              onClick={() => {
                if (item.marker.id) onEventMarkerClick?.(item.marker.id)
                setHoveredMarker({ x: item.x, y: item.y, marker: item.marker })
                setHoveredMarkerCandleTime(item.marker.chartTime ?? null)
              }}
            />
          )
        })}
      </div>

      {hoveredMarker && (
        <div
          className="pointer-events-none absolute z-20 w-64 rounded-xl border border-border bg-background/95 p-3 shadow-xl backdrop-blur-sm"
          style={{
            left: Math.min(Math.max(hoveredMarker.x + 16, 12), (chartContainerRef.current?.clientWidth || 320) - 272),
            top: Math.min(Math.max(hoveredMarker.y + 16, 12), (chartContainerRef.current?.clientHeight || 240) - 140),
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold text-foreground">{hoveredMarker.marker.title || hoveredMarker.marker.kind || 'Event'}</div>
            {hoveredMarker.marker.tone && (
              <div className={`text-[10px] uppercase tracking-[0.2em] ${
                hoveredMarker.marker.tone === 'bullish'
                  ? 'text-emerald-600'
                  : hoveredMarker.marker.tone === 'bearish'
                    ? 'text-orange-600'
                    : 'text-slate-500'
              }`}>
                {hoveredMarker.marker.tone}
              </div>
            )}
          </div>
          {hoveredMarker.marker.summary && (
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {hoveredMarker.marker.summary}
            </div>
          )}
          <div className="mt-2 text-[11px] text-muted-foreground">
            {new Date(hoveredMarker.marker.time).toLocaleString()}
          </div>
          {Array.isArray(hoveredMarker.marker.metadata) && hoveredMarker.marker.metadata.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {hoveredMarker.marker.metadata.slice(0, 3).map((item: string, index: number) => (
                <span key={`${hoveredMarker.marker.id || hoveredMarker.marker.time}-${index}`} className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                  {item}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {subplotIndicators.length > 0 && indicatorPaneTop !== null && (
        <div
          className="absolute left-2 z-10 flex items-center bg-background/80 backdrop-blur-sm rounded-md p-1 px-2 border text-xs"
          style={{ top: indicatorPaneTop + 4 }}
        >
          <select
            value={currentActiveSubplot}
            onChange={(e) => setActiveSubplot(e.target.value)}
            className="bg-transparent border-0 text-xs focus:outline-none cursor-pointer"
            disabled={subplotIndicators.length === 1}
          >
            {subplotIndicators.map(indicator => (
              <option key={indicator} value={indicator}>
                {indicator}
              </option>
            ))}
          </select>
        </div>
      )}

      {selectedFlowIndicators.length > 0 && activeFlowIndicator && flowPaneTop !== null && (
        <div
          className="absolute left-2 z-10 flex items-center gap-2 bg-background/80 backdrop-blur-sm rounded-md p-1 px-2 border text-xs"
          style={{ top: flowPaneTop + 4 }}
        >
          <select
            value={activeFlowIndicator}
            onChange={(e) => setActiveFlowIndicator(e.target.value)}
            className="bg-transparent border-0 text-xs focus:outline-none cursor-pointer text-cyan-400"
            disabled={selectedFlowIndicators.length === 1}
          >
            {selectedFlowIndicators.map(indicator => (
              <option key={indicator} value={indicator}>
                {FLOW_LABELS[indicator]}
              </option>
            ))}
          </select>
          {flowDataAvailableFrom && (
            <span className="text-muted-foreground">
              from {new Date(flowDataAvailableFrom).toLocaleDateString()}
            </span>
          )}
        </div>
      )}

      <div className="absolute bottom-2 right-2 text-xs text-muted-foreground/30 pointer-events-none select-none">
        Hyper Alpha Arena
      </div>

      {!loading && !hasData && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <p className="text-lg font-medium">No K-line data available</p>
            <p className="text-sm">Click "Backfill Historical Data" to fetch data</p>
          </div>
        </div>
      )}
    </>
  )
}
