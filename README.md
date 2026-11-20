# YouTube avtomatik video bot (o'zbek tilida)

Mavzu topadi → ssenariy yozadi (Claude) → o'zbekcha ovoz beradi (edge-tts) →
stok videolarni tanlaydi (Pexels) → subtitr bilan yig'adi (ffmpeg) → YouTube'ga yuklaydi.

## O'rnatish
1. Python 3.10+ va `ffmpeg` o'rnating. Keyin: `pip install -r requirements.txt`
2. `.env.example` ni `.env` ga nusxalang, kalitlarni yozing:
   - `ANTHROPIC_API_KEY` — console.anthropic.com
   - `PIXABAY_API_KEY` — pixabay.com/api/docs (bepul, ro'yxatdan o'tgach darrov chiqadi). Muqobil: `PEXELS_API_KEY`
3. YouTube: console.cloud.google.com → yangi loyiha → "YouTube Data API v3" ni yoqing →
   OAuth consent screen (External, o'zingizni Test user qiling) → Credentials →
   OAuth client ID (**Desktop app**) → JSON'ni `client_secret.json` nomi bilan shu papkaga qo'ying.
   **Muhim:** ruxsat 7 kunda tugab qolmasligi uchun OAuth consent screen'da "Publish app" (In production)
   tugmasini bosing. Shaxsiy foydalanish uchun tekshiruv shart emas, faqat "Google hasn't verified" ogohlantirishi chiqadi.
4. `python main.py auth` — brauzerda ruxsat bering (bir marta). Kompyuteringizda bajaring, keyin
   hosil bo'lgan `token.json` ni serverga ko'chiring.

## Ishlatish
```
python main.py make --dry-run                    # kalitsiz sinov
python main.py make --topic "Nega osmon ko'k?"   # faqat video yasaydi (output/ papkasida)
python main.py make --topic "..." --upload       # yasab yuklaydi
python main.py auto                              # topics.txt dan yoki Claude topgan mavzu bilan yasab yuklaydi
python main.py auto --format long                # uzun video
```

## To'liq avtomatik (kuniga 1 ta)
Serverda cron: `0 9 * * * cd /yo'l/yt-bot && python3 main.py auto >> bot.log 2>&1`

## Muhim
- Yangi API loyihadan yuklangan videolar YouTube auditidan o'tmaguncha **private** bo'lib qoladi.
  Audit formasi: support.google.com/youtube/contact/yt_api_form. Shungacha Studio'da qo'lda public qilasiz.
- Kunlik kvota: bir yuklash ~1600 birlik, standart limit 10 000 → kuniga ~6 ta video.
- YouTube Studio'da "o'zgartirilgan/sintetik kontent" belgisini o'z qoidasiga qarab belgilang.
- Bir xil shablonli ommaviy videolar monetizatsiyada "inauthentic content" deb rad etilishi mumkin.
  Mavzu, ssenariy va tasvirni xilma-xil va qiymatli qiling; `PRIVACY=private` bilan avval tekshirib ko'ring.
- Fon musiqa uchun faqat litsenziyasi bor fayl ishlating (`MUSIC_FILE`).
- Videodagidek AI-generatsiya qilingan kadrlar (Veo, Kling va h.k.) uchun `media.fetch_visual` ni
  almashtirish kifoya: u fayl yo'li va `'video'` qaytarsa bo'ldi.

## GitHub Actions bilan kunlik avtomatik ishga tushirish
Repo **private** bo'lsin. `client_secret.json`, `token.json`, `.env` ni GitHub'ga YUKLAMANG (`.gitignore` ularni o'tkazmaydi).
Settings → Secrets and variables → Actions → New repository secret:
`ANTHROPIC_API_KEY`, `PIXABAY_API_KEY`, `YT_CLIENT_SECRET` (client_secret.json ichidagi matn), `YT_TOKEN` (token.json ichidagi matn).
`token.json` ni olish: `python main.py auth --manual`. Sinash: Actions → "Kunlik video" → Run workflow.
Maxfiylik havolalari uchun `docs/` papkasini GitHub Pages qiling (Settings → Pages → /docs).
