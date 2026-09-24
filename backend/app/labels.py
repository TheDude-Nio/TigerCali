"""标注类别、点序以及 YOLO 各种文本格式的读写。

内部统一存储：像素坐标，点序固定为 左上(TL)、左下(BL)、右下(BR)、右上(TR)。
导出时再按用户选择的点序重排并归一化。
"""
from __future__ import annotations

import math
from typing import Any

# 装甲板颜色，sjtu 为常见 “颜色 + 编号” 双标签格式里的颜色下标
ARMOR_COLORS: list[dict[str, Any]] = [
    {"key": "B", "name": "蓝", "sjtu": 0, "hex": "#3b82f6"},
    {"key": "R", "name": "红", "sjtu": 1, "hex": "#ef4444"},
    {"key": "N", "name": "灰", "sjtu": 2, "hex": "#a3a3a3"},
    {"key": "P", "name": "紫", "sjtu": 3, "hex": "#c084fc"},
]

# 装甲板编号，hotkey 为标注界面的快捷键
ARMOR_TAGS: list[dict[str, Any]] = [
    {"key": "G", "name": "哨兵", "sjtu": 0, "hotkey": "0"},
    {"key": "1", "name": "英雄", "sjtu": 1, "hotkey": "1"},
    {"key": "2", "name": "工程", "sjtu": 2, "hotkey": "2"},
    {"key": "3", "name": "步兵3", "sjtu": 3, "hotkey": "3"},
    {"key": "4", "name": "步兵4", "sjtu": 4, "hotkey": "4"},
    {"key": "5", "name": "步兵5", "sjtu": 5, "hotkey": "5"},
    {"key": "O", "name": "前哨站", "sjtu": 6, "hotkey": "6"},
    {"key": "Bs", "name": "基地小", "sjtu": 7, "hotkey": "7"},
    {"key": "Bb", "name": "基地大", "sjtu": 8, "hotkey": "8"},
]

_COLOR_BY_KEY = {c["key"]: c for c in ARMOR_COLORS}
_TAG_BY_KEY = {t["key"]: t for t in ARMOR_TAGS}

# 点序：canonical 下标 0=左上 1=左下 2=右下 3=右上
POINT_ORDERS: dict[str, dict[str, Any]] = {
    "tl_bl_br_tr": {"name": "左上 → 左下 → 右下 → 右上（逆时针，RM 常用）", "perm": [0, 1, 2, 3]},
    "tl_tr_br_bl": {"name": "左上 → 右上 → 右下 → 左下（顺时针）", "perm": [0, 3, 2, 1]},
    "bl_tl_tr_br": {"name": "左下 → 左上 → 右上 → 右下", "perm": [1, 0, 3, 2]},
}
DEFAULT_POINT_ORDER = "tl_bl_br_tr"

EXPORT_FORMATS: list[dict[str, str]] = [
    {
        "key": "yolo_pose",
        "name": "YOLO Pose（Ultralytics 关键点，推荐）",
        "line": "cls cx cy w h x1 y1 x2 y2 x3 y3 x4 y4",
    },
    {"key": "rm4", "name": "RM 四点格式", "line": "cls x1 y1 x2 y2 x3 y3 x4 y4"},
    {"key": "sjtu", "name": "颜色 + 编号 双标签四点（仅装甲板模式）", "line": "color tag x1 y1 x2 y2 x3 y3 x4 y4"},
    {"key": "yolo_det", "name": "YOLO 检测框", "line": "cls cx cy w h"},
    {"key": "json", "name": "JSON 原始标注（像素坐标，便于备份）", "line": "annotations.json"},
]
EXPORT_FORMAT_KEYS = {f["key"] for f in EXPORT_FORMATS}

MAX_CLASSES = 200
MAX_ANNOTATIONS_PER_IMAGE = 500


class LabelError(ValueError):
    pass


def build_classes(cfg: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """校验 label_config 并展开为类别列表。类别下标 = YOLO class id。"""
    if not isinstance(cfg, dict):
        raise LabelError("类别配置格式错误")
    mode = cfg.get("mode", "armor")
    if mode == "armor":
        colors_in = set(cfg.get("colors") or [])
        tags_in = set(cfg.get("tags") or [])
        # 保持固定顺序，保证 class id = 颜色序号 * 编号数 + 编号序号
        colors = [c["key"] for c in ARMOR_COLORS if c["key"] in colors_in]
        tags = [t["key"] for t in ARMOR_TAGS if t["key"] in tags_in]
        if not colors:
            raise LabelError("至少选择一种装甲板颜色")
        if not tags:
            raise LabelError("至少选择一种装甲板编号")
        classes = [{"name": f"{c}_{t}", "color": c, "tag": t} for c in colors for t in tags]
        return {"mode": "armor", "colors": colors, "tags": tags}, classes
    if mode == "custom":
        names: list[str] = []
        for raw in cfg.get("names") or []:
            name = str(raw).strip()
            if not name:
                continue
            if len(name) > 40:
                raise LabelError(f"类别名过长：{name[:20]}…")
            if any(ch.isspace() for ch in name):
                raise LabelError(f"类别名不能包含空格：{name}")
            if name in names:
                raise LabelError(f"类别名重复：{name}")
            names.append(name)
        if not names:
            raise LabelError("至少填写一个类别")
        if len(names) > MAX_CLASSES:
            raise LabelError(f"类别数不能超过 {MAX_CLASSES}")
        return {"mode": "custom", "names": names}, [{"name": n} for n in names]
    raise LabelError("未知的类别模式")


def sort_points(pts: list[list[float]]) -> list[list[float]]:
    """把任意顺序的四个点整理成 左上、左下、右下、右上。"""
    idx = sorted(range(4), key=lambda i: (pts[i][0], pts[i][1]))
    left = sorted(idx[:2], key=lambda i: pts[i][1])
    right = sorted(idx[2:], key=lambda i: pts[i][1])
    return [pts[left[0]], pts[left[1]], pts[right[1]], pts[right[0]]]


def clean_annotations(raw: list[Any], n_classes: int, width: int, height: int) -> list[dict[str, Any]]:
    """校验、裁剪到图像范围并保留两位小数。"""
    if len(raw) > MAX_ANNOTATIONS_PER_IMAGE:
        raise LabelError(f"单张图片标注数量不能超过 {MAX_ANNOTATIONS_PER_IMAGE}")
    out = []
    for a in raw:
        cls = int(a["cls"])
        if not 0 <= cls < n_classes:
            raise LabelError(f"类别编号 {cls} 超出范围")
        pts = a["pts"]
        if len(pts) != 4:
            raise LabelError("每个装甲板必须是 4 个点")
        clean_pts = []
        for p in pts:
            if len(p) != 2:
                raise LabelError("点坐标格式错误")
            x, y = float(p[0]), float(p[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                raise LabelError("点坐标非法")
            clean_pts.append([round(min(max(x, 0.0), width), 2), round(min(max(y, 0.0), height), 2)])
        out.append({"cls": cls, "pts": clean_pts})
    return out


def flip_idx(order: str) -> list[int]:
    """水平翻转时关键点的对应关系（Ultralytics data.yaml 里的 flip_idx）。"""
    perm = POINT_ORDERS[order]["perm"]
    mirror = [3, 2, 1, 0]  # 左上<->右上, 左下<->右下
    pos = {c: k for k, c in enumerate(perm)}
    return [pos[mirror[c]] for c in perm]


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def format_label_lines(
    annotations: list[dict[str, Any]],
    width: int,
    height: int,
    fmt: str,
    order: str,
    classes: list[dict[str, Any]],
) -> list[str]:
    perm = POINT_ORDERS[order]["perm"]
    lines = []
    for a in annotations:
        cls = a["cls"]
        pts = [a["pts"][i] for i in perm]
        norm = [(_clamp01(x / width), _clamp01(y / height)) for x, y in pts]
        xs = [p[0] for p in norm]
        ys = [p[1] for p in norm]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        box = f"{(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}"
        kpts = " ".join(f"{x:.6f} {y:.6f}" for x, y in norm)
        if fmt == "yolo_pose":
            lines.append(f"{cls} {box} {kpts}")
        elif fmt == "rm4":
            lines.append(f"{cls} {kpts}")
        elif fmt == "yolo_det":
            lines.append(f"{cls} {box}")
        elif fmt == "sjtu":
            c = classes[cls]
            lines.append(f"{_COLOR_BY_KEY[c['color']]['sjtu']} {_TAG_BY_KEY[c['tag']]['sjtu']} {kpts}")
        else:  # pragma: no cover
            raise LabelError(f"未知格式 {fmt}")
    return lines


def _sjtu_to_cls(color_i: int, tag_i: int, classes: list[dict[str, Any]]) -> int | None:
    color = next((c["key"] for c in ARMOR_COLORS if c["sjtu"] == color_i), None)
    tag = next((t["key"] for t in ARMOR_TAGS if t["sjtu"] == tag_i), None)
    for i, c in enumerate(classes):
        if c.get("color") == color and c.get("tag") == tag:
            return i
    return None


def parse_label_text(
    text: str,
    width: int,
    height: int,
    classes: list[dict[str, Any]],
    fmt: str = "auto",
    order: str = DEFAULT_POINT_ORDER,
) -> tuple[list[dict[str, Any]], int]:
    """解析 YOLO 风格的标签文本，返回 (标注, 跳过的行数)。

    fmt=auto 时按每行数字个数判断：9=RM四点，10=双标签，13=YOLO Pose，17=YOLO Pose(带可见性)。
    坐标全部 <= 1.5 视为归一化坐标，否则视为像素坐标。
    """
    perm = POINT_ORDERS.get(order, POINT_ORDERS[DEFAULT_POINT_ORDER])["perm"]
    is_armor = bool(classes) and "color" in classes[0]
    out: list[dict[str, Any]] = []
    skipped = 0
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            vals = [float(v) for v in parts]
        except ValueError:
            skipped += 1
            continue
        n = len(vals)
        kind = fmt
        if kind == "auto":
            kind = {9: "rm4", 10: "sjtu", 13: "yolo_pose", 17: "yolo_pose_vis"}.get(n, "")
        if kind == "yolo_pose" and n == 17:
            kind = "yolo_pose_vis"
        cls: int | None
        if kind == "rm4" and n >= 9:
            cls, coords = int(vals[0]), vals[1:9]
        elif kind == "sjtu" and n >= 10 and is_armor:
            cls, coords = _sjtu_to_cls(int(vals[0]), int(vals[1]), classes), vals[2:10]
        elif kind == "yolo_pose" and n >= 13:
            cls, coords = int(vals[0]), vals[5:13]
        elif kind == "yolo_pose_vis" and n >= 17:
            cls = int(vals[0])
            coords = [vals[5], vals[6], vals[8], vals[9], vals[11], vals[12], vals[14], vals[15]]
        else:
            skipped += 1
            continue
        if cls is None or not 0 <= cls < len(classes):
            skipped += 1
            continue
        normalized = max(coords) <= 1.5
        sx, sy = (width, height) if normalized else (1, 1)
        given = [[coords[2 * k] * sx, coords[2 * k + 1] * sy] for k in range(4)]
        canon: list[list[float]] = [[0.0, 0.0]] * 4
        for k, c in enumerate(perm):
            canon[c] = given[k]
        out.append({"cls": cls, "pts": canon})
    return clean_annotations(out, len(classes), width, height), skipped


def meta() -> dict[str, Any]:
    return {
        "armor_colors": ARMOR_COLORS,
        "armor_tags": ARMOR_TAGS,
        "export_formats": EXPORT_FORMATS,
        "point_orders": [{"key": k, "name": v["name"]} for k, v in POINT_ORDERS.items()],
    }
