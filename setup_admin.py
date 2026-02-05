#!/usr/bin/env python3
"""Setup script to initialize yourself as admin and configure the bot."""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment
load_dotenv('.env.test') or load_dotenv('.env')

import aiosqlite

try:
    import psycopg
except ImportError:
    psycopg = None

DB_URL = os.getenv('DATABASE_URL')
DB_PATH = os.getenv('DATABASE_PATH', 'translations.db')

async def setup():
    """Initialize admin and grant yourself access."""
    print("🔧 Darja Bot Admin Setup")
    print("=" * 50)
    print()
    
    is_pg = False
    if DB_URL:
        print("📡 Using PostgreSQL database")
        is_pg = True
    elif os.path.exists(DB_PATH):
        print(f"📁 Using local SQLite database: {DB_PATH}")
    else:
        print("❌ Database not found!")
        print("   Please run the bot first or set DATABASE_URL.")
        return
    
    # Get your Telegram User ID
    print("\n📝 To set yourself as admin, I need your Telegram User ID.")
    print("   Get it from @userinfobot")
    print()
    
    user_id = input("Enter your Telegram User ID: ").strip()
    if not user_id.isdigit():
        print("❌ Invalid User ID."); return
    
    user_id = int(user_id)
    username = input("Enter your Telegram username (without @): ").strip() or None
    
    if is_pg:
        conn = await psycopg.AsyncConnection.connect(DB_URL)
    else:
        conn = await aiosqlite.connect(DB_PATH)

    async with conn:
        # Add yourself as admin
        if is_pg:
            await conn.execute(
                "INSERT INTO admin_users (user_id, username, can_grant_access) VALUES (%s, %s, 1) "
                "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, can_grant_access = 1",
                (user_id, username)
            )
            # Grant yourself unlimited access
            await conn.execute(
                "INSERT INTO user_subscriptions (user_id, package_id, is_active, end_date) "
                "VALUES (%s, 4, 1, CURRENT_TIMESTAMP + INTERVAL '100 years') "
                "ON CONFLICT DO NOTHING",
                (user_id,)
            )
        else:
            await conn.execute(
                "INSERT OR REPLACE INTO admin_users (user_id, username, can_grant_access) VALUES (?, ?, 1)",
                (user_id, username)
            )
            await conn.execute(
                "INSERT OR REPLACE INTO user_subscriptions (user_id, package_id, is_active, end_date) "
                "VALUES (?, 4, 1, datetime('now', '+100 years'))",
                (user_id,)
            )
        
        await conn.commit()
        print("\n✅ Setup complete! You are now an admin.")
        print()
        print("You are now:")
        print("  • Admin with full access")
        print("  • Unlimited translations")
        print("  • Can grant access to other users")
        print()
        print("Admin commands available:")
        print("  /whitelist add <user_id> [@username]")
        print("  /whitelist remove <user_id>")
        print("  /grant <user_id> [package_id] [duration_days]")
        print("  /revoke <user_id>")
        print()
        print("Packages:")
        print("  1 = Free (14 translations/hour)")
        print("  2 = Basic (50 translations/hour) - $4.99/mo")
        print("  3 = Pro (200 translations/hour) - $9.99/mo")
        print("  4 = Unlimited - $19.99/mo")

if __name__ == '__main__':
    try:
        asyncio.run(setup())
    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
