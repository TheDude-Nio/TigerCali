"""模型预标注：后处理单测 + 接口测试。推理函数用 monkeypatch 替换，测试不依赖 33MB 的模型文件。"""
from __future__ import annotations

import io
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 单独运行本文件时也用临时数据目录，绝不碰仓库里的 data/
_tmp = tempfile.mkdtemp(prefix="tigercali-test-")
os.environ.setdefault("TIGERCALI_DATA_DIR", _tmp)
os.environ.setdefault("TIGERCALI_FRONTEND_DIST", str(Path(_tmp) / "no-dist"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image as PILImage  # noqa: E402

from app import smart  # noqa: E402
from app.main import app  # noqa: E402

COL = {c: i for i, c in enumerate(smart.COLORS)}
TAG = {t: i for i, t in enumerate(smart.TAGS)}


def row(pts: list[float], logit: float, color: str, tag: str) -> np.ndarray:
    r = np.full(smart.ROW_LEN, -5.0, dtype=np.float32)
    r[:8] = pts
    r[8] = logit
    r[9 + COL[color]] = 5.0
    r[13 + TAG[tag]] = 5.0
    return r


# 左上、左下、右下、右上
BOX_A = [100, 100, 100, 140, 200, 140, 200, 100]


def test_decode_threshold_scale_nms_and_order() -> None:
    out = np.stack(
        [
            row([v + 5 for v in BOX_A], 1.0, "B", "1"),  # 与 A 重叠、置信度低 → 被 NMS 去掉
            row(BOX_A, 2.0, "R", "3"),
            row([400, 400, 400, 420, 450, 420, 450, 400], -0.5, "B", "2"),  # logit<0（conf<0.5）→ 丢弃
            row([200, 100, 200, 140, 300, 140, 300, 100], 0.5, "B", "Bb"),  # 与 A 共边（交集面积 0）→ 保留
            row([200, 140, 200, 180, 300, 180, 300, 140], 0.3, "P", "O"),  # 与 A 只有角点接触 → 保留
        ]
    )[None]
    dets = smart.decode(out, scale=0.5)
    assert [(d["color"], d["tag"]) for d in dets] == [("R", "3"), ("B", "Bb"), ("P", "O")]
    assert dets[0]["conf"] == pytest.approx(1 / (1 + math.exp(-2.0)), abs=1e-4)
    # 坐标 ÷ scale 还原到原图，点序保持 左上、左下、右下、右上
    assert dets[0]["pts"] == [[200, 200], [200, 280], [400, 280], [400, 200]]


def test_decode_empty() -> None:
    assert smart.decode(np.full((1, 3, smart.ROW_LEN), -1.0, dtype=np.float32), 1.0) == []


def test_preprocess_letterbox() -> None:
    x, scale = smart.preprocess(PILImage.new("RGB", (1280, 1024), (255, 0, 0)))
    assert x.shape == (1, 3, 640, 640) and x.dtype == np.float32
    assert scale == 0.5
    assert x[0, :, 0, 0].tolist() == pytest.approx([1.0, 0.0, 0.0])  # 左上是原图（RGB）
    assert x[0, :, 600, 0].tolist() == pytest.approx([127 / 255] * 3)  # 下方空白填 127


def jpeg(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def client_for(username: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": username, "password": "secret123", "school": "广东工业大学"})
    assert r.status_code == 200, r.text
    return c


FAKE_DETS = [
    {"color": "R", "tag": "3", "conf": 0.9, "pts": [[-10.0, 10.0], [10.0, 50.0], [90.0, 50.0], [90.0, 10.0]]},
    {"color": "P", "tag": "1", "conf": 0.8, "pts": [[200.0, 10.0], [200.0, 50.0], [260.0, 50.0], [260.0, 10.0]]},
]


@pytest.fixture(scope="module")
def world() -> dict:
    admin = client_for("smart_admin")
    ann = client_for("smart_ann")
    cfg = {"mode": "armor", "colors": ["B", "R"], "tags": ["G", "1", "2", "3", "4", "5", "O", "Bs", "Bb"]}
    tid = admin.post("/api/tasks", json={"name": "预标注", "label_config": cfg}).json()["id"]
    files = [("files", (f"f{i}.jpg", jpeg((320, 240), (i * 40, 10, 10)), "image/jpeg")) for i in range(4)]
    assert admin.post(f"/api/tasks/{tid}/images", files=files).json()["added"] == 4
    other = admin.post("/api/tasks", json={"name": "别的任务", "label_config": cfg}).json()["id"]
    admin.post(f"/api/tasks/{other}/images", files=[("files", ("x.jpg", jpeg((320, 240), (1, 2, 3)), "image/jpeg"))])
    custom = admin.post("/api/tasks", json={"name": "自定义", "label_config": {"mode": "custom", "names": ["car"]}}).json()["id"]
    admin.post(f"/api/tasks/{custom}/images", files=[("files", ("c.jpg", jpeg((320, 240), (9, 9, 9)), "image/jpeg"))])
    ann_id = ann.get("/api/auth/me").json()["id"]
    admin.post(f"/api/tasks/{tid}/members", json={"user_ids": [ann_id]})
    # 按文件名前两张分给标注员，后两张不分
    r = admin.post(f"/api/tasks/{tid}/assign", json={"mode": "count", "entries": [{"user_id": ann_id, "value": 2}]})
    assert r.status_code == 200, r.text
    imgs = admin.get(f"/api/tasks/{tid}/images", params={"page_size": 50}).json()["items"]
    return {
        "admin": admin,
        "ann": ann,
        "tid": tid,
        "imgs": sorted(imgs, key=lambda i: i["filename"]),
        "other_img": admin.get(f"/api/tasks/{other}/images").json()["items"][0]["id"],
        "custom_img": admin.get(f"/api/tasks/{custom}/images").json()["items"][0]["id"],
        "custom": custom,
    }


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(smart, "unavailable_reason", lambda: None)

    def predict(path: Path) -> list[dict]:
        calls.append(path)
        return [dict(d, pts=[p[:] for p in d["pts"]]) for d in FAKE_DETS]

    monkeypatch.setattr(smart, "predict", predict)
    return calls


def test_unavailable_without_model(world: dict) -> None:
    # 测试环境里没有模型文件
    assert TestClient(app).get("/api/meta").json()["smart_available"] is False
    r = world["admin"].post(f"/api/images/{world['imgs'][0]['id']}/smart")
    assert r.status_code == 503 and r.json()["detail"]  # 缺模型文件（或缺 onnxruntime）
    r = world["admin"].post(f"/api/tasks/{world['tid']}/smart", json={"ids": [world["imgs"][0]["id"]]})
    assert r.status_code == 503


def test_image_smart_maps_classes_and_does_not_save(world: dict, fake_model: list[Path]) -> None:
    assert TestClient(app).get("/api/meta").json()["smart_available"] is True
    img = next(i for i in world["imgs"] if i["assignee_id"])
    r = world["ann"].post(f"/api/images/{img['id']}/smart")
    assert r.status_code == 200, r.text
    body = r.json()
    # 任务启用了 B/R：R_3 → 下标 1*9+3=12；紫色没启用 → skipped；越界坐标裁剪到图内
    assert body["skipped"] == 1
    assert body["annotations"] == [{"cls": 12, "pts": [[0.0, 10.0], [10.0, 50.0], [90.0, 50.0], [90.0, 10.0]], "conf": 0.9}]
    assert world["ann"].get(f"/api/images/{img['id']}").json()["ann_count"] == 0  # 只预测、不落库


def test_image_smart_permissions(world: dict, fake_model: list[Path]) -> None:
    unassigned = next(i for i in world["imgs"] if not i["assignee_id"])
    assert world["ann"].post(f"/api/images/{unassigned['id']}/smart").status_code == 404
    assert world["ann"].post(f"/api/images/{world['other_img']}/smart").status_code == 404
    assert world["admin"].post(f"/api/images/{world['custom_img']}/smart").status_code == 400


def test_task_smart_fills_only_unlabeled_unfinished(world: dict, fake_model: list[Path]) -> None:
    admin, ann, tid = world["admin"], world["ann"], world["tid"]
    a, b, c, d = (i["id"] for i in world["imgs"])
    assigned = [i["id"] for i in world["imgs"] if i["assignee_id"]]
    # 一张已有标注、一张确认空图（done）
    labeled, empty_done = assigned
    cur = ann.get(f"/api/images/{labeled}").json()
    box = [[1.0, 1.0], [1.0, 9.0], [9.0, 9.0], [9.0, 1.0]]
    assert ann.put(
        f"/api/images/{labeled}/annotations", json={"annotations": [{"cls": 0, "pts": box}], "version": cur["version"]}
    ).status_code == 200
    assert ann.post(f"/api/images/{empty_done}/done").status_code == 200

    assert ann.post(f"/api/tasks/{tid}/smart", json={"ids": [a]}).status_code == 403
    assert admin.post(f"/api/tasks/{tid}/smart", json={"ids": []}).status_code == 422
    assert admin.post(f"/api/tasks/{tid}/smart", json={"ids": list(range(51))}).status_code == 422
    assert admin.post(f"/api/tasks/{world['custom']}/smart", json={"ids": [world["custom_img"]]}).status_code == 400

    r = admin.post(f"/api/tasks/{tid}/smart", json={"ids": [a, b, c, d, d, world["other_img"]]})
    assert r.status_code == 200, r.text
    todo = [x for x in (a, b, c, d) if x not in assigned]
    # 4 张里只有 2 张没标注且未完成；别的任务的图 + 已标注 + 空图确认 → skipped
    assert r.json() == {"filled": 2, "annotations": 2, "skipped_images": 3}
    assert len(fake_model) == 2
    for x in todo:
        det = admin.get(f"/api/images/{x}").json()
        assert det["ann_count"] == 1 and det["status"] == "todo" and det["version"] == 1
        assert det["annotations"] == [{"cls": 12, "pts": [[0.0, 10.0], [10.0, 50.0], [90.0, 50.0], [90.0, 10.0]]}]
    assert admin.get(f"/api/images/{labeled}").json()["annotations"] == [{"cls": 0, "pts": box}]
    assert admin.get(f"/api/images/{empty_done}").json()["ann_count"] == 0
    # 再跑一次：都已有标注，什么也不做
    r = admin.post(f"/api/tasks/{tid}/smart", json={"ids": todo})
    assert r.json() == {"filled": 0, "annotations": 0, "skipped_images": 2}
