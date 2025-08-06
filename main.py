import os
import tempfile
import uuid
import cv2
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]


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


def get_prediction(columns, roads):
    flat = [x for col in columns for x in col]
    recent = flat[-6:]
    if len(recent) < 3:
        return "未知", "路單過少無法預測", "走勢無明顯規律，選擇觀望。"

    count_banker = flat.count("莊")
    count_player = flat.count("閒")
    total = count_banker + count_player
    banker_rate = round(count_banker / total * 100, 1) if total else 50.0
    player_rate = round(count_player / total * 100, 1) if total else 50.0

    red_count = 0
    blue_count = 0
    for road in roads.values():
        red_count += road.count("紅")
        blue_count += road.count("藍")

    # 統合邏輯
    if recent[-1] == recent[-2] == recent[-3]:
        predict = recent[-1]
        reason = "根據當前連續趨勢，預測延續同方。"
    elif red_count > blue_count + 2:
        predict = "莊"
        reason = "多路一致偏紅，推測莊方延續優勢。"
    elif blue_count > red_count + 2:
        predict = "閒"
        reason = "副路偏藍且轉折頻繁，預測主方轉變。"
    else:
        predict = recent[-1]
        reason = "路單分歧，建議觀望等待明確方向。"

    return predict, f"莊 {banker_rate}%、閒 {player_rate}%", reason


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
        prediction, rate_text, reason = get_prediction(columns, roads)

        reply = (
            f"✅ 預測：{prediction}\n"
            f"📊 勝率：{rate_text}\n"
            f"🧠 統合分析：{reason}"
        )
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析錯誤：{e}")


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
