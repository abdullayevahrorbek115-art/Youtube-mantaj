#!/usr/bin/env python3
"""YouTube avtomatik video bot.

  python main.py auth                       # YouTube'ga bir marta ulanish
  python main.py make --topic "..."         # bitta video yasash
  python main.py make --topic "..." --upload
  python main.py auto                       # mavzuni o'zi topib, yasab, yuklaydi (cron uchun)
  python main.py make --dry-run             # API kalitsiz sinov (soxta ovoz/tasvir)
"""
import argparse
import datetime
import json
import re
import sys

import config
import media
import notify
import script_gen


def load_history():
    if config.HISTORY_FILE.exists():
        return json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(h):
    config.HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower())[:40].strip("-") or "video"


def make_video(topic, fmt, dry=False):
    data = script_gen.demo_script(topic) if dry else script_gen.make_script(topic, fmt)
    work = config.OUTPUT_DIR / f"{datetime.datetime.now():%Y%m%d-%H%M%S}_{slug(topic)}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sarlavha: {data['title']}  ({len(data['scenes'])} sahna)")

    used, scene_files, durs = set(), [], []
    for i, sc in enumerate(data["scenes"], 1):
        print(f"  sahna {i}/{len(data['scenes'])}")
        audio = media.tts(sc["narration"], work / f"a{i:02d}.mp3", dry)
        vis, kind = media.fetch_visual(sc["query"], fmt, work / f"v{i:02d}", used, dry)
        out = work / f"s{i:02d}.mp4"
        durs.append(media.render_scene(vis, kind, audio, out, fmt))
        scene_files.append(out)

    media.write_ass(data["scenes"], durs, fmt, work / "subs.ass")
    media.assemble(scene_files, work, work / "final.mp4")
    print("Tayyor:", work / "final.mp4")
    return work / "final.mp4", data


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("auth")
    pa.add_argument("--manual", action="store_true", help="havolani qo'lda nusxalash usuli")
    for name in ("make", "auto"):
        p = sub.add_parser(name)
        p.add_argument("--format", choices=["shorts", "long"], default=config.VIDEO_FORMAT)
        p.add_argument("--privacy", choices=["private", "unlisted", "public"])
        if name == "make":
            p.add_argument("--topic", default="Sinov mavzu")
            p.add_argument("--upload", action="store_true")
            p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "auth":
        import uploader
        uploader.auth_manual() if a.manual else uploader.auth()
        return

    if a.cmd == "make":
        path, data = make_video(a.topic, a.format, a.dry_run)
        if a.upload:
            import uploader
            uploader.upload(path, data, a.privacy)
        return

    if a.cmd == "auto":
        import uploader
        hist = load_history()
        used = [h["topic"] for h in hist] + uploader.recent_titles()
        topic = None
        if config.get("USE_TOPICS_FILE") == "1" and config.TOPICS_FILE.exists():
            for line in config.TOPICS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line not in used:
                    topic = line
                    break
        if not topic:
            topic = script_gen.new_topic(used)
        print("Mavzu:", topic)
        try:
            path, data = make_video(topic, a.format)
            url = uploader.upload(path, data, a.privacy)
        except Exception as e:
            notify.send(f"❌ Video yuklanmadi\nMavzu: {topic}\nXato: {type(e).__name__}: {str(e)[:700]}")
            raise
        notify.send(f"✅ Video yuklandi ({a.privacy or config.PRIVACY})\n{data['title']}\n{url}")
        notify.send_video(path, data["title"])
        hist.append({"topic": topic, "title": data["title"], "url": url,
                     "date": datetime.datetime.now().isoformat(timespec="seconds")})
        save_history(hist)


if __name__ == "__main__":
    sys.exit(main())
