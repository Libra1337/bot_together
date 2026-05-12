"""
B站视频解析模块
自动识别B站链接/BV号，返回视频信息卡片
"""

import re
import json
import asyncio
import logging

_log = logging.getLogger("QQBot")

# 匹配B站链接的正则
BILIBILI_PATTERNS = [
    r"BV[a-zA-Z0-9]{10}",                           # BV号
    r"av(\d+)",                                       # av号
    r"bilibili\.com/video/(BV[a-zA-Z0-9]{10})",      # 完整链接
    r"bilibili\.com/video/av(\d+)",                   # av链接
    r"b23\.tv/([a-zA-Z0-9]+)",                        # 短链接
]


def extract_bilibili_id(text: str) -> str | None:
    """
    从文本中提取B站视频ID
    返回 BV号 或 None
    """
    # 如果文本包含抖音域名，跳过B站解析（避免误匹配抖音分享文案中的数字）
    if re.search(r"(v\.douyin\.com|douyin\.com/video|iesdouyin\.com)", text):
        return None

    # 先匹配BV号
    match = re.search(r"(BV[a-zA-Z0-9]{10})", text)
    if match:
        return match.group(1)

    # 匹配av号（需要前面是边界 + 至少3位数字，避免误匹配）
    match = re.search(r"(?<![a-zA-Z])av(\d{3,})", text, re.IGNORECASE)
    if match:
        return f"av{match.group(1)}"

    # 匹配短链接 b23.tv
    match = re.search(r"b23\.tv/([a-zA-Z0-9]+)", text)
    if match:
        return f"b23:{match.group(1)}"

    return None


def _format_number(n) -> str:
    """格式化数字：10000 -> 1.0万"""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)

    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _format_duration(seconds) -> str:
    """格式化时长：125 -> 02:05"""
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return str(seconds)

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


async def resolve_short_link(short_code: str) -> str | None:
    """解析b23.tv短链接，获取真实BV号"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sI", "--noproxy", "*", "--max-time", "5",
            "-L", f"https://b23.tv/{short_code}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace")

        # 从重定向的URL中提取BV号
        match = re.search(r"(BV[a-zA-Z0-9]{10})", raw)
        if match:
            return match.group(1)
    except Exception as e:
        _log.warning(f"解析B站短链接失败: {e}")

    return None


async def get_video_info(video_id: str) -> dict | None:
    """
    获取B站视频信息
    video_id: BV号、av号 或 b23:短码
    返回 {"text": "文字信息", "cover": "封面URL"} 或 None
    """
    # 处理短链接
    if video_id.startswith("b23:"):
        short_code = video_id[4:]
        bv = await resolve_short_link(short_code)
        if not bv:
            return None
        video_id = bv

    # 构建API URL
    if video_id.startswith("BV"):
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={video_id}"
    elif video_id.startswith("av"):
        aid = video_id[2:]
        api_url = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
    else:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-H", "Referer: https://www.bilibili.com",
            api_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return None

        data = json.loads(raw)

        if data.get("code") != 0:
            _log.warning(f"B站API返回错误: {data.get('message', '')}")
            return None

        info = data.get("data", {})
        stat = info.get("stat", {})
        owner = info.get("owner", {})

        title = info.get("title", "未知标题")
        up_name = owner.get("name", "未知UP主")
        duration = _format_duration(info.get("duration", 0))
        view = _format_number(stat.get("view", 0))
        danmaku = _format_number(stat.get("danmaku", 0))
        like = _format_number(stat.get("like", 0))
        coin = _format_number(stat.get("coin", 0))
        favorite = _format_number(stat.get("favorite", 0))
        bvid = info.get("bvid", video_id)
        desc = info.get("desc", "")
        cover = info.get("pic", "")  # 封面图URL

        # 截断简介
        if desc and len(desc) > 80:
            desc = desc[:80] + "..."

        text = f"B站视频解析\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"标题：{title}\n"
        text += f"UP主：{up_name}\n"
        text += f"时长：{duration}\n"
        text += f"播放：{view} | 弹幕：{danmaku}\n"
        text += f"点赞：{like} | 投币：{coin} | 收藏：{favorite}\n"
        if desc:
            text += f"简介：{desc}\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"链接：https://www.bilibili.com/video/{bvid}"

        return {"text": text, "cover": cover}

    except Exception as e:
        _log.warning(f"获取B站视频信息失败: {e}")
        return None
