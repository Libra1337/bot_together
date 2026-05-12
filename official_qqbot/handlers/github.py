"""
GitHub 搜索模块
搜索 GitHub 仓库，展示列表供选择
"""

import json
import asyncio
import logging
import urllib.parse
import time

_log = logging.getLogger("QQBot")

# 用户选择状态 {user_key: {repos: [...], expire: timestamp}}
_select_waiting: dict[str, dict] = {}
SELECT_TIMEOUT = 30


def _format_stars(n: int) -> str:
    """格式化 star 数"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


async def search_repos(keyword: str, limit: int = 5) -> list:
    """
    搜索 GitHub 仓库
    返回 [{name, full_name, description, stars, url, language}, ...]
    """
    try:
        encoded = urllib.parse.quote(keyword)
        url = f"https://api.github.com/search/repositories?q={encoded}&per_page={limit}&sort=stars"

        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0",
            "-H", "Accept: application/vnd.github.v3+json",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return []

        data = json.loads(raw)
        items = data.get("items", [])

        results = []
        for repo in items[:limit]:
            desc = repo.get("description", "") or ""
            if len(desc) > 60:
                desc = desc[:60] + "..."
            results.append({
                "full_name": repo.get("full_name", ""),
                "description": desc,
                "stars": repo.get("stargazers_count", 0),
                "url": repo.get("html_url", ""),
                "language": repo.get("language", "") or "",
            })

        return results

    except Exception as e:
        _log.warning(f"GitHub 搜索失败: {e}")
        return []


def build_repo_list(repos: list) -> str:
    """构建仓库选择列表"""
    text = "GitHub 搜索结果，回复序号查看详情喵~（30秒内有效）\n"
    text += "━━━━━━━━━━━━━━\n"
    for i, repo in enumerate(repos, 1):
        stars = _format_stars(repo["stars"])
        lang = f" [{repo['language']}]" if repo["language"] else ""
        text += f"{i}. {repo['full_name']} ⭐{stars}{lang}\n"
        if repo["description"]:
            text += f"   {repo['description']}\n"
    text += "━━━━━━━━━━━━━━\n"
    text += "回复数字序号获取链接~"
    return text


def build_repo_detail(repo: dict) -> str:
    """构建仓库详情消息"""
    stars = _format_stars(repo["stars"])
    lang = repo["language"] if repo["language"] else "未知"

    text = f"GitHub 仓库\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"名称：{repo['full_name']}\n"
    text += f"语言：{lang} | Star：⭐{stars}\n"
    if repo["description"]:
        text += f"简介：{repo['description']}\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"链接：{repo['url']}"
    return text


def set_waiting(user_key: str, repos: list):
    _select_waiting[user_key] = {
        "repos": repos,
        "expire": time.time() + SELECT_TIMEOUT,
    }


def get_waiting(user_key: str) -> list | None:
    state = _select_waiting.get(user_key)
    if not state:
        return None
    if time.time() > state["expire"]:
        del _select_waiting[user_key]
        return None
    return state["repos"]


def clear_waiting(user_key: str):
    _select_waiting.pop(user_key, None)


def cleanup_expired():
    """清理所有过期的仓库选择等待状态（供定时清理任务调用）"""
    now = time.time()
    expired = [k for k, v in _select_waiting.items() if now > v.get("expire", 0)]
    for k in expired:
        del _select_waiting[k]
