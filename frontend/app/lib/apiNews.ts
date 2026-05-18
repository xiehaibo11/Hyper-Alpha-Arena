import { apiRequest } from './apiClient'

export interface NewsSourceConfig {
  type: string
  adapter: string
  url: string
  enabled: boolean
  interval_seconds: number
  config?: Record<string, any>
}

export interface NewsSourcesResponse {
  sources: NewsSourceConfig[]
}

export interface NewsSourcesUpdateResponse {
  success: boolean
  message: string
  sources: NewsSourceConfig[]
}

export interface NewsSourcePreviewArticle {
  title: string
  summary: string
  published_at?: string | null
  source_domain?: string | null
  source_url: string
  validation_issues?: string[]
}

export interface NewsSourceValidationIssue {
  source_url: string
  issues: string[]
}

export interface NewsSourceValidationResult {
  schema_match: boolean
  valid_articles: number
  invalid_articles: number
  issues: NewsSourceValidationIssue[]
}

export interface TestNewsSourceResponse {
  success: boolean
  error?: string
  total_fetched?: number
  articles: NewsSourcePreviewArticle[]
  validation?: NewsSourceValidationResult
}

export interface NewsStatsResponse {
  total_articles: number
  classified: number
  with_sentiment: number
  last_24h: {
    by_domain: Record<string, number>
    by_sentiment: Record<string, number>
    total: number
  }
  latest_article_at?: string | null
}

export async function getNewsSources(): Promise<NewsSourcesResponse> {
  const response = await apiRequest('/news/sources')
  return response.json()
}

export async function updateNewsSources(sources: NewsSourceConfig[]): Promise<NewsSourcesUpdateResponse> {
  const response = await apiRequest('/news/sources', {
    method: 'PUT',
    body: JSON.stringify({ sources }),
  })
  return response.json()
}

export async function testNewsSource(
  payload: Pick<NewsSourceConfig, 'url' | 'adapter'> & { config?: Record<string, any> }
): Promise<TestNewsSourceResponse> {
  const response = await apiRequest('/news/sources/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return response.json()
}

export async function getNewsStats(): Promise<NewsStatsResponse> {
  const response = await apiRequest('/news/stats')
  return response.json()
}
