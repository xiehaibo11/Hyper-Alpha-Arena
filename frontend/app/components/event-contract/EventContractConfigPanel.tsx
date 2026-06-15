import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  EventContractConfig, getEventContractConfig, getStrategies, updateEventContractConfig,
} from '@/lib/eventContractApi'

export default function EventContractConfigPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [cfg, setCfg] = useState<EventContractConfig | null>(null)
  const [signals, setSignals] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { getEventContractConfig().then(setCfg).catch(() => setCfg(null)) }, [])
  useEffect(() => { getStrategies().then((s) => setSignals(s.order_flow)).catch(() => setSignals([])) }, [])

  if (!cfg) return <div className="text-sm text-muted-foreground p-4">{t('eventContract.loading', '加载中…')}</div>

  const setParam = (key: string, field: 'window' | 'thr', value: number) => {
    setCfg({ ...cfg, signal_params: { ...cfg.signal_params, [key]: { ...cfg.signal_params[key], [field]: value } } })
  }

  const signalOptions = signals.includes(cfg.default_signal) ? signals : [cfg.default_signal, ...signals]

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const next = await updateEventContractConfig({
        payout: cfg.payout, daily_reset_tz: cfg.daily_reset_tz,
        default_signal: cfg.default_signal, signal_params: cfg.signal_params,
      })
      setCfg(next); setMsg(t('eventContract.saved', '已保存'))
    } catch { setMsg(t('eventContract.saveFailed', '保存失败')) } finally { setSaving(false) }
  }

  return (
    <div className="border rounded-lg p-4 bg-card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{t('eventContract.config', '事件合约配置')}</h3>
        <button onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground">✕</button>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm">{t('eventContract.signalAlgo', '信号算法')}</label>
        <select value={cfg.default_signal}
          onChange={(e) => setCfg({ ...cfg, default_signal: e.target.value })}
          className="border rounded px-2 py-1 text-sm bg-background">
          {signalOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label className="text-sm">{t('eventContract.payout', '赔付')}</label>
        <input type="number" step="0.01" value={cfg.payout}
          onChange={(e) => setCfg({ ...cfg, payout: Number(e.target.value) })}
          className="border rounded px-2 py-1 text-sm bg-background w-24" />
        <label className="text-sm">{t('eventContract.resetTz', '重置时区')}</label>
        <input value={cfg.daily_reset_tz}
          onChange={(e) => setCfg({ ...cfg, daily_reset_tz: e.target.value })}
          className="border rounded px-2 py-1 text-sm bg-background w-44" />
      </div>
      <div className="text-[11px] text-muted-foreground">
        {t('eventContract.signalHint', '提示:回测显示当前行情下顺势(of_cvd_trend)≈47%、fade(of_cvd_fade)≈52%,均未达 55.6% 保本线。请结合回测对比选择。')}
      </div>

      <div>
        <div className="text-sm font-medium mb-2">{t('eventContract.signalParams', '信号参数 (window / thr)')}</div>
        <table className="text-sm">
          <tbody>
            {Object.keys(cfg.signal_params).map((key) => (
              <tr key={key}>
                <td className="pr-3 py-1 font-mono">{key}</td>
                <td className="pr-2"><input type="number" value={cfg.signal_params[key].window}
                  onChange={(e) => setParam(key, 'window', Number(e.target.value))}
                  className="border rounded px-2 py-1 bg-background w-20" /></td>
                <td><input type="number" step="0.05" value={cfg.signal_params[key].thr}
                  onChange={(e) => setParam(key, 'thr', Number(e.target.value))}
                  className="border rounded px-2 py-1 bg-background w-20" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving}
          className="px-3 py-1 text-sm rounded bg-primary text-primary-foreground disabled:opacity-50">
          {saving ? t('eventContract.saving', '保存中…') : t('eventContract.save', '保存')}
        </button>
        {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
      </div>
    </div>
  )
}
