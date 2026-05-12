const BUILTIN_PLUGINS = [
  {
    id: "builtin.ai_chat",
    name: "AI 对话",
    description: "默认 AI 聊天、清除记忆和网页总结能力。",
    commands: ["清除记忆", "重置记忆", "清空记忆", "重置对话", "清空对话", "@我"],
  },
  {
    id: "builtin.bilibili",
    name: "B站解析",
    description: "自动解析 Bilibili 链接。",
    commands: ["b23.tv", "bilibili.com"],
  },
  {
    id: "builtin.bjd",
    name: "布吉岛查询",
    description: "查询布吉岛版本。",
    commands: ["bjd", "/bjd", "布吉岛"],
  },
  {
    id: "builtin.douyin",
    name: "抖音解析",
    description: "自动解析抖音链接。",
    commands: ["douyin.com", "v.douyin.com"],
  },
  {
    id: "builtin.fun",
    name: "日常娱乐",
    description: "签到、排行榜、运势、今日人品、天气等日常功能。",
    commands: ["签到", "打卡", "排行榜", "运势", "今日人品", "天气"],
  },
  {
    id: "builtin.github",
    name: "GitHub 搜索",
    description: "搜索 GitHub 仓库。",
    commands: ["搜索GitHub"],
  },
  {
    id: "builtin.hypban",
    name: "Hypixel 封禁",
    description: "查询 Hypixel 封禁统计。",
    commands: ["hypban", "/hypban"],
  },
  {
    id: "builtin.music",
    name: "点歌",
    description: "搜索歌曲并返回播放链接。",
    commands: ["点歌", "听歌", "来首歌"],
  },
  {
    id: "builtin.nfa",
    name: "NFA",
    description: "获取 NFA Token 并发送到绑定邮箱。",
    commands: ["nfa", "/nfa"],
  },
  {
    id: "builtin.sauth",
    name: "4399 Sauth",
    description: "获取 4399 Sauth 资源。",
    commands: ["4399", "/4399"],
  },
  {
    id: "builtin.stock",
    name: "库存/邮箱",
    description: "163 小号、库存查看、邮箱绑定与解绑。",
    commands: ["163", "/163", "stock", "/stock", "/bind", "/unbind"],
  },
  {
    id: "builtin.web_crawler",
    name: "网页抓取",
    description: "链接检测、网页正文抓取和 AI 分析。",
    commands: ["http://", "https://"],
  },
  {
    id: "builtin.admin",
    name: "Bot 管理指令",
    description: "QQ 内管理验证、封禁、Staff、广告管理等命令。",
    commands: ["/auth", "/admin", "/ban", "/unban", "/addstaff", "/ad"],
  },
];

module.exports = { BUILTIN_PLUGINS };

