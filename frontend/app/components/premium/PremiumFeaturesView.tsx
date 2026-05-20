'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'react-hot-toast'
import {
  Activity,
  BarChart3,
  Database,
  Info,
  LineChart,
  Sparkles,
  Target,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'

interface PremiumFeaturesViewProps {
  onAccountUpdated?: () => void
  onPageChange?: (page: string) => void
}

const TECHNICAL_INDICATORS = [
  { name: 'MA5 / MA10 / MA20', category: 'Trend' },
  { name: 'EMA20 / EMA50 / EMA100', category: 'Trend' },
  { name: 'VWAP / OBV', category: 'Volume' },
  { name: 'RSI7 / RSI14 / STOCH', category: 'Momentum' },
  { name: 'MACD', category: 'Momentum' },
  { name: 'BOLL / ATR14', category: 'Volatility' },
]

const DEPTH_OPTIONS = [10, 20, 30, 40, 50, 60]

function getCopy(language: string) {
  const isZh = language.toLowerCase().startsWith('zh')
  return isZh
    ? {
        title: '高级功能',
        subtitle: '站内交易工具已直接开放，无需额外开通。',
        dataTools: '数据与决策',
        analysisTools: '分析工具',
        openAccess: '已开放',
        aiContext: 'AI 决策上下文',
        realtimeSignals: '实时信号与信号池',
        quantAnalysis: '量化分析',
        samplingTitle: '采样池深度',
        samplingDesc: '增加 AI 可查看的近期市场样本数量，用于趋势和波动判断。',
        samplingDepth: '采样深度',
        currentConfig: '当前配置',
        samplingInterval: '采样间隔',
        dataCoverage: '数据覆盖',
        storage: '存储方式',
        rolling: '滚动缓存',
        save: '保存配置',
        saving: '保存中...',
        saved: '采样深度已保存',
        loading: '正在加载高级功能配置...',
        loadFailed: '加载高级功能配置失败',
        saveFailed: '保存配置失败',
        loginRequired: '请先登录再保存配置',
        promptLoginRequired: '请先登录再使用提示词工具',
        promptTitle: 'AI 提示词生成',
        promptDesc: '用对话方式生成和优化交易策略提示词。',
        promptAction: '打开提示词工具',
        keyFeatures: '能力',
        promptItems: ['自然语言对话', '多轮策略修订', '自动选择变量', '版本管理'],
        indicatorTitle: '技术指标套件',
        indicatorDesc: '按页面选择的币种和周期读取指标，供图表和 AI 分析使用。',
        periodSupport: '支持周期',
        openKlines: '打开 K 线分析',
        quantTitle: 'AI 量化分析',
        quantDesc: '结合 K 线、指标、市场流和持仓上下文生成分析。',
        quantItems: ['形态识别', '多周期共振', '动量背离', '支撑阻力聚类', '风险收益评估'],
        signalTitle: 'AI 信号生成',
        signalDesc: '通过自然语言创建信号和信号池，并绑定 AI 触发决策。',
        signalItems: ['自然语言转信号', '阈值参数建议', '多条件 AND/OR 组合', '触发 AI 交易评估'],
        openSignals: '创建信号',
        estimatedBoost: '预计提升',
      }
    : {
        title: 'Advanced Features',
        subtitle: 'All in-site trading tools are open for this deployment.',
        dataTools: 'Data and Decision',
        analysisTools: 'Analysis Tools',
        openAccess: 'Open',
        aiContext: 'AI decision context',
        realtimeSignals: 'Realtime signals and pools',
        quantAnalysis: 'Quant analysis',
        samplingTitle: 'Sampling Pool Depth',
        samplingDesc: 'Increase recent market samples available to AI for trend and volatility checks.',
        samplingDepth: 'Sampling depth',
        currentConfig: 'Current Configuration',
        samplingInterval: 'Sampling Interval',
        dataCoverage: 'Data Coverage',
        storage: 'Storage',
        rolling: 'Rolling buffer',
        save: 'Save Configuration',
        saving: 'Saving...',
        saved: 'Sampling depth saved',
        loading: 'Loading advanced configuration...',
        loadFailed: 'Failed to load advanced configuration',
        saveFailed: 'Failed to save configuration',
        loginRequired: 'Please log in before saving configuration',
        promptLoginRequired: 'Please log in to use the prompt tool',
        promptTitle: 'AI Prompt Generator',
        promptDesc: 'Create and refine trading strategy prompts through conversation.',
        promptAction: 'Open Prompt Tool',
        keyFeatures: 'Capabilities',
        promptItems: ['Natural language dialogue', 'Multi-turn strategy editing', 'Automatic variable selection', 'Version management'],
        indicatorTitle: 'Technical Indicator Suite',
        indicatorDesc: 'Read indicators for the selected symbol and timeframe for charts and AI analysis.',
        periodSupport: 'Supported Periods',
        openKlines: 'Open K-line Analysis',
        quantTitle: 'AI Quant Analysis',
        quantDesc: 'Combine K-lines, indicators, market flow, and position context into analysis.',
        quantItems: ['Pattern recognition', 'Multi-timeframe confluence', 'Momentum divergence', 'Support/resistance clustering', 'Risk/reward assessment'],
        signalTitle: 'AI Signal Generator',
        signalDesc: 'Create signals and signal pools with natural language, then bind them to AI decisions.',
        signalItems: ['Natural language to signal', 'Threshold suggestions', 'AND/OR condition groups', 'Trigger AI trade evaluation'],
        openSignals: 'Create Signal',
        estimatedBoost: 'Estimated boost',
      }
}

function estimateBoost(depth: number) {
  if (depth <= 10) return 0
  const steps = (depth - 10) / 10
  return Math.round(Math.pow(2, steps) * 10 - 10)
}

function CapabilityList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="space-y-1 p-3 bg-muted/50 rounded-lg text-xs">
      <div className="font-medium flex items-center gap-2">
        <Info className="w-3 h-3" />
        {title}
      </div>
      <div className="space-y-0.5 text-muted-foreground ml-5">
        {items.map((item) => (
          <div key={item}>- {item}</div>
        ))}
      </div>
    </div>
  )
}

export default function PremiumFeaturesView({ onPageChange }: PremiumFeaturesViewProps) {
  const { i18n } = useTranslation()
  const { user } = useAuth()
  const copy = useMemo(() => getCopy(i18n.language), [i18n.language])

  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [samplingDepth, setSamplingDepth] = useState(10)
  const [samplingInterval, setSamplingInterval] = useState(18)

  useEffect(() => {
    fetchGlobalConfig()
  }, [])

  const fetchGlobalConfig = async () => {
    try {
      setIsLoading(true)
      const response = await fetch('/api/config/global-sampling')
      if (!response.ok) throw new Error(copy.loadFailed)
      const data = await response.json()
      setSamplingDepth(data.sampling_depth || 10)
      setSamplingInterval(data.sampling_interval || 18)
    } catch (error) {
      console.error('Failed to fetch global config:', error)
      toast.error(copy.loadFailed)
    } finally {
      setIsLoading(false)
    }
  }

  const handlePromptToolClick = () => {
    if (!user) {
      toast.error(copy.promptLoginRequired)
      return
    }
    onPageChange?.('prompt-management')
  }

  const handleSaveConfiguration = async () => {
    if (!user) {
      toast.error(copy.loginRequired)
      return
    }

    setIsSaving(true)
    try {
      const response = await fetch('/api/config/global-sampling', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sampling_depth: samplingDepth }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || copy.saveFailed)
      }

      toast.success(copy.saved)
      await fetchGlobalConfig()
    } catch (error) {
      console.error('Failed to save sampling configuration:', error)
      toast.error(error instanceof Error ? error.message : copy.saveFailed)
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">{copy.loading}</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-5 border-b">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{copy.title}</h1>
            <Badge className="bg-green-600 text-white">{copy.openAccess}</Badge>
          </div>
          <p className="text-muted-foreground">{copy.subtitle}</p>
          <div className="flex flex-wrap gap-3 text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Target className="w-4 h-4" />
              <span>{copy.aiContext}</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <Activity className="w-4 h-4" />
              <span>{copy.realtimeSignals}</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <TrendingUp className="w-4 h-4" />
              <span>{copy.quantAnalysis}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="space-y-8">
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Database className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold">{copy.dataTools}</h2>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-lg">{copy.samplingTitle}</CardTitle>
                  <CardDescription className="text-xs">{copy.samplingDesc}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium">{copy.samplingDepth}</span>
                      <span className="text-xs text-muted-foreground">{samplingDepth}</span>
                    </div>
                    <div className="grid grid-cols-6 gap-2">
                      {DEPTH_OPTIONS.map((depth) => (
                        <Button
                          key={depth}
                          variant={samplingDepth === depth ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => setSamplingDepth(depth)}
                          className="h-8 text-xs"
                        >
                          {depth}
                        </Button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1 p-3 bg-muted/50 rounded-lg text-xs">
                    <div className="font-medium flex items-center gap-2">
                      <Info className="w-3 h-3" />
                      {copy.currentConfig}
                    </div>
                    <div className="space-y-0.5 text-muted-foreground ml-5">
                      <div>- {copy.samplingInterval}: {samplingInterval}s</div>
                      <div>- {copy.dataCoverage}: {((samplingDepth * samplingInterval) / 60).toFixed(1)}m</div>
                      <div>- {copy.storage}: {copy.rolling}</div>
                      <div>- {copy.estimatedBoost}: +{estimateBoost(samplingDepth)}%</div>
                    </div>
                  </div>

                  <Button onClick={handleSaveConfiguration} disabled={isSaving} className="w-full h-8 text-xs">
                    {isSaving ? copy.saving : copy.save}
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Sparkles className="w-5 h-5 text-purple-500" />
                    {copy.promptTitle}
                  </CardTitle>
                  <CardDescription className="text-xs">{copy.promptDesc}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <CapabilityList title={copy.keyFeatures} items={copy.promptItems} />
                  <Button
                    onClick={handlePromptToolClick}
                    className="w-full h-8 text-xs bg-purple-600 hover:bg-purple-700 text-white"
                  >
                    <Sparkles className="w-3 h-3 mr-1" />
                    {copy.promptAction}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold">{copy.analysisTools}</h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <LineChart className="w-5 h-5 text-blue-500" />
                    {copy.indicatorTitle}
                  </CardTitle>
                  <CardDescription className="text-xs">{copy.indicatorDesc}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-1 gap-2">
                    {TECHNICAL_INDICATORS.map((indicator) => (
                      <div key={indicator.name} className="flex items-center justify-between gap-2 p-2 border rounded-lg text-xs">
                        <span className="font-medium">{indicator.name}</span>
                        <Badge variant="outline" className="text-[10px] px-1 py-0">{indicator.category}</Badge>
                      </div>
                    ))}
                  </div>
                  <div className="p-2 bg-muted/50 rounded-lg text-xs text-muted-foreground">
                    <div className="font-medium mb-1">{copy.periodSupport}</div>
                    <div>1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 12h, 1d, 3d, 1w, 1M</div>
                  </div>
                  <Button onClick={() => onPageChange?.('klines')} className="w-full h-8 text-xs">
                    {copy.openKlines}
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-lg">{copy.quantTitle}</CardTitle>
                  <CardDescription className="text-xs">{copy.quantDesc}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <CapabilityList title={copy.keyFeatures} items={copy.quantItems} />
                  <Button onClick={() => onPageChange?.('klines')} className="w-full h-8 text-xs">
                    {copy.openKlines}
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Zap className="w-5 h-5 text-yellow-500" />
                    {copy.signalTitle}
                  </CardTitle>
                  <CardDescription className="text-xs">{copy.signalDesc}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <CapabilityList title={copy.keyFeatures} items={copy.signalItems} />
                  <Button
                    onClick={() => onPageChange?.('signal-management')}
                    className="w-full h-8 text-xs bg-yellow-600 hover:bg-yellow-700 text-white"
                  >
                    <Zap className="w-3 h-3 mr-1" />
                    {copy.openSignals}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
