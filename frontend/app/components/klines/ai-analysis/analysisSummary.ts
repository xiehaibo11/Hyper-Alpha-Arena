export function getAnalysisSummary(analysis: string) {
  if (!analysis) return ''

  const lines = analysis.split('\n')
  const summaryLines = []
  let foundFirstSection = false

  for (const line of lines) {
    if (line.startsWith('## ')) {
      if (foundFirstSection) break
      foundFirstSection = true
      summaryLines.push(line)
    } else if (foundFirstSection && line.trim()) {
      summaryLines.push(line)
      if (summaryLines.length >= 5) break
    }
  }

  return summaryLines.join('\n') || analysis.substring(0, 200) + '...'
}
