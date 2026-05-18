// API configuration
const API_BASE_URL = process.env.NODE_ENV === 'production'
  ? '/api'
  : '/api'  // Use proxy, don't hardcode port

async function getErrorMessage(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status}: ${response.statusText || 'Request failed'}`
  const contentType = response.headers.get('content-type') || ''

  try {
    if (contentType.includes('application/json')) {
      const errorData = await response.json()
      const detail = errorData?.detail || errorData?.message || errorData?.error
      const detailText = typeof detail === 'string' ? detail : JSON.stringify(detail)
      return detailText ? `HTTP ${response.status}: ${detailText}` : fallback
    }

    const text = await response.text()
    if (!text) return fallback
    return `HTTP ${response.status}: ${text.slice(0, 300)}`
  } catch {
    return fallback
  }
}

// Helper function for making API requests
export async function apiRequest(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const url = `${API_BASE_URL}${endpoint}`

  const defaultOptions: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  }

  const response = await fetch(url, defaultOptions)

  if (!response.ok) {
    throw new Error(await getErrorMessage(response))
  }

  const contentType = response.headers.get('content-type')
  if (!contentType || !contentType.includes('application/json')) {
    throw new Error('Response is not JSON')
  }

  return response
}
