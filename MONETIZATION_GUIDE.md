# 💰 Darja Bot Monetization Guide

## Features Added

### 1. 🔒 Whitelist System
- Only approved users can access the bot
- Admin users have full control
- Others are blocked with contact button

### 2. 💎 Subscription Tiers

| Tier | Translations/Hour | Price | Duration |
|------|------------------|-------|----------|
| Free | 10 | $0 | Forever |
| Basic | 50 | $4.99/mo | 30 days |
| Pro | 200 | $9.99/mo | 30 days |
| Unlimited | Unlimited | $19.99/mo | 30 days |

### 3. 📊 New Commands

**User Commands:**
- `/subscription` - View your current subscription status
- `/packages` - View available packages and pricing
- `/start` - Shows your tier and limits

**Admin Commands:**
- `/whitelist add <user_id> [@username]` - Add user to whitelist
- `/whitelist remove <user_id>` - Remove user from whitelist
- `/grant <user_id> [package_id] [duration_days]` - Grant paid access
- `/revoke <user_id>` - Revoke user access

## Setup Instructions

### Step 1: Run the Bot Once
```bash
./run_test.sh
```
Let it run for 10 seconds to create the database, then stop it (Ctrl+C).

### Step 2: Setup Yourself as Admin
```bash
source venv/bin/activate
python setup_admin.py
```

You'll need:
- Your Telegram User ID (get it from @userinfobot)
- Your Telegram username (optional)

### Step 3: Run the Bot Again
```bash
./run_test.sh
```

### Step 4: Test

**Test 1: Admin Access**
- Send `/start` → Should show "Unlimited Member"

**Test 2: Check Packages**
- Send `/packages` → Shows all pricing tiers

**Test 3: Grant Access to Others**
- Find a friend's User ID
- Send: `/whitelist add 123456789 @friendusername`

**Test 4: Rate Limiting**
- Ask friend to send 11 messages quickly
- 11th should show upgrade buttons

## Managing Users

### Grant Free Access (Whitelist)
```
/whitelist add 123456789 @username
```

### Grant Paid Package
```
/grant 123456789 2 30
```
- User 123456789 gets Basic package (id=2) for 30 days

### Revoke Access
```
/revoke 123456789
```

### Check User Status
Ask user to send `/subscription` - they'll see their tier.

## Payment Flow

Currently, payments are manual (contact-based):

1. **User hits limit** → Sees upgrade buttons
2. **Clicks upgrade** → Gets your contact info (@Erivative)
3. **User messages you** → You collect payment manually (PayPal, Venmo, etc.)
4. **You grant access** → `/grant <user_id> <package_id> <days>`

### Future Enhancement: Automated Payments
To automate, you'd need:
- Stripe/PayPal integration
- Payment webhook handlers
- Automatic package assignment after payment

## Database Tables

**admin_users** - Whitelisted admins
**packages** - Subscription tiers
**user_subscriptions** - Active subscriptions

View with:
```bash
python view_db.py
```

## Customization

### Change Pricing
Edit the packages in `app.py` around line 140:
```python
# Default packages
await self._connection.execute('''
    INSERT OR IGNORE INTO packages ...
''')
```

### Change Free Tier Limits
Edit in the same place, change `translations_limit` for package_id=1.

### Change Admin Contact
Find and replace `@Erivative` with your username in:
- `handle_message()` - whitelist rejection message
- `upgrade_callback()` - upgrade contact info

## Monitoring

Track revenue manually by querying the database:
```sql
-- Count paid users
SELECT COUNT(*) FROM user_subscriptions 
WHERE package_id > 1 AND is_active = 1;

-- Calculate potential revenue
SELECT SUM(p.price_usd) 
FROM user_subscriptions s 
JOIN packages p ON s.package_id = p.package_id 
WHERE s.is_active = 1;
```

## Tips

1. **Start with free tier** to build user base
2. **Add value** before asking for payment (more translations, better features)
3. **Track usage** - see which features users love
4. **Offer trials** - grant Pro access for 7 days to convert users
5. **Communicate** - use the bot to announce new features

## Next Steps

✅ Bot is ready to monetize!
- Set yourself as admin
- Whitelist beta users
- Collect feedback
- Adjust pricing based on demand

🚀 Optional enhancements:
- Stripe integration for automatic payments
- Referral system (give free translations for referrals)
- Promo codes system
- Usage analytics dashboard
