/** 解码好的图片缓存（LRU），配合预取实现翻页零等待 */
export class BitmapCache {
  private map = new Map<number, Promise<ImageBitmap>>()
  private pinned = new Set<number>()

  constructor(private max = 24) {}

  get(id: number): Promise<ImageBitmap> {
    const hit = this.map.get(id)
    if (hit) {
      this.map.delete(id)
      this.map.set(id, hit)
      return hit
    }
    const p = fetch(`/api/images/${id}/file`, { credentials: 'same-origin' })
      .then((r) => {
        if (!r.ok) throw new Error(`图片加载失败 (${r.status})`)
        return r.blob()
      })
      .then((b) => createImageBitmap(b))
    p.catch(() => this.map.delete(id))
    this.map.set(id, p)
    this.evict()
    return p
  }

  /** 当前正在显示/即将显示的图片不能被回收 */
  pin(ids: number[]) {
    this.pinned = new Set(ids)
  }

  private evict() {
    if (this.map.size <= this.max) return
    for (const [k, v] of this.map) {
      if (this.map.size <= this.max) break
      if (this.pinned.has(k)) continue
      this.map.delete(k)
      v.then((b) => b.close()).catch(() => undefined)
    }
  }

  clear() {
    for (const [k, v] of this.map) if (!this.pinned.has(k)) v.then((b) => b.close()).catch(() => undefined)
    this.map.clear()
  }
}
