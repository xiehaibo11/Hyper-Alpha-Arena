export interface FlowIndicatorAvailability {
  cvd: boolean
  taker_volume: boolean
  oi: boolean
  oi_delta: boolean
  funding: boolean
  depth_ratio: boolean
  order_imbalance: boolean
}

const PERIOD_MINUTES: Record<string, number> = {
  '1m': 1,
  '3m': 3,
  '5m': 5,
  '15m': 15,
  '30m': 30,
  '1h': 60,
  '2h': 120,
  '4h': 240,
  '8h': 480,
  '12h': 720,
  '1d': 1440,
  '3d': 4320,
  '1w': 10080,
  '1M': 43200,
}

export function getFlowIndicatorAvailability(exchange: string, period: string): FlowIndicatorAvailability {
  const minutes = PERIOD_MINUTES[period] || 1

  if (exchange === 'binance' || exchange === 'okx') {
    return {
      cvd: true,
      taker_volume: true,
      oi: minutes >= 5,
      oi_delta: minutes >= 5,
      funding: true,
      depth_ratio: true,
      order_imbalance: true,
    }
  }

  return {
    cvd: true,
    taker_volume: true,
    oi: true,
    oi_delta: true,
    funding: true,
    depth_ratio: true,
    order_imbalance: true,
  }
}
