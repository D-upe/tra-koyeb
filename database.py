import os
import logging
import asyncio
import aiosqlite
from datetime import datetime

try:
    import psycopg
except ImportError:
    psycopg = None

from config import DATABASE_PATH, DATABASE_URL

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path=DATABASE_PATH, db_url=DATABASE_URL):
        self.db_path = db_path
        self.db_url = db_url
        self._connection = None
        self.is_pg = False
    
    async def connect(self):
        if self.db_url:
            # Fix for common copy-paste error where "psql " is included in the URL
            if self.db_url.startswith("psql "):
                self.db_url = self.db_url.replace("psql ", "", 1).strip()
            
            # Remove potential wrapping quotes from the URL
            self.db_url = self.db_url.strip("'").strip('"')
            
            try:
                # PostgreSQL (psycopg 3)
                self._connection = await psycopg.AsyncConnection.connect(self.db_url, autocommit=True)
                self.is_pg = True
                logger.info("📡 Connected to external PostgreSQL database")
            except Exception as e:
                logger.error(f"❌ Failed to connect to PostgreSQL: {e}. Falling back to SQLite.")
                self._connection = await aiosqlite.connect(self.db_path)
                self.is_pg = False
        else:
            # SQLite
            self._connection = await aiosqlite.connect(self.db_path)
            self.is_pg = False
            logger.info(f"💾 Using local SQLite database: {self.db_path}")

        if not self.is_pg:
            await self._connection.execute('PRAGMA foreign_keys = ON')
        
        await self._create_tables()
    
    async def close(self):
        if self._connection:
            await self._connection.close()
    
    def _p(self, query):
        """Adapt placeholders to the current database engine."""
        if self.is_pg:
            return query.replace('?', '%s')
        return query

    async def execute(self, query, params=None):
        """Unified execute method for both SQLite and PostgreSQL."""
        query = self._p(query)
        try:
            if self.is_pg:
                return await self._connection.execute(query, params)
            else:
                # aiosqlite execute is a coroutine that returns a cursor
                return await self._connection.execute(query, params)
        except Exception as e:
            logger.error(f"Database Error: {e} | Query: {query} | Params: {params}")
            raise

    async def commit(self):
        """Unified commit (PostgreSQL in autocommit mode doesn't need it, but SQLite does)."""
        if not self.is_pg and self._connection:
            await self._connection.commit()

    async def _create_tables(self):
        # Shared types/syntax adjustments
        serial_type = "SERIAL PRIMARY KEY" if self.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        
        # 1. Users table
        await self.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                dialect TEXT DEFAULT 'standard',
                context_mode INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. History table
        await self.execute(f'''
            CREATE TABLE IF NOT EXISTS history (
                id {serial_type},
                user_id BIGINT,
                text TEXT,
                time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # 3. Favorites table
        await self.execute(f'''
            CREATE TABLE IF NOT EXISTS favorites (
                id {serial_type},
                user_id BIGINT,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # 4. Cache table
        await self.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                text TEXT,
                dialect TEXT DEFAULT 'standard',
                translation TEXT NOT NULL,
                hit_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (text, dialect)
            )
        ''')
        
        # 5. Rate limits table
        await self.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id BIGINT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                window_start TEXT
            )
        ''')
        
        # 6. Admin users table
        await self.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                is_admin INTEGER DEFAULT 1,
                can_grant_access INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 7. Packages table
        await self.execute(f'''
            CREATE TABLE IF NOT EXISTS packages (
                package_id {serial_type},
                name TEXT NOT NULL,
                description TEXT,
                translations_limit INTEGER DEFAULT 14,
                window_minutes INTEGER DEFAULT 60,
                price_usd REAL DEFAULT 0.0,
                duration_days INTEGER DEFAULT 30,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # 8. Subscriptions table
        await self.execute(f'''
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                subscription_id {serial_type},
                user_id BIGINT,
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
        packages_data = [
            (1, 'Free', 'Basic free tier', 14, 60, 0.0, 36500),
            (2, 'Basic', '50 translations per hour', 50, 60, 4.99, 30),
            (3, 'Pro', '200 translations per hour', 200, 60, 9.99, 30),
            (4, 'Unlimited', 'Unlimited translations', 999999, 60, 19.99, 30)
        ]
        
        for pkg in packages_data:
            if self.is_pg:
                await self.execute(
                    'INSERT INTO packages (package_id, name, description, translations_limit, window_minutes, price_usd, duration_days) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (package_id) DO NOTHING',
                    pkg
                )
            else:
                await self.execute(
                    'INSERT OR IGNORE INTO packages (package_id, name, description, translations_limit, window_minutes, price_usd, duration_days) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    pkg
                )
        
        await self.execute('UPDATE packages SET translations_limit = 14 WHERE package_id = 1 AND translations_limit = 10')
        await self.commit()
    
    async def get_user(self, user_id):
        cursor = await self.execute('SELECT dialect, context_mode FROM users WHERE user_id = ?', (user_id,))
        row = await cursor.fetchone()
        
        if not row:
            await self.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
            await self.commit()
            return {'dialect': 'standard', 'context_mode': True}
        
        return {'dialect': row[0], 'context_mode': bool(row[1])}
    
    async def update_user_dialect(self, user_id, dialect):
        if self.is_pg:
            await self.execute(
                'INSERT INTO users (user_id, dialect) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET dialect = EXCLUDED.dialect',
                (user_id, dialect)
            )
        else:
            await self.execute('INSERT OR REPLACE INTO users (user_id, dialect) VALUES (?, ?)', (user_id, dialect))
        await self.commit()
    
    async def get_history(self, user_id, limit=10):
        time_func = 'TO_CHAR(time, \'HH24:MI\')' if self.is_pg else 'strftime("%H:%M", time)'
        cursor = await self.execute(f'SELECT text, {time_func} as time FROM history WHERE user_id = ? ORDER BY time DESC LIMIT ?', (user_id, limit))
        rows = await cursor.fetchall()
        return [{'text': row[0], 'time': row[1]} for row in rows]
    
    async def add_history(self, user_id, text):
        await self.execute('INSERT INTO history (user_id, text) VALUES (?, ?)', (user_id, text))
        await self.commit()
    
    async def get_favorites(self, user_id):
        cursor = await self.execute('SELECT text FROM favorites WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
    
    async def add_favorite(self, user_id, text):
        cursor = await self.execute('SELECT 1 FROM favorites WHERE user_id = ? AND text = ?', (user_id, text))
        if await cursor.fetchone(): return False
        await self.execute('INSERT INTO favorites (user_id, text) VALUES (?, ?)', (user_id, text))
        await self.commit(); return True
    
    async def get_cached_translation(self, text, dialect='standard'):
        cursor = await self.execute('SELECT translation FROM cache WHERE text = ? AND dialect = ?', (text.lower().strip(), dialect))
        row = await cursor.fetchone()
        if row:
            await self.execute('UPDATE cache SET hit_count = hit_count + 1, last_used = CURRENT_TIMESTAMP WHERE text = ? AND dialect = ?', (text.lower().strip(), dialect))
            await self.commit(); return row[0]
        return None
    
    async def cache_translation(self, text, dialect, translation):
        try:
            if self.is_pg:
                await self.execute('INSERT INTO cache (text, dialect, translation) VALUES (?, ?, ?) ON CONFLICT (text, dialect) DO UPDATE SET translation = EXCLUDED.translation, last_used = CURRENT_TIMESTAMP', (text.lower().strip(), dialect, translation))
            else:
                await self.execute('INSERT OR REPLACE INTO cache (text, dialect, translation) VALUES (?, ?, ?)', (text.lower().strip(), dialect, translation))
            await self.commit()
        except Exception as e: logger.error(f"Cache error: {e}")
    
    async def get_cache_stats(self):
        try:
            cursor = await self.execute('SELECT COUNT(*) FROM cache')
            row = await cursor.fetchone()
            total = row[0] if row else 0
            
            cursor = await self.execute('SELECT SUM(hit_count) FROM cache')
            row = await cursor.fetchone()
            hits = row[0] if row and row[0] is not None else 0
            
            cursor = await self.execute('SELECT COUNT(*) FROM cache WHERE hit_count > 0')
            row = await cursor.fetchone()
            used = row[0] if row else 0
            
            return {
                'total_entries': total, 
                'total_hits': hits,
                'used_entries': used
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {'total_entries': 0, 'total_hits': 0, 'used_entries': 0}

    async def check_rate_limit(self, user_id, max_requests=10, window_minutes=60):
        cursor = await self.execute('SELECT request_count, window_start FROM rate_limits WHERE user_id = ?', (user_id,))
        row = await cursor.fetchone(); now = datetime.now()
        if not row:
            await self.execute('INSERT INTO rate_limits (user_id, request_count, window_start) VALUES (?, 1, ?)', (user_id, now.isoformat()))
            await self.commit(); return True, max_requests - 1, window_minutes
        request_count, window_start = row
        window_start = datetime.fromisoformat(window_start)
        time_elapsed = (now - window_start).total_seconds() / 60
        if time_elapsed >= window_minutes:
            await self.execute('UPDATE rate_limits SET request_count = 1, window_start = ? WHERE user_id = ?', (now.isoformat(), user_id))
            await self.commit(); return True, max_requests - 1, window_minutes
        if request_count >= max_requests: return False, 0, window_minutes - int(time_elapsed)
        await self.execute('UPDATE rate_limits SET request_count = request_count + 1 WHERE user_id = ?', (user_id,))
        await self.commit(); return True, max_requests - request_count - 1, window_minutes - int(time_elapsed)

    async def is_user_allowed(self, user_id):
        cursor = await self.execute('SELECT 1 FROM admin_users WHERE user_id = ?', (user_id,))
        if await cursor.fetchone(): return True, "admin"
        end_check = "s.end_date > CURRENT_TIMESTAMP" if self.is_pg else "s.end_date > datetime('now')"
        cursor = await self.execute(f'SELECT s.subscription_id, p.name FROM user_subscriptions s JOIN packages p ON s.package_id = p.package_id WHERE s.user_id = ? AND s.is_active = 1 AND (s.end_date IS NULL OR {end_check})', (user_id,))
        row = await cursor.fetchone()
        if row: return True, row[1]
        cursor = await self.execute('SELECT COUNT(*) FROM admin_users'); 
        if (await cursor.fetchone())[0] > 0: return False, None
        return True, "free"

    async def get_user_limits(self, user_id):
        end_check = "s.end_date > CURRENT_TIMESTAMP" if self.is_pg else "s.end_date > datetime('now')"
        cursor = await self.execute(f'SELECT p.translations_limit, p.window_minutes, p.name, p.price_usd FROM user_subscriptions s JOIN packages p ON s.package_id = p.package_id WHERE s.user_id = ? AND s.is_active = 1 AND (s.end_date IS NULL OR {end_check}) ORDER BY p.translations_limit DESC LIMIT 1', (user_id,))
        row = await cursor.fetchone()
        if row: return {'limit': row[0], 'window': row[1], 'tier': row[2], 'price': row[3]}
        cursor = await self.execute('SELECT 1 FROM admin_users WHERE user_id = ?', (user_id,))
        if await cursor.fetchone(): return {'limit': 999999, 'window': 60, 'tier': 'admin', 'price': 0}
        return {'limit': 14, 'window': 60, 'tier': 'free', 'price': 0}

    async def add_admin(self, user_id, username=None, can_grant_access=False):
        try:
            if self.is_pg:
                await self.execute('INSERT INTO admin_users (user_id, username, can_grant_access) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, can_grant_access = EXCLUDED.can_grant_access', (user_id, username, 1 if can_grant_access else 0))
            else:
                await self.execute('INSERT OR REPLACE INTO admin_users (user_id, username, can_grant_access) VALUES (?, ?, ?)', (user_id, username, 1 if can_grant_access else 0))
            await self.commit(); return True
        except Exception as e: logger.error(f"Error adding admin: {e}"); return False

    async def grant_access(self, user_id, package_id=1, duration_days=30):
        try:
            end_date = None if duration_days > 1000 else datetime.now().timestamp() + (duration_days * 86400)
            date_conv = "TO_TIMESTAMP(?)" if self.is_pg else "datetime(?, 'unixepoch')"
            await self.execute(f'INSERT INTO user_subscriptions (user_id, package_id, end_date, is_active) VALUES (?, ?, {date_conv}, 1)', (user_id, package_id, end_date))
            await self.commit(); return True
        except Exception as e: logger.error(f"Error granting access: {e}"); return False

    async def revoke_access(self, user_id):
        try:
            await self.execute('UPDATE user_subscriptions SET is_active = 0 WHERE user_id = ?', (user_id,))
            await self.commit(); return True
        except Exception as e: logger.error(f"Error revoking access: {e}"); return False

    async def get_all_packages(self):
        cursor = await self.execute("SELECT package_id, name, description, translations_limit, price_usd, duration_days FROM packages WHERE is_active = 1 ORDER BY price_usd")
        rows = await cursor.fetchall()
        return [{'id': r[0], 'name': r[1], 'description': r[2], 'limit': r[3], 'price': r[4], 'duration': r[5]} for r in rows]

    async def get_user_subscription(self, user_id):
        cursor = await self.execute('SELECT p.name, p.translations_limit, s.end_date, s.translations_used, p.price_usd FROM user_subscriptions s JOIN packages p ON s.package_id = p.package_id WHERE s.user_id = ? AND s.is_active = 1 ORDER BY s.start_date DESC LIMIT 1', (user_id,))
        row = await cursor.fetchone()
        if row: return {'tier': row[0], 'limit': row[1], 'expires': row[2], 'used': row[3], 'price': row[4]}
        return None

# Global DB instance
db = Database()
