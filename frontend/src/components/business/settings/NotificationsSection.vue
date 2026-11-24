<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Bell, Send, Loader2, Check, Settings2, Eye, EyeOff, X } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useNotificationsQuery } from '@/hooks/queries/extensions'
import { useUpdateNotificationConfigMutation, useTestNotificationMutation } from '@/hooks/mutations/notifications'

const { toast } = useToast()

// ─── Queries & Mutations ───────────────────────────────────────────
const { data: notifData, isLoading } = useNotificationsQuery()
const updateMutation = useUpdateNotificationConfigMutation()
const testMutation = useTestNotificationMutation()

// ─── Local State ───────────────────────────────────────────────────
const configData = ref<Record<string, any>>({})
const editingChannel = ref<string | null>(null)
const testingChannel = ref<string | null>(null)
const revealedFields = ref<Record<string, boolean>>({})

// Sync remote data → local state
watch(
  () => notifData.value,
  (val) => {
    if (val) {
      const merged: Record<string, any> = { ...(val.default_config || {}), ...(val.config || {}) }
      // Deep-copy the channel-enabled map: the spread above only clones the top level,
      // so the nested map would otherwise stay a reference into the (readonly) query cache
      // and in-place writes to it would silently no-op.
      const rawEnabled = merged.__channel_enabled
      merged.__channel_enabled =
        rawEnabled && typeof rawEnabled === 'object' && !Array.isArray(rawEnabled) ? { ...rawEnabled } : {}
      configData.value = merged
    }
  },
  { immediate: true },
)

// ─── Channel Definitions ───────────────────────────────────────────
interface ChannelField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'switch' | 'textarea'
  placeholder?: string
  rows?: number
}

interface ChannelDef {
  id: string
  title: string
  required_keys: string[]
  fields: ChannelField[]
}

const channels: ChannelDef[] = [
  {
    id: 'wxpusher',
    title: 'WxPusher',
    required_keys: ['WXPUSHER_APP_TOKEN'],
    fields: [
      { key: 'WXPUSHER_APP_TOKEN', label: 'App Token', type: 'password' },
      { key: 'WXPUSHER_TOPIC_IDS', label: 'Topic IDs', type: 'text', placeholder: '多个用 ; 分隔' },
      { key: 'WXPUSHER_UIDS', label: 'UIDs', type: 'text', placeholder: '多个用 ; 分隔' },
    ],
  },
]

// ─── Computed Helpers ──────────────────────────────────────────────
function hasValue(value: any): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return !Number.isNaN(value) && value !== 0
  return String(value ?? '').trim() !== ''
}

function isChannelEnabled(channelId: string): boolean {
  const map = configData.value.__channel_enabled
  if (!map || typeof map !== 'object') return false
  return map[channelId] === true
}

function isChannelConfigured(channel: ChannelDef): boolean {
  return channel.required_keys.every((k) => hasValue(configData.value[k]))
}

function toggleChannel(channelId: string) {
  // Rebuild the map and the top-level object instead of mutating shared/readonly refs in place,
  // otherwise the toggled value never changes and the request payload stays the same.
  const map = { ...(configData.value.__channel_enabled || {}) }
  map[channelId] = !map[channelId]
  configData.value = { ...configData.value, __channel_enabled: map }
  saveConfig()
}

function openChannelEditor(channelId: string) {
  revealedFields.value = {}
  editingChannel.value = channelId
}

function closeChannelEditor() {
  editingChannel.value = null
  revealedFields.value = {}
}

const editingChannelDef = computed(() => channels.find((c) => c.id === editingChannel.value) || null)

function isRevealed(key: string): boolean {
  return revealedFields.value[key] === true
}

function toggleReveal(key: string) {
  revealedFields.value = { ...revealedFields.value, [key]: !revealedFields.value[key] }
}

function fieldInputType(field: ChannelField): string {
  if (field.type === 'password') return isRevealed(field.key) ? 'text' : 'password'
  return field.type
}

function getFieldValue(key: string): string {
  const val = configData.value[key]
  if (val === undefined || val === null) return ''
  return String(val)
}

function setFieldValue(key: string, value: string) {
  configData.value[key] = value
}

// ─── Actions ──────────────────────────────────────────────────────
async function saveConfig(): Promise<boolean> {
  try {
    // Send a plain deep clone so no reactive/readonly proxy leaks into the request payload
    const payload = JSON.parse(JSON.stringify(configData.value))
    await updateMutation.mutateAsync(payload)
    toast.success('配置已保存')
    return true
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '保存失败')
    return false
  }
}

async function saveChannelEditor() {
  const ok = await saveConfig()
  if (ok) closeChannelEditor()
}

async function testChannel(channelId: string) {
  testingChannel.value = channelId
  try {
    const result = await testMutation.mutateAsync({
      title: '测试通知',
      content: '这是一条来自 CloudSaver 的测试消息。',
      channels: [channelId],
    })
    const channelResult = result.results.find((r) => r.channel === channelId)
    if (channelResult?.ok) {
      toast.success(`${getChannelTitle(channelId)} 测试发送成功`)
    } else {
      toast.error(`测试失败: ${channelResult?.error || '未知错误'}`)
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '测试发送失败')
  } finally {
    testingChannel.value = null
  }
}

function getChannelTitle(id: string): string {
  return channels.find((c) => c.id === id)?.title || id
}

// Summary
const summary = computed(() => {
  const configured = channels.filter((c) => isChannelConfigured(c)).length
  const enabled = channels.filter((c) => isChannelEnabled(c.id)).length
  return { total: channels.length, configured, enabled }
})
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-5 flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">🔔 通知配置</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
          管理消息通知渠道 ·
          <span class="text-[hsl(var(--foreground))]">{{ summary.enabled }}</span> 已启用 /
          <span class="text-[hsl(var(--foreground))]">{{ summary.configured }}</span> 已配置 /
          {{ summary.total }} 个渠道
        </p>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <Skeleton v-for="i in 6" :key="i" class="h-24 w-full rounded-lg" />
    </div>

    <!-- Channel Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="channel in channels"
        :key="channel.id"
        class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden transition-shadow hover:shadow-sm"
      >
        <!-- Card Header -->
        <div class="flex items-center gap-3 px-4 py-3">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--muted))]">
            <Bell class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </div>
          <div class="flex-1 min-w-0">
            <span class="text-sm font-medium text-[hsl(var(--foreground))]">{{ channel.title }}</span>
            <div class="flex items-center gap-1.5 mt-0.5">
              <Badge
                :variant="isChannelConfigured(channel) ? 'default' : 'secondary'"
                class="text-[10px] px-1.5 py-0"
              >
                {{ isChannelConfigured(channel) ? '已配置' : '未配置' }}
              </Badge>
              <Badge
                v-if="isChannelEnabled(channel.id)"
                variant="default"
                class="text-[10px] px-1.5 py-0 bg-green-600"
              >
                已启用
              </Badge>
            </div>
          </div>
          <!-- Toggle -->
          <button
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors"
            :class="isChannelEnabled(channel.id) ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
            role="switch"
            :aria-checked="isChannelEnabled(channel.id)"
            @click.stop="toggleChannel(channel.id)"
          >
            <span
              class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform"
              :class="isChannelEnabled(channel.id) ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
        </div>

        <!-- Action Bar -->
        <div class="flex items-center gap-1 border-t border-[hsl(var(--border))] px-3 py-1.5 bg-[hsl(var(--muted))]/30">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 text-xs px-2"
            @click="openChannelEditor(channel.id)"
          >
            <Settings2 class="mr-1 h-3 w-3" />
            配置
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 text-xs px-2"
            :disabled="!isChannelConfigured(channel) || testingChannel === channel.id"
            @click="testChannel(channel.id)"
          >
            <Loader2 v-if="testingChannel === channel.id" class="mr-1 h-3 w-3 animate-spin" />
            <Send v-else class="mr-1 h-3 w-3" />
            测试
          </Button>
        </div>
      </div>
    </div>

    <!-- Channel Config Modal -->
    <Transition name="fade">
      <div
        v-if="editingChannelDef"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        @click.self="closeChannelEditor"
      >
        <div class="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
            <div class="flex items-center gap-2.5">
              <div class="flex h-8 w-8 items-center justify-center rounded-md bg-[hsl(var(--muted))]">
                <Bell class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
              </div>
              <div>
                <div class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ editingChannelDef.title }}</div>
                <div class="text-xs text-[hsl(var(--muted-foreground))]">渠道配置</div>
              </div>
            </div>
            <Button variant="ghost" size="sm" class="h-7 w-7 p-0" @click="closeChannelEditor"><X class="h-4 w-4" /></Button>
          </div>

          <!-- Body -->
          <div class="flex-1 space-y-3.5 overflow-y-auto px-5 py-4">
            <div v-for="field in editingChannelDef.fields" :key="field.key" class="space-y-1.5">
              <label class="text-xs font-medium text-[hsl(var(--muted-foreground))]">{{ field.label }}</label>
              <!-- Switch -->
              <div v-if="field.type === 'switch'" class="flex items-center">
                <button
                  class="relative inline-flex h-5 w-9 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors"
                  :class="getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
                  role="switch"
                  @click="setFieldValue(field.key, getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'false' : 'true')"
                >
                  <span
                    class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform"
                    :class="getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'translate-x-4' : 'translate-x-0'"
                  />
                </button>
              </div>
              <!-- Textarea -->
              <textarea
                v-else-if="field.type === 'textarea'"
                :value="getFieldValue(field.key)"
                :placeholder="field.placeholder"
                :rows="field.rows || 3"
                class="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                @input="setFieldValue(field.key, ($event.target as HTMLTextAreaElement).value)"
              />
              <!-- Input (with password reveal) -->
              <div v-else class="relative">
                <Input
                  :type="fieldInputType(field)"
                  :model-value="getFieldValue(field.key)"
                  :placeholder="field.placeholder"
                  class="h-9 text-sm"
                  :class="field.type === 'password' ? 'pr-9' : ''"
                  @update:model-value="setFieldValue(field.key, $event)"
                />
                <button
                  v-if="field.type === 'password'"
                  type="button"
                  class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  :aria-label="isRevealed(field.key) ? '隐藏' : '显示'"
                  @click="toggleReveal(field.key)"
                >
                  <EyeOff v-if="isRevealed(field.key)" class="h-4 w-4" />
                  <Eye v-else class="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex justify-end gap-2 border-t border-[hsl(var(--border))] px-5 py-3.5">
            <Button variant="outline" size="sm" @click="closeChannelEditor">取消</Button>
            <Button size="sm" :disabled="updateMutation.isPending.value" @click="saveChannelEditor">
              <Loader2 v-if="updateMutation.isPending.value" class="mr-1 h-3.5 w-3.5 animate-spin" />
              <Check v-else class="mr-1 h-3.5 w-3.5" />
              保存
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
