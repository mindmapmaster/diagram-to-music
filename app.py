#!/usr/bin/env python3
"""图生成歌曲 - Flask 后端（MiniMax 版）
上传思维导图/流程图/笔记图片 → AI 提取内容 → 生成歌词 → MiniMax 生成歌曲
"""

import os
import base64
import time
import requests
from flask import Flask, request, jsonify, render_template

# PythonAnywhere 免费版代理配置
_session = requests.Session()
if "PYTHONANYWHERE_DOMAIN" in os.environ or os.path.exists("/home"):
    _session.proxies = {
        "http": "http://proxy.server:3128",
        "https": "http://proxy.server:3128",
    }

try:
    from config import MINIMAX_API_KEY, MINIMAX_API_URL, MINIMAX_MODEL, ZHIPU_API_KEY, ZHIPU_BASE_URL, ZHIPU_MODEL
except ImportError:
    MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
    MINIMAX_API_URL = "https://api.minimax.io/v1/music_generation"
    MINIMAX_MODEL = "music-2.6"
    ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
    ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    ZHIPU_MODEL = "glm-4v-flash"

# 曲风 Prompt 映射（中文选 → MiniMax 自然语言风格描述）
STYLE_PROMPTS = {
    "pop": "Chinese pop song, emotional, melodic, modern production, clear vocals, heartfelt",
    "ancient": "Chinese ancient style, guzheng and erhu, poetic lyrics, ethereal female vocals, traditional",
    "folk": "Chinese folk, acoustic guitar, storytelling, warm vocals, intimate, countryside",
    "electronic": "EDM, synth, electronic beats, dance, energetic, futuristic, Chinese electronic",
    "rock": "Chinese rock, electric guitar, powerful drums, passionate male vocals, energetic",
    "hiphop": "Chinese hip hop, rap, trap beats, rhythm, urban, cool bass",
    "rnb": "Chinese R&B, soul, smooth, mellow, romantic, jazzy chords, warm vocals",
    "jazz": "Jazz, piano, saxophone, lounge, sophisticated, mellow, late night, Chinese jazz",
    "lofi": "Lo-fi, chill, healing, calm, coffee shop, soft beats, relaxing, ambient",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB


# ============ 智谱 AI：图片识别 + 歌词生成 ============

LYRICS_PROMPT = """根据这张{img_type}的内容创作一首{music_style}歌曲。

先写一句摘要，再写歌名（5-10字），最后写歌词（[Verse][Chorus][Bridge]结构，押韵有节奏）。

严格用三个<sep>分隔输出：
摘要<sep>歌名<sep>歌词

不要输出解释或其他内容。"""

STYLE_PROMPT_EXTRA = "\n\n歌词后输出：<style_prompt>pop, emotional, Chinese vocals</style_prompt>"


def call_zhipu(image_base64: str, img_type: str, music_style_tag: str) -> dict:
    """调用智谱 AI 分析图片并生成歌词"""
    if not ZHIPU_API_KEY:
        raise RuntimeError("未配置智谱 API Key")

    # 获取风格的中文描述
    style_cn = {
        "pop": "流行音乐", "ancient": "中国古风",
        "folk": "民谣", "electronic": "电子舞曲",
        "rock": "摇滚", "hiphop": "嘻哈说唱",
        "rnb": "节奏蓝调 R&B", "jazz": "爵士",
        "lofi": "治愈系 Lo-fi",
    }.get(music_style_tag, "流行音乐")

    music_style_en = STYLE_PROMPTS.get(music_style_tag, STYLE_PROMPTS["pop"])

    prompt = LYRICS_PROMPT.format(img_type=img_type, music_style=style_cn) + STYLE_PROMPT_EXTRA

    payload = {
        "model": ZHIPU_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_base64}},
            ],
        }],
        "max_tokens": 1024,
        "temperature": 0.8,
    }

    for attempt in range(3):
        try:
            resp = _session.post(
                f"{ZHIPU_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            data = resp.json()
            if "choices" in data:
                break
            if attempt < 2:
                time.sleep(2)
        except Exception:
            if attempt < 2:
                time.sleep(2)
    else:
        err = data.get("error", {}).get("message", str(data)) if "data" in dir() else "网络错误"
        raise RuntimeError(f"智谱 AI 调用失败: {err}")

    content = data["choices"][0]["message"]["content"]

    # 清理 GLM 模型内部标记
    import re
    content = re.sub(r'<\|\w+\|>', '', content)  # 去除 <|observation|>, <|user|> 等

    # 解析：摘要<sep>歌名<sep>歌词...<style_prompt>...</style_prompt>
    parts = content.split("<sep>")

    summary = parts[0].strip() if len(parts) > 0 else ""
    title = parts[1].strip() if len(parts) > 1 else "AI 创作歌曲"

    # 歌词部分：可能是 parts[2] 直到 <style_prompt> 之前
    raw_lyrics = parts[2] if len(parts) > 2 else content

    # 提取 <style_prompt>...</style_prompt>
    ai_style_prompt = music_style_en
    if "<style_prompt>" in raw_lyrics and "</style_prompt>" in raw_lyrics:
        sp_start = raw_lyrics.index("<style_prompt>") + len("<style_prompt>")
        sp_end = raw_lyrics.index("</style_prompt>")
        ai_style_prompt = raw_lyrics[sp_start:sp_end].strip()
        raw_lyrics = raw_lyrics[:raw_lyrics.index("<style_prompt>")].strip() + raw_lyrics[sp_end + len("</style_prompt>"):].strip()

    lyrics = raw_lyrics.strip().strip('"').strip("'")

    return {"summary": summary, "title": title, "lyrics": lyrics, "style_prompt": ai_style_prompt}


# ============ MiniMax 音乐生成（同步） ============

def minimax_generate(lyrics: str, title: str, style_prompt: str) -> dict:
    """调用 MiniMax API 同步生成歌曲"""
    if not MINIMAX_API_KEY:
        raise RuntimeError("未配置 MiniMax API Key")

    body = {
        "model": MINIMAX_MODEL,
        "prompt": style_prompt,
        "lyrics": lyrics,
        "output_format": "url",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }

    resp = requests.post(
        MINIMAX_API_URL,
        headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    data = resp.json()

    if resp.status_code != 200:
        err = data.get("base_resp", {}).get("status_msg", data.get("error", f"HTTP {resp.status_code}"))
        raise RuntimeError(f"MiniMax 生成失败: {err}")

    base = data.get("base_resp", {})
    if base.get("status_code") != 0:
        raise RuntimeError(f"MiniMax 错误: {base.get('status_msg', '未知错误')}")

    audio_data = data.get("data", {}).get("audio", "")
    extra = data.get("extra_info", {})

    return {
        "audio_url": audio_data,  # output_format=url 时直接是 URL
        "duration": extra.get("music_duration", 0) / 1000,  # ms → s
        "sample_rate": extra.get("music_sample_rate", 44100),
        "bitrate": extra.get("bitrate", 256000),
        "size": extra.get("music_size", 0),
        "trace_id": data.get("trace_id", ""),
    }


# ============ Flask 路由 ============

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/song", methods=["POST"])
def create_song():
    """一步完成：图片识别 → 歌词生成 → MiniMax 生成歌曲（同步）"""
    if "image" not in request.files:
        return jsonify({"error": "请上传图片"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "未选择图片"}), 400

    img_type = request.form.get("img_type", "思维导图")
    music_style_tag = request.form.get("music_style", "pop")

    # 读取图片
    img_bytes = file.read()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "png"
    img_data_url = f"data:image/{ext};base64,{img_b64}"

    try:
        # Step 1: AI 识别 + 生成歌词
        ai_result = call_zhipu(img_data_url, img_type, music_style_tag)

        # Step 2: MiniMax 同步生成歌曲
        music_result = minimax_generate(ai_result["lyrics"], ai_result["title"], ai_result["style_prompt"])

        return jsonify({
            "status": "done",
            "title": ai_result["title"],
            "summary": ai_result["summary"],
            "lyrics": ai_result["lyrics"],
            "mp3_url": music_result["audio_url"],
            "duration": music_result["duration"],
            "trace_id": music_result.get("trace_id", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/song/download")
def song_download():
    """代理下载（MiniMax URL 24h 过期，先下载到本地缓存）"""
    mp3_url = request.args.get("url", "")
    if not mp3_url:
        return jsonify({"error": "缺少 url 参数"}), 400

    resp = _session.get(mp3_url, timeout=60)
    return resp.content, 200, {
        "Content-Type": "audio/mpeg",
        "Content-Disposition": "attachment; filename=song.mp3",
    }


@app.route("/api/health")
def health():
    minimax_ok = bool(MINIMAX_API_KEY)
    zhipu_ok = bool(ZHIPU_API_KEY)
    return jsonify({"ok": True, "minimax_configured": minimax_ok, "zhipu_configured": zhipu_ok})


if __name__ == "__main__":
    print("🎵 图生成歌曲服务启动中 (MiniMax)...")
    print(f"   MiniMax: {'已配置' if MINIMAX_API_KEY else '⚠️ 未配置'}")
    print(f"   智谱 AI: {'已配置' if ZHIPU_API_KEY else '⚠️ 未配置'}")
    print(f"   访问: http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001, threaded=True)
