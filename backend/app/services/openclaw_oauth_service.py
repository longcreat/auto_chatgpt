"""
OpenClaw OAuth 回调 URL 获取服务

使用已有账号的邮箱 + 密码，纯 HTTP 逆向执行 OAuth 登录流程，
捕获 auth.openai.com 重定向到 redirect_uri 的完整回调 URL，
供用户粘贴回 OpenClaw 完成鉴权。

流程（与 oauth_login 相比，不交换 token，也不生成自己的 PKCE）：
  1. GET  given_auth_url         → login_session cookie  (使用 OpenClaw 的 code_challenge)
  2. POST authorize/continue     → 提交邮箱 (+ sentinel)
  3. POST password/verify        → 提交密码 (+ sentinel)
  3b.如有 OTP 要求              → IMAP 等待验证码
  4. Follow consent redirects   → 提取完整 callback URL (含 state)
"""

import logging
import re
import time
import random
import threading
import uuid
import traceback
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode

from app.services.registration_service import (
    ChatGPTRegistrar,
    _human_delay,
    _build_sentinel_token,
    _make_trace_headers,
    _extract_code_from_url,
    OAUTH_ISSUER,
    OAUTH_REDIRECT_URI,
)

logger = logging.getLogger(__name__)


def _extract_full_callback_url(url: str, redirect_uri_base: str) -> Optional[str]:
    """从 URL 中识别是否是 redirect_uri 的回调，是则返回完整 URL（含 code + state）"""
    if not url:
        return None
    parsed = urlparse(url)
    target = urlparse(redirect_uri_base)
    # 主机 + 端口 + 路径必须匹配
    if (parsed.scheme == target.scheme and
            parsed.netloc == target.netloc and
            parsed.path == target.path and
            "code=" in (parsed.query or "")):
        return url
    return None


class OpenClawOAuthFlow:
    """
    使用 OpenClaw 提供的 auth_url 和已知邮箱密码执行 OAuth 登录，
    捕获完整 callback URL（不交换 token）。
    """

    def __init__(self, proxy: str = None, log_fn=None):
        self._log = log_fn or (lambda msg: logger.info(msg))
        self._reg = ChatGPTRegistrar(proxy=proxy, log_fn=self._log)

    # ── 完整回调 URL 追跟器（与 _oauth_follow_for_code 类似，但返回完整 URL）
    def _follow_for_callback(self, start_url: str, redirect_uri: str,
                             max_hops: int = 15) -> Optional[str]:
        target = urlparse(redirect_uri)
        current = start_url
        for hop in range(max_hops):
            try:
                r = self._reg.session.get(current, headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                }, allow_redirects=False, timeout=30)
            except Exception as e:
                # curl_cffi 在 redirect 到 localhost 时常抛 ConnectionError
                error_str = str(e)
                m = re.search(r'(https?://[^\s\'"]+)', error_str)
                if m:
                    cb = _extract_full_callback_url(m.group(1), redirect_uri)
                    if cb:
                        return cb
                    # 尝试从异常信息直接拼出 redirect 目标
                    if "localhost" in error_str or "127.0.0.1" in error_str:
                        lm = re.search(
                            r'localhost[:/][^\s\'"]*|127\.0\.0\.1[:/][^\s\'"]*',
                            error_str
                        )
                        if lm:
                            guess = f"{target.scheme}://{lm.group(0)}"
                            cb = _extract_full_callback_url(guess, redirect_uri)
                            if cb:
                                return cb
                self._log(f"[OpenClaw] hop {hop} 异常: {e}")
                return None

            current_url = str(r.url)
            cb = _extract_full_callback_url(current_url, redirect_uri)
            if cb:
                return cb

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if not loc:
                    return None
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                cb = _extract_full_callback_url(loc, redirect_uri)
                if cb:
                    return cb
                current = loc
                continue
            return None
        return None

    # ── Consent 流程（与 _oauth_consent_flow 类似，但返回完整 callback URL）
    def _consent_for_callback(self, consent_url: str, redirect_uri: str) -> Optional[str]:
        import json, base64
        from urllib.parse import unquote
        reg = self._reg
        try:
            # 4a: GET consent
            self._log(f"[OpenClaw-consent] GET {consent_url[:80]}")
            try:
                resp = reg.session.get(consent_url, headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                }, allow_redirects=False, timeout=30)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location", "")
                    if loc.startswith("/"):
                        loc = f"{OAUTH_ISSUER}{loc}"
                    cb = _extract_full_callback_url(loc, redirect_uri)
                    if cb:
                        return cb
                    return self._follow_for_callback(loc, redirect_uri)
            except Exception as e:
                m = re.search(r'(https?://[^\s\'"]+)', str(e))
                if m:
                    cb = _extract_full_callback_url(m.group(1), redirect_uri)
                    if cb:
                        return cb
                self._log(f"[OpenClaw-consent] GET 异常: {e}")

            # 4b: 解 oai-client-auth-session cookie
            jar = getattr(reg.session.cookies, "jar", None)
            session_data = None
            if jar:
                for c in jar:
                    if "oai-client-auth-session" in getattr(c, "name", ""):
                        raw = getattr(c, "value", "")
                        try:
                            decoded = unquote(raw).strip('"').strip("'")
                            part = decoded.split(".")[0] if "." in decoded else decoded
                            pad = 4 - len(part) % 4
                            if pad != 4:
                                part += "=" * pad
                            session_data = json.loads(base64.urlsafe_b64decode(part))
                        except Exception:
                            pass
                        break

            if not session_data:
                return None

            workspaces = session_data.get("workspaces", [])
            if not workspaces:
                return None
            ws_id = (workspaces[0] or {}).get("id")
            if not ws_id:
                return None
            self._log(f"[OpenClaw-consent] workspace_id={ws_id}")

            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": consent_url,
                "User-Agent": reg.ua,
                "oai-device-id": reg.device_id,
            }
            h.update(_make_trace_headers())

            # 4c: POST workspace/select
            r = reg.session.post(
                f"{OAUTH_ISSUER}/api/accounts/workspace/select",
                json={"workspace_id": ws_id},
                headers=h, allow_redirects=False, timeout=30,
            )
            self._log(f"[OpenClaw-consent] workspace/select → {r.status_code}")

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                cb = _extract_full_callback_url(loc, redirect_uri)
                if cb:
                    return cb
                return self._follow_for_callback(loc, redirect_uri)

            if r.status_code == 200:
                data = r.json()
                ws_next = data.get("continue_url", "")
                orgs = data.get("data", {}).get("orgs", [])
                if orgs:
                    org_id = (orgs[0] or {}).get("id")
                    projects = (orgs[0] or {}).get("projects", [])
                    project_id = projects[0].get("id") if projects else None
                    if org_id:
                        body = {"org_id": org_id}
                        if project_id:
                            body["project_id"] = project_id
                        org_url = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"
                        h2 = dict(h)
                        h2["Referer"] = org_url
                        r2 = reg.session.post(
                            f"{OAUTH_ISSUER}/api/accounts/organization/select",
                            json=body, headers=h2, allow_redirects=False, timeout=30,
                        )
                        self._log(f"[OpenClaw-consent] org/select → {r2.status_code}")
                        if r2.status_code in (301, 302, 303, 307, 308):
                            loc = r2.headers.get("Location", "")
                            if loc.startswith("/"):
                                loc = f"{OAUTH_ISSUER}{loc}"
                            cb = _extract_full_callback_url(loc, redirect_uri)
                            if cb:
                                return cb
                            return self._follow_for_callback(loc, redirect_uri)
                        if r2.status_code == 200:
                            next2 = r2.json().get("continue_url", ws_next)
                            if next2.startswith("/"):
                                next2 = f"{OAUTH_ISSUER}{next2}"
                            return self._follow_for_callback(next2, redirect_uri)
                if ws_next:
                    ws_full = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"
                    return self._follow_for_callback(ws_full, redirect_uri)
        except Exception as e:
            self._log(f"[OpenClaw-consent] 异常: {e}\n{traceback.format_exc()}")
        return None

    def run(self, auth_url: str, email: str, password: str,
            max_retries: int = 5) -> Dict[str, Any]:
        """
        主流程：使用 OpenClaw 提供的 auth_url 执行 HTTP 登录，
        返回 { success, callback_url, error, log }
        """
        # 解析 redirect_uri
        parsed_auth = urlparse(auth_url)
        params = parse_qs(parsed_auth.query)
        redirect_uri = params.get("redirect_uri", [OAUTH_REDIRECT_URI])[0]
        if not redirect_uri:
            redirect_uri = OAUTH_REDIRECT_URI

        self._log(f"[OpenClaw] 开始 OAuth 流程 email={email}")
        self._log(f"[OpenClaw] redirect_uri={redirect_uri}")

        reg = self._reg

        def _json_headers(referer: str) -> dict:
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": referer,
                "User-Agent": reg.ua,
                "oai-device-id": reg.device_id,
            }
            h.update(_make_trace_headers())
            return h

        # ── 步骤 1+2 带 Cloudflare 重试 ─────────────────────────
        r2_data = None
        for attempt in range(1, max_retries + 1):
            reg.session.cookies.set("oai-did", reg.device_id, domain=".auth.openai.com")
            reg.session.cookies.set("oai-did", reg.device_id, domain="auth.openai.com")

            # 1. GET given_auth_url  (直接使用 OpenClaw 的 code_challenge/state)
            self._log(f"[OpenClaw] 1/4 GET auth_url (attempt {attempt}/{max_retries})")
            try:
                r = reg.session.get(auth_url, headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                }, allow_redirects=True, timeout=30)
            except Exception as e:
                self._log(f"[OpenClaw] authorize 请求异常: {e}")
                if attempt < max_retries:
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 2.0)
                    reg._reinit_session()
                    continue
                return {"success": False, "callback_url": None,
                        "error": f"请求 auth.openai.com 失败: {e}"}

            if r.status_code == 403:
                self._log(f"[OpenClaw] authorize 403, 换指纹重试 ({attempt}/{max_retries})")
                if attempt < max_retries:
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 2.0)
                    reg._reinit_session()
                    continue
                return {"success": False, "callback_url": None,
                        "error": "auth.openai.com 持续返回 403，请检查代理/IP"}

            has_login = any(getattr(c, "name", "") == "login_session"
                            for c in reg.session.cookies)
            self._log(f"[OpenClaw] login_session={'有' if has_login else '无'}")

            # 2. POST authorize/continue (提交邮箱 + sentinel)
            self._log("[OpenClaw] 2/4 POST authorize/continue")
            sentinel = _build_sentinel_token(
                reg.session, reg.device_id, reg.ua, reg.sec_ch_ua,
                reg.impersonate, flow="authorize_continue", fp=reg.fp,
            )
            if not sentinel:
                self._log("[OpenClaw] sentinel 失败，换指纹重试")
                if attempt < max_retries:
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 2.0)
                    reg._reinit_session()
                    continue
                return {"success": False, "callback_url": None,
                        "error": "Sentinel token 获取失败"}

            h_cont = _json_headers(f"{OAUTH_ISSUER}/log-in")
            h_cont["openai-sentinel-token"] = sentinel
            try:
                r2 = reg.session.post(
                    f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                    json={"username": {"kind": "email", "value": email}},
                    headers=h_cont, timeout=30, allow_redirects=False,
                )
            except Exception as e:
                self._log(f"[OpenClaw] authorize/continue 异常: {e}")
                if attempt < max_retries:
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 2.0)
                    reg._reinit_session()
                    continue
                return {"success": False, "callback_url": None,
                        "error": f"authorize/continue 请求失败: {e}"}

            if r2.status_code == 403:
                self._log(f"[OpenClaw] authorize/continue 403，换指纹重试")
                if attempt < max_retries:
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 2.0)
                    reg._reinit_session()
                    continue
                return {"success": False, "callback_url": None,
                        "error": "authorize/continue 持续 403"}

            if r2.status_code != 200:
                return {"success": False, "callback_url": None,
                        "error": f"authorize/continue 失败 ({r2.status_code}): {r2.text[:200]}"}

            try:
                r2_data = r2.json()
                self._log(f"[OpenClaw] authorize/continue → {r2_data}")
            except Exception:
                r2_data = {}

            break  # 步骤 1-2 成功

        # ── 步骤 3: POST password/verify ────────────────────────
        self._log("[OpenClaw] 3/4 POST password/verify")
        sentinel_pwd = _build_sentinel_token(
            reg.session, reg.device_id, reg.ua, reg.sec_ch_ua,
            reg.impersonate, flow="password_verify", fp=reg.fp,
        )
        if not sentinel_pwd:
            return {"success": False, "callback_url": None,
                    "error": "password_verify sentinel 获取失败"}

        h_pwd = _json_headers(f"{OAUTH_ISSUER}/log-in/password")
        h_pwd["openai-sentinel-token"] = sentinel_pwd
        try:
            r3 = reg.session.post(
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                json={"password": password},
                headers=h_pwd, timeout=30, allow_redirects=False,
            )
        except Exception as e:
            return {"success": False, "callback_url": None,
                    "error": f"password/verify 请求异常: {e}"}

        if r3.status_code != 200:
            return {"success": False, "callback_url": None,
                    "error": f"密码验证失败 ({r3.status_code}): {r3.text[:200]}"}

        try:
            verify_data = r3.json()
        except Exception:
            verify_data = {}

        continue_url = verify_data.get("continue_url", "")
        page_type = (verify_data.get("page") or {}).get("type", "")
        self._log(f"[OpenClaw] password/verify → continue_url={continue_url} page={page_type}")

        # ── 步骤 3b: OTP 验证（如需要）──────────────────────────
        if page_type == "email_otp_verification" or "email-verification" in continue_url:
            self._log("[OpenClaw] 3b/4 需要邮箱 OTP 验证")
            from app.services.imap_service import wait_for_verification_email_sync
            from app.config import settings

            ev_url = continue_url if continue_url.startswith("http") else f"{OAUTH_ISSUER}{continue_url}"
            reg.session.get(ev_url, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{OAUTH_ISSUER}/log-in/password",
                "Upgrade-Insecure-Requests": "1",
            }, allow_redirects=True, timeout=30)

            self._log(f"[OpenClaw] 等待 OTP 邮件 (最长 {settings.REGISTRATION_TIMEOUT}s)")
            otp, _ = wait_for_verification_email_sync(
                email, timeout=settings.REGISTRATION_TIMEOUT, poll_interval=5,
            )
            if not otp:
                return {"success": False, "callback_url": None,
                        "error": "OTP 等待超时，未收到验证码邮件"}

            self._log(f"[OpenClaw] 收到 OTP: {otp}")
            _human_delay(0.3, 0.8)
            otp_status, otp_data = reg.validate_otp(otp)

            if otp_status != 200:
                # 重发一次
                reg.session.get(
                    f"{OAUTH_ISSUER}/api/accounts/email-otp/send",
                    headers={
                        "Accept": "text/html,*/*;q=0.8",
                        "Referer": f"{OAUTH_ISSUER}/log-in/password",
                    }, allow_redirects=True, timeout=30,
                )
                otp2, _ = wait_for_verification_email_sync(email, timeout=60, poll_interval=5)
                if otp2:
                    _human_delay(0.3, 0.8)
                    otp_status, otp_data = reg.validate_otp(otp2)
                if otp_status != 200:
                    return {"success": False, "callback_url": None,
                            "error": f"OTP 验证失败 ({otp_status})"}

            if isinstance(otp_data, dict):
                continue_url = otp_data.get("continue_url", "")
                otp_page = (otp_data.get("page") or {}).get("type", "")
                self._log(f"[OpenClaw] OTP 验证通过 → continue_url={continue_url} page={otp_page}")
                if continue_url and continue_url.startswith("/"):
                    continue_url = f"{OAUTH_ISSUER}{continue_url}"

                # 若出现 about_you 页
                if otp_page == "about_you" or "about-you" in continue_url:
                    from app.services.registration_service import _random_name, _random_birthday
                    fn, ln = _random_name()
                    name = f"{fn} {ln}"
                    bdate = _random_birthday()
                    self._log(f"[OpenClaw] 填写账号信息 ({name}, {bdate})")
                    _human_delay(0.3, 0.8)
                    ca_status, ca_data = reg.create_account(name, bdate)
                    if ca_status == 200 and isinstance(ca_data, dict):
                        continue_url = ca_data.get("continue_url", "")
                        if continue_url and continue_url.startswith("/"):
                            continue_url = f"{OAUTH_ISSUER}{continue_url}"
                    else:
                        err_code = ""
                        if isinstance(ca_data, dict):
                            err_code = (ca_data.get("error") or {}).get("code", "")
                        if err_code == "user_already_exists" or ca_status == 400:
                            continue_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"

        # ── 步骤 4: 追踪 consent 流至 redirect_uri ───────────────
        self._log("[OpenClaw] 4/4 追踪 consent 重定向...")
        callback_url = None

        if continue_url:
            if continue_url.startswith("/"):
                continue_url = f"{OAUTH_ISSUER}{continue_url}"
            # 先检查 continue_url 本身是否已是回调
            callback_url = _extract_full_callback_url(continue_url, redirect_uri)

        if not callback_url and continue_url:
            callback_url = self._follow_for_callback(continue_url, redirect_uri)

        if not callback_url:
            consent_target = continue_url or f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            callback_url = self._consent_for_callback(consent_target, redirect_uri)

        if not callback_url:
            return {"success": False, "callback_url": None,
                    "error": "未能获取到 callback URL，OAuth consent 流程未成功返回授权码"}

        self._log(f"[OpenClaw] 成功获取 callback_url: {callback_url[:100]}")
        return {"success": True, "callback_url": callback_url, "error": ""}


# ── 异步任务管理（供路由层调用）────────────────────────────────

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def start_openclaw_task(auth_url: str, account_id: int) -> str:
    """
    在后台线程中启动 OpenClaw OAuth 流程，返回 task_id 供轮询。
    """
    from app.database import SessionLocal, Account
    from app.services.registration_service import _proxy_url

    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise ValueError(f"账号 ID {account_id} 不存在")
        email = account.email
        password = account.password
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    log_lines: list[str] = []

    def _log(msg: str):
        log_lines.append(msg)
        logger.info(msg)

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "running",
            "callback_url": None,
            "error": None,
            "log": log_lines,
        }

    def _run():
        proxy = _proxy_url()
        flow = OpenClawOAuthFlow(proxy=proxy, log_fn=_log)
        try:
            result = flow.run(auth_url=auth_url, email=email, password=password)
            with _tasks_lock:
                _tasks[task_id]["status"] = "done" if result["success"] else "error"
                _tasks[task_id]["callback_url"] = result.get("callback_url")
                _tasks[task_id]["error"] = result.get("error") or ""
        except Exception as e:
            with _tasks_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = str(e)
            _log(f"[OpenClaw] 未捕获异常: {e}\n{traceback.format_exc()}")

    threading.Thread(target=_run, daemon=True).start()
    return task_id


def get_task_result(task_id: str) -> Optional[dict]:
    with _tasks_lock:
        return dict(_tasks[task_id]) if task_id in _tasks else None
