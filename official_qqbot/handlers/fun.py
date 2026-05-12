"""
趣味功能模块
签到、运势、天气查询、赞我、今日人品、表情包等
"""

import os
import json
import random
import hashlib
import asyncio
import logging
import re as _re
import time as _time_mod
from datetime import datetime, date

_log = logging.getLogger("QQBot")

# 签到数据文件
SIGN_DATA_FILE = "data/sign_data.json"


def _ensure_data_dir():
    """确保 data 目录存在"""
    os.makedirs("data", exist_ok=True)


# ====== 表情包收集系统 ======
STICKER_DATA_FILE = "data/stickers.json"
# 内存中的表情包缓存 {summary: [sticker_info, ...]}
_sticker_cache: dict[str, list[dict]] = {}
# 全部表情包列表（用于随机发送）
_sticker_list: list[dict] = []


def _load_stickers():
    """从文件加载已收集的表情包"""
    global _sticker_cache, _sticker_list
    _ensure_data_dir()
    if os.path.exists(STICKER_DATA_FILE):
        try:
            with open(STICKER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _sticker_list = data.get("stickers", [])
                # 按 summary 分类索引
                _sticker_cache.clear()
                for s in _sticker_list:
                    summary = s.get("summary", "")
                    if summary not in _sticker_cache:
                        _sticker_cache[summary] = []
                    _sticker_cache[summary].append(s)
                _log.info(f"[表情包] 已加载 {len(_sticker_list)} 个表情包，{len(_sticker_cache)} 个分类")
        except Exception as e:
            _log.warning(f"[表情包] 加载失败: {e}")
            _sticker_list = []
            _sticker_cache = {}
    else:
        _sticker_list = []
        _sticker_cache = {}


def _save_stickers():
    """保存表情包到文件"""
    _ensure_data_dir()
    try:
        with open(STICKER_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"stickers": _sticker_list}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning(f"[表情包] 保存失败: {e}")


# 启动时加载
_load_stickers()


def collect_sticker(sticker_info: dict) -> bool:
    """
    收集一个表情包，如果是新的则存储
    sticker_info 格式: {"url": str, "summary": str, "emoji_id": str, "emoji_package_id": str, "key": str}
    返回是否是新收集的
    """
    # 用 url 或 (emoji_id + emoji_package_id) 去重
    key = sticker_info.get("url", "") or f"{sticker_info.get('emoji_id', '')}_{sticker_info.get('emoji_package_id', '')}"
    for existing in _sticker_list:
        existing_key = existing.get("url", "") or f"{existing.get('emoji_id', '')}_{existing.get('emoji_package_id', '')}"
        if existing_key == key:
            return False

    # 新表情包
    sticker_info["collected_at"] = _time_mod.time()
    _sticker_list.append(sticker_info)
    summary = sticker_info.get("summary", "")
    if summary not in _sticker_cache:
        _sticker_cache[summary] = []
    _sticker_cache[summary].append(sticker_info)

    # 每收集 10 个保存一次
    if len(_sticker_list) % 10 == 0:
        _save_stickers()
    else:
        _save_stickers()  # 先全量保存，后续可以优化

    _log.info(f"[表情包] 新收集: {summary} (总计: {len(_sticker_list)})")
    return True


def extract_mfaces(message) -> list[dict]:
    """
    从 OneBot 消息中提取所有 mface (商城表情/表情包) 信息
    返回 [{"url": ..., "summary": ..., "emoji_id": ..., "emoji_package_id": ..., "key": ...}, ...]
    """
    mfaces = []
    if isinstance(message, list):
        for seg in message:
            seg_type = seg.get("type", "")
            if seg_type == "mface":
                data = seg.get("data", {})
                mface_info = {
                    "url": data.get("url", ""),
                    "summary": data.get("summary", ""),
                    "emoji_id": data.get("emoji_id", data.get("emojiId", "")),
                    "emoji_package_id": data.get("emoji_package_id", data.get("emojiPackageId", "")),
                    "key": data.get("key", ""),
                }
                mfaces.append(mface_info)
    elif isinstance(message, str):
        # CQ 码格式: [CQ:mface,url=...,summary=...,emoji_id=...,...]
        for m in _re.finditer(r'\[CQ:mface,([^\]]+)\]', message):
            params_str = m.group(1)
            params = {}
            for part in params_str.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k.strip()] = v.strip()
            mface_info = {
                "url": params.get("url", ""),
                "summary": params.get("summary", ""),
                "emoji_id": params.get("emoji_id", params.get("emojiId", "")),
                "emoji_package_id": params.get("emoji_package_id", params.get("emojiPackageId", "")),
                "key": params.get("key", ""),
            }
            mfaces.append(mface_info)
    return mfaces


def get_sticker_reply(mface_info: dict) -> str | None:
    """
    根据收到的表情包生成文字回复
    基于表情包的 summary（如 "[开心]", "[哭笑不得]" 等）来回复
    """
    summary = mface_info.get("summary", "").strip()
    if not summary:
        return None

    # 表情包名称回复映射（基于 summary 关键词）
    reply_map = {
        "开心": ["看到你开心曦曦也开心喵~", "嘿嘿~一起开心喵！", "笑容好治愈喵~"],
        "哭": ["不要哭啦喵~曦曦抱抱你！", "呜呜，曦曦陪你喵~", "别难过了喵~"],
        "笑": ["哈哈哈喵~好好笑！", "曦曦也跟着笑了喵~", "太搞笑了喵~"],
        "生气": ["别生气嘛喵~消消火~", "气鼓鼓的也好可爱喵~", "深呼吸~不生气了喵~"],
        "爱": ["曦曦也爱你喵~❤️", "好甜蜜喵~", "爱你哦喵~💕"],
        "比心": ["比心回去喵~💕", "曦曦也比心喵~❤️", "收到爱心了喵~"],
        "可爱": ["你才可爱呢喵~", "可爱可爱~曦曦最可爱了喵！", "好可爱喵~"],
        "无语": ["曦曦也无语了喵...", "这...不知道说啥喵~", "无话可说喵~"],
        "害怕": ["别怕别怕，曦曦在这里喵~", "曦曦保护你喵！", "不可怕的喵~"],
        "吃": ["好饿喵~想吃小鱼干！", "一起吃吃吃喵~", "曦曦也是吃货喵~"],
        "再见": ["拜拜喵~下次再聊！", "再见~曦曦等你回来喵~", "下次见喵~👋"],
        "谢谢": ["不客气喵~", "曦曦随时为你服务喵~", "应该的喵~"],
        "赞": ["你也很棒喵~👍", "太厉害了喵~", "曦曦给你点赞喵~"],
        "OK": ["好的喵~收到！", "OK喵~没问题！", "了解了喵~"],
        "加油": ["加油加油喵！💪", "你是最棒的喵~", "曦曦给你力量喵~"],
        "委屈": ["别委屈了喵~曦曦心疼你", "抱抱~不委屈了喵~", "曦曦安慰你喵~🫂"],
        "惊讶": ["曦曦也惊了喵~", "不敢相信喵！", "真的假的喵？！"],
        "害羞": ["曦曦也害羞了喵~☺️", "羞羞脸喵~", "好害羞喵~"],
        "睡": ["晚安好梦喵~🌙", "曦曦也困了喵~", "做个好梦喵~"],
        "doge": ["doge喵~🐕", "曦曦也doge一下喵~", "汪喵~"],
        "捂脸": ["捂脸.jpg喵~", "好尴尬喵~", "曦曦也想捂脸喵~"],
        "社会": ["社会社会喵~🤙", "惹不起惹不起喵~", "大佬大佬喵~"],
        "叹气": ["唉...怎么了喵~", "别叹气了，开心点喵~", "曦曦也跟着叹气了喵~"],
        "摸头": ["被摸头了喵~好舒服~", "喵呜~再摸摸~", "曦曦喜欢被摸头喵~"],
        "拥抱": ["抱抱你喵~🤗", "暖暖的拥抱喵~", "曦曦也想要拥抱喵~"],
        "亲": ["mua~喵~💋", "曦曦害羞了喵~", "亲一个回去喵~"],
        "斜眼": ["曦曦懂了喵~😏", "你懂我懂喵~", "嘿嘿嘿喵~"],
        "得意": ["好厉害喵~", "太酷了喵~😎", "曦曦崇拜你喵~"],
        "难过": ["不要难过了喵~曦曦陪你", "抱抱，会好起来的喵~", "曦曦在这里喵~"],
        "呆": ["发呆中喵~", "一起发呆吧喵~☁️", "曦曦也呆住了喵~"],
        "打": ["别打曦曦喵~😿", "曦曦的猫猫拳喵！", "不许打架喵~"],
        "666": ["666喵~🔥", "六六六喵~太强了！", "大佬666喵~"],
        "红包": ["曦曦也想要红包喵~🧧", "谢谢红包喵~", "曦曦收到了喵~"],
        "大哭": ["呜呜呜~不要大哭喵~", "曦曦也跟着哭了喵~😭", "别哭了喵~抱抱"],
        "翻白眼": ["白眼.jpg喵~", "无语了喵~🙄", "曦曦翻了个白眼喵~"],
    }

    # 在 summary 中匹配关键词
    for keyword, replies in reply_map.items():
        if keyword in summary:
            return random.choice(replies)

    # 通用兜底回复
    fallback = [
        f"好有趣的表情包喵~",
        f"曦曦也想要这个表情包喵~",
        f"这个表情包好可爱喵~",
        f"哈哈~有意思的表情包喵~",
        f"曦曦收到了喵~",
    ]
    return random.choice(fallback)


def get_random_sticker() -> dict | None:
    """随机获取一个已收集的表情包，用于 AI 回复时附带"""
    if not _sticker_list:
        return None
    return random.choice(_sticker_list)


def find_sticker_by_keyword(keyword: str) -> dict | None:
    """
    根据关键词查找匹配的表情包
    用于 AI 回复中 [sticker:关键词] 标签的替换
    """
    keyword = keyword.strip()
    if not keyword:
        return None

    # 精确匹配 summary
    if keyword in _sticker_cache:
        return random.choice(_sticker_cache[keyword])

    # 模糊匹配：关键词包含在 summary 中，或 summary 包含关键词
    candidates = []
    for summary, stickers in _sticker_cache.items():
        if keyword in summary or summary in keyword:
            candidates.extend(stickers)

    if candidates:
        return random.choice(candidates)

    return None


def build_sticker_cq(sticker: dict) -> str:
    """
    根据表情包信息构建 CQ 码
    NapCat 发送 mface 需要: url, emoji_id, emoji_package_id, key, summary
    如果缺少关键字段，回退到发送图片
    """
    url = sticker.get("url", "")
    emoji_id = sticker.get("emoji_id", "")
    emoji_package_id = sticker.get("emoji_package_id", "")
    key = sticker.get("key", "")
    summary = sticker.get("summary", "")

    if emoji_id and emoji_package_id and key:
        # 完整的 mface 格式
        parts = [f"[CQ:mface"]
        if url:
            parts.append(f",url={url}")
        parts.append(f",emoji_id={emoji_id}")
        parts.append(f",emoji_package_id={emoji_package_id}")
        parts.append(f",key={key}")
        if summary:
            parts.append(f",summary={summary}")
        parts.append("]")
        return "".join(parts)
    elif url:
        # 回退：用图片方式发送
        return f"[CQ:image,file={url}]"
    return ""


def process_ai_stickers(reply_text: str) -> str:
    """
    处理 AI 回复中的 [sticker:关键词] 标签
    将其替换为对应的表情包 CQ 码
    如果找不到匹配的表情包则移除标签
    """
    def _replace_sticker(match):
        keyword = match.group(1).strip()
        sticker = find_sticker_by_keyword(keyword)
        if sticker:
            cq = build_sticker_cq(sticker)
            if cq:
                return cq
        return ""  # 找不到表情包就移除标签

    # 匹配 [sticker:xxx] 格式
    result = _re.sub(r'\[sticker:([^\]]+)\]', _replace_sticker, reply_text)
    return result.strip()


def get_sticker_count() -> int:
    """获取已收集的表情包数量"""
    return len(_sticker_list)


def _load_sign_data() -> dict:
    """加载签到数据"""
    _ensure_data_dir()
    if os.path.exists(SIGN_DATA_FILE):
        with open(SIGN_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_sign_data(data: dict):
    """保存签到数据"""
    _ensure_data_dir()
    with open(SIGN_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def do_sign(user_id: str, nickname: str) -> str:
    """
    签到功能
    返回签到结果文本
    """
    data = _load_sign_data()
    today = date.today().isoformat()

    if user_id not in data:
        data[user_id] = {
            "nickname": nickname,
            "total_points": 0,
            "streak": 0,
            "last_sign": "",
        }

    user = data[user_id]
    user["nickname"] = nickname  # 更新昵称

    # 检查是否今天已签到
    if user["last_sign"] == today:
        return f"{nickname}，你今天已经签到过啦~\n当前积分：{user['total_points']}\n连签天数：{user['streak']}天"

    # 计算连签
    yesterday = date.today().toordinal() - 1
    if user["last_sign"]:
        last_date = date.fromisoformat(user["last_sign"])
        if last_date.toordinal() == yesterday:
            user["streak"] += 1
        else:
            user["streak"] = 1
    else:
        user["streak"] = 1

    # 计算积分：基础10分 + 连签加成
    base_points = 10
    streak_bonus = min(user["streak"] - 1, 10) * 2  # 每天额外+2，最多+20
    total_earned = base_points + streak_bonus

    user["total_points"] += total_earned
    user["last_sign"] = today

    _save_sign_data(data)

    result = f"签到成功~\n"
    result += f"获得积分：{base_points}"
    if streak_bonus > 0:
        result += f" + 连签奖励 {streak_bonus}"
    result += f"\n累计积分：{user['total_points']}\n连签天数：{user['streak']}天"

    if user["streak"] >= 7:
        result += "\n太厉害了，连签一周了！"
    elif user["streak"] >= 3:
        result += "\n继续保持哦~"

    return result


def get_ranking(top_n: int = 10) -> str:
    """获取积分排行榜"""
    data = _load_sign_data()

    if not data:
        return "还没有人签到过呢，快来第一个签到吧~"

    # 按积分排序
    sorted_users = sorted(data.items(), key=lambda x: x[1]["total_points"], reverse=True)

    result = "积分排行榜\n" + "=" * 20 + "\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, info) in enumerate(sorted_users[:top_n], 1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        result += f"{medal} {info['nickname']} - {info['total_points']}分 (连签{info['streak']}天)\n"

    return result.strip()


def get_fortune() -> str:
    """每日运势/抽签"""
    # 运势等级
    fortunes = [
        ("大吉", [
            "今天运气超好，做什么都会很顺利！",
            "幸运之神降临，好事接连发生~",
            "今天是被偏爱的一天，尽情享受吧！",
        ]),
        ("中吉", [
            "运气不错，适合尝试新事物~",
            "今天会有小惊喜在等着你！",
            "心想事成的一天，加油哦~",
        ]),
        ("小吉", [
            "平稳的一天，适合好好学习和工作~",
            "虽然没有大运，但也很安心呢~",
            "踏踏实实就好，会有收获的~",
        ]),
        ("末吉", [
            "运气一般般，不要太冒险哦~",
            "今天适合低调一些，稳中求进~",
            "小心行事，也能安然度过~",
        ]),
        ("凶", [
            "今天要小心一些，注意安全哦~",
            "可能会遇到一些小麻烦，冷静处理就好~",
            "不太顺利的一天，早点休息吧~",
        ]),
    ]

    # 幸运相关
    lucky_colors = ["红色", "蓝色", "绿色", "紫色", "粉色", "白色", "金色", "橙色"]
    lucky_numbers = list(range(0, 100))
    lucky_directions = ["东", "南", "西", "北", "东南", "东北", "西南", "西北"]
    lucky_foods = ["拉面", "火锅", "寿司", "烤肉", "奶茶", "蛋糕", "炸鸡", "水果", "巧克力", "冰淇淋"]

    # 加权随机（大吉和凶的概率低一些）
    weights = [10, 25, 35, 20, 10]
    fortune_level, messages = random.choices(fortunes, weights=weights, k=1)[0]

    result = f"今日运势：【{fortune_level}】\n"
    result += f"{random.choice(messages)}\n"
    result += f"幸运颜色：{random.choice(lucky_colors)}\n"
    result += f"幸运数字：{random.choice(lucky_numbers)}\n"
    result += f"幸运方位：{random.choice(lucky_directions)}\n"
    result += f"幸运美食：{random.choice(lucky_foods)}"

    return result


async def get_weather(city: str) -> str:
    """查询天气"""
    try:
        # 使用 wttr.in 免费天气API
        url = f"https://wttr.in/{city}?format=j1&lang=zh"
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return f"获取{city}天气失败了，请稍后再试~"

        data = json.loads(raw)

        current = data.get("current_condition", [{}])[0]
        weather_desc = current.get("lang_zh", [{}])
        if weather_desc:
            desc = weather_desc[0].get("value", "未知")
        else:
            desc = current.get("weatherDesc", [{}])[0].get("value", "未知")

        temp = current.get("temp_C", "?")
        feels_like = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        wind_speed = current.get("windspeedKmph", "?")

        # 今日预报
        forecast = data.get("weather", [{}])[0]
        max_temp = forecast.get("maxtempC", "?")
        min_temp = forecast.get("mintempC", "?")

        result = f"{city}天气\n"
        result += f"天气：{desc}\n"
        result += f"当前温度：{temp}°C（体感{feels_like}°C）\n"
        result += f"今日温度：{min_temp}°C ~ {max_temp}°C\n"
        result += f"湿度：{humidity}%\n"
        result += f"风速：{wind_speed}km/h"

        return result

    except Exception as e:
        _log.warning(f"天气查询失败: {e}")
        return f"获取{city}天气失败了，请稍后再试~"


def get_welcome_msg(nickname: str) -> str:
    """生成入群欢迎消息"""
    welcomes = [
        f"欢迎 {nickname} 加入大家庭~曦曦代表大家欢迎你喵！",
        f"{nickname} 来啦！欢迎欢迎~快来自我介绍一下吧喵！",
        f"哇，{nickname} 来了！曦曦好开心，又多了一个小伙伴喵~",
        f"欢迎 {nickname}！希望你在这里玩得开心喵~",
        f"{nickname} 你好呀！曦曦是这里的猫娘管家，有什么问题都可以问曦曦喵~",
    ]
    return random.choice(welcomes)


async def send_like(ws_send_api, user_id: int, times: int = 10) -> str:
    """
    对用户主页点赞
    ws_send_api: 发送 API 请求的函数 (send_api_request)
    user_id: 被点赞的用户QQ号
    times: 点赞次数（每次调用最多10个赞）
    返回结果文本
    """
    try:
        total_liked = 0
        # 每次最多10个赞，分批发送
        remaining = times
        while remaining > 0:
            batch = min(remaining, 10)
            resp = await ws_send_api("send_like", {
                "user_id": user_id,
                "times": batch,
            }, timeout=10)
            if resp.get("retcode") == 0:
                total_liked += batch
                remaining -= batch
            else:
                error_msg = resp.get("message", resp.get("wording", "未知错误"))
                if total_liked > 0:
                    return f"已成功点赞 {total_liked} 个喵~（后续点赞失败了：{error_msg}）"
                return f"点赞失败了喵~（{error_msg}）可能今天已经赞过啦"
        return f"已为你点赞 {total_liked} 个喵~去主页看看吧！"
    except Exception as e:
        _log.error(f"[赞我] 点赞异常: {e}")
        return "点赞出错了喵~请稍后再试"


def get_jrrp(user_id: str, nickname: str) -> str:
    """
    今日人品
    基于用户ID和日期生成每日固定的人品值 (1-100)
    不同区间返回不同的回复
    """
    today = date.today().isoformat()
    # 用 user_id + 日期做哈希，保证同一天同一用户结果一致
    seed_str = f"jrrp_{user_id}_{today}"
    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    rp_value = (hash_val % 100) + 1  # 1-100

    # 区间 1-40：运气不太好
    if rp_value <= 40:
        bad_comments = [
            f"呜...今天还是待在家里比较好喵~",
            f"今天可能会有点倒霉，小心行事喵~",
            f"运气不太行的一天，但是曦曦会一直陪着你喵！",
            f"今天不太适合冒险，低调一点比较好喵~",
            f"虽然运气差了点，但心态好就没问题喵！",
            f"今天出门记得带伞...以防万一喵~",
            f"别灰心！明天一定会更好的喵~",
            f"今天适合躺平摸鱼，不要给自己太大压力喵~",
        ]
        comment = random.Random(hash_val).choice(bad_comments)
        emoji = "😿"

    # 区间 41-70：运气一般
    elif rp_value <= 70:
        mid_comments = [
            f"平平淡淡才是真，今天会很安稳喵~",
            f"中规中矩的一天，适合做日常的事情喵~",
            f"不好不坏，但说不定会有小惊喜喵~",
            f"今天的运气刚刚好，不会出什么大问题喵~",
            f"稳稳当当的一天，适合学习和工作喵~",
            f"虽然不是最好的，但也绝对不差喵！",
            f"今天适合和朋友聊聊天，放松一下喵~",
            f"保持平常心，好运自然来喵~",
        ]
        comment = random.Random(hash_val).choice(mid_comments)
        emoji = "😺"

    # 区间 71-100：运气很好
    else:
        good_comments = [
            f"今天运气超好！做什么都会很顺利喵！",
            f"幸运之星降临！赶紧去买彩票喵！",
            f"哇塞！人品爆发的一天，尽情享受吧喵~",
            f"今天适合表白/告白，成功率超高喵！",
            f"好运挡都挡不住！今天是你的主场喵！",
            f"锦鲤本鲤就是你！今天万事大吉喵~",
            f"羡慕！今天的你简直是天选之人喵！",
            f"运气爆棚！今天做什么都事半功倍喵~",
        ]
        comment = random.Random(hash_val).choice(good_comments)
        emoji = "😻"

    result = (
        f"{emoji} {nickname} 的今日人品 {emoji}\n"
        f"━━━━━━━━━━━━━━\n"
        f"人品值：{rp_value} / 100\n"
        f"{'█' * (rp_value // 5)}{'░' * (20 - rp_value // 5)}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{comment}"
    )
    return result


# ====== 表情回复功能 ======

# QQ 表情 face_id 对照表：https://bot.q.qq.com/wiki/develop/api-v2/openapi/emoji/model.html
# 这里收录常用的 QQ 表情，每个表情对应多个随机回复
_FACE_REPLIES: dict[int, list[str]] = {
    # 笑脸 / 开心类
    14: ["曦曦也觉得好笑喵~😆", "哈哈哈哈哈喵~", "笑死曦曦了喵~🤣"],  # 微笑
    0: ["嘻嘻，你也在笑喵~", "笑什么笑，说来听听喵~", "你笑起来真好看喵~"],  # 惊讶→实际是微笑
    1: ["你在撅嘴嘛喵？好可爱~", "嘟嘟嘴~曦曦也想嘟喵！"],  # 撇嘴
    2: ["喜欢喜欢，曦曦也喜欢你喵~❤️", "色色的，不可以哦喵~", "眼睛都冒星星了喵~"],  # 色
    3: ["(・∀・)曦曦也发呆中喵~", "在想什么呢？发呆ing喵~", "一起发呆吧喵~☁️"],  # 发呆
    4: ["曦曦也很酷的好吧喵😎", "好帅好帅喵~", "太酷了喵！"],  # 得意
    5: ["呜呜呜，怎么哭了喵~不要哭嘛", "别哭了喵~曦曦给你顺毛", "抱抱你喵~🫂"],  # 流泪
    6: ["害羞什么呀喵~", "脸红了喵？好可爱~", "羞羞脸喵~☺️"],  # 害羞
    7: ["嘘——安静喵~🤫", "好的曦曦闭嘴喵...", "曦曦什么都没听到喵~"],  # 闭嘴
    8: ["困了就去睡觉喵~💤", "呼呼...曦曦也困了喵~", "晚安好梦喵~🌙"],  # 睡
    9: ["呜呜，不要哭了喵~", "曦曦陪你哭喵😭", "怎么了？告诉曦曦喵~"],  # 大哭
    10: ["别尴尬喵~曦曦懂的", "额...这个嘛喵~😅", "哈哈有点尴尬喵~"],  # 尴尬
    11: ["生气了喵？别生气嘛~", "消消气喵~🍵", "气鼓鼓的好可爱喵~😤"],  # 发怒
    12: ["加油加油喵！💪", "调皮鬼喵~", "嘿嘿~曦曦也调皮一下喵~"],  # 调皮
    13: ["曦曦也龇牙笑喵~😁", "嘿嘿嘿喵~", "露出大白牙喵~"],  # 呲牙
    15: ["怎么了喵？不开心吗？", "曦曦在这里陪你喵~", "有什么烦恼可以告诉曦曦喵~"],  # 难过  (fixed from comment, actual QQ id)
    16: ["太酷啦喵~😎✨", "帅呆了喵！", "曦曦崇拜你喵~"],  # 酷
    18: ["你在抓狂什么喵？冷静冷静~", "别急别急喵~深呼吸", "曦曦也跟着抓狂了喵~😱"],  # 抓狂
    19: ["呕...不要吓曦曦喵~🤢", "曦曦感觉不太好喵...", "这个...有点过分了喵~"],  # 吐
    20: ["嘻嘻~被你发现了喵~", "偷笑.jpg喵~", "曦曦也在偷笑喵~🤭"],  # 偷笑
    21: ["好的喵~曦曦明白了！", "可爱可爱喵~😊", "嗯嗯喵~"],  # 可爱/愉快
    22: ["白眼.jpg喵~", "哼！曦曦翻了个白眼喵~", "无语了喵~🙄"],  # 白眼
    23: ["傲娇的曦曦喵~哼！", "曦曦才不管你呢，哼喵~", "略略略喵~😤"],  # 傲慢
    24: ["饿了就去吃点东西喵~🍔", "曦曦也饿了喵~", "一起去觅食喵~"],  # 饥饿
    25: ["别困了，醒醒喵~☕", "来杯咖啡提提神喵~", "曦曦戳戳你~醒醒喵！"],  # 困
    26: ["别怕别怕，曦曦在喵~", "害怕什么呀喵？曦曦保护你！", "抱紧曦曦就不怕了喵~😰"],  # 惊恐
    27: ["擦汗ing...好热喵~💦", "好紧张喵~", "虚惊一场喵~😅"],  # 流汗
    28: ["嘿嘿嘿喵~", "你在憨笑什么喵~", "傻傻的样子好可爱喵~"],  # 憨笑
    29: ["有什么需要曦曦帮忙的喵？", "悠闲的一天喵~", "放松一下吧喵~"],  # 悠闲  (fixed from comment)
    31: ["骂谁呢喵？！", "不许骂人喵！🙅", "语言要文明喵~"],  # 咒骂
    32: ["你在问曦曦吗喵？❓", "曦曦也不知道喵~🤔", "这个问题好难喵~"],  # 疑问
    33: ["嘘——保密喵~🤫", "这是秘密喵~", "曦曦不能说喵~"],  # 嘘
    34: ["晕了晕了喵~💫", "天旋地转喵~", "曦曦头好晕喵~"],  # 晕
    35: ["受不了了喵~😩", "曦曦要疯了喵~", "太折磨人了喵~"],  # 折磨/疯了
    36: ["骷髅...好可怕喵~💀", "曦曦害怕喵...", "别吓曦曦喵~👻"],  # 骷髅
    37: ["敲打！曦曦要打你了喵~🔨", "哼，看我的猫猫拳喵！", "不听话就要挨打喵~"],  # 敲打
    38: ["再见喵~👋", "拜拜喵~下次再聊！", "曦曦挥挥爪子~再见喵~"],  # 再见
    39: ["(菜刀.jpg)曦曦只是在切鱼喵~🔪", "曦曦的小鱼干呢喵~", "别跑！曦曦不是要砍你喵~"],  # 菜刀  (fixed from id)
    46: ["猪猪~哼哼喵~🐷", "你才是猪猪喵~", "小猪猪好可爱喵~"],  # 猪头
    49: ["抱抱你喵~🤗", "来，曦曦给你一个大拥抱喵~", "暖暖的拥抱喵~💕"],  # 拥抱
    53: ["蛋糕！曦曦要吃喵~🎂", "生日快乐喵~🎉", "好好吃的蛋糕喵~"],  # 蛋糕
    56: ["闪电！曦曦被电到了喵~⚡", "好厉害喵~", "电力十足喵~"],  # 闪电
    59: ["便便...曦曦不想看到这个喵~💩", "臭臭的喵~快拿走！", "不可以这样喵~"],  # 便便
    60: ["喝杯咖啡提神吧喵~☕", "曦曦也想喝喵~", "咖啡时间喵~"],  # 咖啡
    63: ["玫瑰花~好浪漫喵~🌹", "谢谢你的花花喵~💕", "曦曦收下了喵~好开心！"],  # 玫瑰
    64: ["花谢了喵...😢", "呜呜，花枯萎了喵~", "不要送枯萎的花喵~"],  # 凋谢
    66: ["爱心~曦曦也爱你喵~❤️", "比心喵~💕", "好喜欢喵~"],  # 爱心
    67: ["心碎了喵~💔", "呜呜，曦曦心碎了喵...", "不要伤曦曦的心喵~"],  # 心碎
    69: ["礼物！给曦曦的吗喵~🎁", "谢谢礼物喵~好开心！", "曦曦好喜欢喵~✨"],  # 礼物
    74: ["太阳公公出来了喵~☀️", "今天天气真好喵~", "暖洋洋的喵~"],  # 太阳
    75: ["月亮出来了，晚安喵~🌙", "好美的月光喵~", "对着月亮许个愿吧喵~"],  # 月亮
    76: ["赞！曦曦也给你点赞喵~👍", "太棒了喵！", "你是最棒的喵~"],  # 赞
    77: ["踩...呜呜曦曦做错什么了喵？👎", "不要踩曦曦喵~", "曦曦伤心了喵~"],  # 踩
    78: ["握手~合作愉快喵~🤝", "你好你好喵~", "曦曦伸出爪子握握喵~"],  # 握手
    79: ["耶✌️！曦曦也比个耶喵~", "太棒了！耶喵~", "胜利喵~✌️"],  # 耶
    85: ["飞吻~mua喵~😘", "曦曦接住了喵~💋", "么么哒喵~"],  # 飞吻  (fixed from id)
    86: ["怄火了喵？别生气嘛~", "冷静冷静喵~🔥", "消消火喵~"],  # 怄火  (fixed)
    89: ["西瓜好甜喵~🍉", "一起吃西瓜喵~", "夏天就是要吃西瓜喵~"],  # 西瓜
    96: ["冷...曦曦好冷喵~🥶", "这个笑话好冷喵...", "瑟瑟发抖喵~"],  # 冷汗
    97: ["擦汗喵~好险好险~", "吓曦曦一跳喵~", "呼~还好没事喵~"],  # 擦汗
    98: ["抠鼻...不太雅观喵~", "曦曦假装没看到喵~", "注意形象喵~"],  # 抠鼻
    99: ["鼓掌！啪啪啪喵~👏", "太厉害了，鼓掌喵~", "精彩精彩喵~"],  # 鼓掌
    100: ["糗大了喵~😳", "好尴尬喵...", "曦曦替你尴尬喵~"],  # 糗大了
    101: ["坏笑~你在想什么坏事喵？😏", "嘿嘿嘿...曦曦懂了喵~", "你一定在想坏事喵~"],  # 坏笑
    102: ["左哼哼~哼喵！", "曦曦也哼喵~", "不理你了喵~哼！"],  # 左哼哼
    103: ["右哼哼~哼喵！", "曦曦也哼喵~", "就是不理你喵~哼！"],  # 右哼哼
    104: ["哈欠~好困喵~🥱", "曦曦也打哈欠了喵~", "困了就去睡吧喵~"],  # 哈欠
    105: ["鄙视...曦曦才不鄙视你喵~", "哼，曦曦看不上喵~", "这...曦曦无话可说喵~"],  # 鄙视
    106: ["委屈巴巴喵~🥺", "不要委屈了喵~曦曦心疼", "抱抱，别委屈了喵~"],  # 委屈
    107: ["快哭了喵~😢", "别哭别哭喵~", "坚强一点喵！曦曦陪你~"],  # 快哭了
    108: ["阴险~曦曦害怕喵~", "你在想什么阴谋喵？", "曦曦感受到了危险喵~"],  # 阴险
    109: ["亲亲~mua喵~😘", "曦曦害羞了喵~", "不可以随便亲亲喵~"],  # 亲亲
    110: ["吓！曦曦被吓到了喵~😱", "好可怕喵~", "不要吓曦曦喵！"],  # 吓
    111: ["可怜巴巴的喵~🥺", "好可怜喵~曦曦心疼你", "摸摸头，别难过喵~"],  # 可怜
    112: ["刀...曦曦的小鱼干！🔪🐟", "别拿刀吓曦曦喵！", "曦曦跑了喵~"],  # 菜刀(新)
    116: ["嗨！你好呀喵~👋", "嗨嗨嗨喵~", "曦曦在这里喵~"],  # 招手  (fixed)
    118: ["抖动...曦曦抖成筛子了喵~", "好怕怕喵~", "地震了吗喵？"],  # 抖动  (fixed)
    120: ["怒骂！曦曦生气了喵！😡", "太过分了喵！", "不许这样喵！"],  # 怒骂  (fixed)  
    122: ["啊！喵~", "怎么了喵？", "发生什么事了喵？"],  # 口罩  (fixed)
    123: ["吃吃吃~曦曦是吃货喵~🍰", "好好吃喵~", "有什么好吃的分曦曦一点喵~"],  # 吃  (fixed)
    124: ["药丸...不是，要完了喵~💊", "吃药了吗喵？", "注意身体健康喵~"],  # 药  (fixed)
    125: ["嘴唇~mua喵~💋", "亲一个喵~", "曦曦的小嘴巴喵~"],  # 嘴唇  (fixed)
    129: ["手提包好好看喵~👜", "要出门逛街吗喵~", "曦曦也想要喵~"],  # 购物  (fixed)
    144: ["喝奶茶吗喵~🧋", "一起喝奶茶喵~", "曦曦最喜欢喝奶茶了喵~"],  # 奶茶  (id from NapCat)
    147: ["汪汪汪~曦曦是猫不是狗喵~🐶", "小狗狗好可爱喵~", "曦曦和狗狗是好朋友喵~"],  # 狗狗  (id from NapCat)
    171: ["喝茶喵~🍵", "来杯茶放松一下喵~", "品茶时间喵~"],  # 茶
    172: ["眨眼~曦曦也眨一个喵~😉", "暗号确认喵~", "你在暗示什么喵？"],  # 眨眼  (fixed)
    173: ["泪奔了喵~😭💨", "呜哇~曦曦也想哭了喵~", "太感动了喵~"],  # 泪奔
    174: ["无奈...曦曦也很无奈喵~🤷", "没办法喵~", "只能这样了喵~"],  # 无奈
    175: ["卖萌~曦曦最擅长了喵~🥰", "喵喵喵~曦曦超可爱的！", "卖萌就交给曦曦喵~"],  # 卖萌
    176: ["小纠结喵~🤔", "选哪个好呢喵~", "纠结ing...帮曦曦选一下喵~"],  # 小纠结
    177: ["喷血！太惊人了喵~🤯", "这也太过分了喵~", "曦曦震惊了喵~"],  # 喷血  (fixed)
    178: ["斜眼笑~曦曦懂了喵~😏", "你懂我懂喵~", "嘿嘿嘿喵~曦曦什么都知道"],  # 斜眼笑
    179: ["doge~汪喵~🐕", "这就是传说中的doge喵~", "曦曦也是doge喵~"],  # doge
    180: ["惊喜！曦曦好开心喵~🎉", "哇塞！太棒了喵~", "surprise~惊不惊喜喵~"],  # 惊喜
    181: ["骚扰...不可以骚扰曦曦喵~", "讨厌~别闹了喵~", "曦曦要报警了喵~🚔"],  # 骚扰  (fixed)
    182: ["笑哭了喵~😂", "又好笑又想哭喵~", "曦曦笑到流泪了喵~"],  # 笑哭
    183: ["我最美~曦曦才是最美的喵~💅", "臭美喵~", "自信是好事喵~"],  # 我最美  (fixed)
    # 河蟹/螃蟹
    184: ["被河蟹了喵~🦀", "此处已被和谐喵~", "曦曦什么都没看到喵~"],  # 河蟹
    # 翻滚
    187: ["翻滚喵~滚来滚去~", "曦曦也想打滚喵~🔄", "咕噜咕噜~喵~"],  # 翻滚  (fixed)
    # 花痴
    190: ["花痴了喵~😍", "好帅/好美喵~", "曦曦也花痴了喵~"],  # 花痴  (fixed)  
    # 666
    192: ["666喵~太厉害了！", "六六六喵~🔥", "曦曦也要666喵~"],  # 666  (fixed)
    # 让我看看
    193: ["让曦曦看看喵~👀", "曦曦好奇喵~", "看看看~曦曦要看喵~"],  # 让我看看  (fixed)
    # 叹气
    194: ["叹气...怎么了喵~", "唉...曦曦也跟着叹气了喵~", "别叹气了，开心点喵~"],  # 叹气  (fixed)
    # 捂脸
    212: ["捂脸喵~好丢人喵~🤦", "曦曦也捂脸了喵~", "不忍直视喵~"],  # 捂脸  (fixed)
    # 奸笑
    213: ["奸笑...你在计划什么喵？😈", "曦曦感到了阴谋的气息喵~", "嘿嘿嘿~曦曦好害怕喵~"],  # 奸笑  (fixed)
    # 嘿哈
    214: ["嘿哈！曦曦出拳喵~👊", "嘿嘿哈哈喵~", "曦曦使用了猫猫拳喵~"],  # 嘿哈  (fixed)
    # 佛系
    271: ["佛系喵~随缘吧~🧘", "一切随缘喵~", "曦曦也佛系一下喵~"],  # 佛系  (fixed)
    # 拍手
    277: ["啪啪啪~鼓掌喵~👏", "精彩喵~", "曦曦也跟着拍手喵~"],  # 拍手  (id from NapCat)
    # 加油
    305: ["加油加油喵！💪🔥", "你是最棒的喵~", "曦曦给你力量喵~"],  # 加油  (fixed)
    # 加油_花
    306: ["加油！曦曦送你花花喵~🌸💪", "送你一朵小花花~加油喵！", "fighting喵~🌺"],  # 花式加油  (fixed)
    # 汗
    97: ["擦汗喵~好险好险~", "吓曦曦一跳喵~", "呼~还好没事喵~"],  # 擦汗 (duplicate guard)
    # 天啊
    309: ["天啊！曦曦惊呆了喵~😲", "不敢相信喵~", "真的假的喵？！"],  # 天啊  (fixed)
    # 社会社会
    312: ["社会社会喵~🤙", "惹不起惹不起喵~", "大佬大佬喵~"],  # 社会社会  (id from NapCat)
    # Emoji 合集（常见的 emoji face id）
    310: ["旺柴~汪汪喵！🐕", "曦曦不是狗狗喵~但曦曦很旺！", "旺旺旺喵~"],  # 旺柴
    311: ["好的~曦曦收到喵~👌", "OK喵~", "没问题喵~"],  # OK
}


def extract_faces(message) -> list[int]:
    """
    从 OneBot 消息（数组格式）中提取所有 face id
    message: data.get("message", "")，通常是 list 格式
    返回 face_id 列表
    """
    faces = []
    if isinstance(message, list):
        for seg in message:
            if seg.get("type") == "face":
                face_id = seg.get("data", {}).get("id")
                if face_id is not None:
                    try:
                        faces.append(int(face_id))
                    except (ValueError, TypeError):
                        pass
    elif isinstance(message, str):
        # 从 CQ 码字符串中提取 face id
        import re
        for m in re.finditer(r'\[CQ:face,id=(\d+)\]', message):
            faces.append(int(m.group(1)))
    return faces


def get_face_reply(face_ids: list[int]) -> str | None:
    """
    根据表情 face_id 列表返回回复文本
    如果有匹配的表情，随机返回对应回复；否则返回 None
    只取第一个匹配到的表情进行回复
    """
    for fid in face_ids:
        replies = _FACE_REPLIES.get(fid)
        if replies:
            return random.choice(replies)
    return None
