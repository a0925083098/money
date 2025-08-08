import os
import tempfile
import logging
import cv2
import numpy as np
import openai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
)

# ====== 基本設定 ======
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("bot")

# ====== 小工具 ======
def _analyze_to_columns(image_path: str, cell_size=30):
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError("讀不到圖片（可能路徑錯或檔案壞掉）")
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    lower_red1 = np.array([0, 100, 100]); upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 100, 100]); upper_red2 = np.array([179, 255, 255])
    lower_blue  = np.array([100, 150, 0]); upper_blue  = np.array([140, 255, 255])
    lower_green = np.array([40, 40, 40]); upper_green = np.array([90, 255, 255])

    red_mask   = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    blue_mask  = cv2.inRange(hsv, lower_blue, upper_blue)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    def contours(mask):
        cnts = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        return [cv2.boundingRect(c) for c in cnts]

    points = []
    for (x,y,w,h) in contours(red_mask):
        points.append(("莊", x//cell_size, y//cell_size))
    for (x,y,w,h) in contours(blue_mask):
        points.append(("閒", x//cell_size, y//cell_size))
    for (x,y,w,h) in contours(green_mask):
        points.append(("和", x//cell_size, y//cell_size))

    if not points:
        return []

    max_col = max(p[1] for p in points) + 1
    max_row = max(p[2] for p in points) + 1
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]
    for label, col, row in points:
        grid[row][col] = label

    columns = []
    for c in range(max_col):
        col_vals = [grid[r][c] for r in range(max_row) if grid[r][c]]
        if col_vals:
            columns.append(col_vals)
    return columns

def _generate_road(columns, offset):
    road = []
    for c in range(offset, len(columns)):
        if len(columns[c]) == len(columns[c - offset]):
            road.append("紅")
        else:
            road.append("藍")
    return road

def _generate_all_roads(columns):
    return {
        "大眼仔": _generate_road(columns, 1),
        "小路": _generate_road(columns, 2),
        "蟑螂路": _generate_road(columns, 3),
    }

def _summarize_for_gpt(columns, roads):
    lines = ["主路："]
    for col in columns:
        lines.append("".join(col))
    lines.append("")
    lines.append("副路統計：")
    for name, r in roads.items():
        lines.append(f"{name}：{''.join(r)}")
    return "\n".join(lines)

def _fallback_brief(columns):
    flat = [x for col in columns for x in col if x in ("莊","閒")]
    b = flat.count("莊")
    p = flat.count("閒")
    total = max(1, b+p)
    b_rate = round(b/total*100,1)
    p_rate = round(p/total*100,1)
    # 簡單延續
    pred = flat[-1] if flat else "未知"
    return f"✅ 預測：{pred}\n📊 勝率：莊 {b_rate}%、閒 {p_rate}%\n🧠 統合分析：系統備援（GPT 未回覆），以最近趨勢與總體比例回覆。"

def _gpt_predict(columns, roads):
    if not OPENAI_API_KEY:
        return None, "未設定 OPENAI_API_KEY，跳過 GPT"

    prompt = (
        "你是百家樂預測專家。請根據以下牌路，分析下一局可能開出『莊』或『閒』，並輸出以下格式：\n\n"
        "✅ 預測：莊 或 閒\n"
        "📊 勝率：莊 X%、閒 Y%\n"
        "🧠 統合分析：根據目前走勢與副路趨勢，進行策略判斷與說明。\n\n"
        f"{_summarize_for_gpt(columns, roads)}"
    )
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip(), None
    except Exception as e:
        return None, str(e)

# ====== Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片（照片或檔案）給我分析。\n也可先 /ping 測試我是否在線。")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 pong（webhook 正常）")

async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 讓你確認 webhook 有沒有到達 handler
    txt = (update.message.text or "").strip()
    log.info(f"收到文字訊息：{txt}")
    await update.message.reply_text("我在，請傳圖片（或用 /ping 測試）")

async def _process_image_bytes(update: Update, image_bytes: bytes):
    await update.message.reply_text("📸 圖片已接收，開始分析…")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
        f.write(image_bytes)
        temp_path = f.name
    try:
        columns = _analyze_to_columns(temp_path)
        if not columns:
            await update.message.reply_text("⚠️ 讀不到牌路圖案，請換一張更清晰的圖片或裁掉多餘邊框。")
            return
        roads = _generate_all_roads(columns)
        gpt_text, err = _gpt_predict(columns, roads)
        if gpt_text:
            await update.message.reply_text(gpt_text)
        else:
            log.warning(f"GPT 失敗或未設定：{err}")
            await update.message.reply_text(_fallback_brief(columns))
    except Exception as e:
        log.exception("處理圖片失敗")
        await update.message.reply_text(f"⚠️ 分析錯誤：{e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        b = await file.download_as_bytearray()
        await _process_image_bytes(update, b)
    except Exception as e:
        log.exception("處理 photo 失敗")
        await update.message.reply_text(f"⚠️ 讀取照片失敗：{e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 很多人會用「檔案」傳圖，這裡也支援
    try:
        doc = update.message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await update.message.reply_text("請傳圖片檔（或用相簿上傳）。")
            return
        file = await doc.get_file()
        b = await file.download_as_bytearray()
        await _process_image_bytes(update, b)
    except Exception as e:
        log.exception("處理 document 失敗")
        await update.message.reply_text(f"⚠️ 讀取檔案失敗：{e}")

# ====== 啟動 ======
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))

    # 清掉積欠的 pending updates，避免卡住 & timeout
    app.run_webhook(
        listen="0.0.0.0",
        port=10000,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )
