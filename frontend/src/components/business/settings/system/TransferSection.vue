<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Button } from '@/components/ui/button'
import { SettingCard } from '@/components/ui/setting-card'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Save, Loader2, ArrowLeftRight } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useSaveRuleConfigQuery } from '@/hooks/queries/settings'
import { patchSaveRuleConfig } from '@/api/systemSettings'

const { toast } = useToast()
const queryClient = useQueryClient()

const { data: saveRuleData, isLoading } = useSaveRuleConfigQuery()
const saving = ref(false)

const form = reactive({
  skipTransferred: false,
})

watch(saveRuleData, (d) => {
  if (d) form.skipTransferred = Boolean(d.enable_skip_transferred_history)
}, { immediate: true })

async function save() {
  saving.value = true
  try {
    await patchSaveRuleConfig({ enable_skip_transferred_history: form.skipTransferred })
    queryClient.invalidateQueries({ queryKey: ['system-settings', 'save-rules'] })
    toast.success('转存设置已保存')
  } catch (err: any) {
    toast.error(err?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <SettingCard title="🔀 转存设置" description="追剧转存相关的全局行为配置" :icon="ArrowLeftRight">
      <div v-if="isLoading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
      </div>

      <template v-else>
        <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
          <div class="min-w-0">
            <div class="text-sm font-medium text-[hsl(var(--foreground))]">跳过已转存历史</div>
            <p class="mt-0.5 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">开启后转存时会跳过历史记录中已成功转存过的文件，避免重复转存。</p>
          </div>
          <ToggleSwitch v-model="form.skipTransferred" />
        </div>
      </template>

      <template #footer>
        <Button :disabled="saving || isLoading" @click="save">
          <Loader2 v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
          <Save v-else class="mr-2 h-4 w-4" />
          保存转存设置
        </Button>
      </template>
    </SettingCard>
  </div>
</template>
