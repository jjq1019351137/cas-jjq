<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import {
  RefreshCw,
  Search,
  X,
  FileText,
  Loader2,
  CheckCircle2,
  XCircle,
  ListFilter,
  PlayCircle,
  Wand2,
  Settings2,
} from 'lucide-vue-next'
import { fetchAuditLogs, fetchAuditLogDetail } from '@/api/audit'
import type { AuditLogItem } from '@/types/audit'
import { useToast } from '@/composables/useToast'

const { toast } = useToast()

const loading = ref(false)
const items = ref<AuditLogItem[]>([])
const total = ref(0)

// 四个视图：全部 / 任务运行 / 自动修改 / 管理操作
type ViewKey = 'all' | 'run' | 'auto' | 'manage'
const views = [
  { key: 'all', label: '全部', icon: ListFilter },
  { key: 'run', label: '任务运行', icon: PlayCircle },
  { key: 'auto', label: '自动修改', icon: Wand2 },
  { key: 'manage', label: '管理操作', icon: Settings2 },
] as const
const view = ref<ViewKey>('all')

const query = reactive({
  page: 1,
  page_size: 20,
  q: '',
  success: 'all' as 'all' | 'success' | 'failed',
})

const successParam = computed(() => {
  if (query.success === 'success') return true
  if (query.success === 'failed') return false
  return undefined
})

const totalPages = computed(() => Math.ceil(total.value / query.page_size))
const hasFilters = computed(() => !!query.q || query.success !== 'all')

function viewParams(): { action?: string; source?: string } {
  switch (view.value) {
    case 'run':
      return { action: 'task.run,sync_task.run' }
    case 'auto':
      return { action: 'task.shareurl_repair,task.shareurl_autoupdate' }
    case 'manage':
      return { source: 'none' }
    default:
      return {}
  }
}

async function loadData() {
  loading.value = true
  try {
    const data = await fetchAuditLogs({
      page: query.page,
      page_size: query.page_size,
      q: query.q || undefined,
      success: successParam.value,
      ...viewParams(),
    })
    items.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function switchView(v: ViewKey) {
  if (view.value === v) return
  view.value = v
  query.page = 1
  loadData()
}

function resetFilters() {
  query.q = ''
  query.success = 'all'
  query.page = 1
  loadData()
}

function prevPage() {
  if (query.page > 1) {
    query.page--
    loadData()
  }
}

function nextPage() {
  if (query.page < totalPages.value) {
    query.page++
    loadData()
  }
}

function formatTime(dt: string) {
  if (!dt) return '-'
  const d = new Date(dt)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function actorText(row: AuditLogItem) {
  if (row.actor_username) return row.actor_username
  if (row.actor_user_id) return `#${row.actor_user_id}`
  return row.actor_type === 'system' ? '系统' : '匿名'
}

// ---- 详情弹窗（懒加载 detail） ----
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailRow = ref<AuditLogItem | null>(null)
const detailText = ref('')

async function openDetail(row: AuditLogItem) {
  detailRow.value = row
  detailText.value = ''
  detailOpen.value = true
  if (!row.has_detail) return
  detailLoading.value = true
  try {
    const data = await fetchAuditLogDetail(row.id)
    detailText.value = data.detail || ''
  } catch {
    toast.error('加载详情失败')
    detailOpen.value = false
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  detailRow.value = null
  detailText.value = ''
}

// Initial load
loadData()
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-5 flex items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">📜 审计日志</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">谁、何时、做了什么，结果如何</p>
      </div>
      <button
        class="inline-flex h-9 items-center gap-1.5 rounded-full border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.6)] px-3.5 text-sm font-medium text-[hsl(var(--foreground))] backdrop-blur transition-all hover:bg-[hsl(var(--muted)/.6)] active:scale-95 disabled:opacity-50"
        :disabled="loading"
        @click="loadData"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
    </div>

    <!-- View tabs (segmented pill) -->
    <div class="mb-4 flex overflow-x-auto overscroll-x-contain">
      <div class="inline-flex gap-1 rounded-2xl border border-[hsl(var(--border)/.6)] bg-[hsl(var(--muted))]/40 p-1 backdrop-blur">
        <button
          v-for="v in views"
          :key="v.key"
          class="flex shrink-0 items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-sm font-medium transition-all"
          :class="view === v.key
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="switchView(v.key)"
        >
          <component :is="v.icon" class="h-3.5 w-3.5" />
          {{ v.label }}
        </button>
      </div>
    </div>

    <!-- Filter bar -->
    <div class="mb-4 flex flex-wrap items-center gap-2.5">
      <div class="relative w-full sm:w-72">
        <Search class="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
        <input
          v-model="query.q"
          placeholder="搜索摘要 / 操作 / 用户 / 目标…"
          class="h-9 w-full rounded-full border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.6)] pl-9 pr-3 text-sm text-[hsl(var(--foreground))] outline-none backdrop-blur transition-all placeholder:text-[hsl(var(--muted-foreground))] focus:border-[hsl(var(--ring))] focus:ring-2 focus:ring-[hsl(var(--ring)/.25)]"
          @keyup.enter="() => { query.page = 1; loadData() }"
        />
      </div>

      <div class="inline-flex gap-1 rounded-full border border-[hsl(var(--border)/.6)] bg-[hsl(var(--muted))]/40 p-1 backdrop-blur">
        <button
          v-for="opt in [
            { label: '全部', value: 'all' },
            { label: '成功', value: 'success' },
            { label: '失败', value: 'failed' },
          ]"
          :key="opt.value"
          class="rounded-full px-3 py-1 text-xs font-medium transition-all"
          :class="query.success === opt.value
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="() => { query.success = opt.value as any; query.page = 1; loadData() }"
        >
          {{ opt.label }}
        </button>
      </div>

      <button
        v-if="hasFilters"
        class="inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-xs text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
        @click="resetFilters"
      >
        <X class="h-3 w-3" />
        清除
      </button>
    </div>

    <!-- List (glass card) -->
    <div class="glass-card !p-0 overflow-hidden">
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center gap-2 py-16 text-sm text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-4 w-4 animate-spin" /> 加载中…
      </div>
      <!-- Empty -->
      <div v-else-if="items.length === 0" class="flex flex-col items-center justify-center gap-2 py-16 text-[hsl(var(--muted-foreground))]">
        <FileText class="h-8 w-8 opacity-40" />
        <span class="text-sm">暂无日志记录</span>
      </div>
      <!-- Rows -->
      <ul v-else class="divide-y divide-[hsl(var(--border)/.5)]">
        <li
          v-for="row in items"
          :key="row.id"
          class="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-[hsl(var(--muted)/.45)]"
        >
          <!-- Status indicator -->
          <div class="mt-0.5 shrink-0">
            <CheckCircle2 v-if="row.success" class="h-4 w-4 text-emerald-500" />
            <XCircle v-else class="h-4 w-4 text-[hsl(var(--destructive))]" />
          </div>

          <!-- Main -->
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ row.summary }}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[hsl(var(--muted-foreground))]">
              <span class="inline-flex items-center rounded-md bg-[hsl(var(--muted)/.7)] px-1.5 py-0.5 font-medium text-[hsl(var(--foreground)/.75)]">
                {{ row.action_label || row.action }}
              </span>
              <span
                v-if="row.source_label"
                class="inline-flex items-center rounded-md bg-[hsl(var(--primary)/.1)] px-1.5 py-0.5 font-medium text-[hsl(var(--primary))]"
              >
                {{ row.source_label }}
              </span>
              <span class="text-[hsl(var(--muted-foreground))]">{{ actorText(row) }}</span>
              <span class="text-[hsl(var(--border))]">·</span>
              <span>{{ formatTime(row.created_at) }}</span>
              <span v-if="row.ip" class="text-[hsl(var(--border))]">·</span>
              <span v-if="row.ip" class="font-mono">{{ row.ip }}</span>
            </div>
            <div v-if="!row.success && row.error_message" class="mt-1 text-xs text-[hsl(var(--destructive))]">
              {{ row.error_message }}
            </div>
          </div>

          <!-- Detail button -->
          <button
            v-if="row.has_detail"
            class="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border border-[hsl(var(--border)/.6)] px-2.5 py-1 text-xs text-[hsl(var(--muted-foreground))] opacity-0 transition-all hover:bg-[hsl(var(--muted)/.6)] hover:text-[hsl(var(--foreground))] group-hover:opacity-100"
            @click="openDetail(row)"
          >
            <FileText class="h-3 w-3" />
            详情
          </button>
        </li>
      </ul>
    </div>

    <!-- Pagination -->
    <div class="mt-4 flex items-center justify-between">
      <span class="text-xs text-[hsl(var(--muted-foreground))]">
        共 {{ total }} 条 · 第 {{ query.page }}/{{ totalPages || 1 }} 页
      </span>
      <div class="flex items-center gap-2">
        <button
          class="inline-flex h-8 items-center rounded-full border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.6)] px-3.5 text-xs font-medium text-[hsl(var(--foreground))] backdrop-blur transition-all hover:bg-[hsl(var(--muted)/.6)] active:scale-95 disabled:opacity-40"
          :disabled="query.page <= 1"
          @click="prevPage"
        >
          上一页
        </button>
        <button
          class="inline-flex h-8 items-center rounded-full border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.6)] px-3.5 text-xs font-medium text-[hsl(var(--foreground))] backdrop-blur transition-all hover:bg-[hsl(var(--muted)/.6)] active:scale-95 disabled:opacity-40"
          :disabled="query.page >= totalPages"
          @click="nextPage"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- Detail dialog -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-150"
      leave-to-class="opacity-0"
    >
      <div
        v-if="detailOpen"
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
        @click.self="closeDetail"
      >
        <div class="flex max-h-[82vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.85)] shadow-2xl backdrop-blur-xl">
          <div class="flex items-start justify-between gap-3 border-b border-[hsl(var(--border)/.5)] px-5 py-4">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <CheckCircle2 v-if="detailRow?.success" class="h-4 w-4 shrink-0 text-emerald-500" />
                <XCircle v-else class="h-4 w-4 shrink-0 text-[hsl(var(--destructive))]" />
                <span class="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{{ detailRow?.summary }}</span>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-[hsl(var(--muted-foreground))]">
                <span>{{ detailRow ? formatTime(detailRow.created_at) : '' }}</span>
                <span class="text-[hsl(var(--border))]">·</span>
                <span>{{ detailRow?.action_label }}</span>
                <template v-if="detailRow?.source_label">
                  <span class="text-[hsl(var(--border))]">·</span>
                  <span>{{ detailRow?.source_label }}</span>
                </template>
              </div>
            </div>
            <button
              class="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted)/.6)] hover:text-[hsl(var(--foreground))]"
              @click="closeDetail"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
          <div class="flex-1 overflow-auto p-5">
            <div v-if="detailLoading" class="flex items-center justify-center gap-2 py-10 text-sm text-[hsl(var(--muted-foreground))]">
              <Loader2 class="h-4 w-4 animate-spin" /> 加载详情…
            </div>
            <pre
              v-else
              class="whitespace-pre-wrap break-words rounded-2xl border border-[hsl(var(--border)/.5)] bg-[hsl(var(--muted)/.5)] p-4 font-mono text-xs leading-relaxed text-[hsl(var(--foreground))]"
            >{{ detailText || '（无详情）' }}</pre>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
