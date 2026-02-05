# app.py
import os
import logging
import asyncio
import subprocess
import tempfile
from datetime import datetime
from flask import Flask, request
from dotenv import load_dotenv
import aiosqlite

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, 
    constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes
)
import google.generativeai as genai
from groq import AsyncGroq

# ===== Load env & logging =====
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ===== Database Setup =====
DATABASE_PATH = os.getenv('DATABASE_PATH', 'translations.db')

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._connection = None
    
    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        await self._connection.execute('PRAGMA foreign_keys = ON')
        await self._create_tables()
    
    async def close(self):
        if self._connection:
            await self._connection.close()
    
    async def _create_tables(self):
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                dialect TEXT DEFAULT 'standard',
                context_mode INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                dialect TEXT DEFAULT 'standard',
                translation TEXT NOT NULL,
                hit_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await self._connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_cache_lookup ON cache(text, dialect)
        ''')
        
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Admin whitelist - only these users can use the bot
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_admin INTEGER DEFAULT 1,
                can_grant_access INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Paid packages/subscriptions
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS packages (
                package_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                translations_limit INTEGER DEFAULT 10,
                window_minutes INTEGER DEFAULT 60,
                price_usd REAL DEFAULT 0.0,
                duration_days INTEGER DEFAULT 30,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # User subscriptions
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package_id INTEGER,
                start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_date TIMESTAMP,
                translations_used INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                payment_status TEXT DEFAULT 'pending',
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (package_id) REFERENCES packages(package_id) ON DELETE CASCADE
            )
        ''')
        
        # Insert default packages
        await self._connection.execute('''
            INSERT OR IGNORE INTO packages (package_id, name, description, translations_limit, window_minutes, price_usd, duration_days)
            VALUES 
                (1, 'Free', 'Basic free tier', 10, 60, 0.0, 36500),
                (2, 'Basic', '50 translations per hour', 50, 60, 4.99, 30),
                (3, 'Pro', '200 translations per hour', 200, 60, 9.99, 30),
                (4, 'Unlimited', 'Unlimited translations', 999999, 60, 19.99, 30)
        ''')
        
        await self._connection.commit()
    
    async def get_user(self, user_id):
        cursor = await self._connection.execute(
            'SELECT dialect, context_mode FROM users WHERE user_id = ?',
            (user_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            await self._connection.execute(
                'INSERT INTO users (user_id) VALUES (?)',
                (user_id,)
            )
            await self._connection.commit()
            return {'dialect': 'standard', 'context_mode': True}
        
        return {'dialect': row[0], 'context_mode': bool(row[1])}
    
    async def update_user_dialect(self, user_id, dialect):
        await self._connection.execute(
            'INSERT OR REPLACE INTO users (user_id, dialect) VALUES (?, ?)',
            (user_id, dialect)
        )
        await self._connection.commit()
    
    async def get_history(self, user_id, limit=10):
        cursor = await self._connection.execute(
            'SELECT text, strftime("%H:%M", time) as time FROM history '
            'WHERE user_id = ? ORDER BY time DESC LIMIT ?',
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [{'text': row[0], 'time': row[1]} for row in rows]
    
    async def add_history(self, user_id, text):
        await self._connection.execute(
            'INSERT INTO history (user_id, text) VALUES (?, ?)',
            (user_id, text)
        )
        await self._connection.commit()
    
    async def get_favorites(self, user_id):
        cursor = await self._connection.execute(
            'SELECT text FROM favorites WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
    
    async def add_favorite(self, user_id, text):
        # Check if already exists
        cursor = await self._connection.execute(
            'SELECT 1 FROM favorites WHERE user_id = ? AND text = ?',
            (user_id, text)
        )
        if await cursor.fetchone():
            return False
        
        await self._connection.execute(
            'INSERT INTO favorites (user_id, text) VALUES (?, ?)',
            (user_id, text)
        )
        await self._connection.commit()
        return True
    
    async def get_cached_translation(self, text, dialect='standard'):
        """Check cache for existing translation."""
        cursor = await self._connection.execute(
            'SELECT translation FROM cache WHERE text = ? AND dialect = ?',
            (text.lower().strip(), dialect)
        )
        row = await cursor.fetchone()
        
        if row:
            # Update hit count and last used timestamp
            await self._connection.execute(
                'UPDATE cache SET hit_count = hit_count + 1, last_used = CURRENT_TIMESTAMP '
                'WHERE text = ? AND dialect = ?',
                (text.lower().strip(), dialect)
            )
            await self._connection.commit()
            return row[0]
        return None
    
    async def cache_translation(self, text, dialect, translation):
        """Store translation in cache."""
        try:
            await self._connection.execute(
                'INSERT OR REPLACE INTO cache (text, dialect, translation) VALUES (?, ?, ?)',
                (text.lower().strip(), dialect, translation)
            )
            await self._connection.commit()
        except Exception as e:
            logger.error(f"Cache error: {e}")
    
    async def cleanup_old_cache(self, days=30):
        """Remove cache entries older than specified days."""
        await self._connection.execute(
            'DELETE FROM cache WHERE last_used < datetime("now", ?)',
            (f'-{days} days',)
        )
        await self._connection.commit()

    async def get_cache_stats(self):
        """Get cache statistics."""
        cursor = await self._connection.execute(
            'SELECT COUNT(*) as total, SUM(hit_count) as hits FROM cache'
        )
        row = await cursor.fetchone()
        
        cursor = await self._connection.execute(
            'SELECT COUNT(*) FROM cache WHERE hit_count > 0'
        )
        used = await cursor.fetchone()
        
        return {
            'total_entries': row[0] or 0,
            'total_hits': row[1] or 0,
            'used_entries': used[0] or 0
        }

    async def check_rate_limit(self, user_id, max_requests=10, window_minutes=60):
        """Check if user has exceeded rate limit."""
        cursor = await self._connection.execute(
            'SELECT request_count, window_start FROM rate_limits WHERE user_id = ?',
            (user_id,)
        )
        row = await cursor.fetchone()
        
        now = datetime.now()
        
        if not row:
            # First request for this user
            await self._connection.execute(
                'INSERT INTO rate_limits (user_id, request_count, window_start) VALUES (?, 1, ?)',
                (user_id, now.isoformat())
            )
            await self._connection.commit()
            return True, max_requests - 1, window_minutes
        
        request_count, window_start = row
        window_start = datetime.fromisoformat(window_start)
        time_elapsed = (now - window_start).total_seconds() / 60
        
        if time_elapsed >= window_minutes:
            # Reset window
            await self._connection.execute(
                'UPDATE rate_limits SET request_count = 1, window_start = ? WHERE user_id = ?',
                (now.isoformat(), user_id)
            )
            await self._connection.commit()
            return True, max_requests - 1, window_minutes
        
        if request_count >= max_requests:
            remaining_minutes = window_minutes - int(time_elapsed)
            return False, 0, remaining_minutes
        
        # Increment count
        await self._connection.execute(
            'UPDATE rate_limits SET request_count = request_count + 1 WHERE user_id = ?',
            (user_id,)
        )
        await self._connection.commit()
        
        remaining = max_requests - request_count - 1
        return True, remaining, window_minutes - int(time_elapsed)

    # ===== Admin & Monetization Methods =====
    
    async def is_user_allowed(self, user_id):
        """Check if user is in whitelist (admin or granted access)."""
        # Check if user is admin
        cursor = await self._connection.execute(
            'SELECT 1 FROM admin_users WHERE user_id = ?',
            (user_id,)
        )
        if await cursor.fetchone():
            return True, "admin"
        
        # Check if user has any active subscription (even free tier)
        cursor = await self._connection.execute(
            '''SELECT s.subscription_id, p.name 
               FROM user_subscriptions s 
               JOIN packages p ON s.package_id = p.package_id 
               WHERE s.user_id = ? AND s.is_active = 1 
               AND (s.end_date IS NULL OR s.end_date > datetime('now'))''',
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return True, row[1]  # Returns (True, package_name)
        
        # If whitelist mode is enabled and user is not in any list, deny access
        # Check if any admin users exist (whitelist mode)
        cursor = await self._connection.execute('SELECT COUNT(*) FROM admin_users')
        admin_count = (await cursor.fetchone())[0]
        
        if admin_count > 0:
            # Whitelist mode is active, user not allowed
            return False, None
        
        # No whitelist mode, allow everyone (create free subscription)
        return True, "free"

    async def get_user_limits(self, user_id):
        """Get rate limits based on user's subscription tier."""
        cursor = await self._connection.execute(
            '''SELECT p.translations_limit, p.window_minutes, p.name, p.price_usd
               FROM user_subscriptions s 
               JOIN packages p ON s.package_id = p.package_id 
               WHERE s.user_id = ? AND s.is_active = 1 
               AND (s.end_date IS NULL OR s.end_date > datetime('now'))
               ORDER BY p.translations_limit DESC 
               LIMIT 1''',
            (user_id,)
        )
        row = await cursor.fetchone()
        
        if row:
            return {
                'limit': row[0],
                'window': row[1],
                'tier': row[2],
                'price': row[3]
            }
        
        # Check if admin (unlimited)
        cursor = await self._connection.execute(
            'SELECT 1 FROM admin_users WHERE user_id = ?',
            (user_id,)
        )
        if await cursor.fetchone():
            return {'limit': 999999, 'window': 60, 'tier': 'admin', 'price': 0}
        
        # Default free tier
        return {'limit': 10, 'window': 60, 'tier': 'free', 'price': 0}

    async def add_admin(self, user_id, username=None, can_grant_access=False):
        """Add user to admin whitelist."""
        try:
            await self._connection.execute(
                'INSERT OR REPLACE INTO admin_users (user_id, username, can_grant_access) VALUES (?, ?, ?)',
                (user_id, username, 1 if can_grant_access else 0)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False

    async def remove_admin(self, user_id):
        """Remove user from admin whitelist."""
        try:
            await self._connection.execute(
                'DELETE FROM admin_users WHERE user_id = ?',
                (user_id,)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            return False

    async def grant_access(self, user_id, package_id=1, duration_days=30):
        """Grant access to a user with specific package."""
        try:
            end_date = None if duration_days > 1000 else datetime.now().timestamp() + (duration_days * 86400)
            
            await self._connection.execute(
                '''INSERT INTO user_subscriptions 
                   (user_id, package_id, end_date, is_active) 
                   VALUES (?, ?, datetime(?, 'unixepoch'), 1)''',
                (user_id, package_id, end_date)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error granting access: {e}")
            return False

    async def revoke_access(self, user_id):
        """Revoke user's access."""
        try:
            await self._connection.execute(
                'UPDATE user_subscriptions SET is_active = 0 WHERE user_id = ?',
                (user_id,)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error revoking access: {e}")
            return False

    async def get_all_packages(self):
        """Get all available packages."""
        cursor = await self._connection.execute(
            "SELECT package_id, name, description, translations_limit, price_usd, duration_days "
            "FROM packages WHERE is_active = 1 ORDER BY price_usd"
        )
        rows = await cursor.fetchall()
        return [{
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'limit': row[3],
            'price': row[4],
            'duration': row[5]
        } for row in rows]

    async def get_user_subscription(self, user_id):
        """Get user's current subscription details."""
        cursor = await self._connection.execute(
            '''SELECT p.name, p.translations_limit, s.end_date, s.translations_used, p.price_usd
               FROM user_subscriptions s 
               JOIN packages p ON s.package_id = p.package_id 
               WHERE s.user_id = ? AND s.is_active = 1
               ORDER BY s.start_date DESC 
               LIMIT 1''',
            (user_id,)
        )
        row = await cursor.fetchone()
        
        if row:
            return {
                'tier': row[0],
                'limit': row[1],
                'expires': row[2],
                'used': row[3],
                'price': row[4]
            }
        return None

# Initialize database
db = Database(DATABASE_PATH)

# Admin contact info - UPDATE THIS TO YOUR USERNAME
ADMIN_CONTACT = "@Erivative"  # Change this to your Telegram username

# Track startup time for uptime calculation
startup_time = datetime.now()

# ===== Environment & API keys =====
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
raw_keys = [os.getenv(f'GEMINI_API_KEY{suffix}') for suffix in ['', '_2', '_3']]
GEMINI_API_KEYS = [k for k in raw_keys if k]
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

if not TELEGRAM_TOKEN or (not GEMINI_API_KEYS and not GROQ_API_KEY):
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or API Key(s)")

# PRESERVED: Your specific version choice
DEFAULT_MODEL = "gemini-2.0-flash"
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
BASE_URL = os.getenv('KOYEB_PUBLIC_URL', '').rstrip('/')

# ===== Async Queue for Heavy Operations =====
class TranslationQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.processing = False
        self.worker_task = None
        self.stats = {'processed': 0, 'failed': 0, 'in_queue': 0}
    
    async def add_translation(self, text: str, user_id: int, chat_id: int, message_id: int):
        """Add translation task to queue."""
        await self.queue.put({
            'text': text,
            'user_id': user_id,
            'chat_id': chat_id,
            'message_id': message_id,
            'timestamp': datetime.now()
        })
        self.stats['in_queue'] = self.queue.qsize()
        logger.info(f"Translation queued for user {user_id}. Queue size: {self.stats['in_queue']}")
    
    async def process_queue(self, ptb_app: Application):
        """Background worker to process translation queue."""
        while self.processing:
            try:
                # Wait for a task with a timeout to allow checking processing flag
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                self.stats['in_queue'] = self.queue.qsize()
                
                try:
                    logger.info(f"Processing translation for user {task['user_id']}")
                    
                    # Perform the actual translation
                    result_text = await translate_text(task['text'], task['user_id'])
                    
                    # Send the result back to the user
                    await self.send_translation_result(ptb_app, task, result_text)
                    self.stats['processed'] += 1
                    
                except Exception as e:
                    logger.error(f"Queue processing error: {e}")
                    self.stats['failed'] += 1
                    # Send error message
                    await self.send_translation_result(
                        ptb_app, task, "❌ Error processing your translation. Please try again."
                    )
                
                finally:
                    self.queue.task_done()
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
    
    async def send_translation_result(self, ptb_app: Application, task: dict, result_text: str):
        """Send translation result back to the chat."""
        try:
            chunks = split_message(result_text)
            keyboard = [[InlineKeyboardButton("⭐ Save", callback_data='save_fav')]]
            
            for i, chunk in enumerate(chunks):
                if i == 0:
                    # Edit the "Translating..." message
                    await ptb_app.bot.edit_message_text(
                        chat_id=task['chat_id'],
                        message_id=task['message_id'],
                        text=chunk,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # Send additional chunks as new messages
                    await ptb_app.bot.send_message(
                        chat_id=task['chat_id'],
                        text=chunk,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
        except Exception as e:
            logger.error(f"Error sending translation result: {e}")
    
    async def start_worker(self, ptb_app: Application):
        """Start the background worker."""
        if not self.processing:
            self.processing = True
            self.worker_task = asyncio.create_task(self.process_queue(ptb_app))
            logger.info("Translation queue worker started")
    
    async def stop_worker(self):
        """Stop the background worker."""
        self.processing = False
        if self.worker_task:
            await self.worker_task
            logger.info("Translation queue worker stopped")
    
    def get_stats(self):
        """Get queue statistics."""
        return {
            **self.stats,
            'in_queue': self.queue.qsize(),
            'is_running': self.processing
        }

# Initialize translation queue
translation_queue = TranslationQueue()

# ===== Local Dictionary Fallback =====
LOCAL_DICTIONARY = {
    # Common greetings
    'hello': {
        'darja': 'السلام عليكم / مرحبا',
        'pronunciation': 'As-salamu alaykum / Marhaba',
        'french': 'Bonjour / Salut',
        'english': 'Hello / Hi',
        'note': 'As-salamu alaykum is the formal Islamic greeting'
    },
    'hi': {
        'darja': 'مرحبا / واش راك',
        'pronunciation': 'Marhaba / Wash rak',
        'french': 'Salut / Ça va',
        'english': 'Hi / How are you',
        'note': 'Wash rak is informal among friends'
    },
    'good morning': {
        'darja': 'صباح الخير',
        'pronunciation': 'Sbah el-khir',
        'french': 'Bonjour (le matin)',
        'english': 'Good morning',
        'note': 'Used until noon'
    },
    'good evening': {
        'darja': 'مساء الخير',
        'pronunciation': 'Msa el-khir',
        'french': 'Bonsoir',
        'english': 'Good evening',
        'note': 'Used after sunset'
    },
    'good night': {
        'darja': 'تصبح على خير',
        'pronunciation': 'Tesbah ala khair',
        'french': 'Bonne nuit',
        'english': 'Good night',
        'note': 'Said when parting at night'
    },
    'goodbye': {
        'darja': 'مع السلامة / بسلامة',
        'pronunciation': 'Ma\'a salama / B\'salama',
        'french': 'Au revoir',
        'english': 'Goodbye',
        'note': 'B\'salama is the Algerian short form'
    },
    
    # Common phrases
    'how are you': {
        'darja': 'واش راك / كيفاه راك',
        'pronunciation': 'Wash rak / Kifah rak',
        'french': 'Comment ça va',
        'english': 'How are you',
        'note': 'Wash rak is most common in Algeria'
    },
    'thank you': {
        'darja': 'شكرا / بارك الله فيك',
        'pronunciation': 'Choukran / Barak Allah fik',
        'french': 'Merci',
        'english': 'Thank you',
        'note': 'Barak Allah fik is more heartfelt/grateful'
    },
    'please': {
        'darja': 'عفوا / برك الله فيك',
        'pronunciation': '\'Afak / Baraka Allah fik',
        'french': 'S\'il te plaît',
        'english': 'Please',
        'note': 'Literally means "for your sake"'
    },
    'sorry': {
        'darja': 'سمحني / معذرة',
        'pronunciation': 'Smehli / Ma\'zerta',
        'french': 'Pardon / Désolé',
        'english': 'Sorry / Excuse me',
        'note': 'Smehli literally means "forgive me"'
    },
    'yes': {
        'darja': 'نعم / واه / إييه',
        'pronunciation': 'Na\'am / Wah / Eyeh',
        'french': 'Oui',
        'english': 'Yes',
        'note': 'Wah and Eyeh are casual affirmations'
    },
    'no': {
        'darja': 'لا / أواه',
        'pronunciation': 'La / Owah',
        'french': 'Non',
        'english': 'No',
        'note': 'Owah is Algerian pronunciation'
    },
    
    # Food related
    'food': {
        'darja': 'الماكل / الطعام',
        'pronunciation': 'El-makul / At-ta\'am',
        'french': 'Nourriture',
        'english': 'Food',
        'note': 'El-makul is specifically Algerian dialect'
    },
    'water': {
        'darja': 'الماء / الما',
        'pronunciation': 'El-ma\' / El-ma',
        'french': 'Eau',
        'english': 'Water',
        'note': 'El-ma is the Algerian pronunciation'
    },
    'bread': {
        'darja': 'الخبز / الرغيف',
        'pronunciation': 'El-khobz / Er-raghif',
        'french': 'Pain',
        'english': 'Bread',
        'note': 'Essential part of every Algerian meal'
    },
    'coffee': {
        'darja': 'القهوة',
        'pronunciation': 'El-qahwa',
        'french': 'Café',
        'english': 'Coffee',
        'note': 'Algerian coffee culture is strong'
    },
    'tea': {
        'darja': 'الأتاي / الشاي',
        'pronunciation': 'El-atay / Esh-shay',
        'french': 'Thé',
        'english': 'Tea',
        'note': 'Mint tea is traditional'
    },
    
    # Family
    'mother': {
        'darja': 'مّي / الوالدة',
        'pronunciation': 'Mmi / El-walida',
        'french': 'Mère',
        'english': 'Mother',
        'note': 'Mmi is the most intimate term'
    },
    'father': {
        'darja': 'بابا / الوالد',
        'pronunciation': 'Baba / El-walid',
        'french': 'Père',
        'english': 'Father',
        'note': 'Baba is affectionate Algerian term'
    },
    'brother': {
        'darja': 'خوي',
        'pronunciation': 'Khouya',
        'french': 'Frère',
        'english': 'Brother',
        'note': 'Also used to address close male friends'
    },
    'sister': {
        'darja': 'ختي',
        'pronunciation': 'Khti',
        'french': 'Sœur',
        'english': 'Sister',
        'note': 'Also used to address close female friends'
    },
    'friend': {
        'darja': 'الصاحب / الصاحبي',
        'pronunciation': 'Es-sahib / Es-sahbi',
        'french': 'Ami',
        'english': 'Friend',
        'note': 'Es-sahbi literally means "my companion"'
    },
    
    # Common expressions
    'i love you': {
        'darja': 'نحبك',
        'pronunciation': 'Nhebbek',
        'french': 'Je t\'aime',
        'english': 'I love you',
        'note': 'Can be used for romantic or familial love'
    },
    'very good': {
        'darja': 'مليح / بزاف مليح',
        'pronunciation': 'Mlih / Bzzaf mlih',
        'french': 'Très bien',
        'english': 'Very good',
        'note': 'Mlih is the most common Algerian term'
    },
    'i don\'t understand': {
        'darja': 'ما فهمتش',
        'pronunciation': 'Ma fhemtsh',
        'french': 'Je ne comprends pas',
        'english': 'I don\'t understand',
        'note': 'The "sh" ending is the Algerian negation'
    },
    'where is': {
        'darja': 'وين رايح / وين هو',
        'pronunciation': 'Win rayeh / Win huwa',
        'french': 'Où est',
        'english': 'Where is',
        'note': 'Win is Algerian for "where"'
    },
    'how much': {
        'darja': 'شحال / بشحال',
        'pronunciation': 'Shhal / Beshhal',
        'french': 'Combien',
        'english': 'How much',
        'note': 'Essential for shopping in markets'
    },
    'where are you going': {
        'darja': 'وين راك رايح',
        'pronunciation': 'Win rak rayeh',
        'french': 'Où vas-tu',
        'english': 'Where are you going',
        'note': 'Win means where'
    },
    'i am hungry': {
        'darja': 'راني جيعان',
        'pronunciation': 'Rani ji\'an',
        'french': 'J\'ai faim',
        'english': 'I am hungry',
        'note': 'Rani means "I am" in this context'
    },
    'i am thirsty': {
        'darja': 'راني عطشان',
        'pronunciation': 'Rani \'atshan',
        'french': 'J\'ai soif',
        'english': 'I am thirsty',
        'note': 'Used for needing water'
    },
    'beautiful': {
        'darja': 'شباب / شابة',
        'pronunciation': 'Shbab (m) / Shaba (f)',
        'french': 'Beau / Belle',
        'english': 'Beautiful / Handsome',
        'note': 'Very common Algerian word'
    },
    'nothing': {
        'darja': 'والو',
        'pronunciation': 'Wallou',
        'french': 'Rien',
        'english': 'Nothing',
        'note': 'Derived from Arabic "wa-la-shay"'
    }
}

class DictionaryFallback:
    """Local dictionary fallback when APIs fail."""
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for lookup."""
        return text.lower().strip().rstrip('?').rstrip('!').rstrip('.')
    
    @staticmethod
    def find_match(text: str) -> dict:
        """Find best match in local dictionary."""
        normalized = DictionaryFallback.normalize(text)
        
        # Direct match
        if normalized in LOCAL_DICTIONARY:
            return LOCAL_DICTIONARY[normalized]
        
        # Partial match - check if any key is contained in text
        for key, value in LOCAL_DICTIONARY.items():
            if key in normalized or normalized in key:
                return value
        
        return None
    
    @staticmethod
    def format_translation(text: str, match: dict) -> str:
        """Format dictionary result like API response."""
        return (
            f"🔤 **Original:** {text}\n"
            f"🇩🇿 **Darja:** {match['darja']}\n"
            f"🗣️ **Pronunciation:** {match['pronunciation']}\n"
            f"🇫🇷 **French:** {match['french']}\n"
            f"🇬🇧 **English:** {match['english']}\n"
            f"💡 **Note:** {match['note']}\n\n"
            f"⚠️ *Using offline dictionary (API unavailable)*"
        )
    
    @staticmethod
    def get_all_words() -> str:
        """Get list of all available dictionary words."""
        words = sorted(LOCAL_DICTIONARY.keys())
        return "📚 *Available in offline dictionary:*\n\n" + "\n".join([f"• {w}" for w in words])

# Initialize dictionary fallback
dictionary_fallback = DictionaryFallback()

# ===== Dialect Configuration =====
DIALECT_PROMPTS = {
    'standard': 'Algerian Arabic (Darja)',
    'algiers': 'Algerian Arabic (Darja) from Algiers region',
    'oran': 'Algerian Arabic (Darja) from Oran region',
    'constantine': 'Algerian Arabic (Darja) from Constantine region'
}

# NEW: Utility to handle long messages
def split_message(text, limit=4000):
    """Splits text into chunks to fit Telegram's 4096 character limit."""
    return [text[i:i + limit] for i in range(0, len(text), limit)]

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
    user = await db.get_user(user_id)
    history = await db.get_history(user_id) if user['context_mode'] else None
    dialect = user['dialect']
    
    # Check cache first (only for dialect-specific translations without context)
    if not user['context_mode'] or not history:
        cached = await db.get_cached_translation(text, dialect)
        if cached:
            logger.info(f"Cache hit for: {text[:50]}...")
            await db.add_history(user_id, text)
            return f"⚡ *Cached*\n\n{cached}"
    
    # PRESERVED: Original version fallback list
    version_fallback = [DEFAULT_MODEL, "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    api_error = None
    
    # 1. Try Gemini first
    for model_ver in version_fallback:
        for i, key in enumerate(GEMINI_API_KEYS):
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(
                    model_name=model_ver,
                    system_instruction=get_system_prompt(dialect, history)
                )
                response = model.generate_content(text)
                
                if response.candidates:
                    translation = response.text
                    await db.add_history(user_id, text)
                    
                    # Cache the translation (only if no context was used)
                    if not user['context_mode'] or not history:
                        await db.cache_translation(text, dialect, translation)
                        logger.info(f"Cached translation for: {text[:50]}...")
                    
                    return translation
                api_error = "Safety filter blocked response"
            except Exception as e:
                api_error = str(e)
                logger.warning(f"Gemini error with {model_ver}, key {i}: {e}")
                continue
    
    # 2. Try Groq as fallback if Gemini fails
    if GROQ_API_KEY:
        try:
            logger.info("Attempting Groq fallback...")
            client = AsyncGroq(api_key=GROQ_API_KEY)
            
            response = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": get_system_prompt(dialect, history)},
                    {"role": "user", "content": text}
                ]
            )
            
            if response.choices:
                translation = response.choices[0].message.content
                await db.add_history(user_id, text)
                
                # Cache the translation
                if not user['context_mode'] or not history:
                    await db.cache_translation(text, dialect, translation)
                
                return translation
        except Exception as e:
            api_error = f"Groq error: {str(e)}"
            logger.error(api_error)

    # All APIs failed - try local dictionary fallback
    logger.error(f"All API attempts failed. Last error: {api_error}")
    logger.info(f"Attempting dictionary fallback for: {text[:50]}...")
    
    match = dictionary_fallback.find_match(text)
    if match:
        await db.add_history(user_id, text)
        return dictionary_fallback.format_translation(text, match)
    
    # No dictionary match found
    return (
        "❌ *Translation Service Unavailable*\n\n"
        "The AI translation service is currently unavailable.\n"
        "Please try again in a few minutes.\n\n"
        f"Error: `{api_error}`"
    )

async def translate_voice(file_path: str, user_id: int):
    """Transcribe and translate audio file using Gemini."""
    user = await db.get_user(user_id)
    dialect = user['dialect']
    
    # PRESERVED: Original version fallback list
    version_fallback = [DEFAULT_MODEL, "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    api_error = None
    for model_ver in version_fallback:
        for i, key in enumerate(GEMINI_API_KEYS):
            if not key: continue
            try:
                genai.configure(api_key=key)
                # Note: Voice processing works best with newer models
                model = genai.GenerativeModel(model_name=model_ver)
                
                # Upload file to Gemini
                sample_file = genai.upload_file(path=file_path, display_name="Voice Message")
                
                prompt = get_system_prompt(dialect)
                prompt += "\nThis is a voice message. Please transcribe the audio first accurately, then provide the full translation following the rules above."
                
                response = model.generate_content([prompt, sample_file])
                
                # Clean up uploaded file from Gemini storage
                try:
                    genai.delete_file(sample_file.name)
                except:
                    pass
                
                if response and response.text:
                    return response.text.strip()
                    
            except Exception as e:
                api_error = str(e)
                logger.error(f"Voice API Error (Key {i}, Model {model_ver}): {e}")
                continue
                
    return f"❌ Voice translation failed.\n\nError: {api_error or 'Unknown error'}"

# ===== Handlers =====

async def check_admin(update: Update) -> bool:
    """Check if user is an admin."""
    user_id = update.effective_user.id
    return await db.is_user_allowed(user_id)

async def packages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available packages for purchase."""
    packages = await db.get_all_packages()
    
    text = "💎 *Available Packages*\n\n"
    keyboard = []
    
    for pkg in packages:
        if pkg['price'] == 0:
            text += f"🆓 *{pkg['name']}* - Free\n"
            text += f"   {pkg['limit']} translations/hour\n"
            text += f"   {pkg['description']}\n\n"
        else:
            text += f"{'⭐' if pkg['price'] < 10 else '🚀' if pkg['price'] < 20 else '💎'} *{pkg['name']}* - ${pkg['price']:.2f}/mo\n"
            text += f"   {pkg['limit']} translations/hour\n"
            text += f"   {pkg['description']}\n"
            text += f"   Duration: {pkg['duration']} days\n\n"
            
            if pkg['price'] > 0:
                keyboard.append([InlineKeyboardButton(
                    f"Upgrade to {pkg['name']} - ${pkg['price']:.2f}", 
                    callback_data=f"upgrade_{pkg['name'].lower()}"
                )])
    
    text += "\n✨ Upgrade to get more translations!"
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's current subscription status."""
    user_id = update.effective_user.id
    limits = await db.get_user_limits(user_id)
    sub = await db.get_user_subscription(user_id)
    
    text = f"👤 *Your Subscription*\n\n"
    text += f"Current Tier: *{limits['tier']}*\n"
    text += f"Translations: *{limits['limit']}* per hour\n"
    
    if sub:
        text += f"\n📊 Usage: {sub['used']} translations used\n"
        if sub['expires']:
            text += f"⏰ Expires: {sub['expires']}\n"
    
    if limits['tier'] == 'free':
        text += "\n💡 Type `/packages` to upgrade and get more translations!"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Grant access to a user."""
    if not await check_admin(update):
        await update.message.reply_text("⛔ This command is only for administrators.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/grant <user_id> [package_id] [duration_days]`\n"
            "Example: `/grant 123456789 2 30` - Grant Basic package for 30 days",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_user_id = int(context.args[0])
        package_id = int(context.args[1]) if len(context.args) > 1 else 1
        duration = int(context.args[2]) if len(context.args) > 2 else 30
        
        success = await db.grant_access(target_user_id, package_id, duration)
        if success:
            await update.message.reply_text(
                f"✅ Access granted!\n"
                f"User: `{target_user_id}`\n"
                f"Package ID: {package_id}\n"
                f"Duration: {duration} days",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Failed to grant access.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please use a numeric ID.")

async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Revoke user access."""
    if not await check_admin(update):
        await update.message.reply_text("⛔ This command is only for administrators.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/revoke <user_id>`")
        return
    
    try:
        target_user_id = int(context.args[0])
        success = await db.revoke_access(target_user_id)
        if success:
            await update.message.reply_text(f"✅ Access revoked for user `{target_user_id}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Failed to revoke access.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Add/remove user from whitelist."""
    if not await check_admin(update):
        await update.message.reply_text("⛔ This command is only for administrators.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "`/whitelist add <user_id> [@username]` - Add to whitelist\n"
            "`/whitelist remove <user_id>` - Remove from whitelist",
            parse_mode='Markdown'
        )
        return
    
    action = context.args[0].lower()
    
    try:
        target_user_id = int(context.args[1])
        username = context.args[2] if len(context.args) > 2 else None
        
        if action == 'add':
            success = await db.add_admin(target_user_id, username, can_grant_access=True)
            if success:
                await update.message.reply_text(f"✅ User `{target_user_id}` added to whitelist!", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Failed to add user.")
        elif action == 'remove':
            success = await db.remove_admin(target_user_id)
            if success:
                await update.message.reply_text(f"✅ User `{target_user_id}` removed from whitelist!", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Failed to remove user.")
        else:
            await update.message.reply_text("❌ Invalid action. Use 'add' or 'remove'.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is allowed
    is_allowed, access_type = await db.is_user_allowed(user_id)
    
    if not is_allowed:
        # Whitelist mode is active and user is not allowed
        admin_username = ADMIN_CONTACT.lstrip('@')
        keyboard = [[InlineKeyboardButton("💬 Contact Admin for Access", url=f"https://t.me/{admin_username}")]]
        await update.message.reply_text(
            "🔒 *Welcome to Darja Bot!*\n\n"
            "This bot is currently in private beta.\n"
            "Access is by invitation only.\n\n"
            f"Contact {ADMIN_CONTACT} to request access.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Get user limits to show their tier
    limits = await db.get_user_limits(user_id)
    
    welcome_text = (
        f"🇩🇿 *Marhba!* I am your Darja assistant.\n\n"
        f"You're using the *{limits['tier']}* tier.\n"
    )
    
    if limits['tier'] == 'free':
        welcome_text += f"You have {limits['limit']} translations per hour.\n\n"
        welcome_text += "💡 Type `/packages` to see upgrade options!\n\n"
    elif limits['tier'] == 'admin':
        welcome_text += "You have unlimited access as an administrator.\n\n"
    else:
        welcome_text += f"You have {limits['limit']} translations per hour.\n\n"
    
    welcome_text += "Send any text to begin or use /help to see my commands."
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Description of how to use the bot and list of commands."""
    user_id = update.effective_user.id
    limits = await db.get_user_limits(user_id)
    
    help_text = (
        "📖 *How to use this bot:*\n"
        "• Send **English/French** text to get the Darja translation.\n"
        "• Send **Arabic script** to get French and English translations.\n\n"
        "✨ *Available Commands:*\n"
        "/subscription - View your subscription status\n"
        "/packages - View upgrade packages & pricing\n"
        "/dialect - Change region (Algiers, Oran, etc.)\n"
        "/history - See your last 10 translations\n"
        "/saved - View your bookmarked items\n"
        "/save - Reply to any translation with this to bookmark it\n"
        "/stats - View cache statistics (admin)\n"
        "/queue - View queue status (admin)\n"
        "/dictionary - View offline dictionary words\n"
        "/start - Restart the bot\n\n"
        f"⚠️ *Your Rate Limit:* {limits['limit']} translations per hour ({limits['tier']} tier)\n"
        "⏱️ *Queue:* Translations are processed asynchronously\n"
        "📚 *Offline:* Dictionary available when API fails"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = await db.get_history(update.effective_user.id)
    if not history:
        return await update.message.reply_text("📚 Your history is currently empty.")
    
    lines = [f"• `{h['text']}` ({h['time']})" for h in history]
    await update.message.reply_text("📚 *Recent Translations:*\n\n" + "\n".join(lines), parse_mode='Markdown')

async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ Please reply to the message you want to save with /save")
    
    text = update.message.reply_to_message.text
    user_id = update.effective_user.id
    added = await db.add_favorite(user_id, text)
    
    if added:
        await update.message.reply_text("⭐ Translation bookmarked!")
    else:
        await update.message.reply_text("✅ Already in your /saved list.")

async def saved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    favs = await db.get_favorites(update.effective_user.id)
    if not favs:
        return await update.message.reply_text("⭐ Your saved list is empty.")
    
    await update.message.reply_text("⭐ *Your Saved Translations:*\n\n" + "\n---\n".join(favs), parse_mode='Markdown')

async def dictionary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available offline dictionary words."""
    words_list = dictionary_fallback.get_all_words()
    await update.message.reply_text(words_list, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view cache statistics."""
    if not await check_admin(update):
        await update.message.reply_text("⛔ This command is only for administrators.")
        return
        
    stats = await db.get_cache_stats()
    
    stats_text = (
        "📊 *Cache Statistics*\n\n"
        f"📦 Total entries: `{stats['total_entries']}`\n"
        f"🔥 Total cache hits: `{stats['total_hits']}`\n"
        f"✅ Used entries: `{stats['used_entries']}`\n\n"
        f"Hit rate: `{stats['total_hits'] / max(stats['total_entries'], 1):.1%}`"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view queue statistics."""
    if not await check_admin(update):
        await update.message.reply_text("⛔ This command is only for administrators.")
        return
        
    stats = translation_queue.get_stats()
    
    status_icon = "🟢" if stats['is_running'] else "🔴"
    stats_text = (
        "📊 *Queue Statistics*\n\n"
        f"{status_icon} Status: `{'Running' if stats['is_running'] else 'Stopped'}`\n"
        f"⏳ In queue: `{stats['in_queue']}`\n"
        f"✅ Processed: `{stats['processed']}`\n"
        f"❌ Failed: `{stats['failed']}`\n\n"
        f"The queue processes translations asynchronously to keep the bot responsive."
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def set_dialect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Standard 🇩🇿", callback_data='dial_standard')],
        [InlineKeyboardButton("Algiers 🏙️", callback_data='dial_algiers')],
        [InlineKeyboardButton("Oran 🌅", callback_data='dial_oran')],
        [InlineKeyboardButton("Constantine 🌉", callback_data='dial_constantine')]
    ]
    await update.message.reply_text("Select your preferred dialect:", reply_markup=InlineKeyboardMarkup(keyboard))

async def dialect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    dialect_key = query.data.replace('dial_', '')
    await db.update_user_dialect(update.effective_user.id, dialect_key)
    await query.answer(f"Dialect set to {dialect_key.title()}")
    await query.edit_message_text(f"✅ Dialect successfully updated to: **{DIALECT_PROMPTS[dialect_key]}**", parse_mode='Markdown')

async def save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    translation = query.message.text
    added = await db.add_favorite(update.effective_user.id, translation)
    if added:
        await query.answer("⭐ Saved to Favorites!")
    else:
        await query.answer("Already saved.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice and audio messages."""
    if not update.message:
        return
        
    logger.info(f"Audio/Voice message received from {update.effective_user.id}")
        
    # Check if it's a voice note, an audio file, or a video note
    voice = update.message.voice
    audio = update.message.audio
    video_note = update.message.video_note
    
    if not (voice or audio or video_note):
        return
        
    user_id = update.effective_user.id
    
    # Permission check
    is_allowed, access_type = await db.is_user_allowed(user_id)
    if not is_allowed:
        admin_username = ADMIN_CONTACT.lstrip('@')
        keyboard = [[InlineKeyboardButton("💬 Contact Admin for Access", url=f"https://t.me/{admin_username}")]]
        await update.message.reply_text(
            "🔒 *Access Restricted*\n\n"
            "This bot is currently in private beta and requires an invitation to use.\n\n"
            f"If you'd like to request access, please contact: {ADMIN_CONTACT}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Rate limit check
    limits = await db.get_user_limits(user_id)
    allowed, remaining, reset_minutes = await db.check_rate_limit(user_id, max_requests=limits['limit'], window_minutes=limits['window'])
    
    if not allowed:
        await update.message.reply_text(f"⏱️ *Rate limit reached!*\n\nPlease try again in {reset_minutes} minute(s).", parse_mode='Markdown')
        return

    await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
    status_msg = await update.message.reply_text("📥 *Processing audio message...*", parse_mode='Markdown')

    try:
        # Get the file ID
        if voice:
            file_id = voice.file_id
            mime_type = "audio/ogg"
        elif audio:
            file_id = audio.file_id
            mime_type = audio.mime_type or "audio/mpeg"
        else: # video_note
            file_id = video_note.file_id
            mime_type = "video/mp4"
            
        voice_file = await context.bot.get_file(file_id)
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = os.path.join(tmp_dir, "input_file")
            wav_path = os.path.join(tmp_dir, "voice.wav")
            
            await voice_file.download_to_drive(input_path)
            
            # Convert any audio/video format to WAV
            process = subprocess.run(
                ['ffmpeg', '-y', '-i', input_path, '-ar', '16000', '-ac', '1', wav_path],
                capture_output=True, text=True
            )
            
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {process.stderr}")
                await status_msg.edit_text("❌ Error processing audio file.")
                return

            await status_msg.edit_text("🔄 *Translating audio...*", parse_mode='Markdown')
            
            # Translate using Gemini
            translation = await translate_voice(wav_path, user_id)
            
            # Update status message with result
            chunks = split_message(translation)
            await status_msg.edit_text(chunks[0], parse_mode='Markdown')
            for chunk in chunks[1:]:
                await update.message.reply_text(chunk, parse_mode='Markdown')
                
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await status_msg.edit_text(f"❌ An error occurred during audio processing: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    # Check if user is allowed (whitelist check)
    is_allowed, access_type = await db.is_user_allowed(user_id)
    
    if not is_allowed:
        # User is not in whitelist
        admin_username = ADMIN_CONTACT.lstrip('@')
        keyboard = [[InlineKeyboardButton("💬 Contact Admin for Access", url=f"https://t.me/{admin_username}")]]
        await update.message.reply_text(
            "🔒 *Access Restricted*\n\n"
            "This bot is currently in private beta and requires an invitation to use.\n\n"
            f"If you'd like to request access, please contact: {ADMIN_CONTACT}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Get user's subscription tier and limits
    limits = await db.get_user_limits(user_id)
    max_requests = limits['limit']
    window_minutes = limits['window']
    tier = limits['tier']
    
    # Check rate limit based on user's tier
    allowed, remaining, reset_minutes = await db.check_rate_limit(user_id, max_requests=max_requests, window_minutes=window_minutes)
    
    if not allowed:
        # Show upgrade options for free users who hit limits
        if tier == 'free':
            keyboard = [
                [InlineKeyboardButton("⭐ Upgrade to Basic - $4.99/mo", callback_data='upgrade_basic')],
                [InlineKeyboardButton("🚀 Upgrade to Pro - $9.99/mo", callback_data='upgrade_pro')],
                [InlineKeyboardButton("💎 Go Unlimited - $19.99/mo", callback_data='upgrade_unlimited')]
            ]
            await update.message.reply_text(
                f"⏱️ *Rate Limit Reached!*\n\n"
                f"You've used all {max_requests} translations in your free tier.\n\n"
                f"✨ *Upgrade to continue translating:*\n"
                f"• Basic: 50 translations/hour\n"
                f"• Pro: 200 translations/hour\n"
                f"• Unlimited: No limits!\n\n"
                f"Or wait {reset_minutes} minute(s) for your limit to reset.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Paid user hit their limit (rare but possible)
            await update.message.reply_text(
                f"⏱️ *Rate limit exceeded!*\n\n"
                f"You've reached your {tier} tier limit of {max_requests} translations per hour.\n"
                f"Please try again in {reset_minutes} minute(s).\n\n"
                f"Tip: Use `/history` to review your previous translations!",
                parse_mode='Markdown'
            )
        return
    
    await update.message.chat.send_action(action=constants.ChatAction.TYPING)
    
    # Show queue position if there are pending translations
    queue_size = translation_queue.get_stats()['in_queue']
    queue_notice = ""
    if queue_size > 0:
        queue_notice = f"\n📥 Position in queue: {queue_size + 1}"
    
    # Show tier badge for paid users
    tier_badge = ""
    if tier in ['Basic', 'Pro', 'Unlimited']:
        tier_badge = f"\n🏆 {tier} Member"
    
    status_msg = await update.message.reply_text(
        f"🕒 *Translating...*{queue_notice}{tier_badge}", 
        parse_mode='Markdown'
    )
    
    # Add translation to queue for async processing
    await translation_queue.add_translation(
        text=update.message.text,
        user_id=user_id,
        chat_id=update.message.chat_id,
        message_id=status_msg.message_id
    )
    
    # Rate limit warning (only for free tier or low remaining)
    if remaining <= 3 and tier == 'free':
        await update.message.reply_text(
            f"⚠️ You have {remaining} translation(s) remaining this hour.\n"
            f"💡 Type `/packages` to see upgrade options!",
            parse_mode='Markdown'
        )

# ===== PTB Application Setup =====
ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()

ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("history", history_command))
ptb_app.add_handler(CommandHandler("save", save_command))
ptb_app.add_handler(CommandHandler("saved", saved_command))
ptb_app.add_handler(CommandHandler("dictionary", dictionary_command))
ptb_app.add_handler(CommandHandler("dialect", set_dialect))

ptb_app.add_handler(CommandHandler("stats", stats_command))
ptb_app.add_handler(CommandHandler("queue", queue_command))
ptb_app.add_handler(CommandHandler("dictionary", dictionary_command))

# Voice & Audio handler
ptb_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, handle_voice))

# New monetization commands

ptb_app.add_handler(CommandHandler("packages", packages_command))
ptb_app.add_handler(CommandHandler("subscription", subscription_command))

# Admin commands
ptb_app.add_handler(CommandHandler("grant", grant_command))
ptb_app.add_handler(CommandHandler("revoke", revoke_command))
ptb_app.add_handler(CommandHandler("whitelist", whitelist_command))

ptb_app.add_handler(CallbackQueryHandler(dialect_callback, pattern="^dial_"))
ptb_app.add_handler(CallbackQueryHandler(save_callback, pattern="^save_fav$"))

# Payment instructions template - CUSTOMIZE THIS
PAYMENT_INSTRUCTIONS = """
💳 *Payment Options:*

1️⃣ *Electronic Payment* (Recommended)
   Fastest way to get access.
   
2️⃣ *Bank Transfer*
   Contact admin for account details.
   
3️⃣ *Other Methods*
   BaridiMob, Crypto, etc. available upon request.

Send payment screenshot/receipt along with your User ID to @Erivative.
"""

# Upgrade callback handler
async def upgrade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle upgrade button clicks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Get package details
    package_name = "Unknown"
    package_price = "0"
    stripe_link = None
    
    if query.data == 'upgrade_basic':
        package_name = "Basic"
        package_price = "$4.99"
        stripe_link = os.getenv('STRIPE_BASIC_LINK')
    elif query.data == 'upgrade_pro':
        package_name = "Pro"
        package_price = "$9.99"
        stripe_link = os.getenv('STRIPE_PRO_LINK')
    elif query.data == 'upgrade_unlimited':
        package_name = "Unlimited"
        package_price = "$19.99"
        stripe_link = os.getenv('STRIPE_UNLIMITED_LINK')
    
    pay_now_btn = ""
    if stripe_link:
        pay_now_btn = f"🔗 *Pay Now:* [Click Here to Pay]({stripe_link})\n\n"
    
    message_text = (
        f"💎 *Upgrade to {package_name}*\n\n"
        f"Price: *{package_price}*\n\n"
        f"{pay_now_btn}"
        f"To upgrade via other methods, message: {ADMIN_CONTACT}\n\n"
        f"📋 *Send this info after payment:*\n"
        f"• Your User ID: `{user_id}`\n"
        f"• Package: {package_name}\n\n"
        f"{PAYMENT_INSTRUCTIONS}\n"
        f"Once payment is confirmed, you'll get instant access!"
    )
    
    keyboard = [[InlineKeyboardButton("💬 Message Admin", url=f"https://t.me/{ADMIN_CONTACT.lstrip('@')}")]]
    if stripe_link:
        keyboard.insert(0, [InlineKeyboardButton("💳 Pay Online Now", url=stripe_link)])
    
    await query.edit_message_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

ptb_app.add_handler(CallbackQueryHandler(upgrade_callback, pattern="^upgrade_"))

# Filter for TEXT only
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

@flask_app.route('/health', methods=['GET'])
async def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Get queue stats
        queue_stats = translation_queue.get_stats()
        
        # Get cache stats
        cache_stats = await db.get_cache_stats()
        
        # Calculate uptime
        uptime = datetime.now() - startup_time
        uptime_str = str(uptime).split('.')[0]  # Remove microseconds
        
        # Check if services are healthy
        is_healthy = (
            queue_stats['is_running'] and  # Queue worker is running
            db._connection is not None      # Database is connected
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
                "queue_processed": queue_stats['processed'],
                "queue_failed": queue_stats['failed'],
                "cache_entries": cache_stats['total_entries'],
                "cache_hits": cache_stats['total_hits'],
                "gemini_keys": len(GEMINI_API_KEYS),
                "groq_active": GROQ_API_KEY is not None
            }
        }
        
        return status, 200 if is_healthy else 503
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }, 503

@flask_app.route('/status', methods=['GET'])
async def status_page():
    """Detailed status page with HTML formatting."""
    try:
        queue_stats = translation_queue.get_stats()
        cache_stats = await db.get_cache_stats()
        
        uptime = datetime.now() - startup_time
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Darja Bot Status</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
                .status {{ font-size: 24px; font-weight: bold; margin: 20px 0; }}
                .healthy {{ color: #4CAF50; }}
                .degraded {{ color: #ff9800; }}
                .unhealthy {{ color: #f44336; }}
                .metric {{ display: inline-block; margin: 10px 20px 10px 0; padding: 10px; background: #f0f0f0; border-radius: 5px; }}
                .metric-label {{ font-weight: bold; color: #666; }}
                .metric-value {{ font-size: 20px; color: #333; }}
                .section {{ margin: 30px 0; }}
                .section h2 {{ color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f5f5f5; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🇩🇿 Darja Translation Bot - Status</h1>
                
                <div class="status {'healthy' if queue_stats['is_running'] else 'degraded'}">
                    Status: {'🟢 Operational' if queue_stats['is_running'] else '🟠 Degraded'}
                </div>
                
                <div class="section">
                    <h2>📊 System Metrics</h2>
                    <div class="metric">
                        <div class="metric-label">Uptime</div>
                        <div class="metric-value">{str(uptime).split('.')[0]}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Queue Size</div>
                        <div class="metric-value">{queue_stats['in_queue']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Processed</div>
                        <div class="metric-value">{queue_stats['processed']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Failed</div>
                        <div class="metric-value">{queue_stats['failed']}</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>💾 Cache Metrics</h2>
                    <div class="metric">
                        <div class="metric-label">Cache Entries</div>
                        <div class="metric-value">{cache_stats['total_entries']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Total Hits</div>
                        <div class="metric-value">{cache_stats['total_hits']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Hit Rate</div>
                        <div class="metric-value">{(cache_stats['total_hits'] / max(cache_stats['total_entries'], 1) * 100):.1f}%</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>🔧 Services</h2>
                    <table>
                        <tr><th>Service</th><th>Status</th></tr>
                        <tr><td>Queue Worker</td><td>{'🟢 Running' if queue_stats['is_running'] else '🔴 Stopped'}</td></tr>
                        <tr><td>Database</td><td>{'🟢 Connected' if db._connection else '🔴 Disconnected'}</td></tr>
                        <tr><td>Bot</td><td>{'🟢 Active' if ptb_app.running else '🔴 Inactive'}</td></tr>
                        <tr><td>Gemini Keys</td><td>🟢 {len(GEMINI_API_KEYS)} configured</td></tr>
                        <tr><td>Groq API</td><td>{'🟢 Active' if GROQ_API_KEY else '🔴 Not configured'}</td></tr>
                    </table>
                </div>
                
                <div class="section">
                    <p><small>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html, 200
        
    except Exception as e:
        logger.error(f"Status page error: {e}")
        return f"<h1>Error</h1><p>{str(e)}</p>", 500

@flask_app.route('/metrics', methods=['GET'])
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    try:
        queue_stats = translation_queue.get_stats()
        cache_stats = await db.get_cache_stats()
        
        uptime = datetime.now() - startup_time
        uptime_seconds = uptime.total_seconds()
        
        # Prometheus format metrics
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
        logger.error(f"Metrics endpoint error: {e}")
        return f"# Error generating metrics\n# {str(e)}", 500

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

def main():
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi
    port = int(os.environ.get("PORT", 8080))
    asgi_app = WsgiToAsgi(flask_app)
    
    async def run_webhook_server():
        """Run the web server for health checks and webhook."""
        config = uvicorn.Config(
            app=asgi_app,
            host="0.0.0.0",
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def run():
        # Initialize database first
        await db.connect()
        logger.info(f"💾 Database connected: {DATABASE_PATH}")
        
        # Start translation queue worker
        await translation_queue.start_worker(ptb_app)
        
        try:
            # Initialize the application
            await ptb_app.initialize()
            await ptb_app.start()
            await setup_commands(ptb_app)
            
            if BASE_URL:
                # Production: Use webhook mode
                await ptb_app.bot.set_webhook(url=f"{BASE_URL}/webhook")
                logger.info(f"🚀 Webhook mode: {BASE_URL}/webhook")
                logger.info("🤖 Bot is running with webhook")
                
                # Run webhook server (this blocks)
                await run_webhook_server()
            else:
                # Local testing: Use polling mode
                logger.info("🔄 Polling mode (local testing)")
                logger.info("🤖 Bot is now listening for messages...")
                logger.info("💡 Send /start to your bot on Telegram to test!")
                
                # Start polling
                await ptb_app.updater.start_polling(drop_pending_updates=True)
                
                # Run web server in background for health checks
                web_task = asyncio.create_task(run_webhook_server())
                
                # Keep running until interrupted
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
            
            # Stop the application
            await ptb_app.stop()
            await ptb_app.shutdown()
            
        finally:
            # Cleanup
            await translation_queue.stop_worker()
            await db.close()
            logger.info("💾 Database connection closed")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()
