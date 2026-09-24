/**
 * 四点标注画布引擎：纯 Canvas 2D，所有交互只在需要时通过 requestAnimationFrame 重绘一次。
 *
 * 坐标系：标注存储为图像像素坐标（连续坐标，像素 i 覆盖 [i, i+1)），
 * 屏幕坐标 = 图像坐标 * scale + (ox, oy)。
 */
import type { Ann, Point } from '../types'
import { cloneAnns, hexA, pointInPoly, polyArea, sortPoints } from './geometry'

export interface EditorHooks {
  styleOf(cls: number): { color: string; label: string }
  newClass(): number
  onChange(anns: Ann[]): void
  onSelect(index: number): void
  onView?(): void
}

type Drag =
  | { kind: 'pan'; sx: number; sy: number; ox: number; oy: number }
  | { kind: 'vertex'; ann: number; v: number; moved: boolean; snapshot: string; sx: number; sy: number }
  | { kind: 'move'; ann: number; start: Point; orig: Point[]; moved: boolean; snapshot: string; sx: number; sy: number }

const HIT_VERTEX = 8
const LOUPE = 180
const MIN_SCALE = 0.02
const MAX_SCALE = 80

export class Editor {
  readonly canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private hooks: EditorHooks
  private dpr = 1
  cw = 0
  ch = 0

  img: CanvasImageSource | null = null
  iw = 0
  ih = 0
  anns: Ann[] = []
  selected = -1
  selectedVertex = -1
  private hoverAnn = -1
  private hoverVertex: { ann: number; v: number } | null = null
  drawing: Point[] | null = null

  scale = 1
  ox = 0
  oy = 0
  private fitted = true
  mouse = { sx: 0, sy: 0, ix: 0, iy: 0, inside: false }
  private drag: Drag | null = null
  private space = false

  readonly = false
  autoSort = true
  showLabels = true
  loupe = true
  brightness = 1
  contrast = 1

  private undoStack: string[] = []
  private redoStack: string[] = []
  private raf = 0
  private ro: ResizeObserver
  private listeners: [EventTarget, string, EventListener, AddEventListenerOptions?][] = []

  constructor(canvas: HTMLCanvasElement, hooks: EditorHooks) {
    this.canvas = canvas
    this.hooks = hooks
    const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true })
    if (!ctx) throw new Error('浏览器不支持 Canvas')
    this.ctx = ctx
    this.on(canvas, 'pointerdown', this.onDown as EventListener)
    this.on(canvas, 'pointermove', this.onMove as EventListener)
    this.on(canvas, 'pointerup', this.onUp as EventListener)
    this.on(canvas, 'pointercancel', this.onUp as EventListener)
    this.on(canvas, 'pointerleave', this.onLeave as EventListener)
    this.on(canvas, 'wheel', this.onWheel as EventListener, { passive: false })
    this.on(canvas, 'contextmenu', ((e: Event) => e.preventDefault()) as EventListener)
    this.on(canvas, 'dblclick', this.onDblClick as EventListener)
    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(canvas.parentElement ?? canvas)
    this.resize()
  }

  private on(t: EventTarget, type: string, fn: EventListener, opts?: AddEventListenerOptions) {
    const bound = fn.bind(this) as EventListener
    t.addEventListener(type, bound, opts)
    this.listeners.push([t, type, bound, opts])
  }

  destroy() {
    for (const [t, type, fn, opts] of this.listeners) t.removeEventListener(type, fn, opts)
    this.ro.disconnect()
    cancelAnimationFrame(this.raf)
  }

  // ---------------------------------------------------------------- 公共 API

  setImage(img: CanvasImageSource, w: number, h: number, anns: Ann[], keepView = false) {
    const sameSize = w === this.iw && h === this.ih
    this.img = img
    this.iw = w
    this.ih = h
    this.anns = cloneAnns(anns)
    this.selected = -1
    this.selectedVertex = -1
    this.hoverAnn = -1
    this.hoverVertex = null
    this.drawing = null
    this.drag = null
    this.undoStack = []
    this.redoStack = []
    if (!(keepView && sameSize) || this.fitted) this.fit()
    this.updateMouseImage()
    this.hooks.onSelect(-1)
    this.requestRender()
  }

  /** 用户操作之外的整体替换（复制上一张、清空），可撤销 */
  setAnnotations(anns: Ann[]) {
    this.pushUndo(this.snapshot())
    this.anns = cloneAnns(anns)
    this.select(-1)
    this.emitChange()
  }

  /** 从服务器刷新（版本冲突），不可撤销、不触发保存 */
  replaceAnnotations(anns: Ann[]) {
    this.anns = cloneAnns(anns)
    this.undoStack = []
    this.redoStack = []
    this.select(-1)
    this.requestRender()
  }

  fit() {
    if (!this.iw || !this.cw) return
    this.scale = Math.min(this.cw / this.iw, this.ch / this.ih) * 0.97
    this.ox = (this.cw - this.iw * this.scale) / 2
    this.oy = (this.ch - this.ih * this.scale) / 2
    this.fitted = true
    this.hooks.onView?.()
    this.requestRender()
  }

  /** 以 1 图像像素 = 1 屏幕像素显示 */
  actualSize() {
    this.zoomAt(1 / this.scale, this.cw / 2, this.ch / 2)
  }

  zoomAt(factor: number, sx: number, sy: number) {
    const ns = Math.min(MAX_SCALE, Math.max(MIN_SCALE, this.scale * factor))
    const f = ns / this.scale
    this.ox = sx - (sx - this.ox) * f
    this.oy = sy - (sy - this.oy) * f
    this.scale = ns
    this.fitted = false
    this.updateMouseImage()
    this.hooks.onView?.()
    this.requestRender()
  }

  setSpace(down: boolean) {
    this.space = down
    this.updateCursor()
  }

  undo() {
    if (this.drawing) {
      this.drawing.pop()
      if (!this.drawing.length) this.drawing = null
      this.requestRender()
      return
    }
    const prev = this.undoStack.pop()
    if (prev === undefined) return
    this.redoStack.push(this.snapshot())
    this.anns = JSON.parse(prev)
    this.select(-1)
    this.emitChange()
  }

  redo() {
    const next = this.redoStack.pop()
    if (next === undefined) return
    this.undoStack.push(this.snapshot())
    this.anns = JSON.parse(next)
    this.select(-1)
    this.emitChange()
  }

  /** Delete：画到一半时撤掉最后一个点，否则删除选中的框 */
  deleteSelected(): boolean {
    if (this.drawing) {
      this.drawing.pop()
      if (!this.drawing.length) this.drawing = null
      this.requestRender()
      return true
    }
    if (this.readonly || this.selected < 0) return false
    this.pushUndo(this.snapshot())
    this.anns.splice(this.selected, 1)
    this.select(Math.min(this.selected, this.anns.length - 1))
    this.emitChange()
    return true
  }

  deleteAt(index: number) {
    if (this.readonly || index < 0 || index >= this.anns.length) return
    this.pushUndo(this.snapshot())
    this.anns.splice(index, 1)
    this.select(-1)
    this.emitChange()
  }

  cancel() {
    if (this.drawing) this.drawing = null
    else this.select(-1)
    this.requestRender()
  }

  setClassOf(index: number, cls: number) {
    if (this.readonly || index < 0 || index >= this.anns.length || this.anns[index].cls === cls) return
    this.pushUndo(this.snapshot())
    this.anns[index].cls = cls
    this.emitChange()
  }

  /** 方向键微调：选中了点就动点，否则整体平移选中的框 */
  nudge(dx: number, dy: number) {
    if (this.readonly || this.selected < 0) return
    const a = this.anns[this.selected]
    this.pushUndo(this.snapshot())
    if (this.selectedVertex >= 0) {
      const p = a.pts[this.selectedVertex]
      a.pts[this.selectedVertex] = this.clampPt(p[0] + dx, p[1] + dy)
    } else {
      a.pts = this.translateClamped(a.pts, dx, dy)
    }
    this.emitChange()
  }

  selectNext(dir = 1) {
    if (!this.anns.length) return
    const n = this.anns.length
    this.select(this.selected < 0 ? (dir > 0 ? 0 : n - 1) : (this.selected + dir + n) % n)
  }

  select(i: number, vertex = -1) {
    const changed = i !== this.selected
    this.selected = i
    this.selectedVertex = i >= 0 ? vertex : -1
    if (changed) this.hooks.onSelect(i)
    this.requestRender()
  }

  requestRender() {
    if (this.raf) return
    this.raf = requestAnimationFrame(() => {
      this.raf = 0
      try {
        this.render()
      } catch (e) {
        // 图片被回收（ImageBitmap 已 close）等极端情况：跳过这一帧，下次切图会恢复
        console.warn('render skipped', e)
      }
    })
  }

  // ---------------------------------------------------------------- 内部工具

  private snapshot(): string {
    return JSON.stringify(this.anns)
  }

  private pushUndo(s: string) {
    this.undoStack.push(s)
    if (this.undoStack.length > 200) this.undoStack.shift()
    this.redoStack = []
  }

  private emitChange() {
    this.requestRender()
    this.hooks.onChange(cloneAnns(this.anns))
  }

  private resize() {
    const parent = this.canvas.parentElement
    if (!parent) return
    const rect = parent.getBoundingClientRect()
    this.dpr = window.devicePixelRatio || 1
    this.cw = Math.max(1, Math.floor(rect.width))
    this.ch = Math.max(1, Math.floor(rect.height))
    this.canvas.width = Math.round(this.cw * this.dpr)
    this.canvas.height = Math.round(this.ch * this.dpr)
    this.canvas.style.width = `${this.cw}px`
    this.canvas.style.height = `${this.ch}px`
    if (this.fitted) this.fit()
    this.requestRender()
  }

  private toImage(sx: number, sy: number): Point {
    return [(sx - this.ox) / this.scale, (sy - this.oy) / this.scale]
  }

  private toScreen(p: Point): Point {
    return [p[0] * this.scale + this.ox, p[1] * this.scale + this.oy]
  }

  private clampPt(x: number, y: number): Point {
    return [Math.min(Math.max(x, 0), this.iw), Math.min(Math.max(y, 0), this.ih)]
  }

  private translateClamped(pts: Point[], dx: number, dy: number): Point[] {
    const xs = pts.map((p) => p[0])
    const ys = pts.map((p) => p[1])
    dx = Math.min(Math.max(dx, -Math.min(...xs)), this.iw - Math.max(...xs))
    dy = Math.min(Math.max(dy, -Math.min(...ys)), this.ih - Math.max(...ys))
    return pts.map((p) => [p[0] + dx, p[1] + dy] as Point)
  }

  private local(e: PointerEvent | WheelEvent | MouseEvent) {
    const r = this.canvas.getBoundingClientRect()
    return { sx: e.clientX - r.left, sy: e.clientY - r.top }
  }

  private updateMouseImage() {
    const [ix, iy] = this.toImage(this.mouse.sx, this.mouse.sy)
    this.mouse.ix = ix
    this.mouse.iy = iy
  }

  /** 命中的顶点：优先当前选中的框，其次离鼠标最近的 */
  private hitVertex(sx: number, sy: number): { ann: number; v: number } | null {
    const nearest = (i: number): { v: number; d: number } | null => {
      let best: { v: number; d: number } | null = null
      const pts = this.anns[i].pts
      for (let v = 0; v < pts.length; v++) {
        const [px, py] = this.toScreen(pts[v])
        const d = (px - sx) ** 2 + (py - sy) ** 2
        if (d <= HIT_VERTEX * HIT_VERTEX && (!best || d < best.d)) best = { v, d }
      }
      return best
    }
    if (this.selected >= 0) {
      const h = nearest(this.selected)
      if (h) return { ann: this.selected, v: h.v }
    }
    let best: { ann: number; v: number; d: number } | null = null
    for (let i = 0; i < this.anns.length; i++) {
      if (i === this.selected) continue
      const h = nearest(i)
      if (h && (!best || h.d < best.d)) best = { ann: i, v: h.v, d: h.d }
    }
    return best ? { ann: best.ann, v: best.v } : null
  }

  private hitAnn(ix: number, iy: number): number {
    let best = -1
    let bestArea = Infinity
    for (let i = 0; i < this.anns.length; i++) {
      const pts = this.anns[i].pts
      if (pointInPoly(ix, iy, pts)) {
        const a = polyArea(pts)
        if (a < bestArea) {
          bestArea = a
          best = i
        }
      }
    }
    return best
  }

  private updateCursor() {
    let c = 'crosshair'
    if (this.drag?.kind === 'pan') c = 'grabbing'
    else if (this.space) c = 'grab'
    else if (this.drag?.kind === 'move') c = 'move'
    else if (!this.drawing && !this.readonly && this.hoverVertex) c = 'pointer'
    else if (!this.drawing && this.hoverAnn >= 0) c = this.readonly ? 'pointer' : 'move'
    if (this.canvas.style.cursor !== c) this.canvas.style.cursor = c
  }

  // ---------------------------------------------------------------- 事件

  private onDown(e: PointerEvent) {
    const { sx, sy } = this.local(e)
    this.mouse.sx = sx
    this.mouse.sy = sy
    this.updateMouseImage()
    if (e.button === 1 || e.button === 2 || (e.button === 0 && this.space)) {
      this.drag = { kind: 'pan', sx, sy, ox: this.ox, oy: this.oy }
      this.canvas.setPointerCapture(e.pointerId)
      this.updateCursor()
      e.preventDefault()
      return
    }
    if (e.button !== 0 || !this.img) return
    const [ix, iy] = this.toImage(sx, sy)

    if (this.readonly) {
      this.select(this.hitAnn(ix, iy))
      return
    }

    if (this.drawing) {
      this.addPoint(ix, iy)
      return
    }

    if (!e.ctrlKey && !e.metaKey) {
      const hv = this.hitVertex(sx, sy)
      if (hv) {
        this.select(hv.ann, hv.v)
        this.drag = { kind: 'vertex', ann: hv.ann, v: hv.v, moved: false, snapshot: this.snapshot(), sx, sy }
        this.canvas.setPointerCapture(e.pointerId)
        return
      }
      const ha = this.hitAnn(ix, iy)
      if (ha >= 0) {
        this.select(ha)
        this.drag = {
          kind: 'move',
          ann: ha,
          start: [ix, iy],
          orig: this.anns[ha].pts.map((p) => [p[0], p[1]] as Point),
          moved: false,
          snapshot: this.snapshot(),
          sx,
          sy,
        }
        this.canvas.setPointerCapture(e.pointerId)
        return
      }
    }

    // 点在图像外太远就只取消选择
    const tol = 20 / this.scale
    if (ix < -tol || iy < -tol || ix > this.iw + tol || iy > this.ih + tol) {
      this.select(-1)
      return
    }
    this.select(-1)
    this.drawing = [this.clampPt(ix, iy)]
    this.requestRender()
  }

  private addPoint(ix: number, iy: number) {
    const d = this.drawing!
    const p = this.clampPt(ix, iy)
    const last = d[d.length - 1]
    // 连点两次同一位置忽略（防止误触产生退化的框）
    if (Math.hypot((p[0] - last[0]) * this.scale, (p[1] - last[1]) * this.scale) < 3) return
    d.push(p)
    if (d.length === 4) {
      const pts = this.autoSort ? sortPoints(d) : d
      this.drawing = null
      if (polyArea(pts) < 0.5) {
        this.requestRender()
        return
      }
      this.pushUndo(this.snapshot())
      this.anns.push({ cls: this.hooks.newClass(), pts })
      this.select(this.anns.length - 1)
      this.emitChange()
    } else {
      this.requestRender()
    }
  }

  private onMove(e: PointerEvent) {
    const { sx, sy } = this.local(e)
    this.mouse.sx = sx
    this.mouse.sy = sy
    this.mouse.inside = true
    this.updateMouseImage()
    const d = this.drag
    if (d?.kind === 'pan') {
      this.ox = d.ox + (sx - d.sx)
      this.oy = d.oy + (sy - d.sy)
      this.fitted = false
      this.updateMouseImage()
    } else if (d?.kind === 'vertex') {
      if (!d.moved && Math.hypot(sx - d.sx, sy - d.sy) < 2) return
      d.moved = true
      this.anns[d.ann].pts[d.v] = this.clampPt(this.mouse.ix, this.mouse.iy)
    } else if (d?.kind === 'move') {
      if (!d.moved && Math.hypot(sx - d.sx, sy - d.sy) < 3) return
      d.moved = true
      this.anns[d.ann].pts = this.translateClamped(d.orig, this.mouse.ix - d.start[0], this.mouse.iy - d.start[1])
    } else if (!this.drawing) {
      this.hoverVertex = this.readonly ? null : this.hitVertex(sx, sy)
      this.hoverAnn = this.hoverVertex ? this.hoverVertex.ann : this.hitAnn(this.mouse.ix, this.mouse.iy)
    }
    this.updateCursor()
    this.hooks.onView?.()
    this.requestRender()
  }

  private onUp(e: PointerEvent) {
    const d = this.drag
    this.drag = null
    if (this.canvas.hasPointerCapture(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId)
    if (d?.kind === 'vertex' && d.moved) {
      const a = this.anns[d.ann]
      if (this.autoSort) {
        const moved = a.pts[d.v]
        a.pts = sortPoints(a.pts)
        this.selectedVertex = a.pts.indexOf(moved)
      }
      this.pushUndo(d.snapshot)
      this.emitChange()
    } else if (d?.kind === 'move' && d.moved) {
      this.pushUndo(d.snapshot)
      this.emitChange()
    }
    this.updateCursor()
    this.requestRender()
  }

  private onLeave() {
    this.mouse.inside = false
    this.hoverAnn = -1
    this.hoverVertex = null
    this.requestRender()
  }

  private onDblClick(e: MouseEvent) {
    // 双击空白处：适应窗口
    if (this.drawing || this.readonly) return
    const { sx, sy } = this.local(e)
    const [ix, iy] = this.toImage(sx, sy)
    if (this.hitAnn(ix, iy) < 0 && !this.hitVertex(sx, sy) && (ix < 0 || iy < 0 || ix > this.iw || iy > this.ih)) this.fit()
  }

  private onWheel(e: WheelEvent) {
    e.preventDefault()
    const { sx, sy } = this.local(e)
    const unit = e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1
    const factor = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0018))
    this.zoomAt(factor, sx, sy)
  }

  // ---------------------------------------------------------------- 绘制

  private render() {
    const ctx = this.ctx
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    ctx.fillStyle = '#0b0f17'
    ctx.fillRect(0, 0, this.cw, this.ch)
    if (!this.img) return

    ctx.save()
    ctx.imageSmoothingEnabled = this.scale < 2.5
    ctx.imageSmoothingQuality = 'high'
    if (this.brightness !== 1 || this.contrast !== 1) ctx.filter = `brightness(${this.brightness}) contrast(${this.contrast})`
    ctx.drawImage(this.img, this.ox, this.oy, this.iw * this.scale, this.ih * this.scale)
    ctx.restore()

    const toS = (p: Point) => this.toScreen(p)
    for (let i = 0; i < this.anns.length; i++) {
      if (!this.showLabels && i !== this.selected) continue
      this.drawAnn(ctx, this.anns[i], toS, i === this.selected, i === this.hoverAnn, true)
    }
    if (this.drawing) this.drawDrawing(ctx, toS)

    const m = this.mouse
    if (m.inside && this.drag?.kind !== 'pan' && !this.space) {
      ctx.save()
      ctx.strokeStyle = 'rgba(255,255,255,0.35)'
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(0, Math.round(m.sy) + 0.5)
      ctx.lineTo(this.cw, Math.round(m.sy) + 0.5)
      ctx.moveTo(Math.round(m.sx) + 0.5, 0)
      ctx.lineTo(Math.round(m.sx) + 0.5, this.ch)
      ctx.stroke()
      ctx.restore()
      if (this.loupe && m.ix >= -2 && m.iy >= -2 && m.ix <= this.iw + 2 && m.iy <= this.ih + 2) this.drawLoupe(ctx)
    }
  }

  private drawAnn(
    ctx: CanvasRenderingContext2D,
    a: Ann,
    toS: (p: Point) => Point,
    selected: boolean,
    hover: boolean,
    withText: boolean,
    small = false,
  ) {
    const { color, label } = this.hooks.styleOf(a.cls)
    const pts = a.pts.map(toS)
    ctx.beginPath()
    ctx.moveTo(pts[0][0], pts[0][1])
    for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1])
    ctx.closePath()
    ctx.fillStyle = hexA(color, selected ? 0.22 : hover ? 0.16 : 0.08)
    ctx.fill()
    ctx.lineWidth = small ? 1.2 : selected ? 2.2 : 1.5
    ctx.strokeStyle = color
    ctx.stroke()

    const r = small ? 2.5 : selected ? 4.5 : 3.2
    for (let k = 0; k < pts.length; k++) {
      ctx.beginPath()
      ctx.arc(pts[k][0], pts[k][1], k === this.selectedVertex && selected ? r + 1.5 : r, 0, Math.PI * 2)
      // 第 1 个点（左上）用白色实心标出，方便检查点序
      ctx.fillStyle = k === 0 ? '#ffffff' : color
      ctx.fill()
      ctx.lineWidth = 1
      ctx.strokeStyle = k === 0 ? color : 'rgba(0,0,0,0.6)'
      ctx.stroke()
    }

    if (!withText) return
    ctx.font = '600 12px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
    if (selected || hover) {
      const cx = pts.reduce((s, p) => s + p[0], 0) / 4
      const cy = pts.reduce((s, p) => s + p[1], 0) / 4
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = 'rgba(0,0,0,0.8)'
      ctx.lineWidth = 3
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      for (let k = 0; k < pts.length; k++) {
        const dx = pts[k][0] - cx
        const dy = pts[k][1] - cy
        const len = Math.hypot(dx, dy) || 1
        const tx = pts[k][0] + (dx / len) * 12
        const ty = pts[k][1] + (dy / len) * 12
        ctx.strokeText(String(k + 1), tx, ty)
        ctx.fillText(String(k + 1), tx, ty)
      }
    }
    const top = pts.reduce((best, p) => (p[1] < best[1] || (p[1] === best[1] && p[0] < best[0]) ? p : best), pts[0])
    const minX = Math.min(...pts.map((p) => p[0]))
    const tw = ctx.measureText(label).width + 8
    const ly = top[1] - 20
    ctx.fillStyle = color
    ctx.fillRect(minX, ly, tw, 16)
    ctx.fillStyle = '#fff'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, minX + 4, ly + 8.5)
  }

  private drawDrawing(ctx: CanvasRenderingContext2D, toS: (p: Point) => Point, small = false) {
    const d = this.drawing!
    const color = this.hooks.styleOf(this.hooks.newClass()).color
    const pts = d.map(toS)
    const mouse = toS([this.mouse.ix, this.mouse.iy])
    ctx.save()
    ctx.strokeStyle = color
    ctx.lineWidth = small ? 1.2 : 1.8
    ctx.beginPath()
    ctx.moveTo(pts[0][0], pts[0][1])
    for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1])
    ctx.stroke()
    ctx.setLineDash([5, 4])
    ctx.beginPath()
    ctx.moveTo(pts[pts.length - 1][0], pts[pts.length - 1][1])
    ctx.lineTo(mouse[0], mouse[1])
    if (pts.length === 3) ctx.lineTo(pts[0][0], pts[0][1])
    ctx.stroke()
    ctx.setLineDash([])
    for (let k = 0; k < pts.length; k++) {
      ctx.beginPath()
      ctx.arc(pts[k][0], pts[k][1], small ? 2.5 : 4, 0, Math.PI * 2)
      ctx.fillStyle = k === 0 ? '#fff' : color
      ctx.fill()
      ctx.strokeStyle = 'rgba(0,0,0,0.7)'
      ctx.lineWidth = 1
      ctx.stroke()
    }
    if (!small) {
      ctx.font = '600 12px sans-serif'
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = 'rgba(0,0,0,0.8)'
      ctx.lineWidth = 3
      const t = `${pts.length}/4`
      ctx.strokeText(t, mouse[0] + 12, mouse[1] - 10)
      ctx.fillText(t, mouse[0] + 12, mouse[1] - 10)
    }
    ctx.restore()
  }

  private drawLoupe(ctx: CanvasRenderingContext2D) {
    const m = this.mouse
    const size = LOUPE
    const margin = 12
    // 鼠标靠近左上角时放到右上角
    const right = m.sx < size + margin * 3 && m.sy < size + margin * 3 + 24
    const x0 = right ? this.cw - size - margin : margin
    const y0 = margin
    const z = Math.min(40, Math.max(6, this.scale * 4))
    const half = size / 2 / z
    const sx = m.ix - half
    const sy = m.iy - half

    ctx.save()
    ctx.beginPath()
    ctx.rect(x0, y0, size, size)
    ctx.fillStyle = '#000'
    ctx.fill()
    ctx.clip()
    ctx.imageSmoothingEnabled = false
    if (this.brightness !== 1 || this.contrast !== 1) ctx.filter = `brightness(${this.brightness}) contrast(${this.contrast})`
    ctx.drawImage(this.img!, 0, 0, this.iw, this.ih, x0 - sx * z, y0 - sy * z, this.iw * z, this.ih * z)
    ctx.filter = 'none'
    const toL = (p: Point): Point => [x0 + (p[0] - sx) * z, y0 + (p[1] - sy) * z]
    for (let i = 0; i < this.anns.length; i++) this.drawAnn(ctx, this.anns[i], toL, i === this.selected, false, false, true)
    if (this.drawing) this.drawDrawing(ctx, toL, true)
    // 中心十字
    const cx = x0 + size / 2
    const cy = y0 + size / 2
    ctx.strokeStyle = 'rgba(255,255,255,0.9)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(cx - 14, cy + 0.5)
    ctx.lineTo(cx - 4, cy + 0.5)
    ctx.moveTo(cx + 4, cy + 0.5)
    ctx.lineTo(cx + 14, cy + 0.5)
    ctx.moveTo(cx + 0.5, cy - 14)
    ctx.lineTo(cx + 0.5, cy - 4)
    ctx.moveTo(cx + 0.5, cy + 4)
    ctx.lineTo(cx + 0.5, cy + 14)
    ctx.stroke()
    ctx.restore()

    ctx.save()
    ctx.strokeStyle = '#f97316'
    ctx.lineWidth = 2
    ctx.strokeRect(x0, y0, size, size)
    ctx.fillStyle = 'rgba(0,0,0,0.65)'
    ctx.fillRect(x0, y0 + size, size, 20)
    ctx.fillStyle = '#fff'
    ctx.font = '11px ui-monospace, Menlo, Consolas, monospace'
    ctx.textBaseline = 'middle'
    ctx.fillText(`x ${m.ix.toFixed(1)}  y ${m.iy.toFixed(1)}  ×${(z).toFixed(0)}`, x0 + 6, y0 + size + 10)
    ctx.restore()
  }
}
