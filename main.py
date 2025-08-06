import os
import pytesseract
from PIL import Image
from io import BytesIO
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# /start 指令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳一張牌路圖片給我，我會幫你分析下一顆可能開什麼。")

# 處理圖片訊息
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📷 圖片已接收，開始分析...")

    try:
        # 下載圖片
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        image = Image.open(BytesIO(photo_bytes))

        # OCR 辨識圖片文字
        text = pytesseract.image_to_string(image, lang='eng+chi_sim')
        text = text.upper()  # 統一大寫方便判斷

        # 模擬預測邏輯
        count_banker = text.count("莊") + text.count("B")
        count_player = text.count("閒") + text.count("P")

        if count_banker > count_player:
            prediction = "莊"
            win_rate = "莊 53.0%、閒 47.0%"
            strategy = "根據當前連續趨勢，預測延續同方。"
        elif count_player > count_banker:
            prediction = "閒"
            win_rate = "閒 53.0%、莊 47.0%"
            strategy = "根據當前反轉模式，預測轉換對方。"
        else:
            prediction = "未知"
            win_rate = "莊 50%、閒 50%"
            strategy = "無法辨識趨勢，建議觀望。"

        # 回覆結果
        result = f"""✅ 預測：{prediction}
📊 勝率：{win_rate}
🧠 策略分析：{strategy}"""
        await update.message.reply_text(result)

    except Exception as e:
        await update.message.reply_text(f"❌ 分析失敗：{str(e)}")

# 建立 Telegram App
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# Webhook 模式啟動
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
