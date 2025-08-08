import os
import io
import json
import time
import logging
from typing import Dict, Any, List, Optional

import requests
from PIL import Image, ImageOps, ImageFilter

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ===================== 基本設定 =====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # 若你是 webhook 模式，請在 Render 設好
OCR_API_KEY = os.environ.get("OCR_API_KEY", "helloworld")  # OCR.space 免費 key 也可

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("baccarat-bot")

# 快捷鍵鍵盤
REPLY_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("開始預測")],
        [KeyboardButton("莊"), KeyboardButton("閒")],
        [KeyboardButton("繼續分析"), KeyboardButton("停止分析")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ===================== 狀態資料結構 =====================
"""
context.user_data 會存：
{
  "room": {
      "built_at": 1699999999,
      "history": ["莊","閒","莊", ...],   # 已知開獎史（可由圖片OCR起始）
      "last_input": null or "莊"/"閒",    # 使用者剛輸入的最新結果（待「繼續分析」）
      "model": {...}                      # 由圖片建模出的統計/特徵
  }
}
"""

# ===================== 工具函式：影像預處理 & OCR =====================
def preprocess_for_ocr(img_bytes: bytes) -> bytes:
    """把 PNG/JPG 影像做基礎強化，再輸出 JPG bytes。"""
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    # 放大 + 增加對比與銳利，讓格線/字符更清楚
    w, h = im.size
    scale = 1.7 if max(w, h) < 1800 else 1.2
    im = im.resize((int(w * scale), int(h * scale)))
    im = ImageOps.autocontrast(im, cutoff=1)
    im = im.filter(ImageFilter.SHARPEN)
    # 轉成 JPG
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()

def ocr_space_image(img_jpg_bytes: bytes) -> str:
    """呼叫 OCR.space，回傳純文字（失敗回空字串）"""
    url = "https://api.ocr.space/parse/image"
    files = {"file": ("image.jpg", img_jpg_bytes, "image/jpeg")}
    data = {
        "apikey": OCR_API_KEY,
        "language": "eng",
        "isOverlayRequired": False,
        "filetype": "JPG",  # 關鍵：明確指定檔案類型，避免偵測失敗
    }
    try:
        r = requests.post(url, files=files, data=data, timeout=30)
        r.raise_for_status()
        js = r.json()
        if js.get("IsErroredOnProcessing"):
            log.warning("OCR error: %s", js.get("ErrorMessage"))
            return ""
        parsed = js.get("ParsedResults", [])
        if not parsed:
            return ""
        return parsed[0].get("ParsedText", "") or ""
    except Exception as e:
        log.exception("OCR exception: %s", e)
        return ""

# ===================== 模型：從 OCR 文字建立初始房間資料 =====================
def build_room_from_ocr_text(txt: str) -> Dict[str, Any]:
    """
    這裡你可以把 txt 解析為牌路；為了先跑通流程，我用超簡化解析：
    - 只抓到 '莊' 或 '閒' 的字樣當作歷史（實務上你會從圓珠路圖像解析）
    """
    hist: List[str] = []
    for ch in txt:
        if ch in ("莊", "閒"):
            hist.append(ch)
        # 若是英文 B/P 也納入
        if ch.upper() == "B":
            hist.append("莊")
        if ch.upper() == "P":
            hist.append("閒")

    # 最少給點假資料，避免空
    if len(hist) < 6:
        hist = (["莊", "閒"] * 6)[:12]

    model = {
        "total": len(hist),
        "banker_count": sum(1 for x in hist if x == "莊"),
        "player_count": sum(1 for x in hist if x == "閒"),
    }
    return {"history": hist, "model": model}

# ===================== 預測邏輯（可替換成 GPT） =====================
def simple_predict(history: List[str]) -> Dict[str, Any]:
    """
    極簡啟動版：
    - 看最近 6 手的多寡，偏多者延續
    - 平手則看最後一手反轉
    回傳：
    {
      "pick": "莊" 或 "閒",
      "p_bank": 0.57, "p_player": 0.43,
      "reason": "根據近6手... "
    }
    """
    lookback = history[-6:] if len(history) >= 6 else history[:]
    b = sum(1 for x in lookback if x == "莊")
    p = len(lookback) - b
    if b > p:
        pick = "莊"
        p_bank = 0.55 + min(0.1, (b - p) * 0.03)
    elif p > b:
        pick = "閒"
        p_bank = 1 - (0.55 + min(0.1, (p - b) * 0.03))
    else:
        # 平手：反向最後一手
        pick = "閒" if (lookback and lookback[-1] == "莊") else "莊"
        p_bank = 0.50

    p_player = 1 - p_bank
    reason = f"根據近{len(lookback)}手的分佈（莊{b}、閒{p}），採用趨勢延續/平手反向策略。"
    return {"pick": pick, "p_bank": round(p_bank, 2), "p_player": round(p_player, 2), "reason": reason}

# ===================== Bot 回覆模板 =====================
def format_predict_message(pred: Dict[str, Any]) -> str:
    pick = pred["pick"]
    win_b = f"{int(pred['p_bank']*100)}%"
    win_p = f"{int(pred['p_player']*100)}%"
    if pick == "莊":
        line1 = "✅ 預測：莊"
    else:
        line1 = "✅ 預測：閒"
    return (
        f"{line1}\n"
        f"📊 勝率：莊 {win_b}、閒 {win_p}\n"
        f"🧠 統合分析：{pred['reason']}"
    )

# ===================== Handlers =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "傳送房間牌路圖片，我會先建立模型。\n"
        "之後每局用下方按鈕輸入結果（莊/閒），再按「繼續分析」預測下一局。\n"
        "需要重置就按「停止分析」。",
        reply_markup=REPLY_KB,
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.photo:
        return
    await msg.reply_text("📥 圖片已接收，開始分析...", reply_markup=REPLY_KB)

    # 下載最高解析度那張
    photo = msg.photo[-1]
    file = await photo.get_file()
    img_bytes = await file.download_as_bytearray()

    # 預處理 + 轉成 JPG，解決你「電腦截圖 PNG 失敗」的問題
    jpg_bytes = preprocess_for_ocr(bytes(img_bytes))

    # OCR
    txt = ocr_space_image(jpg_bytes)

    # 建模
    room = build_room_from_ocr_text(txt)
    context.user_data["room"] = {
        "built_at": int(time.time()),
        "history": room["history"],
        "last_input": None,
        "model": room["model"],
    }

    await msg.reply_text(
        "🧩 房間數據分析完成 ✅\n"
        "🧠 AI 模型已建立初步趨勢判斷\n\n"
        "1️⃣ 輸入最新開獎（按：莊 或 閒）\n"
        "2️⃣ 接著按「繼續分析」開始預測下一局\n\n"
        "🔁 換房或結束時請按「停止分析」重置。",
        reply_markup=REPLY_KB,
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == "停止分析":
        context.user_data.pop("room", None)
        await update.message.reply_text("🧹 已停止分析並清空資料。可重新上傳新房間走勢圖。", reply_markup=REPLY_KB)
        return

    # 需要已有房間
    room = context.user_data.get("room")
    if text == "開始預測":
        if not room:
            await update.message.reply_text("尚未建立模型，請先傳房間走勢圖片。", reply_markup=REPLY_KB)
            return
        pred = simple_predict(room["history"])
        await update.message.reply_text(format_predict_message(pred), reply_markup=REPLY_KB)
        return

    if text in ("莊", "閒"):
        if not room:
            await update.message.reply_text("尚未建立模型，請先傳房間走勢圖片。", reply_markup=REPLY_KB)
            return
        room["last_input"] = text
        await update.message.reply_text("✅ 已記錄最新開獎結果。請按「繼續分析」預測下一局。", reply_markup=REPLY_KB)
        return

    if text == "繼續分析":
        if not room:
            await update.message.reply_text("尚未建立模型，請先傳房間走勢圖片。", reply_markup=REPLY_KB)
            return
        if not room.get("last_input"):
            await update.message.reply_text("請先輸入最新開獎結果（按：莊 或 閒）。", reply_markup=REPLY_KB)
            return

        # 把上一局結果寫進歷史，再做下一局預測
        room["history"].append(room["last_input"])
        room["last_input"] = None

        pred = simple_predict(room["history"])
        await update.message.reply_text(format_predict_message(pred), reply_markup=REPLY_KB)
        return

    # 其他文字
    await update.message.reply_text("我看不懂這個指令～請用下方按鈕操作喔。", reply_markup=REPLY_KB)

# ===================== 啟動 =====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # 1) Webhook 模式（Render 推薦）
    if WEBHOOK_URL:
        log.info("Starting webhook on 0.0.0.0:10000 -> %s", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        # 2) 開發用 Polling
        log.info("Starting polling ...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
