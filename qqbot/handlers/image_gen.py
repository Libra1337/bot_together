"""
AI 图片生成模块
基于 OpenAI 兼容接口的 images/generations 端点
支持多 Key 轮换重试
"""

import json
import asyncio
import logging
import re

_log = logging.getLogger("QQBot")

# 检测用户是否在请求生成图片
IMAGE_KEYWORDS = [
    r"生成(?:一张|一幅|一个|几张)?(?:.*?)图(?:片)?",
    r"画(?:一张|一幅|一个|几张)?(?:.*?)图(?:片)?",
    r"(?:帮我|给我|来张?|来一张?)画",
    r"(?:帮我|给我|来张?|来一张?)生成.*图",
    r"(?:我)?想要(?:一张|一幅)?.*?(?:图片|的图|壁纸|头像|照片|插画)",
    r"生成.*?(?:壁纸|头像|照片|插画|图片)",
    r"画.*?(?:壁纸|头像|照片|插画|图片)",
]

# 编译正则
_IMAGE_PATTERNS = [re.compile(p) for p in IMAGE_KEYWORDS]


def is_image_request(content: str) -> bool:
    """判断用户消息是否是图片生成请求"""
    for pattern in _IMAGE_PATTERNS:
        if pattern.search(content):
            return True
    return False


def extract_image_prompt(content: str) -> str:
    """从用户消息中提取图片生成的描述 prompt"""
    # 移除常见的触发词前缀，保留核心描述
    cleaned = content
    remove_prefixes = [
        "帮我生成一张", "帮我生成", "帮我画一张", "帮我画一幅", "帮我画",
        "给我生成一张", "给我生成", "给我画一张", "给我画一幅", "给我画",
        "生成一张", "生成一幅", "来张", "来一张", "来一幅",
        "画一张", "画一幅", "画一个",
        "我想要一张", "我想要一幅", "我想要",
        "想要一张", "想要一幅", "想要",
    ]
    for prefix in remove_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # 移除常见后缀
    remove_suffixes = ["的图片", "的图", "图片", "的壁纸", "壁纸", "的照片", "照片", "的插画", "插画"]
    for suffix in remove_suffixes:
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
            break

    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = content  # fallback 用原始内容

    return cleaned


# 单次请求的 curl 超时（图片生成较慢，给足时间）
CURL_TIMEOUT = 90
# 每个 Key 最多重试次数
MAX_RETRIES_PER_KEY = 2
# 重试间隔
RETRY_DELAY = 3


async def _try_generate(url: str, api_key: str, payload_file: str) -> dict:
    """单次 curl 请求，返回解析后的 JSON 或错误 dict"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*",
            "--connect-timeout", "15",
            "--max-time", str(CURL_TIMEOUT),
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", f"@{payload_file}",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return {"_err": "empty_response"}

        # 有时候上游返回 HTML 错误页
        if raw.startswith("<"):
            _log.warning(f"[图片生成] 收到 HTML 响应: {raw[:100]}")
            return {"_err": "html_response", "_raw": raw[:200]}

        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_err": "json_decode", "_raw": raw[:200] if raw else ""}
    except Exception as e:
        return {"_err": "exception", "_detail": str(e)}


async def generate_image(base_url: str, api_key: str, prompt: str,
                         model: str = "grok-imagine-1.0-fast",
                         size: str = "1024x1024",
                         all_keys: list[dict] | None = None) -> tuple[str | None, str]:
    """
    调用 OpenAI 兼容的 /v1/images/generations 端点生成图片
    支持多 Key 轮换：如果传入 all_keys，当一个 Key 失败后会尝试下一个

    返回 (图片URL, 错误原因) — 成功时错误原因为空，失败时图片URL为None
    """
    import tempfile
    import os

    url = f"{base_url.rstrip('/')}/images/generations"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }, ensure_ascii=False)

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    tmp.write(payload)
    tmp.close()

    # 构建要尝试的 Key 列表：当前 key 排第一，其余 key 跟后面
    keys_to_try = [api_key]
    if all_keys:
        for k in all_keys:
            key_val = k["key"] if isinstance(k, dict) else k
            if key_val != api_key and key_val not in keys_to_try:
                keys_to_try.append(key_val)
                if len(keys_to_try) >= 4:  # 最多尝试 4 个不同的 Key
                    break

    last_error = ""
    total_attempts = 0

    try:
        for key_idx, current_key in enumerate(keys_to_try):
            for attempt in range(MAX_RETRIES_PER_KEY):
                total_attempts += 1
                key_tag = f"Key{key_idx+1}" if len(keys_to_try) > 1 else "Key"
                _log.info(f"[图片生成] {key_tag} 第{attempt+1}次尝试 (总第{total_attempts}次)")

                data = await _try_generate(url, current_key, tmp.name)

                # 内部错误
                if "_err" in data:
                    err_type = data["_err"]
                    if err_type == "empty_response":
                        last_error = "服务器无响应（超时）"
                        _log.warning(f"[图片生成] {key_tag} 空响应/超时")
                    elif err_type == "html_response":
                        last_error = "服务器返回了错误页面"
                        _log.warning(f"[图片生成] {key_tag} HTML错误页")
                    else:
                        last_error = data.get("_detail", err_type)
                        _log.warning(f"[图片生成] {key_tag} 错误: {last_error}")

                    if attempt < MAX_RETRIES_PER_KEY - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue

                # API 返回了 error 字段
                if "error" in data:
                    err = data["error"]
                    err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
                    err_code = err.get("code", "") if isinstance(err, dict) else ""
                    _log.warning(f"[图片生成] {key_tag} API错误: code={err_code} msg={err_msg}")

                    # 内容被安全审核拦截 — 不重试，直接返回
                    if "blocked" in err_msg.lower() and "upstream" not in err_code:
                        return None, "图片内容被安全审核拦截了喵，换个描述试试吧~"

                    # upstream_error — 上游服务问题，换 Key 或重试
                    if err_code == "upstream_error":
                        last_error = "上游图片服务暂时不可用"
                        if attempt < MAX_RETRIES_PER_KEY - 1:
                            _log.info(f"[图片生成] 上游错误，{RETRY_DELAY}s 后重试")
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            # 当前 Key 重试用完，换下一个 Key
                            _log.info(f"[图片生成] {key_tag} 重试用完，尝试下一个 Key")
                            break

                    # 其他错误
                    last_error = err_msg or "未知API错误"
                    if attempt < MAX_RETRIES_PER_KEY - 1:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    break

                # 成功：提取图片 URL
                img_data = data.get("data", [])
                if img_data and len(img_data) > 0:
                    image_url = img_data[0].get("url", "")
                    if image_url:
                        _log.info(f"[图片生成] 成功! (第{total_attempts}次尝试)")
                        return image_url, ""

                    # 有些 API 返回 b64_json
                    b64 = img_data[0].get("b64_json", "")
                    if b64:
                        _log.info(f"[图片生成] 成功 (base64, 第{total_attempts}次尝试)")
                        return f"base64://{b64}", ""

                _log.warning(f"[图片生成] 返回数据中无图片: {json.dumps(data, ensure_ascii=False)[:200]}")
                last_error = "返回数据中没有图片"
                if attempt < MAX_RETRIES_PER_KEY - 1:
                    await asyncio.sleep(RETRY_DELAY)

        # 所有 Key 都试完了
        keys_tried = min(len(keys_to_try), 4)
        return None, f"图片生成失败了喵：{last_error}（已尝试 {keys_tried} 个渠道共 {total_attempts} 次）"

    except Exception as e:
        _log.error(f"[图片生成] 异常: {e}")
        return None, "图片生成出错了喵，请稍后再试~"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
