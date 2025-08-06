import os
import tempfile
import uuid
import requests
import cv2
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# ➤ 指令 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片給我分析。")

# ➤ 智能預測策略邏輯
def predict_next(columns):
    flat = [x for col in columns for x in col]
    recent = flat[-6:]

    if len(recent) < 3:
        return "無法預測"

    # 三連一樣 → 預測延續
    if recent[-1] == recent[-2] == recent[-3]:
        return recent[-1]

    # 雙跳 → 預測對稱延續
    if recent[-4:] == ['莊', '閒', '莊', '閒']:
        return '閒'
    if recent[-4:] == ['閒', '莊', '閒', '莊']:
        return '莊'

    # 最近兩顆不同 → 預測換邊
    if recent[-1] != recent[-2]:
        return recent[-1]

    # 其他情況 → 跟最後一顆
    return recent[-1]

# ➤ 傳圖片觸發
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
        temp_image.write(image_bytes)
        temp_path = temp_image.name

    try:
        result = analyze_baccarat_image(temp_path)

        if not result:
            await update.message.reply_text("❌ 分析失敗，請確認圖片清晰並為牌路圖。")
            return

        # 預測下一顆
        next_prediction = predict_next(result)

        # 計算莊/閒勝率
        flat = [x for col in result for x in col]
        banker_count = flat.count("莊")
        player_count = flat.count("閒")
        total = banker_count + player_count
        if total == 0:
            banker_rate = player_rate = 50.0
        else:
            banker_rate = round(banker_count / total * 100, 1)
            player_rate = round(player_count / total * 100, 1)

        reply = (
            f"✅ 預測：{next_prediction}\n"
            f"📊 勝率：莊 {banker_rate}%、閒 {player_rate}%\n"
            f"🧠 策略分析：根據近期牌路規則預測下一顆。"
        )
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析時發生錯誤：{e}")

# ➤ 圖片辨識牌路函數
def analyze_baccarat_image(image_path: str, cell_size=30):
    image = cv2.imread(image_path)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    lower_red1 = np.array([0, 100, 100])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 100, 100])
    upper_red2 = np.array([179, 255, 255])
    lower_blue = np.array([100, 150, 0])
    upper_blue = np.array([140, 255, 255])
    lower_green = np.array([40, 40, 40])
    upper_green = np.array([90, 255, 255])

    red_mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    contours_red = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contours_blue = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contours_green = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]

    points = []

    def process_contours(contours, label):
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            col = x // cell_size
            row = y // cell_size
            points.append((label, col, row))

    process_contours(contours_red, '莊')
    process_contours(contours_blue, '閒')
    process_contours(contours_green, '和')

    max_col = max([p[1] for p in points], default=0) + 1
    max_row = max([p[2] for p in points], default=0) + 1
    grid = [['' for _ in range(max_col)] for _ in range(max_row)]

    for label, col, row in points:
        grid[row][col] = label

    columns = []
    for col in range(max_col):
        column = []
        for row in range(max_row):
            if grid[row][col]:
                column.append(grid[row][col])
        if column:
            columns.append(column)

    return columns

# ➤ 機器人啟動（Webhook 模式）
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
