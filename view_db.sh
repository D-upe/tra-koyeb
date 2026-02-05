#!/bin/bash
# SQLite Database Viewer for Darja Bot

echo "📊 Darja Bot Database Viewer"
echo "============================"
echo ""

# Load environment to get DB path
set -a
source .env.test 2>/dev/null || source .env 2>/dev/null
set +a

DB_PATH="${DATABASE_PATH:-./test_translations.db}"

if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database not found: $DB_PATH"
    echo "   The bot needs to run first to create the database."
    exit 1
fi

echo "📁 Database: $DB_PATH"
echo "💾 Size: $(ls -lh "$DB_PATH" | awk '{print $5}')"
echo ""

# Function to run SQL queries
run_query() {
    sqlite3 "$DB_PATH" "$1"
}

echo "1️⃣  USERS TABLE"
echo "---------------"
echo "Total users: $(run_query "SELECT COUNT(*) FROM users;")"
run_query "SELECT user_id, dialect, context_mode, created_at FROM users LIMIT 10;" | column -t -s '|'
echo ""

echo "2️⃣  HISTORY TABLE (Last 10 translations)"
echo "----------------------------------------"
echo "Total history entries: $(run_query "SELECT COUNT(*) FROM history;")"
run_query ".mode column
.headers on
SELECT h.id, u.user_id, h.text, h.time 
FROM history h 
JOIN users u ON h.user_id = u.user_id 
ORDER BY h.time DESC 
LIMIT 10;"
echo ""

echo "3️⃣  FAVORITES TABLE"
echo "-------------------"
echo "Total favorites: $(run_query "SELECT COUNT(*) FROM favorites;")"
run_query ".mode column
.headers on
SELECT f.id, u.user_id, substr(f.text, 1, 50) as text_preview, f.created_at 
FROM favorites f 
JOIN users u ON f.user_id = u.user_id 
ORDER BY f.created_at DESC 
LIMIT 10;"
echo ""

echo "4️⃣  CACHE TABLE (Translation cache)"
echo "-----------------------------------"
echo "Total cached translations: $(run_query "SELECT COUNT(*) FROM cache;")"
echo "Total cache hits: $(run_query "SELECT COALESCE(SUM(hit_count), 0) FROM cache;")"
run_query ".mode column
.headers on
SELECT text, dialect, hit_count, last_used 
FROM cache 
ORDER BY hit_count DESC 
LIMIT 10;"
echo ""

echo "5️⃣  RATE LIMITS TABLE"
echo "---------------------"
echo "Active rate limit entries: $(run_query "SELECT COUNT(*) FROM rate_limits;")"
run_query ".mode column
.headers on
SELECT user_id, request_count, window_start 
FROM rate_limits 
ORDER BY request_count DESC 
LIMIT 10;"
echo ""

echo "✅ Database view complete!"
