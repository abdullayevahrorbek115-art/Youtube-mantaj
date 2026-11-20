import os
import pathlib

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


_load_env()


def get(name, default=None):
    return os.environ.get(name, default)


ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY")
GEMINI_API_KEY = get("GEMINI_API_KEY")  # bepul: aistudio.google.com/apikey
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-2.5-flash")
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

SIZES = {"shorts": (1080, 1920), "long": (1920, 1080)}
