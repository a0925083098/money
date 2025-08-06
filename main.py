import os
import tempfile
import cv2
import numpy as np
import openai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
openai.api_key = OPENAI_API_KEY


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片給我分析。")


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


def generate_road(columns, offset):
    road = []
    for col in range(offset, len(columns)):
        current_col = columns[col]
        prev_col = columns[col - offset]
        if len(current_col) == len(prev_col):
            road.append("紅")
        else:
            road.append("藍")
    return road


def generate_all_roads(columns):
    return {
        "大眼仔": generate_road(columns, 1),
        "小路": generate_road(columns, 2),
        "蟑螂路": generate_road(columns, 3),
    }


def summarize_history(columns, roads):
    history_text = "主路：\n"
    for col in columns:
        history_text += "".join(col) + "\n"
    history_text += "\n副路統計：\n"
    for name, road in roads.items():
        history_text += f"{name}：{''.join(road)}\n"
    return history_text


async def gpt_predict_baccarat(columns, roads):
    history = summarize_history(columns, roads)

    prompt = (
        "你是百家樂預測專家。請根據以下牌路，分析下一局可能開出『莊』或『閒』，並輸出以下格式：\n\n"
        "✅ 預測：莊 或 閒\n"
        "📊 勝率：莊 X%、閒 Y%\n"
        "🧠 統合分析：根據目前走勢與副路趨勢，進行策略判斷與說明。\n\n"
        f"牌路內容如下：\n{history}"
    )

    try:
        response = await openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ GPT 分析失敗：\n{e}"


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
        temp_image.write(image_bytes)
        temp_path = temp_image.name

    try:
        columns = analyze_baccarat_image(temp_path)
        roads = generate_all_roads(columns)
        result = await gpt_predict_baccarat(columns, roads)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析錯誤：{e}")


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_webhook(
        listen="0.0.0.0",
        port=10000,
        webhook_url=WEBHOOK_URL
    )
