export type AuditLogItem = {
  id: number
  created_at: string

  actor_type: string
  actor_user_id?: number | null
  actor_username?: string | null

  source?: string | null
  source_label?: string | null
  category: string
  category_label: string
  action: string
  action_label: string

  target_type?: string | null
  target_id?: string | null
  target_name?: string | null

  summary: string
  ip?: string | null
  success: boolean
  error_message?: string | null
  has_detail: boolean
}

export type AuditLogDetail = AuditLogItem & {
  detail?: string | null
}

export type AuditLogListResponse = {
  page: number
  page_size: number
  total: number
  items: AuditLogItem[]
}

export type AuditActionMeta = {
  code: string
  label: string
  category: string
  category_label: string
}

export type AuditActionRegistry = {
  actions: AuditActionMeta[]
  categories: Record<string, string>
  sources: Record<string, string>
}
