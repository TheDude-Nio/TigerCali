"""端到端流程测试：注册 → 建任务 → 上传 → 分配 → 标注 → 提交 → 审核 → 导出。"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="tigercali-test-")
os.environ["TIGERCALI_DATA_DIR"] = _tmp
os.environ["TIGERCALI_FRONTEND_DIST"] = str(Path(_tmp) / "no-dist")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image as PILImage  # noqa: E402

from app import labels  # noqa: E402
from app.main import app  # noqa: E402


def jpeg(color: tuple[int, int, int], size: tuple[int, int] = (640, 480)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def client_for(username: str, school: str = "广东工业大学") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": username, "password": "secret123", "school": school})
    assert r.status_code == 200, r.text
    return c


ARMOR = {"mode": "armor", "colors": ["B", "R"], "tags": ["G", "1", "2", "3", "4", "5", "O", "Bs", "Bb"]}


@pytest.fixture(scope="module")
def world() -> dict:
    admin = client_for("admin")
    alice = client_for("alice")
    bob = client_for("bob", "华南理工大学")
    r = admin.post("/api/tasks", json={"name": "测试任务", "description": "# 要求", "label_config": ARMOR})
    assert r.status_code == 200, r.text
    task = r.json()
    ids = {u: c.get("/api/auth/me").json()["id"] for u, c in (("admin", admin), ("alice", alice), ("bob", bob))}
    return {"admin": admin, "alice": alice, "bob": bob, "task": task, "ids": ids}


def test_auth_rules() -> None:
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"username": "x", "password": "123456", "school": "某大学"}).status_code == 400
    assert c.post("/api/auth/register", json={"username": "shortpw", "password": "1", "school": "某大学"}).status_code == 400
    client_for("dupe")
    r = c.post("/api/auth/register", json={"username": "DUPE", "password": "123456", "school": "某大学"})
    assert r.status_code == 409
    assert c.post("/api/auth/login", json={"username": "dupe", "password": "wrong!"}).status_code == 400
    assert c.post("/api/auth/login", json={"username": "Dupe", "password": "secret123"}).status_code == 200
    assert c.get("/api/auth/me").json()["username"] == "dupe"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_classes(world: dict) -> None:
    t = world["task"]
    assert len(t["classes"]) == 18
    assert t["classes"][0]["name"] == "B_G"
    assert t["classes"][10]["name"] == "R_1"
    assert t["my_role"] == "owner" and t["is_manager"]


def test_full_flow(world: dict) -> None:
    admin, alice, bob = world["admin"], world["alice"], world["bob"]
    tid = world["task"]["id"]
    ids = world["ids"]

    # 搜索用户 & 学校
    schools = {s["school"] for s in admin.get("/api/schools").json()}
    assert {"广东工业大学", "华南理工大学"} <= schools
    found = admin.get("/api/users", params={"school": "华南理工大学", "task_id": tid}).json()
    assert [u["username"] for u in found] == ["bob"]

    # 非成员看不到任务
    assert alice.get(f"/api/tasks/{tid}").status_code == 404

    # 上传：3 张散图 + 一个含 5 张图和标签的 zip + 1 张重复
    files = [("files", (f"seq/frame_{i}.jpg", jpeg((i * 20, 0, 0)), "image/jpeg")) for i in (1, 2, 10)]
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        for i in range(5):
            zf.writestr(f"images/z_{i}.jpg", jpeg((0, i * 30, 0)))
        # RM 四点格式预标注：左上 左下 右下 右上
        zf.writestr("labels/z_0.txt", "10 0.1 0.1 0.1 0.2 0.3 0.2 0.3 0.1\n")
        zf.writestr("images/dup.jpg", jpeg((20, 0, 0)))  # 与 frame_1 相同
    files.append(("files", ("pack.zip", zbuf.getvalue(), "application/zip")))
    r = admin.post(f"/api/tasks/{tid}/images", files=files)
    assert r.status_code == 200, r.text
    up = r.json()
    assert up["added"] == 8 and up["duplicates"] == 1, up
    assert up["labels"]["matched"] == 1

    all_list = admin.get(f"/api/tasks/{tid}/image-list", params={"assignee": "all"}).json()["items"]
    names = [i["filename"] for i in all_list]
    # 自然排序
    assert names.index("seq/frame_2.jpg") < names.index("seq/frame_10.jpg")
    z0 = next(i for i in all_list if i["filename"] == "images/z_0.jpg")
    d = admin.get(f"/api/images/{z0['id']}").json()
    assert d["annotations"][0]["cls"] == 10
    assert d["annotations"][0]["pts"][0] == [64.0, 48.0]

    # 缩略图和原图
    assert admin.get(f"/api/images/{z0['id']}/thumb").status_code == 200
    assert admin.get(f"/api/images/{z0['id']}/file").headers["content-type"] == "image/jpeg"

    # 加成员并分配：alice 60%，bob 40%
    r = admin.post(f"/api/tasks/{tid}/members", json={"user_ids": [ids["alice"], ids["bob"]]})
    assert r.json()["added"] == 2
    r = admin.post(
        f"/api/tasks/{tid}/assign",
        json={"mode": "ratio", "entries": [{"user_id": ids["alice"], "value": 60}, {"user_id": ids["bob"], "value": 40}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["assigned"] == {str(ids["alice"]): 5, str(ids["bob"]): 3}  # 8 * 0.6 = 4.8 → 5

    # 一键均分（回收未完成的重新分）
    r = admin.post(
        f"/api/tasks/{tid}/assign",
        json={
            "mode": "even",
            "entries": [{"user_id": ids["alice"]}, {"user_id": ids["bob"]}],
            "reclaim": True,
            "order": "random",
        },
    )
    assert r.json()["assigned"] == {str(ids["alice"]): 4, str(ids["bob"]): 4}
    assert r.json()["remaining"] == 0

    # alice 看到自己的任务和图片
    tasks = alice.get("/api/tasks").json()
    assert tasks[0]["my_assigned"] == 4 and tasks[0]["my_done"] == 0
    mine = alice.get(f"/api/tasks/{tid}/image-list").json()["items"]
    assert len(mine) == 4
    # 标注员不能看别人的列表
    assert alice.get(f"/api/tasks/{tid}/image-list", params={"assignee": "all"}).status_code == 403

    # alice 不能改 bob 的图
    bob_img = bob.get(f"/api/tasks/{tid}/image-list").json()["items"][0]
    r = alice.put(f"/api/images/{bob_img['id']}/annotations", json={"annotations": [], "version": 0})
    assert r.status_code == 403

    # 提交前必须全部完成
    assert alice.post(f"/api/tasks/{tid}/submit").status_code == 409

    ann = {"cls": 3, "pts": [[10, 10], [10, 30], [60, 30], [60, 10]]}
    for it in mine:
        det = alice.get(f"/api/images/{it['id']}").json()
        r = alice.put(
            f"/api/images/{it['id']}/annotations",
            json={"annotations": [ann], "version": det["version"], "done": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"
    # 版本冲突
    r = alice.put(f"/api/images/{mine[0]['id']}/annotations", json={"annotations": [], "version": 0})
    assert r.status_code == 409
    # 越界坐标会被裁剪，非法类别被拒绝
    det = alice.get(f"/api/images/{mine[0]['id']}").json()
    r = alice.put(
        f"/api/images/{mine[0]['id']}/annotations",
        json={"annotations": [{"cls": 99, "pts": [[0, 0]] * 4}], "version": det["version"]},
    )
    assert r.status_code == 400

    prog = alice.get(f"/api/tasks/{tid}/my-progress").json()
    assert prog["done"] == 4 and prog["done_today"] == 4

    assert alice.post(f"/api/tasks/{tid}/submit").status_code == 200
    # 提交后不能再改，除非撤回
    r = alice.put(f"/api/images/{mine[0]['id']}/annotations", json={"annotations": [], "version": det["version"]})
    assert r.status_code == 403

    # 管理员标记一张有问题并打回
    r = admin.post(f"/api/images/{mine[1]['id']}/flag", json={"flagged": True, "note": "左上点偏了"})
    assert r.status_code == 200
    r = admin.post(f"/api/tasks/{tid}/members/{ids['alice']}/review", json={"action": "reject", "comment": "请修改"})
    assert r.json()["status"] == "rejected"
    reworked = alice.get(f"/api/images/{mine[1]['id']}").json()
    assert reworked["status"] == "rework" and reworked["review_note"] == "左上点偏了"
    assert alice.post(f"/api/tasks/{tid}/submit").status_code == 409
    r = alice.post(f"/api/images/{mine[1]['id']}/done")
    assert r.json()["status"] == "done"
    assert alice.post(f"/api/tasks/{tid}/submit").status_code == 200
    r = admin.post(f"/api/tasks/{tid}/members/{ids['alice']}/review", json={"action": "approve"})
    assert r.json() == {"status": "approved", "task_finished": False}

    # bob 完成：用 done 接口确认空图
    for it in bob.get(f"/api/tasks/{tid}/image-list").json()["items"]:
        assert bob.post(f"/api/images/{it['id']}/done").status_code == 200
    assert bob.post(f"/api/tasks/{tid}/submit").status_code == 200
    r = admin.post(f"/api/tasks/{tid}/members/{ids['bob']}/review", json={"action": "approve"})
    assert r.json()["task_finished"] is True
    assert admin.get(f"/api/tasks/{tid}").json()["status"] == "finished"

    stats = admin.get(f"/api/tasks/{tid}/stats").json()
    assert stats["total"] == 8 and stats["done"] == 8 and stats["unassigned"] == 0
    assert {m["username"]: m["status"] for m in stats["members"]}["alice"] == "approved"

    # 分页 + 随机
    page = admin.get(f"/api/tasks/{tid}/images", params={"page_size": 3, "order": "random", "seed": 7}).json()
    assert page["total"] == 8 and len(page["items"]) == 3

    # 导出预览
    pv = admin.get(f"/api/tasks/{tid}/export", params={"scope": "approved", "val_ratio": 0.25, "preview": True}).json()
    assert pv["images"] == 8 and pv["val"] == 2 and pv["train"] == 6

    # 导出 YOLO Pose
    r = admin.get(f"/api/tasks/{tid}/export", params={"fmt": "yolo_pose", "scope": "approved", "val_ratio": 0.25})
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert zf.testzip() is None
    names = zf.namelist()
    assert "data.yaml" in names and "README.txt" in names
    label_files = [n for n in names if n.startswith("labels/")]
    img_files = [n for n in names if n.startswith("images/")]
    assert len(label_files) == 8 and len(img_files) == 8
    assert sum(1 for n in label_files if n.startswith("labels/val/")) == 2
    yaml = zf.read("data.yaml").decode()
    assert "kpt_shape: [4, 2]" in yaml and "flip_idx: [3, 2, 1, 0]" in yaml
    lines = [
        zf.read(n).decode().strip()
        for n in label_files
        if zf.read(n).decode().strip()
    ]
    rows = [ln.split() for text in lines for ln in text.splitlines()]
    assert rows and all(len(p) == 13 for p in rows)
    # alice 标的 cls=3，预标注 cls=10
    assert {p[0] for p in rows} <= {"3", "10"} and "3" in {p[0] for p in rows}
    # 图片完整
    first_img = img_files[0]
    PILImage.open(io.BytesIO(zf.read(first_img))).verify()

    # 其他格式
    for fmt, n in (("rm4", 9), ("sjtu", 10), ("yolo_det", 5)):
        r = admin.get(f"/api/tasks/{tid}/export", params={"fmt": fmt, "include_images": False, "include_empty": False})
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        txt = [zf.read(x).decode().split() for x in zf.namelist() if x.startswith("labels/")]
        assert txt and all(len(p) == n for p in txt), fmt
    r = admin.get(f"/api/tasks/{tid}/export", params={"fmt": "json", "include_images": False})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "annotations.json" in zf.namelist()

    # 标注员不能导出
    assert alice.get(f"/api/tasks/{tid}/export").status_code == 403


def test_label_config_remap(world: dict) -> None:
    admin = world["admin"]
    r = admin.post("/api/tasks", json={"name": "remap", "label_config": {"mode": "armor", "colors": ["R"], "tags": ["1", "3"]}})
    tid = r.json()["id"]
    admin.post(f"/api/tasks/{tid}/images", files=[("files", ("a.jpg", jpeg((1, 2, 3)), "image/jpeg"))])
    img = admin.get(f"/api/tasks/{tid}/image-list", params={"assignee": "all"}).json()["items"][0]
    admin.put(
        f"/api/images/{img['id']}/annotations",
        json={"annotations": [{"cls": 1, "pts": [[1, 1], [1, 5], [9, 5], [9, 1]]}], "version": 0},
    )
    # 增加颜色 B（排在 R 前面）→ R_3 的 id 从 1 变成 3
    r = admin.patch(f"/api/tasks/{tid}", json={"label_config": {"mode": "armor", "colors": ["B", "R"], "tags": ["1", "3"]}})
    assert r.status_code == 200, r.text
    d = admin.get(f"/api/images/{img['id']}").json()
    assert d["annotations"][0]["cls"] == 3
    # 删除已使用的类别被拒绝
    r = admin.patch(f"/api/tasks/{tid}", json={"label_config": {"mode": "armor", "colors": ["B"], "tags": ["1", "3"]}})
    assert r.status_code == 400
    # 删除任务
    assert admin.delete(f"/api/tasks/{tid}").status_code == 200


def test_label_helpers() -> None:
    pts = [[60, 10], [10, 30], [10, 10], [60, 30]]
    assert labels.sort_points(pts) == [[10, 10], [10, 30], [60, 30], [60, 10]]
    assert labels.flip_idx("tl_tr_br_bl") == [1, 0, 3, 2]
    anns, skipped = labels.parse_label_text(
        "0 0.5 0.5 0.2 0.2 0.4 0.4 0.4 0.6 0.6 0.6 0.6 0.4\nbad line\n", 100, 100, [{"name": "a"}], "auto"
    )
    assert skipped == 1 and anns[0]["pts"] == [[40, 40], [40, 60], [60, 60], [60, 40]]


def test_attachments_and_split(world: dict) -> None:
    admin = world["admin"]
    tid = world["task"]["id"]
    buf = io.BytesIO()
    PILImage.new("RGB", (10, 10)).save(buf, "PNG")
    r = admin.post(f"/api/tasks/{tid}/attachments", files={"file": ("x.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    url = r.json()["url"]
    assert admin.get(url).status_code == 200
    assert world["bob"].get(url).status_code == 200
    assert client_for("stranger").get(url).status_code == 404
