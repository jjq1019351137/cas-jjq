<script setup lang="ts">
import { computed } from 'vue'
import type { TaskItem } from '@/types/tasks'
import type { ResolvedTaskAccount } from '@/utils/taskAccount'
import { getDriveTypeLabel } from '@/utils/driveType'
import { Play, Pencil, Trash2, Power, Link2, FolderClosed, History, ShieldAlert, Camera } from 'lucide-vue-next'

const props = defineProps<{
  task: TaskItem
  /** 任务生效的网盘账号（由页面基于账号列表解析，自动任务解析为默认账号） */
  account?: ResolvedTaskAccount
}>()

const emit = defineEmits<{
  'run-once': [task: TaskItem]
  edit: [task: TaskItem]
  delete: [task: TaskItem]
  'toggle-status': [task: TaskItem]
}>()

function truncate(str: string | undefined | null, len = 40) {
  if (!str) return '-'
  return str.length > len ? str.slice(0, len) + '...' : str
}

function formatTime(dateStr: string | undefined | null) {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    if (Number.isNaN(d.getTime())) return dateStr
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

/** 季集编号格式化：S01E08，季/集缺失时返回 '-' */
function formatEpisode(season?: number | null, episode?: number | null) {
  const sn = Number(season)
  const ep = Number(episode)
  if (!Number.isFinite(sn) || sn <= 0 || !Number.isFinite(ep) || ep <= 0) return '-'
  return `S${String(sn).padStart(2, '0')}E${String(ep).padStart(2, '0')}`
}

const statusLabel = computed(() => {
  if (!props.task.enabled) return '暂停'
  if (props.task.shareurl_ban) return '错误'
  return '运行中'
})

const statusTone = computed(() => {
  if (!props.task.enabled) return 'muted'
  if (props.task.shareurl_ban) return 'danger'
  return 'success'
})

const isEnded = computed(() => props.task.tmdb_is_ended === true || props.task.extra?.ended === true)

/** 除当前主链接外的其它分享链接数量（每次运行均会逐条转存） */
const backupLinkCount = computed(() => {
  const links = props.task.shareurls || []
  return Math.max(0, links.filter((x) => !x.is_active).length)
})

const banLabel = computed(() => {
  const ban = String(props.task.shareurl_ban || '')
  if (!ban) return ''
  return backupLinkCount.value ? `${ban}（共 ${backupLinkCount.value + 1} 条链接，已全部尝试）` : ban
})

const banTitle = computed(() => banLabel.value)

/** 剧集播出状态：完结 / 连载（仅 TMDB 剧集类型可判定） */
const airStatusLabel = computed(() => {
  const task = props.task
  if (task.tmdb_media_type !== 'tv') return isEnded.value ? '已完结' : ''
  if (isEnded.value) return '完结'
  if (task.tmdb_status) return '连载'
  return ''
})

/** 更新进度：对齐旧版「最新 / 落后 N 集 / 未知」语义，并补充进度条与季集明细 */
const progress = computed(() => {
  const task = props.task
  if (!(task.tmdb_id && task.tmdb_media_type === 'tv')) return null
  const p = task.drama_update_progress
  let tone: 'latest' | 'behind' | 'unknown' = 'unknown'
  let label = '未知'
  if (p?.available && p.is_latest) {
    tone = 'latest'
    label = '已是最新'
  } else if (p?.available && typeof p.behind_episodes === 'number') {
    const behind = p.behind_episodes
    tone = behind > 0 ? 'behind' : 'latest'
    label = behind > 0 ? `落后 ${behind} 集` : '已是最新'
  }
  const saved = Number(p?.saved_episode) || 0
  const latest = Number(p?.tmdb_episode) || 0
  return {
    tone,
    label,
    pill: tone === 'behind' ? 'warning' : tone === 'latest' ? 'success' : 'muted',
    savedText: formatEpisode(p?.saved_season, p?.saved_episode),
    latestText: formatEpisode(p?.tmdb_season, p?.tmdb_episode),
    hasBar: latest > 0,
    percent: latest > 0 ? Math.min(100, Math.max(0, Math.round((saved / latest) * 100))) : 0,
    snapshot: formatTime(p?.snapshot_captured_at),
    reason: p?.reason || '',
  }
})

/** 进度悬浮详情：已存 / 最新 / 快照时间 / 失败原因 */
const progressTitle = computed(() => {
  const p = progress.value
  if (!p) return ''
  const lines = [`已存：${p.savedText}`, `最新：${p.latestText}`, `快照：${p.snapshot}`]
  if (p.reason) lines.push(`原因：${p.reason}`)
  return lines.join('\n')
})

const EXEC_STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  skipped: '跳过',
  running: '运行中',
}

/** 最近一次执行：后端按 started_at 倒序返回，取首项 */
const lastExec = computed(() => {
  const execs = props.task.executions || []
  return execs.length ? execs[0] : null
})

const lastExecLabel = computed(() => {
  const exec = lastExec.value
  if (!exec) return '尚未执行'
  const status = String(exec.status || '').toLowerCase()
  return `${EXEC_STATUS_LABEL[status] || exec.status} · ${formatTime(exec.started_at)}`
})

const lastExecTone = computed(() => {
  const status = String(lastExec.value?.status || '').toLowerCase()
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'muted'
})

const lastExecTitle = computed(() => {
  const exec = lastExec.value
  if (!exec) return '暂无执行记录'
  const status = String(exec.status || '').toLowerCase()
  const lines = [`状态：${EXEC_STATUS_LABEL[status] || exec.status}`, `开始：${formatTime(exec.started_at)}`]
  if (exec.finished_at) lines.push(`结束：${formatTime(exec.finished_at)}`)
  if (exec.message) lines.push(`信息：${exec.message}`)
  return lines.join('\n')
})

const accountLabel = computed(() => {
  const acc = props.account
  if (!acc) return ''
  if (acc.accountName) return acc.isAuto ? `${acc.accountName}（自动）` : acc.accountName
  return '未识别账号'
})

const syncCount = computed(() => (props.task.sync_task_uids || []).length)
</script>

<template>
  <article
    class="glass-panel glass-panel--interactive drama-card"
    :class="{ 'drama-card--off': !task.enabled }"
  >
    <!-- 标题 + 状态 -->
    <header class="drama-card__head">
      <h3 class="drama-card__title" :title="task.taskname">{{ task.taskname }}</h3>
      <div class="drama-card__tags">
        <span v-if="airStatusLabel" class="pill" :class="isEnded ? 'pill--teal' : 'pill--info'">
          {{ airStatusLabel }}
        </span>
        <span class="pill" :class="`pill--${statusTone}`">{{ statusLabel }}</span>
      </div>
    </header>

    <!-- 更新进度 -->
    <div v-if="progress" class="glass-inset drama-card__progress" :title="progressTitle">
      <div class="drama-card__progress-top">
        <span class="pill" :class="`pill--${progress.pill}`">{{ progress.label }}</span>
        <span class="drama-card__episodes">
          <span class="drama-card__episode">{{ progress.savedText }}</span>
          <span class="drama-card__arrow">→</span>
          <span class="drama-card__episode drama-card__episode--target">{{ progress.latestText }}</span>
        </span>
      </div>
      <div v-if="progress.hasBar" class="drama-card__bar">
        <span
          class="drama-card__bar-fill"
          :class="`drama-card__bar-fill--${progress.tone}`"
          :style="{ width: progress.percent + '%' }"
        />
      </div>
      <div class="drama-card__progress-foot">
        <Camera class="h-3 w-3 shrink-0" />
        <span class="truncate">快照 {{ progress.snapshot }}</span>
        <span v-if="progress.reason" class="drama-card__reason truncate">{{ progress.reason }}</span>
      </div>
    </div>
    <div v-else class="glass-inset drama-card__progress drama-card__progress--empty">
      <span class="pill pill--muted">未关联剧集</span>
      <span class="drama-card__hint">关联 TMDB 剧集后可显示更新进度</span>
    </div>

    <!-- 网盘与账号 -->
    <div v-if="account" class="drama-card__account">
      <span class="pill pill--primary">{{ getDriveTypeLabel(account.driveType) }}</span>
      <span class="truncate" :title="accountLabel">{{ accountLabel }}</span>
      <span v-if="syncCount" class="pill pill--accent" :title="`已关联 ${syncCount} 个同步任务`">
        同步 ×{{ syncCount }}
      </span>
    </div>

    <!-- 来源与保存路径 -->
    <div class="drama-card__meta">
      <div class="drama-card__meta-row" :title="task.shareurl">
        <Link2 class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">{{ truncate(task.shareurl, 36) }}</span>
        <span v-if="backupLinkCount" class="pill pill--accent shrink-0" :title="`共 ${backupLinkCount + 1} 条链接，每次运行均会逐条转存`">+{{ backupLinkCount }} 源</span>
      </div>
      <div class="drama-card__meta-row" :title="task.savepath">
        <FolderClosed class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">{{ task.savepath || '-' }}</span>
      </div>
      <div v-if="task.shareurl_ban" class="drama-card__meta-row drama-card__meta-row--ban" :title="banTitle">
        <ShieldAlert class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">{{ banLabel }}</span>
      </div>
    </div>

    <!-- 最近执行 + 操作 -->
    <footer class="drama-card__foot">
      <span class="drama-card__exec" :class="`drama-card__exec--${lastExecTone}`" :title="lastExecTitle">
        <History class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">{{ lastExecLabel }}</span>
      </span>
      <div class="drama-card__actions">
        <!-- 对齐「运行一次」语义：带 allow_once 忽略按星期运行限制，点击即执行 -->
        <button type="button" class="icon-action" title="运行一次" @click="emit('run-once', task)">
          <Play class="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          class="icon-action"
          :class="{ 'icon-action--on': task.enabled }"
          :title="task.enabled ? '暂停' : '启用'"
          @click="emit('toggle-status', task)"
        >
          <Power class="h-3.5 w-3.5" />
        </button>
        <button type="button" class="icon-action" title="编辑" @click="emit('edit', task)">
          <Pencil class="h-3.5 w-3.5" />
        </button>
        <button type="button" class="icon-action icon-action--danger" title="删除" @click="emit('delete', task)">
          <Trash2 class="h-3.5 w-3.5" />
        </button>
      </div>
    </footer>
  </article>
</template>

<style scoped>
/* 卡片外观（毛玻璃底 / 高光 / 悬停浮起）由全局 .glass-panel 提供，此处只负责布局 */
.drama-card {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  padding: 0.95rem 1rem 0.8rem;
}

.drama-card--off {
  opacity: 0.72;
}

.drama-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.drama-card__title {
  flex: 1;
  min-width: 0;
  font-size: 0.9rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drama-card__tags {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-shrink: 0;
}

.drama-card__progress {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.55rem 0.65rem;
}

.drama-card__progress--empty {
  flex-direction: row;
  align-items: center;
  gap: 0.45rem;
}

.drama-card__progress-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.drama-card__episodes {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.7rem;
  font-variant-numeric: tabular-nums;
  color: hsl(var(--foreground) / 0.7);
}

.drama-card__episode {
  font-weight: 600;
}

.drama-card__episode--target {
  color: hsl(var(--foreground));
}

.drama-card__arrow {
  opacity: 0.6;
}

.drama-card__bar {
  position: relative;
  height: 5px;
  border-radius: 9999px;
  background: hsl(var(--border) / 0.8);
  overflow: hidden;
}

.drama-card__bar-fill {
  display: block;
  height: 100%;
  border-radius: 9999px;
  transition: width 0.4s cubic-bezier(0.32, 0.72, 0, 1);
}

.drama-card__bar-fill--latest {
  background: linear-gradient(90deg, hsl(145 63% 52%), hsl(160 70% 45%));
}

.drama-card__bar-fill--behind {
  background: linear-gradient(90deg, hsl(35 95% 58%), hsl(20 90% 55%));
}

.drama-card__bar-fill--unknown {
  background: hsl(var(--muted-foreground) / 0.5);
}

.drama-card__progress-foot {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
  font-size: 0.68rem;
  color: hsl(var(--foreground) / 0.62);
}

.drama-card__reason {
  color: hsl(35 90% 42%);
}

.drama-card__hint {
  font-size: 0.68rem;
  color: hsl(var(--foreground) / 0.62);
}

.drama-card__account {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
  font-size: 0.72rem;
  color: hsl(var(--foreground) / 0.72);
}

.drama-card__meta {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.72rem;
  color: hsl(var(--foreground) / 0.72);
}

.drama-card__meta-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.drama-card__meta-row--ban {
  color: hsl(0 72% 50%);
}

.drama-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid hsl(var(--border));
}

.drama-card__exec {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
  font-size: 0.7rem;
  color: hsl(var(--foreground) / 0.7);
}

.drama-card__exec--success {
  color: hsl(145 63% 38%);
}

.drama-card__exec--danger {
  color: hsl(0 72% 50%);
}

.drama-card__actions {
  display: flex;
  align-items: center;
  gap: 0.1rem;
  flex-shrink: 0;
}
</style>
