import type { MutableRefObject } from 'react'
import { HistogramSeries, LineSeries } from 'lightweight-charts'
import { formatChartTime } from '@/lib/dateTime'
import { FLOW_COLORS, FLOW_LABELS } from './TradingViewChartUtils'

export interface FlowSeriesRefs {
  cvd: MutableRefObject<any>
  takerBuy: MutableRefObject<any>
  takerSell: MutableRefObject<any>
  oi: MutableRefObject<any>
  oiDelta: MutableRefObject<any>
  funding: MutableRefObject<any>
  depth: MutableRefObject<any>
  imbalance: MutableRefObject<any>
}

export function createFlowSeriesRefs(
  cvd: MutableRefObject<any>,
  takerBuy: MutableRefObject<any>,
  takerSell: MutableRefObject<any>,
  oi: MutableRefObject<any>,
  oiDelta: MutableRefObject<any>,
  funding: MutableRefObject<any>,
  depth: MutableRefObject<any>,
  imbalance: MutableRefObject<any>,
): FlowSeriesRefs {
  return { cvd, takerBuy, takerSell, oi, oiDelta, funding, depth, imbalance }
}

export function createFlowPaneSeries(flowPane: any, refs: FlowSeriesRefs) {
  refs.cvd.current = flowPane.addSeries(LineSeries, {
    color: FLOW_COLORS.cvd.line, lineWidth: 2, visible: false,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
  })
  refs.takerBuy.current = flowPane.addSeries(HistogramSeries, {
    color: FLOW_COLORS.taker_volume.up, visible: false,
    priceFormat: { type: 'volume' }
  })
  refs.takerSell.current = flowPane.addSeries(HistogramSeries, {
    color: FLOW_COLORS.taker_volume.down, visible: false,
    priceFormat: { type: 'volume' }
  })
  refs.oi.current = flowPane.addSeries(LineSeries, {
    color: FLOW_COLORS.oi.line, lineWidth: 2, visible: false,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
  })
  refs.oiDelta.current = flowPane.addSeries(HistogramSeries, {
    color: FLOW_COLORS.oi_delta.line, visible: false,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
  })
  refs.funding.current = flowPane.addSeries(LineSeries, {
    color: FLOW_COLORS.funding.line, lineWidth: 2, visible: false,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
  })
  refs.depth.current = flowPane.addSeries(LineSeries, {
    color: FLOW_COLORS.depth_ratio.line, lineWidth: 2, visible: false,
    priceFormat: { type: 'price', precision: 4, minMove: 0.0001 }
  })
  refs.imbalance.current = flowPane.addSeries(HistogramSeries, {
    color: FLOW_COLORS.order_imbalance.line, visible: false,
    priceFormat: { type: 'price', precision: 4, minMove: 0.0001 }
  })
}

export function getFlowSeriesRef(refs: FlowSeriesRefs, indicator: string) {
  switch (indicator) {
    case 'cvd': return refs.cvd
    case 'taker_volume': return { buy: refs.takerBuy, sell: refs.takerSell }
    case 'oi': return refs.oi
    case 'oi_delta': return refs.oiDelta
    case 'funding': return refs.funding
    case 'depth_ratio': return refs.depth
    case 'order_imbalance': return refs.imbalance
    default: return null
  }
}

export function updateFlowSeries(indicator: string, data: any[], refs: FlowSeriesRefs) {
  if (!data || data.length === 0) return

  const colors = FLOW_COLORS[indicator]

  if (indicator === 'taker_volume') {
    if (refs.takerBuy.current) {
      const buyData = data.map(d => ({
        time: formatChartTime(d.time),
        value: d.buy || 0,
        color: colors.up
      }))
      refs.takerBuy.current.setData(buyData)
    }
    if (refs.takerSell.current) {
      const sellData = data.map(d => ({
        time: formatChartTime(d.time),
        value: -(d.sell || 0),
        color: colors.down
      }))
      refs.takerSell.current.setData(sellData)
    }
    return
  }

  const seriesRef = getFlowSeriesRef(refs, indicator)
  if (!seriesRef || !('current' in seriesRef) || !seriesRef.current) return

  if (['oi_delta', 'order_imbalance'].includes(indicator)) {
    const histData = data.map(d => ({
      time: formatChartTime(d.time),
      value: d.value || 0,
      color: (d.value || 0) >= 0 ? colors.up : colors.down
    }))
    seriesRef.current.setData(histData)
  } else if (indicator === 'depth_ratio') {
    const lineData = data.map(d => ({
      time: formatChartTime(d.time),
      value: d.value > 0 ? Math.log10(d.value) : 0
    }))
    seriesRef.current.setData(lineData)
  } else if (indicator === 'funding') {
    const lineData = data.map(d => ({
      time: formatChartTime(d.time),
      value: (d.value || 0) * 10000
    }))
    seriesRef.current.setData(lineData)
  } else {
    const lineData = data.map(d => ({
      time: formatChartTime(d.time),
      value: d.value
    }))
    seriesRef.current.setData(lineData)
  }
}

export function updateFlowPaneLabel(flowLabelRef: MutableRefObject<any>, indicator: string) {
  if (flowLabelRef.current && flowLabelRef.current.updateText) {
    flowLabelRef.current.updateText(FLOW_LABELS[indicator] || indicator)
  }
}

export function hideAllFlowSeries(refs: FlowSeriesRefs) {
  refs.cvd.current?.applyOptions({ visible: false })
  refs.takerBuy.current?.applyOptions({ visible: false })
  refs.takerSell.current?.applyOptions({ visible: false })
  refs.oi.current?.applyOptions({ visible: false })
  refs.oiDelta.current?.applyOptions({ visible: false })
  refs.funding.current?.applyOptions({ visible: false })
  refs.depth.current?.applyOptions({ visible: false })
  refs.imbalance.current?.applyOptions({ visible: false })
}

export function showFlowSeries(indicator: string, refs: FlowSeriesRefs) {
  hideAllFlowSeries(refs)
  if (indicator === 'taker_volume') {
    refs.takerBuy.current?.applyOptions({ visible: true })
    refs.takerSell.current?.applyOptions({ visible: true })
    return
  }

  const seriesRef = getFlowSeriesRef(refs, indicator)
  if (seriesRef && 'current' in seriesRef && seriesRef.current) {
    seriesRef.current.applyOptions({ visible: true })
  }
}

export function clearFlowSeriesData(refs: FlowSeriesRefs) {
  refs.cvd.current?.setData([])
  refs.takerBuy.current?.setData([])
  refs.takerSell.current?.setData([])
  refs.oi.current?.setData([])
  refs.oiDelta.current?.setData([])
  refs.funding.current?.setData([])
  refs.depth.current?.setData([])
  refs.imbalance.current?.setData([])
}

export function resetFlowSeriesRefs(refs: FlowSeriesRefs) {
  refs.cvd.current = null
  refs.takerBuy.current = null
  refs.takerSell.current = null
  refs.oi.current = null
  refs.oiDelta.current = null
  refs.funding.current = null
  refs.depth.current = null
  refs.imbalance.current = null
}
