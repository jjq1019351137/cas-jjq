<script setup lang="ts">
import { ref, watch, computed, reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { X, Folder, FolderOpen, Loader2, ArrowUp, RefreshCw, FileText, ArrowLeftRight } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useCreateSyncTaskMutation, useUpdateSyncTaskMutation } from '@/hooks/mutations/sync'
import { useTasksQuery } from '@/hooks/queries/tasks'
import { browseLocalSync } from '@/api/syncTasks'
import { browseOpenList } from '@/api/openlist'
import type { SyncTaskItem } from '@/types/syncTasks'
import { extractErrorMessage } from '@/lib/driveAuth'

interface Props {
  open: boolean
  editTask?: SyncTaskItem | null
}

const props = withDefaults(defineProps<Props>(), {
  editTask: null,
})

const emit = defineEmits<{
  close: []
}>()

const { toast } = useToast()
const createMutation = useCreateSyncTaskMutation()
const updateMutation = useUpdateSyncTaskMutation()
const { data: dramaTasks } = useTasksQuery()

type EndpointKind = 'local' | 'openlist'

const isEditing = computed(() => !!props.editTask)
const title = computed(() => (isEditing.value ? '编辑同步任务' : '新建同步任务'))
const showAdvanced = ref(false)

// Form state（已移除网盘直连，仅本地 / OpenList）
const name = ref('')
const enabled = ref(true)
const sourceType = ref<EndpointKind>('openlist')
const sourceAccountId = ref<number | null>(null)
const sourcePath = ref('/')
const targetType = ref<EndpointKind>('local')
const targetAccountId = ref<number | null>(null)
const targetPath = ref('/')
const mode = ref<'one_way' | 'two_way'>('one_way')
const overwrite = ref(false)
const deleteExtras = ref(false)
const deleteExtrasDelayMinutes = ref(5)
const forceRefresh = ref(false)
const autoWash = ref(true)
const unzipZipAfterSync = ref(true)
const concurrency = ref(4)
const requestIntervalSeconds = ref(0)
const openlistCopyBatchSize = ref(200)
const dramaTaskUids = ref<string[]>([])
const DELETE_DELAY_OPTIONS = [0, 5, 10, 15, 20, 25, 30] as const

function endpointLabel(t: EndpointKind) {
  return t === 'local' ? '本地' : 'OpenList'
}

const summaryText = computed(
  () => `${endpointLabel(sourceType.value)} 到 ${endpointLabel(targetType.value)} 的${mode.value === 'one_way' ? '单向' : '双向'}同步`,
)

function swapSides() {
  const st = sourceType.value
  const sp = sourcePath.value
  const sa = sourceAccountId.value
  sourceType.value = targetType.value
  sourcePath.value = targetPath.value
  sourceAccountId.value = targetAccountId.value
  targetType.value = st
  targetPath.value = sp
  targetAccountId.value = sa
}

function normalizeEndpointType(raw: string | undefined | null): EndpointKind {
  return raw === 'openlist' ? 'openlist' : 'local'
}

function resetForm() {
  name.value = ''
  enabled.value = true
  sourceType.value = 'openlist'
  sourceAccountId.value = null
  sourcePath.value = '/'
  targetType.value = 'local'
  targetAccountId.value = null
  targetPath.value = '/'
  mode.value = 'one_way'
  overwrite.value = false
  deleteExtras.value = false
  deleteExtrasDelayMinutes.value = 5
  forceRefresh.value = false
  autoWash.value = true
  unzipZipAfterSync.value = true
  concurrency.value = 4
  requestIntervalSeconds.value = 0
  openlistCopyBatchSize.value = 200
  dramaTaskUids.value = []
  showAdvanced.value = false
}

function fillFromTask(task: SyncTaskItem) {
  name.value = task.name
  enabled.value = task.enabled
  sourceType.value = normalizeEndpointType(task.source.type)
  sourceAccountId.value = null
  sourcePath.value = task.source.path
  targetType.value = normalizeEndpointType(task.target.type)
  targetAccountId.value = null
  targetPath.value = task.target.path
  mode.value = task.mode
  overwrite.value = task.strategy.overwrite
  deleteExtras.value = task.strategy.one_way_delete_extras
  const delay = Number(task.strategy.one_way_delete_extras_delay_minutes ?? 5)
  deleteExtrasDelayMinutes.value = DELETE_DELAY_OPTIONS.includes(delay as any) ? delay : 5
  forceRefresh.value = task.strategy.force_refresh
  autoWash.value = task.strategy.auto_wash ?? true
  unzipZipAfterSync.value = task.strategy.unzip_zip_after_sync ?? true
  concurrency.value = task.strategy.concurrency
  requestIntervalSeconds.value = task.strategy.request_interval_seconds
  openlistCopyBatchSize.value = task.strategy.openlist_copy_batch_size
  dramaTaskUids.value = [...(task.drama_task_uids ?? [])]
  showAdvanced.value = false
}

watch(
  () => props.open,
  (val) => {
    if (val) {
      if (props.editTask) {
        fillFromTask(props.editTask)
      } else {
        resetForm()
      }
    }
  },
)

function buildPayload() {
  return {
    name: name.value.trim(),
    enabled: enabled.value,
    source: {
      type: sourceType.value,
      path: sourcePath.value,
    },
    target: {
      type: targetType.value,
      path: targetPath.value,
    },
    mode: mode.value,
    strategy: {
      overwrite: overwrite.value,
      one_way_delete_extras: deleteExtras.value,
      one_way_delete_extras_delay_minutes: deleteExtras.value ? deleteExtrasDelayMinutes.value : 0,
      force_refresh: forceRefresh.value,
      concurrency: concurrency.value,
      request_interval_seconds: requestIntervalSeconds.value,
      openlist_copy_batch_size: openlistCopyBatchSize.value,
      unzip_zip_after_sync: unzipZipAfterSync.value,
      auto_wash: autoWash.value,
    },
    drama_task_uids: dramaTaskUids.value,
  }
}

function handleSubmit() {
  if (!name.value.trim()) return
  if (isEditing.value && props.editTask) {
    updateMutation.mutate(
      { syncTaskId: props.editTask.id, payload: buildPayload() },
      {
        onSuccess: () => {
          toast.success('同步任务已更新')
          emit('close')
        },
        onError: (err: any) => {
          toast.error('更新失败', { description: extractErrorMessage(err, '未知错误') })
        },
      },
    )
  } else {
    createMutation.mutate(buildPayload(), {
      onSuccess: () => {
        toast.success('同步任务已创建')
        resetForm()
        emit('close')
      },
      onError: (err: any) => {
        toast.error('创建失败', { description: extractErrorMessage(err, '未知错误') })
      },
    })
  }
}

const isPending = computed(() => createMutation.isPending.value || updateMutation.isPending.value)

function handleOverlayClick() {
  emit('close')
}

function toggleDramaTask(uid: string) {
  const idx = dramaTaskUids.value.indexOf(uid)
  if (idx >= 0) {
    dramaTaskUids.value.splice(idx, 1)
  } else {
    dramaTaskUids.value.push(uid)
  }
}

// ===== Path Browser =====
const pathPicker = reactive({
  visible: false,
  loading: false,
  endpoint: '' as 'source' | 'target',
  endpointType: 'local' as EndpointKind,
  accountName: '',
  currentPath: '/',
  paths: [] as Array<{ name: string; fid?: string; path?: string }>,
  items: [] as Array<{ name: string; is_dir: boolean; size?: number | null; updated_at?: any; fid?: string; path?: string }>,
  error: '',
})

async function openPathPicker(endpoint: 'source' | 'target') {
  const type = endpoint === 'source' ? sourceType.value : targetType.value
  pathPicker.endpoint = endpoint
  pathPicker.endpointType = type
  pathPicker.accountName = ''
  pathPicker.currentPath = (endpoint === 'source' ? sourcePath.value : targetPath.value) || '/'
  pathPicker.visible = true
  pathPicker.error = ''
  await refreshPicker()
}

async function refreshPicker() {
  pathPicker.loading = true
  pathPicker.error = ''
  try {
    if (pathPicker.endpointType === 'local') {
      const res = await browseLocalSync({ path: pathPicker.currentPath, max_items: 500 })
      pathPicker.currentPath = res.dir_path || pathPicker.currentPath
      pathPicker.items = res.items || []
      pathPicker.paths = res.paths || []
    } else {
      const res = await browseOpenList({ path: pathPicker.currentPath, max_items: 500 })
      pathPicker.currentPath = res.dir_path || pathPicker.currentPath
      pathPicker.items = res.items || []
      pathPicker.paths = res.paths || []
    }
  } catch (e: any) {
    pathPicker.error = e?.message || '浏览失败'
    pathPicker.items = []
    pathPicker.paths = []
  } finally {
    pathPicker.loading = false
  }
}

function pickerEnterDir(item: { name: string; path?: string }) {
  const newPath = item.path
    ? item.path
    : pathPicker.currentPath.endsWith('/')
      ? pathPicker.currentPath + item.name
      : pathPicker.currentPath + '/' + item.name
  pathPicker.currentPath = newPath
  refreshPicker()
}

function pickerGoUp() {
  const parts = pathPicker.currentPath.replace(/\/+$/, '').split('/')
  parts.pop()
  const parent = parts.join('/') || '/'
  pathPicker.currentPath = parent
  refreshPicker()
}

function pickerGoToBreadcrumb(index: number) {
  if (pathPicker.endpointType === 'local') {
    const parts = pathPicker.paths.slice(0, index + 1)
    const path = parts.map((p) => p.name).join('/') || '/'
    pathPicker.currentPath = path.startsWith('/') ? path : '/' + path
  } else {
    const parts = pathPicker.paths.slice(0, index + 1)
    pathPicker.currentPath = '/' + parts.map((p) => p.name).join('/')
  }
  refreshPicker()
}

function pickerConfirm(withTaskName: boolean) {
  let path = pathPicker.currentPath || '/'
  if (withTaskName && name.value.trim()) {
    path = `${path}/${name.value.trim()}`.replace(/\/+/g, '/')
  }
  if (pathPicker.endpoint === 'source') {
    sourcePath.value = path
  } else {
    targetPath.value = path
  }
  pathPicker.visible = false
}

function closePicker() {
  pathPicker.visible = false
}
</script>

<template>
  <!-- ===== Path Browser Modal ===== -->
  <Teleport to="body">
    <div v-if="pathPicker.visible" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="closePicker" />
      <div class="relative z-10 w-[640px] max-w-[90vw] max-h-[80vh] rounded-lg bg-[hsl(var(--background))] shadow-xl flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))]">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">
            浏览{{ pathPicker.endpoint === 'source' ? '源' : '目标' }}路径
            <span class="ml-2 text-xs font-normal text-[hsl(var(--muted-foreground))]">
              ({{ pathPicker.endpointType === 'local' ? '本地' : 'OpenList' }})
            </span>
          </h3>
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))]" @click="closePicker">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>

        <!-- Breadcrumb & toolbar -->
        <div class="px-5 py-2 border-b border-[hsl(var(--border))] flex items-center gap-2">
          <button
            class="rounded p-1 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]"
            title="返回上级"
            @click="pickerGoUp"
          >
            <ArrowUp class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]"
            title="刷新"
            @click="refreshPicker"
          >
            <RefreshCw class="h-4 w-4" />
          </button>
          <div class="flex-1 flex items-center gap-0.5 overflow-x-auto text-xs text-[hsl(var(--muted-foreground))]">
            <button
              class="hover:text-[hsl(var(--foreground))] hover:underline shrink-0 px-1"
              @click="pathPicker.currentPath = '/'; refreshPicker()"
            >/</button>
            <template v-for="(seg, idx) in pathPicker.paths" :key="idx">
              <span class="shrink-0">/</span>
              <button
                class="hover:text-[hsl(var(--foreground))] hover:underline shrink-0 px-1 truncate max-w-[120px]"
                :title="seg.name"
                @click="pickerGoToBreadcrumb(idx)"
              >{{ seg.name }}</button>
            </template>
          </div>
        </div>

        <!-- Directory listing -->
        <div class="flex-1 overflow-y-auto px-5 py-3 min-h-[200px]">
          <div v-if="pathPicker.loading" class="flex items-center justify-center py-8">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="pathPicker.error" class="text-xs text-red-500 py-4 text-center">{{ pathPicker.error }}</div>
          <div v-else-if="pathPicker.items.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-4 text-center">
            当前目录为空
          </div>
          <div v-else class="space-y-0.5">
            <div
              v-for="(item, idx) in pathPicker.items.filter(i => i.is_dir)"
              :key="'d-' + idx"
              class="flex items-center gap-2 px-2 py-2 rounded cursor-pointer hover:bg-[hsl(var(--accent))] text-sm"
              @click="pickerEnterDir(item)"
            >
              <Folder class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0" />
              <span class="truncate text-[hsl(var(--foreground))] flex-1">{{ item.name }}</span>
            </div>
            <div
              v-for="(item, idx) in pathPicker.items.filter(i => !i.is_dir)"
              :key="'f-' + idx"
              class="flex items-center gap-2 px-2 py-2 rounded text-sm opacity-60"
            >
              <FileText class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0" />
              <span class="truncate text-[hsl(var(--foreground))] flex-1">{{ item.name }}</span>
              <span v-if="item.size" class="text-xs text-[hsl(var(--muted-foreground))] shrink-0">
                {{ item.size > 1048576 ? (item.size / 1048576).toFixed(1) + ' MB' : item.size > 1024 ? (item.size / 1024).toFixed(1) + ' KB' : item.size + ' B' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-[hsl(var(--border))] flex items-center gap-2">
          <Button size="sm" @click="pickerConfirm(false)">使用当前文件夹</Button>
          <Button v-if="name.trim()" size="sm" variant="outline" @click="pickerConfirm(true)">
            当前文件夹/{{ name.trim() }}
          </Button>
          <div class="flex-1" />
          <span class="text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[200px]" :title="pathPicker.currentPath">
            {{ pathPicker.currentPath }}
          </span>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Main Modal ===== -->
  <Teleport to="body">
    <Transition name="sync-modal">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50" @click="handleOverlayClick" />
        <div class="relative z-10 flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl">
          <div class="flex items-start justify-between gap-4 border-b border-[hsl(var(--border))] px-6 py-4">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">{{ title }}</h2>
                <span
                  class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                  :class="enabled ? 'bg-emerald-500/15 text-emerald-600' : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'"
                >{{ enabled ? '已启用' : '已停用' }}</span>
              </div>
              <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">左右两侧分别配置源与目标，中间可以切换方向与同步模式。</p>
            </div>
            <Button variant="ghost" size="icon" class="h-8 w-8 shrink-0" @click="emit('close')">
              <X class="h-4 w-4" />
            </Button>
          </div>

          <div class="flex-1 space-y-5 overflow-y-auto bg-[hsl(var(--muted))]/20 px-6 py-5">
            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div class="flex flex-wrap items-end gap-3">
                <div class="min-w-[220px] flex-1 space-y-1.5">
                  <label class="text-sm font-medium text-[hsl(var(--foreground))]">任务名称</label>
                  <Input v-model="name" placeholder="例如：电影库增量同步" />
                </div>
                <label class="mb-2 flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
                  <input v-model="enabled" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                  启用任务
                </label>
                <Button variant="outline" size="sm" class="mb-1.5" @click="showAdvanced = !showAdvanced">
                  {{ showAdvanced ? '收起高级' : '高级配置' }}
                </Button>
              </div>
            </section>

            <section class="space-y-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">同步方向</h3>
                  <p class="text-xs text-[hsl(var(--muted-foreground))]">左右两侧分别配置源与目标，中间可切换方向。</p>
                </div>
                <div class="inline-flex rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-0.5">
                  <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="mode === 'one_way' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="mode = 'one_way'">单向</button>
                  <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="mode === 'two_way' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="mode = 'two_way'">双向</button>
                </div>
              </div>

              <div class="grid grid-cols-1 items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
                <div class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                  <div class="flex items-start justify-between gap-2">
                    <div>
                      <div class="text-sm font-semibold text-[hsl(var(--foreground))]">源配置</div>
                      <div class="text-xs text-[hsl(var(--muted-foreground))]">同步读取的起点</div>
                    </div>
                    <span class="rounded-full bg-sky-500/15 px-2 py-0.5 text-[11px] font-medium text-sky-600">{{ endpointLabel(sourceType) }}</span>
                  </div>
                  <div class="inline-flex rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-0.5">
                    <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="sourceType === 'local' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="sourceType = 'local'">本地</button>
                    <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="sourceType === 'openlist' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="sourceType = 'openlist'">OpenList</button>
                  </div>
                  <div class="space-y-1.5">
                    <label class="text-sm font-medium text-[hsl(var(--foreground))]">源路径</label>
                    <div class="flex gap-2">
                      <Input v-model="sourcePath" placeholder="/" class="flex-1" />
                      <Button variant="outline" size="sm" @click="openPathPicker('source')"><FolderOpen class="mr-1 h-4 w-4" />浏览</Button>
                    </div>
                  </div>
                </div>

                <div class="flex flex-col items-center justify-center gap-2 py-2">
                  <div class="hidden h-10 w-px bg-[hsl(var(--border))] md:block" />
                  <Button variant="outline" size="sm" class="gap-1" @click="swapSides">
                    <ArrowLeftRight class="h-3.5 w-3.5" />切换方向
                  </Button>
                  <div class="hidden h-10 w-px bg-[hsl(var(--border))] md:block" />
                </div>

                <div class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                  <div class="flex items-start justify-between gap-2">
                    <div>
                      <div class="text-sm font-semibold text-[hsl(var(--foreground))]">目标配置</div>
                      <div class="text-xs text-[hsl(var(--muted-foreground))]">同步写入的位置</div>
                    </div>
                    <span class="rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium text-violet-600">{{ endpointLabel(targetType) }}</span>
                  </div>
                  <div class="inline-flex rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-0.5">
                    <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="targetType === 'local' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="targetType = 'local'">本地</button>
                    <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="targetType === 'openlist' ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]' : 'text-[hsl(var(--muted-foreground))]'" @click="targetType = 'openlist'">OpenList</button>
                  </div>
                  <div class="space-y-1.5">
                    <label class="text-sm font-medium text-[hsl(var(--foreground))]">目标路径</label>
                    <div class="flex gap-2">
                      <Input v-model="targetPath" placeholder="/" class="flex-1" />
                      <Button variant="outline" size="sm" @click="openPathPicker('target')"><FolderOpen class="mr-1 h-4 w-4" />浏览</Button>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div>
                <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">同步策略</h3>
                <p class="text-xs text-[hsl(var(--muted-foreground))]">常用选项放前面，高级参数收在下方。</p>
              </div>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
                  <input v-model="overwrite" type="checkbox" class="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))]" />
                  <span class="text-sm text-[hsl(var(--foreground))]"><span class="font-medium">覆盖同名文件</span><span class="mt-0.5 block text-xs text-[hsl(var(--muted-foreground))]">目标已存在同名文件时允许覆盖。</span></span>
                </label>
                <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
                  <input v-model="deleteExtras" type="checkbox" class="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))]" />
                  <span class="text-sm text-[hsl(var(--foreground))]"><span class="font-medium">删除多余文件</span><span class="mt-0.5 block text-xs text-[hsl(var(--muted-foreground))]">单向模式下清理目标侧源中不存在的文件。</span></span>
                </label>
                <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
                  <input v-model="forceRefresh" type="checkbox" class="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))]" />
                  <span class="text-sm text-[hsl(var(--foreground))]"><span class="font-medium">强制刷新</span><span class="mt-0.5 block text-xs text-[hsl(var(--muted-foreground))]">忽略目录缓存，重新拉取源/目标列表。</span></span>
                </label>
                <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
                  <input v-model="unzipZipAfterSync" type="checkbox" class="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))]" />
                  <span class="text-sm text-[hsl(var(--foreground))]"><span class="font-medium">同步 ZIP 后解压</span><span class="mt-0.5 block text-xs text-[hsl(var(--muted-foreground))]">解压到同目录并按前缀重命名，删除原 zip。</span></span>
                </label>
              </div>
              <div v-if="deleteExtras && mode === 'one_way'" class="max-w-xs space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">删除延时</label>
                <select v-model.number="deleteExtrasDelayMinutes" class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm">
                  <option v-for="m in DELETE_DELAY_OPTIONS" :key="m" :value="m">{{ m === 0 ? '立即删除（0 分钟）' : `${m} 分钟后删除` }}</option>
                </select>
              </div>
              <div v-if="showAdvanced" class="grid gap-3 border-t border-[hsl(var(--border))] pt-3 sm:grid-cols-3">
                <div class="space-y-1"><label class="text-xs text-[hsl(var(--muted-foreground))]">并发数</label><Input v-model.number="concurrency" type="number" min="1" max="32" /></div>
                <div class="space-y-1"><label class="text-xs text-[hsl(var(--muted-foreground))]">请求间隔（秒）</label><Input v-model.number="requestIntervalSeconds" type="number" min="0" max="5" step="0.1" /></div>
                <div class="space-y-1"><label class="text-xs text-[hsl(var(--muted-foreground))]">OpenList 批量复制大小</label><Input v-model.number="openlistCopyBatchSize" type="number" min="1" max="5000" /></div>
              </div>
            </section>

            <section class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div>
                <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">关联追剧任务</h3>
                <p class="text-xs text-[hsl(var(--muted-foreground))]">勾选后，对应追剧任务完成时可联动触发本同步。</p>
              </div>
              <div class="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2">
                <div v-if="!dramaTasks?.length" class="py-6 text-center text-xs text-[hsl(var(--muted-foreground))]">暂无追剧任务</div>
                <label v-for="dt in dramaTasks" :key="dt.task_uid" class="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-[hsl(var(--muted))]">
                  <input type="checkbox" :checked="dramaTaskUids.includes(dt.task_uid)" class="h-3.5 w-3.5 rounded" @change="toggleDramaTask(dt.task_uid)" />
                  <span class="truncate text-sm">{{ dt.taskname }}</span>
                </label>
              </div>
            </section>
          </div>

          <div class="flex flex-wrap items-center justify-between gap-3 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] px-6 py-4">
            <div class="text-sm text-[hsl(var(--muted-foreground))]">{{ summaryText }}</div>
            <div class="flex gap-2">
              <Button variant="outline" @click="emit('close')">取消</Button>
              <Button :disabled="!name.trim() || isPending" @click="handleSubmit">{{ isPending ? '保存中...' : isEditing ? '保存修改' : '创建任务' }}</Button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sync-modal-enter-active,
.sync-modal-leave-active {
  transition: opacity 0.2s ease;
}
.sync-modal-enter-active > div:last-child,
.sync-modal-leave-active > div:last-child {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.sync-modal-enter-from,
.sync-modal-leave-to {
  opacity: 0;
}
.sync-modal-enter-from > div:last-child,
.sync-modal-leave-to > div:last-child {
  transform: translateY(12px) scale(0.98);
  opacity: 0;
}
</style>
