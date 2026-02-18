import os
from PIL import Image
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get("BOT_TOKEN")
TEMPLATE_PATH = "scout_ramdan.png"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()

    os.makedirs("tmp", exist_ok=True)
    user_path = "tmp/user.jpg"
    result_path = "tmp/result.jpg"

    await file.download_to_drive(user_path)

    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    user_img = Image.open(user_path).convert("RGBA")

    # Resize user image to fit template
    user_img = user_img.resize(template.size)

    # Paste user image
    combined = Image.alpha_composite(user_img, template)

    combined = combined.convert("RGB")
    combined.save(result_path, "JPEG", quality=95)

    await update.message.reply_photo(photo=open(result_path, "rb"))

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.run_polling()