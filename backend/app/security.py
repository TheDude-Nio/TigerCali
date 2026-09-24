from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

_N, _R, _P = 2**14, 8, 1


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        expect = base64.b64decode(dk)
        calc = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expect)
        )
        return hmac.compare_digest(calc, expect)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginLimiter:
    """同一 IP + 用户名 10 分钟内最多失败 10 次。"""

    def __init__(self, max_fail: int = 10, window: float = 600) -> None:
        self.max_fail = max_fail
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._fails.get(key)
            if not q:
                return False
            self._prune(q, now)
            return len(q) >= self.max_fail

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    # 用作普通计数器时更直观的名字
    hit = fail


login_limiter = LoginLimiter()
# 同一 IP 每小时最多注册 200 个账号：挡住脚本刷号，又不会误伤整个实验室共用一个出口 IP 集中注册
register_limiter = LoginLimiter(max_fail=200, window=3600)
