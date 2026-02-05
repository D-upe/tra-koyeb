#!/usr/bin/env python3
"""Setup script to initialize yourself as admin and configure the bot."""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment
load_dotenv('.env.test') or load_dotenv('.env')

import aiosqlite

DB_PATH = os.getenv('DATABASE_PATH', 'translations.db')

async def setup():
    """Initialize admin and grant yourself access."""
    print("🔧 Darja Bot Admin Setup")
    print("=" * 50)
    print()
    
    if not os.path.exists(DB_PATH):
        print("❌ Database not found!")
        print("   Please run the bot first to create the database.")
        print("   Run: ./run_test.sh")
        return
    
    print(f"📁 Database: {DB_PATH}")
    print()
    
    # Get your Telegram User ID
    print("📝 To set yourself as admin, I need your Telegram User ID.")
    print("   How to find it:")
    print("   1. Message @userinfobot on Telegram")
    print("   2. It will reply with your User ID")
    print()
    
    user_id = input("Enter your Telegram User ID: ").strip()
    
    if not user_id.isdigit():
        print("❌ Invalid User ID. Please enter only numbers.")
        return
    
    user_id = int(user_id)
    username = input("Enter your Telegram username (without @): ").strip() or None
    
    print()
    print(f"Setting up admin:")
    print(f"  User ID: {user_id}")
    print(f"  Username: @{username if username else 'N/A'}")
    print()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Check current tables
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = [row[0] for row in await cursor.fetchall()]
            print(f"✅ Database tables: {', '.join(tables)}")
        
        # Add yourself as admin
        await db.execute(
            "INSERT OR REPLACE INTO admin_users (user_id, username, can_grant_access) VALUES (?, ?, 1)",
            (user_id, username)
        )
        
        # Grant yourself unlimited access (package_id 4 = Unlimited)
        await db.execute(
            """INSERT OR REPLACE INTO user_subscriptions 
               (user_id, package_id, is_active, end_date) 
               VALUES (?, 4, 1, datetime('now', '+100 years'))""",
            (user_id,)
        )
        
        await db.commit()
        
        print()
        print("✅ Setup complete!")
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
        print("  1 = Free (10 translations/hour)")
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
