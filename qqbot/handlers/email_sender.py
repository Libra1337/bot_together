"""
邮件发送模块
"""

import logging
import smtplib
import html
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

_log = logging.getLogger("QQBot")


def _html_escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def _format_value_html(key: str, value: str) -> str:
    escaped_value = _html_escape(value)
    key_lower = key.lower()
    if key_lower in {"token", "sauth"} or len(value) > 80:
        return f"""<div style="max-width:100%;box-sizing:border-box;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;color:#111827;font-size:12px;line-height:1.65;font-family:Consolas,'Courier New',monospace;white-space:pre-wrap;word-break:break-all;overflow-wrap:anywhere;">{escaped_value}</div>"""
    return f'<span style="word-break:break-all;overflow-wrap:anywhere;">{escaped_value}</span>'


def _build_html(subject: str, body: str) -> str:
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    subject_html = _html_escape(subject)

    greeting = ""
    kv_rows = []
    extra_lines = []

    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("━"):
            continue
        if "：" in line:
            k, v = line.split("：", 1)
            kv_rows.append((k.strip(), v.strip()))
        elif "Ciallo" in line or "主人" in line or "来了喵" in line or "来啦" in line:
            greeting = line
        elif "爱来自" in line or "欢迎进入" in line:
            extra_lines.append(line)
        else:
            extra_lines.append(line)

    table_rows = ""
    for k, v in kv_rows:
        key_html = _html_escape(k)
        value_html = _format_value_html(k, v)
        table_rows += f"""<tr>
<td style="padding:10px 0;color:#6b7280;font-size:14px;vertical-align:top;width:90px;">{key_html}</td>
<td style="padding:10px 0;color:#111827;font-size:14px;font-family:Consolas,'Courier New',monospace;word-break:break-all;overflow-wrap:anywhere;">{value_html}</td>
</tr>"""

    extra_html = ""
    for line in extra_lines:
        extra_html += (
            f'<p style="margin:4px 0;color:#6b7280;font-size:13px;">{_html_escape(line)}</p>'
        )

    greeting_html = ""
    if greeting:
        greeting_html = (
            f'<p style="color:#374151;font-size:15px;margin:0 0 16px 0;">{_html_escape(greeting)}</p>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;">

<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;width:560px;max-width:100%;table-layout:fixed;">

<tr><td style="background:#4f46e5;padding:20px 32px;">
<span style="font-size:20px;font-weight:700;color:#ffffff;letter-spacing:0.5px;">Miracle</span>
</td></tr>

<tr><td style="padding:24px 32px 0;">
<div style="color:#6b7280;font-size:13px;">{now}</div>
</td></tr>

<tr><td style="padding:12px 32px 0;">
<h1 style="margin:0;font-size:24px;font-weight:700;color:#111827;">{subject_html}</h1>
</td></tr>

<tr><td style="padding:16px 32px 0;">
{greeting_html}
</td></tr>

<tr><td style="padding:8px 32px 0;">
<h3 style="margin:0 0 8px 0;font-size:14px;font-weight:600;color:#111827;">详情</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb;table-layout:fixed;">
{table_rows}
</table>
</td></tr>

<tr><td style="padding:16px 32px 0;">
{extra_html}
</td></tr>

<tr><td style="padding:24px 32px 0;">
<div style="border-top:1px solid #e5e7eb;"></div>
</td></tr>

<tr><td style="padding:16px 32px 24px;">
<p style="margin:0;color:#9ca3af;font-size:11px;">
Miracle Bot Auto-Send<br>
此邮件由系统自动发送，请勿直接回复
</p>
</td></tr>

</table>
</td></tr>
</table>

</body></html>"""


async def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    use_tls: bool = False,
    from_name: str = "Miracle Team",
) -> tuple[bool, str]:
    """
    使用配置的 SMTP 账号发送邮件。
    """
    sender_user = (smtp_user or "").strip()
    envelope_from = (from_addr or sender_user).strip()

    if not smtp_host or not sender_user or not smtp_pass or not envelope_from:
        _log.error("[邮件] SMTP 配置不完整，无法发送")
        return False, "SMTP 配置不完整"

    for attempt in range(3):
        server = None
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((from_name, envelope_from))
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(_build_html(subject, body), "html", "utf-8"))

            if use_tls:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                server.ehlo()
                try:
                    server.starttls()
                    server.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass

            server.login(sender_user, smtp_pass)
            server.sendmail(envelope_from, [to_addr], msg.as_string())
            server.quit()
            _log.info(f"[邮件] {envelope_from} -> {to_addr} 成功")
            return True, ""

        except Exception as e:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
            _log.warning(f"[邮件] 第 {attempt + 1}/3 次发送失败: {e}")

    _log.error(f"[邮件] 连续3次失败，放弃发送 -> {to_addr}")
    return False, "邮件发送失败"
