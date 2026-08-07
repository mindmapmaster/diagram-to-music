#!/usr/bin/env python3
"""图生成歌曲 - Flask 后端（MiniMax 版）
上传思维导图/流程图/笔记图片 → AI 提取内容 → 生成歌词 → MiniMax 生成歌曲
"""

import os
import base64
import json
import time
import uuid
import requests
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file, abort
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# PythonAnywhere 免费版代理配置（仅 PythonAnywhere 环境启用）
_session = requests.Session()
if "PYTHONANYWHERE_DOMAIN" in os.environ:
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

RESULTS_DIR = Path(__file__).parent / "results"
CASES_DIR = Path(__file__).parent / "static" / "cases"


def _ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)


def _compress_image(img_bytes: bytes, max_size: int = 1024) -> tuple:
    """压缩图片：缩放到 max_size 以内，转为 JPEG quality=85。
    返回 (compressed_bytes, ext, data_url)。
    如果 Pillow 不可用，回退到原始 bytes。
    """
    if not HAS_PIL:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return img_bytes, "png", f"data:image/png;base64,{b64}"

    try:
        img = Image.open(BytesIO(img_bytes))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()

        b64 = base64.b64encode(compressed).decode("utf-8")
        return compressed, "jpg", f"data:image/jpeg;base64,{b64}"
    except Exception:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return img_bytes, "png", f"data:image/png;base64,{b64}"


def _generate_song_id():
    return datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]


def _save_result(image_bytes: bytes, ext: str, lyrics: str, title: str, style: str, style_name: str, audio_bytes: bytes) -> str:
    song_id = _generate_song_id()
    result_dir = RESULTS_DIR / song_id
    result_dir.mkdir(parents=True, exist_ok=False)

    image_path = result_dir / f"image.{ext}"
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    audio_path = result_dir / "audio.mp3"
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    lyrics_path = result_dir / "lyrics.txt"
    with open(lyrics_path, "w", encoding="utf-8") as f:
        f.write(lyrics)

    meta = {
        "id": song_id,
        "title": title,
        "style": style,
        "style_name": style_name,
        "created_at": datetime.now().isoformat(),
    }
    with open(result_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return song_id


def _load_result(song_id: str):
    result_dir = RESULTS_DIR / song_id
    if not result_dir.exists():
        return None

    meta_path = result_dir / "meta.json"
    lyrics_path = result_dir / "lyrics.txt"
    audio_path = result_dir / "audio.mp3"
    if not meta_path.exists() or not lyrics_path.exists() or not audio_path.exists():
        return None

    image_files = list(result_dir.glob("image.*"))
    image_ext = image_files[0].suffix.lstrip(".") if image_files else "png"

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(lyrics_path, "r", encoding="utf-8") as f:
        lyrics = f.read()

    return {"meta": meta, "lyrics": lyrics, "image_ext": image_ext}


def _download_audio(url: str) -> bytes:
    resp = _session.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


STYLE_NAME_MAP = {
    "pop": "流行", "ancient": "古风", "folk": "民谣",
    "electronic": "电子", "rock": "摇滚", "hiphop": "嘻哈",
    "rnb": "R&B", "jazz": "爵士", "lofi": "治愈",
}


_ensure_dirs()


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

    for attempt in range(2):
        try:
            resp = _session.post(
                f"{ZHIPU_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            data = resp.json()
            if "choices" in data:
                break
            if attempt < 1:
                time.sleep(2)
        except Exception:
            if attempt < 1:
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

    if len(parts) < 3:
        # 智谱有时不按 <sep> 输出，改用中文标签兜底匹配
        sm = re.search(r'摘要[：:]\s*(.+?)(?:\n|歌名)', content, re.DOTALL)
        tm = re.search(r'歌名[：:]\s*(.+?)(?:\n)', content)
        summary = sm.group(1).strip() if sm else ""
        title = tm.group(1).strip() if tm else (parts[1].strip() if len(parts) > 1 else "AI 创作歌曲")
        # 歌词：从"歌名"行之后到 <style_prompt> 或末尾
        if tm:
            lyrics_start = tm.end()
            raw_lyrics = content[lyrics_start:].strip()
        else:
            raw_lyrics = content
    else:
        summary = parts[0].strip()
        title = parts[1].strip()
        raw_lyrics = parts[2]

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
        timeout=180,
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

@app.route("/api/validate", methods=["POST"])
def validate_image():
    """上传时校验：1.安全检测(色情/暴力/敏感) 2.是否为思维导图/流程图/思维笔记"""
    if "image" not in request.files:
        return jsonify({"error": "请上传图片"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "未选择图片"}), 400

    img_bytes = file.read()
    # 压缩图片，防止大图导致 OOM
    _, _, img_data_url = _compress_image(img_bytes, max_size=512)

    if not ZHIPU_API_KEY:
        return jsonify({"safe": True, "is_diagram": True})

    payload = {
        "model": ZHIPU_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请判断这张图片，严格按如下格式回答（不要其他内容）：\nSAFE:YES或NO（图片是否包含色情、暴力、血腥、政治敏感等违规内容，有违规内容则NO，无则YES）\nDIAGRAM:YES或NO（图片是否属于思维导图、流程图、思维笔记、组织结构图、UML图、白板整理、手绘笔记、结构化笔记等可视化内容，是则YES；纯风景照、自拍、美食、宠物、表情包、商品图等明显无关图片则NO）"},
                {"type": "image_url", "image_url": {"url": img_data_url}},
            ],
        }],
        "max_tokens": 20,
        "temperature": 0,
    }

    try:
        resp = _session.post(
            f"{ZHIPU_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        data = resp.json()
        if "choices" in data:
            answer = data["choices"][0]["message"]["content"].strip().upper()
            safe = "SAFE:YES" in answer or "SAFE: YES" in answer
            is_diagram = "DIAGRAM:YES" in answer or "DIAGRAM: YES" in answer
            return jsonify({"safe": safe, "is_diagram": is_diagram})
    except Exception:
        pass

    return jsonify({"safe": True, "is_diagram": True})


@app.route("/test")
def test_page():
    return render_template("test.html")


@app.route("/api/cases")
def get_cases():
    """返回精选案例配置"""
    cases_file = CASES_DIR / "cases.json"
    if cases_file.exists():
        with open(cases_file, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"cases": []})


@app.route("/result/<song_id>")
def result_page(song_id):
    """结果展示页（可分享）"""
    result = _load_result(song_id)
    if not result:
        return render_template("result.html", not_found=True), 404
    return render_template(
        "result.html",
        not_found=False,
        song_id=song_id,
        title=result["meta"]["title"],
        style=result["meta"]["style"],
        style_name=result["meta"]["style_name"],
        lyrics=result["lyrics"],
        created_at=result["meta"]["created_at"],
    )


@app.route("/api/image/<song_id>")
def get_result_image(song_id):
    """获取结果图片"""
    result_dir = RESULTS_DIR / song_id
    if not result_dir.exists():
        return jsonify({"error": "not found"}), 404
    image_files = list(result_dir.glob("image.*"))
    if not image_files:
        return jsonify({"error": "image not found"}), 404
    ext = image_files[0].suffix.lstrip(".")
    mimetype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
    return send_file(image_files[0], mimetype=mimetype)


@app.route("/api/audio/<song_id>")
def get_result_audio(song_id):
    """获取结果音频（在线播放）"""
    audio_path = RESULTS_DIR / song_id / "audio.mp3"
    if not audio_path.exists():
        return jsonify({"error": "audio not found"}), 404
    return send_file(audio_path, mimetype="audio/mpeg")


@app.route("/download/<song_id>")
def download_result(song_id):
    """下载结果音频"""
    result = _load_result(song_id)
    if not result:
        return jsonify({"error": "not found"}), 404
    audio_path = RESULTS_DIR / song_id / "audio.mp3"
    title = result["meta"]["title"]
    filename = f"{title}.mp3".replace("\\", "_").replace("/", "_").replace("..", "_")
    return send_file(
        audio_path,
        mimetype="audio/mpeg",
        as_attachment=True,
        download_name=filename,
    )

@app.after_request
def add_no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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

    # 读取图片并压缩，防止大图导致 OOM
    img_bytes = file.read()
    compressed_bytes, ext, img_data_url = _compress_image(img_bytes, max_size=1024)

    try:
        # Step 1: AI 识别 + 生成歌词
        ai_result = call_zhipu(img_data_url, img_type, music_style_tag)

        # Step 2: MiniMax 同步生成歌曲
        music_result = minimax_generate(ai_result["lyrics"], ai_result["title"], ai_result["style_prompt"])

        # Step 3: 下载音频并保存到本地（MiniMax URL 24h 过期）
        audio_bytes = _download_audio(music_result["audio_url"])
        style_name = STYLE_NAME_MAP.get(music_style_tag, music_style_tag)
        song_id = _save_result(compressed_bytes, ext, ai_result["lyrics"], ai_result["title"], music_style_tag, style_name, audio_bytes)

        return jsonify({
            "status": "done",
            "song_id": song_id,
            "redirect_url": f"/result/{song_id}",
            "title": ai_result["title"],
            "summary": ai_result["summary"],
            "lyrics": ai_result["lyrics"],
            "mp3_url": f"/api/audio/{song_id}",
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
    filename = request.args.get("filename", "song.mp3")
    # 安全处理文件名，防止路径遍历
    filename = filename.replace("\\", "_").replace("/", "_").replace("..", "_")
    if not filename.endswith(".mp3"):
        filename += ".mp3"
    return resp.content, 200, {
        "Content-Type": "audio/mpeg",
        "Content-Disposition": f"attachment; filename={filename}",
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
