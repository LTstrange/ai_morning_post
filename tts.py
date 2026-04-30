"""调用小米 MiMo-V2.5-TTS API，将文本转为语音音频文件（content-addressable 存储）。"""

import base64
import hashlib
import os
from pathlib import Path

from openai import OpenAI

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"

STYLE_INSTRUCTION = "温暖、自然的早间新闻播报风格，语速适中，吐字清晰。"

AUDIO_DIR = Path(__file__).parent / "audio"


def _hash_path(audio_bytes):
    """根据音频内容的 SHA-256 计算存储路径：audio/{hash[:2]}/{hash[2:]}.mp3"""
    h = hashlib.sha256(audio_bytes).hexdigest()
    return AUDIO_DIR / h[:2] / f"{h[2:]}.mp3"


def text_to_speech(text, voice=DEFAULT_VOICE, style_instruction=None, max_retries=3):
    """
    将文本转为语音，以 content-addressable 方式存储为 MP3 文件。

    参数:
        text: 待合成的文本（播报稿）
        voice: 语音ID（默认"冰糖"）
        style_instruction: 风格指令（可选，默认使用早间播报风格）
        max_retries: 最大重试次数（默认3次）

    返回:
        成功返回音频文件的 Path，失败返回 None
    """
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        print("  [错误] 未设置 MIMO_API_KEY 环境变量")
        return None

    client = OpenAI(api_key=api_key, base_url=MIMO_BASE_URL)

    if style_instruction is None:
        style_instruction = STYLE_INSTRUCTION

    messages = [
        {"role": "user", "content": style_instruction},
        {"role": "assistant", "content": text},
    ]

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MIMO_MODEL,
                messages=messages,
                audio={"format": "mp3", "voice": voice},
            )

            audio = response.choices[0].message.audio
            if audio is None:
                print(f"  [重试] 第 {attempt + 1}/{max_retries} 次失败，音频数据为空")
                continue

            audio_data = audio.data
            if not audio_data:
                print(
                    f"  [重试] 第 {attempt + 1}/{max_retries} 次失败，音频数据为空字符串"
                )
                continue

            audio_bytes = base64.b64decode(audio_data)
            if len(audio_bytes) == 0:
                print(f"  [重试] 第 {attempt + 1}/{max_retries} 次失败，解码后数据为空")
                continue

            output_path = _hash_path(audio_bytes)

            if output_path.exists():
                print(f"  [跳过] 相同内容的音频已存在: {output_path}")
                return output_path

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            print(f"  [完成] 已写入 {len(audio_bytes):,} 字节到 {output_path}")
            return output_path

        except Exception as e:
            print(f"  [重试] 第 {attempt + 1}/{max_retries} 次异常: {e}")
            continue

    print(f"  [失败] {max_retries} 次尝试均失败")
    return None
