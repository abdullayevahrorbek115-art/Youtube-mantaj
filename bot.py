#!/usr/bin/env python3
"""YouTube avtomatik video bot (o'zbek tilida) - hammasi bitta faylda.

  python bot.py auth --manual        # YouTube ruxsati (bir marta)
  python bot.py make --dry-run       # kalitsiz sinov
  python bot.py make --topic "..." [--upload]
  python bot.py auto                 # mavzu topib, video yasab, yuklaydi, Telegramga xabar beradi
"""
import argparse
import asyncio
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def get(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


_load_env()


class config:
    get = staticmethod(get)
    ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY")
    GEMINI_API_KEY = get("GEMINI_API_KEY")  # bepul: aistudio.google.com/apikey
    GEMINI_MODEL = get("GEMINI_MODEL", "gemini-3.8-flash")
    CLAUDE_MODEL = get("CLAUDE_MODEL", "claude-sonnet-5-5")
    PEXELS_API_KEY = get("PEXELS_API_KEY")
    PIXABAY_API_KEY = get("PIXABAY_API_KEY")  # bo'lsa, Pixabay ishlatiladi

    TTS_VOICE = get("TTS_VOICE", "uz-UZ-SardorNeural")  # yoki uz-UZ-MadinaNeural
    TTS_RATE = get("TTS_RATE", "+0%")

    NICHE = get("NICHE", "qiziqarli faktlar va ilm-fan")
    VIDEO_FORMAT = get("VIDEO_FORMAT", "shorts")  # shorts | long
    PRIVACY = get("PRIVACY", "private")  # private | unlisted | public

    SUB_FONT = get("SUB_FONT", "DejaVu Sans")
    MUSIC_FILE = get("MUSIC_FILE", "")  # ixtiyoriy: fon musiqa (mp3), royalty-free bo'lsin

    OUTPUT_DIR = ROOT / "output"
    HISTORY_FILE = ROOT / "history.json"
    TOPICS_FILE = ROOT / "topics.txt"
    CLIENT_SECRETS = ROOT / "client_secret.json"
    TOKEN_FILE = ROOT / "token.json"

    SIZES = ({"shorts": (1080, 1920), "long": (1920, 1080)} if get("HD") == "1"
             else {"shorts": (720, 1280), "long": (1280, 720)})


# ==================== py ====================
def _creds():
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def send(text):
    """Telegramga xabar yuboradi. Natija matnini qaytaradi (sinov uchun)."""
    token, chat = _creds()
    if not token or not chat:
        print("[telegram o'chiq]", text)
        return "XATO: TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID Render'da kiritilmagan"
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text[:4000]}, timeout=30)
        info = f"Telegram javobi: {r.status_code} {r.text[:300]}"
        if r.status_code != 200:
            print(info)
        return info
    except Exception as e:
        print("Telegramga yuborib bo'lmadi:", e)
        return f"XATO: {type(e).__name__}: {e}"


def send_video(path, caption):
    """Tayyor videoni ham yuboradi (Telegram limiti 50 MB)."""
    token, chat = _creds()
    if not token or not chat:
        return
    try:
        if os.path.getsize(path) > 49 * 1024 * 1024:
            return
        with open(path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                          data={"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"},
                          files={"video": f}, timeout=300)
    except Exception as e:
        print("Videoni yuborib bo'lmadi:", e)

# ==================== py ====================
API = "https://api.anthropic.com/v1/messages"


_GEMINI_CACHE = {}


def _gemini_models():
    """Tanlangan modeldan boshlab, hisobda mavjud 'flash' modellar ro'yxati (nomlar o'zgarib turadi)."""
    if "m" in _GEMINI_CACHE:
        return _GEMINI_CACHE["m"]
    found = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         headers={"x-goog-api-key": config.GEMINI_API_KEY},
                         params={"pageSize": 200}, timeout=30)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                name = m["name"].split("/")[-1]
                if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in name
                        and not any(x in name for x in ("image", "tts", "live", "audio", "embed", "native", "robotics"))):
                    found.append(name)
    except Exception as e:
        print("Modellar ro'yxatini olib bo'lmadi:", e)
    found.sort(reverse=True)  # yangi versiyalar oldinda
    order = [config.GEMINI_MODEL, "gemini-flash-latest"] + found
    models = list(dict.fromkeys(order))[:6]
    _GEMINI_CACHE["m"] = models
    print("Gemini modellari navbati:", models)
    return models


def _ask_gemini(prompt, max_tokens):
    hdr = {"x-goog-api-key": config.GEMINI_API_KEY, "content-type": "application/json"}
    models = []
    for m in (config.GEMINI_MODEL, "gemini-3.8-flash", "gemini-flash-latest", "gemini-flash-lite-latest"):
        if m and m not in models:
            models.append(m)
    last = "javob yo'q"
    for rnd in range(2):  # hamma model band bo'lsa, 45 soniya kutib yana bir aylanish
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            cfg = {"maxOutputTokens": max(max_tokens, 2048), "temperature": 0.8}
            cfg["thinkingConfig"] = {"thinkingLevel": "low"} if "gemini-3" in model else {"thinkingBudget": 0}
            for attempt in range(3):
                try:
                    r = requests.post(url, headers=hdr, timeout=180,
                                      json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg})
                except (requests.Timeout, requests.ConnectionError) as e:
                    last = f"{model}: {type(e).__name__}"
                    print("Gemini kutish/ulanish xatosi:", last)
                    time.sleep(5)
                    continue
                if r.status_code == 200:
                    parts = r.json()["candidates"][0]["content"]["parts"]
                    return "".join(p.get("text", "") for p in parts)
                last = f"{model}: {r.status_code} {r.text[:200]}"
                print("Gemini:", last[:120])
                if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in cfg:
                    cfg.pop("thinkingConfig")
                    cfg["maxOutputTokens"] = 8192
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(8 * (attempt + 1))
                    continue
                break  # 404 va boshqalar: keyingi modelga
        if rnd == 0:
            time.sleep(45)
    raise RuntimeError(f"Gemini xato: {last}")


def _ask_claude(prompt, max_tokens):
    r = requests.post(
        API,
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _ask(prompt, max_tokens=4000):
    """GEMINI_API_KEY bo'lsa bepul Gemini, aks holda Claude."""
    if config.GEMINI_API_KEY:
        return _ask_gemini(prompt, max_tokens)
    if config.ANTHROPIC_API_KEY:
        return _ask_claude(prompt, max_tokens)
    raise SystemExit("GEMINI_API_KEY (bepul) yoki ANTHROPIC_API_KEY kerak")


def new_topic(used):
    used_txt = "\n".join(f"- {u}" for u in used[-60:]) or "(hali yo'q)"
    text = _ask(
        f"YouTube kanal uchun yo'nalish: {config.NICHE}.\n"
        "O'zbekistonlik tomoshabinga qiziq bo'ladigan YANGI bitta video mavzusini o'ylab top.\n"
        f"Avval ishlatilgan mavzular (takrorlama):\n{used_txt}\n\n"
        "Faqat mavzuni bitta qator qilib, o'zbek tilida (lotin) yoz. Boshqa hech narsa yozma.",
        max_tokens=100,
    )
    return text.strip().splitlines()[0].strip("-• \"")


def make_script(topic, fmt):
    if fmt == "shorts":
        spec = "Short video: jami 40-55 soniya, 7-9 ta sahna, har sahna 1-2 qisqa jumla. Birinchi sahna kuchli 'hook' bo'lsin."
    else:
        spec = "Uzun video: jami 4-6 daqiqa, 12-16 ta sahna, har sahna 2-4 jumla. Kirish, asosiy qism va xulosa bo'lsin."
    text = _ask(
        f"Sen YouTube uchun ssenariy yozuvchisan. Mavzu: {topic}\n{spec}\n\n"
        "Qoidalar:\n"
        "- Narration: sodda, jonli o'zbek tili (lotin yozuvi), ovoz chiqarib o'qishga qulay. Raqamlarni so'z bilan yoz. Emoji, qavs, sahna belgilari YO'Q.\n"
        "- Faqat haqiqiy, tekshirilgan faktlar yoz. Bilmagan narsani to'qima.\n"
        "- Har sahna uchun 'query': stok video qidirish uchun 2-4 so'zli INGLIZCHA so'rov (aniq, ko'rinadigan narsa: 'ocean waves', 'city night traffic').\n"
        "- title: 60 belgigacha, qiziqtiruvchi. description: 2-3 jumla + 3 ta hashtag. tags: 8-12 ta.\n\n"
        "Faqat JSON qaytar, boshqa matn yo'q:\n"
        '{"title":"","description":"","tags":[""],"scenes":[{"narration":"","query":""}]}',
        max_tokens=6000,
    )
    s, e = text.find("{"), text.rfind("}")
    data = json.loads(text[s : e + 1])
    assert data["scenes"], "ssenariy bo'sh"
    return data


def demo_script(topic):
    return {
        "title": f"Test: {topic}"[:60],
        "description": "Sinov video #test #bot #uzbek",
        "tags": ["test", "uzbek"],
        "scenes": [
            {"narration": "Salom! Bu sinov video bo'lib, bot ishlayotganini tekshiramiz.", "query": "city night"},
            {"narration": "Har bir sahna uchun alohida ovoz va tasvir tanlanadi.", "query": "ocean waves"},
            {"narration": "Oxirida hammasi bitta videoga birlashtiriladi va yuklanadi.", "query": "mountain sunrise"},
        ],
    }

# ==================== py ====================
def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg xato:\n{' '.join(map(str, cmd))}\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


# ---------------------------------------------------------------- ovoz
def tts(text, out_path, dry=False):
    out_path = pathlib.Path(out_path)
    if dry:  # internetsiz sinov: so'zlar soniga qarab sinus ovoz
        secs = max(1.5, len(text.split()) * 0.38)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={secs}", "-c:a", "libmp3lame", str(out_path)])
        return out_path
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, config.TTS_VOICE, rate=config.TTS_RATE).save(str(out_path))

    async def guarded():
        await asyncio.wait_for(go(), timeout=90)

    last = None
    for _ in range(3):
        try:
            asyncio.run(guarded())
            return out_path
        except Exception as e:
            last = e
            print("Ovoz xatosi, qayta uriniladi:", type(e).__name__, e)
            time.sleep(3)
    raise RuntimeError(f"Ovoz (edge-tts) ishlamadi: {type(last).__name__}: {last}")
    return out_path


# ---------------------------------------------------------------- tasvir
def _download(url, path):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def _fetch_pixabay(query, fmt, out_base, used_ids):
    key = config.PIXABAY_API_KEY
    w, h = config.SIZES[fmt]
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": query, "per_page": 20, "safesearch": "true"},
        timeout=30,
    )
    r.raise_for_status()
    for v in r.json().get("hits", []):
        if ("pxb", v["id"]) in used_ids:
            continue
        vids = [x for x in v.get("videos", {}).values() if x.get("url") and x.get("width")]
        if not vids:
            continue
        # kerakli o'lchamga yaqin, lekin juda katta bo'lmagan fayl
        vids.sort(key=lambda x: abs(x["width"] - 1280) if x["width"] >= 640 else 9999)
        used_ids.add(("pxb", v["id"]))
        p = out_base.with_suffix(".mp4")
        _download(vids[0]["url"], p)
        return p, "video"
    r = requests.get(
        "https://pixabay.com/api/",
        params={"key": key, "q": query, "image_type": "photo", "per_page": 10, "safesearch": "true",
                "orientation": "vertical" if fmt == "shorts" else "horizontal"},
        timeout=30,
    )
    r.raise_for_status()
    for ph in r.json().get("hits", []):
        if ("pxbp", ph["id"]) in used_ids:
            continue
        used_ids.add(("pxbp", ph["id"]))
        p = out_base.with_suffix(".jpg")
        _download(ph["largeImageURL"], p)
        return p, "photo"
    raise RuntimeError(f"Pixabay'da '{query}' uchun hech narsa topilmadi")


def fetch_visual(query, fmt, out_base, used_ids, dry=False):
    """(fayl_yo'li, 'video'|'photo') qaytaradi."""
    out_base = pathlib.Path(out_base)
    w, h = config.SIZES[fmt]
    if dry:
        p = out_base.with_suffix(".mp4")
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration=4", "-pix_fmt", "yuv420p", str(p)])
        return p, "video"
    if config.PIXABAY_API_KEY:
        return _fetch_pixabay(query, fmt, out_base, used_ids)
    if not config.PEXELS_API_KEY:
        raise SystemExit("PIXABAY_API_KEY yoki PEXELS_API_KEY .env faylida yo'q")
    hdr = {"Authorization": config.PEXELS_API_KEY}
    orient = "portrait" if fmt == "shorts" else "landscape"

    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers=hdr,
        params={"query": query, "orientation": orient, "per_page": 10, "size": "medium"},
        timeout=30,
    )
    r.raise_for_status()
    for v in r.json().get("videos", []):
        if v["id"] in used_ids:
            continue
        files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("width")]
        if not files:
            continue
        # kerakli o'lchamga eng yaqin (lekin juda og'ir emas) fayl
        files.sort(key=lambda f: abs(f["width"] - w) + (0 if f["width"] >= w * 0.6 else 5000))
        used_ids.add(v["id"])
        p = out_base.with_suffix(".mp4")
        _download(files[0]["link"], p)
        return p, "video"

    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers=hdr,
        params={"query": query, "orientation": orient, "per_page": 5},
        timeout=30,
    )
    r.raise_for_status()
    for ph in r.json().get("photos", []):
        if ("p", ph["id"]) in used_ids:
            continue
        used_ids.add(("p", ph["id"]))
        p = out_base.with_suffix(".jpg")
        _download(ph["src"]["large2x"], p)
        return p, "photo"
    raise RuntimeError(f"Pexels'da '{query}' uchun hech narsa topilmadi")


# ---------------------------------------------------------------- yig'ish
def render_scene(media, kind, audio, out, fmt, text=None):
    w, h = config.SIZES[fmt]
    out = pathlib.Path(out)
    dur = duration(audio) + 0.35
    if kind == "video":
        inp = ["-stream_loop", "-1", "-i", str(media)]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=25,setsar=1"
    else:
        frames = int(dur * 25) + 1
        zw, zh = int(w * 1.4) // 2 * 2, int(h * 1.4) // 2 * 2
        inp = ["-loop", "1", "-i", str(media)]
        vf = (
            f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={zw}:{zh},"
            f"zoompan=z='min(zoom+0.0007,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=25,"
            "setsar=1"
        )
    if text:  # subtitrni shu sahnaning o'ziga yozamiz (oxirida qayta kodlash kerak bo'lmaydi)
        ass = out.with_suffix(".ass")
        write_ass([{"narration": text}], [dur], fmt, ass)
        vf += f",ass={ass.name}"
    vf += ",format=yuv420p"
    run(
        ["ffmpeg", "-y", *inp, "-i", str(audio), "-t", f"{dur:.3f}", "-vf", vf, "-af", "apad",
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-threads", "2", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", out.name],
        cwd=out.parent,
    )
    return dur


def _ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(scenes, durs, fmt, path):
    w, h = config.SIZES[fmt]
    size = int(h * 0.034) if fmt == "shorts" else int(h * 0.05)
    margin = int(h * 0.18) if fmt == "shorts" else int(h * 0.08)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Default,{config.SUB_FONT},{size},&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,1,2,60,60,{margin},1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    t = 0.0
    for sc, d in zip(scenes, durs):
        words = sc["narration"].replace("\n", " ").split()
        n = 4 if fmt == "shorts" else 7
        chunks = [" ".join(words[i : i + n]) for i in range(0, len(words), n)] or [""]
        total = sum(len(c) for c in chunks) or 1
        cur = t
        for c in chunks:
            seg = (d - 0.2) * len(c) / total
            text = c.replace("{", "(").replace("}", ")")
            lines.append(f"Dialogue: 0,{_ts(cur)},{_ts(cur+seg)},Default,,0,0,0,,{text}")
            cur += seg
        t += d
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def assemble(scene_files, workdir, final_path):
    """Sahnalarni ulaydi. Video qayta kodlanmaydi (tez); faqat fon musiqa bo'lsa ovoz aralashtiriladi."""
    workdir = pathlib.Path(workdir)
    final_name = pathlib.Path(final_path).name
    lst = workdir / "list.txt"
    lst.write_text("".join(f"file '{pathlib.Path(f).name}'\n" for f in scene_files), encoding="utf-8")
    music = config.MUSIC_FILE and pathlib.Path(config.MUSIC_FILE).exists()
    if not music:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
             "-movflags", "+faststart", final_name], cwd=workdir)
        return
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "full.mp4"], cwd=workdir)
    run(["ffmpeg", "-y", "-i", "full.mp4", "-stream_loop", "-1", "-i", str(pathlib.Path(config.MUSIC_FILE).resolve()),
         "-filter_complex", "[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", final_name], cwd=workdir)


# ==================== py ====================
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # eski sarlavhalarni o'qish uchun
]


def auth():
    """Bir marta brauzerda ruxsat berish. token.json yaratadi."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not config.CLIENT_SECRETS.exists():
        raise SystemExit("client_secret.json topilmadi (README'dagi 3-qadamga qarang)")
    flow = InstalledAppFlow.from_client_secrets_file(str(config.CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(port=0)
    config.TOKEN_FILE.write_text(creds.to_json())
    print("token.json saqlandi")


def auth_manual():
    """Brauzer ochilmaydigan joylar (Codespaces, server, telefon) uchun: URL'ni nusxalab qo'yish usuli."""
    import os
    from google_auth_oauthlib.flow import InstalledAppFlow

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.CLIENT_SECRETS), SCOPES, redirect_uri="http://localhost"
    )
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    print("\n1) Shu havolani brauzerda oching va ruxsat bering:\n\n" + url + "\n")
    print("2) Oxirida sahifa ochilmaydi ('site can't be reached'), bu normal.")
    print("   Brauzer manzil satridagi BUTUN havolani (http://localhost/?code=... ) nusxalab, shu yerga qo'ying.\n")
    resp = input("Havola: ").strip()
    flow.fetch_token(authorization_response=resp)
    config.TOKEN_FILE.write_text(flow.credentials.to_json())
    print("token.json saqlandi")


def _service():
    import os
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if os.environ.get("YT_TOKEN"):  # Render / GitHub: token muhit o'zgaruvchisida
        creds = Credentials.from_authorized_user_info(json.loads(os.environ["YT_TOKEN"]), SCOPES)
        if not creds.valid:
            creds.refresh(Request())
    else:
        if not config.TOKEN_FILE.exists():
            raise SystemExit("Avval: python main.py auth")
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            config.TOKEN_FILE.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def recent_titles(n=50):
    """Kanalning oxirgi video sarlavhalari (takror mavzu bo'lmasligi uchun). Xato bo'lsa bo'sh ro'yxat."""
    try:
        yt = _service()
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        items = yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=n).execute()["items"]
        return [i["snippet"]["title"] for i in items]
    except Exception as e:
        print("Eski sarlavhalarni o'qib bo'lmadi:", e)
        return []


def upload(video_path, meta, privacy=None):
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", [])[:15],
            "categoryId": "27",  # Education
            "defaultLanguage": "uz",
            "defaultAudioLanguage": "uz",
        },
        "status": {
            "privacyStatus": privacy or config.PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    req = yt.videos().insert(
        part="snippet,status", body=body, media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    )
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  yuklanmoqda {int(status.progress()*100)}%")
    url = f"https://youtu.be/{resp['id']}"
    print("Yuklandi:", url)
    return url

# ==================== main.py ====================
#!/usr/bin/env python3
"""YouTube avtomatik video bot.

  python main.py auth                       # YouTube'ga bir marta ulanish
  python main.py make --topic "..."         # bitta video yasash
  python main.py make --topic "..." --upload
  python main.py auto                       # mavzuni o'zi topib, yasab, yuklaydi (cron uchun)
  python main.py make --dry-run             # API kalitsiz sinov (soxta ovoz/tasvir)
"""



def load_history():
    if config.HISTORY_FILE.exists():
        return json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(h):
    config.HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower())[:40].strip("-") or "video"


def make_video(topic, fmt, dry=False):
    data = demo_script(topic) if dry else make_script(topic, fmt)
    work = config.OUTPUT_DIR / f"{datetime.datetime.now():%Y%m%d-%H%M%S}_{slug(topic)}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data["scenes"])
    print(f"Sarlavha: {data['title']}  ({n} sahna)")
    if not dry:
        send(f"📝 Ssenariy tayyor: {data['title']} ({n} sahna). Ovoz va tasvir tayyorlanmoqda...")

    t0 = time.time()
    used, scene_files = set(), []
    for i, sc in enumerate(data["scenes"], 1):
        audio = tts(sc["narration"], work / f"a{i:02d}.mp3", dry)
        vis, kind = fetch_visual(sc["query"], fmt, work / f"v{i:02d}", used, dry)
        out = work / f"s{i:02d}.mp4"
        render_scene(vis, kind, audio, out, fmt, sc["narration"])
        scene_files.append(out)
        print(f"  sahna {i}/{n} tayyor ({int(time.time() - t0)} s)", flush=True)

    assemble(scene_files, work, work / "final.mp4")
    print("Tayyor:", work / "final.mp4", f"({int(time.time() - t0)} s)", flush=True)
    return work / "final.mp4", data


def auto_once(fmt, privacy=None):
    """Mavzu topadi, video yasaydi, YouTube'ga yuklaydi, Telegramga xabar beradi."""
    hist = load_history()
    used = [h["topic"] for h in hist] + recent_titles()
    topic = None
    if config.get("USE_TOPICS_FILE") == "1" and config.TOPICS_FILE.exists():
        for line in config.TOPICS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line not in used:
                topic = line
                break
    try:
        if not topic:
            topic = new_topic(used)
        print("Mavzu:", topic)
        path, data = make_video(topic, fmt)
        send("⬆️ Video tayyor, YouTube'ga yuklanmoqda...")
        url = upload(path, data, privacy)
    except Exception as e:
        send(f"❌ Video yuklanmadi\nMavzu: {topic}\nXato: {type(e).__name__}: {str(e)[:700]}")
        raise
    send(f"✅ Video yuklandi ({privacy or config.PRIVACY})\n{data['title']}\n{url}")
    send_video(path, data["title"])
    hist.append({"topic": topic, "title": data["title"], "url": url,
                 "date": datetime.datetime.now().isoformat(timespec="seconds")})
    save_history(hist)


def posted_count_today():
    """Kanalga bugun (Toshkent vaqti) nechta video yuklangan. Xato bo'lsa 0."""
    try:
        yt = _service()
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        items = yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=10).execute()["items"]
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5))).date()
        n = 0
        for i in items:
            t = datetime.datetime.strptime(i["snippet"]["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S")
            if (t + datetime.timedelta(hours=5)).date() == today:
                n += 1
        return n
    except Exception as e:
        print("posted_count_today xato:", e)
        return 0


def parse_times(text):
    """'7:00 18:00', '07,18', '9, 21:30' -> [(7,0),(18,0)]. Noto'g'ri bo'lsa None."""
    parts = [p for p in re.split(r"[\s,;]+", text.strip()) if p]
    out = []
    for p in parts:
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", p)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h > 23 or mi > 59:
            return None
        out.append((h, mi))
    return sorted(set(out)) or None


def fmt_times(times):
    return ", ".join(f"{h:02d}:{m:02d}" for h, m in times)


def schedule_step(state, t, now, times, job, count_posted, max_attempts=4, retry_min=25):
    """Kuniga len(times) ta video: har bir vaqt kelganda yasaydi. Xato bo'lsa retry_min daqiqadan keyin qayta uriniladi."""
    if state.get("date") != t.date():
        state.update(date=t.date(), made=0, synced=False, attempts=0, next=0)
    mins = t.hour * 60 + t.minute
    due = sum(1 for h, m in times if h * 60 + m <= mins)
    if due == 0 or state["made"] >= due:
        return
    if state["attempts"] >= max_attempts * max(len(times), 1) or now < state["next"]:
        return
    if not state["synced"]:  # qayta ishga tushganda kanaldagi bugungi videolarni hisobga olamiz
        state["made"] = max(state["made"], count_posted())
        state["synced"] = True
        if state["made"] >= due:
            return
    state["attempts"] += 1
    res = job()
    if res is True:
        state["made"] += 1
    elif res is None:  # boshqa video yasalmoqda
        state["attempts"] -= 1
        state["next"] = now + 600
    else:
        state["next"] = now + retry_min * 60


def handle_command(text, holder, trigger, privacy):
    """Telegramdagi xabarga javob matnini qaytaradi (yoki None)."""
    text = (text or "").strip()
    if not text:
        return None
    first = text.split()[0].lower().split("@")[0] if text.startswith("/") else ""
    rest = text.split(None, 1)[1] if text.startswith("/") and len(text.split(None, 1)) > 1 else text
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5)))
    status = (f"🕒 Hozir: {now:%H:%M} (Toshkent)\n📅 Kunlik video vaqtlari: {fmt_times(holder['times'])}\n"
              f"🔒 Holat: {privacy or config.PRIVACY}\n\n"
              "Buyruqlar:\n/vaqt 07:00 18:00 - vaqtlarni o'zgartirish\n/video - hozir bitta video yasash\n/holat - shu xabar")
    if first in ("/start", "/holat", "/status", "/help", ""):
        if first == "" and parse_times(text):
            pass  # oddiy vaqt yozilgan: pastda qayta ishlanadi
        else:
            return status
    if first in ("/video", "/hozir"):
        if trigger() is False:
            return "⏳ Oldingi video hali yasalmoqda. Tugagach yana urinib ko'ring."
        return "🎬 Video yasash boshlandi. Tayyor bo'lgach xabar yuboraman."
    if first in ("/vaqt", "/time", "/jadval", ""):
        if first and rest == text:  # /vaqt argumentsiz
            return f"📅 Hozirgi vaqtlar: {fmt_times(holder['times'])}\nO'zgartirish: /vaqt 07:00 18:00"
        times = parse_times(rest)
        if not times:
            return "Vaqt formati noto'g'ri. Masalan: /vaqt 07:00 18:00"
        holder["times"] = times
        return (f"✅ Saqlandi: har kuni {fmt_times(times)} (Toshkent) da {len(times)} ta video.\n"
                f"Doimiy qilish uchun Render'da RUN_TIMES={','.join(f'{h:02d}:{m:02d}' for h, m in times)} qo'yib qo'ying.")
    return status


def serve(fmt, privacy=None):
    """Render Web Service uchun: port ochib turadi, belgilangan vaqtlarda video yasaydi, Telegram buyruqlarini o'qiydi.
    /run?key=RUN_KEY - qo'lda ishga tushirish, /test?key=RUN_KEY - Telegram sinovi."""
    import http.server
    import threading

    key = config.get("RUN_KEY")
    port = int(os.environ.get("PORT", "10000"))
    lock = threading.Lock()
    raw = config.get("RUN_TIMES") or f"{config.get('RUN_HOUR', '9')}:00"
    holder = {"times": parse_times(raw) or [(9, 0)]}

    def job():
        """True: muvaffaqiyatli, False: xato, None: boshqa video hali yasalmoqda."""
        if not lock.acquire(blocking=False):
            print("Oldingi video hali yasalmoqda, o'tkazib yuborildi")
            return None
        try:
            auto_once(fmt, privacy)
            return True
        except Exception as e:
            print("Xato:", type(e).__name__, e)
            return False
        finally:
            lock.release()

    def tk_now():
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5)))

    def scheduler():
        state = {}
        while True:
            try:
                schedule_step(state, tk_now(), time.time(), holder["times"], job, posted_count_today)
            except Exception as e:
                print("Rejalashtiruvchi xato:", e)
            time.sleep(60)

    def trigger():
        if lock.locked():
            return False
        threading.Thread(target=job, daemon=True).start()
        return True

    def telegram_loop():
        token, chat = _creds()
        if not token or not chat:
            return
        base = f"https://api.telegram.org/bot{token}"
        offset = None
        try:  # eski xabarlarni o'tkazib yuboramiz
            r = requests.get(base + "/getUpdates", params={"offset": -1, "timeout": 0}, timeout=30).json()
            if r.get("result"):
                offset = r["result"][-1]["update_id"] + 1
        except Exception as e:
            print("getUpdates boshlang'ich xato:", e)
        while True:
            try:
                r = requests.get(base + "/getUpdates", params={"offset": offset, "timeout": 30}, timeout=45).json()
                if not r.get("ok"):
                    print("getUpdates:", str(r)[:200])
                    time.sleep(30)
                    continue
                for u in r.get("result", []):
                    offset = u["update_id"] + 1
                    m = u.get("message") or u.get("channel_post")
                    if not m or str(m["chat"]["id"]) != str(chat):
                        continue
                    reply = handle_command(m.get("text"), holder, trigger, privacy)
                    if reply:
                        send(reply)
            except Exception as e:
                print("Telegram tinglash xatosi:", e)
                time.sleep(10)

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code, text):
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(text.encode("utf-8"))

        def do_GET(self):
            if self.path.startswith("/test"):
                if key and f"key={key}" in self.path:
                    return self._send(200, send("✅ Sinov xabari: Telegram ulangan, bot ishlayapti"))
                return self._send(403, "Ruxsat yo'q")
            if self.path.startswith("/run"):
                if key and f"key={key}" in self.path:
                    trigger()
                    return self._send(200, "Boshlandi. Natija Telegramga keladi.")
                return self._send(403, "Ruxsat yo'q")
            self._send(200, "Video bot ishlayapti")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=telegram_loop, daemon=True).start()
    print(f"Server {port} portda. Kunlik vaqtlar: {fmt_times(holder['times'])} (Toshkent)")
    http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


def main():
    for st in (sys.stdout, sys.stderr):  # Render loglarida natija darrov ko'rinsin
        try:
            st.reconfigure(line_buffering=True)
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("auth")
    pa.add_argument("--manual", action="store_true", help="havolani qo'lda nusxalash usuli")
    for name in ("make", "auto", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--format", choices=["shorts", "long"], default=config.VIDEO_FORMAT)
        p.add_argument("--privacy", choices=["private", "unlisted", "public"])
        if name == "make":
            p.add_argument("--topic", default="Sinov mavzu")
            p.add_argument("--upload", action="store_true")
            p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "auth":
        auth_manual() if a.manual else auth()
    elif a.cmd == "make":
        path, data = make_video(a.topic, a.format, a.dry_run)
        if a.upload:
            upload(path, data, a.privacy)
    elif a.cmd == "serve":
        serve(a.format, a.privacy)
    elif a.cmd == "auto":
        # Render Web Service PORT beradi: shunda bir martalik emas, doimiy server rejimi
        if os.environ.get("PORT") and config.get("FORCE_ONESHOT") != "1":
            serve(a.format, a.privacy)
        else:
            auto_once(a.format, a.privacy)


if __name__ == "__main__":
    sys.exit(main())
