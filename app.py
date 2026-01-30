import os
import logging
import asyncio
import tempfile  # Added for audio handling
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask, request
from dotenv import load_dotenv
from pydub import AudioSegment  # Added for OGA to MP3 conversion

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, 
    constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes
)
import google.generativeai as genai

# ===== Load env & logging =====
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ===== Environment & API keys =====
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
raw_keys = [os.getenv(f'GEMINI_API_KEY{suffix}') for suffix in ['', '_2', '_3']]
GEMINI_API_KEYS = [k for k in raw_keys if k]

if not TELEGRAM_TOKEN or not GEMINI_API_KEYS:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY(s)")

DEFAULT_MODEL = "gemini-1.5-flash"
BASE_URL = os.getenv('KOYEB_PUBLIC_URL', '').rstrip('/')

# ===== Data Structures =====
user_data = defaultdict(lambda: {
    'history': deque(maxlen=10), 
    'favorites': [],
    'dialect': 'standard',
    'context_mode': True 
})

DIALECT_PROMPTS = {
    'standard': 'Algerian Arabic (Darja)',
    'algiers': 'Algerian Arabic (Darja) from Algiers region',
    'oran': 'Algerian Arabic (Darja) from Oran region',
    'constantine': 'Algerian Arabic (Darja) from Constantine region'
}

def get_system_prompt(dialect='standard', context_history=None):
    dialect_desc = DIALECT_PROMPTS.get(dialect, DIALECT_PROMPTS['standard'])
    prompt = f"You are an expert translator for {dialect_desc}.\n"
    
    if context_history:
        history_list = [h['text'] for h in list(context_history)]
        prompt += f"Recent context for reference: {history_list}\n"

    prompt += """
STRICT RULES:
1. IF INPUT IS ARABIC SCRIPT -> PROVIDE FRENCH AND ENGLISH.
2. IF INPUT IS LATIN SCRIPT -> PROVIDE DARJA (ARABIC SCRIPT) AND FRENCH AND ENGLISH.
3. IF INPUT IS AUDIO -> TRANSCRIBE THE AUDIO FIRST, THEN TRANSLATE.
REQUIRED OUTPUT FORMAT:
🔤 **Original:** [transcription/text]
🇩🇿 **Darja:** [Arabic script]
🗣️ **Pronunciation:** [latin]
🇫🇷 **French:** [translation]
🇬🇧 **English:** [translation]
💡 **Note:** [Short cultural note]
"""
    return prompt

# ===== Core Functions =====
async def translate_text(text_or_file, user_id: int, is_audio=False):
    user = user_data[user_id]
    history = user['history'] if user['context_mode'] else None
    
    for key in GEMINI_API_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(
                model_name=DEFAULT_MODEL,
                system_instruction=get_system_prompt(user['dialect'], history)
            )
            
            if is_audio:
                # text_or_file is the uploaded file object here
                response = model.generate_content(["Transcribe and translate this Algerian audio.", text_or_file])
            else:
                response = model.generate_content(text_or_file)
            
            if response.candidates:
                # Update local history with the response summary
                user['history'].append({
                    'text': "Voice Message" if is_audio else text_or_file[:30],
                    'time': datetime.now().strftime('%H:%M')
                })
                return response.text
            return "⚠️ Safety filter blocked this response."
        except Exception as e:
            logger.error(f"Gemini Error: {e}")
            continue
    return "❌ Connection error with AI."

# ===== Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇩🇿 *Marhba!* I am your Darja assistant.\n\n"
        "Send text or a **voice message** to begin.", 
        parse_mode='Markdown'
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    voice = update.message.voice
    
    await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
    status_msg = await update.message.reply_text("🎤 *Processing your voice...*", parse_mode='Markdown')

    # Create temporary file paths
    with tempfile.NamedTemporaryFile(suffix='.oga', delete=False) as temp_oga:
        oga_path = temp_oga.name
    mp3_path = oga_path.replace('.oga', '.mp3')

    try:
        # Download and convert
        new_file = await context.bot.get_file(voice.file_id)
        await new_file.download_to_drive(oga_path)
        
        audio = AudioSegment.from_file(oga_path, format="ogg")
        audio.export(mp3_path, format="mp3")

        # Upload to Gemini File API
        genai.configure(api_key=GEMINI_API_KEYS[0])
        uploaded_audio = genai.upload_file(path=mp3_path, mime_type="audio/mpeg")
        
        # Translate
        result_text = await translate_text(uploaded_audio, user_id, is_audio=True)
        
        keyboard = [[InlineKeyboardButton("⭐ Save", callback_data='save_fav')]]
        await status_msg.edit_text(result_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Voice processing failed: {e}")
        await status_msg.edit_text("❌ Sorry, I couldn't process that audio.")
    
    finally:
        # Cleanup temporary files
        for path in [oga_path, mp3_path]:
            if os.path.exists(path):
                os.remove(path)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    await update.message.chat.send_action(action=constants.ChatAction.TYPING)
    status_msg = await update.message.reply_text("🕒 *Translating...*", parse_mode='Markdown')
    
    try:
        result_text = await translate_text(update.message.text, update.effective_user.id)
        keyboard = [[InlineKeyboardButton("⭐ Save", callback_data='save_fav')]]
        await status_msg.edit_text(result_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text("❌ Error processing translation.")

# ... (Keep all your other command handlers: help, history, save, dialect, etc. here) ...

# ===== PTB Application Setup =====
ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()

ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("history", history_command))
ptb_app.add_handler(CommandHandler("save", save_command))
ptb_app.add_handler(CommandHandler("saved", saved_command))
ptb_app.add_handler(CommandHandler("dialect", set_dialect))

ptb_app.add_handler(CallbackQueryHandler(dialect_callback, pattern="^dial_"))
ptb_app.add_handler(CallbackQueryHandler(save_callback, pattern="^save_fav$"))
ptb_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "OK", 200

async def setup_commands(app):
    commands = [
        BotCommand("start", "Restart the bot"),
        BotCommand("help", "How to use & list commands"),
        BotCommand("dialect", "Change region/dialect"),
        BotCommand("history", "Show recent translations"),
        BotCommand("saved", "View bookmarks"),
        BotCommand("save", "Bookmark a translation (reply to it)")
    ]
    await app.bot.set_my_commands(commands)

def main():
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi
    port = int(os.environ.get("PORT", 8080))
    asgi_app = WsgiToAsgi(flask_app)

    async def run():
        async with ptb_app:
            await ptb_app.start()
            await setup_commands(ptb_app)
            
            if BASE_URL:
                await ptb_app.bot.set_webhook(url=f"{BASE_URL}/webhook")
                logger.info(f"🚀 Webhook: {BASE_URL}/webhook")
            
            config = uvicorn.Config(app=asgi_app, host="0.0.0.0", port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
            await ptb_app.stop()

    async def main_async():
        await run()

    asyncio.run(main_async())

if __name__ == '__main__':
    main()
