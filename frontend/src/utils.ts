import type { ClassDef, ImageStatus, MemberStatus, Role } from './types'
import { metaStore } from './store'

export const MEMBER_STATUS: Record<MemberStatus, { text: string; cls: string }> = {
  labeling: { text: '标注中', cls: 'badge-blue' },
  submitted: { text: '待审核', cls: 'badge-orange' },
  approved: { text: '已通过', cls: 'badge-green' },
  rejected: { text: '被打回', cls: 'badge-red' },
}

export const ROLE_TEXT: Record<Role, string> = {
  owner: '创建者',
  manager: '管理员',
  annotator: '标注员',
}

export const IMAGE_STATUS: Record<ImageStatus, { text: string; cls: string }> = {
  todo: { text: '未完成', cls: 'badge-gray' },
  done: { text: '已完成', cls: 'badge-green' },
  rework: { text: '需返工', cls: 'badge-red' },
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function pct(a: number, b: number): number {
  return b > 0 ? Math.round((a / b) * 1000) / 10 : 0
}

export function basename(path: string): string {
  const i = path.lastIndexOf('/')
  return i >= 0 ? path.slice(i + 1) : path
}

const FALLBACK_ARMOR: Record<string, string> = { B: '#3b82f6', R: '#ef4444', N: '#a3a3a3', P: '#c084fc' }
const PALETTE = [
  '#f97316', '#22c55e', '#3b82f6', '#eab308', '#ec4899', '#14b8a6', '#8b5cf6', '#ef4444',
  '#84cc16', '#06b6d4', '#f43f5e', '#a855f7', '#10b981', '#f59e0b', '#6366f1', '#d946ef',
]

export function classColor(classes: ClassDef[], cls: number): string {
  const c = classes[cls]
  if (c?.color) {
    const hex = metaStore.meta?.armor_colors.find((x) => x.key === c.color)?.hex
    return hex ?? FALLBACK_ARMOR[c.color] ?? '#f97316'
  }
  return PALETTE[cls % PALETTE.length]
}

export function classLabel(classes: ClassDef[], cls: number): string {
  return classes[cls]?.name ?? `#${cls}`
}

export function debounce<T extends (...args: never[]) => void>(fn: T, ms: number) {
  let t: ReturnType<typeof setTimeout> | null = null
  const wrapped = (...args: Parameters<T>) => {
    if (t) clearTimeout(t)
    t = setTimeout(() => {
      t = null
      fn(...args)
    }, ms)
  }
  wrapped.cancel = () => {
    if (t) clearTimeout(t)
    t = null
  }
  return wrapped
}
