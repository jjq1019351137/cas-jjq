import { computed, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useTasksQuery } from '@/hooks/queries/tasks'
import type { DramaTaskPreset } from '@/types/dramaLauncher'
import type { TaskItem } from '@/types/tasks'

export function useDramaTaskLauncher() {
  const { data: tasks } = useTasksQuery()
  const queryClient = useQueryClient()

  const sheetOpen = ref(false)
  const editingTask = ref<TaskItem | undefined>(undefined)
  const presetTmdb = ref<DramaTaskPreset | null>(null)

  const showStreamLog = ref(false)
  const streamLogUrl = ref('')
  const streamLogTitle = ref('执行日志')
  const streamLogMethod = ref<'GET' | 'POST'>('GET')
  const streamLogBody = ref<Record<string, any> | null>(null)

  // 执行过程可能改动任务本身（自动修复换链、115自动换链、进度快照），
  // 流结束或弹窗关闭都要让任务列表失效，否则卡片仍是旧链接，再次运行会用旧数据构造 payload
  function invalidateTasks() {
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }

  function handleStreamDone() {
    invalidateTasks()
  }

  watch(showStreamLog, (visible, previous) => {
    if (previous && !visible) invalidateTasks()
  })

  function findExistingTask(tmdbId: number, mediaType: string): TaskItem | undefined {
    if (!tmdbId) return undefined
    return (tasks.value || []).find(
      (t) =>
        t.task_type === 'drama' &&
        Number(t.tmdb_id) === tmdbId &&
        String(t.tmdb_media_type || '').toLowerCase() === String(mediaType || '').toLowerCase(),
    )
  }

  const trackedKeys = computed(() => {
    const keys = new Set<string>()
    for (const t of tasks.value || []) {
      if (t.task_type !== 'drama') continue
      const id = Number(t.tmdb_id) || 0
      if (id <= 0) continue
      const mediaType = String(t.tmdb_media_type || '').toLowerCase()
      if (!mediaType) continue
      keys.add(`${mediaType}:${id}`)
    }
    return keys
  })

  function openCreate(preset?: DramaTaskPreset | null) {
    editingTask.value = undefined
    presetTmdb.value = preset || null
    sheetOpen.value = true
  }

  function openEdit(task: TaskItem) {
    presetTmdb.value = null
    editingTask.value = task
    sheetOpen.value = true
  }

  function openFromPreset(preset: DramaTaskPreset) {
    const tmdbId = Number(preset.tmdb_id) || 0
    if (tmdbId > 0) {
      const existing = findExistingTask(tmdbId, preset.tmdb_media_type)
      if (existing) {
        openEdit(existing)
        return
      }
    }
    openCreate(preset)
  }

  function close() {
    sheetOpen.value = false
    editingTask.value = undefined
    presetTmdb.value = null
  }

  function handleRunOnce(payload: Record<string, any>) {
    streamLogTitle.value = `运行一次：${payload.taskname || '任务'}`
    streamLogUrl.value = '/api/tasks/run/stream'
    streamLogMethod.value = 'POST'
    streamLogBody.value = payload
    showStreamLog.value = true
    close()
  }

  return {
    sheetOpen,
    editingTask,
    presetTmdb,
    showStreamLog,
    streamLogUrl,
    streamLogTitle,
    streamLogMethod,
    streamLogBody,
    trackedKeys,
    findExistingTask,
    openCreate,
    openEdit,
    openFromPreset,
    close,
    handleRunOnce,
    handleStreamDone,
  }
}
