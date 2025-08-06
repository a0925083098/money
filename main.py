import os
import cv2
import numpy as np
import pytesseract
from PIL import Image
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，請上傳百家樂牌路圖片，我會幫你分析下一顆預測。")

def analyze_image(image: Image.Image) -> str:
    # 圖片轉換為 OpenCV 格式
    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    # 使用 pytesseract 辨識圖中文字
    try:
        ocr_result = pytesseract.image_to_string(cv_image, lang="eng")
    except Exception as e:
        return f"❌ 分析失敗：{str(e)}"

    # 判斷莊 or 閒（簡單紅藍像素比例）
    hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)
    red_mask = cv2.inRange(hsv, (0, 70, 50), (10, 255, 255))
    blue_mask = cv2.inRange(hsv, (100, 70, 50), (140, 255, 255))

    red_area = np.sum(red_mask > 0)
    blue_area = np.sum(blue_mask > 0)

    total = red_area + blue_area
    if total == 0:
        return "❌ 無法辨識顏色，請傳清晰的牌路圖片。"

    red_ratio = red_area / total
    blue_ratio = blue_area / total

    if red_ratio > blue_ratio:
        predict = "莊"
        win_rate = f"莊 {red_ratio*100:.1f}%、閒 {blue_ratio*100:.1f}%"
        strategy = "根據目前紅色面積較多，預測莊勝。"
    else:
        predict = "閒"
        win_rate = f"閒 {blue_ratio*100:.1f}%、莊 {red_ratio*100:.1f}%"
        strategy = "根據目前藍色面積較多，預測閒勝。"

    return f"""✅ 預測：{predict}
📊 勝率：{win_rate}
🧠 策略分析：{strategy}"""

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片接收中，開始分析...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        image = Image.open(BytesIO(photo_bytes))

        result = analyze_image(image)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"❌ 分析失敗：{str(e)}")

# 啟動機器人
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
