export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

let unauthorizedHandler: (() => void) | null = null
export function onUnauthorized(fn: () => void) {
  unauthorizedHandler = fn
}

export function qs(params?: Params): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json()
    if (typeof j.detail === 'string') return j.detail
    return JSON.stringify(j.detail ?? j)
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

interface ReqOpts {
  silent401?: boolean
  signal?: AbortSignal
  keepalive?: boolean
}

async function request<T>(method: string, url: string, body?: unknown, opts: ReqOpts = {}): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', signal: opts.signal, keepalive: opts.keepalive }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(url, init)
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, '网络连接失败，请检查网络')
  }
  if (!res.ok) {
    const msg = await parseError(res)
    if (res.status === 401 && !opts.silent401) unauthorizedHandler?.()
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(url: string, params?: Params, opts?: ReqOpts) => request<T>('GET', url + qs(params), undefined, opts),
  post: <T>(url: string, body?: unknown, opts?: ReqOpts) => request<T>('POST', url, body ?? {}, opts),
  put: <T>(url: string, body?: unknown, opts?: ReqOpts) => request<T>('PUT', url, body ?? {}, opts),
  patch: <T>(url: string, body?: unknown, opts?: ReqOpts) => request<T>('PATCH', url, body ?? {}, opts),
  del: <T>(url: string, opts?: ReqOpts) => request<T>('DELETE', url, undefined, opts),
}

/** 带上传进度的表单提交（fetch 拿不到上传进度） */
export function uploadForm<T>(url: string, form: FormData, onProgress?: (loaded: number, total: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.withCredentials = true
    xhr.responseType = 'json'
    if (onProgress) xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as T)
      else {
        const detail = xhr.response?.detail
        if (xhr.status === 401) unauthorizedHandler?.()
        reject(new ApiError(xhr.status, typeof detail === 'string' ? detail : `上传失败 (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, '网络连接失败'))
    xhr.send(form)
  })
}

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}
