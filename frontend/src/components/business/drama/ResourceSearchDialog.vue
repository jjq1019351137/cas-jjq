<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Search, Loader2, X, History, Trash2, CheckCircle2, XCircle, HelpCircle } from 'lucide-vue-next'
import { previewShare } from '@/api/tasks'
import { fetchTaskSuggestions, verifyTaskSuggestions } from '@/api/resourceSearch'
import { RESOURCE_SEARCH_SOURCE_LABELS, type TaskSuggestionItem } from '@/types/resourceSearch'
import { detectDriveTypeByUrl } from '@/utils/driveType'

interface Props {
  visible: boolean
  initialQuery?: string
  /** 已确定的网盘类型（指定账号，或自动+已填分享链接推断），传入后只搜该网盘资源 */
  driveType?: string | null
  /** 待选网盘类型集合（已有账号类型），driveType 为空时用于限定搜索范围 */
  driveTypes?: string[] | null
}

const props = withDefaults(defineProps<Props>(), {
  initialQuery: '',
  driveType: null,
  driveTypes: null,
})

const emit = defineEmits<{
  'update:visible': [val: boolean]
  select: [item: TaskSuggestionItem]
}>()

// ===== State =====
const HISTORY_KEY = 'resource_search_history'
const PAGE_SIZE = 30

const query = ref('')
const inputRef = ref<InstanceType<typeof Input> | null>(null)
const listRef = ref<HTMLDivElement | null>(null)

const search = reactive({
  loading: false,
  verifying: false,
  deep: 0 as 0 | 1,
  runId: 0,
  message: '',
  items: [] as TaskSuggestionItem[],
  searched: false,
})

const selectedSource = ref<string>('all')
const visibleCount = ref(PAGE_SIZE)
const history = ref<string[]>(loadHistory())

// ===== History =====
function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const arr = JSON.parse(raw || '[]')
    return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string' && x.trim()).slice(0, 10) : []
  } catch {
    return []
  }
}

function pushHistory(q: string) {
  const v = q.trim()
  if (!v) return
  const next = [v, ...history.value.filter((x) => x !== v)].slice(0, 10)
  history.value = next
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  } catch { /* ignore */ }
}

function clearHistory() {
  history.value = []
  try {
    localStorage.removeItem(HISTORY_KEY)
  } catch { /* ignore */ }
}

// ===== Derived =====
const sourceOptions = computed(() => {
  const map = new Map<string, { key: string; label: string; count: number }>()
  for (const item of search.items) {
    const key = String(item.source_key || item.source || '').trim() || 'unknown'
    const label = RESOURCE_SEARCH_SOURCE_LABELS[key] || String(item.source || key)
    const entry = map.get(key) || { key, label, count: 0 }
    entry.count += 1
    map.set(key, entry)
  }
  return [...map.values()]
})

const filteredItems = computed(() => {
  if (selectedSource.value === 'all') return search.items
  return search.items.filter((x) => (String(x.source_key || x.source || '').trim() || 'unknown') === selectedSource.value)
})

const displayItems = computed(() => filteredItems.value.slice(0, visibleCount.value))

// 搜索范围提示：优先展示已确定的单一网盘类型，否则展示已有账号类型集合
const scopeHint = computed(() => {
  const dt = String(props.driveType || '').trim()
  if (dt) return `已限定 ${dt}`
  const list = (props.driveTypes || []).map((x) => String(x || '').trim()).filter(Boolean)
  if (list.length) return `已有账号：${list.join(' / ')}`
  return ''
})

const stats = computed(() => {
  const list = filteredItems.value
  return {
    total: list.length,
    valid: list.filter((x) => x.verify === true).length,
    invalid: list.filter((x) => x.verify === false).length,
    pending: list.filter((x) => x.verify === null || x.verify === undefined).length,
  }
})

// ===== Helpers =====
function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + 'MB'
  return (bytes / 1073741824).toFixed(2) + 'GB'
}

function sanitizeQuery(value: string) {
  return String(value || '')
    .replace(/\((19|20)\d{2}\)/g, '')
    .trim()
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ===== Search =====
async function doSearch(deep: 0 | 1) {
  const q = sanitizeQuery(query.value)
  if (q.length < 2) return
  search.loading = true
  search.searched = true
  search.deep = deep
  search.message = ''
  search.items = []
  selectedSource.value = 'all'
  visibleCount.value = PAGE_SIZE
  search.runId += 1
  const runId = search.runId
  pushHistory(q)
  try {
    const res = await fetchTaskSuggestions(q, deep, props.driveType, null, props.driveTypes)
    if (runId !== search.runId) return
    search.message = String(res?.message || '').trim()
    search.items = (res?.data || []).filter((x) => x && x.shareurl).map((x) => ({ ...x, verify: null }))
    if (search.items.length) {
      verifyItems(runId, search.items)
    }
  } catch {
    if (runId === search.runId) search.message = '搜索失败，请稍后重试'
  } finally {
    if (runId === search.runId) search.loading = false
  }
}

// ===== Verify（按网盘类型分组逐组验证，组间随机延迟防限流）=====
async function verifyItems(runId: number, items: TaskSuggestionItem[]) {
  search.verifying = true
  const pending = items.filter((x) => x.shareurl && (x.verify === null || x.verify === undefined)).map((x) => x.shareurl)
  const dedup = Array.from(new Set(pending))

  const byDrive = new Map<string, string[]>()
  const unknown: string[] = []
  for (const url of dedup) {
    const dt = detectDriveTypeByUrl(url)
    if (!dt) {
      unknown.push(url)
      continue
    }
    const list = byDrive.get(String(dt)) || []
    list.push(url)
    byDrive.set(String(dt), list)
  }

  const driveGroups = [...byDrive.entries()].map(([drive_type, shareurls]) => ({ drive_type, shareurls }))
  driveGroups.sort((a, b) => a.drive_type.localeCompare(b.drive_type))

  for (const { shareurls } of driveGroups) {
    if (runId !== search.runId || !props.visible) return
    try {
      const res = await verifyTaskSuggestions(shareurls)
      if (runId !== search.runId) return
      const mapping = new Map((res.items || []).map((it) => [it.shareurl, it]))
      for (const it of items) {
        if (!it.shareurl) continue
        const row = mapping.get(it.shareurl)
        if (!row) continue
        it.verify = Boolean(row.ok)
        if (row.max_file_size) it.maxFileSize = Number(row.max_file_size) || null
      }
      markLargestAndSort(items)
    } catch {
      if (runId !== search.runId) return
      for (const it of items) {
        if (shareurls.includes(it.shareurl)) it.verify = false
      }
    }
    await sleep(120 + Math.floor(Math.random() * 180))
  }

  for (const url of unknown) {
    if (runId !== search.runId || !props.visible) return
    try {
      await previewShare({ shareurl: url, max_items: 1 })
      if (runId !== search.runId) return
      for (const it of items) {
        if (it.shareurl === url) it.verify = true
      }
    } catch {
      if (runId !== search.runId) return
      for (const it of items) {
        if (it.shareurl === url) it.verify = false
      }
    }
  }

  if (runId === search.runId) {
    markLargestAndSort(items)
    search.verifying = false
  }
}

function markLargestAndSort(items: TaskSuggestionItem[]) {
  const sizes = items.map((x) => Number(x.maxFileSize) || 0)
  const max = sizes.length ? Math.max(...sizes) : 0
  for (const it of items) it.isLargest = max > 0 && (Number(it.maxFileSize) || 0) === max
  // 有效结果按文件大小降序排前面，失效/未知结果排后面
  search.items = [
    ...items.filter((i) => i.verify === true).sort((a, b) => (Number(b.maxFileSize) || 0) - (Number(a.maxFileSize) || 0)),
    ...items.filter((i) => i.verify !== true),
  ]
}

// ===== Interaction =====
function selectItem(item: TaskSuggestionItem) {
  emit('select', item)
  close()
}

function close() {
  search.runId += 1
  emit('update:visible', false)
}

function onListScroll() {
  const el = listRef.value
  if (!el) return
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80 && visibleCount.value < filteredItems.value.length) {
    visibleCount.value += PAGE_SIZE
  }
}

function applyHistory(q: string) {
  query.value = q
  doSearch(0)
}

watch(selectedSource, () => {
  visibleCount.value = PAGE_SIZE
  if (listRef.value) listRef.value.scrollTop = 0
})

watch(
  () => props.visible,
  (val) => {
    if (val) {
      query.value = sanitizeQuery(props.initialQuery || '')
      search.items = []
      search.message = ''
      search.searched = false
      selectedSource.value = 'all'
      visibleCount.value = PAGE_SIZE
      history.value = loadHistory()
      nextTick(() => {
        if (query.value.length >= 2) doSearch(0)
      })
    } else {
      search.runId += 1
      search.loading = false
      search.verifying = false
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-6">
      <!-- Overlay -->
      <div class="absolute inset-0 bg-black/60" @click="close" />

      <!-- Panel -->
      <div class="relative z-10 flex h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-3 sm:px-5">
          <div class="flex items-center gap-2">
            <Search class="h-4 w-4 text-[hsl(var(--primary))]" />
            <h2 class="text-base font-semibold text-[hsl(var(--card-foreground))]">资源搜索</h2>
            <Badge v-if="scopeHint" variant="outline" class="text-[10px]">{{ scopeHint }}</Badge>
            <span v-if="search.verifying" class="inline-flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
              <Loader2 class="h-3 w-3 animate-spin" /> 正在检查链接有效性...
            </span>
          </div>
          <button
            class="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
            @click="close"
          >
            <X class="h-4.5 w-4.5" />
          </button>
        </div>

        <!-- Search bar -->
        <div class="border-b border-[hsl(var(--border))] px-4 py-3 sm:px-5">
          <div class="flex items-center gap-2">
            <div class="relative flex-1">
              <Input
                ref="inputRef"
                v-model="query"
                placeholder="输入至少 2 个字符搜索资源，如剧名"
                @keydown.enter="doSearch(0)"
              />
            </div>
            <Button size="sm" :disabled="sanitizeQuery(query).length < 2 || search.loading" @click="doSearch(0)">
              <Loader2 v-if="search.loading && search.deep === 0" class="mr-1 h-3.5 w-3.5 animate-spin" />
              <Search v-else class="mr-1 h-3.5 w-3.5" />
              搜索
            </Button>
            <Button size="sm" variant="outline" :disabled="sanitizeQuery(query).length < 2 || search.loading" @click="doSearch(1)">
              <Loader2 v-if="search.loading && search.deep === 1" class="mr-1 h-3.5 w-3.5 animate-spin" />
              深度搜索
            </Button>
          </div>

          <!-- Search history -->
          <div v-if="history.length && !search.items.length && !search.loading" class="mt-2.5 flex flex-wrap items-center gap-1.5">
            <History class="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
            <button
              v-for="h in history"
              :key="h"
              class="rounded-full border border-[hsl(var(--border))] px-2.5 py-0.5 text-xs text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
              @click="applyHistory(h)"
            >
              {{ h }}
            </button>
            <button
              class="ml-1 inline-flex items-center gap-0.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--destructive))]"
              @click="clearHistory"
            >
              <Trash2 class="h-3 w-3" /> 清空
            </button>
          </div>

          <!-- Source filter + stats -->
          <div v-if="search.items.length" class="mt-2.5 flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <button
                class="rounded-full px-2.5 py-0.5 text-xs transition-colors"
                :class="selectedSource === 'all'
                  ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                  : 'border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'"
                @click="selectedSource = 'all'"
              >
                全部 ({{ search.items.length }})
              </button>
              <button
                v-for="opt in sourceOptions"
                :key="opt.key"
                class="rounded-full px-2.5 py-0.5 text-xs transition-colors"
                :class="selectedSource === opt.key
                  ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                  : 'border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'"
                @click="selectedSource = opt.key"
              >
                {{ opt.label }} ({{ opt.count }})
              </button>
            </div>
            <div class="flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
              <span class="inline-flex items-center gap-0.5"><CheckCircle2 class="h-3 w-3 text-green-500" /> {{ stats.valid }}</span>
              <span class="inline-flex items-center gap-0.5"><XCircle class="h-3 w-3 text-red-400" /> {{ stats.invalid }}</span>
              <span v-if="stats.pending" class="inline-flex items-center gap-0.5"><HelpCircle class="h-3 w-3" /> {{ stats.pending }}</span>
            </div>
          </div>
        </div>

        <!-- Message -->
        <div v-if="search.message" class="border-b border-[hsl(var(--border))] px-4 py-1.5 text-xs text-[hsl(var(--muted-foreground))] sm:px-5">
          {{ search.message }}
        </div>

        <!-- Result list -->
        <div ref="listRef" class="flex-1 overflow-y-auto" @scroll.passive="onListScroll">
          <!-- Loading -->
          <div v-if="search.loading" class="flex flex-col items-center justify-center gap-2 py-16 text-sm text-[hsl(var(--muted-foreground))]">
            <Loader2 class="h-6 w-6 animate-spin text-[hsl(var(--primary))]" />
            {{ search.deep === 1 ? '深度搜索中，可能需要较长时间...' : '搜索中...' }}
          </div>

          <!-- Empty -->
          <div v-else-if="search.searched && !filteredItems.length" class="flex flex-col items-center justify-center gap-1.5 py-16 text-sm text-[hsl(var(--muted-foreground))]">
            <Search class="h-8 w-8 opacity-40" />
            <span>{{ search.items.length ? '当前渠道下没有结果，试试其他渠道' : '未搜索到资源，试试深度搜索或换个关键词' }}</span>
          </div>

          <!-- Idle -->
          <div v-else-if="!search.searched" class="flex flex-col items-center justify-center gap-1.5 py-16 text-sm text-[hsl(var(--muted-foreground))]">
            <Search class="h-8 w-8 opacity-40" />
            <span>输入关键词开始搜索，结果来自网络，请自行辨识</span>
          </div>

          <!-- Items -->
          <template v-else>
            <div
              v-for="(item, idx) in displayItems"
              :key="`${item.shareurl}-${idx}`"
              class="cursor-pointer border-b border-[hsl(var(--border))] px-4 py-2.5 transition-colors last:border-0 hover:bg-[hsl(var(--accent))] sm:px-5"
              :title="item.content || ''"
              @click="selectItem(item)"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-1.5">
                  <CheckCircle2 v-if="item.verify === true" class="h-3.5 w-3.5 shrink-0 text-green-500" />
                  <XCircle v-else-if="item.verify === false" class="h-3.5 w-3.5 shrink-0 text-red-400" />
                  <Loader2 v-else class="h-3.5 w-3.5 shrink-0 animate-spin text-[hsl(var(--muted-foreground))]" />
                  <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ item.taskname || item.content }}</span>
                </div>
                <div class="flex shrink-0 items-center gap-1">
                  <Badge v-if="item.isLargest" variant="outline" class="border-amber-200 bg-amber-50 text-[10px] text-amber-600">最大</Badge>
                  <span v-if="item.maxFileSize" class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ formatSize(item.maxFileSize) }}</span>
                  <Badge v-if="item.source" variant="outline" class="text-[10px]">{{ item.source }}</Badge>
                </div>
              </div>
              <a
                :href="item.shareurl"
                target="_blank"
                rel="noopener"
                class="mt-0.5 block truncate text-xs text-[hsl(var(--primary))] hover:underline"
                @click.stop
              >{{ item.shareurl }}</a>
              <div v-if="item.content || item.datetime || item.channel" class="mt-0.5 flex items-center gap-2 overflow-hidden">
                <span v-if="item.datetime" class="shrink-0 text-[10px] text-[hsl(var(--muted-foreground))]">{{ item.datetime }}</span>
                <span v-if="item.channel" class="shrink-0 text-[10px] text-[hsl(var(--muted-foreground))]">{{ item.channel }}</span>
                <span v-if="item.content" class="truncate text-[10px] text-[hsl(var(--muted-foreground))]">{{ item.content }}</span>
              </div>
            </div>

            <!-- Load more hint -->
            <div v-if="displayItems.length < filteredItems.length" class="py-2.5 text-center text-xs text-[hsl(var(--muted-foreground))]">
              下拉加载更多（{{ displayItems.length }}/{{ filteredItems.length }}）
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="flex items-center justify-between border-t border-[hsl(var(--border))] px-4 py-2.5 text-xs text-[hsl(var(--muted-foreground))] sm:px-5">
          <span>共 {{ stats.total }} 条结果，点击条目填入分享链接</span>
          <Button size="sm" variant="ghost" @click="close">关闭</Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
