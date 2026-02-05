# 💳 Payment Collection Guide for Darja Bot

## Option 1: Manual Payment (Easiest - Start Here)

### How it works:
1. User hits limit → Sees upgrade buttons with your contact
2. User messages you on Telegram (@Erivative)
3. You collect payment manually
4. You manually grant access with `/grant` command

### Payment Methods:

**A. PayPal**
- Create PayPal.Me link: paypal.me/yourname
- User sends money → You confirm → Grant access
- Pros: Easy, no fees for friends/family
- Cons: Manual confirmation

**B. Venmo / Cash App**
- Similar to PayPal
- Share your username
- User pays → Screenshot → You verify → Grant access

**C. Cryptocurrency**
- Bitcoin, Ethereum, USDT
- User sends crypto → You verify on blockchain → Grant access
- Pros: No chargebacks, global
- Cons: Price volatility

**D. Bank Transfer**
- Share IBAN/SWIFT for international
- Or local bank details
- Pros: Low fees
- Cons: Slow, user needs banking app

### Workflow Example:

**User:** (hits limit, clicks "Upgrade to Pro")
**Bot:** "Contact @Erivative to upgrade. Your User ID: 123456789"

**User messages you:**
"Hi! I want to upgrade to Pro. My ID is 123456789"

**You reply:**
"Great! Pro is $9.99/month. Pay here: paypal.me/yourname/9.99
Once paid, send me the screenshot!"

**User sends payment + screenshot**

**You:**
```
/grant 123456789 3 30
```
(3 = Pro package, 30 = 30 days)

**Bot confirms:** ✅ Access granted!

---

## Option 2: Semi-Automated (Stripe/PayPal)

### Stripe Payment Links
1. Create Stripe account: stripe.com
2. Create "Product" for each tier
   - Basic: $4.99
   - Pro: $9.99
   - Unlimited: $19.99
3. Create "Payment Link" for each
4. Store links in bot

### Updated Bot Flow:
1. User clicks upgrade → Gets Stripe payment link
2. User pays on Stripe
3. Stripe sends YOU email notification
4. You manually grant access with `/grant`

### Setup:
```bash
# Add to .env.test
STRIPE_BASIC_LINK=https://buy.stripe.com/...
STRIPE_PRO_LINK=https://buy.stripe.com/...
STRIPE_UNLIMITED_LINK=https://buy.stripe.com/...
```

### Pros:
- Professional payment page
- Credit cards accepted
- Automatic receipts
- Safer than manual

### Cons:
- 2.9% + $0.30 fee per transaction
- Still requires manual granting
- Need to verify User ID somehow

---

## Option 3: Fully Automated (Advanced)

### Telegram Payments API
Uses Telegram's built-in payment system:

**Setup:**
1. Message @BotFather → /mybots → Select bot → Payments
2. Choose provider (Stripe, etc.)
3. Get provider token
4. Add to bot code

**Pros:**
- Native Telegram experience
- Apple Pay / Google Pay support
- Fully automated
- User never leaves Telegram

**Cons:**
- Requires coding
- Provider fees (Stripe: 2.9% + $0.30)
- Telegram takes no cut but provider does

### Implementation:
Would need to add:
```python
# When user clicks upgrade
await update.message.reply_invoice(
    title="Pro Subscription",
    description="200 translations/hour",
    payload="pro_30days",
    provider_token=STRIPE_TOKEN,
    currency="USD",
    prices=[{"label": "Pro", "amount": 999}]  # $9.99 in cents
)

# After successful payment
async def successful_payment(update, context):
    user_id = update.effective_user.id
    await db.grant_access(user_id, package_id=3, duration_days=30)
    await update.message.reply_text("✅ Payment received! You now have Pro access!")
```

---

## Option 4: Buy Me a Coffee / Ko-fi

**Simple donation-style:**
- Set up: buymeacoffee.com or ko-fi.com
- Link in bot: "Support the bot"
- Users donate any amount
- You manually grant based on donation amount

**Pros:**
- Super easy setup
- No programming
- Feels like supporting, not paying

**Cons:**
- Not automated
- Users might donate wrong amount
- Manual tracking

---

## Recommended Strategy (Start Here!)

### Phase 1: Manual (Weeks 1-4)
**PayPal + Manual granting**
- Start free to build user base
- Collect feedback
- Perfect your translations
- See if users actually want to pay

### Phase 2: Semi-Automated (Month 2)
**Stripe Payment Links**
- If you have 10+ paying users
- Create professional payment pages
- Still manual granting (but safer)

### Phase 3: Automated (Month 3+)
**Telegram Payments API**
- If making $100+/month consistently
- Worth the dev effort
- Fully automated experience

---

## Quick Start: PayPal Manual

### 1. Create PayPal.Me Link
1. Go to paypal.me
2. Create your link: paypal.me/YourName
3. Test it works

### 2. Update Bot Contact
In `app.py`, find `@Erivative` and change to your username.

### 3. Set Response Template
Save this in notes for quick replies:

```
Thanks for your interest in upgrading! 🚀

Here are the options:
• Basic (50 translations/hour) - $4.99
• Pro (200 translations/hour) - $9.99  
• Unlimited - $19.99

Pay here: paypal.me/YOURNAME/AMOUNT

After paying, send me:
1. Screenshot of payment
2. Your User ID: [their ID]

I'll activate your access within 1 hour!
```

### 4. Grant Access
When payment confirmed:
```
/grant USER_ID PACKAGE_ID DAYS

Examples:
/grant 123456789 2 30    # Basic, 30 days
/grant 123456789 3 30    # Pro, 30 days
/grant 123456789 4 30    # Unlimited, 30 days
```

---

## Tracking Revenue

### Manual Tracking (Spreadsheet)
| Date | User | Tier | Amount | Granted? | Expires |
|------|------|------|--------|----------|---------|
| 2024-01-15 | @user1 | Pro | $9.99 | ✅ | 2024-02-15 |

### Automated Tracking (SQL)
```bash
python view_db.py

# Or query directly:
# Total revenue potential
sqlite3 test_translations.db "SELECT SUM(price_usd) FROM packages p JOIN user_subscriptions s ON p.package_id = s.package_id WHERE s.is_active = 1;"
```

---

## Tax Considerations

⚠️ **Important:** 
- Check your local tax laws
- Keep records of income
- PayPal/Business accounts report to IRS (USA) over $600/year
- Consider registering as business if making significant income

---

## Pricing Tips

1. **Start lower**: $2.99, $5.99, $9.99 initially
2. **Test demand**: See what users actually pay
3. **Annual discount**: Offer 2 months free for yearly (e.g., $99/year instead of $120)
4. **Trial periods**: Give 3-day free Pro trial
5. **Limited offers**: "50% off this week only"

---

## My Recommendation

**Start with Option 1 (Manual PayPal):**
- Takes 10 minutes to setup
- No coding needed
- See if anyone pays first
- Perfect for testing

**Move to Option 2 (Stripe Links) when:**
- 5+ people paying monthly
- Too time-consuming to handle manually
- Want to look more professional

**Never build Option 3 unless:**
- Making $500+/month
- Have time to code it
- Stripe fees are worth the automation

---

## Need Help?

- **PayPal**: paypal.com/help
- **Stripe**: stripe.com/docs
- **Telegram Payments**: core.telegram.org/bots/payments

Start simple, scale later! 🚀
