"""
ChatGPT 全自动注册服务 — 纯 HTTP 协议实现 (零浏览器依赖)

核心技术:
  - curl_cffi  : TLS 指纹模拟 (impersonate Chrome), 绕过 Cloudflare
  - 纯 HTTP    : 无 Playwright / Selenium / 浏览器进程
  - Datadog APM: 模拟真实浏览器遥测 trace headers
  - Cookie 链  : 自动累积 auth session state

注册流程 (参考逆向抓包 — Codex client_id + PKCE 绕过 Cloudflare):
  Step 0a GET  auth.openai.com/oauth/authorize         → Codex PKCE, 获取 login_session
  Step 0b POST auth.openai.com/.../authorize/continue   → 提交邮箱 (sentinel)
  Step 1  POST auth.openai.com/.../user/register        → 注册 (邮箱+密码, sentinel)
  Step 2  GET  auth.openai.com/.../email-otp/send       → 触发验证码
  [IMAP]  轮询 163.com 收取 OpenAI 验证码
  Step 3  POST auth.openai.com/.../email-otp/validate   → 验证 OTP (sentinel)
  Step 4  POST auth.openai.com/.../create_account       → 姓名+生日 → 完成

OAuth 登录换 Token (注册成功后可选执行):
  1  GET  /oauth/authorize  (PKCE + state)            → login_session
  2  POST /api/accounts/authorize/continue             → 提交邮箱 (sentinel)
  3  POST /api/accounts/password/verify                → 提交密码 (sentinel)
  4  consent / workspace / organization 多步           → 提取 authorization code
  5  POST /oauth/token                                 → code → access/refresh token
"""

import json
import os
import re
import random
import string
import time
import uuid
import secrets
import hashlib
import base64
import logging
import traceback
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode

from curl_cffi import requests as curl_requests

from app.config import settings
from app.services.imap_service import wait_for_verification_email_sync

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  浏览器指纹生成器 (Anti-Detection)
# ═══════════════════════════════════════════════════════════════

# curl_cffi TLS 指纹配置
#
# Cloudflare Bot Management 会根据 JA3/JA4 TLS 指纹对 Chrome 版本区别对待:
#   - Chrome 120/123/124: 这些版本的指纹已被大量 Python 爬虫/自动化工具使用,
#     Cloudflare 积累了海量黑名单数据, 403 率极高 (实测 ~80%)。不作为主选。
#   - Chrome 131+: 发布时间短, 真实用户占比高, Cloudflare 模型宽松, 403 率低。
#
# 策略: 主池只用 131/133/136, 旧版本保留为最后兜底 (极小权重)。
_CHROME_IMPERSONATES = [
    {
        "major": 120, "impersonate": "chrome120",
        "build": 6099, "patch_range": (109, 230),
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "weight": 0,   # 禁用: JA3 已被 Cloudflare 大量标记
    },
    {
        "major": 123, "impersonate": "chrome123",
        "build": 6312, "patch_range": (46, 170),
        "sec_ch_ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "weight": 0,   # 禁用: 同上
    },
    {
        "major": 124, "impersonate": "chrome124",
        "build": 6367, "patch_range": (60, 208),
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "weight": 0,   # 禁用: 同上
    },
    {
        "major": 131, "impersonate": "chrome131",
        "build": 6778, "patch_range": (69, 205),
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "weight": 3,
    },
    {
        "major": 133, "impersonate": "chrome133a",
        "build": 6943, "patch_range": (33, 120),
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "weight": 5,
    },
    {
        "major": 136, "impersonate": "chrome136",
        "build": 7103, "patch_range": (31, 100),
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "weight": 5,
    },
]

# 操作系统平台 (Windows 权重更高, macOS 增加多样性)
_PLATFORMS = [
    {
        "name": "Windows", "ua_part": "Windows NT 10.0; Win64; x64",
        "sec_platform": '"Windows"', "sec_arch": '"x86"',
        "versions": ["10.0.0", "13.0.0", "14.0.0", "15.0.0", "16.0.0"],
        "weight": 7,
    },
    {
        "name": "macOS", "ua_part": "Macintosh; Intel Mac OS X 10_15_7",
        "sec_platform": '"macOS"', "sec_arch": '"arm"',
        "versions": ["14.0.0", "14.4.0", "14.7.0", "15.0.0", "15.1.0", "15.2.0"],
        "weight": 3,
    },
]

# 屏幕分辨率 (最后一位为权重)
_SCREENS = [
    (1920, 1080, 6), (2560, 1440, 3), (1366, 768, 2), (1440, 900, 1),
    (1536, 864, 2), (1680, 1050, 1), (3840, 2160, 1), (1600, 900, 1),
]

# Accept-Language 变体: (header 值, 主语言, navigator.languages 列表)
_ACCEPT_LANGUAGES = [
    ("en-US,en;q=0.9", "en-US", ["en-US", "en"]),
    ("en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7", "en-US", ["en-US", "en", "zh-CN", "zh"]),
    ("en-GB,en;q=0.9,en-US;q=0.8", "en-GB", ["en-GB", "en", "en-US"]),
    ("en-US,en;q=0.9,fr;q=0.8", "en-US", ["en-US", "en", "fr"]),
    ("en,en-US;q=0.9", "en", ["en", "en-US"]),
    ("en-US,en;q=0.9,de;q=0.8", "en-US", ["en-US", "en", "de"]),
    ("en-US,en;q=0.9,ja;q=0.8", "en-US", ["en-US", "en", "ja"]),
    ("en-US,en;q=0.9,es;q=0.8", "en-US", ["en-US", "en", "es"]),
    ("en-US,en;q=0.9,ko;q=0.8", "en-US", ["en-US", "en", "ko"]),
    ("en-US,en;q=0.9,pt-BR;q=0.8", "en-US", ["en-US", "en", "pt-BR"]),
]

# 硬件参数 (加权分布, 常见值出现概率更高)
_DEVICE_MEMORIES = [4, 8, 8, 8, 16, 16, 32]
_HW_CONCURRENCIES = [4, 4, 6, 8, 8, 10, 12, 16, 20]
_COLOR_DEPTHS = [24, 24, 24, 30, 32]


def _make_full_version_list(sec_ch_ua: str, full_ver: str) -> str:
    """从 sec-ch-ua 生成 sec-ch-ua-full-version-list
    Brand 类条目用 X.0.0.0, Chrome/Chromium 用完整版本号"""
    entries = []
    for part in sec_ch_ua.split(", "):
        if "Brand" in part:
            m = re.search(r'v="(\d+)"', part)
            entries.append(re.sub(r'v="\d+"', f'v="{m.group(1)}.0.0.0"', part) if m else part)
        else:
            entries.append(re.sub(r'v="\d+"', f'v="{full_ver}"', part))
    return ", ".join(entries)


def _weighted_choice(items: list):
    """按最后一个元素 (tuple) 或 'weight' 键 (dict) 加权随机选择, 自动过滤 weight=0"""
    if isinstance(items[0], dict):
        active = [item for item in items if item.get("weight", 1) > 0]
        weights = [item["weight"] for item in active]
    else:
        active = [item for item in items if item[-1] > 0]
        weights = [item[-1] for item in active]
    if not active:
        active = items  # 全部被过滤时兜底
        weights = None
    return random.choices(active, weights=weights, k=1)[0]


def generate_fingerprint(exclude_impersonate: str = None) -> dict:
    """
    生成完整的浏览器指纹配置。

    包含 TLS 指纹 (impersonate)、所有 sec-ch-ua 系列 headers、
    User-Agent、屏幕 / 语言 / 硬件参数, 用于构建一致的反检测请求。
    新版本 Chrome 有更高权重, 降低被 Cloudflare 拦截的概率。
    """
    # Chrome TLS 指纹 (加权, 排除指定版本以确保切换)
    profiles = _CHROME_IMPERSONATES
    if exclude_impersonate:
        candidates = [p for p in profiles if p["impersonate"] != exclude_impersonate]
        if candidates:
            profiles = candidates
    profile = _weighted_choice(profiles)

    # 完整版本号
    patch = random.randint(*profile["patch_range"])
    full_ver = f"{profile['major']}.0.{profile['build']}.{patch}"

    # sec-ch-ua headers
    sec_ch_ua = profile["sec_ch_ua"]
    sec_ch_ua_fvl = _make_full_version_list(sec_ch_ua, full_ver)

    # 平台 (加权)
    platform = _weighted_choice(_PLATFORMS)
    platform_ver = random.choice(platform["versions"])

    # User-Agent
    ua = (
        f"Mozilla/5.0 ({platform['ua_part']}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{full_ver} Safari/537.36"
    )

    # 屏幕 (加权)
    screen = _weighted_choice(_SCREENS)

    # 语言
    accept_lang, primary_lang, lang_list = random.choice(_ACCEPT_LANGUAGES)

    return {
        # TLS
        "impersonate": profile["impersonate"],
        "major": profile["major"],
        "full_version": full_ver,
        # UA
        "user_agent": ua,
        # sec-ch-ua 全系列
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_full_version_list": sec_ch_ua_fvl,
        "sec_ch_ua_platform": platform["sec_platform"],
        "sec_ch_ua_arch": platform["sec_arch"],
        "sec_ch_ua_bitness": '"64"',
        "sec_ch_ua_model": '""',
        "sec_ch_ua_platform_version": f'"{platform_ver}"',
        "sec_ch_ua_full_version": f'"{full_ver}"',
        "sec_ch_ua_mobile": "?0",
        # 浏览器环境
        "accept_language": accept_lang,
        "primary_language": primary_lang,
        "language_list": lang_list,
        "screen_width": screen[0],
        "screen_height": screen[1],
        "screen_resolution": f"{screen[0]}x{screen[1]}",
        "device_memory": random.choice(_DEVICE_MEMORIES),
        "hardware_concurrency": random.choice(_HW_CONCURRENCIES),
        "color_depth": random.choice(_COLOR_DEPTHS),
        "platform_name": platform["name"],
    }


OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer",
    "Michael", "Linda", "David", "Elizabeth", "William", "Barbara",
    "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
    "Charles", "Karen", "Daniel", "Lisa", "Matthew", "Nancy",
    "Anthony", "Betty", "Mark", "Margaret", "Steven", "Sandra",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson",
    "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee",
    "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres", "Hill",
]


# (已无用, 保留向后兼容) — 请使用 generate_fingerprint()
def _pick_chrome_profile():
    fp = generate_fingerprint()
    return fp["impersonate"], fp["major"], fp["full_version"], fp["user_agent"], fp["sec_ch_ua"]


def _random_name() -> Tuple[str, str]:
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def _random_birthday() -> str:
    """YYYY-MM-DD, 1985-2002"""
    y = random.randint(1985, 2002)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


def _generate_password(length: int = 14) -> str:
    """符合 OpenAI 密码策略: 大小写 + 数字 + 特殊字符"""
    lo = string.ascii_lowercase
    up = string.ascii_uppercase
    dg = string.digits
    sp = "!@#$%&*"
    pwd = [random.choice(lo), random.choice(up), random.choice(dg), random.choice(sp)]
    pool = lo + up + dg + sp
    pwd += [random.choice(pool) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


def _human_delay(lo: float = 0.3, hi: float = 1.0):
    time.sleep(random.uniform(lo, hi))


def _make_trace_headers() -> dict:
    """Datadog APM 追踪头 (从真实浏览器抓包还原)"""
    trace_id = random.randint(10**17, 10**18 - 1)
    parent_id = random.randint(10**17, 10**18 - 1)
    tp = f"00-{uuid.uuid4().hex}-{format(parent_id, '016x')}-01"
    return {
        "traceparent": tp,
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(trace_id),
        "x-datadog-parent-id": str(parent_id),
    }


def _generate_pkce() -> Tuple[str, str]:
    """生成 PKCE code_verifier 和 code_challenge (S256)"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _extract_code_from_url(url: str) -> Optional[str]:
    if not url or "code=" not in url:
        return None
    try:
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


def _proxy_url() -> Optional[str]:
    """从数据库配置构建代理 URL"""
    from app.services.settings_service import get_proxy_url
    return get_proxy_url()


def oauth_access_token_expires_at(tokens: Optional[dict]) -> Optional[datetime]:
    """从 OAuth token 响应推导 access_token 过期时间。"""
    if not isinstance(tokens, dict):
        return None
    expires_in = tokens.get("expires_in")
    if not isinstance(expires_in, (int, float)):
        return None
    return datetime.utcnow() + timedelta(seconds=float(expires_in))


# ═══════════════════════════════════════════════════════════════
#  Sentinel Token PoW (逆向 sentinel SDK JS)
# ═══════════════════════════════════════════════════════════════

class SentinelTokenGenerator:
    """
    纯 Python 生成 openai-sentinel-token (Proof of Work)。
    逆向自 https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js
    """
    MAX_ATTEMPTS = 500_000

    def __init__(self, device_id: str, user_agent: str,
                 screen_resolution: str = "1920x1080",
                 primary_language: str = "en-US",
                 language_list: list = None,
                 hardware_concurrency: int = None,
                 color_depth: int = 24):
        self.device_id = device_id
        self.user_agent = user_agent
        self.screen_resolution = screen_resolution
        self.primary_language = primary_language
        self.language_list = language_list or ["en-US", "en"]
        self.hardware_concurrency = hardware_concurrency
        self.color_depth = color_depth
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str) -> str:
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= (h >> 16); h = (h * 2246822507) & 0xFFFFFFFF
        h ^= (h >> 13); h = (h * 3266489909) & 0xFFFFFFFF
        h ^= (h >> 16); h &= 0xFFFFFFFF
        return format(h, "08x")

    def _get_config(self) -> list:
        now_str = time.strftime(
            "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
            time.gmtime(),
        )
        perf_now = random.uniform(1000, 50000)
        nav_prop = random.choice([
            "vendorSub", "productSub", "vendor", "maxTouchPoints",
            "hardwareConcurrency", "cookieEnabled", "credentials",
            "plugins", "mimeTypes", "pdfViewerEnabled",
        ])
        hw = self.hardware_concurrency or random.choice([4, 8, 12, 16])
        return [
            self.screen_resolution, now_str, 4294705152, random.random(),
            self.user_agent,
            "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js",
            None, None,
            self.primary_language,
            ",".join(self.language_list),
            random.random(), f"{nav_prop}-undefined",
            random.choice(["location", "URL", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number"]),
            perf_now, self.sid, "",
            hw,
            time.time() * 1000 - perf_now,
        ]

    @staticmethod
    def _b64(data) -> str:
        return base64.b64encode(
            json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
        ).decode()

    def generate_token(self, seed: str = None, difficulty: str = None) -> str:
        seed = seed or self.requirements_seed
        difficulty = str(difficulty or "0")
        start = time.time()
        config = self._get_config()
        for i in range(self.MAX_ATTEMPTS):
            config[3] = i
            config[9] = round((time.time() - start) * 1000)
            data = self._b64(config)
            if self._fnv1a_32(seed + data)[:len(difficulty)] <= difficulty:
                return "gAAAAAB" + data + "~S"
        return "gAAAAAB" + self._b64(str(None))

    def generate_requirements_token(self) -> str:
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        return "gAAAAAC" + self._b64(config)


def _make_sentinel_gen(device_id: str, ua: str, fp: dict = None) -> SentinelTokenGenerator:
    """Create SentinelTokenGenerator, optionally enriched with fingerprint data."""
    kwargs = {}
    if fp:
        kwargs = {
            "screen_resolution": fp["screen_resolution"],
            "primary_language": fp["primary_language"],
            "language_list": fp["language_list"],
            "hardware_concurrency": fp["hardware_concurrency"],
            "color_depth": fp["color_depth"],
        }
    return SentinelTokenGenerator(device_id=device_id, user_agent=ua, **kwargs)


def _fetch_sentinel_challenge(session, device_id: str, ua: str, sec_ch_ua: str,
                              impersonate: str, flow: str = "authorize_continue",
                              fp: dict = None):
    """POST sentinel.openai.com/backend-api/sentinel/req → 获取 challenge"""
    gen = _make_sentinel_gen(device_id, ua, fp)
    body = {"p": gen.generate_requirements_token(), "id": device_id, "flow": flow}
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
        "Origin": "https://sentinel.openai.com",
        "User-Agent": ua,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": fp["sec_ch_ua_platform"] if fp else '"Windows"',
    }
    try:
        resp = session.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            data=json.dumps(body), headers=headers, timeout=20,
            impersonate=impersonate,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"sentinel challenge 失败: {e}")
    return None


def _build_sentinel_token(session, device_id: str, ua: str, sec_ch_ua: str,
                          impersonate: str, flow: str = "authorize_continue",
                          fp: dict = None) -> Optional[str]:
    """构建完整的 openai-sentinel-token JSON 字符串"""
    challenge = _fetch_sentinel_challenge(session, device_id, ua, sec_ch_ua, impersonate, flow, fp=fp)
    if not challenge:
        return None
    c_value = challenge.get("token", "")
    if not c_value:
        return None
    pow_data = challenge.get("proofofwork") or {}
    gen = _make_sentinel_gen(device_id, ua, fp)
    if pow_data.get("required") and pow_data.get("seed"):
        p_value = gen.generate_token(seed=pow_data["seed"], difficulty=pow_data.get("difficulty", "0"))
    else:
        p_value = gen.generate_requirements_token()
    return json.dumps({"p": p_value, "t": "", "c": c_value, "id": device_id, "flow": flow},
                      separators=(",", ":"))


# ═══════════════════════════════════════════════════════════════
#  注册器核心类
# ═══════════════════════════════════════════════════════════════

class ChatGPTRegistrar:
    """
    ChatGPT 纯 HTTP 注册器。
    使用 curl_cffi 模拟 Chrome TLS 指纹, 全流程接口完成, 无需浏览器。
    """
    CHATGPT = "https://chatgpt.com"
    AUTH = "https://auth.openai.com"

    def __init__(self, proxy: str = None, log_fn=None):
        self.device_id = str(uuid.uuid4())
        self.auth_logging_id = str(uuid.uuid4())

        # 生成完整浏览器指纹 (包含 TLS/UA/屏幕/语言/硬件等)
        self.fp = generate_fingerprint()
        self.impersonate = self.fp["impersonate"]
        self.major = self.fp["major"]
        self.full_ver = self.fp["full_version"]
        self.ua = self.fp["user_agent"]
        self.sec_ch_ua = self.fp["sec_ch_ua"]

        # curl_cffi session (TLS 指纹模拟)
        self.session = curl_requests.Session(impersonate=self.impersonate)
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        self._apply_fingerprint_headers()
        self.session.cookies.set("oai-did", self.device_id, domain="chatgpt.com")
        self.code_verifier = None  # PKCE, 注册时生成
        self._callback_url = None
        self._log = log_fn or (lambda msg: logger.info(msg))

    def _apply_fingerprint_headers(self):
        """根据 self.fp 应用全部指纹 headers 到 session"""
        fp = self.fp
        self.session.headers.update({
            "User-Agent": fp["user_agent"],
            "Accept-Language": fp["accept_language"],
            "sec-ch-ua": fp["sec_ch_ua"],
            "sec-ch-ua-mobile": fp["sec_ch_ua_mobile"],
            "sec-ch-ua-platform": fp["sec_ch_ua_platform"],
            "sec-ch-ua-arch": fp["sec_ch_ua_arch"],
            "sec-ch-ua-bitness": fp["sec_ch_ua_bitness"],
            "sec-ch-ua-full-version": fp["sec_ch_ua_full_version"],
            "sec-ch-ua-full-version-list": fp["sec_ch_ua_full_version_list"],
            "sec-ch-ua-model": fp["sec_ch_ua_model"],
            "sec-ch-ua-platform-version": fp["sec_ch_ua_platform_version"],
        })

    # ── 日志 ───────────────────────────────────────────────
    def _step_log(self, step: str, method: str, url: str, status: int, extra=None):
        line = f"  [{step}] {method} {url[:100]} → {status}"
        if extra:
            try:
                line += f"  {json.dumps(extra, ensure_ascii=False)[:300]}"
            except Exception:
                line += f"  {str(extra)[:300]}"
        self._log(line)

    # ── 重新初始化 Session（换指纹重试用）─────────────────
    def _reinit_session(self):
        """关闭旧 session, 生成全新指纹重建 session"""
        try:
            self.session.close()
        except Exception:
            pass
        # 生成新指纹 (排除当前版本确保切换)
        self.fp = generate_fingerprint(exclude_impersonate=self.impersonate)
        self.impersonate = self.fp["impersonate"]
        self.major = self.fp["major"]
        self.full_ver = self.fp["full_version"]
        self.ua = self.fp["user_agent"]
        self.sec_ch_ua = self.fp["sec_ch_ua"]
        self.device_id = str(uuid.uuid4())
        self.auth_logging_id = str(uuid.uuid4())
        proxy = _proxy_url()
        self.session = curl_requests.Session(impersonate=self.impersonate)
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        self._apply_fingerprint_headers()
        self.session.cookies.set("oai-did", self.device_id, domain="chatgpt.com")
        self._log(f"  [重试] 换用 Chrome {self.major} ({self.impersonate}) | {self.fp['platform_name']}")

    # ── 辅助: Sentinel & API 请求头 ──────────────────────

    def _get_sentinel(self, flow: str = "authorize_continue") -> Optional[str]:
        """构建 sentinel token"""
        return _build_sentinel_token(
            self.session, self.device_id, self.ua, self.sec_ch_ua,
            self.impersonate, flow=flow, fp=self.fp,
        )

    def _api_headers(self, referer: str, with_sentinel: str = None) -> dict:
        """构造 JSON API 请求头, with_sentinel 传 flow 名称则附加 sentinel"""
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": self.AUTH,
            "Referer": referer,
            "oai-device-id": self.device_id,
        }
        h.update(_make_trace_headers())
        if with_sentinel:
            sentinel = self._get_sentinel(with_sentinel)
            if sentinel:
                h["openai-sentinel-token"] = sentinel
            else:
                self._log(f"  ⚠️ sentinel token ({with_sentinel}) 获取失败, 继续尝试")
        return h

    # ── Step 0a: OAuth 会话初始化 ──────────────────────────────

    def init_oauth_session(self, max_retries: int = 5) -> bool:
        """
        GET /oauth/authorize (Codex client_id + PKCE + screen_hint=signup)
        获取 login_session cookie, 为后续 API 调用建立会话。

        关键: 纯 HTTP 必须使用 Codex client_id (app_EMoamEEZ73f0CkXaXp7hrann),
              ChatGPT Web client_id 在纯 HTTP 调用时会被 auth.openai.com 拒绝 (403)。
        """
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

        code_verifier, code_challenge = _generate_pkce()
        self.code_verifier = code_verifier

        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(24),
            "screen_hint": "signup",
            "prompt": "login",
        }
        auth_url = f"{self.AUTH}/oauth/authorize?{urlencode(params)}"

        last_status = 0
        last_text = ""
        for attempt in range(1, max_retries + 1):
            self._log(f"Step 0a: GET /oauth/authorize (尝试 {attempt}/{max_retries})")
            try:
                r = self.session.get(auth_url, headers={
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
                self._log(f"  请求异常: {e}")
                if attempt < max_retries:
                    _human_delay(2.0, 4.0)
                    self._reinit_session()
                    self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
                    self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
                    continue
                raise Exception(f"OAuth authorize 请求异常: {e}\n当前代理: {_proxy_url()}")

            final = str(r.url)
            last_status = r.status_code
            last_text = r.text[:300]
            self._step_log(f"Step 0a (try {attempt})", "GET", auth_url[:80], r.status_code, {"final": final[:150]})

            if r.status_code == 200:
                has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
                self._log(f"  login_session: {'✅ 已获取' if has_login else '⚠️ 未获取 (非致命)'}")
                return True

            if r.status_code == 403:
                self._log(f"  Cloudflare 403, 换指纹重试 ({attempt}/{max_retries}) ...")
                if attempt < max_retries:
                    # 渐进延迟: 5s, 8s, 12s, 16s...
                    delay = 3.0 + attempt * 3.0
                    _human_delay(delay, delay + 3.0)
                    self._reinit_session()
                    self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
                    self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
                    # 重新生成 PKCE (state 也换新)
                    code_verifier, code_challenge = _generate_pkce()
                    self.code_verifier = code_verifier
                    params["code_challenge"] = code_challenge
                    params["state"] = secrets.token_urlsafe(24)
                    auth_url = f"{self.AUTH}/oauth/authorize?{urlencode(params)}"
                    continue

        raise Exception(
            f"auth.openai.com /oauth/authorize 持续 403 ({max_retries} 次)\n"
            f"当前代理: {_proxy_url()}\n"
            f"响应预览: {last_text}"
        )

    # ── Step 0b: 提交邮箱 (authorize/continue) ─────────────────

    def authorize_continue(self, email: str) -> str:
        """
        POST /api/accounts/authorize/continue
        提交邮箱, 返回 page type (如 'signup', 'login' 等).
        需要 sentinel token.
        """
        url = f"{self.AUTH}/api/accounts/authorize/continue"
        headers = self._api_headers(
            referer=f"{self.AUTH}/create-account",
            with_sentinel="authorize_continue",
        )

        body = {
            "username": {"kind": "email", "value": email},
            "screen_hint": "signup",
        }

        self._log("Step 0b: POST authorize/continue (提交邮箱)")
        r = self.session.post(url, json=body, headers=headers, timeout=30)

        page_type = "?"
        try:
            data = r.json()
            page_type = data.get("page", {}).get("type", "?")
        except Exception:
            data = {"text": r.text[:300]}

        self._step_log("Step 0b", "POST", url, r.status_code, {"page_type": page_type})

        if r.status_code != 200:
            raise Exception(
                f"authorize/continue 失败 ({r.status_code}): {r.text[:300]}"
            )
        return page_type

    def visit_homepage(self, max_retries: int = 3):
        url = f"{self.CHATGPT}/"
        _headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        for attempt in range(1, max_retries + 1):
            r = self.session.get(url, headers=_headers, allow_redirects=True, timeout=30)
            self._step_log(f"Step 0 (try {attempt})", "GET", url, r.status_code)
            if r.status_code == 200:
                return
            if r.status_code == 403:
                self._log(f"  Cloudflare 403, 换指纹重试 ({attempt}/{max_retries}) ...")
                _human_delay(1.5, 3.0)
                if attempt < max_retries:
                    self._reinit_session()
                continue
            # 其他非 200 状态也继续（例如 302 重定向已被 allow_redirects 处理）
            return
        raise Exception(f"chatgpt.com 首页持续返回 403 (尝试 {max_retries} 次)，IP 或指纹被 Cloudflare 拦截")

    # ── Step 1: CSRF ───────────────────────────────────────
    def get_csrf(self) -> str:
        url = f"{self.CHATGPT}/api/auth/csrf"
        r = self.session.get(url, headers={
            "Accept": "application/json",
            "Referer": f"{self.CHATGPT}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }, timeout=30)
        self._step_log("Step 1", "GET", url, r.status_code)
        if r.status_code != 200:
            raise Exception(f"CSRF 请求失败 HTTP {r.status_code}: {r.text[:200]}")
        raw = r.text.strip()
        if not raw:
            raise Exception(f"CSRF 响应为空 (HTTP {r.status_code})，可能首页 403 未恢复")
        try:
            data = r.json()
        except Exception:
            raise Exception(f"CSRF 响应非 JSON: {raw[:200]}")
        token = data.get("csrfToken", "")
        if not token:
            raise Exception(f"CSRF token 字段缺失: {data}")
        self._step_log("Step 1", "GET", url, r.status_code, {"csrf": token[:20] + "..."})
        return token

    # ── Step 2: Signin ─────────────────────────────────────
    def signin(self, email: str, csrf: str) -> str:
        url = f"{self.CHATGPT}/api/auth/signin/openai"
        params = {
            "prompt": "login",
            "ext-oai-did": self.device_id,
            "auth_session_logging_id": self.auth_logging_id,
            "screen_hint": "login_or_signup",
            "login_hint": email,
        }
        form = {
            "callbackUrl": f"{self.CHATGPT}/",
            "csrfToken": csrf,
            "json": "true",
        }
        r = self.session.post(url, params=params, data=form, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Referer": f"{self.CHATGPT}/",
            "Origin": self.CHATGPT,
        })
        data = r.json()
        auth_url = data.get("url", "")
        self._step_log("Step 2", "POST", url, r.status_code,
                       {"url": auth_url[:100] + "..." if len(auth_url) > 100 else auth_url})
        if not auth_url:
            raise Exception("未获取到 authorize URL")
        return auth_url

    # ── Step 3: Authorize ──────────────────────────────────
    def authorize(self, url: str) -> str:
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.CHATGPT}/",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        final = str(r.url)
        self._step_log("Step 3", "GET", url[:80], r.status_code, {"final": final})
        return final

    # ── Step 1: Register ──────────────────────────────────
    def register_user(self, email: str, password: str) -> Tuple[int, dict]:
        url = f"{self.AUTH}/api/accounts/user/register"
        headers = self._api_headers(
            referer=f"{self.AUTH}/create-account/password",
            with_sentinel="register",
        )
        r = self.session.post(url, json={"username": email, "password": password},
                              headers=headers, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text[:500]}
        self._step_log("Step 1", "POST", url, r.status_code, data)
        return r.status_code, data

    # ── Step 2: Send OTP ──────────────────────────────────
    def send_otp(self) -> Tuple[int, dict]:
        nav_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.AUTH}/create-account/password",
            "Upgrade-Insecure-Requests": "1",
        }
        # 2a: 触发发送
        url_send = f"{self.AUTH}/api/accounts/email-otp/send"
        r = self.session.get(url_send, headers=nav_headers, allow_redirects=True, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"final_url": str(r.url)}
        self._step_log("Step 2a", "GET", url_send, r.status_code, data)

        # 2b: 访问 email-verification 页面 (建立路由状态)
        url_verify = f"{self.AUTH}/email-verification"
        r2 = self.session.get(url_verify, headers=nav_headers, allow_redirects=True, timeout=30)
        self._step_log("Step 2b", "GET", url_verify, r2.status_code)
        return r.status_code, data

    # ── Step 3: Validate OTP ──────────────────────────────
    def validate_otp(self, code: str) -> Tuple[int, dict]:
        url = f"{self.AUTH}/api/accounts/email-otp/validate"
        headers = self._api_headers(
            referer=f"{self.AUTH}/email-verification",
            with_sentinel="email_otp_validate",
        )
        r = self.session.post(url, json={"code": code}, headers=headers, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text[:500]}
        self._step_log("Step 3", "POST", url, r.status_code, data)
        return r.status_code, data

    # ── Step 4: Create Account ─────────────────────────────
    def create_account(self, name: str, birthdate: str) -> Tuple[int, dict]:
        url = f"{self.AUTH}/api/accounts/create_account"
        headers = self._api_headers(
            referer=f"{self.AUTH}/about-you",
        )
        r = self.session.post(url, json={"name": name, "birthdate": birthdate},
                              headers=headers, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text[:500]}
        self._step_log("Step 4", "POST", url, r.status_code, data)
        if isinstance(data, dict):
            cb = data.get("continue_url") or data.get("url") or data.get("redirect_url")
            if cb:
                self._callback_url = cb
        return r.status_code, data

    # ── Callback ───────────────────────────────────────────
    def callback(self, url: str = None) -> Optional[str]:
        url = url or self._callback_url
        if not url:
            return None
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._step_log("Callback", "GET", url[:80], r.status_code)
        return str(r.url)

    # ── 提取 Cookie ───────────────────────────────────────
    def extract_session_token(self) -> Optional[str]:
        jar = getattr(self.session.cookies, "jar", None)
        if jar:
            for c in jar:
                name = getattr(c, "name", "")
                if "session" in name.lower() and "token" in name.lower():
                    return getattr(c, "value", "")
            for c in jar:
                name = getattr(c, "name", "")
                if "session" in name.lower():
                    return getattr(c, "value", "")
        return None

    # ═══════════════════════════════════════════════════════
    #  注册主流程
    # ═══════════════════════════════════════════════════════

    def run_register(self, email: str) -> Dict[str, Any]:
        password = _generate_password()
        first_name, last_name = _random_name()
        full_name = f"{first_name} {last_name}"
        birthdate = _random_birthday()

        result = {
            "success": False,
            "email": email,
            "password": password,
            "session_token": None,
            "access_token": None,
            "refresh_token": None,
            "error": "",
        }

        self._log(f"═══ 开始注册: {email} ═══")
        self._log(f"  Chrome {self.major} ({self.impersonate}) | {self.fp['platform_name']} | {self.fp['screen_resolution']} | {full_name} | {birthdate}")

        try:
            # ── Step 0a: OAuth 会话初始化 (Codex client_id + PKCE) ──
            self.init_oauth_session()
            _human_delay(0.3, 0.8)

            # ── Step 0b: 提交邮箱 (authorize/continue + sentinel) ──
            page_type = self.authorize_continue(email)
            self._log(f"  authorize/continue → page_type={page_type}")
            _human_delay(0.3, 0.8)

            # ── Step 1: 注册用户 (email + password + sentinel) ──
            self._log("Step 1: 注册用户 (email + password) ...")
            _human_delay(0.5, 1.0)
            status, data = self.register_user(email, password)
            if status != 200:
                error_msg = ""
                if isinstance(data, dict):
                    error_msg = data.get("error", data.get("detail", str(data)))
                else:
                    error_msg = str(data)
                # 已存在的邮箱也报错, 但不阻塞 (可能需要不同处理)
                result["error"] = f"注册失败 ({status}): {error_msg}"
                self._log(f"  ❌ {result['error']}")
                return result

            # ── Step 2: 触发 OTP 发送 ──
            self._log("Step 2: 触发 OTP 发送 ...")
            _human_delay(0.3, 0.8)
            self.send_otp()

            # ── IMAP 轮询等待验证码 ──
            _reg_timeout = settings.REGISTRATION_TIMEOUT
            self._log(f"等待验证码 (IMAP 轮询, 最长 {_reg_timeout}s) ...")
            otp, link = wait_for_verification_email_sync(
                email,
                timeout=_reg_timeout,
                poll_interval=5,
            )
            if not otp:
                result["error"] = f"未收到验证码, 超时 {_reg_timeout}s"
                self._log(f"  ❌ {result['error']}")
                return result
            self._log(f"  ✅ 收到验证码: {otp}")
            _human_delay(0.3, 0.8)

            # ── Step 3: 验证 OTP (+ sentinel) ──
            self._log("Step 3: 验证 OTP ...")
            status, data = self.validate_otp(otp)
            if status != 200:
                self._log("  验证失败, 重发并重试 ...")
                self.send_otp()
                _human_delay(1.0, 2.0)
                otp2, _ = wait_for_verification_email_sync(email, timeout=60, poll_interval=5)
                if otp2:
                    status, data = self.validate_otp(otp2)
                if status != 200:
                    result["error"] = f"OTP 验证失败 ({status}): {data}"
                    return result

            # ── Step 4: 创建账号 (姓名 + 生日) ──
            self._log(f"Step 4: 创建账号 ({full_name}, {birthdate}) ...")
            _human_delay(0.5, 1.5)
            status, data = self.create_account(full_name, birthdate)
            if status != 200:
                result["error"] = f"创建账号失败 ({status}): {data}"
                return result

            _human_delay(0.2, 0.5)
            self.callback()

            result["success"] = True
            result["session_token"] = self.extract_session_token()
            self._log(f"  ✅ 注册成功! token={'有' if result['session_token'] else '无'}")

        except Exception as e:
            self._log(f"  ❌ 异常: {e}")
            self._log(traceback.format_exc())
            result["error"] = str(e)

        return result

    # ═══════════════════════════════════════════════════════
    #  OAuth 登录换 Codex Token
    # ═══════════════════════════════════════════════════════

    def oauth_login(self, email: str, password: str) -> Optional[Dict[str, str]]:
        """
        注册成功后执行 Codex OAuth 流程, 换取 access_token / refresh_token。
        返回 token dict 或 None。
        """
        self._log("[OAuth] 开始 Codex OAuth 流程 ...")

        # 确保 auth 域也有 oai-did
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)

        auth_params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        auth_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(auth_params)}"

        def _json_headers(referer: str) -> dict:
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": referer,
                "User-Agent": self.ua,
                "oai-device-id": self.device_id,
            }
            h.update(_make_trace_headers())
            return h

        # 1. GET /oauth/authorize → login_session
        self._log("[OAuth] 1/5 GET /oauth/authorize")
        try:
            r = self.session.get(auth_url, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{self.CHATGPT}/",
                "Upgrade-Insecure-Requests": "1",
            }, allow_redirects=True, timeout=30)
        except Exception as e:
            self._log(f"[OAuth] authorize 异常: {e}")
            return None

        has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
        self._log(f"[OAuth] login_session: {'有' if has_login else '无'}")

        # 2. POST authorize/continue → 提交邮箱 (需 sentinel)
        self._log("[OAuth] 2/5 POST authorize/continue")
        sentinel = _build_sentinel_token(
            self.session, self.device_id, self.ua, self.sec_ch_ua,
            self.impersonate, flow="authorize_continue", fp=self.fp,
        )
        if not sentinel:
            self._log("[OAuth] sentinel token 获取失败")
            return None

        h_continue = _json_headers(f"{OAUTH_ISSUER}/log-in")
        h_continue["openai-sentinel-token"] = sentinel
        try:
            r2 = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                json={"username": {"kind": "email", "value": email}},
                headers=h_continue, timeout=30, allow_redirects=False,
            )
        except Exception as e:
            self._log(f"[OAuth] authorize/continue 异常: {e}")
            return None

        if r2.status_code != 200:
            self._log(f"[OAuth] authorize/continue 失败: {r2.status_code} {r2.text[:200]}")
            return None
        try:
            r2_data = r2.json()
            self._log(f"[OAuth] authorize/continue 响应: {json.dumps(r2_data, ensure_ascii=False)[:300]}")
        except Exception:
            self._log(f"[OAuth] authorize/continue 响应 (非JSON): {r2.text[:200]}")

        # 3. POST password/verify → 提交密码 (需 sentinel)
        self._log("[OAuth] 3/5 POST password/verify")
        sentinel_pwd = _build_sentinel_token(
            self.session, self.device_id, self.ua, self.sec_ch_ua,
            self.impersonate, flow="password_verify", fp=self.fp,
        )
        if not sentinel_pwd:
            self._log("[OAuth] password sentinel 失败")
            return None

        h_pwd = _json_headers(f"{OAUTH_ISSUER}/log-in/password")
        h_pwd["openai-sentinel-token"] = sentinel_pwd
        try:
            r3 = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                json={"password": password},
                headers=h_pwd, timeout=30, allow_redirects=False,
            )
        except Exception as e:
            self._log(f"[OAuth] password/verify 异常: {e}")
            return None

        if r3.status_code != 200:
            self._log(f"[OAuth] password/verify 失败: {r3.status_code} {r3.text[:200]}")
            return None

        try:
            verify_data = r3.json()
        except Exception:
            verify_data = {}
        continue_url = verify_data.get("continue_url", "")
        self._log(f"[OAuth] password/verify 响应: {json.dumps(verify_data, ensure_ascii=False)[:300]}")
        self._log(f"[OAuth] continue_url = {continue_url}")

        # 4. 跟随 consent → 提取 authorization code
        self._log("[OAuth] 4/5 提取 authorization code ...")
        code = None

        if continue_url:
            if continue_url.startswith("/"):
                continue_url = f"{OAUTH_ISSUER}{continue_url}"
            code = _extract_code_from_url(continue_url)

        if not code and continue_url:
            self._log(f"[OAuth] follow_for_code: {continue_url[:100]}")
            code = self._oauth_follow_for_code(continue_url)

        if not code:
            # 尝试 workspace/org consent
            consent_target = continue_url or f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            self._log(f"[OAuth] consent_flow: {consent_target[:100]}")
            code = self._oauth_consent_flow(consent_target)

        if not code:
            self._log("[OAuth] 未获取到 authorization code")
            return None

        # 5. POST /oauth/token → 换 token
        self._log("[OAuth] 5/5 POST /oauth/token")
        try:
            r5 = self.session.post(
                f"{OAUTH_ISSUER}/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": self.ua},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": OAUTH_REDIRECT_URI,
                    "client_id": OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                timeout=60,
            )
        except Exception as e:
            self._log(f"[OAuth] token 交换异常: {e}")
            return None

        if r5.status_code != 200:
            self._log(f"[OAuth] token 交换失败: {r5.status_code} {r5.text[:200]}")
            return None

        tokens = r5.json()
        if tokens.get("access_token"):
            self._log("[OAuth] ✅ Codex Token 获取成功")
            return tokens
        self._log("[OAuth] token 响应缺少 access_token")
        return None

    def _oauth_follow_for_code(self, start_url: str, max_hops: int = 12) -> Optional[str]:
        """逐步跟随 302, 在跳转链中提取 code"""
        current = start_url
        for hop in range(max_hops):
            try:
                r = self.session.get(current, headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                }, allow_redirects=False, timeout=30)
            except Exception as e:
                # curl_cffi 在 redirect 到 localhost 时可能抛异常
                m = re.search(r'(https?://localhost[^\s\'"]+)', str(e))
                if m:
                    c = _extract_code_from_url(m.group(1))
                    if c:
                        return c
                return None

            code = _extract_code_from_url(str(r.url))
            if code:
                return code

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if not loc:
                    return None
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code
                current = loc
                continue
            return None
        return None

    def _oauth_consent_flow(self, consent_url: str) -> Optional[str]:
        """处理 workspace/org 选择页面 (consent 授权流程)"""
        try:
            # 4a: GET consent 页面 (触发 oai-client-auth-session cookie 设置)
            self._log(f"[OAuth-consent] 4a: GET {consent_url[:80]}")
            try:
                resp_consent = self.session.get(consent_url, headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                }, allow_redirects=False, timeout=30)
                if resp_consent.status_code in (301, 302, 303, 307, 308):
                    loc = resp_consent.headers.get("Location", "")
                    code = _extract_code_from_url(loc)
                    if code:
                        self._log(f"[OAuth-consent] consent 直接 302 获取到 code")
                        return code
                    code = self._oauth_follow_for_code(loc if loc.startswith("http") else f"{OAUTH_ISSUER}{loc}")
                    if code:
                        return code
                else:
                    self._log(f"[OAuth-consent] consent 页面 → {resp_consent.status_code}")
            except Exception as e:
                m = re.search(r'(https?://localhost[^\s\'"]+)', str(e))
                if m:
                    code = _extract_code_from_url(m.group(1))
                    if code:
                        self._log("[OAuth-consent] 从 ConnectionError 提取到 code")
                        return code
                self._log(f"[OAuth-consent] consent GET 异常: {e}")

            # 4b: 解码 oai-client-auth-session cookie → 提取 workspace_id
            jar = getattr(self.session.cookies, "jar", None)
            all_cookies = []
            session_data = None
            if jar:
                for c in jar:
                    name = getattr(c, "name", "")
                    all_cookies.append(name)
                    if "oai-client-auth-session" in name:
                        raw = getattr(c, "value", "")
                        try:
                            from urllib.parse import unquote
                            decoded = unquote(raw).strip('"').strip("'")
                            part = decoded.split(".")[0] if "." in decoded else decoded
                            pad = 4 - len(part) % 4
                            if pad != 4:
                                part += "=" * pad
                            session_data = json.loads(base64.urlsafe_b64decode(part))
                        except Exception as e2:
                            self._log(f"[OAuth-consent] cookie 解码失败: {e2}")
                        break

            self._log(f"[OAuth-consent] cookies: {all_cookies}")
            if not session_data:
                self._log("[OAuth-consent] 无 session_data, 退出")
                return None
            self._log(f"[OAuth-consent] session keys: {list(session_data.keys())}")

            workspaces = session_data.get("workspaces", [])
            if not workspaces:
                self._log(f"[OAuth-consent] 无 workspaces: {json.dumps(session_data, ensure_ascii=False)[:500]}")
                return None

            ws_id = (workspaces[0] or {}).get("id")
            ws_kind = (workspaces[0] or {}).get("kind", "?")
            if not ws_id:
                self._log("[OAuth-consent] workspace_id 为空")
                return None
            self._log(f"[OAuth-consent] 4b: workspace_id={ws_id} (kind={ws_kind})")

            # 4c: POST workspace/select
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": consent_url,
                "User-Agent": self.ua,
                "oai-device-id": self.device_id,
            }
            h.update(_make_trace_headers())

            self._log("[OAuth-consent] 4c: POST workspace/select")
            r = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/workspace/select",
                json={"workspace_id": ws_id},
                headers=h, allow_redirects=False, timeout=30,
            )
            self._log(f"[OAuth-consent] workspace/select → {r.status_code}")

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    self._log("[OAuth-consent] workspace/select 302 获取到 code")
                    return code
                return self._oauth_follow_for_code(loc)

            if r.status_code == 200:
                data = r.json()
                ws_next = data.get("continue_url", "")
                ws_page = data.get("page", {}).get("type", "")
                self._log(f"[OAuth-consent] ws_next={ws_next}, ws_page={ws_page}")

                # 4d: organization/select
                orgs = data.get("data", {}).get("orgs", [])
                if orgs:
                    org_id = (orgs[0] or {}).get("id")
                    projects = (orgs[0] or {}).get("projects", [])
                    project_id = projects[0].get("id") if projects else None
                    self._log(f"[OAuth-consent] 4d: org_id={org_id}, project_id={project_id}")

                    if org_id:
                        body = {"org_id": org_id}
                        if project_id:
                            body["project_id"] = project_id

                        h2 = dict(h)
                        org_url = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"
                        h2["Referer"] = org_url

                        r2 = self.session.post(
                            f"{OAUTH_ISSUER}/api/accounts/organization/select",
                            json=body,
                            headers=h2, allow_redirects=False, timeout=30,
                        )
                        self._log(f"[OAuth-consent] org/select → {r2.status_code}")

                        if r2.status_code in (301, 302, 303, 307, 308):
                            loc = r2.headers.get("Location", "")
                            if loc.startswith("/"):
                                loc = f"{OAUTH_ISSUER}{loc}"
                            code = _extract_code_from_url(loc)
                            if code:
                                self._log("[OAuth-consent] org/select 302 获取到 code")
                                return code
                            return self._oauth_follow_for_code(loc)
                        if r2.status_code == 200:
                            org_data = r2.json()
                            org_next = org_data.get("continue_url", "")
                            self._log(f"[OAuth-consent] org_next={org_next}")
                            if org_next:
                                if org_next.startswith("/"):
                                    org_next = f"{OAUTH_ISSUER}{org_next}"
                                return self._oauth_follow_for_code(org_next)

                if ws_next:
                    if ws_next.startswith("/"):
                        ws_next = f"{OAUTH_ISSUER}{ws_next}"
                    return self._oauth_follow_for_code(ws_next)

        except Exception as e:
            self._log(f"[OAuth-consent] 流程异常: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════════════

def register_account(email: str, log_lines: list) -> dict:
    """
    注册单个 ChatGPT 账号 (同步函数, 供后台任务直接调用)。

    返回: { success, email, password, session_token, access_token, refresh_token, error }
    """
    def log_fn(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logger.info(msg)
        log_lines.append(line)

    proxy = _proxy_url()
    if proxy:
        log_fn(f"  代理: {proxy}")

    registrar = ChatGPTRegistrar(proxy=proxy, log_fn=log_fn)
    result = registrar.run_register(email)

    # 注册成功后尝试 OAuth 换 token
    if result["success"] and result["password"]:
        log_fn("  尝试 OAuth 换取 Codex Token ...")
        try:
            tokens = registrar.oauth_login(email, result["password"])
            if tokens:
                result["access_token"] = tokens.get("access_token")
                result["refresh_token"] = tokens.get("refresh_token")
                result["id_token"] = tokens.get("id_token")
                result["expires_in"] = tokens.get("expires_in")
                log_fn("  ✅ Codex Token 已获取")
            else:
                log_fn("  ⚠️ OAuth 未成功 (注册仍有效)")
        except Exception as e:
            log_fn(f"  ⚠️ OAuth 异常: {e} (注册仍有效)")

    log_fn(f"═══ 结束: success={result['success']} ═══")
    return result


def refresh_session_token(email: str, password: str) -> Optional[str]:
    """
    重新登录获取 session token。
    使用已注册的邮箱 + 密码走 Auth 流程。
    """
    proxy = _proxy_url()
    registrar = ChatGPTRegistrar(proxy=proxy, log_fn=logger.info)

    try:
        registrar.visit_homepage()
        _human_delay(0.3, 0.8)

        csrf = registrar.get_csrf()
        _human_delay(0.2, 0.5)

        auth_url = registrar.signin(email, csrf)
        _human_delay(0.3, 0.8)

        final_url = registrar.authorize(auth_url)
        final_path = urlparse(final_url).path
        _human_delay(0.3, 0.8)

        if "password" in final_path or "log-in" in final_path:
            url = f"{registrar.AUTH}/api/accounts/password/verify"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Referer": f"{registrar.AUTH}/log-in/password",
                "Origin": registrar.AUTH,
            }
            headers.update(_make_trace_headers())
            r = registrar.session.post(url, json={"password": password}, headers=headers)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                cb = data.get("continue_url") or data.get("url")
                if cb:
                    registrar.callback(cb)
                return registrar.extract_session_token()

        elif "chatgpt.com" in final_url or "callback" in final_path:
            return registrar.extract_session_token()

        logger.error(f"刷新 token 失败: 未知落地页 {final_url}")
        return None

    except Exception as e:
        logger.error(f"刷新 token 失败 {email}: {e}")
        return None


def refresh_oauth_tokens(refresh_token: str, log_fn=None) -> Optional[Dict[str, Any]]:
    """
    使用 refresh_token 直接向 auth.openai.com 申请新的一组 OAuth token。

    返回 access_token / refresh_token / id_token / expires_in 等字段。
    """
    proxy = _proxy_url()
    fp = generate_fingerprint()
    session = curl_requests.Session(impersonate=fp["impersonate"])
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    logger_fn = log_fn or logger.info
    try:
        resp = session.post(
            f"{OAUTH_ISSUER}/oauth/token",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": fp["user_agent"],
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            timeout=60,
        )
    except Exception as exc:
        logger_fn(f"[OAuth-refresh] refresh_token 交换异常: {exc}")
        session.close()
        return None

    try:
        if resp.status_code != 200:
            logger_fn(f"[OAuth-refresh] refresh_token 交换失败: {resp.status_code} {resp.text[:200]}")
            return None

        tokens = resp.json()
        if tokens.get("access_token") and tokens.get("refresh_token"):
            return tokens

        logger_fn("[OAuth-refresh] 响应缺少 access_token 或 refresh_token")
        return None
    finally:
        session.close()


def fetch_tokens_for_account(email: str, password: str, log_lines: list) -> dict:
    """
    为已注册的账号获取 OAuth Token (同步函数)。
    用于注册时 Token 获取失败的账号, 补充获取 access_token / refresh_token。

    返回: { success, access_token, refresh_token, id_token, expires_in, error }
    """
    def log_fn(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logger.info(msg)
        log_lines.append(line)

    proxy = _proxy_url()
    if proxy:
        log_fn(f"  代理: {proxy}")

    registrar = ChatGPTRegistrar(proxy=proxy, log_fn=log_fn)
    log_fn(f"═══ 补获 Token: {email} ═══")
    log_fn(f"  Chrome {registrar.major} ({registrar.impersonate}) | {registrar.fp['platform_name']} | {registrar.fp['screen_resolution']}")

    result = {
        "success": False,
        "access_token": None,
        "refresh_token": None,
        "id_token": None,
        "expires_in": None,
        "error": None,
    }

    try:
        tokens = registrar.oauth_login(email, password)
        if tokens:
            result["access_token"] = tokens.get("access_token")
            result["refresh_token"] = tokens.get("refresh_token")
            result["id_token"] = tokens.get("id_token")
            result["expires_in"] = tokens.get("expires_in")
            result["success"] = True
            log_fn("  ✅ Codex Token 获取成功")
        else:
            result["error"] = "OAuth 流程未成功"
            log_fn("  ❌ OAuth 流程未成功")
    except Exception as e:
        result["error"] = str(e)
        log_fn(f"  ❌ 异常: {e}")

    log_fn(f"═══ 结束: success={result['success']} ═══")
    return result
