
import os
import asyncio
from dotenv import load_dotenv
load_dotenv('.env.test') or load_dotenv('.env')

try:
    import psycopg
except ImportError:
    print("❌ Error: psycopg not found. Run 'pip install \"psycopg[binary]\"'")
    exit(1)

DATABASE_URL = os.getenv('DATABASE_URL')

async def init_db():
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL not found in .env.test or .env")
        return

    print(f"📡 Connecting to Neon...")
    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
            print("✅ Connected!")
            
            # 1. Users table
            print("🏗️ Creating users table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    dialect TEXT DEFAULT 'standard',
                    context_mode INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 2. History table
            print("🏗️ Creating history table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    text TEXT,
                    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            ''')
            
            # 3. Favorites table
            print("🏗️ Creating favorites table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            ''')
            
            # 4. Cache table
            print("🏗️ Creating cache table...")
            await conn.execute('''
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
            print("🏗️ Creating rate_limits table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id BIGINT PRIMARY KEY,
                    request_count INTEGER DEFAULT 0,
                    window_start TEXT
                )
            ''')
            
            # 6. Admin users table
            print("🏗️ Creating admin_users table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admin_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    is_admin INTEGER DEFAULT 1,
                    can_grant_access INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 7. Packages table
            print("🏗️ Creating packages table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS packages (
                    package_id SERIAL PRIMARY KEY,
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
            print("🏗️ Creating user_subscriptions table...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    subscription_id SERIAL PRIMARY KEY,
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
            
            # 9. Default Packages
            print("📦 Inserting default packages...")
            packages = [
                (1, 'Free', 'Basic free tier', 14, 60, 0.0, 36500),
                (2, 'Basic', '50 translations per hour', 50, 60, 4.99, 30),
                (3, 'Pro', '200 translations per hour', 200, 60, 9.99, 30),
                (4, 'Unlimited', 'Unlimited translations', 999999, 60, 19.99, 30)
            ]
            for pkg in packages:
                await conn.execute(
                    'INSERT INTO packages (package_id, name, description, translations_limit, window_minutes, price_usd, duration_days) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (package_id) DO NOTHING',
                    pkg
                )

            print("\n✨ Database initialized successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
