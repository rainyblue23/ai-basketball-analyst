# -*- coding: utf-8 -*-
"""登录：少量固定账号 + 签名会话 cookie + 本地豁免。

设计（用户 2026-10-05 定）：
  * 账号存 `data/accounts.json`（或环境变量 `AIHOOP_ACCOUNTS`），密码只存 **PBKDF2-SHA256 加盐哈希**；
  * 会话用 **随机令牌 + SQLite 会话记录**（可撤销，重启后端不失效），`HttpOnly` + `SameSite=Lax`；
  * **本地豁免**：回环地址（127.0.0.1/::1）且带内部令牌（`AIHOOP_INTERNAL_TOKEN`）时放行 ——
    这样门禁里的 API 集成测试与真机核对脚本继续可用，浏览器一律走登录。

本模块不依赖产品其它模块；浏览器与接口共用会话。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DATA = Path(os.environ.get("AIHOOP_DATA_DIR") or
            Path(__file__).resolve().parents[2] / "data").expanduser().resolve()
COOKIE_NAME = "aihoop_session"
SESSION_TTL_S = int(os.environ.get("AIHOOP_SESSION_TTL", str(8 * 3600)))
PBKDF2_ROUNDS = 120_000


# ---------------- 账号 ----------------
def hash_password(password: str, salt: Optional[str] = None) -> dict:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return {"salt": salt, "hash": base64.b64encode(dk).decode("ascii"), "rounds": PBKDF2_ROUNDS}


def verify_password(password: str, rec: dict) -> bool:
    if not password or not isinstance(rec, dict) or not rec.get("salt") or not rec.get("hash"):
        return False
    try:
        rounds = int(rec.get("rounds") or PBKDF2_ROUNDS)
        if not 10000 <= rounds <= 2000000 or len(password) > 256:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), str(rec["salt"]).encode("utf-8"), rounds)
        return hmac.compare_digest(base64.b64encode(dk).decode("ascii"), str(rec["hash"]))
    except (ValueError, TypeError, OverflowError):
        return False



def load_accounts() -> dict:
    raw = os.environ.get("AIHOOP_ACCOUNTS", "").strip()
    if raw:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    p = DATA / "accounts.json"
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_account(username: str, password: str) -> None:
    acc = load_accounts()
    acc[username] = hash_password(password)
    p = DATA / "accounts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------------- 会话 ----------------
@contextmanager
def _db():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "auth.sqlite", timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, username TEXT, fingerprint TEXT, expires REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS attempts (host TEXT, at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS registration_attempts (host TEXT, at REAL)")
    try:
        with c:
            yield c
    finally:
        c.close()


def _fingerprint(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()


def issue_session(username: str) -> str:
    rec = load_accounts().get(username)
    if not rec:
        raise ValueError("账号不存在")
    token = secrets.token_urlsafe(32)
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
        c.execute("INSERT INTO sessions VALUES (?,?,?,?)", (
            hashlib.sha256(token.encode()).hexdigest(), username, _fingerprint(rec), time.time()+SESSION_TTL_S))
    return token


def read_session(token: str) -> Optional[str]:
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return None
    with _db() as c:
        row = c.execute("SELECT username,fingerprint,expires FROM sessions WHERE id=?",
                        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row or row[2] <= time.time():
        return None
    rec = load_accounts().get(row[0])
    return row[0] if rec and hmac.compare_digest(row[1], _fingerprint(rec)) else None


def revoke_session(token):
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE id=?", (hashlib.sha256(token.encode()).hexdigest(),))


def login_allowed(host):
    # Shared by workers; count all attempts before password hashing.
    now = time.time()
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM attempts WHERE at<?", (now-60,))
        count = c.execute("SELECT COUNT(*) FROM attempts WHERE host=?", (host,)).fetchone()[0]
        if count >= 10:
            return False
        c.execute("INSERT INTO attempts VALUES (?,?)", (host, now))
    return True


def register_allowed(host):
    """限制同一来源每小时最多尝试注册 10 次，跨进程共享计数。"""
    now = time.time()
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM registration_attempts WHERE at<?", (now-3600,))
        count = c.execute("SELECT COUNT(*) FROM registration_attempts WHERE host=?", (host,)).fetchone()[0]
        if count >= 10:
            return False
        c.execute("INSERT INTO registration_attempts VALUES (?,?)", (host, now))
    return True


def internal_ok(client_host: str, token: str = "") -> bool:
    """仅回环地址且配置了正确内部令牌时豁免，不以来源地址代替登录。"""
    want = os.environ.get("AIHOOP_INTERNAL_TOKEN", "").strip()
    return (client_host in ("127.0.0.1", "::1") and bool(want) and
            bool(token) and hmac.compare_digest(str(token), want))


def main():
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description="创建账号或重设密码（原会话随之失效）")
    parser.add_argument("username")
    args = parser.parse_args()
    if os.environ.get("AIHOOP_ACCOUNTS", "").strip():
        parser.error("正在使用环境变量账号，请先移除 AIHOOP_ACCOUNTS 再管理本地账号")
    name = args.username.strip()
    if not name or len(name) > 64:
        parser.error("用户名长度需为 1–64 个字符")
    password = getpass.getpass("新密码（至少 10 位）: ")
    if len(password) < 10 or len(password) > 256:
        parser.error("密码长度需为 10–256 个字符")
    if password != getpass.getpass("再次输入密码: "):
        parser.error("两次密码不一致")
    save_account(name, password)
    print("账号已保存。重设密码后，原登录会话失效。")


if __name__ == "__main__":
    main()
