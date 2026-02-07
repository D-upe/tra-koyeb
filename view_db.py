#!/usr/bin/env python3
"""View Darja Bot SQLite Database"""

import os
import sys
from datetime import datetime

# Load environment
from dotenv import load_dotenv
load_dotenv('.env.test') or load_dotenv('.env')

import aiosqlite
import asyncio

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

DATABASE_URL = os.getenv('DATABASE_URL')
DB_PATH = os.getenv('DATABASE_PATH', 'translations.db')

class UnifiedDB:
    def __init__(self, db_path, db_url=None):
        self.db_path = db_path
        self.db_url = db_url
        self.conn = None
        self.is_pg = False

    async def connect(self):
        if self.db_url and psycopg:
            try:
                self.conn = await psycopg.AsyncConnection.connect(self.db_url, autocommit=True)
                self.is_pg = True
                return True
            except Exception as e:
                print(f"⚠️ Failed to connect to PostgreSQL: {e}")
        
        if os.path.exists(self.db_path):
            self.conn = await aiosqlite.connect(self.db_path)
            self.is_pg = False
            return True
        return False

    def p(self, query):
        if self.is_pg:
            return query.replace('?', '%s')
        return query

    async def execute(self, query, params=None):
        query = self.p(query)
        if self.is_pg and self.conn:
            cur = await self.conn.execute(query, params)
            return cur
        elif self.conn:
            return await self.conn.execute(query, params)
        raise Exception("Database not connected")

    async def fetchall(self, cursor):
        return await cursor.fetchall()

    async def fetchone(self, cursor):
        return await cursor.fetchone()

    async def close(self):
        if self.conn:
            await self.conn.close()

async def view_database():
    """Display all database contents."""
    
    db = UnifiedDB(DB_PATH, DATABASE_URL)
    if not await db.connect():
        print(f"❌ Database not found or connection failed.")
        print(f"   DATABASE_URL: {'Set' if DATABASE_URL else 'Not set'}")
        print(f"   DATABASE_PATH: {DB_PATH} ({'Exists' if os.path.exists(DB_PATH) else 'Missing'})")
        return
    
    print("📊 Darja Bot Database Viewer")
    print("=" * 60)
    if db.is_pg and DATABASE_URL:
        # Mask the password in DATABASE_URL for display
        display_url = DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'PostgreSQL'
        print(f"🌐 Database: PostgreSQL ({display_url})")
    else:
        print(f"📁 Database: {DB_PATH} (SQLite)")
        if os.path.exists(DB_PATH):
            print(f"💾 Size: {os.path.getsize(DB_PATH) / 1024:.1f} KB")

    
    print()
    
    try:
        # 1. Users Table
        print("1️⃣  USERS TABLE")
        print("-" * 60)
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        count = (await db.fetchone(cursor))[0]
        print(f"Total users: {count}")
        
        cursor = await db.execute("SELECT user_id, dialect, context_mode, created_at FROM users ORDER BY created_at DESC LIMIT 10")
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'User ID':<15} {'Dialect':<12} {'Context Mode':<13} {'Created At'}")
            print("-" * 60)
            for row in rows:
                user_id, dialect, context_mode, created_at = row
                print(f"{user_id:<15} {dialect:<12} {'✅ On' if context_mode else '❌ Off':<13} {created_at}")
        print()
        
        # 2. History Table
        print("2️⃣  HISTORY TABLE (Last 10 translations)")
        print("-" * 60)
        cursor = await db.execute("SELECT COUNT(*) FROM history")
        count = (await db.fetchone(cursor))[0]
        print(f"Total history entries: {count}")
        
        cursor = await db.execute("""
            SELECT h.id, u.user_id, h.text, h.time 
            FROM history h 
            JOIN users u ON h.user_id = u.user_id 
            ORDER BY h.time DESC 
            LIMIT 10
        """)
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'ID':<5} {'User ID':<15} {'Text':<35} {'Time'}")
            print("-" * 60)
            for row in rows:
                id_, user_id, text, time = row
                text_preview = text[:32] + '...' if len(text) > 35 else text
                print(f"{id_:<5} {user_id:<15} {text_preview:<35} {time}")
        print()
        
        # 3. Favorites Table
        print("3️⃣  FAVORITES TABLE")
        print("-" * 60)
        cursor = await db.execute("SELECT COUNT(*) FROM favorites")
        count = (await db.fetchone(cursor))[0]
        print(f"Total favorites: {count}")
        
        cursor = await db.execute("""
            SELECT f.id, u.user_id, f.text, f.created_at 
            FROM favorites f 
            JOIN users u ON f.user_id = u.user_id 
            ORDER BY f.created_at DESC 
            LIMIT 10
        """)
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'ID':<5} {'User ID':<15} {'Text Preview':<40}")
            print("-" * 60)
            for row in rows:
                id_, user_id, text, created_at = row
                text_preview = text[:37] + '...' if len(text) > 40 else text
                print(f"{id_:<5} {user_id:<15} {text_preview}")
        print()
        
        # 4. Cache Table
        print("4️⃣  CACHE TABLE (Translation cache)")
        print("-" * 60)
        cursor = await db.execute("SELECT COUNT(*) FROM cache")
        count = (await db.fetchone(cursor))[0]
        print(f"Total cached translations: {count}")
        
        cursor = await db.execute("SELECT COALESCE(SUM(hit_count), 0) FROM cache")
        total_hits = (await db.fetchone(cursor))[0]
        print(f"Total cache hits: {total_hits}")
        
        cursor = await db.execute("""
            SELECT text, dialect, hit_count, last_used 
            FROM cache 
            ORDER BY hit_count DESC 
            LIMIT 10
        """)
        rows = await db.fetchall(cursor)
        if rows:
            print(f"\n{'Text':<25} {'Dialect':<12} {'Hits':<8} {'Last Used'}")
            print("-" * 60)
            for row in rows:
                text, dialect, hits, last_used = row
                text_preview = text[:22] + '...' if len(text) > 25 else text
                print(f"{text_preview:<25} {dialect:<12} {hits:<8} {last_used}")
        print()
        
        # 5. Rate Limits Table
        print("5️⃣  RATE LIMITS TABLE")
        print("-" * 60)
        cursor = await db.execute("SELECT COUNT(*) FROM rate_limits")
        count = (await db.fetchone(cursor))[0]
        print(f"Active rate limit entries: {count}")
        
        cursor = await db.execute("""
            SELECT user_id, request_count, window_start 
            FROM rate_limits 
            ORDER BY request_count DESC 
            LIMIT 10
        """)
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'User ID':<15} {'Requests':<10} {'Window Start'}")
            print("-" * 60)
            for row in rows:
                user_id, requests, window_start = row
                print(f"{user_id:<15} {requests:<10} {window_start}")
        print()
        
        # 6. Admin Users Table
        print("6️⃣  ADMIN USERS TABLE")
        print("-" * 60)
        cursor = await db.execute("SELECT user_id, username, is_admin, can_grant_access FROM admin_users")
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'User ID':<15} {'Username':<15} {'Admin':<7} {'Grant'}")
            print("-" * 60)
            for row in rows:
                user_id, username, is_admin, can_grant = row
                print(f"{user_id:<15} {str(username):<15} {'✅' if is_admin else '❌':<7} {'✅' if can_grant else '❌'}")
        print()

        # 7. Packages Table
        print("7️⃣  PACKAGES TABLE")
        print("-" * 60)
        cursor = await db.execute("SELECT package_id, name, translations_limit, price_usd, duration_days FROM packages")
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'ID':<4} {'Name':<12} {'Limit':<8} {'Price':<8} {'Duration'}")
            print("-" * 60)
            for row in rows:
                pid, name, limit, price, duration = row
                print(f"{pid:<4} {name:<12} {limit:<8} ${price:<7.2f} {duration} days")
        print()

        # 8. Subscriptions Table
        print("8️⃣  USER SUBSCRIPTIONS TABLE")
        print("-" * 60)
        cursor = await db.execute("""
            SELECT s.subscription_id, s.user_id, p.name, s.start_date, s.end_date, s.is_active
            FROM user_subscriptions s
            JOIN packages p ON s.package_id = p.package_id
            ORDER BY s.start_date DESC
            LIMIT 10
        """)
        rows = await db.fetchall(cursor)
        if rows:
            print(f"{'ID':<4} {'User ID':<15} {'Package':<12} {'End Date':<20} {'Active'}")
            print("-" * 60)
            for row in rows:
                sid, uid, pkg, start, end, active = row
                print(f"{sid:<4} {uid:<15} {pkg:<12} {str(end):<20} {'✅' if active else '❌'}")
        print()

        if not db.is_pg:
            # 9. Database Schema (SQLite only for simplicity)
            print("9️⃣  DATABASE SCHEMA")
            print("-" * 60)
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = await db.fetchall(cursor)
            print("Tables:")
            for table in tables:
                print(f"  • {table[0]}")
    
    except Exception as e:
        print(f"❌ Error while reading data: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()
    
    print()
    print("=" * 60)
    print("✅ Database view complete!")

if __name__ == '__main__':
    try:
        asyncio.run(view_database())
    except KeyboardInterrupt:
        print("\n\n👋 Viewer closed")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
