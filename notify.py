"""Telegram orqali xabar yuborish (faqat bildirishnoma, bot doim yoqiq turishi shart emas)."""
import os
import requests


def _creds():
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def send(text):
    token, chat = _creds()
    if not token or not chat:
        print("[telegram o'chiq]", text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text[:4000]}, timeout=30)
    except Exception as e:
        print("Telegramga yuborib bo'lmadi:", e)


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
