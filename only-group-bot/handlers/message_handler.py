"""
消息处理器模块
负责关键词匹配和自动回复逻辑
"""

from datetime import datetime
from typing import Optional


class MessageHandler:
    """消息处理器：根据配置的规则进行关键词匹配和自动回复"""

    def __init__(self, replies: list, default_reply: str):
        """
        初始化消息处理器

        Args:
            replies: 回复规则列表，每个元素包含 keyword 和 reply
            default_reply: 没有匹配到关键词时的默认回复
        """
        self.replies = replies
        self.default_reply = default_reply

    def get_reply(self, content: str) -> str:
        """
        根据消息内容匹配关键词并返回回复

        Args:
            content: 用户发送的消息内容

        Returns:
            匹配到的回复内容，或默认回复
        """
        # 去除消息前后空白字符
        content = content.strip()

        # 遍历所有回复规则，进行模糊匹配（消息中包含关键词即触发）
        for rule in self.replies:
            keyword = rule.get("keyword", "")
            reply = rule.get("reply", "")

            if keyword and keyword in content:
                # 检查是否是动态回复
                processed = self._process_dynamic_reply(reply)
                if processed is not None:
                    return processed
                return reply

        # 没有匹配到任何关键词，返回默认回复
        return self.default_reply

    def _process_dynamic_reply(self, reply: str) -> Optional[str]:
        """
        处理动态回复标记

        支持的动态标记：
        - auto:time  获取当前时间

        Args:
            reply: 回复内容

        Returns:
            处理后的动态内容，如果不是动态标记则返回 None
        """
        if not reply.startswith("auto:"):
            return None

        action = reply[5:].strip()  # 去掉 "auto:" 前缀

        if action == "time":
            now = datetime.now()
            return f"现在的时间是：{now.strftime('%Y年%m月%d日 %H:%M:%S')}"

        # 未识别的动态标记，返回原内容
        return reply

    def add_rule(self, keyword: str, reply: str):
        """
        动态添加回复规则

        Args:
            keyword: 关键词
            reply: 回复内容
        """
        self.replies.append({"keyword": keyword, "reply": reply})

    def remove_rule(self, keyword: str) -> bool:
        """
        删除指定关键词的回复规则

        Args:
            keyword: 要删除的关键词

        Returns:
            是否成功删除
        """
        for i, rule in enumerate(self.replies):
            if rule.get("keyword") == keyword:
                self.replies.pop(i)
                return True
        return False
