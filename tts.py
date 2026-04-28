"""调用小米 MiMo-V2.5-TTS API，将文本转为语音音频文件。"""

import base64
import os
from pathlib import Path

from openai import OpenAI

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"

STYLE_INSTRUCTION = "温暖、自然的早间新闻播报风格，语速适中，吐字清晰。"


def text_to_speech(text, output_path, voice=DEFAULT_VOICE, style_instruction=None):
    """
    将文本转为语音并保存为WAV文件。

    参数:
        text: 待合成的文本（播报稿）
        output_path: 输出WAV文件路径
        voice: 语音ID（默认"冰糖"）
        style_instruction: 风格指令（可选，默认使用早间播报风格）
    """
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        raise ValueError("未设置 MIMO_API_KEY 环境变量")

    client = OpenAI(api_key=api_key, base_url=MIMO_BASE_URL)

    if style_instruction is None:
        style_instruction = STYLE_INSTRUCTION

    messages = [
        {"role": "user", "content": style_instruction},
        {"role": "assistant", "content": text},
    ]

    response = client.chat.completions.create(
        model=MIMO_MODEL,
        messages=messages,
        audio={"format": "wav", "voice": voice},
    )

    audio_bytes = base64.b64decode(response.choices[0].message.audio.data)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
