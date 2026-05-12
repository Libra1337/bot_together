"""
空调系统 - 群聊互动玩法
每个群一台空调，可升温降温，温度超高会爆炸
全球排行榜统计炸了多少台
"""

import os
import json
import random
import time
import logging
from PIL import Image, ImageDraw, ImageFont

_log = logging.getLogger("QQBot")

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AC_DATA_FILE = os.path.join(_BOT_DIR, "data", "ac_data.json")
AC_IMG_DIR = os.path.join(_BOT_DIR, "data", "ac_images")
ASSETS_DIR = os.path.join(_BOT_DIR, "assets", "ac")

os.makedirs(AC_IMG_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# 素材文件名约定（放到 assets/ac/ 下）
# ac_normal.png   - 正常空调底图
# ac_burned.png   - 烧焦空调图
# ac_boom.gif     - 爆炸动图
# 如果没有素材则纯 Pillow 生成

# ====== 空调品牌 ======
AC_BRANDS = [
    "格力",
    "美的",
    "海尔",
    "大金",
    "三菱电机",
    "松下",
    "奥克斯",
    "志高",
    "海信",
    "TCL",
    "长虹",
    "科龙",
    "日立",
    "富士通",
    "约克",
    "特灵",
    "开利",
    "曦曦牌",
    "Miracle 定制版",
    "喵喵牌",
]

# ====== 温度相关常数 ======
DEFAULT_TEMP = 24
MIN_TEMP = -50
MAX_TEMP = 100  # 超过这个概率爆炸
BOOM_THRESHOLD = 60  # 60°C 以上开始有爆炸概率
FREEZE_THRESHOLD = -30  # -30°C 以下开始有冻裂概率

# 温度评价
TEMP_COMMENTS = {
    (-999, -30): [
        "空调冻裂了喵...冰晶都飘出来了",
        "南极都没这么冷吧！",
        "企鹅看了都摇头",
    ],
    (-30, -10): ["冷到发抖喵~", "穿上你最厚的棉袄吧", "呼出的气都结冰了"],
    (-10, 0): ["好冷喵~要多穿点", "零下了哦，注意保暖"],
    (0, 16): ["有点凉凉的喵~", "秋天的感觉"],
    (16, 26): ["舒适的温度喵~", "完美！不冷不热", "空调の最佳状态"],
    (26, 35): ["有点热了喵~", "夏天的感觉", "要不要来根冰棍"],
    (35, 45): ["好热啊喵！", "快要中暑了！", "这温度能煎鸡蛋了"],
    (45, 60): ["危险温度！小心空调过热！", "空调在冒烟了喵...", "闻到焦味了吗"],
    (60, 80): ["空调快炸了！赶紧降温！", "警告！警告！过热警报！", "空调已经红了..."],
    (80, 100): [
        "空调在剧烈颤抖！随时可能爆炸！",
        "最后的警告！！！",
        "听到滋滋声了吗...",
    ],
    (100, 999): ["你做到了不可能的事...", "空调已超越物理极限"],
}

# 爆炸台词
BOOM_LINES = [
    "轰！！！空调炸了！！！碎片满天飞喵~",
    "砰！！！空调原地爆炸！蘑菇云升起！",
    "BOOM！空调承受不住了！化为一团火球！",
    "咔嚓~砰！！空调裂开了然后爆炸了喵！",
    "警报！警报！空调核心熔毁！轰隆隆！！！",
    "空调：「我尽力了...」然后它炸了。",
    "恭喜你成功把空调送上了天喵~",
]

FREEZE_BOOM_LINES = [
    "咔嚓！空调冻裂了！冰渣子到处飞！",
    "冻到极限了！空调结冰后碎成渣了喵~",
    "空调变成了一个大冰块...然后裂开了！",
]


# ====== 数据管理 ======
def _load_data() -> dict:
    try:
        if os.path.exists(AC_DATA_FILE):
            with open(AC_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"groups": {}, "boom_rank": {}}


def _save_data(data: dict):
    try:
        os.makedirs(os.path.dirname(AC_DATA_FILE), exist_ok=True)
        with open(AC_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning(f"[空调] 保存数据失败: {e}")


_data = _load_data()


def _get_group(group_id: int | str) -> dict:
    gid = str(group_id)
    if gid not in _data["groups"]:
        _data["groups"][gid] = {
            "temp": DEFAULT_TEMP,
            "brand": random.choice(AC_BRANDS),
            "on": False,
            "boomed": False,
            "boom_count": 0,
        }
        _save_data(_data)
    return _data["groups"][gid]


def _get_boom_rank() -> dict:
    return _data.get("boom_rank", {})


def _add_boom(group_id: int | str):
    gid = str(group_id)
    if "boom_rank" not in _data:
        _data["boom_rank"] = {}
    _data["boom_rank"][gid] = _data["boom_rank"].get(gid, 0) + 1
    g = _get_group(group_id)
    g["boom_count"] = g.get("boom_count", 0) + 1


def _get_temp_comment(temp: int) -> str:
    for (lo, hi), comments in TEMP_COMMENTS.items():
        if lo <= temp < hi:
            return random.choice(comments)
    return "无法形容的温度..."


def _calc_boom_chance(temp: int) -> float:
    """计算爆炸概率：60°C以上线性增长，100°C=100%"""
    if temp < BOOM_THRESHOLD:
        return 0.0
    if temp >= MAX_TEMP:
        return 1.0
    return (temp - BOOM_THRESHOLD) / (MAX_TEMP - BOOM_THRESHOLD)


def _calc_freeze_chance(temp: int) -> float:
    """计算冻裂概率：-30°C以下线性增长，-50°C=100%"""
    if temp > FREEZE_THRESHOLD:
        return 0.0
    if temp <= MIN_TEMP:
        return 1.0
    return (FREEZE_THRESHOLD - temp) / (FREEZE_THRESHOLD - MIN_TEMP)


# ====== 图片生成 ======
def _get_font(size: int):
    """尝试加载中文字体"""
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",  # 黑体
        "C:/Windows/Fonts/simsun.ttc",  # 宋体
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _temp_color(temp: int) -> tuple:
    """根据温度返回颜色 (R,G,B)"""
    if temp <= -20:
        return (100, 150, 255)  # 冰蓝
    if temp <= 0:
        return (130, 200, 255)  # 浅蓝
    if temp <= 20:
        return (50, 180, 80)  # 绿色
    if temp <= 30:
        return (50, 50, 50)  # 黑色
    if temp <= 45:
        return (255, 165, 0)  # 橙色
    if temp <= 60:
        return (255, 80, 0)  # 深橙
    return (255, 0, 0)  # 红色


def generate_ac_image(temp: int, brand: str, boomed: bool = False) -> str:
    """
    生成空调状态图片，返回文件路径
    """
    w, h = 400, 300

    # 尝试加载素材
    normal_path = os.path.join(ASSETS_DIR, "ac_normal.png")
    burned_path = os.path.join(ASSETS_DIR, "ac_burned.png")

    if boomed and os.path.exists(burned_path):
        img = Image.open(burned_path).convert("RGBA")
        img = img.resize((w, h), Image.LANCZOS)
    elif os.path.exists(normal_path):
        img = Image.open(normal_path).convert("RGBA")
        img = img.resize((w, h), Image.LANCZOS)
    else:
        # 纯生成
        img = Image.new("RGBA", (w, h), (240, 240, 245, 255))
        draw = ImageDraw.Draw(img)

        if boomed:
            # 烧焦背景
            draw.rectangle(
                [20, 60, 380, 200], fill=(60, 40, 30), outline=(40, 20, 10), width=3
            )
            draw.rectangle([30, 70, 370, 190], fill=(80, 50, 35))
            # 烟雾效果
            for _ in range(8):
                cx = random.randint(50, 350)
                cy = random.randint(20, 80)
                r = random.randint(15, 40)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(100, 100, 100, 80))
        else:
            # 正常空调
            body_color = (
                (230, 230, 235)
                if temp <= 60
                else (200, 160, 130)
                if temp <= 80
                else (180, 100, 80)
            )
            draw.rectangle(
                [20, 60, 380, 200], fill=body_color, outline=(180, 180, 185), width=3
            )
            draw.rectangle([30, 70, 370, 190], fill=(245, 245, 248))
            # 出风口
            for y in range(175, 195, 5):
                draw.line([(40, y), (360, y)], fill=(200, 200, 205), width=1)
            # 管子
            draw.line(
                [(370, 180), (395, 220), (390, 260)], fill=(160, 160, 170), width=6
            )

    draw = ImageDraw.Draw(img)

    # 画温度数字
    temp_str = f"{temp}°C"
    font_temp = _get_font(60 if abs(temp) < 100 else 50)
    color = _temp_color(temp)

    bbox = draw.textbbox((0, 0), temp_str, font=font_temp)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = 85

    if not boomed:
        # 描边效果
        for dx in [-2, 0, 2]:
            for dy in [-2, 0, 2]:
                if dx or dy:
                    draw.text(
                        (tx + dx, ty + dy),
                        temp_str,
                        fill=(255, 255, 255),
                        font=font_temp,
                    )
        draw.text((tx, ty), temp_str, fill=color, font=font_temp)
    else:
        # 烧焦的 X
        font_x = _get_font(80)
        draw.text((w // 2 - 30, 80), "X", fill=(200, 50, 30), font=font_x)

    # 品牌名
    font_brand = _get_font(16)
    draw.text((25, 210), f"品牌：{brand}", fill=(120, 120, 120), font=font_brand)

    # 状态
    if boomed:
        font_status = _get_font(22)
        draw.text((w // 2 - 60, 240), "已报废", fill=(200, 50, 30), font=font_status)
    elif temp >= 60:
        font_status = _get_font(18)
        draw.text((w // 2 - 50, 240), "过热警告!", fill=(255, 80, 0), font=font_status)
    elif temp <= -20:
        font_status = _get_font(18)
        draw.text(
            (w // 2 - 50, 240), "低温警告!", fill=(100, 150, 255), font=font_status
        )

    # 保存
    filename = f"ac_{int(time.time() * 1000)}.png"
    filepath = os.path.join(AC_IMG_DIR, filename)
    img.save(filepath, "PNG")
    return filepath


# ====== 指令处理 ======
def cmd_turn_on(group_id) -> tuple[str, str | None]:
    """
    开空调
    返回 (文字, 图片路径|None)
    """
    g = _get_group(group_id)
    if g.get("on") and not g.get("boomed"):
        return (
            f"空调已经开着了喵~ 当前温度 {g['temp']}°C\n品牌：{g['brand']}",
            generate_ac_image(g["temp"], g["brand"]),
        )

    if g.get("boomed"):
        g["boomed"] = False
        g["temp"] = DEFAULT_TEMP
        g["brand"] = random.choice(AC_BRANDS)

    g["on"] = True
    g["temp"] = DEFAULT_TEMP
    _save_data(_data)

    img = generate_ac_image(g["temp"], g["brand"])
    return (
        f"空调已开启喵~ 嗡嗡嗡~\n品牌：{g['brand']}\n当前温度：{g['temp']}°C\n{_get_temp_comment(g['temp'])}",
        img,
    )


def cmd_turn_off(group_id) -> tuple[str, str | None]:
    """关空调"""
    g = _get_group(group_id)
    if not g.get("on"):
        return ("空调没有开喵~ 先发「开空调」开启吧", None)
    g["on"] = False
    _save_data(_data)
    return ("空调已关闭喵~ 安静了~", None)


def cmd_raise_temp(group_id, amount: int = 5) -> tuple[str, str | None]:
    """
    升温
    返回 (文字, 图片路径|None)
    """
    g = _get_group(group_id)
    if not g.get("on") or g.get("boomed"):
        return ("空调没开或者已经炸了喵~ 先「开空调」吧", None)

    old = g["temp"]
    g["temp"] = min(g["temp"] + amount, 200)
    _save_data(_data)

    # 检查爆炸
    chance = _calc_boom_chance(g["temp"])
    if chance > 0 and random.random() < chance:
        # 爆炸！
        boom_line = random.choice(BOOM_LINES)
        g["boomed"] = True
        g["on"] = False
        _add_boom(group_id)
        _save_data(_data)

        img = generate_ac_image(g["temp"], g["brand"], boomed=True)
        rank = _get_group_rank(group_id)
        return (
            f"{boom_line}\n\n温度：{old}°C → {g['temp']}°C 时爆炸！\n"
            f"本群已炸 {g.get('boom_count', 1)} 台空调，全球排名第 {rank}！\n"
            f"发「换空调」获取新空调喵~",
            img,
        )

    comment = _get_temp_comment(g["temp"])
    warning = ""
    if chance > 0:
        pct = int(chance * 100)
        warning = f"\n爆炸概率：{pct}%"

    img = generate_ac_image(g["temp"], g["brand"])
    return (f"温度：{old}°C → {g['temp']}°C ↑\n{comment}{warning}", img)


def cmd_lower_temp(group_id, amount: int = 5) -> tuple[str, str | None]:
    """降温"""
    g = _get_group(group_id)
    if not g.get("on") or g.get("boomed"):
        return ("空调没开或者已经炸了喵~ 先「开空调」吧", None)

    old = g["temp"]
    g["temp"] = max(g["temp"] - amount, -100)
    _save_data(_data)

    # 检查冻裂
    chance = _calc_freeze_chance(g["temp"])
    if chance > 0 and random.random() < chance:
        boom_line = random.choice(FREEZE_BOOM_LINES)
        g["boomed"] = True
        g["on"] = False
        _add_boom(group_id)
        _save_data(_data)

        img = generate_ac_image(g["temp"], g["brand"], boomed=True)
        rank = _get_group_rank(group_id)
        return (
            f"{boom_line}\n\n温度：{old}°C → {g['temp']}°C 时冻裂！\n"
            f"本群已炸 {g.get('boom_count', 1)} 台空调，全球排名第 {rank}！\n"
            f"发「换空调」获取新空调喵~",
            img,
        )

    comment = _get_temp_comment(g["temp"])
    warning = ""
    if chance > 0:
        pct = int(chance * 100)
        warning = f"\n冻裂概率：{pct}%"

    img = generate_ac_image(g["temp"], g["brand"])
    return (f"温度：{old}°C → {g['temp']}°C ↓\n{comment}{warning}", img)


def cmd_change_ac(group_id) -> tuple[str, str | None]:
    """换空调"""
    g = _get_group(group_id)
    old_brand = g.get("brand", "未知")
    g["temp"] = DEFAULT_TEMP
    g["brand"] = random.choice(AC_BRANDS)
    g["on"] = True
    g["boomed"] = False
    _save_data(_data)

    img = generate_ac_image(g["temp"], g["brand"])
    return (
        f"旧空调（{old_brand}）已丢掉喵~\n"
        f"新空调到货！品牌：{g['brand']}\n"
        f"当前温度：{g['temp']}°C\n"
        f"好好珍惜这台新空调喵~",
        img,
    )


def cmd_ac_status(group_id) -> tuple[str, str | None]:
    """查看空调状态"""
    g = _get_group(group_id)
    if g.get("boomed"):
        img = generate_ac_image(g["temp"], g["brand"], boomed=True)
        return (
            f"空调已报废喵...\n品牌：{g['brand']}\n"
            f"炸毁时温度：{g['temp']}°C\n"
            f"本群累计炸毁 {g.get('boom_count', 0)} 台\n"
            f"发「换空调」获取新空调",
            img,
        )
    if not g.get("on"):
        return ("空调当前是关着的喵~ 发「开空调」开启", None)

    img = generate_ac_image(g["temp"], g["brand"])
    return (
        f"空调状态\n品牌：{g['brand']}\n"
        f"温度：{g['temp']}°C\n"
        f"{_get_temp_comment(g['temp'])}\n"
        f"本群累计炸毁 {g.get('boom_count', 0)} 台",
        img,
    )


def _get_group_rank(group_id) -> int:
    """获取群在全球爆炸排行榜的名次"""
    rank_data = _get_boom_rank()
    gid = str(group_id)
    my_count = rank_data.get(gid, 0)
    rank = 1
    for _, count in rank_data.items():
        if count > my_count:
            rank += 1
    return rank


def cmd_boom_rank() -> str:
    """全球炸炸排行榜"""
    rank_data = _get_boom_rank()
    if not rank_data:
        return "还没有群炸过空调喵~ 大家都很爱惜空调呢"

    sorted_groups = sorted(rank_data.items(), key=lambda x: x[1], reverse=True)[:20]
    lines = ["全球空调炸炸排行榜", "━━━━━━━━━━━━━━"]
    for i, (gid, count) in enumerate(sorted_groups, 1):
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        lines.append(f"{medal} 群{gid[-6:]} | 炸了 {count} 台")
    lines.append("━━━━━━━━━━━━━━")
    total = sum(rank_data.values())
    lines.append(f"全球共炸毁 {total} 台空调喵~")
    return "\n".join(lines)
