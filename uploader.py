"""YouTube Data API v3 orqali yuklash."""
import json
import config

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
