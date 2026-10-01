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

/**
 * 4 点对应求单应矩阵 H（3x3，h33 = 1，按行展开成 8 个数），把 src[i] 映射到 dst[i]。
 * 高斯消元（部分主元）解 8x8 方程组；四点共线等退化情况返回 null。
 */
export function homography(src: Point[], dst: Point[]): number[] | null {
  const A: number[][] = []
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i]
    const [u, v] = dst[i]
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v])
  }
  for (let c = 0; c < 8; c++) {
    let p = c
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r
    if (Math.abs(A[p][c]) < 1e-12) return null
    ;[A[c], A[p]] = [A[p], A[c]]
    for (let r = 0; r < 8; r++) {
      if (r === c) continue
      const f = A[r][c] / A[c][c]
      for (let k = c; k < 9; k++) A[r][k] -= f * A[c][k]
    }
  }
  return A.map((row, i) => row[8] / A[i][i])
}

export function applyH(h: number[], x: number, y: number): Point {
  const w = h[6] * x + h[7] * y + 1
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w]
}

/** 三点对应求仿射变换 [a, b, c, d, e, f]（Canvas setTransform 的参数顺序），退化时返回 null */
export function affine3(s: Point[], d: Point[]): number[] | null {
  const [[x0, y0], [x1, y1], [x2, y2]] = s
  const det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
  if (Math.abs(det) < 1e-9) return null
  const solve = (u0: number, u1: number, u2: number) => {
    const p = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det
    const q = ((x1 - x0) * (u2 - u0) - (x2 - x0) * (u1 - u0)) / det
    return [p, q, u0 - p * x0 - q * y0]
  }
  const [a, c, e] = solve(d[0][0], d[1][0], d[2][0])
  const [b, dd, f] = solve(d[0][1], d[1][1], d[2][1])
  return [a, b, c, dd, e, f]
}

export function hexA(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/(.)/g, '$1$1') : h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}
