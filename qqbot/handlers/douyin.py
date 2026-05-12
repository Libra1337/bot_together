"""
抖音视频解析模块
自动识别抖音链接，提取视频信息（标题/作者/播放/点赞/评论/收藏/封面）
支持海外服务器（香港等）：短链接 302 到首页时自动降级处理
"""

import re
import json
import asyncio
import logging
import urllib.parse

_log = logging.getLogger("QQBot")

# 移动端 UA（iesdouyin 移动分享页可靠性更高）
_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)

# PC 端 UA（fallback 用）
_PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def extract_douyin_url(text: str) -> str | None:
    """从文本中提取抖音链接（支持纯文本和 JSON 卡片内容）"""
    if not text:
        return None

    # 1. 直接视频链接（优先级最高）
    match = re.search(r"(https?://www\.douyin\.com/video/(\d+))", text)
    if match:
        return match.group(1)

    match = re.search(r"(https?://www\.iesdouyin\.com/share/video/(\d+))", text)
    if match:
        return match.group(1)

    # 2. 短链接
    match = re.search(r"(https?://v\.douyin\.com/[a-zA-Z0-9]+/?)", text)
    if match:
        return match.group(1)

    return None


def extract_douyin_url_from_segments(message) -> str | None:
    """
    从 OneBot 消息段（数组格式）中提取抖音链接
    支持从 JSON 卡片 (type=json) 和 XML 卡片 (type=xml) 中提取
    """
    if not isinstance(message, list):
        return None

    for seg in message:
        seg_type = seg.get("type", "")
        data = seg.get("data", {})

        # JSON 卡片消息（QQ 内分享抖音时常见）
        if seg_type == "json":
            json_str = data.get("data", "")
            if json_str and ("douyin" in json_str or "抖音" in json_str):
                url = _extract_url_from_json_card(json_str)
                if url:
                    return url

        # XML 卡片消息（小程序分享）
        elif seg_type == "xml":
            xml_str = data.get("data", "")
            if xml_str and ("douyin" in xml_str or "抖音" in xml_str):
                url = _extract_url_from_xml_card(xml_str)
                if url:
                    return url

    return None


def _extract_url_from_json_card(json_str: str) -> str | None:
    """从 JSON 卡片数据中提取抖音链接"""
    try:
        card = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        # 可能是转义过的 JSON
        try:
            card = json.loads(json_str.replace("\\", ""))
        except Exception:
            card = None

    if not card:
        # 直接从字符串中搜索 URL
        return _search_douyin_url_in_text(json_str)

    # 递归搜索 JSON 中的抖音链接
    return _search_douyin_url_in_dict(card)


def _search_douyin_url_in_dict(obj, depth=0) -> str | None:
    """递归搜索字典/列表中的抖音链接"""
    if depth > 10:
        return None

    if isinstance(obj, str):
        return _search_douyin_url_in_text(obj)
    elif isinstance(obj, dict):
        # 优先检查常见的 URL 字段
        for key in ("jumpUrl", "jump_url", "url", "qqdocurl", "preview", "actionData",
                     "appurl", "source_url", "raw_url", "shareUrl", "share_url"):
            val = obj.get(key, "")
            if isinstance(val, str) and ("douyin" in val or "iesdouyin" in val):
                found = _search_douyin_url_in_text(val)
                if found:
                    return found
        # 递归搜索所有值
        for val in obj.values():
            found = _search_douyin_url_in_dict(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _search_douyin_url_in_dict(item, depth + 1)
            if found:
                return found
    return None


def _search_douyin_url_in_text(text: str) -> str | None:
    """从文本中搜索抖音链接"""
    # 完整视频链接
    m = re.search(r"(https?://www\.douyin\.com/video/(\d+))", text)
    if m:
        return m.group(1)

    m = re.search(r"(https?://www\.iesdouyin\.com/share/video/(\d+))", text)
    if m:
        return m.group(1)

    # 短链接
    m = re.search(r"(https?://v\.douyin\.com/[a-zA-Z0-9]+/?)", text)
    if m:
        return m.group(1)

    return None


def _extract_url_from_xml_card(xml_str: str) -> str | None:
    """从 XML 卡片数据中提取抖音链接"""
    # 搜索 url 属性或 href
    for pattern in [
        r'url="(https?://[^"]*douyin[^"]*)"',
        r'href="(https?://[^"]*douyin[^"]*)"',
        r'action="(https?://[^"]*douyin[^"]*)"',
        r'(https?://v\.douyin\.com/[a-zA-Z0-9]+/?)',
        r'(https?://www\.douyin\.com/video/\d+)',
    ]:
        m = re.search(pattern, xml_str)
        if m:
            return m.group(1)
    return None


async def _curl_get(url: str, ua: str = _MOBILE_UA, timeout: int = 10,
                    follow_redirect: bool = True, headers_only: bool = False) -> str:
    """通用 curl GET 请求"""
    args = ["curl", "-s", "--noproxy", "*", "--max-time", str(timeout)]
    if follow_redirect:
        args.append("-L")
    if headers_only:
        args.append("-I")
    args.extend([
        "-H", f"User-Agent: {ua}",
        "-H", "Accept-Language: zh-CN,zh;q=0.9",
        url,
    ])
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace")


async def _resolve_short_url(url: str) -> str | None:
    """
    解析抖音短链接，获取重定向后的真实URL
    海外 IP 可能 302 到首页，此时返回 None
    """
    try:
        raw = await _curl_get(url, headers_only=True, follow_redirect=False)
        match = re.search(r"Location:\s*(https?://\S+)", raw, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            # 检查是否被重定向到首页（海外 IP 的典型行为）
            if location.rstrip("/") == "https://www.douyin.com":
                _log.warning("[抖音] 短链接被重定向到首页（疑似地区限制）")
                return None
            return location
    except Exception as e:
        _log.warning(f"解析抖音短链接失败: {e}")
    return None


async def _resolve_short_url_via_page(url: str) -> str | None:
    """
    备用方案：通过访问短链接页面，从 HTML 中提取 video_id
    适用于海外 IP（302 到首页后，页面 JS 可能包含真实 ID）
    """
    try:
        # 方法1：用 -L 跟随重定向后，搜索最终页面中的 video_id
        html = await _curl_get(url, ua=_MOBILE_UA, timeout=15, follow_redirect=True)
        if html:
            # 从页面内容搜索 video_id
            vid = re.search(r'"aweme_id"\s*:\s*"(\d+)"', html)
            if vid:
                return f"https://www.douyin.com/video/{vid.group(1)}"

            vid = re.search(r'/video/(\d{15,25})', html)
            if vid:
                return f"https://www.douyin.com/video/{vid.group(1)}"

            # 搜索 share_info 中的 aweme_id
            vid = re.search(r'"id"\s*:\s*"(\d{15,25})"', html)
            if vid:
                return f"https://www.douyin.com/video/{vid.group(1)}"
    except Exception as e:
        _log.warning(f"[抖音] 备用短链接解析失败: {e}")
    return None


async def _resolve_short_url_via_api(url: str) -> str | None:
    """
    备用方案2：通过抖音内部 API 尝试解析
    利用 iesdouyin 的 302 重定向（有时和 v.douyin.com 行为不同）
    """
    try:
        # 从短链接提取短码
        short_match = re.search(r"v\.douyin\.com/([a-zA-Z0-9]+)", url)
        if not short_match:
            return None
        short_code = short_match.group(1)

        # 尝试 iesdouyin 的短链接重定向
        ies_url = f"https://www.iesdouyin.com/share/video/?share_id={short_code}"
        raw = await _curl_get(ies_url, headers_only=True, follow_redirect=False, timeout=10)
        match = re.search(r"Location:\s*(https?://\S+)", raw, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            vid = re.search(r'/video/(\d+)', location)
            if vid:
                return f"https://www.douyin.com/video/{vid.group(1)}"

        # 尝试直接 GET iesdouyin，从 HTML 中提取
        html = await _curl_get(ies_url, ua=_MOBILE_UA, timeout=12, follow_redirect=True)
        if html:
            vid = re.search(r'/video/(\d{15,25})', html)
            if vid:
                return f"https://www.douyin.com/video/{vid.group(1)}"

            # 搜索 _ROUTER_DATA 中的 video_id
            router = re.search(r'"aweme_id"\s*:\s*"(\d+)"', html)
            if router:
                return f"https://www.douyin.com/video/{router.group(1)}"
    except Exception as e:
        _log.warning(f"[抖音] API 备用解析失败: {e}")
    return None


def _extract_video_id(url: str) -> str | None:
    """从URL中提取视频ID"""
    match = re.search(r"/video/(\d+)", url)
    if match:
        return match.group(1)
    return None


async def _parse_via_iesdouyin(video_id: str) -> dict | None:
    """
    方法1: 通过 iesdouyin.com 移动分享页解析
    页面内嵌 _ROUTER_DATA JSON，包含完整视频信息
    """
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    try:
        html = await _curl_get(share_url, ua=_MOBILE_UA, timeout=12)
        if not html or len(html) < 100:
            _log.warning("[抖音] iesdouyin 响应为空")
            return None

        # 提取 _ROUTER_DATA
        m = re.search(r'_ROUTER_DATA\s*=\s*(\{.+?\})\s*</script>', html, re.S)
        if not m:
            _log.warning("[抖音] 未找到 _ROUTER_DATA")
            return None

        router_data = json.loads(m.group(1))
        loader_data = router_data.get("loaderData", {})

        # 遍历找到视频页的数据
        video_info_res = None
        for key, val in loader_data.items():
            if isinstance(val, dict) and "videoInfoRes" in val:
                video_info_res = val["videoInfoRes"]
                break

        if not video_info_res:
            _log.warning("[抖音] loaderData 中未找到 videoInfoRes")
            return None

        item_list = video_info_res.get("item_list", [])
        if not item_list:
            # 海外被屏蔽 or 视频不存在
            filters = video_info_res.get("filter_list", [])
            if filters:
                reason = filters[0].get("filter_reason", "")
                _log.warning(f"[抖音] 视频被过滤: {reason}")
            return None

        item = item_list[0]
        desc = item.get("desc", "")
        author = item.get("author", {})
        nickname = author.get("nickname", "")
        stats = item.get("statistics", {})
        digg = stats.get("digg_count", 0)
        comment = stats.get("comment_count", 0)
        share = stats.get("share_count", 0)
        collect = stats.get("collect_count", 0)
        play = stats.get("play_count", 0)

        # 提取封面
        cover = ""
        video_data = item.get("video", {})
        for cover_key in ("origin_cover", "cover", "dynamic_cover"):
            cover_data = video_data.get(cover_key, {})
            if isinstance(cover_data, dict):
                url_list = cover_data.get("url_list", [])
                if url_list and isinstance(url_list, list):
                    cover = url_list[0]
                    break

        return _build_result(video_id, desc, nickname, digg, comment, share, collect, play, cover)

    except json.JSONDecodeError as e:
        _log.warning(f"[抖音] iesdouyin JSON 解析失败: {e}")
    except Exception as e:
        _log.warning(f"[抖音] iesdouyin 解析异常: {e}")
    return None


async def _parse_via_douyin_web(video_id: str) -> dict | None:
    """
    方法2: 通过 douyin.com 网页版解析
    尝试从 RENDER_DATA / meta 标签提取信息
    """
    page_url = f"https://www.douyin.com/video/{video_id}"
    try:
        html = await _curl_get(page_url, ua=_PC_UA, timeout=12)
        if not html or len(html) < 200:
            return None

        desc = ""
        nickname = ""
        digg = 0
        comment = 0
        share = 0
        collect = 0
        play = 0
        cover = ""

        # 尝试 RENDER_DATA（旧版页面可能还有）
        render_match = re.search(r'id="RENDER_DATA"[^>]*>([^<]+)</script>', html)
        if render_match:
            try:
                render_raw = urllib.parse.unquote(render_match.group(1))
                rdata = json.loads(render_raw)

                for key, val in rdata.items():
                    if not isinstance(val, dict):
                        continue
                    aweme = val.get("aweme", {}).get("detail", {})
                    if not aweme:
                        for k2, v2 in val.items():
                            if isinstance(v2, dict) and "desc" in v2:
                                aweme = v2
                                break
                    if aweme and aweme.get("desc"):
                        desc = aweme.get("desc", "")
                        author_info = aweme.get("authorInfo", aweme.get("author", {}))
                        nickname = author_info.get("nickname", "")
                        s = aweme.get("stats", aweme.get("statistics", {}))
                        digg = s.get("diggCount", s.get("digg_count", 0))
                        comment = s.get("commentCount", s.get("comment_count", 0))
                        share = s.get("shareCount", s.get("share_count", 0))
                        collect = s.get("collectCount", s.get("collect_count", 0))
                        play = s.get("playCount", s.get("play_count", 0))

                        vd = aweme.get("video", {})
                        for ck in ("originCover", "origin_cover", "cover"):
                            cd = vd.get(ck, {})
                            if isinstance(cd, dict):
                                ul = cd.get("url_list", cd.get("urlList", []))
                                if ul:
                                    cover = ul[0]
                                    break
                        break
            except Exception as e:
                _log.warning(f"[抖音] RENDER_DATA 解析失败: {e}")

        # 从 meta/title 标签补充
        if not desc:
            og_match = re.search(r'property="og:description"\s+content="([^"]*)"', html)
            if og_match:
                desc = og_match.group(1).strip()

        if not desc:
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html)
            if title_match:
                t = title_match.group(1).strip()
                t = re.sub(r'\s*[-_]\s*抖音.*$', '', t)
                if t and t != "抖音":
                    desc = t

        if not nickname:
            author_match = re.search(r'name="author"\s+content="([^"]*)"', html)
            if author_match:
                nickname = author_match.group(1).strip()

        if not cover:
            og_img = re.search(r'property="og:image"\s+content="([^"]*)"', html)
            if og_img:
                cover = og_img.group(1).strip()

        if not desc and not nickname:
            return None

        return _build_result(video_id, desc, nickname, digg, comment, share, collect, play, cover)

    except Exception as e:
        _log.warning(f"[抖音] douyin.com 解析异常: {e}")
    return None


def _build_result(video_id: str, desc: str, nickname: str,
                  digg: int, comment: int, share: int, collect: int,
                  play: int, cover: str) -> dict:
    """构建统一的返回结果"""
    page_url = f"https://www.douyin.com/video/{video_id}"

    if desc and len(desc) > 100:
        desc = desc[:100] + "..."

    text = "抖音视频解析\n"
    text += "━━━━━━━━━━━━━━\n"
    if nickname:
        text += f"作者：{nickname}\n"
    if desc:
        text += f"描述：{desc}\n"
    if play or digg or comment:
        text += f"播放：{_fmt(play)} | 点赞：{_fmt(digg)} | 评论：{_fmt(comment)}\n"
    if collect or share:
        text += f"收藏：{_fmt(collect)} | 分享：{_fmt(share)}\n"
    text += "━━━━━━━━━━━━━━\n"
    text += f"链接：{page_url}"

    return {"text": text, "cover": cover}


async def get_video_info(url: str) -> dict | None:
    """
    获取抖音视频信息
    返回 {"text": "格式化文本", "cover": "封面URL"} 或 None

    解析优先级：
    1. 如果是完整链接（含 video_id），直接用 iesdouyin 解析
    2. 如果是短链接，尝试解析 302 获取 video_id
    3. 短链接 302 失败（海外 IP），尝试备用方法
    4. iesdouyin 移动分享页（_ROUTER_DATA，数据最全）
    5. douyin.com 网页版（RENDER_DATA / meta 标签，兼容旧版）
    6. 返回基本链接信息
    """
    try:
        video_id = _extract_video_id(url)

        # 如果是短链接，需要先解析出 video_id
        if not video_id and "v.douyin.com" in url:
            _log.info(f"[抖音] 解析短链接: {url}")

            # 方法1：标准 302 重定向
            real_url = await _resolve_short_url(url)
            if real_url:
                video_id = _extract_video_id(real_url)
                if video_id:
                    _log.info(f"[抖音] 302 解析成功: {video_id}")

            # 方法2：从页面 HTML 中提取（海外 IP 降级）
            if not video_id:
                _log.info("[抖音] 302 解析失败，尝试从页面提取...")
                real_url = await _resolve_short_url_via_page(url)
                if real_url:
                    video_id = _extract_video_id(real_url)
                    if video_id:
                        _log.info(f"[抖音] 页面提取成功: {video_id}")

            # 方法3：通过 iesdouyin API 尝试
            if not video_id:
                _log.info("[抖音] 页面提取失败，尝试 iesdouyin API...")
                real_url = await _resolve_short_url_via_api(url)
                if real_url:
                    video_id = _extract_video_id(real_url)
                    if video_id:
                        _log.info(f"[抖音] iesdouyin API 解析成功: {video_id}")

        if not video_id:
            _log.warning(f"[抖音] 无法从链接中提取 video_id: {url}")
            return {
                "text": (
                    "抖音视频解析\n"
                    "━━━━━━━━━━━━━━\n"
                    "（短链接解析失败，可能是地区限制）\n"
                    "请尝试发送完整链接（包含 /video/数字 的链接）\n"
                    "━━━━━━━━━━━━━━"
                ),
                "cover": "",
            }

        _log.info(f"[抖音] 开始解析视频: {video_id}")

        # 方法1: iesdouyin（优先，数据最全，海外可用）
        result = await _parse_via_iesdouyin(video_id)
        if result:
            _log.info("[抖音] iesdouyin 解析成功")
            return result

        # 方法2: douyin.com 网页版（fallback）
        result = await _parse_via_douyin_web(video_id)
        if result:
            _log.info("[抖音] douyin.com 解析成功")
            return result

        # 方法3: 都失败了，返回基本信息
        _log.warning("[抖音] 所有解析方法均失败，返回基本信息")
        page_url = f"https://www.douyin.com/video/{video_id}"
        text = (
            f"抖音视频解析\n"
            f"━━━━━━━━━━━━━━\n"
            f"视频ID：{video_id}\n"
            f"（视频详细信息获取失败，可能是地区限制或视频已删除）\n"
            f"━━━━━━━━━━━━━━\n"
            f"链接：{page_url}"
        )
        return {"text": text, "cover": ""}

    except Exception as e:
        _log.warning(f"抖音解析失败: {e}")
        return None


def _fmt(n) -> str:
    """格式化数字：超过1万显示 x.x万"""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)
