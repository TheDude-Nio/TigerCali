/**
 * 暗光增强：CLAHE（限制对比度的自适应直方图均衡），参数与 labelRightnow 的 OpenCV 调用一致
 * （clipLimit 2.0，8×8 分块）。只处理亮度 Y，再把 ΔY 加回 RGB——等价于 YCbCr 里色度不变，颜色不偏。
 * 只用于显示，不改原图、不影响标注坐标。
 */

const TILES = 8
const CLIP_LIMIT = 2.0

/** 对 RGBA 像素就地做 CLAHE */
export function claheInPlace(px: Uint8ClampedArray, w: number, h: number) {
  const n = w * h
  const Y = new Uint8Array(n)
  for (let i = 0, j = 0; i < n; i++, j += 4) Y[i] = (px[j] * 299 + px[j + 1] * 587 + px[j + 2] * 114 + 500) / 1000

  const tw = Math.ceil(w / TILES)
  const th = Math.ceil(h / TILES)
  const luts = new Uint8Array(TILES * TILES * 256)
  const hist = new Uint32Array(256)
  for (let ty = 0; ty < TILES; ty++) {
    for (let tx = 0; tx < TILES; tx++) {
      const x0 = tx * tw, x1 = Math.min(w, x0 + tw)
      const y0 = ty * th, y1 = Math.min(h, y0 + th)
      const area = Math.max(1, (x1 - x0) * (y1 - y0))
      hist.fill(0)
      for (let y = y0; y < y1; y++) for (let x = x0, i = y * w + x0; x < x1; x++, i++) hist[Y[i]]++
      // 削峰：超出上限的部分平均分给所有灰度级
      const limit = Math.max(1, Math.floor((CLIP_LIMIT * area) / 256))
      let excess = 0
      for (let k = 0; k < 256; k++) if (hist[k] > limit) { excess += hist[k] - limit; hist[k] = limit }
      const add = Math.floor(excess / 256)
      let rest = excess - add * 256
      for (let k = 0; k < 256; k++) hist[k] += add + (k < rest ? 1 : 0)
      rest = 0
      let cdf = 0
      const base = (ty * TILES + tx) * 256
      for (let k = 0; k < 256; k++) {
        cdf += hist[k]
        luts[base + k] = Math.min(255, Math.round((cdf * 255) / area))
      }
    }
  }

  // 每个像素在相邻 4 个分块中心之间双线性插值，消除分块边界
  for (let y = 0; y < h; y++) {
    const gy = (y + 0.5) / th - 0.5
    const ty0 = Math.max(0, Math.min(TILES - 1, Math.floor(gy)))
    const ty1 = Math.min(TILES - 1, ty0 + 1)
    const fy = Math.max(0, Math.min(1, gy - ty0))
    for (let x = 0; x < w; x++) {
      const gx = (x + 0.5) / tw - 0.5
      const tx0 = Math.max(0, Math.min(TILES - 1, Math.floor(gx)))
      const tx1 = Math.min(TILES - 1, tx0 + 1)
      const fx = Math.max(0, Math.min(1, gx - tx0))
      const i = y * w + x
      const v = Y[i]
      const a = luts[(ty0 * TILES + tx0) * 256 + v]
      const b = luts[(ty0 * TILES + tx1) * 256 + v]
      const c = luts[(ty1 * TILES + tx0) * 256 + v]
      const d = luts[(ty1 * TILES + tx1) * 256 + v]
      const out = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
      const dv = out - v
      const j = i * 4
      px[j] += dv
      px[j + 1] += dv
      px[j + 2] += dv
    }
  }
}

/** 返回增强后的新位图（原位图不动，由调用方管理生命周期） */
export async function enhance(src: ImageBitmap): Promise<ImageBitmap> {
  const c = new OffscreenCanvas(src.width, src.height)
  const ctx = c.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(src, 0, 0)
  const data = ctx.getImageData(0, 0, src.width, src.height)
  claheInPlace(data.data, src.width, src.height)
  ctx.putImageData(data, 0, 0)
  return createImageBitmap(c)
}
