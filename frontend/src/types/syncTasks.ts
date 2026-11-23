export type SyncEndpointType = 'local' | 'openlist' | 'netdisk'

export type SyncMode = 'one_way' | 'two_way'

export type SyncEndpoint = {
  type: SyncEndpointType
  path: string
  account_id?: number | null
  account_name?: string | null
  drive_type?: string | null
}

export type SyncStrategy = {
  overwrite: boolean
  one_way_delete_extras: boolean
  /** 删除多余文件延时（分钟）：0/5/10/.../30，0=立即删除 */
  one_way_delete_extras_delay_minutes?: number
  force_refresh: boolean
  concurrency: number
  request_interval_seconds: number
  openlist_copy_batch_size: number
  /** 同步 zip 后自动解压、按前缀重命名并删除 zip */
  unzip_zip_after_sync?: boolean
  auto_wash?: boolean
}

export type SyncExecutionItem = {
  id: number
  sync_task_id: number
  status: string
  started_at: string
  finished_at?: string | null
  stage?: string | null
  run_log?: string | null
  stats: Record<string, any>
  message?: string | null
  cancel_requested_at?: string | null
  cancel_requested_by?: number | null
  cancel_message?: string | null
}

export type SyncExecutionFileItem = {
  id: number
  sync_execution_id: number
  path: string
  action: string
  status: string
  size?: number | null
  message?: string | null
  updated_at: string
  created_at: string
}

export type SyncExecutionFilePage = {
  items: SyncExecutionFileItem[]
  total: number
  offset: number
  limit: number
}

export type SyncTaskItem = {
  id: number
  uid: string
  name: string
  enabled: boolean
  source: SyncEndpoint
  target: SyncEndpoint
  mode: SyncMode
  strategy: SyncStrategy
  drama_task_uids?: string[]
  addition?: Record<string, any>
  is_running?: boolean
  running_execution_id?: number | null
  created_at: string
  updated_at: string
}
