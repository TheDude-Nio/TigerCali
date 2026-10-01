"""模型预标注：用 ONNX 装甲板检测模型给图片生成四点框。

推理与后处理照搬上交 LabelRoboMaster / labelRightnow 的 model.cpp（MIT License, Copyright (c) 2021 xinyang），
模型文件也来自那里。onnxruntime / numpy 懒导入：没装或没放模型时服务照常启动，只是预标注不可用。
"""
from __future__ import annotations

import importlib.util
import math
import os
import threading
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from . import labels
from .config import settings

INPUT_SIZE = 640
PAD_VALUE = 127
# 模型输出每行：8 个坐标 + 1 个置信度 logit + 颜色 + 编号。顺序与上交原版一致（实测输出最后一维 = 22）
COLORS = ["B", "R", "N", "P"]
TAGS = ["G", "1", "2", "3", "4", "5", "O", "Bs", "Bb"]
ROW_LEN = 9 + len(COLORS) + len(TAGS)


class SmartUnavailable(RuntimeError):
    pass


_lock = threading.Lock()
_session: Any = None


def unavailable_reason() -> str | None:
    """不可用的原因，可用时返回 None。只查文件和包是否存在，不真正导入，/api/meta 每次调用都很便宜。"""
    if importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("numpy") is None:
        return "服务器未安装 onnxruntime（pip install onnxruntime numpy）"
    if not settings.smart_model.is_file():
        return f"未找到模型文件：{settings.smart_model}（见 README「模型预标注」）"
    return None


def available() -> bool:
    return unavailable_reason() is None


def _get_session() -> Any:
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            reason = unavailable_reason()
            if reason:
                raise SmartUnavailable(reason)
            import onnxruntime as ort

            opts = ort.SessionOptions()
            # 留出核给 Web 请求和缩略图线程；同一 session 的并发 run 是线程安全的
            opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
            sess = ort.InferenceSession(str(settings.smart_model), opts, providers=["CPUExecutionProvider"])
            out_shape = sess.get_outputs()[0].shape
            if out_shape[-1] != ROW_LEN:
                raise SmartUnavailable(f"模型输出维度是 {out_shape[-1]}，不是预期的 {ROW_LEN}（4 种颜色 × 9 种编号）")
            _session = sess
    return _session


def preprocess(im: PILImage.Image) -> tuple[Any, float]:
    """等比缩放到长边 640，贴在 640×640 左上角，其余填 127；RGB、/255、NCHW。返回 (输入张量, 缩放比例)。"""
    import numpy as np

    im = im.convert("RGB")
    w, h = im.size
    scale = INPUT_SIZE / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    canvas = PILImage.new("RGB", (INPUT_SIZE, INPUT_SIZE), (PAD_VALUE,) * 3)
    canvas.paste(im.resize((nw, nh), PILImage.BILINEAR), (0, 0))
    x = np.asarray(canvas, dtype=np.float32) / 255.0
    return x.transpose(2, 0, 1)[None], scale


def decode(out: Any, scale: float) -> list[dict[str, Any]]:
    """模型输出 → [{color, tag, conf, pts}]，pts 为原图像素坐标，点序与模型一致（左上、左下、右下、右上）。"""
    import numpy as np

    rows = np.asarray(out, dtype=np.float32).reshape(-1, ROW_LEN)
    # logit > 0 ⇔ sigmoid > 0.5，与 model.cpp 的 inv_sigmoid(0.5) 阈值一致；先过滤，后面只剩几十行
    rows = rows[rows[:, 8] > 0.0]
    if not len(rows):
        return []
    rows = rows[np.argsort(-rows[:, 8], kind="stable")]
    pts = rows[:, :8].reshape(-1, 4, 2) / scale
    lo, hi = pts.min(axis=1), pts.max(axis=1)
    kept: list[int] = []
    for i in range(len(rows)):
        # 与任何已保留框的外接矩形有正面积交集就丢弃（model.cpp 的 is_overlap，等价于阈值 0 的 NMS）
        if any(
            min(hi[i, 0], hi[j, 0]) - max(lo[i, 0], lo[j, 0]) > 0 and min(hi[i, 1], hi[j, 1]) - max(lo[i, 1], lo[j, 1]) > 0
            for j in kept
        ):
            continue
        kept.append(i)
    return [
        {
            "color": COLORS[int(np.argmax(rows[i, 9:13]))],
            "tag": TAGS[int(np.argmax(rows[i, 13:ROW_LEN]))],
            "conf": round(1.0 / (1.0 + math.exp(-float(rows[i, 8]))), 4),
            "pts": [[float(x), float(y)] for x, y in pts[i]],
        }
        for i in kept
    ]


def predict(path: Path) -> list[dict[str, Any]]:
    """对一张存储的原图推理。原图在上传时已按 EXIF 转正，直接读取即与库里的宽高一致。"""
    sess = _get_session()
    with PILImage.open(path) as im:
        x, scale = preprocess(im)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    return decode(out, scale)


def to_annotations(
    dets: list[dict[str, Any]], classes: list[dict[str, Any]], width: int, height: int
) -> tuple[list[dict[str, Any]], int]:
    """按 (颜色, 编号) 映射到任务的类别下标并裁剪到图内。任务没启用的类别丢弃，返回 (标注, 丢弃数)。"""
    index = {(c.get("color"), c.get("tag")): i for i, c in enumerate(classes)}
    raw, confs, skipped = [], [], 0
    for d in dets[: labels.MAX_ANNOTATIONS_PER_IMAGE]:
        cls = index.get((d["color"], d["tag"]))
        if cls is None:
            skipped += 1
            continue
        raw.append({"cls": cls, "pts": d["pts"]})
        confs.append(d["conf"])
    anns = labels.clean_annotations(raw, len(classes), width, height)
    for a, c in zip(anns, confs):
        a["conf"] = c
    return anns, skipped
