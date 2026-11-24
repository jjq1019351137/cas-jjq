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

// ─── Computed Helpers