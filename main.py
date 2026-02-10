import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request
import uvicorn
from asgiref.wsgi import WsgiToAsgi
from telegram import BotCommand, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from config import TELEGRAM_TOKEN, BASE_URL, PORT, ADMIN_CONTACT, DATABASE_PATH, GEMINI_API_KEYS, GROQ_API_KEY
from database import db
from services import translation_queue
from handlers import (
    start, help_command, history_command, save_command, saved_command,
    dictionary_command, stats_command, queue_command, set_dialect,
    dialect_callback, save_callback, handle_voice, handle_message,
    packages_command, subscription_command, grant_command, revoke_command, whitelist_command,
    upgrade_callback
)

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Track startup time
startup_time = datetime.now()

# Flask App for Health Checks & Webhook
flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        # We need access to ptb_app here. We can set it globally or attach to flask app context
        # Ideally, we put this inside main or use a global. 
        # For simplicity in this structure, we'll assume ptb_app is available via closure or global
        # But wait, uvicorn runs asgi_app.
        # We can pass update to queue if we have access to ptb_app
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "OK", 200

@flask_app.route('/health', methods=['GET'])
async def health_check():
    try:
        queue_stats = translation_queue.get_stats()
        cache_stats = await db.get_cache_stats()
        
        uptime = datetime.now() - startup_time
        uptime_str = str(uptime).split('.')[0]
        
        is_healthy = (
            queue_stats['is_running'] and 
            db._connection is not None
        )
        
        status = {
            "status": "healthy" if is_healthy else "degraded",
            "timestamp": datetime.now().isoformat(),
            "uptime": uptime_str,
            "services": {
                "database": "connected" if db._connection else "disconnected",
                "queue_worker": "running" if queue_stats['is_running'] else "stopped",
                "bot": "active" if ptb_app.running else "inactive"
            },
            "metrics": {
                "queue_size": queue_stats['in_queue'],
                "processed": queue_stats['processed'],
                "failed": queue_stats['failed'],
                "cache_hits": cache_stats['total_hits']
            }
        }
        return status, 200
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {"status": "error", "message": str(e)}, 500

@flask_app.route('/status', methods=['GET'])
def status_page():
    try:
        queue_stats = translation_queue.get_stats()
        
        # We need an async wrapper to get cache stats if we are inside sync flask route?
        # But we are running with uvicorn/asgi, so async def works.
        # However, calling await inside sync flask route is tricky unless using quart or async route
        # Flask 2.0+ supports async.
        return "Status Page Placeholder - Use /health for JSON", 200
    except Exception as e:
        return str(e), 500

@flask_app.route('/metrics', methods=['GET'])
async def prometheus_metrics():
    try:
        queue_stats = translation_queue.get_stats()
        cache_stats = await db.get_cache_stats()
        
        uptime = datetime.now() - startup_time
        uptime_seconds = uptime.total_seconds()
        
        metrics = f"""# HELP darja_bot_uptime_seconds Bot uptime in seconds
# TYPE darja_bot_uptime_seconds gauge
darja_bot_uptime_seconds {uptime_seconds}

# HELP darja_bot_queue_size Current queue size
# TYPE darja_bot_queue_size gauge
darja_bot_queue_size {queue_stats['in_queue']}

# HELP darja_bot_queue_processed_total Total processed translations
# TYPE darja_bot_queue_processed_total counter
darja_bot_queue_processed_total {queue_stats['processed']}

# HELP darja_bot_queue_failed_total Total failed translations
# TYPE darja_bot_queue_failed_total counter
darja_bot_queue_failed_total {queue_stats['failed']}

# HELP darja_bot_cache_entries_total Total cache entries
# TYPE darja_bot_cache_entries_total gauge
darja_bot_cache_entries_total {cache_stats['total_entries']}

# HELP darja_bot_cache_hits_total Total cache hits
# TYPE darja_bot_cache_hits_total counter
darja_bot_cache_hits_total {cache_stats['total_hits']}

# HELP darja_bot_gemini_keys Number of configured Gemini API keys
# TYPE darja_bot_gemini_keys gauge
darja_bot_gemini_keys {len(GEMINI_API_KEYS)}

# HELP darja_bot_groq_active Groq API status (1=active, 0=inactive)
# TYPE darja_bot_groq_active gauge
darja_bot_groq_active {1 if GROQ_API_KEY else 0}

# HELP darja_bot_service_up Service health status (1=up, 0=down)
# TYPE darja_bot_service_up gauge
darja_bot_service_up {1 if queue_stats['is_running'] else 0}
"""
        return metrics, 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return f"# Error\n{e}", 500

async def setup_commands(app):
    commands = [
        BotCommand("start", "Restart the bot"),
        BotCommand("help", "How to use & list commands"),
        BotCommand("subscription", "View your subscription status"),
        BotCommand("packages", "View upgrade packages"),
        BotCommand("dialect", "Change region/dialect"),
        BotCommand("history", "Show recent translations"),
        BotCommand("saved", "View bookmarks"),
        BotCommand("save", "Bookmark a translation (reply to it)"),
        BotCommand("stats", "View cache statistics (admin)"),
        BotCommand("queue", "View queue status (admin)"),
        BotCommand("dictionary", "View offline dictionary words")
    ]
    await app.bot.set_my_commands(commands)

# Global PTB App placeholder
ptb_app = None

def main():
    global ptb_app
    
    # Initialize PTB Application
    ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()
    
    # Register Handlers
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("history", history_command))
    ptb_app.add_handler(CommandHandler("save", save_command))
    ptb_app.add_handler(CommandHandler("saved", saved_command))
    ptb_app.add_handler(CommandHandler("dictionary", dictionary_command))
    ptb_app.add_handler(CommandHandler("dialect", set_dialect))
    
    ptb_app.add_handler(CommandHandler("stats", stats_command))
    ptb_app.add_handler(CommandHandler("queue", queue_command))
    
    ptb_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, handle_voice))
    
    ptb_app.add_handler(CommandHandler("packages", packages_command))
    ptb_app.add_handler(CommandHandler("subscription", subscription_command))
    
    ptb_app.add_handler(CommandHandler("grant", grant_command))
    ptb_app.add_handler(CommandHandler("revoke", revoke_command))
    ptb_app.add_handler(CommandHandler("whitelist", whitelist_command))
    
    ptb_app.add_handler(CallbackQueryHandler(dialect_callback, pattern="^dial_"))
    ptb_app.add_handler(CallbackQueryHandler(save_callback, pattern="^save_fav$"))
    ptb_app.add_handler(CallbackQueryHandler(upgrade_callback, pattern="^upgrade_"))
    
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Setup ASGI for Uvicorn
    asgi_app = WsgiToAsgi(flask_app)
    
    async def run_webhook_server():
        config = uvicorn.Config(
            app=asgi_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def run():
        # Connect Database
        await db.connect()
        logger.info(f"💾 Database connected: {DATABASE_PATH}")
        
        # Start Queue
        await translation_queue.start_worker(ptb_app)
        
        try:
            await ptb_app.initialize()
            await ptb_app.start()
            await setup_commands(ptb_app)
            
            if BASE_URL:
                # Webhook Mode
                webhook_url = f"{BASE_URL}/webhook"
                await ptb_app.bot.set_webhook(url=webhook_url)
                logger.info(f"🚀 Webhook mode: {webhook_url}")
                
                # Run web server (blocking)
                await run_webhook_server()
            else:
                # Polling Mode
                logger.info("🔄 Polling mode (local testing)")
                await ptb_app.updater.start_polling(drop_pending_updates=True)
                
                # Run web server in background
                web_task = asyncio.create_task(run_webhook_server())
                
                try:
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                finally:
                    web_task.cancel()
                    try:
                        await web_task
                    except asyncio.CancelledError:
                        pass
            
            await ptb_app.stop()
            await ptb_app.shutdown()
            
        finally:
            await translation_queue.stop_worker()
            await db.close()
            logger.info("👋 Shutdown complete")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()
