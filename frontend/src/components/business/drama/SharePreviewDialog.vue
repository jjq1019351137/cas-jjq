<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { X, Folder, FileText, ArrowUp, RefreshCw, ChevronLeft, ChevronRight, Loader2 } from 'lucide-vue-next'
import { previewShare } from '@/api/tasks'
import type { SharePreviewItem } from '@/types/tasks'

/** 分享链接预览上下文：透传给 previewShare 以复算重命名预览（name_re） */
export interface SharePreviewContext {
  taskname?: string
  pattern?: string | null
  replace?: string | null
  sort_index?: number | null
  savepath?: string | null
  ignore_extension?: boolean | null
  update_subdir?: string | null
  startfid?: string | null
  tmdb_id?: number | null
  tmdb_media_type?: string | null
  account_name?: string | null
}

interface Props {
  visible: boolean
  shareurl: string
  /** 只读模式：隐藏"使用当前文件夹"，仅浏览内容与重命名结果 */
  readonly?: boolean
  previewContext?: SharePreviewContext | null
  zIndex?: number
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false,
  previewContext: null,
  zIndex: 100,
})

const emit = defineEmits<{
  'update:visible': [val: boolean]
  /** 非只读模式下"使用当前文件夹"：root=true 表示选择分享根目录 */
  'pick-folder': [payload: { root: boolean; pdir_fid?: string; name?: string }]
  /** 首次加载完成（供调用方做任务名回填等） */
  loaded: [items: SharePreviewItem[]]
}>()

const PAGE_SIZE = 20

const previewing = ref(false)
const error = ref('')
const items = ref<SharePreviewItem[]>([])
const total = ref(0)
const page = ref(1)
const dirStack = ref<{ pdir_fid: string; name: string }[]>([])
const forcedRoot = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(items.value.length / PAGE_SIZE)))
const pageItems = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return items.value.slice(start, start + PAGE_SIZE)
})

/** 当前 shareurl 是否已定位到子目录（带 fid 参数） */
const shareurlHasFid = computed(() => {
  const raw = String(props.shareurl || '').trim()
  return /[?&#]fid=/i.test(raw) || /#\/list\/share\//i.test(raw)
})

const hasPattern = computed(() => Boolean(String(props.previewContext?.pattern || '').trim()))

function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + 'MB'
  return (bytes / 1073741824).toFixed(2) + 'GB'
}

function formatTime(ts: any): string {
  if (!ts) return '-'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return '-'
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch { return '-' }
}

function buildParams(overrides: Record<string, any> = {}) {
  const ctx = props.previewContext || {}
  return {
    shareurl: String(props.shareurl || '').trim(),
    account_name: ctx.account_name ?? undefined,
    max_items: 200,
    taskname: ctx.taskname || undefined,
    pattern: ctx.pattern || undefined,
    replace: ctx.replace || undefined,
    sort_index: ctx.sort_index ?? undefined,
    savepath: ctx.savepath || undefined,
    ignore_extension: ctx.ignore_extension ?? undefined,
    update_subdir: ctx.update_subdir || undefined,
    startfid: ctx.startfid || undefined,
    tmdb_id: ctx.tmdb_id ?? undefined,
    tmdb_media_type: ctx.tmdb_media_type || undefined,
    ...overrides,
  }
}

async function loadDir(pdirFid?: string, opts: { emitLoaded?: boolean } = {}) {
  const url = String(props.shareurl || '').trim()
  if (!url) return
  previewing.value = true
  error.value = ''
  try {
    const pdirParam = pdirFid || (forcedRoot.value ? '' : null)
    const res = await previewShare(buildParams({ pdir_fid: pdirParam }))
    const list = res.items || []
    items.value = list
    total.value = list.length
    page.value = 1
    if (opts.emitLoaded) emit('loaded', list)
  } catch (e: any) {
    error.value = e?.message || '预览失败'
    items.value = []
    total.value = 0
  } finally {
    previewing.value = false
  }
}

async function refresh() {
  const pdirFid = dirStack.value.length > 0 ? dirStack.value[dirStack.value.length - 1].pdir_fid : undefined
  await loadDir(pdirFid)
}

async function enterDir(item: SharePreviewItem) {
  if (!item.is_dir) return
  dirStack.value.push({ pdir_fid: item.fid, name: item.name })
  await loadDir(item.fid)
}

function goBack() {
  dirStack.value.pop()
  const last = dirStack.value.length > 0 ? dirStack.value[dirStack.value.length - 1].pdir_fid : undefined
  loadDir(last)
}

function goRoot() {
  dirStack.value = []
  forcedRoot.value = true
  loadDir(undefined)
}

function pickCurrentFolder() {
  if (props.readonly) return
  if (forcedRoot.value && dirStack.value.length === 0) {
    emit('pick-folder', { root: true })
    return
  }
  const current = dirStack.value.at(-1)
  if (current) {
    emit('pick-folder', { root: false, pdir_fid: current.pdir_fid, name: current.name })
  }
}

function close() {
  emit('update:visible', false)
}

watch(
  () => props.visible,
  (val) => {
    if (val) {
      items.value = []
      total.value = 0
      page.value = 1
      dirStack.value = []
      forcedRoot.value = false
      error.value = ''
      loadDir(undefined, { emitLoaded: true })
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 flex items-center justify-center" :style="{ zIndex }">
      <div class="absolute inset-0 bg-black/60" @click="close" />
      <div class="modal-surface relative z-10 flex max-h-[80vh] w-[720px] flex-col overflow-hidden">
        <div class="modal-bar flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">分享链接预览（共 {{ total }} 个文件）</h3>
          <button class="icon-action" @click="close">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>
        <!-- Toolbar -->
        <div class="modal-bar flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-2">
          <button class="icon-action" title="刷新" @click="refresh" :disabled="previewing">
            <RefreshCw class="h-4 w-4" :class="previewing ? 'animate-spin' : ''" />
          </button>
          <button v-if="dirStack.length > 0 || shareurlHasFid" class="icon-action w-auto gap-1 px-2 text-xs" @click="goRoot" title="回到分享根目录">
            <Folder class="h-3.5 w-3.5" /> 根目录
          </button>
          <button v-if="dirStack.length > 0" class="icon-action w-auto gap-1 px-2 text-xs" @click="goBack">
            <ArrowUp class="h-3.5 w-3.5" /> 返回上级
          </button>
          <span v-if="dirStack.length > 0" class="text-xs text-[hsl(var(--muted-foreground))] truncate">/ {{ dirStack.map(d => d.name).join(' / ') }}</span>
          <span v-else-if="forcedRoot" class="text-xs text-[hsl(var(--muted-foreground))]">分享根目录</span>
          <span v-else-if="shareurlHasFid" class="text-xs text-[hsl(var(--muted-foreground))]">当前位于指定子目录</span>
          <div class="flex-1" />
          <Button v-if="!readonly" size="sm" variant="default" @click="pickCurrentFolder" :disabled="!dirStack.length && !forcedRoot">
            使用当前文件夹
          </Button>
        </div>
        <!-- Table Header -->
        <div class="grid grid-cols-[1fr_80px_1fr_120px] gap-2 px-3 py-2 border-b-2 border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]">
          <span>名称</span><span>大小</span><span>重命名预览</span><span>时间</span>
        </div>
        <!-- Table Body -->
        <div class="flex-1 overflow-y-auto">
          <div v-if="previewing && !items.length" class="flex items-center justify-center py-10">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="error" class="py-8 text-center text-xs text-red-500">{{ error }}</div>
          <div v-else-if="!items.length" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">无文件</div>
          <div
            v-for="(item, idx) in pageItems"
            :key="idx"
            class="grid grid-cols-[1fr_80px_1fr_120px] gap-2 items-center px-3 py-2 border-b border-[hsl(var(--border))] hover:bg-[hsl(var(--accent)/.5)] text-sm"
          >
            <div class="flex items-center gap-2 min-w-0">
              <component :is="item.is_dir ? Folder : FileText" class="h-4 w-4 shrink-0 text-[hsl(var(--muted-foreground))]" />
              <span class="truncate" :class="item.is_dir ? 'cursor-pointer text-[hsl(var(--primary))] hover:underline' : ''" @click="item.is_dir && enterDir(item)">{{ item.name }}</span>
            </div>
            <div class="text-[hsl(var(--muted-foreground))] text-xs">{{ item.is_dir ? (item.include_items || item.children_count || 0) + '项' : formatSize(item.size || 0) }}</div>
            <div class="truncate text-xs">
              <span v-if="item.file_name_re" class="text-green-600">{{ item.file_name_re }}</span>
              <span v-else-if="item.file_name_saved" class="text-[hsl(var(--muted-foreground))]">{{ item.file_name_saved }}</span>
              <span v-else-if="hasPattern" class="text-red-500">×</span>
              <span v-else class="text-[hsl(var(--muted-foreground))]">-</span>
            </div>
            <div class="text-[hsl(var(--muted-foreground))] text-xs">{{ formatTime(item.updated_at) }}</div>
          </div>
        </div>
        <!-- Pagination -->
        <div v-if="totalPages > 1" class="modal-bar flex items-center justify-center gap-3 border-t border-[hsl(var(--border))] px-5 py-3">
          <button class="icon-action" :disabled="page <= 1" @click="page--">
            <ChevronLeft class="h-4 w-4 text-[hsl(var(--foreground))]" />
          </button>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ page }} / {{ totalPages }}</span>
          <button class="icon-action" :disabled="page >= totalPages" @click="page++">
            <ChevronRight class="h-4 w-4 text-[hsl(var(--foreground))]" />
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
