"""Ovoz (edge-tts, o'zbek), stok video (Pexels) va ffmpeg bilan yig'ish."""
import asyncio
import pathlib
import subprocess
import requests
import config


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

    asyncio.run(go())
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
def render_scene(media, kind, audio, out, fmt):
    w, h = config.SIZES[fmt]
    dur = duration(audio) + 0.35
    if kind == "video":
        inp = ["-stream_loop", "-1", "-i", str(media)]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1,format=yuv420p"
    else:
        frames = int(dur * 30) + 1
        inp = ["-loop", "1", "-i", str(media)]
        vf = (
            f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
            f"zoompan=z='min(zoom+0.0007,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30,"
            "setsar=1,format=yuv420p"
        )
    run(
        ["ffmpeg", "-y", *inp, "-i", str(audio), "-t", f"{dur:.3f}", "-vf", vf, "-af", "apad",
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k", str(out)]
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
    workdir = pathlib.Path(workdir)
    lst = workdir / "list.txt"
    lst.write_text("".join(f"file '{pathlib.Path(f).name}'\n" for f in scene_files), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "full.mp4"], cwd=workdir)

    cmd = ["ffmpeg", "-y", "-i", "full.mp4"]
    music = config.MUSIC_FILE and pathlib.Path(config.MUSIC_FILE).exists()
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(pathlib.Path(config.MUSIC_FILE).resolve())]
        fc = "[0:v]ass=subs.ass[v];[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", "ass=subs.ass", "-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", pathlib.Path(final_path).name]
    run(cmd, cwd=workdir)
