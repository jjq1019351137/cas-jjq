export type ResourceSearchSourceKey = 'net' | 'cloudsaver' | 'pansou'

export const RESOURCE_SEARCH_SOURCE_LABELS: Record<string, string> = {
  net: 'Net',
  cloudsaver: 'CloudSaver',
  pansou: 'PanSou',
}

export type ResourceSearchSourceItem = {
  key: ResourceSearchSourceKey
  enabled: boolean
  server?: string | null
  username?: string | null
  password?: string | null
  token?: string | null
}

export type ResourceSearchSourceListResponse = {
  sources: ResourceSearchSourceItem[]
}

export type TaskSuggestionItem = {
  taskname: string
  shareurl: string
  content?: string | null
  datetime?: string | null
  channel?: string | null
  source?: string | null
  source_key?: string | null
  verify?: boolean | null
  maxFileSize?: number | null
  isLargest?: boolean
}

export type TaskSuggestionResponse = {
  success: boolean
  data: TaskSuggestionItem[]
  message?: string | null
}

export type TaskSuggestionVerifyItem = {
  shareurl: string
  drive_type?: string | null
  ok: boolean
  message?: string | null
  pdir_fid?: string | null
  max_file_size?: number | null
  latest_video?: Record<string, any> | null
  is_largest?: boolean
}

export type TaskSuggestionVerifyResponse = {
  items: TaskSuggestionVerifyItem[]
  total: number
  valid: number
  invalid: number
}

