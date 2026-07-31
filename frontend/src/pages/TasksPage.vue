<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import {
  Plus, Search, Film, Play, Wrench, Square, Camera,
  HardDrive, User, HelpCircle, X, CalendarCheck, Save,
} from 'lucide-vue-next'
import TaskCard from '@/components/business/drama/TaskCard.vue'
import DramaTaskLauncher from '@/components/business/drama/DramaTaskLauncher.vue'
import { useTasksQuery, useTaskSchedulerSettingQuery } from '@/hooks/queries/tasks'
import {
  useDeleteTaskMutation,
  useSetTaskStatusMutation,
  useRepairBannedMutation,
  useStopCompletedMutation,
  useSyncSnapshotsMutation,
  useUpdateSchedulerMutation,
  useRunAllTasksMutation,
} from '@/hooks/mutations/tasks'
import { useToast } from '@/composables/useToast'
import { useDramaTaskLauncher } from '@/composables/useDramaTaskLauncher'
import type { TaskItem } from '@/types/tasks'
import { useDriveAccountsQuery } from '@/hooks/queries/extensions'
import { getDriveTypeLabel } from '@/utils/driveType'
import { resolveTaskAccount, type ResolvedTaskAccount } from '@/utils/taskAccount'

const { toast } = useToast()
const launcher = useDramaTaskLauncher()

const searchQuery = ref('')
const selectedDriveType = ref('')
const selectedAccountName = ref('')

// Delete confirm state
const deleteDialogOpen = ref(false)
const taskToDelete = ref<TaskItem | null>(null)

// Queries
const { data: tasks, isLoading } = useTasksQuery()
const { data: schedulerData } = useTaskSchedulerSettingQuery()
const { data: driveAccounts } = useDriveAccountsQuery()

// Mutations
const deleteMutation = useDeleteTaskMutation()
const statusMutation = useSetTaskStatusMutation()
const repairMutation = useRepairBannedMutation()
const stopMutation = useStopCompletedMutation()
const syncMutation = useSyncSnapshotsMutation()
const schedulerMutation = useUpdateSchedulerMutation()
const runAllMutation = useRunAllTasksMutation()

// Scheduler form
const schedulerForm = reactive({
  enabled: false,
  crontab: '',
  timezone: 'Asia/Shanghai',
})

watch(
  () => schedulerData.value,
  (val) => {
    if (val) {
      schedulerForm.enabled = val.enabled
      schedulerForm.crontab = val.crontab || ''
      schedulerForm.timezone = val.timezone || 'Asia/Shanghai'
    }
  },
  { immediate: true },
)

// --- Task categorization: 进行中 > 已完结 > 已禁用 ---
type TaskCategory = 'active' | 'ended' | 'disabled'

function getTaskCategory(t: TaskItem): TaskCategory {
  if (!t.enabled) return 'disabled'
  if (t.tmdb_is_ended === true || t.extra?.ended === true) return 'ended'
  return 'active'
}

const CATEGORY_ORDER: Record<TaskCategory, number> = { active: 0, ended: 1, disabled: 2 }
const CATEGORY_LABELS: Record<TaskCategory, string> = { active: '进行中', ended: '已完结', disabled: '已禁用' }

const taskAccountMap = computed(() => {
  const map = new Map<number, ResolvedTaskAccount>()
  for (const task of tasks.value || []) {
    map.set(task.id, resolveTaskAccount(task, driveAccounts.value))
  }
  return map
})

function getTaskAccount(task: TaskItem): ResolvedTaskAccount {
  return taskAccountMap.value.get(task.id) || resolveTaskAccount(task, driveAccounts.value)
}

const UNASSIGNED_ACCOUNT = '__NONE__'

const driveTypeOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const task of tasks.value || []) {
    const { driveType } = getTaskAccount(task)
    if (!driveType) continue
    counts.set(driveType, (counts.get(driveType) || 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((a, b) => getDriveTypeLabel(a[0]).localeCompare(getDriveTypeLabel(b[0]), 'zh-CN'))
    .map(([code, count]) => ({ code, count }))
})

const accountOptions = computed(() => {
  const counts = new Map<string, { count: number; driveType: string }>()
  let unassigned = 0
  for (const task of tasks.value || []) {
    const resolved = getTaskAccount(task)
    if (selectedDriveType.value && resolved.driveType !== selectedDriveType.value) continue
    if (!resolved.accountName) {
      unassigned += 1
      continue
    }
    const entry = counts.get(resolved.accountName) || { count: 0, driveType: resolved.driveType }
    entry.count += 1
    counts.set(resolved.accountName, entry)
  }
  const options = Array.from(counts.entries())
    .sort((a, b) => a[0].localeCompare(b[0], 'zh-CN'))
    .map(([name, meta]) => ({
      value: name,
      label: selectedDriveType.value || !meta.driveType ? name : `${name}（${getDriveTypeLabel(meta.driveType)}）`,
      count: meta.count,
    }))
  if (unassigned > 0) {
    options.push({ value: UNASSIGNED_ACCOUNT, label: '未识别账号', count: unassigned })
  }
  return options
})

watch(accountOptions, (options) => {
  if (!selectedAccountName.value) return
  if (!options.some((opt) => opt.value === selectedAccountName.value)) {
    selectedAccountName.value = ''
  }
})

const hasActiveFilters = computed(() => Boolean(searchQuery.value.trim() || selectedDriveType.value || selectedAccountName.value))

const filteredTasks = computed(() => {
  const list = tasks.value || []
  const q = searchQuery.value.trim().toLowerCase()
  const filtered = list.filter((t) => {
    const matchesKeyword = !q || t.taskname.toLowerCase().includes(q) || t.shareurl.toLowerCase().includes(q) || t.savepath.toLowerCase().includes(q)
    const resolved = getTaskAccount(t)
    const matchesDriveType = !selectedDriveType.value || resolved.driveType === selectedDriveType.value
    const matchesAccount = !selectedAccountName.value
      || (selectedAccountName.value === UNASSIGNED_ACCOUNT ? !resolved.accountName : resolved.accountName === selectedAccountName.value)
    return matchesKeyword && matchesDriveType && matchesAccount
  })
  return filtered.sort((a, b) => CATEGORY_ORDER[getTaskCategory(a)] - CATEGORY_ORDER[getTaskCategory(b)])
})

function clearFilters() {
  searchQuery.value = ''
  selectedDriveType.value = ''
  selectedAccountName.value = ''
}

// Grouped tasks with category headers for display
const groupedTasks = computed(() => {
  const groups: { category: TaskCategory; label: string; tasks: TaskItem[] }[] = []
  for (const cat of ['active', 'ended', 'disabled'] as TaskCategory[]) {
    const items = filteredTasks.value.filter((t) => getTaskCategory(t) === cat)
    if (items.length) groups.push({ category: cat, label: CATEGORY_LABELS[cat], tasks: items })
  }
  return groups
})

// Category counts for stat tiles (over all tasks, not filtered)
const categoryCounts = computed(() => {
  const list = tasks.value || []
  return {
    active: list.filter((t) => getTaskCategory(t) === 'active').length,
    ended: list.filter((t) => getTaskCategory(t) === 'ended').length,
    disabled: list.filter((t) => getTaskCategory(t) === 'disabled').length,
  }
})

// --- Batch actions ---
function handleRunAll() {
  launcher.streamLogTitle.value = '执行全部：日志'
  launcher.streamLogUrl.value = '/api/tasks/run-all/stream'
  launcher.streamLogMethod.value = 'POST'
  launcher.streamLogBody.value = null
  launcher.showStreamLog.value = true
}

function handleRepairBanned() {
  repairMutation.mutate(undefined, {
    onSuccess: () => toast.success('修复失效完成'),
    onError: (e: any) => toast.error(e?.message || '修复失效失败'),
  })
}

function handleStopCompleted() {
  stopMutation.mutate(undefined, {
    onSuccess: () => toast.success('停止完结任务完成'),
    onError: (e: any) => toast.error(e?.message || '停止完结任务失败'),
  })
}

function handleSyncSnapshots() {
  syncMutation.mutate(undefined, {
    onSuccess: () => toast.success('同步快照完成'),
    onError: (e: any) => toast.error(e?.message || '同步快照失败'),
  })
}

// --- Scheduler ---
function saveScheduler() {
  schedulerMutation.mutate(
    {
      enabled: schedulerForm.enabled,
      crontab: schedulerForm.crontab,
      timezone: schedulerForm.timezone,
    },
    {
      onSuccess: () => toast.success('调度配置已保存'),
      onError: (e: any) => toast.error(e?.message || '保存调度配置失败'),
    },
  )
}

// --- Per-task actions ---
function buildRunOncePayloadFromTask(task: TaskItem) {
  const shareurls = (task.shareurls || [])
    .map((x) => String(x.url || '').trim())
    .filter(Boolean)
  return {
    // 带上 task_uid 后端才能关联到真实任务行：
    // 失败时写入 shareurl_ban 并触发自动修复，成功时触发115自动换链
    task_uid: String(task.task_uid || '').trim(),
    task_type: task.task_type,
    taskname: String(task.taskname || '').trim(),
    shareurl: String(task.shareurl || '').trim(),
    shareurls,
    savepath: String(task.savepath || '').trim(),
    sync_task_uids: [...(task.sync_task_uids || [])],
    pattern: task.pattern ?? null,
    replace: task.replace ?? null,
    enddate: task.enddate ?? null,
    ignore_extension: Boolean(task.ignore_extension),
    sort_index: task.sort_index ?? null,
    startfid: task.startfid ?? null,
    account_name: task.account_name ?? null,
    update_subdir: task.update_subdir ?? null,
    tmdb_id: task.tmdb_id ?? null,
    tmdb_media_type: task.tmdb_media_type ?? null,
    enabled: Boolean(task.enabled),
    addition: { ...(task.addition || {}) },
    extra: {
      ...(task.extra || {}),
      allow_once: true,
      runweek: [],
    },
  }
}

function handleRunOnceTask(task: TaskItem) {
  launcher.streamLogTitle.value = `运行一次: ${task.taskname}`
  launcher.streamLogUrl.value = '/api/tasks/run/stream'
  launcher.streamLogMethod.value = 'POST'
  launcher.streamLogBody.value = buildRunOncePayloadFromTask(task)
  launcher.showStreamLog.value = true
}

function handleEdit(task: TaskItem) {
  launcher.openEdit(task)
}

function handleDeleteConfirm(task: TaskItem) {
  taskToDelete.value = task
  deleteDialogOpen.value = true
}

function handleDeleteExecute() {
  if (!taskToDelete.value) return
  deleteMutation.mutate(taskToDelete.value.id, {
    onSuccess: () => {
      toast.success('任务已删除')
      deleteDialogOpen.value = false
      taskToDelete.value = null
    },
    onError: (e: any) => toast.error(e?.message || '删除失败'),
  })
}

function handleToggleStatus(task: TaskItem) {
  statusMutation.mutate(
    { taskId: task.id, enabled: !task.enabled },
    {
      onSuccess: () => toast.success(task.enabled ? '已暂停' : '已启用'),
      onError: (e: any) => toast.error(e?.message || '操作失败'),
    },
  )
}

</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <header class="tasks-header">
      <h1 class="tasks-header__title">🎬 追剧任务</h1>
      <p class="tasks-header__subtitle">管理追剧任务、全局调度与批量操作</p>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-6">
      <!-- Stat tiles -->
      <div class="mb-4 grid grid-cols-3 gap-3">
        <div class="glass-panel glass-panel--interactive stat-tile">
          <div class="stat-tile__top">
            <span class="stat-tile__dot stat-tile__dot--active" />
            <span class="stat-tile__label">进行中</span>
          </div>
          <div class="stat-tile__value">{{ categoryCounts.active }}</div>
        </div>
        <div class="glass-panel glass-panel--interactive stat-tile">
          <div class="stat-tile__top">
            <span class="stat-tile__dot stat-tile__dot--ended" />
            <span class="stat-tile__label">已完结</span>
          </div>
          <div class="stat-tile__value">{{ categoryCounts.ended }}</div>
        </div>
        <div class="glass-panel glass-panel--interactive stat-tile">
          <div class="stat-tile__top">
            <span class="stat-tile__dot stat-tile__dot--disabled" />
            <span class="stat-tile__label">已禁用</span>
          </div>
          <div class="stat-tile__value">{{ categoryCounts.disabled }}</div>
        </div>
      </div>

      <!-- Global Scheduler Config -->
      <div class="glass-panel mb-4 px-4 py-3.5">
        <div class="panel-title mb-3">
          <CalendarCheck class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          全局调度配置
        </div>
        <div v-if="!schedulerData" class="flex flex-wrap gap-3">
          <Skeleton class="h-9 w-40 rounded-full" />
          <Skeleton class="h-9 w-40 rounded-full" />
        </div>
        <div v-else class="flex flex-wrap items-center gap-x-5 gap-y-3">
          <label class="flex cursor-pointer items-center gap-2 text-sm text-[hsl(var(--foreground))]">
            <ToggleSwitch v-model="schedulerForm.enabled" />
            启用调度
          </label>
          <div class="flex items-center gap-2">
            <span class="flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))]">
              Crontab
              <a
                href="http://tool.lu/crontab"
                target="_blank"
                rel="noopener noreferrer"
                title="crontab 表达式在线工具（新页面打开）"
                class="transition-colors hover:text-[hsl(var(--primary))]"
              >
                <HelpCircle class="h-3.5 w-3.5" />
              </a>
            </span>
            <Input v-model="schedulerForm.crontab" placeholder="0 */6 * * *" class="h-9 w-40 rounded-full bg-[hsl(var(--background))]" />
          </div>
          <div class="flex items-center gap-2">
            <span class="text-sm text-[hsl(var(--muted-foreground))]">时区</span>
            <Input v-model="schedulerForm.timezone" placeholder="Asia/Shanghai" class="h-9 w-40 rounded-full bg-[hsl(var(--background))]" />
          </div>
          <Button size="sm" class="rounded-full" :disabled="schedulerMutation.isPending.value" @click="saveScheduler">
            <Save class="mr-1 h-4 w-4" />
            {{ schedulerMutation.isPending.value ? '保存中...' : '保存' }}
          </Button>
        </div>
      </div>

      <!-- Toolbar: search + batch actions + new task -->
      <div class="glass-panel mb-4 flex flex-wrap items-center gap-2 px-4 py-3">
        <div class="relative min-w-[11rem] flex-1 sm:max-w-xs">
          <Search class="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <Input
            v-model="searchQuery"
            placeholder="搜索任务..."
            class="h-9 rounded-full border-[hsl(var(--border))] bg-[hsl(var(--background))] pl-10"
          />
        </div>
        <span class="hidden h-5 w-px bg-[hsl(var(--border))] sm:block" />
        <Button size="sm" variant="outline" class="rounded-full" :disabled="runAllMutation.isPending.value" @click="handleRunAll">
          <Play class="mr-1 h-3.5 w-3.5" /> 执行全部
        </Button>
        <Button size="sm" variant="outline" class="rounded-full" :disabled="repairMutation.isPending.value" @click="handleRepairBanned">
          <Wrench class="mr-1 h-3.5 w-3.5" /> 修复失效
        </Button>
        <Button size="sm" variant="outline" class="rounded-full" :disabled="stopMutation.isPending.value" @click="handleStopCompleted">
          <Square class="mr-1 h-3.5 w-3.5" /> 停止完结
        </Button>
        <Button size="sm" variant="outline" class="rounded-full" :disabled="syncMutation.isPending.value" @click="handleSyncSnapshots">
          <Camera class="mr-1 h-3.5 w-3.5" /> 同步快照
        </Button>
        <div class="ml-auto flex items-center gap-2">
          <Button v-if="hasActiveFilters" size="sm" variant="ghost" class="rounded-full" @click="clearFilters">
            清空筛选
          </Button>
          <Button size="sm" class="rounded-full" @click="launcher.openCreate()">
            <Plus class="mr-1 h-4 w-4" />
            新建任务
          </Button>
        </div>
      </div>

      <!-- Global filters -->
      <div class="glass-panel mb-5 px-4 py-3">
        <!-- 网盘类型 -->
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="mr-1.5 flex w-14 flex-shrink-0 items-center gap-1 text-xs font-medium text-[hsl(var(--muted-foreground))]">
            <HardDrive class="h-3.5 w-3.5" />
            网盘
          </span>
          <button
            type="button"
            class="filter-pill"
            :class="{ 'filter-pill--active': !selectedDriveType }"
            @click="selectedDriveType = ''"
          >
            全部
          </button>
          <button
            v-for="option in driveTypeOptions"
            :key="option.code"
            type="button"
            class="filter-pill"
            :class="{ 'filter-pill--active': selectedDriveType === option.code }"
            @click="selectedDriveType = selectedDriveType === option.code ? '' : option.code"
          >
            {{ getDriveTypeLabel(option.code) }}
            <span class="filter-pill__count">{{ option.count }}</span>
          </button>
        </div>

        <div class="hairline my-2.5" />

        <!-- 网盘账号 -->
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="mr-1.5 flex w-14 flex-shrink-0 items-center gap-1 text-xs font-medium text-[hsl(var(--muted-foreground))]">
            <User class="h-3.5 w-3.5" />
            账号
          </span>
          <button
            type="button"
            class="filter-pill"
            :class="{ 'filter-pill--active': !selectedAccountName }"
            @click="selectedAccountName = ''"
          >
            全部
          </button>
          <button
            v-for="account in accountOptions"
            :key="account.value"
            type="button"
            class="filter-pill"
            :class="{ 'filter-pill--active': selectedAccountName === account.value }"
            @click="selectedAccountName = selectedAccountName === account.value ? '' : account.value"
          >
            {{ account.label }}
            <span class="filter-pill__count">{{ account.count }}</span>
          </button>
        </div>

        <!-- 已选条件摘要 + 快速清空 -->
        <template v-if="selectedDriveType || selectedAccountName">
          <div class="hairline mt-2.5" />
          <div class="mt-2.5 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
            <span>
              已筛选：{{ [selectedDriveType ? getDriveTypeLabel(selectedDriveType) : '', selectedAccountName === UNASSIGNED_ACCOUNT ? '未识别账号' : selectedAccountName].filter(Boolean).join(' / ') }}
            </span>
            <button
              type="button"
              class="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
              @click="selectedDriveType = ''; selectedAccountName = ''"
            >
              <X class="h-3 w-3" />
              清除
            </button>
          </div>
        </template>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton v-for="i in 6" :key="i" class="h-52 rounded-[1.15rem]" />
      </div>

      <!-- Empty state -->
      <div
        v-else-if="filteredTasks.length === 0 && !searchQuery"
        class="glass-panel flex flex-col items-center justify-center px-6 py-16"
      >
        <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-[hsl(var(--muted))]/70">
          <Film class="h-8 w-8 text-[hsl(var(--muted-foreground))]" />
        </div>
        <h3 class="mb-1 text-lg font-semibold tracking-tight text-[hsl(var(--foreground))]">还没有追剧任务</h3>
        <p class="mb-4 text-sm text-[hsl(var(--muted-foreground))]">创建第一个任务，开始自动追剧吧</p>
        <Button size="sm" class="rounded-full" @click="launcher.openCreate()">
          <Plus class="mr-1 h-4 w-4" />
          创建任务
        </Button>
      </div>

      <!-- No results -->
      <div
        v-else-if="filteredTasks.length === 0 && hasActiveFilters"
        class="glass-panel flex flex-col items-center justify-center gap-3 px-6 py-16"
      >
        <p class="text-sm text-[hsl(var(--muted-foreground))]">当前筛选条件下没有匹配的任务</p>
        <Button size="sm" variant="outline" class="rounded-full" @click="clearFilters">清空筛选</Button>
      </div>

      <!-- Task grid grouped by category -->
      <div v-else class="space-y-6">
        <div v-for="group in groupedTasks" :key="group.category">
          <div class="group-head">
            <span class="stat-tile__dot" :class="`stat-tile__dot--${group.category}`" />
            <h2 class="group-head__label">{{ group.label }}</h2>
            <span class="filter-pill__count">{{ group.tasks.length }}</span>
          </div>
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <TaskCard
              v-for="task in group.tasks"
              :key="task.id"
              :task="task"
              :account="getTaskAccount(task)"
              @run-once="handleRunOnceTask"
              @edit="handleEdit"
              @delete="handleDeleteConfirm"
              @toggle-status="handleToggleStatus"
            />
          </div>
        </div>
      </div>
    </div>

    <DramaTaskLauncher :launcher="launcher" />

    <!-- Delete Confirm Dialog -->
    <AlertDialog :open="deleteDialogOpen" @update:open="deleteDialogOpen = $event">
      <AlertDialogContent
        class="rounded-[1.15rem] border-[hsl(var(--border))] bg-[hsl(var(--background))] sm:rounded-[1.15rem]"
      >
        <AlertDialogHeader>
          <AlertDialogTitle>确认删除</AlertDialogTitle>
          <AlertDialogDescription>
            确定要删除任务「{{ taskToDelete?.taskname }}」吗？此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel class="rounded-full" @click="deleteDialogOpen = false">取消</AlertDialogCancel>
          <AlertDialogAction class="rounded-full bg-red-600 hover:bg-red-700" @click="handleDeleteExecute">
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>

<style scoped>
/* 页头：半透明磨砂条，与内容区滚动内容形成层次 */
.tasks-header {
  padding: 1.25rem 1.5rem 1rem;
  border-bottom: 1px solid hsl(var(--border) / 0.6);
  background: hsl(var(--background) / 0.7);
  backdrop-filter: blur(20px) saturate(1.6);
  -webkit-backdrop-filter: blur(20px) saturate(1.6);
}

.tasks-header__title {
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: hsl(var(--foreground));
}

.tasks-header__subtitle {
  margin-top: 0.15rem;
  font-size: 0.8rem;
  color: hsl(var(--muted-foreground));
}

/* 统计瓷砖 */
.stat-tile {
  padding: 0.85rem 1rem;
}

.stat-tile__top {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.stat-tile__label {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.stat-tile__value {
  margin-top: 0.3rem;
  font-size: 1.5rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: hsl(var(--foreground));
}

/* 分类色点（瓷砖与分组标题共用） */
.stat-tile__dot {
  height: 0.5rem;
  width: 0.5rem;
  flex-shrink: 0;
  border-radius: 9999px;
  background: hsl(var(--muted-foreground));
}

.stat-tile__dot--active {
  background: linear-gradient(135deg, hsl(145 70% 52%), hsl(160 70% 42%));
  box-shadow: 0 0 0 3px hsl(145 70% 52% / 0.16);
}

.stat-tile__dot--ended {
  background: linear-gradient(135deg, hsl(190 70% 52%), hsl(210 80% 55%));
  box-shadow: 0 0 0 3px hsl(200 75% 52% / 0.16);
}

.stat-tile__dot--disabled {
  background: linear-gradient(135deg, hsl(215 16% 62%), hsl(215 16% 48%));
  box-shadow: 0 0 0 3px hsl(215 16% 55% / 0.16);
}

/* 分组标题行 */
.group-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.75rem;
  padding-left: 0.15rem;
}

.group-head__label {
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
}
</style>
