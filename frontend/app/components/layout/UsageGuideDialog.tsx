import { forwardRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

interface UsageGuideDialogProps extends React.HTMLAttributes<HTMLElement> {
  children: React.ReactNode
}

interface GuideSection {
  title: string
  body: string[]
}

// Local usage guide content. Edit these sections freely; when you deploy to a
// server you can either keep this in-app guide or point the trigger to a URL.
const GUIDE: Record<'zh' | 'en', { title: string; sections: GuideSection[] }> = {
  zh: {
    title: '使用指南',
    sections: [
      {
        title: '1. 快速开始',
        body: [
          '在左侧导航进入各功能页：行情 K 线、AI 交易员、程序交易、信号、因子等。',
          '首次使用建议先在测试环境熟悉流程，再切换到实盘。',
        ],
      },
      {
        title: '2. 绑定交易所',
        body: [
          '支持 Hyperliquid（钱包签名）与币安合约（API Key）。',
          '在设置中填入对应凭证后即可拉取行情与下单。',
        ],
      },
      {
        title: '3. 配置策略',
        body: [
          'AI 交易员：用自然语言描述策略，AI 实时分析并决策。',
          '程序交易：用规则/代码定义策略，可先回测验证。',
          '信号：监控市场资金流，满足条件自动触发。',
        ],
      },
      {
        title: '4. 需要帮助',
        body: [
          '有任何问题，欢迎通过 Telegram 直接联系我们：https://t.me/WhimSeeker',
        ],
      },
    ],
  },
  en: {
    title: 'User Guide',
    sections: [
      {
        title: '1. Getting Started',
        body: [
          'Use the left navigation to open each page: K-Lines, AI Trader, Program Trader, Signals, Factors, and more.',
          'For your first run, get familiar in a test environment before going live.',
        ],
      },
      {
        title: '2. Connect an Exchange',
        body: [
          'Supports Hyperliquid (wallet signing) and Binance Futures (API key).',
          'Enter your credentials in Settings to stream market data and place orders.',
        ],
      },
      {
        title: '3. Configure a Strategy',
        body: [
          'AI Trader: describe your strategy in natural language; the AI analyzes and decides in real time.',
          'Program Trader: define rules/code, and backtest before going live.',
          'Signals: monitor market flow and trigger automatically when conditions are met.',
        ],
      },
      {
        title: '4. Need Help',
        body: [
          'Questions? Contact us directly on Telegram: https://t.me/WhimSeeker',
        ],
      },
    ],
  },
}

const UsageGuideDialog = forwardRef<HTMLElement, UsageGuideDialogProps>(
  function UsageGuideDialog({ children, ...triggerProps }, ref) {
  const { i18n } = useTranslation()
  const lang = i18n.language?.startsWith('zh') ? 'zh' : 'en'
  const guide = GUIDE[lang]

  return (
    <Dialog>
      <DialogTrigger asChild ref={ref} {...triggerProps}>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{guide.title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-5 py-2">
          {guide.sections.map((section) => (
            <div key={section.title} className="space-y-1.5">
              <h3 className="text-sm font-semibold">{section.title}</h3>
              {section.body.map((line, i) => (
                <p key={i} className="text-sm text-muted-foreground leading-relaxed">
                  {line}
                </p>
              ))}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
})

export default UsageGuideDialog
