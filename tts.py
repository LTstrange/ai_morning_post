"""调用小米 MiMo-V2.5-TTS API，将文本转为语音音频文件。"""

import base64
import os
from pathlib import Path

from openai import OpenAI

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"

STYLE_INSTRUCTION = "温暖、自然的早间新闻播报风格，语速适中，吐字清晰。"


def text_to_speech(
    text, output_path, voice=DEFAULT_VOICE, style_instruction=None, max_retries=3
):
    """
    将文本转为语音并保存为WAV文件。

    参数:
        text: 待合成的文本（播报稿）
        output_path: 输出WAV文件路径
        voice: 语音ID（默认"冰糖"）
        style_instruction: 风格指令（可选，默认使用早间播报风格）
        max_retries: 最大重试次数（默认3次）

    返回:
        True 表示成功，False 表示失败
    """
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        print("  [错误] 未设置 MIMO_API_KEY 环境变量")
        return False

    client = OpenAI(api_key=api_key, base_url=MIMO_BASE_URL)

    if style_instruction is None:
        style_instruction = STYLE_INSTRUCTION

    messages = [
        {"role": "user", "content": style_instruction},
        {"role": "assistant", "content": text},
    ]

    output_path = Path(output_path)

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MIMO_MODEL,
                messages=messages,
                audio={"format": "wav", "voice": voice},
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

            # 成功，写入文件
            if output_path.exists():
                print(f"  [覆盖] {output_path.name} 已存在，将被覆盖")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            print(f"  [完成] 已写入 {len(audio_bytes)} 字节到 {output_path.name}")
            return True

        except Exception as e:
            print(f"  [重试] 第 {attempt + 1}/{max_retries} 次异常: {e}")
            continue

    print(f"  [失败] {max_retries} 次尝试均失败")
    return False


def main():
    """批量生成 reports/ 目录下所有语音播报稿的音频。"""
    from dotenv import load_dotenv

    load_dotenv()

    reports_dir = Path(__file__).parent / "reports"
    voice_files = sorted(reports_dir.glob("*-voice.txt"))

    if not voice_files:
        print("未找到语音播报稿文件")
        return

    print(f"找到 {len(voice_files)} 个语音播报稿\n")

    success_count = 0
    fail_count = 0

    for voice_file in voice_files:
        audio_file = voice_file.with_suffix(".wav")
        print(f"正在生成: {audio_file.name}")
        text = voice_file.read_text(encoding="utf-8")
        if text_to_speech(text, audio_file):
            success_count += 1
        else:
            fail_count += 1

    print(f"\n完成: {success_count} 成功, {fail_count} 失败")


if __name__ == "__main__":
    main()
