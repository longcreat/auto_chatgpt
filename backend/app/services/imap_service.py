"""
IMAP 邮件接收服务
用于读取 Cloudflare 转发到真实邮箱的 ChatGPT 验证邮件，提取验证码/链接
支持 163.com / Gmail / 其他 IMAP 服务
"""

import imaplib
import email
import re
import time
import asyncio
import logging
from email.header import decode_header
from typing import Optional, Tuple
from app.services.settings_service import get_imap_config

logger = logging.getLogger(__name__)


def _decode_str(s):
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="ignore")
    return s or ""


def _get_text_from_email(msg) -> str:
    """递归提取邮件文本内容"""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    text += payload.decode("utf-8", errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="ignore")
    return text


def _extract_otp(text: str) -> Optional[str]:
    """从邮件正文提取 6 位数字验证码"""
    patterns = [
        r"verification code[:\s]*(\d{6})",
        r"login code[:\s]*(\d{6})",
        r"code is[:\s]*(\d{6})",
        r"verify.*?(\d{6})",
        r"<strong>(\d{6})</strong>",
        r"<b>(\d{6})</b>",
        r"\b(\d{6})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_verify_link(text: str) -> Optional[str]:
    """从邮件正文提取验证链接"""
    pattern = r'https://[^\s"<>]+auth[^\s"<>]+'
    m = re.search(pattern, text)
    if m:
        return m.group(0)
    return None


def wait_for_verification_email_sync(
    to_email: str,
    timeout: int = 120,
    poll_interval: int = 5,
) -> Tuple[Optional[str], Optional[str]]:
    """
    同步版本: 等待 ChatGPT 发往 to_email 的验证邮件。
    供纯 HTTP 注册服务直接调用 (无需 asyncio)。
    返回 (otp_code, verify_link)，超时返回 (None, None)
    """
    return _blocking_wait_for_email(to_email, timeout, poll_interval)


async def wait_for_verification_email(
    to_email: str,
    timeout: int = 120,
    poll_interval: int = 5,
) -> Tuple[Optional[str], Optional[str]]:
    """
    异步版本: 等待 ChatGPT 发往 to_email 的验证邮件。
    返回 (otp_code, verify_link)，超时返回 (None, None)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _blocking_wait_for_email,
        to_email,
        timeout,
        poll_interval,
    )


def _imap_id_command(imap: imaplib.IMAP4_SSL):
    """
    163/126/yeah.net 要求登录后发送 IMAP ID 命令，
    否则会拒绝搜索并返回 'please use official client'。
    使用 xatom 发送自定义命令，避免 imaplib 内部状态混乱。
    """
    try:
        # 注册 ID 命令到 imaplib 允许列表，使其在 AUTH 状态可用
        imaplib.Commands["ID"] = ("AUTH", "SELECTED")
        typ, dat = imap._simple_command(
            "ID",
            '("name" "AutoChatGPT" "version" "1.0" '
            '"vendor" "AutoChatGPT" "contact" "admin@autochatgpt.com")',
        )
        logger.info(f"[IMAP] ID 命令: {typ}")
    except Exception as e:
        logger.warning(f"[IMAP] ID 命令异常 (非致命): {e}")


def _blocking_wait_for_email(
    to_email: str,
    timeout: int,
    poll_interval: int,
) -> Tuple[Optional[str], Optional[str]]:
    """
    轮询 IMAP 等待 OpenAI 验证邮件。
    ▸ 163.com 的 IMAP SEARCH TO/FROM 对 Cloudflare 转发邮件无效
      (搜索的是信封地址而非 message header)，所以改用 SINCE + Python 端过滤。
    ▸ UNSEEN 标志也不可靠 (转发邮件可能被自动标记已读)，
      因此用 seen_nums 集合追踪已处理的邮件号。
    """
    import datetime

    start = time.time()
    imap = None
    poll_count = 0
    seen_nums: set = set()  # 已检查过的邮件序列号
    today_str = datetime.datetime.utcnow().strftime("%d-%b-%Y")

    logger.info(f"[IMAP] 开始轮询验证码 → {to_email} (timeout={timeout}s, interval={poll_interval}s)")
    imap_cfg = get_imap_config()
    logger.info(f"[IMAP] 服务器: {imap_cfg['host']}:{imap_cfg['port']}, 用户: {imap_cfg['user']}")
    logger.info(f"[IMAP] 搜索策略: SINCE {today_str} + Python 过滤 TO/FROM header")

    try:
        imap = imaplib.IMAP4_SSL(imap_cfg["host"], imap_cfg["port"])
        logger.info("[IMAP] SSL 连接成功")

        imap.login(imap_cfg["user"], imap_cfg["password"])
        logger.info("[IMAP] 登录成功")

        # 163/126 系邮箱必须在 select 前发送 ID 命令
        _imap_id_command(imap)

        typ, dat = imap.select("INBOX")
        if typ != "OK":
            logger.error(f"[IMAP] SELECT INBOX 失败: {typ} {dat}")
            return None, None
        logger.info("[IMAP] INBOX 已选择, 开始轮询 ...")

        # 记录当前已有的所有邮件号，只处理之后新到的
        status0, nums0 = imap.search(None, f'(SINCE "{today_str}")')
        if status0 == "OK" and nums0[0]:
            seen_nums = set(nums0[0].split())
            logger.info(f"[IMAP] 初始邮件数 (今日): {len(seen_nums)}, 仅处理之后到达的新邮件")
        else:
            logger.info("[IMAP] 今日暂无邮件")

        while time.time() - start < timeout:
            poll_count += 1
            elapsed = int(time.time() - start)
            logger.info(f"[IMAP] 第 {poll_count} 次轮询 (已过 {elapsed}s / {timeout}s)")

            # NOOP 刷新邮箱状态, 让服务器通知新邮件到达
            imap.noop()

            # 163.com IMAP SEARCH TO/FROM 对 Cloudflare 转发邮件无效
            # 改用 SINCE date 搜索, 然后在 Python 端过滤 header
            status, nums = imap.search(None, f'(SINCE "{today_str}")')

            if status == "OK" and nums[0]:
                msg_nums = nums[0].split()
                new_nums = [n for n in msg_nums if n not in seen_nums]

                if new_nums:
                    logger.info(f"[IMAP] 发现 {len(new_nums)} 封新邮件 (今日共 {len(msg_nums)})")

                    for num in new_nums:
                        seen_nums.add(num)

                        # 先用 BODY.PEEK 读取 header (不标记已读)
                        _, data = imap.fetch(
                            num, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
                        )
                        raw_header = data[0][1].decode("utf-8", errors="ignore")
                        msg_hdr = email.message_from_string(raw_header)

                        to_hdr = str(msg_hdr.get("To", "")).lower()
                        from_hdr = str(msg_hdr.get("From", "")).lower()
                        subject_raw = msg_hdr.get("Subject", "")
                        # 解码 MIME 编码的 Subject
                        decoded_parts = decode_header(subject_raw)
                        subject = "".join(
                            part.decode(enc or "utf-8", errors="ignore")
                            if isinstance(part, bytes) else str(part)
                            for part, enc in decoded_parts
                        )

                        logger.info(
                            f"[IMAP]   邮件 #{num.decode()}: "
                            f"From={from_hdr[:50]}, To={to_hdr[:50]}, Subject={subject[:60]}"
                        )

                        # 过滤: TO 必须包含目标邮箱
                        if to_email.lower() not in to_hdr:
                            logger.info(f"[IMAP]   → 跳过 (TO 不匹配)")
                            continue

                        # 过滤: FROM 必须来自 openai
                        if "openai" not in from_hdr:
                            logger.info(f"[IMAP]   → 跳过 (非 OpenAI 发件人)")
                            continue

                        # 匹配! 优先从 Subject 提取 OTP
                        otp = _extract_otp(subject)

                        if not otp:
                            # Subject 没有, 再从正文提取
                            _, body_data = imap.fetch(num, "(RFC822)")
                            raw = body_data[0][1]
                            msg_full = email.message_from_bytes(raw)
                            text = _get_text_from_email(msg_full)
                            otp = _extract_otp(text)
                            link = _extract_verify_link(text)
                        else:
                            link = None

                        logger.info(f"[IMAP]   → OTP={otp}, link={'有' if link else '无'}")

                        if otp or link:
                            imap.store(num, "+FLAGS", "\\Seen")
                            logger.info(f"[IMAP] ✅ 验证码获取成功: OTP={otp}")
                            return otp, link
                else:
                    logger.info(f"[IMAP] 无新邮件")
            else:
                logger.info(f"[IMAP] 无新邮件")

            time.sleep(poll_interval)

    except Exception as e:
        logger.error(f"[IMAP] ❌ 错误: {e}", exc_info=True)
    finally:
        if imap:
            try:
                imap.close()
                imap.logout()
            except Exception:
                pass

    return None, None
