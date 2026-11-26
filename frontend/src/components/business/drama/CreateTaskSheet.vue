<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  X, Eye, Loader2, Folder, FolderOpen, Search,
  Play, ArrowUp, ArrowDown, FileText, GripVertical, BookOpen, Check,
  ChevronDown, ChevronRight,
} from 'lucide-vue-next'
import { previewShare, previewShareBatch, browseDrive, fetchTasks } from '@/api/tasks'
import type { TaskSuggestionItem } from '@/types/resourceSearch'
import ResourceSearchDialog, { type ResourceSearchAction } from '@/components/business/drama/ResourceSearchDialog.vue'
import SharePreviewDialog from '@/components/business/drama/SharePreviewDialog.vue'
import { searchTMDB, fetchTMDBDetail } from '@/api/media'
import { useToast } from '@/composables/useToast'
import { useCreateTaskMutation, useUpdateTaskMutation, useCheckTaskShareUrlsMutation, useActivateTaskShareUrlMutation } from '@/hooks/mutations/tasks'
import { useDriveAccountsQuery, usePluginsQuery } from '@/hooks/queries/extensions'
import { useSyncTasksQuery } from '@/hooks/queries/sync'
import { useTasksQuery, useMagicRegexQuery } from '@/hooks/queries/tasks'
import { detectDriveTypeByUrl } from '@/utils/driveType'
import type { DramaTaskPreset } from '@/types/dramaLauncher'
import type { TaskItem, SharePreviewItem, DriveBrowseItem, TaskShareUrlItem } from '@/types/tasks'
import type { TMDBBrief } from '@/types/media'

const props = defineProps<{
  open: boolean
  editTask?: TaskItem
  presetTmdb?: DramaTaskPreset | null
}>()

const emit = defineEmits<{
  close: []
  'run-once': [payload: Record<string, any>]
}>()

const { toast } = useToast()
const createMutation = useCreateTaskMutation()
const updateMutation = useUpdateTaskMutation()
const checkShareUrlsMutation = useCheckTaskShareUrlsMutation()
const activateShareUrlMutation = useActivateTaskShareUrlMutation()
const { data: accountsData } = useDriveAccountsQuery()
const { data: syncTasksData } = useSyncTasksQuery()
const { data: pluginsData } = usePluginsQuery()
const { data: tasksData } = useTasksQuery()
const { data: magicRegexData } = useMagicRegexQuery()

const plugins = computed(() =>
  (pluginsData.value || []).filter((p) => p.enabled && p.task_config_fields && p.task_config_fields.length > 0),
)

const activeAccounts = computed(() =>
  (accountsData.value || []).filter((a) => a.enabled && a.runtime_status === 'active'),
)
const syncTasks = computed(() => syncTasksData.value || [])

const isEditing = computed(() => Boolean(props.editTask?.id))
const title = computed(() => (isEditing.value ? '编辑追剧任务' : '新建追剧任务'))

// Form state
const state = reactive({
  taskname: '',
  shareurl: '',
  savepath: '',
  account_choice: '__AUTO__' as string,
  tmdb_id: null as number | null,
  tmdb_media_type: 'tv' as 'tv' | 'movie',
  pattern: '',
  replace: '',
  ignore_extension: true,
  runweek_mode: 'manual' as 'auto' | 'manual',
  runweek: [] as number[],
  enddate: '',
  enabled: true,
  auto_update_115_shareurl: true,
  sync_task_uids: [] as string[],
  sort_index: 1 as number | null,
  startfid: '',
  update_subdir: '',
  update_subdir_resave_mode: 'none' as 'none' | 'resave' | 'resave_all',
  addition: {} as Record<string, Record<string, any>>,
})

// Preview state
const previewing = ref(false)
const previewError = ref('')
const previewItems = ref<SharePreviewItem[]>([])
const previewTotal = ref(0)
const showPreviewModal = ref(false)

// Path browser state
const showPathBrowser = ref(false)
const browsePath = ref('/')
const browseItems = ref<DriveBrowseItem[]>([])
const browseLoading = ref(false)
const browseError = ref('')

// TMDB search state
const showTmdbSearch = ref(false)
const tmdbQuery = ref('')
const tmdbSearching = ref(false)
const tmdbResults = ref<TMDBBrief[]>([])
const tmdbSearchConfigured = ref(true)

// StartFID picker state
const showStartfidPicker = ref(false)
const startfidItems = ref<SharePreviewItem[]>([])
const startfidLoading = ref(false)
const startfidError = ref('')

// UI state
const submitting = ref(false)

// Auto-preview state
const previewHint = ref('')
const autoPreviewTimer = ref<any>(null)
const autoLocateRunId = ref(0)
const skipNextShareurlAutoLocate = ref(false)
const savepathTouched = ref(false)
const savepathLastApplied = ref('')
const tmdbDetailCache = ref<Record<string, any>>({})
const isInitializing = ref(false)

// Resource search dialog state
const showResourceSearch = ref(false)
const resourceSearchOpening = ref(false)
const resourceSearchQuery = ref('')

// ===== 备用分享链接 =====
/** 备用链接行（不含主链接）；主链接始终为 state.shareurl */
type BackupLinkRow = {
  url: string
  status: 'unknown' | 'ok' | 'invalid' | string
  reason?: string | null
  last_checked_at?: string | null
  /** 正在自动定位实际文件夹 */
  locating?: boolean
}
const backupLinks = ref<BackupLinkRow[]>([])
/** 链接列表上限（与后端 MAX_SHARE_LINKS 一致）：主链接 + 备用链接合计 */
const MAX_SHARE_LINKS = 10
const MAX_BACKUP_LINKS = MAX_SHARE_LINKS - 1
const backupInput = ref('')
const backupChecking = ref(false)
const backupEditSnapshot = ref('')
/** 正在调用 activate 接口切换主链接的行序号 */
const promotingIndex = ref<number | null>(null)
const mainLinkStatus = ref<BackupLinkRow['status']>('unknown')
const mainLinkReason = ref<string | null>(null)

// 备用链接预览（与主链接预览一致，可选目录）
const backupPreviewVisible = ref(false)
const backupPreviewUrl = ref('')
/** 当前预览的备用链接行引用，供“使用当前文件夹”写回对应行 */
const backupPreviewRow = ref<BackupLinkRow | null>(null)

// 资源搜索打开来源：main=主链接旁搜索；backup=备用区搜索添加；replace:{index}=换链
const resourceSearchOrigin = ref<'main' | 'backup' | `replace:${number}`>('main')

const RESOURCE_ACTIONS_MAIN: ResourceSearchAction[] = [
  { key: 'replace_main', label: '替换主链接', min: 1, max: 1 },
  { key: 'append_backup', label: '追加为备用链接', min: 1 },
]
const RESOURCE_ACTIONS_BACKUP: ResourceSearchAction[] = [
  { key: 'append_backup', label: '追加为备用链接', min: 1 },
]
const RESOURCE_ACTIONS_REPLACE: ResourceSearchAction[] = [
  { key: 'replace_one', label: '替换此链接', min: 1, max: 1 },
]

const resourceSearchActions = computed(() => {
  const origin = resourceSearchOrigin.value
  if (origin === 'main') return RESOURCE_ACTIONS_MAIN
  if (origin === 'backup') return RESOURCE_ACTIONS_BACKUP
  return RESOURCE_ACTIONS_REPLACE
})

function isPluginEnabled(key: string): boolean {
  return key in state.addition
}
function togglePluginEnabled(key: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    const plugin = plugins.value.find(p => p.plugin_key === key)
    if (plugin) {
      state.addition = { ...state.addition, [key]: { ...(plugin.default_task_config || {}) } }
    } else {
      state.addition = { ...state.addition, [key]: {} }
    }
  } else {
    const { [key]: _, ...rest } = state.addition
    state.addition = rest
  }
}

/** 插件详细字段默认折叠，点击标题展开 */
const expandedPluginKeys = ref<Set<string>>(new Set())
function isPluginExpanded(key: string): boolean {
  return expandedPluginKeys.value.has(key)
}
function togglePluginExpanded(key: string) {
  const next = new Set(expandedPluginKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedPluginKeys.value = next
}

// Builtin rename rules —— 从后端 /tasks/magic-regex 拉取。
// 选择内置/魔法规则时写入 key（如 $TV_REGEX），replace 留空，运行时走最新生效规则；
// 避免把旧版展开式 \1E\2.\3 固化进任务（纯数字文件名会得到 E01.zip）。
const builtinRules = computed(() => {
  const fetched = (magicRegexData.value?.rules || []).map((r) => ({
    key: r.key || '',
    label: r.label ? `${r.label}（${r.key}）` : r.key,
    pattern: r.pattern || '',
    replace: r.replace || '',
  }))
  return [{ key: '', label: '自定义 / 不使用', pattern: '', replace: '' }, ...fetched]
})
// 依据当前 pattern/replace 反查命中的内置规则，便于编辑已有任务时回显选择
const selectedRuleIdx = computed(() => {
  const rules = builtinRules.value
  const p = state.pattern || ''
  const r = state.replace || ''
  if (!p && !r) return 0
  // 已存魔法 key（replace 通常为空）
  if (p.startsWith('$')) {
    const byKey = rules.findIndex((rule, i) => i > 0 && rule.key === p)
    if (byKey >= 0) return byKey
  }
  // 兼容历史任务：展开后的 pattern/replace
  const idx = rules.findIndex((rule, i) => i > 0 && rule.pattern === p && rule.replace === r)
  return idx >= 0 ? idx : 0
})

function applyBuiltinRule(event: Event) {
  const idx = Number((event.target as HTMLSelectElement).value)
  const rules = builtinRules.value
  if (idx < 0 || idx >= rules.length) return
  if (idx === 0) {
    state.pattern = ''
    state.replace = ''
    return
  }
  const rule = rules[idx]
  if (rule.key) {
    state.pattern = rule.key
    state.replace = ''
    return
  }
  state.pattern = rule.pattern
  state.replace = rule.replace
}

// Weekday options
const weekdays = [
  { value: 1, label: '一' },
  { value: 2, label: '二' },
  { value: 3, label: '三' },
  { value: 4, label: '四' },
  { value: 5, label: '五' },
  { value: 6, label: '六' },
  { value: 7, label: '日' },
]

// Helpers
function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + 'MB'
  return (bytes / 1073741824).toFixed(2) + 'GB'
}

// Sync state from editTask
/**
 * 已初始化的表单标识：避免弹窗打开期间任务列表 refetch（如“验证全部”/“设为主链接”触发
 * invalidateQueries 后新的 editTask 对象）重新初始化表单，把尚未保存的备用链接与链接状态覆盖掉。
 */
const initializedFormKey = ref('')
watch(
  () => [props.open, props.editTask, props.presetTmdb] as const,
  ([open, task, preset]) => {
    if (!open) {
      initializedFormKey.value = ''
      return
    }
    const formKey = task?.id ? `task:${task.id}` : `new:${preset?.tmdb_id ?? ''}:${preset?.taskname ?? ''}`
    if (initializedFormKey.value === formKey) return
    initializedFormKey.value = formKey
    const shouldOpenTmdbSearch = !task && Boolean(preset?.open_tmdb_search)
    const nextTmdbQuery = shouldOpenTmdbSearch ? String(preset?.tmdb_search_query || preset?.taskname || '').trim() : ''
    if (task) {
      isInitializing.value = true
      state.taskname = task.taskname || ''
      state.shareurl = task.shareurl || ''
      state.savepath = task.savepath || ''
      state.account_choice = task.account_name ? String(task.account_name) : '__AUTO__'
      state.tmdb_id = task.tmdb_id ?? null
      state.tmdb_media_type = (task.tmdb_media_type as 'tv' | 'movie') || 'tv'
      state.pattern = task.pattern || ''
      state.replace = task.replace || ''
      state.ignore_extension = task.ignore_extension
      state.sort_index = task.sort_index ?? null
      state.startfid = task.startfid || ''
      state.update_subdir = task.update_subdir || ''
      state.enddate = task.enddate || ''
      state.enabled = task.enabled
      state.auto_update_115_shareurl = Boolean(task.extra?.auto_update_115_shareurl ?? true)
      state.update_subdir_resave_mode = String(task.extra?.update_subdir_resave_mode || 'none') as any
      const extra = task.extra || {}
      const rw = Array.isArray((extra as any).runweek) ? (extra as any).runweek : []
      state.runweek = rw.map((x: any) => Number(x)).filter((x: number) => x >= 1 && x <= 7)
      const savedMode = String((extra as any).runweek_mode || '').trim().toLowerCase()
      if (savedMode === 'auto' || savedMode === 'manual') {
        state.runweek_mode = savedMode
      } else if (task.tmdb_id && String(task.tmdb_media_type || '').toLowerCase() === 'tv' && !state.runweek.length) {
        // 历史任务：已关联 TMDB 剧集且未手动配置过更新日，默认自动模式
        state.runweek_mode = 'auto'
        nextTick(() => {
          applyAutoRunweekFromTmdb(Number(task.tmdb_id) || 0, 'tv').catch(() => {})
        })
      } else {
        state.runweek_mode = 'manual'
      }
      const taskUid = String(task.task_uid || '').trim()
      // Use the ordered sync_task_uids from the task response (backend returns them sorted by sort_order)
      const savedSyncUids = Array.isArray(task.sync_task_uids) ? task.sync_task_uids.map((u: any) => String(u || '').trim()).filter(Boolean) : []
      if (savedSyncUids.length > 0) {
        state.sync_task_uids = savedSyncUids
      } else {
        state.sync_task_uids = taskUid
          ? syncTasks.value
              .filter((st) => Array.isArray(st.drama_task_uids) && st.drama_task_uids.includes(taskUid))
              .map((st) => String(st.uid || '').trim())
              .filter(Boolean)
          : []
      }
      // Load addition from task
      initAdditionFromTask(task.addition)
      initShareLinksFromTask(task.shareurls, task.shareurl || '')
      nextTick(() => { isInitializing.value = false })
    } else {
      resetForm()
      if (preset) {
        state.taskname = preset.taskname || ''
        state.tmdb_id = preset.tmdb_id || null
        state.tmdb_media_type = preset.tmdb_media_type || 'tv'
        // 有TMDB关联时默认使用自动更新日模式
        if (preset.tmdb_id && preset.tmdb_media_type === 'tv') {
          state.runweek_mode = 'auto'
          nextTick(() => {
            applyAutoRunweekFromTmdb(Number(preset.tmdb_id) || 0, preset.tmdb_media_type || 'tv').catch(() => {})
          })
        }
      }
      initAdditionDefaults()
    }
    previewItems.value = []
    previewError.value = ''
    previewTotal.value = 0
    showPathBrowser.value = false
    showTmdbSearch.value = shouldOpenTmdbSearch
    tmdbQuery.value = nextTmdbQuery
    tmdbResults.value = []
    tmdbSearchConfigured.value = true
    showStartfidPicker.value = false
    showPreviewModal.value = false
    savepathTouched.value = Boolean(task)
    savepathLastApplied.value = ''
    autoLocateRunId.value += 1
    // 关闭资源搜索弹窗
    showResourceSearch.value = false
    if (shouldOpenTmdbSearch && nextTmdbQuery) {
      nextTick(() => {
        doTmdbSearch().catch(() => {})
      })
    }
  },
  { immediate: true },
)

function resetForm() {
  state.taskname = ''
  state.shareurl = ''
  state.savepath = ''
  state.account_choice = '__AUTO__'
  state.tmdb_id = null
  state.tmdb_media_type = 'tv'
  state.pattern = ''
  state.replace = ''
  state.ignore_extension = true
  state.runweek_mode = 'manual'
  state.runweek = []
  state.enddate = ''
  state.enabled = true
  state.auto_update_115_shareurl = true
  state.sync_task_uids = []
  state.sort_index = 1
  state.startfid = ''
  state.update_subdir = ''
  state.update_subdir_resave_mode = 'none'
  state.addition = {}
  backupLinks.value = []
  backupInput.value = ''
  mainLinkStatus.value = 'unknown'
  mainLinkReason.value = null
}

// ===== 备用链接管理 =====
/** 从任务回显多链接：首位（is_active）为主链接，其余为备用 */
function initShareLinksFromTask(links: TaskShareUrlItem[] | undefined | null, activeUrl: string) {
  const list = Array.isArray(links) ? links : []
  const active = String(activeUrl || '').trim()
  const mainRow = list.find((x) => x.url === active)
  mainLinkStatus.value = mainRow?.status || 'unknown'
  mainLinkReason.value = mainRow?.reason || null
  backupLinks.value = list
    .filter((x) => x.url && x.url !== active)
    .map((x) => ({ url: x.url, status: x.status || 'unknown', reason: x.reason || null, last_checked_at: x.last_checked_at || null }))
}

/** 当前已占用的链接集合（主链接 + 备用） */
function usedLinkSet(): Set<string> {
  const set = new Set<string>()
  const main = String(state.shareurl || '').trim()
  if (main) set.add(main)
  for (const row of backupLinks.value) set.add(row.url)
  return set
}

/** 同盘校验：备用链接必须与主链接同网盘类型 */
function isSameDriveAsMain(url: string): boolean {
  const main = String(state.shareurl || '').trim()
  if (!main) return true
  const mainDt = detectDriveTypeByUrl(main)
  const dt = detectDriveTypeByUrl(url)
  if (!mainDt || !dt) return false
  return String(mainDt) === String(dt)
}

function appendBackupLinks(urls: string[]): number {
  const used = usedLinkSet()
  let added = 0
  let skippedDup = 0
  let skippedDrive = 0
  let skippedLimit = 0
  const addedRows: BackupLinkRow[] = []
  for (const raw of urls) {
    const url = String(raw || '').trim()
    if (!url) continue
    if (used.has(url)) {
      skippedDup += 1
      continue
    }
    if (!isSameDriveAsMain(url)) {
      skippedDrive += 1
      continue
    }
    if (backupLinks.value.length >= MAX_BACKUP_LINKS) {
      skippedLimit += 1
      continue
    }
    used.add(url)
    backupLinks.value.push({ url, status: 'unknown', reason: null, last_checked_at: null })
    // 持行对象引用（而非行号）：异步定位期间用户可能移动/删除其它行
    addedRows.push(backupLinks.value[backupLinks.value.length - 1])
    added += 1
  }
  if (skippedDup) toast.error(`已跳过 ${skippedDup} 个重复链接`)
  if (skippedDrive) toast.error(`已跳过 ${skippedDrive} 个不同网盘类型的链接`)
  if (skippedLimit) toast.error(`备用链接最多 ${MAX_BACKUP_LINKS} 个，已跳过 ${skippedLimit} 个`)
  if (added) {
    toast.success(`已添加 ${added} 个备用链接`)
    // 与主链接一致：新增后自动定位到实际文件夹
    for (const row of addedRows) locateBackupLink(row).catch(() => {})
  }
  return added
}

/** 自动定位到实际文件夹：先按 resolved_pdir_fid 重写链接，再对单目录下钻一层 */
async function resolveShareurlFolder(rawUrl: string): Promise<string> {
  const url = String(rawUrl || '').trim()
  if (!url) return url
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : null
  let resolved = url
  try {
    const batchRes = await previewShareBatch({ shareurls: [url], account_name: accountName })
    const row = (batchRes.items || []).find((x) => String(x.shareurl || '').trim() === url)
    if (row && row.ok) {
      const fid = String((row as any).pdir_fid || (row as any).resolved_pdir_fid || '').trim()
      // 排除根目录与路径型 fid（如百度的 '/'）：无需/无法重写链接
      if (fid && fid !== '0' && fid !== 'root' && !fid.includes('/')) {
        const next = getShareurl(url, { fid })
        if (next) resolved = next
      }
    }
  } catch {
    return resolved
  }
  try {
    const res = await previewShare(buildPreviewParams({ shareurl: resolved }))
    const items = res.items || []
    if (items.length === 1 && items[0].is_dir) {
      const deep = getShareurl(resolved, { fid: items[0].fid })
      if (deep && deep !== resolved) resolved = deep
    }
  } catch { /* 定位失败保持原链接 */ }
  return resolved
}

/**
 * 对指定备用链接执行自动定位；定位后链接变化则重置校验状态。
 * 按行对象引用操作（不用行号）：异步期间用户上下移/删除其它行时，行号会漂移，
 * 导致 locating 标志被写到错误行上，使那一行永远停在“定位中”且按钮被禁用。
 */
async function locateBackupLink(row: BackupLinkRow) {
  if (!row || !row.url.trim()) return
  const origin = row.url
  row.locating = true
  try {
    const resolved = await resolveShareurlFolder(origin)
    // 定位期间该行可能已被删除或链接被改，仅在仍存在且未变时写回
    if (!backupLinks.value.includes(row) || row.url !== origin) return
    if (resolved && resolved !== origin) {
      const used = usedLinkSet()
      used.delete(origin)
      if (used.has(resolved)) {
        toast.error('自动定位后的链接与已有链接重复，已保留原链接')
        return
      }
      row.url = resolved
      row.status = 'unknown'
      row.reason = null
      row.last_checked_at = null
    }
  } finally {
    row.locating = false
  }
}

/** 备用链接手工编辑完成：同盘/去重校验后重置状态并自动定位 */
function onBackupUrlEdited(index: number, previous: string) {
  const row = backupLinks.value[index]
  if (!row) return
  const url = String(row.url || '').trim()
  row.url = url
  if (!url) {
    row.url = previous
    return
  }
  if (url === previous) return
  const duplicated = [String(state.shareurl || '').trim(), ...backupLinks.value.filter((_x, i) => i !== index).map((x) => x.url)]
    .filter(Boolean)
    .includes(url)
  if (duplicated) {
    toast.error('该链接已存在')
    row.url = previous
    return
  }
  if (!isSameDriveAsMain(url)) {
    toast.error('备用链接必须与主链接同网盘类型')
    row.url = previous
    return
  }
  row.status = 'unknown'
  row.reason = null
  row.last_checked_at = null
}

function addBackupFromInput() {
  const url = backupInput.value.trim()
  if (!url) return
  if (!state.shareurl.trim()) {
    toast.error('请先填写主分享链接')
    return
  }
  if (backupLinks.value.length >= MAX_BACKUP_LINKS) {
    toast.error(`备用链接最多 ${MAX_BACKUP_LINKS} 个`)
    return
  }
  if (appendBackupLinks([url])) backupInput.value = ''
}

function removeBackupLink(index: number) {
  backupLinks.value.splice(index, 1)
}

function moveBackupLink(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= backupLinks.value.length) return
  const arr = [...backupLinks.value]
  const [row] = arr.splice(index, 1)
  arr.splice(target, 0, row)
  backupLinks.value = arr
}

/** 将备用链接提升为主链接（仅调整表单状态） */
function applyPromoteLocally(index: number) {
  const row = backupLinks.value[index]
  if (!row) return
  const oldMain = String(state.shareurl || '').trim()
  const oldStatus = mainLinkStatus.value
  const oldReason = mainLinkReason.value
  skipNextShareurlAutoLocate.value = true
  state.shareurl = row.url
  // 旧版 FID 锚点换链失效；集数锚点可保留
  if (state.startfid && !isEpisodeAnchor(state.startfid)) {
    state.startfid = ''
  }
  mainLinkStatus.value = row.status
  mainLinkReason.value = row.reason || null
  const arr = [...backupLinks.value]
  arr.splice(index, 1)
  if (oldMain) arr.unshift({ url: oldMain, status: oldStatus, reason: oldReason, last_checked_at: null })
  backupLinks.value = arr.slice(0, MAX_BACKUP_LINKS)
}

/**
 * 设为主链接：链接已存在于已保存任务时调 activate 接口立即生效（同时清空封禁、写审计）；
 * 尚未保存的链接只能先在表单内调整，保存后生效。
 */
async function promoteBackupLink(index: number) {
  const row = backupLinks.value[index]
  if (!row) return
  const taskId = Number(props.editTask?.id) || 0
  const persisted = (props.editTask?.shareurls || []).some((x) => x.url === row.url)
  if (taskId > 0 && persisted) {
    promotingIndex.value = index
    try {
      await activateShareUrlMutation.mutateAsync({ taskId, shareurl: row.url })
      applyPromoteLocally(index)
      mainLinkStatus.value = 'ok'
      mainLinkReason.value = null
      toast.success('已切换为主链接（已生效）')
    } catch (e: any) {
      toast.error(e?.message || '切换主链接失败')
    } finally {
      promotingIndex.value = null
    }
    return
  }
  applyPromoteLocally(index)
  toast.success('已设为主链接，保存后生效')
}

function openBackupPreview(row: BackupLinkRow) {
  if (!row || !row.url.trim()) return
  backupPreviewRow.value = row
  backupPreviewUrl.value = row.url
  backupPreviewVisible.value = true
}

/** 备用链接预览弹窗“使用当前文件夹”：将选中目录写回该条备用链接 */
function onPickBackupFolder(payload: { root: boolean; pdir_fid?: string; name?: string }) {
  const row = backupPreviewRow.value
  if (!row || !backupLinks.value.includes(row)) {
    backupPreviewVisible.value = false
    return
  }
  const baseUrl = row.url.trim()
  const nextUrl = payload.root
    ? stripShareurlSubdir(baseUrl)
    : (String(payload.pdir_fid || '').trim() ? getShareurl(baseUrl, { fid: String(payload.pdir_fid), name: payload.name }) : baseUrl)
  if (!nextUrl) return
  if (nextUrl !== baseUrl) {
    const duplicated = [String(state.shareurl || '').trim(), ...backupLinks.value.filter((x) => x !== row).map((x) => x.url)]
      .filter(Boolean)
      .includes(nextUrl)
    if (duplicated) {
      toast.error('该目录对应的链接已存在')
      backupPreviewVisible.value = false
      return
    }
    row.url = nextUrl
    row.status = 'unknown'
    row.reason = null
    row.last_checked_at = null
  }
  toast.success(payload.root ? '已使用分享根目录' : `已选择当前目录: ${payload.name || ''}`)
  backupPreviewVisible.value = false
}

/** 预览上下文：供只读预览复算重命名结果 */
const sharePreviewContext = computed(() => ({
  taskname: state.taskname || undefined,
  pattern: state.pattern || null,
  replace: state.replace || null,
  sort_index: state.sort_index ?? null,
  savepath: state.savepath || null,
  ignore_extension: state.ignore_extension ?? null,
  update_subdir: state.update_subdir || null,
  startfid: state.startfid || null,
  tmdb_id: state.tmdb_id ?? null,
  tmdb_media_type: state.tmdb_media_type || null,
  account_name: state.account_choice !== '__AUTO__' ? state.account_choice : null,
}))

function statusLabel(status: string): string {
  if (status === 'ok') return '可用'
  if (status === 'invalid') return '失效'
  return '未验证'
}

function statusClass(status: string): string {
  if (status === 'ok') return 'border-green-200 bg-green-50 text-green-600'
  if (status === 'invalid') return 'border-red-200 bg-red-50 text-red-500'
  return 'text-[hsl(var(--muted-foreground))]'
}

/** 验证全部链接：编辑态走后端接口落库，新建态仅前端展示 */
async function checkAllShareLinks() {
  const main = String(state.shareurl || '').trim()
  if (!main) {
    toast.error('请先填写主分享链接')
    return
  }
  backupChecking.value = true
  try {
    const urls = [main, ...backupLinks.value.map((x) => x.url).filter(Boolean)]
    const applyResults = (rows: { url: string; ok: boolean; message?: string | null }[]) => {
      const map = new Map(rows.map((x) => [String(x.url || '').trim(), x]))
      const mainRow = map.get(main)
      if (mainRow) {
        mainLinkStatus.value = mainRow.ok ? 'ok' : 'invalid'
        mainLinkReason.value = mainRow.ok ? null : (mainRow.message || null)
      }
      backupLinks.value = backupLinks.value.map((row) => {
        const hit = map.get(row.url)
        if (!hit) return row
        return { ...row, status: hit.ok ? 'ok' : 'invalid', reason: hit.ok ? null : (hit.message || null) }
      })
    }
    if (isEditing.value && props.editTask?.id) {
      // 传入表单当前列表：尚未保存的备用链接也能拿到验证结果（已保存的同时落库）
      const res = await checkShareUrlsMutation.mutateAsync({ taskId: props.editTask.id, shareurls: urls })
      applyResults((res.items || []).map((x) => ({ url: x.url, ok: x.ok, message: x.message })))
    } else {
      const res = await previewShareBatch({ shareurls: urls, account_name: state.account_choice !== '__AUTO__' ? state.account_choice : null })
      applyResults((res.items || []).map((x) => ({ url: String(x.shareurl || '').trim(), ok: Boolean(x.ok), message: x.message })))
    }
    toast.success('链接验证完成')
  } catch (e: any) {
    toast.error(e?.message || '链接验证失败')
  } finally {
    backupChecking.value = false
  }
}

function extractRunweekFromTmdbDetail(detail: any) {
  const raw: any[] = Array.isArray(detail?.episode_weekdays) && detail.episode_weekdays.length
    ? detail.episode_weekdays
    : Array.isArray(detail?.update_weekdays)
      ? detail.update_weekdays
      : []
  const normalized = raw
    .map((x) => Number(x))
    .filter((x): x is number => Number.isFinite(x) && x >= 1 && x <= 7)
  return Array.from(new Set<number>(normalized)).sort((a, b) => a - b)
}

async function applyAutoRunweekFromTmdb(tmdbId: number, mediaType: 'tv' | 'movie') {
  if (mediaType !== 'tv' || tmdbId <= 0) {
    state.runweek_mode = 'manual'
    state.runweek = []
    return
  }
  state.runweek_mode = 'auto'
  try {
    const detail = await fetchTMDBDetail('tv', tmdbId)
    state.runweek = extractRunweekFromTmdbDetail(detail)
  } catch {
    state.runweek = []
  }
}

function initAdditionDefaults() {
  const addition: Record<string, Record<string, any>> = {}
  for (const plugin of plugins.value) {
    addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}) }
  }
  state.addition = addition
}

function initAdditionFromTask(taskAddition: Record<string, any> | undefined | null) {
  const addition: Record<string, Record<string, any>> = {}
  for (const plugin of plugins.value) {
    if (taskAddition && taskAddition[plugin.plugin_key]) {
      addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}), ...taskAddition[plugin.plugin_key] }
    } else {
      addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}) }
    }
  }
  state.addition = addition
}

// Watch savepath manual edits
watch(
  () => props.open,
  (open) => {
    if (open) expandedPluginKeys.value = new Set()
  },
)

watch(() => state.savepath, (newVal) => {
  if (newVal && newVal !== savepathLastApplied.value) {
    savepathTouched.value = true
  }
})

// ===== Share URL Helpers =====
function isCloud139HashShareurl(shareurl: string) {
  return /^https?:\/\/(?:yun|caiyun)\.139\.com/i.test(String(shareurl || '').trim())
}

function getShareurl(shareurl: string, dir?: { fid?: string; name?: string }) {
  const raw = String(shareurl || '').trim()
  const fid = String(dir?.fid || '').trim()
  // 路径型 fid（如百度网盘的 '/'、'/我的资源'）无法嵌入 URL 定位，直接返回原链接，避免正则拼接把链接截断成裸域名
  if (fid.includes('/')) return raw
  if (isCloud139HashShareurl(raw)) {
    const [head, fragment = ''] = raw.split('#', 2)
    if (fragment) {
      const [fragPath, fragQuery = ''] = fragment.split('?', 2)
      const parts = fragQuery.split('&').map(x => String(x || '').trim()).filter(x => x && !x.startsWith('fid='))
      if (fid && !['0', 'root'].includes(fid)) parts.push(`fid=${encodeURIComponent(fid)}`)
      return `${head}#${parts.length ? `${fragPath}?${parts.join('&')}` : fragPath}`
    }
    let nextHead = head.replace(/([?&])fid=[^&#]*/g, '$1').replace(/[?&]+$/, '').replace('?&', '?')
    if (fid && !['0', 'root'].includes(fid)) {
      nextHead = `${nextHead}${nextHead.includes('?') ? '&' : '?'}fid=${encodeURIComponent(fid)}`
    }
    return nextHead
  }
  if (!fid || fid === '0') {
    const match = raw.match(/.*s\/[a-zA-Z0-9\-_]+(\?[^#]*)?/)
    return (match ? match[0] : raw.split('#')[0]).trim()
  }
  if (raw.includes(fid)) {
    const escapedFid = fid.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const m = raw.match(new RegExp(`.*/${escapedFid}[^/]*`))
    if (m?.[0]) return m[0]
  }
  if (raw.includes('#/list/share')) {
    return `${raw.split('#')[0]}#/list/share/${fid}`
  }
  return `${raw.split('#')[0]}#/list/share/${fid}`
}

function normalizeSavepath(value: string) {
  const s = String(value || '').trim()
  if (!s) return ''
  const normalized = `/${s}`.replace(/\/+/g, '/')
  return normalized.length > 1 ? normalized.replace(/\/+$/, '') : normalized
}

function cleanSavepathBase(savepath: string, taskname: string) {
  let p = normalizeSavepath(savepath)
  if (!p) return ''
  p = p.replace(/\/S\d{1,3}$/i, '')
  const name = String(taskname || '').trim()
  if (!name) return p
  const parts = p.split('/').filter(Boolean)
  const last = String(parts.at(-1) || '')
  if (!last) return p
  if (last === name) return normalizeSavepath(parts.slice(0, -1).join('/'))
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (new RegExp(`^${escaped}\\s*\\(\\d{4}\\)$`).test(last)) {
    return normalizeSavepath(parts.slice(0, -1).join('/'))
  }
  return p
}

function driveTypeForTask(task: TaskItem) {
  const acc = (accountsData.value || []).find(a => String(a.name) === String(task.account_name || ''))
  if (acc) return String(acc.drive_type || '').trim() || null
  const byUrl = detectDriveTypeByUrl(task.shareurl)
  return byUrl ? String(byUrl) : null
}

function currentDriveType() {
  if (state.account_choice !== '__AUTO__') {
    const acc = (accountsData.value || []).find(a => String(a.name) === state.account_choice)
    if (acc) return String(acc.drive_type || '').trim() || null
  }
  const dt = detectDriveTypeByUrl(state.shareurl)
  return dt ? String(dt) : null
}

function existingTaskCategory(task: TaskItem) {
  const savepath = normalizeSavepath(task.savepath)
  if (savepath.includes('/动漫')) return '动漫'
  if (savepath.includes('/综艺')) return '综艺'
  const mt = String(task.tmdb_media_type || '').toLowerCase()
  if (mt === 'movie') return '电影'
  if (mt === 'tv') return '电视剧'
  return ''
}

function categoryFromTmdb(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  if (mediaType === 'movie') return '电影'
  const genres = Array.isArray(detail?.genres) ? detail.genres : []
  const ids = new Set<number>()
  const names = new Set<string>()
  for (const g of genres) {
    const id = Number((g as any)?.id)
    if (Number.isFinite(id) && id > 0) ids.add(id)
    const n = String((g as any)?.name || '').trim().toLowerCase()
    if (n) names.add(n)
  }
  const hasAnime = ids.has(16) || Array.from(names).some(n => n.includes('animation') || n.includes('动画'))
  if (hasAnime) return '动漫'
  const varietyIds = new Set([10764, 10767, 10763])
  const hasVariety = Array.from(varietyIds).some(id => ids.has(id)) || Array.from(names).some(n => n.includes('reality') || n.includes('talk') || n.includes('真人秀') || n.includes('脱口秀'))
  if (hasVariety) return '综艺'
  return '电视剧'
}

function ensureCategorySegment(base: string, category: string) {
  const p = normalizeSavepath(base)
  const c = String(category || '').trim()
  if (!p || !c) return p
  const segs = p.split('/').filter(Boolean)
  if (segs.includes(c)) return p
  return normalizeSavepath(`${p}/${c}`)
}

function yearFromTmdbDetail(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  const raw = mediaType === 'movie' ? String(detail?.release_date || '') : String(detail?.first_air_date || '')
  if (raw.length >= 4 && /^\d{4}/.test(raw)) return Number(raw.slice(0, 4))
  return null
}

function appendYearSuffix(name: string, year: number | null) {
  const n = String(name || '').trim()
  if (!n) return ''
  if (!year || !Number.isFinite(year) || year < 1900 || year > 2100) return n
  if (/\(\d{4}\)\s*$/.test(n)) return n
  return `${n}(${year})`
}

async function getTmdbDetailForCurrent() {
  const id = Number(state.tmdb_id) || 0
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  if (id <= 0 || (mt !== 'movie' && mt !== 'tv')) return null
  const key = `${mt}:${id}`
  if (tmdbDetailCache.value[key]) return tmdbDetailCache.value[key]
  try {
    const detail = await fetchTMDBDetail(mt as any, id)
    // 后端返回 {media_type, data:{...}} 包裹结构，解包后供调用方直接取 name/genres 等字段
    const flat = (detail as any)?.data && typeof (detail as any).data === 'object' ? (detail as any).data : detail
    tmdbDetailCache.value[key] = flat
    return flat
  } catch {
    tmdbDetailCache.value[key] = null
    return null
  }
}

async function autoFillSavepath(runId: number) {
  // Only fill savepath for new tasks when savepath is empty or was auto-applied
  if (isEditing.value) return
  if (savepathTouched.value) return
  const currentSave = String(state.savepath || '').trim()
  if (currentSave && currentSave !== savepathLastApplied.value) return

  const dt = currentDriveType()
  if (!dt) return

  // Load tasks
  let allTasks = tasksData.value
  if (!allTasks || !allTasks.length) {
    try {
      allTasks = await fetchTasks()
    } catch {
      return
    }
  }
  if (runId !== autoLocateRunId.value) return

  const candidates = (allTasks || []).filter(t => driveTypeForTask(t) === dt && String(t.savepath || '').trim())
  if (!candidates.length) return

  // Get TMDB detail for category/year
  const detail = await getTmdbDetailForCurrent()
  if (runId !== autoLocateRunId.value) return

  const mt = String(state.tmdb_media_type || '').toLowerCase()
  const category = categoryFromTmdb(mt, detail)
  const titleFromTmdb = String(detail?.name || detail?.title || '').trim()
  const baseNameSeg = String(state.taskname || '').trim() || titleFromTmdb
  const year = yearFromTmdbDetail(mt, detail)
  const nameSeg = appendYearSuffix(baseNameSeg, year)
  if (!nameSeg) return

  const filteredByCat = candidates.filter(t => existingTaskCategory(t) === category)
  const pool = filteredByCat.length ? filteredByCat : candidates

  const counts = new Map<string, number>()
  const firstIdx = new Map<string, number>()
  for (let i = 0; i < pool.length; i++) {
    const t = pool[i]
    const base = cleanSavepathBase(t.savepath, t.taskname)
    if (!base) continue
    counts.set(base, (counts.get(base) || 0) + 1)
    if (!firstIdx.has(base)) firstIdx.set(base, i)
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1]
    return (firstIdx.get(a[0]) || 0) - (firstIdx.get(b[0]) || 0)
  })
  const baseRoot = sorted[0]?.[0] || ''
  if (!baseRoot) return

  let root = ensureCategorySegment(baseRoot, category)
  root = normalizeSavepath(root)
  const suggested = normalizeSavepath(`${root}/${nameSeg}`)

  state.savepath = suggested
  savepathLastApplied.value = suggested
}

// Auto-preview: watch shareurl changes with debounce
watch(() => state.shareurl, (newUrl, oldUrl) => {
  if (isInitializing.value) return
  if (autoPreviewTimer.value) clearTimeout(autoPreviewTimer.value)
  if (!newUrl?.trim()) {
    previewHint.value = ''
    return
  }
  if (newUrl === oldUrl) return
  if (skipNextShareurlAutoLocate.value) {
    skipNextShareurlAutoLocate.value = false
    return
  }

  autoPreviewTimer.value = setTimeout(async () => {
    autoLocateRunId.value += 1
    const runId = autoLocateRunId.value
    previewHint.value = '正在自动定位...'

    try {
      const url = newUrl.trim()

      // Step 1: Use previewShareBatch to get pdir_fid
      const batchRes = await previewShareBatch({ shareurls: [url], account_name: state.account_choice !== '__AUTO__' ? state.account_choice : null })
      if (runId !== autoLocateRunId.value) return

      const row = (batchRes.items || []).find(x => String(x.shareurl || '').trim() === url)
      if (row && row.ok) {
        const fid = String((row as any).pdir_fid || (row as any).resolved_pdir_fid || '').trim()
        // 排除根目录与路径型 fid（如百度的 '/'）：无需/无法重写链接，保持用户输入不变
        if (fid && fid !== '0' && fid !== 'root' && !fid.includes('/')) {
          // Auto deep-in: rewrite shareurl with resolved pdir_fid
          const resolved = getShareurl(url, { fid })
          if (resolved !== url) {
            state.shareurl = resolved
            // 旧版 FID 锚点随链接失效；集数锚点可跨目录保留
            if (state.startfid && !isEpisodeAnchor(state.startfid)) {
              state.startfid = ''
            }
            // The watch will re-trigger, so return here
            previewHint.value = '已自动定位到实际文件夹'
            return
          }
        }
      }

      // Step 2: Preview share to get file list
      const res = await previewShare(buildPreviewParams())
      if (runId !== autoLocateRunId.value) return

      if (res?.items?.length) {
        previewItems.value = res.items
        previewTotal.value = res.items.length

        // If there's only one directory, try auto-drilling
        const dirs = res.items.filter((i: any) => i.is_dir)
        if (dirs.length === 1 && res.items.length === 1) {
          const deepRes = await previewShare(buildPreviewParams({ pdir_fid: dirs[0].fid }))
          if (runId !== autoLocateRunId.value) return
          if (deepRes?.items?.length) {
            previewItems.value = deepRes.items
            previewTotal.value = deepRes.items.length
            // Rewrite shareurl to deep path
            const deepUrl = getShareurl(state.shareurl.trim(), { fid: dirs[0].fid })
            if (deepUrl !== state.shareurl.trim()) {
              state.shareurl = deepUrl
              previewHint.value = `已自动进入: ${dirs[0].name}`
              return
            }
          }
        }

        // Step 3: Auto-fill task name
        if (!state.taskname && res.items.length > 0) {
          // Use first item name or share name from response
          const firstDir = res.items.find((i: any) => i.is_dir)
          state.taskname = firstDir?.name || res.items[0]?.name || ''
        }

        previewHint.value = `已预览 ${previewTotal.value} 个文件`
      } else {
        previewHint.value = '链接无效或无文件'
      }

      // Step 4: Auto-fill savepath
      if (runId === autoLocateRunId.value) {
        autoFillSavepath(runId).catch(() => {})
      }
    } catch (e: any) {
      if (runId !== autoLocateRunId.value) return
      previewHint.value = '预览失败: ' + (e?.message || '网络错误')
    }
  }, 800)
})

// ===== Preview =====
function buildPreviewParams(overrides: Record<string, any> = {}) {
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : undefined
  return {
    shareurl: state.shareurl.trim(),
    account_name: accountName,
    max_items: 200,
    taskname: state.taskname || undefined,
    pattern: state.pattern || undefined,
    replace: state.replace || undefined,
    sort_index: state.sort_index ?? undefined,
    savepath: state.savepath || undefined,
    ignore_extension: state.ignore_extension ?? undefined,
    update_subdir: state.update_subdir || undefined,
    startfid: state.startfid || undefined,
    tmdb_id: state.tmdb_id ?? undefined,
    tmdb_media_type: state.tmdb_media_type || undefined,
    ...overrides,
  }
}

async function handlePreview() {
  const url = state.shareurl.trim()
  if (!url) return
  previewError.value = ''
  previewItems.value = []
  previewTotal.value = 0
  // 内容加载与目录导航统一由 SharePreviewDialog 负责
  showPreviewModal.value = true
}

/** 主链接预览首次加载完成：回填任务名与预览计数 */
function onMainPreviewLoaded(items: SharePreviewItem[]) {
  previewItems.value = items
  previewTotal.value = items.length
  if (!state.taskname && items.length > 0) {
    state.taskname = items[0].name || ''
  }
  previewHint.value = items.length ? `已预览 ${items.length} 个文件` : '链接无效或无文件'
}

/** 剥除分享链接上的子目录定位（#/list/share/xxx、fid= 参数），得到分享根链接 */
function stripShareurlSubdir(shareurl: string): string {
  const baseUrl = String(shareurl || '').trim()
  if (!baseUrl) return baseUrl
  try {
    const url = new URL(baseUrl.startsWith('http') ? baseUrl : `https://x.com/${baseUrl}`)
    url.searchParams.delete('fid')
    url.hash = ''
    return baseUrl.startsWith('http') ? url.toString() : `${url.pathname.slice(1)}${url.search}`
  } catch {
    return baseUrl.replace(/#\/list\/share\/[^?]*/g, '').replace(/([?&])fid=[^&]*&?/g, '$1').replace(/[?&]$/, '')
  }
}

/** 预览弹窗“使用当前文件夹”：根目录则剥除子目录定位，否则将 fid 写回 shareurl */
function onPickShareFolder(payload: { root: boolean; pdir_fid?: string; name?: string }) {
  if (payload.root) {
    const baseUrl = state.shareurl.trim()
    const nextShareurl = stripShareurlSubdir(baseUrl)
    if (nextShareurl !== baseUrl) {
      skipNextShareurlAutoLocate.value = true
      state.shareurl = nextShareurl
    }
    state.startfid = ''
    previewHint.value = '已使用分享根目录'
    toast.success('已选择分享根目录')
    showPreviewModal.value = false
    return
  }
  const fid = String(payload.pdir_fid || '').trim()
  if (!fid) return
  state.startfid = ''
  const baseUrl = state.shareurl.trim()
  const nextShareurl = getShareurl(baseUrl, { fid, name: payload.name })
  if (nextShareurl !== baseUrl) {
    skipNextShareurlAutoLocate.value = true
    state.shareurl = nextShareurl
  }
  previewHint.value = `已使用当前文件夹: ${payload.name || ''}`
  toast.success(`已选择当前目录: ${payload.name || ''}`)
  showPreviewModal.value = false
}

// ===== Path Browser =====
async function openPathBrowser() {
  showPathBrowser.value = true
  browsePath.value = state.savepath || '/'
  browseError.value = ''
  await loadBrowseDir(browsePath.value)
}

async function loadBrowseDir(dirPath: string) {
  browseLoading.value = true
  browseError.value = ''
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : null
  try {
    const data = await browseDrive({
      dir_path: dirPath,
      account_name: accountName,
      shareurl: state.shareurl || null,
      max_items: 200,
    })
    browsePath.value = data.dir_path || dirPath
    browseItems.value = data.items || []
  } catch (e: any) {
    browseError.value = e?.message || '浏览失败'
    browseItems.value = []
  } finally {
    browseLoading.value = false
  }
}

function enterDir(item: DriveBrowseItem) {
  const newPath = browsePath.value.endsWith('/')
    ? browsePath.value + item.name
    : browsePath.value + '/' + item.name
  loadBrowseDir(newPath)
}

function browseUp() {
  const parts = browsePath.value.replace(/\/+$/, '').split('/')
  parts.pop()
  const parent = parts.join('/') || '/'
  loadBrowseDir(parent)
}

function confirmPath() {
  state.savepath = browsePath.value
  showPathBrowser.value = false
}

function useCurrentPath(withTaskname: boolean) {
  const base = browsePath.value || '/'
  if (withTaskname && state.taskname?.trim()) {
    state.savepath = `${base}/${state.taskname.trim()}`.replace(/\/+/g, '/')
  } else {
    state.savepath = base
  }
  showPathBrowser.value = false
}

// ===== TMDB Search =====
let tmdbSearchTimer: ReturnType<typeof setTimeout> | null = null

function openTmdbSearch() {
  showTmdbSearch.value = !showTmdbSearch.value
  if (showTmdbSearch.value) {
    tmdbQuery.value = state.taskname || ''
    tmdbResults.value = []
    tmdbSearchConfigured.value = true
    if (tmdbQuery.value.trim()) {
      doTmdbSearch().catch(() => {})
    }
  }
}

// Watch tmdbQuery with debounce for auto-search
watch(tmdbQuery, (val) => {
  if (!showTmdbSearch.value) return
  if (tmdbSearchTimer) clearTimeout(tmdbSearchTimer)
  if (!val.trim()) return
  tmdbSearchTimer = setTimeout(() => doTmdbSearch(), 500)
})

async function doTmdbSearch() {
  const q = tmdbQuery.value.trim()
  if (!q) return
  tmdbSearching.value = true
  tmdbResults.value = []
  try {
    const data = await searchTMDB({ q, type: state.tmdb_media_type })
    tmdbSearchConfigured.value = Boolean(data.configured)
    tmdbResults.value = data.items || []
  } catch (e: any) {
    toast.error(e?.message || 'TMDB搜索失败')
  } finally {
    tmdbSearching.value = false
  }
}

async function selectTmdb(item: TMDBBrief) {
  state.tmdb_id = item.id || null
  state.tmdb_media_type = (item.media_type as 'tv' | 'movie') || state.tmdb_media_type
  if (!state.taskname) {
    state.taskname = item.title || item.name || ''
  }
  await applyAutoRunweekFromTmdb(Number(item.id) || 0, state.tmdb_media_type)
  showTmdbSearch.value = false
  toast.success(`已关联: ${item.title || item.name} (${item.id})`)
}

function clearTmdbSelection() {
  state.tmdb_id = null
  state.runweek_mode = 'manual'
  state.runweek = []
  tmdbResults.value = []
  showTmdbSearch.value = false
  toast.success('已清除 TMDB 关联')
}

// ===== Start episode (原 startfid) Picker =====
/** 从重命名后的文件名提取集数锚点，如 S01E92 / E92 */
function toEpisodeAnchor(name: string): string | null {
  const text = String(name || '').trim()
  if (!text) return null
  const stem = text.replace(/\.[^.]+$/, '')
  const se = stem.match(/[Ss](\d{1,2})\s*[.\-_ ]?\s*[Ee][Pp]?(\d{1,4})\b/)
  if (se) return `S${se[1].padStart(2, '0')}E${se[2].padStart(2, '0')}`
  const eOnly = stem.match(/(?:^|[^A-Za-z0-9])[Ee][Pp]?(\d{1,4})\b/)
  if (eOnly) return `E${eOnly[1]}`
  const bare = stem.match(/^(\d{1,4})$/)
  if (bare) return `E${bare[1]}`
  return null
}

function isEpisodeAnchor(value: string): boolean {
  return Boolean(toEpisodeAnchor(value))
}

function renamedNameOf(item: SharePreviewItem): string {
  return String(item.file_name_re || item.name_re || item.name || item.file_name || '').trim()
}

async function openStartfidPicker() {
  if (!state.shareurl.trim()) {
    toast.error('请先填写分享链接')
    return
  }
  showStartfidPicker.value = true
  startfidLoading.value = true
  startfidError.value = ''
  startfidItems.value = []
  try {
    // 带上 pattern/replace，以便预览重命名后的临时文件名再提取集数
    const data = await previewShare(buildPreviewParams({ max_items: 500, startfid: null }))
    const files = (data.items || []).filter((item) => !item.is_dir)
    files.sort((a, b) => {
      const na = renamedNameOf(a)
      const nb = renamedNameOf(b)
      const ka = toEpisodeAnchor(na)
      const kb = toEpisodeAnchor(nb)
      if (ka && kb) {
        const ma = ka.match(/S(\d+)E(\d+)/i)
        const mb = kb.match(/S(\d+)E(\d+)/i)
        if (ma && mb) {
          const sa = Number(ma[1]) * 10000 + Number(ma[2])
          const sb = Number(mb[1]) * 10000 + Number(mb[2])
          if (sa !== sb) return sa - sb
        }
        const ea = Number((ka.match(/(\d+)$/) || [])[1] || 0)
        const eb = Number((kb.match(/(\d+)$/) || [])[1] || 0)
        if (ea !== eb) return ea - eb
      }
      return na.localeCompare(nb, 'zh')
    })
    startfidItems.value = files
  } catch (e: any) {
    startfidError.value = e?.message || '获取文件列表失败'
  } finally {
    startfidLoading.value = false
  }
}

function selectStartfid(item: SharePreviewItem) {
  const renamed = renamedNameOf(item)
  const anchor = toEpisodeAnchor(renamed)
  if (!anchor) {
    toast.error('无法从该文件的重命名结果识别集数，请检查匹配/替换规则后重试')
    return
  }
  state.startfid = anchor
  showStartfidPicker.value = false
  toast.success(`已选择起始集数: ${anchor}（${renamed}）`)
}

// ===== Weekday =====
function toggleWeekday(day: number) {
  const idx = state.runweek.indexOf(day)
  if (idx === -1) {
    state.runweek.push(day)
    state.runweek.sort((a, b) => a - b)
  } else {
    state.runweek.splice(idx, 1)
  }
}

// ===== Sync Task Reorder (Drag & Arrow) =====
const syncDragIndex = ref<number | null>(null)

function moveSyncTask(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= state.sync_task_uids.length) return
  const arr = [...state.sync_task_uids]
  const [item] = arr.splice(index, 1)
  arr.splice(target, 0, item)
  state.sync_task_uids = arr
}

function onSyncDragStart(index: number, event: DragEvent) {
  syncDragIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
}

function onSyncDragOver(_index: number, event: DragEvent) {
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
}

function onSyncDrop(targetIndex: number) {
  const fromIndex = syncDragIndex.value
  if (fromIndex === null || fromIndex === targetIndex) return
  const arr = [...state.sync_task_uids]
  const [item] = arr.splice(fromIndex, 1)
  arr.splice(targetIndex, 0, item)
  state.sync_task_uids = arr
  syncDragIndex.value = null
}

function onSyncDragEnd() {
  syncDragIndex.value = null
}

// ===== Build Payload =====
function buildPayload() {
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : null
  const extra: Record<string, any> = {
    runweek_mode: state.runweek_mode,
    runweek: state.runweek_mode === 'auto' ? [] : [...state.runweek],
    update_subdir_resave_mode: state.update_subdir_resave_mode,
    auto_update_115_shareurl: Boolean(state.auto_update_115_shareurl),
  }
  return {
    task_type: 'drama',
    taskname: state.taskname.trim() || '未命名任务',
    shareurl: state.shareurl.trim(),
    shareurls: [state.shareurl.trim(), ...backupLinks.value.map((x) => x.url)].filter(Boolean),
    savepath: state.savepath.trim(),
    sync_task_uids: [...state.sync_task_uids],
    pattern: state.pattern.trim() || null,
    replace: state.replace.trim() || null,
    enddate: state.enddate.trim() || null,
    ignore_extension: state.ignore_extension,
    sort_index: state.sort_index,
    startfid: state.startfid.trim() || null,
    account_name: accountName,
    update_subdir: state.update_subdir.trim() || null,
    tmdb_id: state.tmdb_id,
    tmdb_media_type: state.tmdb_id ? state.tmdb_media_type : null,
    enabled: state.enabled,
    addition: state.addition,
    extra,
  }
}

// ===== Submit =====
async function handleSubmit() {
  if (!state.shareurl.trim()) {
    toast.error('请填写分享链接')
    return
  }
  if (!state.savepath.trim()) {
    toast.error('请填写保存路径')
    return
  }

  const payload = buildPayload()
  submitting.value = true
  try {
    if (isEditing.value && props.editTask) {
      await updateMutation.mutateAsync({ taskId: props.editTask.id, payload })
    } else {
      await createMutation.mutateAsync(payload)
    }
    toast.success('保存成功')
    resetAndClose()
  } catch (e: any) {
    toast.error(e?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

// ===== Run Once =====
function handleRunOnce() {
  if (!state.shareurl.trim()) {
    toast.error('请填写分享链接')
    return
  }
  if (!state.savepath.trim()) {
    toast.error('请填写保存路径')
    return
  }
  const payload: Record<string, any> = buildPayload()
  payload.extra = {
    ...(payload.extra || {}),
    allow_once: true,
    runweek: [],
  }
  // 编辑已存在任务时带上 task_uid，后端据此关联真实任务：
  // 失败时才能写入 shareurl_ban 并触发自动修复，成功时才能触发115自动换链
  const editingUid = String(props.editTask?.task_uid || '').trim()
  if (editingUid) payload.task_uid = editingUid
  emit('run-once', payload)
}

function resetAndClose() {
  resetForm()
  previewItems.value = []
  previewError.value = ''
  emit('close')
}

// ===== Resource Search Dialog =====
// 已指定账号 → 该账号网盘类型；自动+已填分享链接 → 链接推断类型；均无则不限定单一类型
const resourceSearchDriveType = computed(() => {
  if (state.account_choice !== '__AUTO__') {
    const acc = (accountsData.value || []).find(a => String(a.name) === state.account_choice)
    const dt = String(acc?.drive_type || '').trim()
    if (dt) return dt
  }
  const byUrl = detectDriveTypeByUrl(state.shareurl)
  return byUrl ? String(byUrl) : null
})

// 新增任务且未确定类型时，按已有可用账号类型限定搜索范围
const resourceSearchDriveTypes = computed(() => {
  const out: string[] = []
  for (const a of accountsData.value || []) {
    if (a.enabled === false) continue
    const status = String((a as any).runtime_status || '').trim()
    if (status && status !== 'active') continue
    const dt = String(a.drive_type || '').trim()
    if (dt && !out.includes(dt)) out.push(dt)
  }
  return out
})

function openResourceSearch() {
  if (resourceSearchOpening.value) return
  resourceSearchOrigin.value = 'main'
  resourceSearchOpening.value = true
  ;(async () => {
    let q = String(state.taskname || '').trim()
    // 已关联 TMDB 时优先用 TMDB 标题作为搜索词（任务名可能带季/画质等噪声）
    if (Number(state.tmdb_id) > 0) {
      const detail = await getTmdbDetailForCurrent()
      const title = String(detail?.name || detail?.title || '').trim()
      if (title) q = title
    }
    resourceSearchQuery.value = q
    showResourceSearch.value = true
  })().finally(() => {
    resourceSearchOpening.value = false
  })
}

function onResourceSelected(item: TaskSuggestionItem) {
  state.shareurl = item.shareurl // 填充分享链接，会触发自动定位
  if (!state.taskname?.trim() && item.taskname) state.taskname = item.taskname
}

/** 多选搜索动作：替换主链接 / 追加备用 / 替换指定备用链接 */
function onResourceAction(key: string, items: TaskSuggestionItem[]) {
  const urls = items.map((x) => String(x.shareurl || '').trim()).filter(Boolean)
  if (!urls.length) return
  if (key === 'replace_main') {
    const first = items[0]
    const url = urls[0]
    // 旧主链接降为备用（同盘时），避免直接丢弃已配置链接
    const oldMain = String(state.shareurl || '').trim()
    state.shareurl = url
    // 旧版 FID 锚点换链失效；集数锚点可保留
    if (state.startfid && !isEpisodeAnchor(state.startfid)) {
      state.startfid = ''
    }
    mainLinkStatus.value = 'unknown'
    mainLinkReason.value = null
    if (oldMain && oldMain !== url && detectDriveTypeByUrl(oldMain) === detectDriveTypeByUrl(url)) {
      const kept = backupLinks.value.filter((x) => x.url !== oldMain && x.url !== url)
      // 旧主链接降为备用时也遵守上限，超限则丢弃最后一条
      backupLinks.value = [
        { url: oldMain, status: 'unknown', reason: null, last_checked_at: null },
        ...kept,
      ].slice(0, MAX_BACKUP_LINKS)
    } else {
      backupLinks.value = backupLinks.value.filter((x) => x.url !== url && isSameDriveAsMain(x.url))
    }
    if (!state.taskname?.trim() && first?.taskname) state.taskname = first.taskname
    toast.success('已替换主链接')
    return
  }
  if (key === 'append_backup') {
    if (!state.shareurl.trim()) {
      // 无主链接时首条作为主链接，其余作备用
      state.shareurl = urls[0]
      mainLinkStatus.value = 'unknown'
      mainLinkReason.value = null
      appendBackupLinks(urls.slice(1))
      return
    }
    appendBackupLinks(urls)
    return
  }
  if (key === 'replace_one') {
    const origin = resourceSearchOrigin.value
    const index = origin.startsWith('replace:') ? Number(origin.split(':')[1]) : -1
    const url = urls[0]
    if (index < 0 || index >= backupLinks.value.length) return
    if (!isSameDriveAsMain(url)) {
      toast.error('备用链接必须与主链接同网盘类型')
      return
    }
    const used = usedLinkSet()
    used.delete(backupLinks.value[index].url)
    if (used.has(url)) {
      toast.error('该链接已存在')
      return
    }
    backupLinks.value[index] = { url, status: 'unknown', reason: null, last_checked_at: null }
    locateBackupLink(backupLinks.value[index]).catch(() => {})
    toast.success('已替换备用链接')
  }
}

/** 备用区“搜索添加”/行“换链”入口 */
function openResourceSearchForBackup(origin: 'backup' | `replace:${number}`) {
  if (!state.shareurl.trim()) {
    toast.error('请先填写主分享链接')
    return
  }
  resourceSearchOrigin.value = origin
  resourceSearchQuery.value = String(state.taskname || '').trim()
  showResourceSearch.value = true
}

// ===== Helpers =====
function getTmdbTitle(item: TMDBBrief): string {
  return item.title || item.name || item.original_title || item.original_name || ''
}
function getTmdbYear(item: TMDBBrief): string {
  const d = item.release_date || item.first_air_date
  return d ? d.slice(0, 4) : ''
}
function getTmdbPoster(item: TMDBBrief): string {
  return item.poster_path ? `https://image.tmdb.org/t/p/w92${item.poster_path}` : ''
}
</script>

<template>
  <!-- ===== 主链接预览（可选目录）：复用通用预览组件 ===== -->
  <SharePreviewDialog
    v-model:visible="showPreviewModal"
    :shareurl="state.shareurl"
    :readonly="false"
    :preview-context="sharePreviewContext"
    @loaded="onMainPreviewLoaded"
    @pick-folder="onPickShareFolder"
  />

  <!-- ===== StartFID Picker Modal ===== -->
  <Teleport to="body">
    <div v-if="showStartfidPicker" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/60" @click="showStartfidPicker = false" />
      <div class="modal-surface relative z-10 flex max-h-[70vh] w-[560px] flex-col overflow-hidden">
        <div class="modal-bar flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">选择起始集数</h3>
          <button class="icon-action" @click="showStartfidPicker = false">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>
        <div class="px-5 py-2 border-b border-[hsl(var(--border))]">
          <p class="text-xs text-[hsl(var(--muted-foreground))]">
            按匹配/替换规则生成临时文件名后提取集数（如 S01E92）。将转存该集及之后（集数 ≥ 起始值）的文件；换链后无需重设。
          </p>
        </div>
        <!-- Table Header -->
        <div class="grid grid-cols-[1fr_90px_70px] gap-2 px-5 py-2 border-b border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]">
          <span>原名 → 重命名</span><span>集数</span><span>大小</span>
        </div>
        <div class="flex-1 overflow-y-auto px-5 py-3">
          <div v-if="startfidLoading" class="flex items-center justify-center py-8">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="startfidError" class="text-xs text-red-500 py-4 text-center">{{ startfidError }}</div>
          <div v-else-if="startfidItems.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-4 text-center">无文件可选</div>
          <div v-else class="space-y-0.5">
            <div
              v-for="item in startfidItems"
              :key="item.fid"
              class="grid grid-cols-[1fr_90px_70px] gap-2 items-center px-3 py-2 rounded cursor-pointer hover:bg-[hsl(var(--accent))] text-sm"
              :class="state.startfid === toEpisodeAnchor(renamedNameOf(item)) ? 'bg-[hsl(var(--accent))] ring-1 ring-[hsl(var(--primary))]' : ''"
              @click="selectStartfid(item)"
            >
              <div class="min-w-0">
                <div class="truncate text-[hsl(var(--foreground))]">{{ item.name }}</div>
                <div v-if="renamedNameOf(item) && renamedNameOf(item) !== item.name" class="truncate text-xs text-green-600">
                  → {{ renamedNameOf(item) }}
                </div>
              </div>
              <span class="text-xs font-medium text-[hsl(var(--foreground))]">{{ toEpisodeAnchor(renamedNameOf(item)) || '-' }}</span>
              <span class="text-[hsl(var(--muted-foreground))] text-xs">{{ item.size ? formatSize(item.size) : '-' }}</span>
            </div>
          </div>
        </div>
        <div class="modal-bar flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-3">
          <Button v-if="state.startfid" size="sm" variant="outline" class="rounded-full" @click="state.startfid = ''; showStartfidPicker = false">
            清除选择
          </Button>
          <div v-else />
          <Button size="sm" variant="outline" class="rounded-full" @click="showStartfidPicker = false">
            关闭
          </Button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Path Browser Modal ===== -->
  <Teleport to="body">
    <div v-if="showPathBrowser" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="showPathBrowser = false" />
      <div class="modal-surface relative z-10 flex max-h-[80vh] w-[600px] flex-col overflow-hidden">
        <div class="modal-bar flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">浏览保存路径</h3>
          <button class="icon-action" @click="showPathBrowser = false">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>
        <div class="px-5 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between">
          <span class="text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[360px]">当前: {{ browsePath }}</span>
          <button class="text-xs text-[hsl(var(--primary))] hover:underline flex items-center gap-1 shrink-0" @click="browseUp">
            <ArrowUp class="h-3 w-3" /> 返回上级
          </button>
        </div>
        <div class="flex-1 overflow-y-auto px-5 py-3">
          <div v-if="browseLoading" class="flex items-center justify-center py-8">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="browseError" class="text-xs text-red-500 py-4 text-center">{{ browseError }}</div>
          <div v-else-if="browseItems.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-4 text-center">无文件或目录</div>
          <div v-else class="space-y-0.5">
            <div
              v-for="item in browseItems"
              :key="item.fid"
              class="flex items-center gap-2 px-2 py-2 rounded text-sm"
              :class="item.is_dir ? 'cursor-pointer hover:bg-[hsl(var(--accent))]' : 'opacity-80'"
              @click="item.is_dir && enterDir(item)"
            >
              <component
                :is="item.is_dir ? Folder : FileText"
                class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0"
              />
              <span class="truncate text-[hsl(var(--foreground))] flex-1 min-w-0">{{ item.file_name || item.name }}</span>
              <span class="shrink-0 text-[10px] text-[hsl(var(--muted-foreground))]">
                {{ item.is_dir ? `${item.include_items || 0}项` : formatSize(item.size || 0) || '-' }}
              </span>
            </div>
          </div>
        </div>
        <div class="modal-bar flex gap-2 border-t border-[hsl(var(--border))] px-5 py-3">
          <Button size="sm" class="rounded-full" @click="useCurrentPath(false)">使用当前文件夹</Button>
          <Button v-if="state.taskname?.trim()" size="sm" variant="outline" class="rounded-full" @click="useCurrentPath(true)">
            当前文件夹/{{ state.taskname.trim() }}
          </Button>
          <div class="flex-1" />
          <Button size="sm" class="rounded-full" @click="confirmPath">确认选择此路径</Button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Main Modal ===== -->
  <Teleport to="body">
    <Transition name="task-modal">
      <div v-if="props.open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/50 transition-opacity" @click="resetAndClose" />
        <!-- Panel -->
        <div class="relative z-10 flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="modal-bar flex items-start justify-between gap-4 border-b border-[hsl(var(--border))] px-5 py-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="text-lg font-semibold tracking-tight text-[hsl(var(--foreground))]">{{ title }}</h2>
                <span
                  class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                  :class="state.enabled ? 'bg-emerald-500/15 text-emerald-600' : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'"
                >{{ state.enabled ? '已启用' : '已停用' }}</span>
              </div>
              <p class="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">左右并联配置；高级选项在下方平铺展开。</p>
            </div>
            <button class="icon-action shrink-0" @click="resetAndClose">
              <X class="h-5 w-5" />
            </button>
          </div>

          <!-- Scrollable Form：并联布局，压缩纵向滚动 -->
          <div class="flex-1 space-y-3 overflow-y-auto bg-[hsl(var(--muted))]/15 px-5 py-3">
            <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <!-- ===== 基础信息 ===== -->
            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="section-heading">
                基础信息
              </h3>
              
              <!-- 任务名称 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">任务名称</label>
                <div class="relative">
                  <Input v-model="state.taskname" placeholder="可选，默认从预览自动提取" class="pr-24" />
                  <Button
                    size="sm" variant="ghost"
                    class="absolute right-1 top-1/2 -translate-y-1/2 h-7 text-xs"
                    :disabled="resourceSearchOpening"
                    @click="openResourceSearch">
                    <Loader2 v-if="resourceSearchOpening" class="h-3 w-3 mr-1 animate-spin" />
                    <Search v-else class="h-3 w-3 mr-1" />
                    搜索资源
                  </Button>
                </div>
              </div>

              <!-- 分享链接 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">
                  分享链接 <span class="text-red-500">*</span>
                  <span v-if="state.shareurl.trim() && mainLinkStatus !== 'unknown'" class="ml-1.5 rounded-full border px-1.5 py-0.5 text-[10px] font-normal" :class="statusClass(mainLinkStatus)" :title="mainLinkReason || ''">
                    {{ statusLabel(mainLinkStatus) }}
                  </span>
                </label>
                <div class="flex gap-2">
                  <Input v-model="state.shareurl" placeholder="粘贴分享链接..." class="flex-1" />
                  <Button variant="outline" size="sm" :disabled="!state.shareurl.trim() || previewing" @click="handlePreview">
                    <Loader2 v-if="previewing" class="h-4 w-4 animate-spin" />
                    <Eye v-else class="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <!-- 备用分享链接：主链接失效时自动切换（默认展开） -->
              <div class="rounded-md border border-[hsl(var(--border))] px-3 py-2">
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-1 text-sm font-medium text-[hsl(var(--foreground))]">
                    多源链接
                    <span v-if="backupLinks.length" class="rounded-full border border-[hsl(var(--primary))] px-1.5 text-[10px] text-[hsl(var(--primary))]">{{ backupLinks.length }}/{{ MAX_BACKUP_LINKS }}</span>
                  </div>
                  <div class="flex items-center gap-1">
                    <Button size="sm" variant="ghost" class="h-7 text-xs" :disabled="!state.shareurl.trim() || backupChecking" @click="checkAllShareLinks">
                      <Loader2 v-if="backupChecking" class="mr-1 h-3 w-3 animate-spin" />
                      验证全部
                    </Button>
                    <Button size="sm" variant="ghost" class="h-7 text-xs" :disabled="!state.shareurl.trim() || backupLinks.length >= MAX_BACKUP_LINKS" @click="openResourceSearchForBackup('backup')">
                      <Search class="mr-1 h-3 w-3" /> 搜索添加
                    </Button>
                  </div>
                </div>
                <div class="mt-2 space-y-2">
                  <p class="text-xs text-[hsl(var(--muted-foreground))]">顺序 = 转存优先级；已标失效的链接不再请求。</p>
                  <div v-if="!backupLinks.length" class="py-1 text-xs text-[hsl(var(--muted-foreground))]">暂无其它源链接</div>
                  <div
                    v-for="(row, idx) in backupLinks"
                    :key="idx"
                    class="flex items-center gap-1.5 rounded border border-[hsl(var(--border))] px-2 py-1.5"
                  >
                    <span class="w-4 shrink-0 text-center text-[10px] text-[hsl(var(--muted-foreground))]" :title="`转存优先级 ${idx + 2}（主链接为 1）`">{{ idx + 2 }}</span>
                    <Input
                      v-model="row.url"
                      class="h-7 min-w-0 flex-1 text-xs"
                      placeholder="分享链接"
                      :title="row.url"
                      @focus="backupEditSnapshot = row.url"
                      @change="onBackupUrlEdited(idx, backupEditSnapshot)"
                      @keydown.enter.prevent="onBackupUrlEdited(idx, backupEditSnapshot)"
                    />
                    <span v-if="row.locating" class="inline-flex shrink-0 items-center gap-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">
                      <Loader2 class="h-3 w-3 animate-spin" /> 定位中
                    </span>
                    <span v-else class="shrink-0 rounded-full border px-1.5 text-[10px]" :class="statusClass(row.status)" :title="row.reason || ''">{{ statusLabel(row.status) }}</span>
                    <button class="icon-action h-6 w-6 shrink-0" title="上移（提高转存优先级）" :disabled="idx === 0" @click="moveBackupLink(idx, -1)">
                      <ArrowUp class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" title="下移（降低转存优先级）" :disabled="idx === backupLinks.length - 1" @click="moveBackupLink(idx, 1)">
                      <ArrowDown class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" title="自动定位文件夹" :disabled="row.locating" @click="locateBackupLink(row)">
                      <Folder class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" title="预览内容（可选目录）" @click="openBackupPreview(row)">
                      <Eye class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" title="搜索换链" @click="openResourceSearchForBackup(`replace:${idx}`)">
                      <Search class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" :title="isEditing ? '设为主链接（优先级提到第 1；已保存的链接立即生效）' : '设为主链接（优先级提到第 1）'" :disabled="promotingIndex === idx" @click="promoteBackupLink(idx)">
                      <Loader2 v-if="promotingIndex === idx" class="h-3 w-3 animate-spin" />
                      <Check v-else class="h-3 w-3" />
                    </button>
                    <button class="icon-action h-6 w-6 shrink-0" title="删除" @click="removeBackupLink(idx)">
                      <X class="h-3 w-3" />
                    </button>
                  </div>
                  <div class="flex gap-2">
                    <Input v-model="backupInput" placeholder="手动粘贴分享链接..." class="flex-1 text-xs" :disabled="backupLinks.length >= MAX_BACKUP_LINKS" @keydown.enter.prevent="addBackupFromInput" />
                    <Button size="sm" variant="outline" :disabled="!backupInput.trim() || backupLinks.length >= MAX_BACKUP_LINKS" @click="addBackupFromInput">添加</Button>
                  </div>
                </div>
              </div>

              <!-- 预览错误 -->
              <div v-if="previewError" class="rounded-md bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-400">
                {{ previewError }}
              </div>
              <!-- 预览提示（自动预览 / 手动预览） -->
              <div v-if="previewHint || previewItems.length > 0" class="flex items-center gap-2">
                <p class="text-xs text-[hsl(var(--muted-foreground))]">
                  {{ previewHint || `已预览 ${previewTotal} 个文件` }}
                </p>
                <button class="text-xs text-[hsl(var(--primary))] hover:underline" @click="showPreviewModal = true">
                  查看详情
                </button>
              </div>

              <!-- 账号选择 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">账号选择</label>
                <select
                  v-model="state.account_choice"
                  class="field-input"
                >
                  <option value="__AUTO__">自动选择</option>
                  <option v-for="acc in activeAccounts" :key="acc.name" :value="acc.name">
                    {{ acc.name }}（{{ acc.drive_type }}）
                  </option>
                </select>
              </div>

              <!-- 保存路径 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">
                  保存路径 <span class="text-red-500">*</span>
                </label>
                <div class="flex gap-2">
                  <Input v-model="state.savepath" placeholder="网盘保存路径，如 /我的追剧/海贼王" class="flex-1" />
                  <Button variant="outline" size="sm" @click="openPathBrowser">
                    <FolderOpen class="h-4 w-4 mr-1" />
                    浏览
                  </Button>
                </div>
              </div>
              <!-- 115自动换链（仅115驱动时显示） -->
              <label v-if="currentDriveType() === '115'" class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                <input v-model="state.auto_update_115_shareurl" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                115自动换链
              </label>
            </section>

            <!-- ===== 右列：TMDB + 重命名 ===== -->
            <div class="space-y-3">
            <!-- ===== TMDB 关联 ===== -->
            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="section-heading">
                TMDB 关联（可选）
              </h3>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="field-label">TMDB ID</label>
                  <div class="flex gap-1.5">
                    <Input
                      :model-value="state.tmdb_id ?? ''"
                      type="number"
                      placeholder="如 12345"
                      class="flex-1"
                      @update:model-value="state.tmdb_id = $event ? Number($event) : null"
                    />
                    <Button variant="outline" size="sm" @click="openTmdbSearch">
                      <Search class="h-4 w-4" />
                    </Button>
                    <Button v-if="state.tmdb_id" variant="outline" size="sm" @click="clearTmdbSelection">
                      清除
                    </Button>
                  </div>
                </div>
                <div>
                  <label class="field-label">类型</label>
                  <select
                    v-model="state.tmdb_media_type"
                    class="field-input"
                  >
                    <option value="tv">剧集 (TV)</option>
                    <option value="movie">电影 (Movie)</option>
                  </select>
                </div>
              </div>

              <!-- TMDB 搜索面板 -->
              <div v-if="showTmdbSearch" class="rounded-md border border-[hsl(var(--border))] p-3 space-y-2">
                <div v-if="props.presetTmdb?.tmdb_search_reason" class="rounded-md bg-[hsl(var(--muted))] px-2.5 py-2 text-xs text-[hsl(var(--muted-foreground))]">
                  <span v-if="props.presetTmdb.tmdb_search_reason === 'ambiguous'">自动识别到多个可能结果，请手动确认正确的 TMDB 条目。</span>
                  <span v-else-if="props.presetTmdb.tmdb_search_reason === 'no-match'">未自动识别到 TMDB 条目，请手动搜索并关联。</span>
                  <span v-else>当前未配置 TMDB API Key，暂时无法自动搜索关联。</span>
                </div>
                <Input
                  v-model="tmdbQuery"
                  placeholder="输入影视名称搜索TMDB..."
                  class="h-8 text-xs"
                  @keydown.enter="doTmdbSearch"
                />
                <div v-if="!tmdbSearchConfigured" class="text-xs text-amber-600 py-1 text-center">
                  未配置 TMDB API Key，无法返回搜索结果
                </div>
                <div v-if="tmdbSearching" class="flex items-center justify-center py-3">
                  <Loader2 class="h-4 w-4 animate-spin text-[hsl(var(--muted-foreground))]" />
                </div>
                <div v-else-if="tmdbResults.length === 0 && !tmdbQuery.trim()" class="text-xs text-[hsl(var(--muted-foreground))] py-2 text-center">
                  输入影视名称后可搜索并手动关联
                </div>
                <div v-else-if="tmdbResults.length === 0 && tmdbQuery.trim() && tmdbSearchConfigured" class="text-xs text-[hsl(var(--muted-foreground))] py-2 text-center">
                  未找到匹配的 TMDB 结果
                </div>
                <div v-else class="max-h-48 overflow-y-auto space-y-1">
                  <div
                    v-for="item in tmdbResults"
                    :key="item.id ?? item.name ?? ''"
                    class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-[hsl(var(--accent))]"
                    @click="selectTmdb(item)"
                  >
                    <img
                      v-if="getTmdbPoster(item)"
                      :src="getTmdbPoster(item)"
                      class="h-10 w-7 rounded object-cover shrink-0"
                      alt=""
                    />
                    <div v-else class="h-10 w-7 rounded bg-[hsl(var(--muted))] flex items-center justify-center shrink-0">
                      <Search class="h-3 w-3 text-[hsl(var(--muted-foreground))]" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <p class="text-xs font-medium text-[hsl(var(--foreground))] truncate">{{ getTmdbTitle(item) }}</p>
                      <p class="text-[10px] text-[hsl(var(--muted-foreground))]">
                        {{ getTmdbYear(item) }} · {{ item.media_type === 'movie' ? '电影' : '剧集' }} · ID: {{ item.id }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- ===== 重命名规则 ===== -->
            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="flex items-center justify-between section-heading">
                <span>重命名规则（可选）</span>
                <a
                  href="/docs#regex"
                  target="_blank"
                  rel="noopener noreferrer"
                  title="查看正则使用说明（新页面打开）"
                  class="inline-flex items-center gap-1 text-xs font-normal text-[hsl(var(--primary))] hover:underline"
                >
                  <BookOpen class="h-3.5 w-3.5" />
                  使用说明
                </a>
              </h3>
              <div>
                <label class="field-label">内置规则</label>
                <select
                  :value="selectedRuleIdx"
                  class="field-input"
                  @change="applyBuiltinRule"
                >
                  <option v-for="(rule, idx) in builtinRules" :key="idx" :value="idx">
                    {{ rule.label }}
                  </option>
                </select>
              </div>
              <div>
                <label class="field-label">匹配正则 (pattern)</label>
                <Input v-model="state.pattern" placeholder="如 .*\.(mp4|mkv)$，或内置规则 key 如 $TV_REGEX" />
              </div>
              <div>
                <label class="field-label">替换字符串 (replace)</label>
                <Input v-model="state.replace" placeholder="如 {TASKNAME}.{SXX}E{E}.{EXT}，留空则仅筛选不改名" />
              </div>
              <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                <input v-model="state.ignore_extension" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                忽略扩展名
              </label>
            </section>
            </div>
            </div>

            <!-- ===== 下部并联：插件 + 调度（插件字段默认折叠） ===== -->
            <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <section v-if="plugins.length > 0" class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="section-heading">
                插件选项
              </h3>
              <div class="space-y-3">
                <div
                  v-for="plugin in plugins"
                  :key="plugin.plugin_key"
                  class="space-y-2 rounded-[0.6rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3"
                >
                  <div class="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      class="inline-flex items-center gap-1 text-sm font-medium text-[hsl(var(--foreground))] hover:opacity-80"
                      @click="togglePluginExpanded(plugin.plugin_key)"
                    >
                      <ChevronDown v-if="isPluginExpanded(plugin.plugin_key)" class="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                      <ChevronRight v-else class="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                      {{ plugin.plugin_key }}
                    </button>
                    <label class="inline-flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]" @click.stop>
                      启用
                      <input
                        type="checkbox"
                        :checked="isPluginEnabled(plugin.plugin_key)"
                        class="h-4 w-4 rounded border-[hsl(var(--border))]"
                        @change="togglePluginEnabled(plugin.plugin_key, $event)"
                      />
                    </label>
                  </div>
                  <div v-if="isPluginExpanded(plugin.plugin_key)" class="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <div
                      v-for="field in plugin.task_config_fields"
                      :key="field.key"
                      class="space-y-0.5"
                      :class="{ 'opacity-50 pointer-events-none': !isPluginEnabled(plugin.plugin_key) }"
                    >
                      <label class="field-label field-label--inline">{{ field.description || field.label || field.key }}</label>
                      <div v-if="field.input_type === 'switch'" class="flex items-center">
                        <input
                          type="checkbox"
                          :checked="state.addition[plugin.plugin_key]?.[field.key]"
                          class="h-4 w-4 rounded border-[hsl(var(--border))]"
                          @change="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: ($event.target as HTMLInputElement).checked }"
                        />
                      </div>
                      <Input
                        v-else-if="field.input_type === 'number'"
                        type="number"
                        :model-value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        class="h-8 text-sm"
                        @update:model-value="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: $event ? Number($event) : null }"
                      />
                      <textarea
                        v-else-if="field.input_type === 'textarea'"
                        :value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        rows="2"
                        class="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1 text-sm"
                        @input="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: ($event.target as HTMLTextAreaElement).value }"
                      />
                      <Input
                        v-else
                        :type="field.input_type === 'password' ? 'password' : 'text'"
                        :model-value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        class="h-8 text-sm"
                        @update:model-value="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: $event }"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="section-heading">
                调度配置（可选）
              </h3>
              <div>
                <label class="field-label">更新日模式</label>
                <select
                  v-model="state.runweek_mode"
                  class="field-input"
                >
                  <option value="auto">自动（TMDB）</option>
                  <option value="manual">手动</option>
                </select>
              </div>
              <div v-if="state.runweek_mode === 'manual'">
                <label class="field-label">更新日（周几）</label>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="day in weekdays"
                    :key="day.value"
                    type="button"
                    class="h-8 w-8 rounded-full text-xs font-medium border transition-colors"
                    :class="state.runweek.includes(day.value)
                      ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-[hsl(var(--primary))]'
                      : 'bg-[hsl(var(--background))] text-[hsl(var(--foreground))] border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]'"
                    @click="toggleWeekday(day.value)"
                  >
                    {{ day.label }}
                  </button>
                </div>
              </div>
              <div>
                <label class="field-label">截止日期</label>
                <Input v-model="state.enddate" type="date" />
              </div>
            </section>
            </div>

            <!-- ===== 高级选项（下部平铺展开） ===== -->
            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
              <h3 class="section-heading">高级选项</h3>
              <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer md:col-span-2">
                  <input v-model="state.enabled" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                  启用任务
                </label>

                <div class="md:col-span-2">
                  <label class="field-label">关联同步任务</label>
                  <div
                    v-if="syncTasks.length === 0"
                    class="rounded-[0.6rem] border border-dashed border-[hsl(var(--border))] px-3 py-3 text-center text-xs text-[hsl(var(--muted-foreground))]"
                  >
                    暂无同步任务
                  </div>
                  <div v-else class="space-y-2">
                    <div class="max-h-28 overflow-y-auto rounded-[0.6rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
                      <label
                        v-for="st in syncTasks"
                        :key="st.uid"
                        class="sync-option"
                        :class="{ 'sync-option--on': state.sync_task_uids.includes(st.uid) }"
                      >
                        <input
                          type="checkbox"
                          class="sr-only"
                          :checked="state.sync_task_uids.includes(st.uid)"
                          @change="
                            state.sync_task_uids.includes(st.uid)
                              ? state.sync_task_uids = state.sync_task_uids.filter(u => u !== st.uid)
                              : state.sync_task_uids = [...state.sync_task_uids, st.uid]
                          "
                        />
                        <span class="sync-option__box"><Check class="h-3 w-3" /></span>
                        <span class="sync-option__name">{{ st.name }}</span>
                      </label>
                    </div>
                    <div
                      v-if="state.sync_task_uids.length > 0"
                      class="rounded-[0.6rem] border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-2"
                    >
                      <div class="mb-1 flex items-center justify-between gap-2 px-0.5">
                        <span class="text-[11px] font-medium text-[hsl(var(--foreground))]/75">
                          执行顺序 · {{ state.sync_task_uids.length }} 项
                        </span>
                        <span class="text-[11px] text-[hsl(var(--muted-foreground))]">拖拽或用箭头调整</span>
                      </div>
                      <div class="space-y-1">
                        <div
                          v-for="(uid, index) in state.sync_task_uids"
                          :key="uid"
                          class="sync-order"
                          :class="{ 'sync-order--dragging': syncDragIndex === index }"
                          draggable="true"
                          @dragstart="onSyncDragStart(index, $event)"
                          @dragover.prevent="onSyncDragOver(index, $event)"
                          @drop="onSyncDrop(index)"
                          @dragend="onSyncDragEnd"
                        >
                          <GripVertical class="sync-order__grip" />
                          <span class="sync-order__index">{{ index + 1 }}</span>
                          <span class="sync-order__name">{{ syncTasks.find(s => s.uid === uid)?.name || uid }}</span>
                          <button type="button" class="icon-action h-6 w-6" title="上移" :disabled="index === 0" @click="moveSyncTask(index, -1)">
                            <ArrowUp class="h-3 w-3" />
                          </button>
                          <button type="button" class="icon-action h-6 w-6" title="下移" :disabled="index === state.sync_task_uids.length - 1" @click="moveSyncTask(index, 1)">
                            <ArrowDown class="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <label class="field-label">排序索引 (sort_index)</label>
                  <Input
                    :model-value="state.sort_index ?? ''"
                    type="number"
                    placeholder="排序优先级"
                    @update:model-value="state.sort_index = $event ? Number($event) : null"
                  />
                </div>

                <div>
                  <label class="field-label">起始集数 (startfid)</label>
                  <div class="flex gap-2">
                    <Input v-model="state.startfid" placeholder="如 S01E92 / E92，转存该集及之后" class="flex-1" />
                    <Button variant="outline" size="sm" @click="openStartfidPicker" :disabled="!state.shareurl.trim()">
                      <FileText class="h-4 w-4 mr-1" />
                      选择
                    </Button>
                  </div>
                  <p class="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                    按重命名规则提取剧集号后过滤；换分享链接后仍有效。
                  </p>
                </div>

                <div>
                  <label class="field-label">更新子目录 (update_subdir)</label>
                  <Input v-model="state.update_subdir" placeholder="如 Season 1" />
                </div>

                <div>
                  <label class="field-label">子目录重存模式</label>
                  <select
                    v-model="state.update_subdir_resave_mode"
                    class="field-input"
                  >
                    <option value="none">不重存</option>
                    <option value="resave">重存新文件</option>
                    <option value="resave_all">全量重存</option>
                  </select>
                </div>
              </div>
            </section>
          </div>

          <!-- Footer -->
          <div class="modal-bar flex items-center justify-between border-t border-[hsl(var(--border))] px-6 py-4">
            <Button variant="outline" size="sm" class="rounded-full" @click="handleRunOnce" :disabled="submitting">
              <Play class="h-4 w-4 mr-1" />
              运行一次
            </Button>
            <div class="flex items-center gap-3">
              <Button variant="outline" size="sm" class="rounded-full" @click="resetAndClose">取消</Button>
              <Button size="sm" class="rounded-full" :disabled="submitting" @click="handleSubmit">
                <Loader2 v-if="submitting" class="mr-1.5 h-4 w-4 animate-spin" />
                {{ isEditing ? '保存修改' : '创建任务' }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 资源搜索弹窗 -->
    <ResourceSearchDialog
      v-model:visible="showResourceSearch"
      :initial-query="resourceSearchQuery"
      :drive-type="resourceSearchDriveType"
      :drive-types="resourceSearchDriveTypes"
      :multi-select="true"
      :actions="resourceSearchActions"
      :preview-context="sharePreviewContext"
      @select="onResourceSelected"
      @action="onResourceAction"
    />

    <!-- 备用链接预览：与主链接预览一致（可刷新/导航/选目录），选目录写回该条备用链接 -->
    <SharePreviewDialog
      v-model:visible="backupPreviewVisible"
      :shareurl="backupPreviewUrl"
      :readonly="false"
      :preview-context="sharePreviewContext"
      :z-index="110"
      @pick-folder="onPickBackupFolder"
    />
  </Teleport>
</template>

<style scoped>
.task-modal-enter-active,
.task-modal-leave-active {
  transition: opacity 0.2s ease;
}
.task-modal-enter-active > div:last-child,
.task-modal-leave-active > div:last-child {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.task-modal-enter-from,
.task-modal-leave-to {
  opacity: 0;
}
.task-modal-enter-from > div:last-child,
.task-modal-leave-to > div:last-child {
  transform: translateY(12px) scale(0.98);
  opacity: 0;
}

/* ===== 关联同步任务：可选行（iOS 分组列表风格，自绘勾选框代替原生 checkbox） ===== */
.sync-option {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.5rem 0.7rem;
  font-size: 0.78rem;
  color: hsl(var(--foreground));
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.sync-option + .sync-option {
  border-top: 1px solid hsl(var(--border) / 0.7);
}

.sync-option:hover {
  background: hsl(var(--accent));
}

.sync-option--on {
  background: hsl(var(--primary) / 0.07);
}

.sync-option--on:hover {
  background: hsl(var(--primary) / 0.12);
}

.sync-option__box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 1.05rem;
  width: 1.05rem;
  flex-shrink: 0;
  border-radius: 0.35rem;
  border: 1.5px solid hsl(var(--border));
  background: hsl(var(--background));
  color: transparent;
  transition:
    background-color 0.16s cubic-bezier(0.32, 0.72, 0, 1),
    border-color 0.16s ease,
    color 0.16s ease;
}

.sync-option--on .sync-option__box {
  border-color: hsl(var(--primary));
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}

/* 原生 checkbox 被 sr-only 隐藏，用 focus-within 补回键盘焦点可见性 */
.sync-option:focus-within .sync-option__box {
  box-shadow: 0 0 0 3px hsl(var(--ring) / 0.25);
}

.sync-option__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-option--on .sync-option__name {
  font-weight: 500;
}

/* ===== 关联同步任务：执行顺序行 ===== */
.sync-order {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.35rem 0.3rem 0.2rem;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--background));
  font-size: 0.75rem;
  color: hsl(var(--foreground));
  transition:
    box-shadow 0.18s ease,
    opacity 0.18s ease;
}

.sync-order:hover {
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.06);
}

.sync-order--dragging {
  opacity: 0.45;
}

.sync-order__grip {
  height: 0.85rem;
  width: 0.85rem;
  flex-shrink: 0;
  color: hsl(var(--muted-foreground));
  cursor: grab;
}

.sync-order__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 1.15rem;
  width: 1.15rem;
  flex-shrink: 0;
  border-radius: 9999px;
  background: hsl(var(--primary) / 0.12);
  color: hsl(var(--primary));
  font-size: 0.625rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.sync-order__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
