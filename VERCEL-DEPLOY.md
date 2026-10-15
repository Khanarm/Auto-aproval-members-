# Auto Approve Bot — Vercel Webhook Build

This is a Vercel-compatible webhook rewrite based on the uploaded TechifyBots Auto-Approve-Bot project.

## Important differences
Vercel functions are short-lived serverless functions; they cannot run the original persistent Pyrogram client. This version uses the official Telegram Bot API webhook and keeps the core **automatic approval of new join requests**. It is not a line-for-line port of the original: Pyrogram user login/session and `/accept` bulk processing of old pending requests are not included in this Vercel build.

## Deploy
1. Push these files to the root of your GitHub repository.
2. Import that repository in Vercel and deploy.
3. Add environment variables in Vercel Project Settings → Environment Variables:
   - `BOT_TOKEN` — bot token from BotFather
   - `ADMIN` — your numeric Telegram user ID
   - `DB_URI` — MongoDB connection URI (optional, needed for stats/broadcast)
   - `DB_NAME` — optional; defaults to `approve`
   - `WEBHOOK_SECRET` — optional secret containing only letters/numbers/underscore/hyphen
   - `IS_FSUB` — `False` by default
   - `AUTH_CHANNELS` — space-separated numeric channel IDs, optional
4. Redeploy after adding variables.
5. Set the Telegram webhook. Replace `<BOT_TOKEN>`, `<VERCEL_URL>` and optional secret in a browser URL or HTTP client:
   `https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<VERCEL_URL>/api/index`
   If using `WEBHOOK_SECRET`, call `setWebhook` with `secret_token=<WEBHOOK_SECRET>` and use POST JSON for reliable encoding.
6. Add the bot to each channel/group as administrator and enable permission to invite/add users.
7. Test by sending `/start` to the bot and submitting a join request to a channel/group where join requests are enabled.

## Notes
- The webhook endpoint is `https://<your-project>.vercel.app/api/index` (the function root handles POST updates).
- Never publish your bot token or MongoDB URI in GitHub.
- This is a minimal webhook conversion. Force-subscription buttons for private channels may need explicit invite links configured, and `/broadcast` requires MongoDB.
