import os, io, time, logging, json
from typing import List, Tuple
import requests
from PIL import Image, ImageOps, ImageFilter
import numpy as np
import cv2
from openai import OpenAI

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ====== Env ======
BOT_TOKEN       = os.environ["BOT_TOKEN"]
WEBHOOK_URL     = os.environ.get("WEBHOOK_URL")
OCR_API_KEY     = os.environ.get("OCR_API_KEY", "helloworld")
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("baccarat-bot")
client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Reply Keyboard ======
REPLY_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("開始預測")],
        [KeyboardButton("莊"), KeyboardButton("閒")],
        [KeyboardButton("繼續分析"), KeyboardButton("停止分析")],
    ], resize_keyboard=True, one_time_keyboard=False
)

# ====== OCR helpers ======
def preprocess_for_ocr(img_bytes: bytes) -> bytes:
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    scale = 1.7 if max(w, h) < 1800 else 1.2
    im = im.resize((int(w * scale), int(h * scale)))
    im = ImageOps.autocontrast(im, cutoff=1).filter(ImageFilter.SHARPEN)
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()

def ocr_space_image(img_jpg_bytes: bytes) -> str:
    url = "https://api.ocr.space/parse/image"
    files = {"file": ("image.jpg", img_jpg_bytes, "image/jpeg")}
    data = {
        "apikey": OCR_API_KEY, "language": "cht", "isOverlayRequired": False,
        "filetype": "JPG", "OCREngine": 2, "scale": True, "isTable": True,
    }
    try:
        r = requests.post(url, files=files, data=data, timeout=60)
        r.raise_for_status()
        js = r.json()
        if js.get("IsErroredOnProcessing"): return ""
        pr = js.get("ParsedResults", []);  return pr[0].get("ParsedText","") if pr else ""
    except Exception as e:
        log.exception("OCR exception: %s", e); return ""

def build_history_from_text(txt: str) -> List[str]:
    def normalize(s: str) -> str:
        out = []
        for ch in s:
            code = ord(ch)
            if 0xFF01 <= code <= 0xFF5E: ch = chr(code - 0xFEE0)
            elif code == 0x3000: ch = " "
            out.append(ch)
        return "".join(out)
    s = normalize(txt).upper().replace(" ", "")
    s = s.replace("蓝","藍").replace("靑","青").replace("閑","閒")
    hist: List[str] = []
    for ch in s:
        if ch in ("莊","庄","R","B","Z"): hist.append("莊")
        elif ch in ("閒","闲","藍","蓝","青","P","X"): hist.append("閒")
    return hist

# ====== Color-based beads detection ======
# Tunables (base on your 5 images)
ROI_BOTTOM_PCT = 0.45          # take bottom 45% of image as bead area
MIN_AREA, MAX_AREA = 20, 1800  # contour area filter
BIN_WIDTH = 22                 # px per column bin (approx grid cell width)

def crop_bead_region(img: np.ndarray) -> np.ndarray:
    h = img.shape[0]
    y0 = int(h * (1 - ROI_BOTTOM_PCT))
    return img[y0:, :]  # bottom strip

def mask_colors(hsv: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    # red (two ranges)
    red1 = cv2.inRange(hsv, (0, 90, 70), (10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 90, 70), (180, 255, 255))
    red = cv2.bitwise_or(red1, red2)
    # blue
    blue = cv2.inRange(hsv, (100, 90, 70), (135, 255, 255))
    return red, blue

def find_centers(mask: np.ndarray, label: str) -> List[Tuple[int,int,str]]:
    kernel = np.ones((3,3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts = []
    for c in cnts:
        area = cv2.contourArea(c)
        if MIN_AREA <= area <= MAX_AREA:
            M = cv2.moments(c)
            if M["m00"] != 0:
                cx = int(M["m10"]/M["m00"]); cy = int(M["m01"]/M["m00"])
                pts.append((cx, cy, label))
    return pts

def column_index(x: int, x_min: int) -> int:
    return int(round((x - x_min) / max(BIN_WIDTH, 1)))

def beads_history_from_image(img_bytes: bytes) -> List[str]:
    arr = np.frombuffer(img_bytes, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if im is None: return []

    roi = crop_bead_region(im)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red, blue = mask_colors(hsv)
    pts = find_centers(red, "莊") + find_centers(blue, "閒")
    if not pts: return []

    # normalize to ROI coords and sort into columns
    xs = [p[0] for p in pts]
    x_min = min(xs)
    cols = {}
    for x, y, lab in pts:
        col = column_index(x, x_min)
        cols.setdefault(col, []).append((x, y, lab))

    history: List[str] = []
    for col in sorted(cols.keys()):
        col_pts = sorted(cols[col], key=lambda p: p[1])  # top->bottom
        for _, _, lab in col_pts:
            history.append(lab)
    return history

# ====== GPT predict (short reason, gap>=2%) ======
def gpt_predict(history: List[str]) -> dict:
    n = len(history); last6 = history[-6:] if n >= 6 else history[:]
    prompt = (
        "你是百家樂走勢分析專家，結合【全局(60%)】與【最近6手(40%)】進行混合分析，"
        "預測下一局莊/閒與勝率。"
        "嚴格要求：勝率差至少0.02，不得50/50。只回JSON："
        "{pick:'莊或閒', p_bank:0~1, p_player:0~1, reason:'簡短中文結論', detail:'完整分析'}。"
        "reason 最多15字。p_bank+p_player=1。\n\n"
        f"全局序列（{n}手）：{' '.join(history)}\n"
        f"最近6手：{' '.join(last6)}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.3,
        messages=[{"role":"user","content":prompt}],
    )
    txt = resp.choices[0].message.content
    try:
        data = json.loads(txt)
    except Exception:
        log.warning("GPT 非JSON：%s", txt)
        data = {"pick":"莊","p_bank":0.51,"p_player":0.49,"reason":"趨勢平衡","detail":"fallback"}

    pb = float(data.get("p_bank", 0.51)); pp = float(data.get("p_player", 0.49))
    if abs(pb-pp) < 0.02:
        if pb >= pp: pb, pp = 0.51, 0.49
        else: pb, pp = 0.49, 0.51
    s = pb+pp
    if s != 1: pb = round(pb/s,2); pp = round(1-pb,2)
    return {
        "pick": "莊" if str(data.get("pick","莊")).startswith("莊") else "閒",
        "p_bank": round(pb,2),
        "p_player": round(pp,2),
        "reason": (data.get("reason") or "綜合權重判斷")[:15],
    }

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
    raw_bytes = await file.download_as_bytearray()

    # 1) 優先：色塊偵測
    hist = beads_history_from_image(bytes(raw_bytes))

    # 2) 失敗→退回 OCR
    if not hist or len(hist) < 6:
        jpg = preprocess_for_ocr(bytes(raw_bytes))
        txt = ocr_space_image(jpg)
        hist = build_history_from_text(txt)
        raw_preview = (txt[:200] + "…") if len(txt) > 200 else txt
        await m.reply_text(f"📝 OCR原文（前200字）：\n{raw_preview}")

    await m.reply_text(f"📜 偵測到歷史：{' '.join(hist) if hist else '（空）'}")

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
        ); return

    if t == "停止分析":
        context.user_data.pop("room", None)
        await update.message.reply_text("🧹 已清空資料，請重新上傳走勢圖。", reply_markup=REPLY_KB)
        return

    room = context.user_data.get("room")

    if t in ("莊","閒"):
        if not room:
            await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB); return
        room["last_input"] = t
        await update.message.reply_text("✅ 已記錄最新開獎，請按「繼續分析」。", reply_markup=REPLY_KB)
        return

    if t == "繼續分析":
        if not room:
            await update.message.reply_text("尚未建立模型，請先上傳圖片。", reply_markup=REPLY_KB); return
        if not room.get("last_input"):
            await update.message.reply_text("請先按「莊/閒」輸入最新開獎。", reply_markup=REPLY_KB); return

        room["history"].append(room["last_input"])
        room["last_input"] = None

        pred = gpt_predict(room["history"])
        await update.message.reply_text(fmt(pred), reply_markup=REPLY_KB)
        return

    await update.message.reply_text("請用下方快捷鍵操作。", reply_markup=REPLY_KB)

# ====== Entry ======
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if WEBHOOK_URL:
        port = int(os.environ.get("PORT", 10000))
        app.run_webhook(listen="0.0.0.0", port=port, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
