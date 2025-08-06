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

    recent_trend = recent[-3:]
    last = recent[-1]
    second_last = recent[-2]
    third_last = recent[-3]

    long_streak = (last == second_last == third_last)
    red_bias = red_count > blue_count + 2
    blue_bias = blue_count > red_count + 2

    # 預測邏輯
    if long_streak:
        predict = last
        reason = "根據當前連續趨勢，預測延續同方。"

    elif red_bias and count_banker > count_player:
        predict = "莊"
        reason = "多路偏紅且主路莊方占優，預測莊方延續。"

    elif blue_bias and count_player > count_banker:
        predict = "閒"
        reason = "副路偏藍且閒方近期增強，預測轉向閒方。"

    elif abs(red_count - blue_count) <= 2:
        predict = last
        reason = "路單紅藍接近，預測延續最近趨勢。"

    else:
        predict = last
        reason = "走勢無明顯規律，選擇觀望或延續最近一顆。"

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

        # 判斷勝率中哪個高
        banker_percent = float(rate_text.split("莊")[1].split("%")[0].strip())
        player_percent = float(rate_text.split("閒")[1].split("%")[0].strip())

        # 若預測與勝率相反 → 顯示提醒
        note = ""
        if (prediction == "莊" and player_percent > banker_percent) or \
           (prediction == "閒" and banker_percent > player_percent):
            note = "\n⚠️ 預測與總勝率方向不同，代表策略預測走勢反轉或續勢。"

        reply = (
            f"✅ 預測：{prediction}\n"
            f"📊 勝率：{rate_text}\n"
            f"🧠 統合分析：{reason}{note}"
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
