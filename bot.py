import os
import asyncio
from PIL import Image, ImageFilter
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# --------- Fix for Python 3.14+: ensure an event loop exists ----------
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
# --------------------------------------------------------------------

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
TEMPLATE_PATH = "scout_ramdan.png"

WELCOME_TEXT = (
    "✨ أهلاً بك!\n\n"
    "📸 ابعثلي صورة (بورتريه أو لاندسكيب) وأنا نركّبها تلقائيًا داخل القالب "
    "ونرجعلك الصورة النهائية.\n\n"
    "✅ فقط أرسل الصورة هنا."
)

HELP_TEXT = (
    "طريقة الاستعمال بسيطة:\n"
    "1) ابعث صورة\n"
    "2) استنى ثواني\n"
    "3) توصلك الصورة النهائية بالقالب ✅"
)

WAIT_TEXT = "⏳ وصلتني الصورة… راني نخدم عليها الآن، شوية برك!"

ERROR_TEXT = "❌ صرا خطأ أثناء المعالجة. جرّب صورة أخرى أو عاود بعد شوية."

# ---------- Image helpers ----------
def center_crop_to_aspect(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    قصّ ذكي من الوسط باش نطابق Ratio تاع القالب بدون تشويه (يدعم طول/عرض).
    """
    iw, ih = img.size
    target_ratio = target_w / target_h
    img_ratio = iw / ih

    if img_ratio > target_ratio:
        # الصورة واسعة: نقص من الجوانب
        new_w = int(ih * target_ratio)
        left = (iw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ih))
    else:
        # الصورة طويلة: نقص من فوق/تحت
        new_h = int(iw / target_ratio)
        top = (ih - new_h) // 2
        img = img.crop((0, top, iw, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)

def build_mask_from_template(template_rgba: Image.Image, threshold: int = 25) -> Image.Image:
    """
    نخرج Mask تاع المنطقة السوداء (المحراب).
    أي بكسل قريب للسواد (R,G,B <= threshold) يتحسب ضمن الماسك.
    """
    rgb = template_rgba.convert("RGB")
    w, h = rgb.size

    mask = Image.new("L", (w, h), 0)
    src = list(rgb.getdata())
    out = []

    for (r, g, b) in src:
        if r <= threshold and g <= threshold and b <= threshold:
            out.append(255)
        else:
            out.append(0)

    mask.putdata(out)
    # نعومة خفيفة للحواف
    mask = mask.filter(ImageFilter.GaussianBlur(radius=1.2))
    return mask
    
def compose_with_template(user_img_path: str) -> str:
    """
    1) نقصّ صورة المستخدم قص ذكي على مقاس القالب
    2) نصنع hole في القالب في مكان الأسود (يولي شفاف)
    3) نركّب القالب فوق صورة المستخدم ونخرج JPG
    """
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    tw, th = template.size

    # صورة المستخدم: قص ذكي (بالطول/بالعرض) بدون تشويه
    user = Image.open(user_img_path).convert("RGB")
    user = center_crop_to_aspect(user, tw, th).convert("RGBA")

    # ماسك المنطقة السوداء
    hole_mask = build_mask_from_template(template, threshold=25)

    # نخلي القالب "مخروم" (شفاف) في المنطقة السوداء
    r, g, b, a = template.split()
    zero = Image.new("L", template.size, 0)
    new_alpha = Image.composite(zero, a, hole_mask)  # أين الماسك أبيض => alpha=0
    template_hole = Image.merge("RGBA", (r, g, b, new_alpha))

    # دمج نهائي: صورة المستخدم تحت + القالب فوق
    final = Image.alpha_composite(user, template_hole).convert("RGB")

    out_path = user_img_path.replace("_in.jpg", "_out.jpg")
    final.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
    
# ---------- Telegram handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return

    # رسالة انتظار + “يكتب…”
    await update.message.reply_text(WAIT_TEXT)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)

    try:
        os.makedirs("tmp", exist_ok=True)
        msg_id = update.message.message_id

        in_path = os.path.join("tmp", f"{msg_id}_in.jpg")

        # تحميل الصورة
        photo = update.message.photo[-1]  # أعلى دقة
        tg_file = await photo.get_file()
        await tg_file.download_to_drive(in_path)

        # تركيب
        out_path = compose_with_template(in_path)

        # إرسال النتيجة
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
        with open(out_path, "rb") as f:
            await update.message.reply_photo(photo=f, caption="✅ تفضل صورتك بالقالب!")

        # تنظيف
        try:
            os.remove(in_path)
            os.remove(out_path)
        except:
            pass

    except Exception:
        await update.message.reply_text(ERROR_TEXT)

async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # إذا بعث نص/ملف/ستيكر… نوجهوه بلطف
    await update.message.reply_text("📌 ابعث صورة فقط باش نركّبها داخل القالب ✅")

def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN ناقص. ضيفه في Environment Variables في Render.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO, handle_non_photo))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()


