"""Gemini (bepul) yoki Claude orqali mavzu va ssenariy (o'zbek tilida) yaratish."""
import json
import requests
import config

API = "https://api.anthropic.com/v1/messages"


def _ask_gemini(prompt, max_tokens):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    hdr = {"x-goog-api-key": config.GEMINI_API_KEY, "content-type": "application/json"}
    cfg = {"maxOutputTokens": max(max_tokens, 1024), "temperature": 0.8,
           "thinkingConfig": {"thinkingBudget": 0}}  # 'o'ylash' tokenlari javobni yeb qo'ymasin
    for attempt in range(2):
        r = requests.post(url, headers=hdr, timeout=120,
                          json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg})
        if r.status_code == 400 and "thinking" in r.text.lower() and attempt == 0:
            cfg.pop("thinkingConfig")  # bu model thinkingConfig'ni qo'llamasa
            cfg["maxOutputTokens"] = 8192
            continue
        break
    if r.status_code != 200:
        raise RuntimeError(f"Gemini xato {r.status_code}: {r.text[:400]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


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
