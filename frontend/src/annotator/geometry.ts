import type { Ann, Point } from '../types'

/** 把任意顺序的 4 个点整理成 左上、左下、右下、右上（与后端 labels.sort_points 一致） */
export function sortPoints(pts: Point[]): Point[] {
  const idx = [0, 1, 2, 3].sort((a, b) => pts[a][0] - pts[b][0] || pts[a][1] - pts[b][1])
  const left = idx.slice(0, 2).sort((a, b) => pts[a][1] - pts[b][1])
  const right = idx.slice(2).sort((a, b) => pts[a][1] - pts[b][1])
  return [pts[left[0]], pts[left[1]], pts[right[1]], pts[right[0]]]
}

export function pointInPoly(x: number, y: number, pts: Point[]): boolean {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]
    const [xj, yj] = pts[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

export function polyArea(pts: Point[]): number {
  let a = 0
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
  return Math.abs(a / 2)
}

export function cloneAnns(anns: Ann[]): Ann[] {
  return anns.map((a) => ({ cls: a.cls, pts: a.pts.map((p) => [p[0], p[1]] as Point) }))
}

export function hexA(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/(.)/g, '$1$1') : h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}
