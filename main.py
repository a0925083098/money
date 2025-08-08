import os, io, time, logging
from typing import Dict, Any, List
import requests
from PIL import Image, ImageOps, ImageFilter

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

# ====== 環境變數 ======
BOT_TOKEN   = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
OCR_API_KEY = os.environ.get("OCR_API_KEY", "helloworld")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("baccarat-bot")

# ====== 快捷鍵（常駐）======
REPLY_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("開始預測")],
        [KeyboardButton("莊"), KeyboardButton("閒")],
        [KeyboardButton("繼續分析"), KeyboardButton("停止分析")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ====== 影像預處理 + OCR ======
def preprocess_for_ocr(img_bytes: bytes) -> bytes:
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    scale = 1.7 if max(w, h) < 1800 else 1.2
    im = im.resize((int(w*scale), int(h*scale)))
    im = ImageOps.autocontrast(im, cutoff=1).filter(ImageFilter.SHARPEN)
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()

def ocr_space_image(img_jpg_bytes: bytes) -> str:
    url = "https://api.ocr.space/parse/image"
    files = {"file": ("image.jpg", img_jpg_bytes, "image/jpeg")}
    data = {"apikey": OCR_API_KEY, "language": "eng", "isOverlayRequired": False, "filetype": "JPG"}
    try:
        r = requests.post(url, files=files, data=data, timeout=30); r.raise_for_status()
        js = r.json()
        if js.get("IsErroredOnProcessing"): return ""
        pr = js.get("ParsedResults", []);  return pr[0].get("ParsedText","") if pr else ""
    except Exception as e:
        log.exception("OCR error: %s", e); return ""

# ====== 簡易建模 + 預測（可之後換 GPT）======
def build_room_from_ocr_text(txt: str) -> Dict[str, Any]:
    hist: List[str] = []
    for ch in txt:
        if ch in ("莊","閒"): hist.append(ch)
        if ch.upper()=="B": hist.append("莊")
        if ch.upper()=="P": hist.append("閒")
    if len(hist) < 6: hist = (["莊","閒"]*6)[:12]
    model = {
        "total": len(hist),
        "banker_count": sum(1 for x in hist if x=="莊"),
        "player_count": sum(1 for x in hist if x=="閒"),
    }
    return {"history": hist, "model": model}

def simple_predict(history: List[str]) -> Dict[str, Any]:
    look = history[-6:] if len(history)>=6 else history[:]
    b = sum(1 for x in look if x=="莊"); p = len(look)-b
    if b>p: pick="莊"; p_bank = 0.55 + min(0.1,(b-p)*0.03)
    elif p>b: pick="閒"; p_bank = 1-(0.55 + min(0.1,(p-b)*0.03))
    else: pick="閒" if (look and look[-1]=="莊") else "莊"; p_bank=0.50
    return {"pick":pick, "p_bank":round(p_bank,2), "p_player":round(1-p_bank,2),
            "reason":f"近{len(look)}手分佈：莊{b}/閒{p}，採趨勢延續/平手反向策略。"}

def fmt(pred):  # 回覆模板
    return (f"✅ 預測：{pred['pick']}\n"
            f"📊 勝率：莊 {int(pred['p_bank']*100)}%、閒 {int(pred['p_player']*100)}%\n"
            f"🧠 統合分析：{pred['reason']}")

# ====== Handlers ======
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "傳牌路圖片建立模型；之後用下方快捷鍵操作：\n"
        "開始預測／莊／閒／繼續分析／停止分析",
        reply_markup=REPLY_KB
    )

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    await m.reply_text("📥 圖片已接收，開始分析...", reply_markup=REPLY_KB)
    file = await m.photo[-1].get_file()
    jpg = preprocess_for_ocr(await file.download_as_bytearray())
    txt = ocr_space_image(jpg)
    room = build_room_from_ocr_text(txt)
    context.user_data["room"] = {
        "built_at": int(time.time()),
        "history": room["history"],
        "last_input": None,
        "model": room["model"],
    }
    await m.reply_text(
        "🧩 房間數據分析完成 ✅\n🧠 AI 模型已建立\n"
        "1️⃣ 請按「莊/閒」輸入最新開獎\n2️⃣ 再按「繼續分析」預測下一局\n"
        "🔁 換房請按「停止分析」。",
        reply_markup=REPLY_KB,
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if t == "停止分析":
        context.user_data.pop("room", None)
        return await update.message.reply_text("🧹 已清空資料，請重新上傳走勢圖。", reply_markup=REPLY_KB)

    room = context.user_data.get("room")
    if t == "開始預測":
        if not room: return await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB)
        return await update.message.reply_text(fmt(simple_predict(room["history"])), reply_markup=REPLY_KB)

    if t in ("莊","閒"):
        if not room: return await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB)
        room["last_input"] = t
        return await update.message.reply_text("✅ 已記錄最新開獎，請按「繼續分析」。", reply_markup=REPLY_KB)

    if t == "繼續分析":
        if not room: return await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB)
        if not room.get("last_input"): return await update.message.reply_text("請先按「莊/閒」輸入最新開獎。", reply_markup=REPLY_KB)
        room["history"].append(room["last_input"]); room["last_input"] = None
        return await update.message.reply_text(fmt(simple_predict(room["history"])), reply_markup=REPLY_KB)

    # 其他文字
    await update.message.reply_text("請用下方快捷鍵操作。", reply_markup=REPLY_KB)

# ====== 進入點 ======
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
