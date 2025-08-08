import os, io, time, logging, json
from typing import List
import requests
from PIL import Image, ImageOps, ImageFilter
from openai import OpenAI

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

# ====== Env ======
BOT_TOKEN       = os.environ["BOT_TOKEN"]
WEBHOOK_URL     = os.environ.get("WEBHOOK_URL")   # 例：https://your-service.onrender.com
OCR_API_KEY     = os.environ.get("OCR_API_KEY", "helloworld")
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("baccarat-bot")

# OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Reply Keyboard（快捷鍵）======
REPLY_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("開始預測")],
        [KeyboardButton("莊"), KeyboardButton("閒")],
        [KeyboardButton("繼續分析"), KeyboardButton("停止分析")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ====== 影像預處理 + OCR =======
def preprocess_for_ocr(img_bytes: bytes) -> bytes:
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    scale = 1.7 if max(w, h) < 1800 else 1.2
    im = im.resize((int(w * scale), int(h * scale)))
    im = ImageOps.autocontrast(im, cutoff=1).filter(ImageFilter.SHARPEN)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()

def ocr_space_image(img_jpg_bytes: bytes) -> str:
    url = "https://api.ocr.space/parse/image"
    files = {"file": ("image.jpg", img_jpg_bytes, "image/jpeg")}
    data = {"apikey": OCR_API_KEY, "language": "eng", "isOverlayRequired": False, "filetype": "JPG"}
    try:
        r = requests.post(url, files=files, data=data, timeout=30)
        r.raise_for_status()
        js = r.json()
        if js.get("IsErroredOnProcessing"):
            log.warning("OCR error: %s", js.get("ErrorMessage"))
            return ""
        pr = js.get("ParsedResults", [])
        return pr[0].get("ParsedText", "") if pr else ""
    except Exception as e:
        log.exception("OCR exception: %s", e)
        return ""

# ====== 由 OCR 文字建立歷史序列（簡化版）======
def build_history_from_text(txt: str) -> List[str]:
    hist: List[str] = []
    for ch in txt:
        if ch in ("莊", "閒"):
            hist.append(ch)
        elif ch.upper() == "B":
            hist.append("莊")
        elif ch.upper() == "P":
            hist.append("閒")
    if len(hist) < 6:
        # 避免空資料—僅作占位，實務請換成你真正的牌路解析
        hist = (["莊", "閒"] * 6)[:12]
    return hist

# ====== GPT 混合分析（全局60% + 最近6手40%），勝率差至少2% ======
def gpt_predict(history: List[str]) -> dict:
    n = len(history)
    last6 = history[-6:] if n >= 6 else history[:]
    prompt = (
        "你是百家樂走勢分析專家，請結合【全局統計(60%)】與【最近6手(40%)】進行混合分析，"
        "並預測下一局莊/閒與勝率。\n\n"
        "嚴格要求：\n"
        "1) 勝率必須有偏向，差距至少 0.02（2%），不得 50/50。\n"
        "2) 僅回傳 JSON：{pick:'莊或閒', p_bank:0~1, p_player:0~1, reason:'簡短中文結論', detail:'完整分析'}\n"
        "3) reason 最多15個字，聚焦結論（例如：全局偏莊，短期同方 / 短期反彈機率高）。\n"
        "4) p_bank + p_player 必須 = 1。\n\n"
        f"全局序列（{n}手）：{' '.join(history)}\n"
        f"最近6手：{' '.join(last6)}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    txt = resp.choices[0].message.content
    try:
        data = json.loads(txt)
    except Exception:
        log.warning("GPT 非JSON：%s", txt)
        data = {"pick": "莊", "p_bank": 0.51, "p_player": 0.49, "reason": "趨勢平衡", "detail": "fallback"}

    # 數值保護與修正
    pb = float(data.get("p_bank", 0.51))
    pp = float(data.get("p_player", 0.49))
    # 調整使差距至少 0.02
    if abs(pb - pp) < 0.02:
        if pb >= pp:
            pb, pp = 0.51, 0.49
        else:
            pb, pp = 0.49, 0.51
    # 正規化到和為1
    s = pb + pp
    if s != 1:
        pb = round(pb / s, 2)
        pp = round(1 - pb, 2)
    data["p_bank"] = round(pb, 2)
    data["p_player"] = round(pp, 2)
    data["pick"] = "莊" if str(data.get("pick", "莊")).startswith("莊") else "閒"
    data["reason"] = (data.get("reason") or "綜合權重判斷")[:15]
    return data

# ====== 回覆格式（短版 reason）======
def fmt(pred: dict) -> str:
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
    hist = build_history_from_text(txt)

    # 顯示 OCR 偵測到的歷史，方便你確認
    await m.reply_text(f"📜 偵測到歷史：{' '.join(hist)}")

    context.user_data["room"] = {
        "built_at": int(time.time()),
        "history": hist,
        "last_input": None,
    }
    await m.reply_text(
        "🧩 房間數據分析完成 ✅\n🧠 GPT 混合分析模型已建立\n"
        "1️⃣ 按「莊/閒」輸入最新開獎\n2️⃣ 再按「繼續分析」預測下一局\n"
        "🔁 換房請按「停止分析」。",
        reply_markup=REPLY_KB,
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()

    if t == "開始預測":
        await update.message.reply_text(
            "✅已收到您的請求，請傳百家走勢圖\n\n"
            "⚠️注意請務必使用文財推薦平台，如有判斷失誤造成失利，後果自負！\n"
            "使用非推薦平台發現者永久停用機器人資格🚫",
            reply_markup=REPLY_KB,
        )
        return

    if t == "停止分析":
        context.user_data.pop("room", None)
        await update.message.reply_text("🧹 已清空資料，請重新上傳走勢圖。", reply_markup=REPLY_KB)
        return

    room = context.user_data.get("room")

    if t in ("莊", "閒"):
        if not room:
            await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB)
            return
        room["last_input"] = t
        await update.message.reply_text("✅ 已記錄最新開獎，請按「繼續分析」。", reply_markup=REPLY_KB)
        return

    if t == "繼續分析":
        if not room:
            await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB)
            return
        if not room.get("last_input"):
            await update.message.reply_text("請先按「莊/閒」輸入最新開獎。", reply_markup=REPLY_KB)
            return

        room["history"].append(room["last_input"])
        room["last_input"] = None

        pred = gpt_predict(room["history"])
        await update.message.reply_text(fmt(pred), reply_markup=REPLY_KB)
        return

    await update.message.reply_text("請用下方快捷鍵操作。", reply_markup=REPLY_KB)

# ====== 進入點 ======
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Webhook（Render 推薦）或 Polling（本地開發）
    if WEBHOOK_URL:
        port = int(os.environ.get("PORT", 10000))
        logging.info(f"Run webhook on 0.0.0.0:{port} -> {WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        logging.info("Run polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
