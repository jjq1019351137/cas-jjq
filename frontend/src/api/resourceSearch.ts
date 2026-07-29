import { http } from '@/api/http'
import type { ResourceSearchSourceKey, ResourceSearchSourceListResponse, TaskSuggestionResponse, TaskSuggestionVerifyResponse } from '@/types/resourceSearch'

export async function fetchResourceSearchSources() {
  const { data } = await http.get<ResourceSearchSourceListResponse>('/resource-search/sources')
  return data
}

export async function patchResourceSearchSource(key: ResourceSearchSourceKey, payload: Partial<{ enabled: boolean; server: string | null; username: string | null; password: string | null; token: string | null }>) {
  const { data } = await http.patch<ResourceSearchSourceListResponse>(`/resource-search/sources/${encodeURIComponent(key)}`, payload)
  return data
}

export async function fetchTaskSuggestions(
  q: string,
  d: number,
  drive_type?: string | null,
  sources?: string[] | null,
  drive_types?: string[] | null,
) {
  const params: any = { q, d }
  const dt = String(drive_type || '').trim()
  if (dt) params.drive_type = dt
  const dts = (drive_types || []).map((x) => String(x || '').trim()).filter(Boolean)
  if (!dt && dts.length) params.drive_types = dts.join(',')
  const src = (sources || []).map((x) => String(x || '').trim()).filter(Boolean)
  if (src.length) params.sources = src.join(',')
  const { data } = await http.get<TaskSuggestionResponse>('/tasks/suggestions', { params, timeout: 60000 })
  return data
}

export async function verifyTaskSuggestions(shareurls: string[], account_name?: string | null) {
  const urls = (shareurls || []).map((x) => String(x || '').trim()).filter(Boolean)
  if (!urls.length) return { items: [], total: 0, valid: 0, invalid: 0 } as TaskSuggestionVerifyResponse
  const { data } = await http.post<TaskSuggestionVerifyResponse>(
    '/tasks/suggestions/verify',
    { shareurls: urls, account_name: account_name ?? null },
    { timeout: 120000, headers: { 'X-Retryable': '1' } },
  )
  return data
}
