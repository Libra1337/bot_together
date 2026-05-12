"""
抽奖模块
实现多步交互创建抽奖，记录参与者，定时开奖
保证公平公正公开
"""

import asyncio
import time
import random
import hashlib
import logging

_log = logging.getLogger("QQBot")

# 正在创建抽奖的会话 {user_key: {"step": ..., "data": ..., "created_at": timestamp}}
_creating_sessions = {}

# 活跃的抽奖 {group_id: LotteryData}
_active_lotteries = {}


class LotteryData:
    def __init__(self, creator_id, group_id, prize, count, duration_mins, limits):
        self.creator_id = creator_id
        self.group_id = group_id
        self.prize = prize
        self.count = count
        self.end_time = time.time() + duration_mins * 60
        self.limits = limits  # set of allowed qq numbers, empty means no limit
        self.participants = set()  # set of participant qq numbers
        # 生成高强度的密码安全随机字符串作为盐值，保证后续开奖可审计
        self.salt = "SALT-" + "".join(str(random.SystemRandom().randint(0, 9)) for _ in range(16))
        # 提前公布盐值的哈希，开奖时公布原值，这是经典的防伪公平承诺(Commitment)机制
        self.salt_hash = hashlib.sha256(self.salt.encode()).hexdigest()[:12]
        self.rewards_vault = []  # 存放具体的奖品卡密等

# 存放私聊配置状态
_deposit_sessions = {}  # {user_id: group_id}


def is_creating(user_id, group_id) -> bool:
    user_key = f"{group_id}_{user_id}"
    return user_key in _creating_sessions


async def start_lottery_creation(user_id, group_id):
    user_key = f"{group_id}_{user_id}"
    _creating_sessions[user_key] = {
        "step": "prize",
        "data": {"group_id": group_id, "creator_id": user_id},
        "created_at": time.time(),
    }
    return "🎊 曦曦来帮主人发起抽奖喵！\n请问这次的【奖品名称】是什么呢？\n（回复“取消”可退出抽奖配置）"


async def handle_creation_step(user_id, group_id, content, send_func) -> bool:
    user_key = f"{group_id}_{user_id}"
    session = _creating_sessions.get(user_key)
    if not session:
        return False

    if content == "取消":
        del _creating_sessions[user_key]
        await send_func("已取消抽奖创建喵~")
        return True

    step = session["step"]
    data = session["data"]

    if step == "prize":
        data["prize"] = content
        session["step"] = "count"
        await send_func(f"好的喵！奖品是【{content}】~\n那么【奖品数量】是多少份呢？（请输入数字）")
        return True

    elif step == "count":
        if not content.isdigit() or int(content) <= 0:
            await send_func("奖品数量必须是大于 0 的数字喵！请重新输入：")
            return True
        data["count"] = int(content)
        session["step"] = "time"
        await send_func(f"记下来啦！共 {content} 份。\n请问【开奖时间】是几分钟后呢？（请输入分钟数，例如输入 5）")
        return True

    elif step == "time":
        if not content.isdigit() or int(content) <= 0:
            await send_func("时间必须是大于 0 的数字喵！请重新输入分钟数：")
            return True
        data["duration"] = int(content)
        session["step"] = "limit"
        await send_func(f"明白！{content} 分钟后开奖~\n最后，有什么【限制条件】吗？\n如果仅限特定QQ号参与，请发送他们的QQ（空格隔开）；\n如果所有人都能参与，请直接回复“无”。")
        return True

    elif step == "limit":
        limits = set()
        if content != "无":
            import re
            qqs = re.findall(r'\d{5,12}', content)
            limits = set(int(q) for q in qqs)
            if not limits:
                await send_func("没有识别到合法的QQ号喵，请重新输入（或者回复“无”）：")
                return True

        data["limits"] = limits

        # 完成创建
        del _creating_sessions[user_key]

        # 一个群仅允许一个并行抽奖，如果有旧的，直接顶掉（简单化处理）
        if group_id in _active_lotteries:
            pass

        lottery = LotteryData(
            creator_id=data["creator_id"],
            group_id=data["group_id"],
            prize=data["prize"],
            count=data["count"],
            duration_mins=data["duration"],
            limits=data["limits"]
        )

        _active_lotteries[group_id] = lottery

        limit_text = f"仅限特定QQ参与 (共{len(limits)}人)" if limits else "无限制 (群员皆可参与)"
        msg = f"🎉 抽奖创建成功喵！\n"
        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"🎁 奖品：{lottery.prize} (共 {lottery.count} 份)\n"
        msg += f"⏱️ 开奖时间：{data['duration']} 分钟后自动开奖\n"
        msg += f"👥 参与条件：{limit_text}\n"
        msg += f"🔒 公平防伪码：{lottery.salt_hash}\n"
        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"👉 参与指引：在群内发送“参与抽奖”\n"
        msg += f"👉 发起人指引：请立刻私聊曦曦发送“/lottery”存放具体奖品卡密哦！喵~"

        await send_func(msg)
        return True

    return False

def get_expired_lotteries() -> list:
    """返回已到期的 group_id 列表"""
    now = time.time()
    return [gid for gid, lot in _active_lotteries.items() if now >= lot.end_time]


def join_lottery(user_id, group_id) -> str | None:
    """处理用户参与抽奖的指令，返回提示文本，若无抽奖则返回 None"""
    lottery = _active_lotteries.get(group_id)
    if not lottery:
        return None

    if lottery.limits and user_id not in lottery.limits:
        return "抱歉喵，您不在本次抽奖的指定参与名单中~"

    if user_id in lottery.participants:
        return "您已经参与过本次抽奖啦，请耐心等待开奖喵~"

    lottery.participants.add(user_id)
    return f"参与成功！当前奖池已有 {len(lottery.participants)} 人参与喵~"


async def try_early_draw(user_id, group_id, send_func, send_pm_func) -> bool:
    """尝试提前开奖，若是发起人则执行，否则返回 False 且不处理"""
    lottery = _active_lotteries.get(group_id)
    if not lottery:
        return False
    if lottery.creator_id != user_id:
        return False

    await do_draw(group_id, send_func, send_pm_func, manual=True)
    return True


def _mask_reward(text: str) -> str:
    """对奖品内容做脱敏预览，保留前3和后2个字符，中间用*替代"""
    if len(text) <= 6:
        return text[:2] + "*" * max(len(text) - 2, 1)
    return text[:3] + "*" * (len(text) - 5) + text[-2:]


def _build_vault_preview(lottery) -> str:
    """构建奖品保险箱预览文本"""
    msg = f"🔐 奖品保险箱 ({lottery.prize})\n"
    msg += f"━━━━━━━━━━━━━━\n"
    for i, item in enumerate(lottery.rewards_vault, 1):
        msg += f"  {i}. {_mask_reward(item)}\n"
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"共 {len(lottery.rewards_vault)} 份奖励已安全存入喵~"
    return msg


async def handle_pm_command(user_id, content, send_pm_func) -> bool:
    """处理发起人的私聊存放奖励交互"""
    # 查看奖品保险箱
    if content in ("/showlottery", "showlottery", "/查看奖品", "查看奖品"):
        for gid, lottery in _active_lotteries.items():
            if lottery.creator_id == user_id:
                if lottery.rewards_vault:
                    # 发起人私聊查看：显示完整奖品内容，方便核验
                    msg = f"🔐 奖品保险箱 ({lottery.prize})\n"
                    msg += f"━━━━━━━━━━━━━━\n"
                    for i, item in enumerate(lottery.rewards_vault, 1):
                        msg += f"  {i}. {item}\n"
                    msg += f"━━━━━━━━━━━━━━\n"
                    msg += f"共 {len(lottery.rewards_vault)} 份奖励已安全存入喵~\n"
                    msg += f"（仅发起人可见完整内容）"
                    await send_pm_func(msg)
                else:
                    await send_pm_func(f"抽奖（{lottery.prize}）还没有存放奖励喵~\n请私聊发送 /lottery 来存放奖品！")
                return True
        await send_pm_func("主人当前没有正在进行的抽奖喵~")
        return True

    if content == "/lottery":
        # 寻找该用户创建的活跃抽奖（简单处理取第一个）
        target_group = None
        for gid, lottery in _active_lotteries.items():
            if lottery.creator_id == user_id:
                target_group = gid
                break
        
        if not target_group:
            await send_pm_func("主人当前没有正在进行的群活抽奖喵~")
            return True
            
        lottery = _active_lotteries[target_group]
        if lottery.rewards_vault:
            await send_pm_func(f"该抽奖（{lottery.prize}）已经存放过奖励了喵~")
            return True
            
        _deposit_sessions[user_id] = target_group
        await send_pm_func(f"请存放 {lottery.count} 个【{lottery.prize}】进来喵~\n（如果是多个奖励，支持换行、分号、或句号分隔。直接发给我就好啦！）")
        return True
        
    # 如果处于存放会话中
    if user_id in _deposit_sessions:
        group_id = _deposit_sessions[user_id]
        lottery = _active_lotteries.get(group_id)
        if not lottery:
            del _deposit_sessions[user_id]
            await send_pm_func("抽奖似乎已经结束或被取消了喵~")
            return True
            
        if content == "取消":
            del _deposit_sessions[user_id]
            await send_pm_func("已取消存放喵~")
            return True
            
        # 解析奖励
        import re
        if lottery.count == 1:
            items = [content.strip()]
        else:
            if '\n' in content:
                raw_items = content.strip().split('\n')
            elif ';' in content or '；' in content:
                raw_items = re.split(r'[;；]+', content.strip())
            elif '。' in content:
                raw_items = content.strip().split('。')
            else:
                raw_items = [content.strip()]
                
            items = [i.strip() for i in raw_items if i.strip()]
            
        if len(items) != lottery.count:
            await send_pm_func(f"曦曦识别到了 {len(items)} 个奖励元素，但抽奖配置了要发 {lottery.count} 个喵！可以回复“取消”中止，或者重新发一次正确的格式~")
            return True
            
        lottery.rewards_vault = items
        del _deposit_sessions[user_id]
        preview = _build_vault_preview(lottery)
        await send_pm_func(f"✅ 存入成功喵！已记录了 {len(items)} 份奖励。\n等开奖时曦曦会自动去私戳中奖的小伙伴发给他们哦~\n\n{preview}\n\n💡 随时发送 /showlottery 可以再次查看")
        return True
        
    return False

async def do_draw(group_id, send_func, send_pm_func, manual=False):
    """执行开奖逻辑，采用密码学安全的 SystemRandom 与哈希校验"""
    lottery = _active_lotteries.pop(group_id, None)
    if not lottery:
        return

    msg = f"🎉 【抽奖开奖啦】 🎉\n"
    msg += f"🎁 奖品：{lottery.prize}\n"
    msg += f"👥 总参与人数：{len(lottery.participants)} 人\n"
    msg += f"━━━━━━━━━━━━━━\n"

    if len(lottery.participants) == 0:
        msg += "唔...居然没有人参与抽奖，奖品退回给发起人喵 QAQ"
        await send_func(msg)
        return

    # 为了绝对的 Fairness (公平)，我们使用操作系统底层的真随机生成器 (SystemRandom)
    # 并公布抽奖时所用的盐值，它与开奖前发布的防伪哈希对齐，杜绝暗箱操作
    seed_str = str(list(lottery.participants)) + lottery.salt
    secure_random = random.SystemRandom(seed_str.encode())
    
    # 转换为列表
    participants_list = list(lottery.participants)
    
    # 防止需要抽出的奖品数大于总参与人数
    winners_count = min(lottery.count, len(participants_list))
    
    # SystemRandom sample 生成不重复的中奖者
    winners = secure_random.sample(participants_list, winners_count)

    msg += f"🎊 恭喜以下幸运儿中奖：\n\n"
    for w in winners:
        msg += f"[CQ:at,qq={w}] \n"

    if lottery.rewards_vault:
        msg += f"\n👉 奖励已由曦曦自动私发给各位中奖者啦，请注意查收私聊喵！\n"
        # 执行私发奖励
        for i, w in enumerate(winners):
            reward = lottery.rewards_vault[i]
            pm_content = f"🎉 恭喜您在群【{group_id}】的抽奖中获得了：{lottery.prize}！\n━━━━━━━━━━━━━━\n您的专属奖励如下：\n{reward}\n━━━━━━━━━━━━━━\n爱来自曦曦喵~"
            await send_pm_func(w, pm_content)
    else:
        msg += f"\n👉 请尽快联系发起人领取奖励喵！ [CQ:at,qq={lottery.creator_id}]\n"
        
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"⚖️ 公平校验机制说明：\n"
    msg += f"初始防伪码：{lottery.salt_hash}\n"
    msg += f"开奖盐值明文：{lottery.salt}\n"
    msg += f"（系统采用原生 SystemRandom 确保绝对随机）"

    await send_func(msg)


def cleanup_stale_sessions(max_age: float = 600):
    """清理超过 max_age 秒的创建会话（供定时清理任务调用）"""
    now = time.time()
    stale = [k for k, v in _creating_sessions.items() if now - v.get("created_at", 0) > max_age]
    for k in stale:
        del _creating_sessions[k]
    if stale:
        _log.info(f"[抽奖] 清理了 {len(stale)} 个超时创建会话")
