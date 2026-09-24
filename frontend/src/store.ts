import { reactive } from 'vue'
import { api } from './api'
import type { Meta, User } from './types'

export const auth = reactive({
  user: null as User | null,
  loaded: false,
})

export const metaStore = reactive({
  meta: null as Meta | null,
})

let sessionPromise: Promise<void> | null = null
export function loadSession(): Promise<void> {
  if (!sessionPromise) {
    sessionPromise = api
      .get<User>('/api/auth/me', undefined, { silent401: true })
      .then((u) => {
        auth.user = u
      })
      .catch(() => {
        auth.user = null
      })
      .finally(() => {
        auth.loaded = true
      })
  }
  return sessionPromise
}

let metaPromise: Promise<Meta> | null = null
export function loadMeta(): Promise<Meta> {
  if (!metaPromise) {
    metaPromise = api.get<Meta>('/api/meta').then((m) => {
      metaStore.meta = m
      return m
    })
    metaPromise.catch(() => (metaPromise = null))
  }
  return metaPromise
}

export function setUser(u: User | null) {
  auth.user = u
  auth.loaded = true
}

// ---------------------------------------------------------------- toast

export interface ToastItem {
  id: number
  text: string
  kind: 'info' | 'success' | 'error' | 'warn'
}

export const toasts = reactive<ToastItem[]>([])
let toastId = 0

export function toast(text: string, kind: ToastItem['kind'] = 'info', ms = 2600) {
  const id = ++toastId
  toasts.push({ id, text, kind })
  if (toasts.length > 5) toasts.splice(0, toasts.length - 5)
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, ms)
}

// ---------------------------------------------------------------- confirm / prompt 对话框

export interface DialogState {
  open: boolean
  title: string
  message: string
  danger: boolean
  okText: string
  input: boolean
  inputValue: string
  placeholder: string
  multiline: boolean
  resolve: ((v: string | null) => void) | null
}

export const dialog = reactive<DialogState>({
  open: false,
  title: '',
  message: '',
  danger: false,
  okText: '确定',
  input: false,
  inputValue: '',
  placeholder: '',
  multiline: false,
  resolve: null,
})

function openDialog(opts: Partial<DialogState>): Promise<string | null> {
  dialog.resolve?.(null)
  return new Promise((resolve) => {
    Object.assign(dialog, {
      open: true,
      title: '',
      message: '',
      danger: false,
      okText: '确定',
      input: false,
      inputValue: '',
      placeholder: '',
      multiline: false,
      ...opts,
      resolve,
    })
  })
}

export async function confirmDialog(
  title: string,
  message = '',
  opts: { danger?: boolean; okText?: string } = {},
): Promise<boolean> {
  return (await openDialog({ title, message, ...opts })) !== null
}

export function promptDialog(
  title: string,
  opts: { message?: string; value?: string; placeholder?: string; multiline?: boolean; okText?: string; danger?: boolean } = {},
): Promise<string | null> {
  return openDialog({
    title,
    message: opts.message ?? '',
    input: true,
    inputValue: opts.value ?? '',
    placeholder: opts.placeholder ?? '',
    multiline: opts.multiline ?? false,
    okText: opts.okText ?? '确定',
    danger: opts.danger ?? false,
  })
}
