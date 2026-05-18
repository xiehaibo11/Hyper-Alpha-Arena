import { useEffect, useMemo, useState } from 'react'
import type { HTMLAttributes } from 'react'
import {
  applyArenaStrategyPromptFix,
  getArenaStrategyDiagnostics,
  type ArenaStrategyDiagnostics,
} from '../../lib/api'

interface ContextSnapshot {
  module: string
  display_name?: string
  responsibility?: string
  status: string
  summary: string
  direction?: string | null
  confidence?: number | null
  risk_level?: string | null
  freshness?: string
  symbol?: string | null
  timeframe?: string | null
  generated_at?: string | null
}

interface ContextPayload {
  exchange: string
  symbols: string[]
  timeframe: string
  modules: Record<string, ContextSnapshot[]>
}

interface ArenaAIContextPanelProps {
  accountId?: number | null
  exchange: string
  x: number
  y: number
  scale?: number
  dragHandlers?: HTMLAttributes<HTMLDivElement>
}

const MODULE_LABELS: Record<string, string> = {
  supervisor_ai: 'SUP',
  kline_ai: 'K-LINE',
  insight_ai: 'INSIGHT',
  market_data_ai: 'FLOW',
  signal_ai: 'SIGNAL',
  wallet_tracking_ai: 'WALLET',
  trader_management_ai: 'TRADER',
  backtest_data_ai: 'BT',
  strategy_diagnostics_ai: 'DIAG',
  attribution_ai: 'ATTR',
}

function statusColor(status?: string) {
  if (status === 'ok') return '#4ade80'
  if (status === 'warning' || status === 'partial') return '#facc15'
  if (status === 'missing' || status === 'error') return '#f87171'
  return '#94a3b8'
}

function riskColor(risk?: string | null) {
  if (risk === 'high') return '#f87171'
  if (risk === 'medium') return '#facc15'
  if (risk === 'low') return '#4ade80'
  return '#94a3b8'
}

function shortSummary(text: string, limit = 190) {
  if (!text) return 'NO CONTEXT'
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text
}

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return 'N/A'
  return `${Math.round(value * 100)}%`
}

export default function ArenaAIContextPanel({
  accountId,
  exchange,
  x,
  y,
  scale = 1,
  dragHandlers,
}: ArenaAIContextPanelProps) {
  const [payload, setPayload] = useState<ContextPayload | null>(null)
  const [diagnostics, setDiagnostics] = useState<ArenaStrategyDiagnostics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const [applyStatus, setApplyStatus] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async (force = false) => {
      try {
        const params = new URLSearchParams({
          exchange,
          timeframe: '15m',
          recompute: force ? 'true' : 'false',
        })
        if (accountId) params.set('account_id', String(accountId))
        const res = await fetch(`/api/arena/ai-context?${params.toString()}`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!cancelled) {
          setPayload(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'LOAD FAILED')
      }
    }

    const loadDiagnostics = async () => {
      if (!accountId) return
      try {
        const data = await getArenaStrategyDiagnostics({ account_id: accountId, exchange, limit: 50 })
        if (!cancelled) {
          setDiagnostics(data)
          setDiagnosticError(null)
        }
      } catch (err) {
        if (!cancelled) setDiagnosticError(err instanceof Error ? err.message : 'DIAG FAILED')
      }
    }

    load(true)
    loadDiagnostics()
    const timer = setInterval(() => {
      load(false)
      loadDiagnostics()
    }, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [accountId, exchange])

  const moduleRows = useMemo(() => {
    const modules = payload?.modules || {}
    return Object.entries(MODULE_LABELS).map(([key, label]) => {
      const rows = modules[key] || []
      const worst = rows.find(r => r.status !== 'ok') || rows[0]
      return {
        key,
        label,
        name: worst?.display_name || label,
        responsibility: worst?.responsibility || '',
        status: worst?.status || 'missing',
        freshness: worst?.freshness || 'unknown',
        risk: worst?.risk_level || 'unknown',
        count: rows.length,
      }
    })
  }, [payload])

  const supervisor = payload?.modules?.supervisor_ai?.[0]
  const diagnosis = payload?.modules?.strategy_diagnostics_ai?.[0]
  const generatedAt = supervisor?.generated_at ? new Date(supervisor.generated_at) : null
  const clock = generatedAt && !Number.isNaN(generatedAt.getTime())
    ? generatedAt.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
    : '--:--'

  const applyPromptFix = async () => {
    if (!accountId || !diagnostics?.can_apply_prompt_fix) return
    try {
      setApplying(true)
      setApplyStatus(null)
      const result = await applyArenaStrategyPromptFix({ account_id: accountId, exchange, limit: 50 })
      setApplyStatus(`BOUND #${result.new_prompt_template_id}`)
      setDiagnostics(result.diagnostics)
    } catch (err) {
      setApplyStatus(err instanceof Error ? err.message : 'APPLY FAILED')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div style={{
      position: 'absolute',
      left: x,
      top: y,
      width: 300 * scale,
      height: 392 * scale,
      zIndex: 12,
      imageRendering: 'pixelated',
      cursor: dragHandlers ? 'move' : undefined,
      touchAction: dragHandlers ? 'none' : undefined,
    }}
      title={dragHandlers ? 'Drag to move AI supervisor screen' : undefined}
      {...dragHandlers}
    >
      <div style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: 300,
        height: 392,
        transform: `scale(${scale})`,
        transformOrigin: 'top left',
        background: 'linear-gradient(180deg, #3a3d48 0%, #222633 55%, #151821 100%)',
        border: '2px solid #4b5563',
        borderRadius: 6,
        boxShadow: '0 6px 18px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.1)',
        padding: 6,
      }}>
        <div style={{
          height: '100%',
          background: '#070b12',
          border: '1px solid #000',
          borderRadius: 3,
          overflow: 'hidden',
          position: 'relative',
          fontFamily: 'monospace',
        }}>
          <div style={{
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            opacity: 0.35,
            backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.35) 2px, rgba(0,0,0,0.35) 4px)',
          }} />
          <div style={{ position: 'relative', zIndex: 1, padding: 9 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: '#93c5fd', fontWeight: 'bold', fontSize: 12 }}>AI SUPERVISOR</span>
              <span style={{ color: '#64748b', fontSize: 9 }}>{exchange.toUpperCase()} {clock}</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, marginBottom: 8 }}>
              {moduleRows.map(row => (
                <div key={row.key} style={{
                  border: `1px solid ${statusColor(row.status)}`,
                  color: statusColor(row.status),
                  borderRadius: 3,
                  padding: '2px 3px',
                  fontSize: 8,
                  lineHeight: '10px',
                  background: 'rgba(15,23,42,0.7)',
                  minWidth: 0,
                }}
                  title={`${row.name} | status=${row.status} freshness=${row.freshness}\n${row.responsibility}`}
                >
                  <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.label}</div>
                  <div style={{ color: riskColor(row.risk) }}>{row.count}</div>
                </div>
              ))}
            </div>

            <div style={{ color: '#cbd5e1', fontSize: 10, lineHeight: '14px', height: 44, overflow: 'hidden' }}>
              {error ? `ERR ${error}` : shortSummary(supervisor?.summary || '')}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 9 }}>
              <span style={{ color: riskColor(supervisor?.risk_level) }}>
                RISK {String(supervisor?.risk_level || 'UNKNOWN').toUpperCase()}
              </span>
              <span style={{ color: '#94a3b8' }}>
                CONF {supervisor?.confidence != null ? supervisor.confidence.toFixed(2) : 'N/A'}
              </span>
            </div>

            <div style={{
              marginTop: 8,
              borderTop: '1px solid rgba(148,163,184,0.22)',
              paddingTop: 7,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                <span style={{ color: '#f9a8d4', fontWeight: 'bold', fontSize: 10 }}>STRATEGY DIAG</span>
                <span style={{ color: riskColor(diagnostics?.risk_level || diagnosis?.risk_level), fontSize: 9 }}>
                  SCORE {diagnostics?.health_score ?? 'N/A'}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, marginBottom: 6 }}>
                <div style={{ color: '#cbd5e1', border: '1px solid #334155', borderRadius: 3, padding: '2px 3px', fontSize: 8 }}>
                  HOLD {pct(diagnostics?.stats?.hold_rate)}
                </div>
                <div style={{ color: '#cbd5e1', border: '1px solid #334155', borderRadius: 3, padding: '2px 3px', fontSize: 8 }}>
                  PNL {diagnostics?.stats ? diagnostics.stats.realized_pnl.toFixed(2) : 'N/A'}
                </div>
                <div style={{ color: '#cbd5e1', border: '1px solid #334155', borderRadius: 3, padding: '2px 3px', fontSize: 8 }}>
                  DEC {diagnostics?.stats?.decision_count ?? 'N/A'}
                </div>
              </div>
              <div style={{ color: '#e2e8f0', fontSize: 9, lineHeight: '12px', height: 36, overflow: 'hidden' }}>
                {diagnosticError ? `ERR ${diagnosticError}` : shortSummary(diagnostics?.summary || diagnosis?.summary || '', 150)}
              </div>
              <div style={{ color: '#facc15', fontSize: 8, lineHeight: '11px', height: 24, overflow: 'hidden', marginTop: 5 }}>
                {(diagnostics?.issues || []).slice(0, 2).map((item) => `! ${item}`).join('  ') || 'NO CRITICAL ISSUE'}
              </div>
              <div style={{ color: '#86efac', fontSize: 8, lineHeight: '11px', height: 24, overflow: 'hidden', marginTop: 4 }}>
                {(diagnostics?.optimizations || []).slice(0, 2).map((item) => `+ ${item}`).join('  ') || 'MONITORING'}
              </div>
              <div style={{ color: '#93c5fd', fontSize: 8, lineHeight: '11px', height: 34, overflow: 'hidden', marginTop: 5 }}>
                {(diagnostics?.trade_summaries || []).slice(0, 3).map((item) => item.summary).join(' | ') || 'NO TRADE SUMMARY'}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 7, gap: 6 }}>
                <button
                  type="button"
                  data-no-screen-drag="true"
                  disabled={!accountId || !diagnostics?.can_apply_prompt_fix || applying}
                  onClick={(event) => {
                    event.stopPropagation()
                    applyPromptFix()
                  }}
                  style={{
                    flex: '0 0 auto',
                    background: diagnostics?.can_apply_prompt_fix ? '#172554' : '#1f2937',
                    color: diagnostics?.can_apply_prompt_fix ? '#bfdbfe' : '#64748b',
                    border: '1px solid #334155',
                    borderRadius: 3,
                    padding: '3px 6px',
                    fontSize: 8,
                    lineHeight: '10px',
                    fontFamily: 'monospace',
                    cursor: diagnostics?.can_apply_prompt_fix ? 'pointer' : 'not-allowed',
                  }}
                >
                  {applying ? 'APPLYING' : 'APPLY FIX'}
                </button>
                <span style={{ color: '#94a3b8', fontSize: 8, lineHeight: '10px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {applyStatus || diagnostics?.prompt_template?.name || 'NO PROMPT'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
