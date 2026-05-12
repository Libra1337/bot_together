"""
点歌模块
搜索QQ音乐并分享（QQ客户端原生播放，完整歌曲）
"""

import json
import asyncio
import logging
import urllib.parse
import time

_log = logging.getLogger("QQBot")

# 用户选歌状态 {user_key: {songs: [...], expire: timestamp}}
_select_waiting: dict[str, dict] = {}
SELECT_TIMEOUT = 30  # 选歌超时秒数


async def search_music(keyword: str, limit: int = 5) -> list:
    """
    搜索QQ音乐，返回歌曲列表
    每个元素: {id, mid, name, artist}
    """
    try:
        encoded = urllib.parse.quote(keyword)
        search_data = json.dumps({
            "search": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "num_per_page": limit,
                    "page_num": 1,
                    "query": keyword,
                    "search_type": 0,
                }
            }
        }, ensure_ascii=False)

        encoded_data = urllib.parse.quote(search_data)
        url = f"https://u.y.qq.com/cgi-bin/musicu.fcg?data={encoded_data}"

        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return []

        data = json.loads(raw)
        songs = data.get("search", {}).get("data", {}).get("body", {}).get("song", {}).get("list", [])

        results = []
        for song in songs[:limit]:
            singers = song.get("singer", [{}])
            artist_name = singers[0].get("name", "未知") if singers else "未知"
            results.append({
                "id": song.get("id", 0),
                "mid": song.get("mid", ""),
                "name": song.get("name", "未知"),
                "artist": artist_name,
            })

        return results

    except Exception as e:
        _log.warning(f"搜索音乐失败: {e}")
        return []


def build_song_list(songs: list) -> str:
    """构建歌曲选择列表文本"""
    text = "找到以下歌曲，回复序号选择喵~（30秒内有效）\n"
    text += "━━━━━━━━━━━━━━\n"
    for i, song in enumerate(songs, 1):
        text += f"{i}. {song['name']} - {song['artist']}\n"
    text += "━━━━━━━━━━━━━━\n"
    text += "回复数字序号即可点播~"
    return text


def build_music_share(song: dict) -> str:
    """
    构建音乐分享消息
    QQ音乐播放链接（在QQ内可直接打开QQ音乐播放完整歌曲）
    """
    name = song["name"]
    artist = song["artist"]
    song_mid = song.get("mid", "")

    # QQ音乐在线播放页（在QQ内点击可调起QQ音乐完整播放）
    play_url = f"https://i.y.qq.com/v8/playsong.html?songmid={song_mid}"

    result = f"点歌成功喵~\n"
    result += f"歌名：{name}\n"
    result += f"歌手：{artist}\n"
    result += f"点击播放：{play_url}"

    return result


def set_waiting(user_key: str, songs: list):
    """设置用户的选歌等待状态"""
    _select_waiting[user_key] = {
        "songs": songs,
        "expire": time.time() + SELECT_TIMEOUT,
    }


def get_waiting(user_key: str) -> list | None:
    """获取用户的选歌列表，如果超时则返回None"""
    state = _select_waiting.get(user_key)
    if not state:
        return None

    if time.time() > state["expire"]:
        del _select_waiting[user_key]
        return None

    return state["songs"]


def clear_waiting(user_key: str):
    """清除用户的选歌等待状态"""
    _select_waiting.pop(user_key, None)


def cleanup_expired():
    """清理所有过期的选歌等待状态（供定时清理任务调用）"""
    now = time.time()
    expired = [k for k, v in _select_waiting.items() if now > v.get("expire", 0)]
    for k in expired:
        del _select_waiting[k]
