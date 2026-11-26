export type DriveType = 'quark' | 'cloud189'

export const DRIVE_TYPE_LABELS: Record<string, string> = {
  quark: '夸克',
  cloud189: '天翼云盘',
}

export function getDriveTypeLabel(code: string | null | undefined) {
  const key = String(code || '').trim()
  return DRIVE_TYPE_LABELS[key] || key || '未知类型'
}

export function detectDriveTypeByUrl(url: string): DriveType | null {
  const value = String(url || '')
  if (!value) return null
  if (/pan\.quark\.cn/i.test(value)) return 'quark'
  if (/(?:cloud|m\.cloud)\.189\.cn/i.test(value)) return 'cloud189'
  return null
}
