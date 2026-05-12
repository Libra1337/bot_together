"""
网页爬虫模块
使用 curl 抓取网页内容，解析 HTML 提取正文摘要
"""

import re
import asyncio
import logging
from html.parser import HTMLParser

_log = logging.getLogger("QQBot")

# curl 超时配置
CURL_MAX_TIME = 15
CURL_MAX_REDIRS = 5
# 正文截断长度
MAX_CONTENT_LEN = 1500
# 下载大小限制（字节）
MAX_DOWNLOAD_SIZE = "2097152"  # 2MB

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def is_valid_url(text: str) -> bool:
    """检查文本是否为合法的 HTTP(S) URL"""
    return bool(re.match(r"https?://[^\s]+", text.strip()))


def extract_url(text: str) -> str | None:
    """从文本中提取第一个 URL（排除 QQ 系内部链接）"""
    # QQ 系域名不走网页爬虫
    _QQ_INTERNAL = (
        "qm.qq.com",
        "ti.qq.com",
        "url.cn",
        "qq.com/invite",
        "jq.qq.com",
        "qun.qq.com",
        "c.pc.qq.com",
        "i.qq.com",
        "connect.qq.com",
        "graph.qq.com",
        "qzone.qq.com",
        "group.qq.com",
        "docs.qq.com",
    )
    m = re.search(r"(https?://[^\s]+)", text.strip())
    if not m:
        return None
    url = m.group(1)
    for domain in _QQ_INTERNAL:
        if domain in url:
            return None
    return url


class _TextExtractor(HTMLParser):
    """从 HTML 中提取正文文本的解析器"""

    # 需要跳过的标签（其内容也跳过）
    SKIP_TAGS = {
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "noscript",
        "svg",
        "iframe",
        "form",
    }

    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_depth = 0  # > 0 表示在 SKIP_TAGS 内部
        self._texts: list[str] = []
        self.links: list[dict] = []  # {"text": ..., "href": ...}
        self._current_link: dict | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        # 提取 meta description
        if tag == "meta":
            attr_dict = dict(attrs)
            name = attr_dict.get("name", "").lower()
            if name == "description":
                self.description = attr_dict.get("content", "")
        # 提取链接
        if tag == "a" and self._skip_depth == 0:
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "")
            if href and href.startswith("http"):
                self._current_link = {"text": "", "href": href}
        # 块级元素添加换行
        if tag in (
            "p",
            "div",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "tr",
            "article",
            "section",
        ):
            self._texts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._current_link is not None:
            text = self._current_link["text"].strip()
            if text and len(text) > 1:
                self.links.append(self._current_link)
            self._current_link = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip_depth == 0:
            self._texts.append(data)
        if self._current_link is not None:
            self._current_link["text"] += data

    def get_text(self) -> str:
        raw = "".join(self._texts)
        # 合并连续空白和换行
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


async def fetch_page(url: str) -> tuple[bool, str]:
    """
    使用 curl 抓取网页
    返回 (success, html_or_error)
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "-L",  # 跟随重定向
            "--max-time",
            str(CURL_MAX_TIME),
            "--max-redirs",
            str(CURL_MAX_REDIRS),
            "--max-filesize",
            MAX_DOWNLOAD_SIZE,
            "-H",
            f"User-Agent: {USER_AGENT}",
            "-H",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H",
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            # curl 退出码 63 = 超出 max-filesize
            if proc.returncode == 63:
                return False, "页面太大了喵，超过了 2MB 限制~"
            return False, f"请求失败喵 (curl code={proc.returncode}): {err[:150]}"

        # 尝试多种编码解码
        raw = stdout
        html = ""

        # 先尝试 utf-8
        try:
            html = raw.decode("utf-8")
        except UnicodeDecodeError:
            # 尝试从 HTML 中检测 charset
            raw_partial = raw[:4096].decode("ascii", errors="replace")
            charset_match = re.search(
                r'charset[="\s]+([a-zA-Z0-9\-]+)', raw_partial, re.IGNORECASE
            )
            encoding = charset_match.group(1) if charset_match else "gbk"
            try:
                html = raw.decode(encoding, errors="replace")
            except (UnicodeDecodeError, LookupError):
                html = raw.decode("utf-8", errors="replace")

        if not html.strip():
            return False, "页面返回了空内容喵~"

        return True, html

    except Exception as e:
        _log.warning(f"[爬虫] 抓取失败: {e}")
        return False, f"抓取出错了喵: {str(e)[:100]}"


def extract_content(html: str, url: str) -> dict:
    """
    从 HTML 中提取正文内容
    返回 {"title": str, "description": str, "content": str, "url": str}
    """
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception as e:
        _log.warning(f"[爬虫] HTML解析出错: {e}")

    title = parser.title.strip()
    description = parser.description.strip()
    content = parser.get_text()

    # 截断正文
    if len(content) > MAX_CONTENT_LEN:
        content = content[:MAX_CONTENT_LEN] + "...(内容已截断)"

    # 截断标题
    if len(title) > 100:
        title = title[:100] + "..."

    # 截断描述
    if len(description) > 200:
        description = description[:200] + "..."

    # 收集页面内发现的链接（去重，最多保留15个）
    seen_hrefs = set()
    unique_links = []
    for link in parser.links:
        href = link["href"].split("#")[0].rstrip("/")  # 去锚点、去尾部斜杠
        if href not in seen_hrefs and href != url.rstrip("/"):
            seen_hrefs.add(href)
            unique_links.append(link)
            if len(unique_links) >= 15:
                break

    return {
        "title": title or "（无标题）",
        "description": description,
        "content": content or "（未能提取到正文内容）",
        "url": url,
        "links": unique_links,
    }


def build_result_msg(info: dict) -> str:
    """构建爬虫结果消息"""
    msg = f"🌐 网页抓取结果\n"
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"📌 标题：{info['title']}\n"

    if info["description"]:
        msg += f"📝 描述：{info['description']}\n"

    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"📄 正文内容：\n{info['content']}\n"
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"🔗 来源：{info['url']}"

    return msg


def build_links_text(links: list[dict]) -> str:
    """构建页面发现的链接列表文本，供 AI 分析时参考"""
    if not links:
        return ""
    text = ""
    for i, link in enumerate(links, 1):
        text += f"{i}. [{link['text']}] → {link['href']}\n"
    return text.strip()
