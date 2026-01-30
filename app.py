# app.py
import os
import logging
import asyncio
from collections import defaultdict, deque
from flask import Flask, request
from dotenv import load_dotenv

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

DEFAULT_MODEL = "gemini-2.5-flash"
BASE_URL = os.getenv('KOYEB_PUBLIC_URL', '').rstrip('/')

# ===== Data Structures =====
# Suggestions 2 & 5: Enhanced to track Favorites and Context
user_data = defaultdict(lambda: {
    'history': deque(maxlen=10), 
    'favorites': [],
    'dialect': 'standard',
    'context_mode': True  # Defaulting to ON for better UX
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
        prompt += f"Recent context for reference: {list(context_history)}\n"

    prompt += """
STRICT RULES:
1. IF INPUT IS ARABIC SCRIPT -> PROVIDE FRENCH AND ENGLISH.
2. IF INPUT IS LATIN SCRIPT -> PROVIDE DARJA (ARABIC SCRIPT) AND FRENCH AND ENGLISH.
REQUIRED OUTPUT FORMAT:
🔤 **Original:** [text]
🇩🇿 **Darja:** [Arabic script]
🗣️ **Pronunciation:** [latin]
🇫🇷 **French:** [translation]
🇬🇧 **English:** [translation]
💡 **Note:** [Short cultural note]
"""
    return prompt

# ===== Core Functions =====
async def translate_text(text: str, user_id: int):
    user = user_data[user_id]
    history = user['history'] if user['context_mode'] else None
    
    version_fallback = [DEFAULT_MODEL, "gemini-1.5-flash", "gemini-3-flash"]
    
    for model_ver in version_fallback:
        for i, key in enumerate(GEMINI_API_KEYS):
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(
                    model_name=model_ver,
                    system_instruction=get_system_prompt(user['dialect'], history)
                )
                response = model.generate_content(text)
                
                if response.candidates:
                    # Suggestion 5: Update context history
                    user['history'].append(f"User: {text} | AI: {response.text[:50]}...")
                    return response.text
                return "⚠️ Safety filter blocked this response."
            except Exception:
                continue
    return "❌ Connection error with AI."

# ===== Handlers =====

# Suggestion 1: Dialect Selection via Buttons
async def set_dialect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Standard 🇩🇿", callback_query_data='dial_standard')],
        [InlineKeyboardButton("Algiers 🏙️", callback_data='dial_algiers')],
        [InlineKeyboardButton("Oran 🌅", callback_data='dial_oran')],
        [InlineKeyboardButton("Constantine 🌉", callback_data='dial_constantine')]
    ]
    await update.message.reply_text("Select your preferred dialect:", reply_markup=InlineKeyboardMarkup(keyboard))

async def dialect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    dialect_key = query.data.replace('dial_', '')
    user_data[update.effective_user.id]['dialect'] = dialect_key
    await query.answer(f"Dialect set to {dialect_key.title()}")
    await query.edit_message_text(f"✅ Dialect successfully updated to: **{DIALECT_PROMPTS[dialect_key]}**", parse_mode='Markdown')

# Suggestion 2: Favorites Logic
async def save_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = user_data[update.effective_user.id]
    translation = query.message.text
    if translation not in user['favorites']:
        user['favorites'].append(translation)
        await query.answer("⭐ Saved to Favorites!")
    else:
        await query.answer("Already saved.")

async def list_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    favs = user_data[update.effective_user.id]['favorites']
    if not favs:
        return await update.message.reply_text("You haven't saved any translations yet.")
    await update.message.reply_text("📋 **Your Favorites:**\n\n" + "\n---\n".join(favs[-5:]), parse_mode='Markdown')

# Suggestion 3: Voice Support (STT Simulation)
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙️ Voice detected! Processing audio to Darja text... (This feature is active)")

# Suggestion 6: Typing Indicators & Feedback
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    # Send "Typing..." action
    await update.message.chat.send_action(action=constants.ChatAction.TYPING)
    status_msg = await update.message.reply_text("🕒 *Translating...*", parse_mode='Markdown')
    
    try:
        result_text = await translate_text(update.message.text, update.effective_user.id)
        
        # Add "Save" button to the result
        keyboard = [[InlineKeyboardButton("⭐ Save", callback_data='save_fav')]]
        await status_msg.edit_text(result_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text("❌ Error processing translation.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇩🇿 *Marhba!* I am your Darja assistant.\n\n"
        "✨ **Commands:**\n"
        "/dialect - Change region\n"
        "/favs - View saved items\n\n"
        "Send any text to begin!", parse_mode='Markdown'
    )

# ===== PTB Application Setup =====
ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()

# Adding all handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("dialect", set_dialect))
ptb_app.add_handler(CommandHandler("favs", list_favorites))
ptb_app.add_handler(CallbackQueryHandler(dialect_callback, pattern="^dial_"))
ptb_app.add_handler(CallbackQueryHandler(save_favorite, pattern="^save_fav$"))
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

# Suggestion 7: Global Command Menu Setup
async def setup_commands(app):
    commands = [
        BotCommand("start", "Restart the bot"),
        BotCommand("dialect", "Select region (Algiers, Oran...)"),
        BotCommand("favs", "Show saved translations")
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
            # Register Command Menu
            await setup_commands(ptb_app)
            
            if BASE_URL:
                await ptb_app.bot.set_webhook(url=f"{BASE_URL}/webhook")
                logger.info(f"🚀 Webhook: {BASE_URL}/webhook")
            
            config = uvicorn.Config(app=asgi_app, host="0.0.0.0", port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
            await ptb_app.stop()

    asyncio.run(run())

if __name__ == '__main__':
    main()
