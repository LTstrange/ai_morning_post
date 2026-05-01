"""邮件发送模块：将早报通过 SMTP 发送给用户。"""

import os
import smtplib
from email.mime.audio import MIMEAudio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown


def _get_smtp_config():
    """从环境变量读取 SMTP 配置。"""
    host = os.getenv("SMTP_HOST", "smtp.qq.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM", "") or user
    return host, port, user, password, from_addr


def markdown_to_html(md_text):
    """将 Markdown 文本转为带基本样式的 HTML 邮件正文。"""
    body_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return (
        "<!DOCTYPE html>"
        '<html><head><meta charset="utf-8">'
        "<style>"
        "body{font-family:-apple-system,Arial,sans-serif;line-height:1.6;color:#333;max-width:800px;margin:0 auto;padding:20px}"
        "h1{color:#1a1a1a;border-bottom:2px solid #e0e0e0;padding-bottom:8px}"
        "h2{color:#2c3e50;margin-top:24px}"
        "h3{color:#34495e}"
        "a{color:#3498db;text-decoration:none}"
        "a:hover{text-decoration:underline}"
        "ul{padding-left:20px}"
        "li{margin-bottom:4px}"
        "blockquote{border-left:4px solid #ddd;margin:0;padding:0 16px;color:#666}"
        "</style></head><body>"
        f"{body_html}"
        '<hr style="margin-top:40px;border:none;border-top:1px solid #e0e0e0">'
        '<p style="color:#555;font-size:14px;line-height:1.8">'
        "如果你想调整订阅的期刊或研究兴趣，直接回复这封邮件告诉我就好，我会帮你处理。"
        "</p>"
        '<p style="color:#999;font-size:12px;line-height:1.8">'
        "本邮件由 AI 自动生成，内容仅供参考。"
        "不想继续接收的话，回复「取消订阅」即可。"
        "</p>"
        "</body></html>"
    )


def send_report_email(to_addr, subject, report_md, tts_path=None):
    """发送早报邮件。

    - to_addr: 收件人邮箱
    - subject: 邮件标题
    - report_md: Markdown 早报正文
    - tts_path: 可选的 TTS 音频路径（附件）
    """
    host, port, user, password, from_addr = _get_smtp_config()

    if not user or not password:
        print("  [邮件] SMTP_USER 或 SMTP_PASSWORD 未配置，跳过邮件发送")
        return False

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    html_body = markdown_to_html(report_md)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if tts_path:
        audio_file = Path(tts_path)
        if audio_file.exists():
            with open(audio_file, "rb") as f:
                audio_part = MIMEAudio(f.read(), _subtype="mpeg")
            audio_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=f"ai-morning-post-{subject[-10:]}.mp3",
            )
            msg.attach(audio_part)

    try:
        with smtplib.SMTP_SSL(host, port) as server:
            server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"  [邮件] 发送失败: {e}")
        return False
