import { http } from '@/api/http'
import type { AuditActionRegistry, AuditLogDetail, AuditLogListResponse } from '@/types/audit'

export async function fetchAuditLogs(params: {
  page: number
  page_size: number
  q?: string
  action?: string
  category?: string
  source?: string
  success?: boolean
}) {
  const { data } = await http.get<AuditLogListResponse>('/audit-logs', { params })
  return data
}

export async function fetchAuditActionRegistry() {
  const { data } = await http.get<AuditActionRegistry>('/audit-logs/actions')
  return data
}

export async function fetchAuditLogDetail(id: number) {
  const { data } = await http.get<AuditLogDetail>(`/audit-logs/${id}`)
  return data
}
