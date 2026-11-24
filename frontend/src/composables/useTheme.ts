import { ref, watch } from 'vue'

type Theme = 'light' | 'dark'

const THEME_KEY = 'cas-x-theme'

function readStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    // private mode / blocked storage
  }
  return null
}

function getInitialTheme(): Theme {
  const stored = readStoredTheme()
  if (stored) return stored
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(getInitialTheme())

function applyTheme(value: Theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', value === 'dark')
  root.style.colorScheme = value
}

function persistTheme(value: Theme) {
  try {
    localStorage.setItem(THEME_KEY, value)
  } catch {
    // private mode / blocked storage
  }
}

// 模块加载即同步 DOM；变更时写入 localStorage（含首次固化系统偏好）
watch(
  theme,
  (value) => {
    persistTheme(value)
    applyTheme(value)
  },
  { immediate: true },
)

export function useTheme() {
  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  function setTheme(value: Theme) {
    theme.value = value
  }

  return {
    theme,
    toggleTheme,
    setTheme,
    isDark: () => theme.value === 'dark',
  }
}
