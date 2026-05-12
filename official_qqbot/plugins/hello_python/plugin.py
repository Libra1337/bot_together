async def handle(event, api):
    content = event.get("content", "").strip()
    name = "朋友"
    parts = content.split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        name = parts[1].strip()
    return {"handled": True, "reply": f"你好，{name}。这是 Python 插件回复。"}

