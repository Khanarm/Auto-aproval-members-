import os
import logging
from typing import Any

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("auto-approve-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN = int(os.getenv("ADMIN", "0") or "0")
DB_URI = os.getenv("DB_URI", "").strip()
DB_NAME = os.getenv("DB_NAME", "approve").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
IS_FSUB = os.getenv("IS_FSUB", "False").lower() == "true"
AUTH_CHANNELS = [int(x) for x in os.getenv("AUTH_CHANNELS", "").split() if x.lstrip("-").isdigit()]
PICS = os.getenv("PICS", "").split()

app = FastAPI(title="Auto Approve Telegram Bot")
mongo_client = None
users_collection = None
if DB_URI and MongoClient:
    try:
        mongo_client = MongoClient(DB_URI, serverSelectionTimeoutMS=4000, connectTimeoutMS=4000)
        mongo_client.admin.command("ping")
        users_collection = mongo_client[DB_NAME]["users"]
        log.info("MongoDB connected")
    except Exception:
        log.exception("MongoDB connection failed")
        mongo_client = None
        users_collection = None

async def tg(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload or {})
        data = response.json()
    if not data.get("ok"):
        log.warning("Telegram API %s failed: %s", method, data)
    return data

async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await tg("sendMessage", payload)

async def is_admin(user_id: int) -> bool:
    return bool(ADMIN and user_id == ADMIN)

async def check_fsub(user_id: int) -> list[int]:
    missing = []
    for channel_id in AUTH_CHANNELS:
        result = await tg("getChatMember", {"chat_id": channel_id, "user_id": user_id})
        if not result.get("ok"):
            missing.append(channel_id)
            continue
        status = result.get("result", {}).get("status")
        if status not in ("creator", "administrator", "member"):
            missing.append(channel_id)
    return missing

async def handle_message(message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user = message.get("from", {})
    user_id = user.get("id")
    if not chat_id or not user_id:
        return
    if users_collection is not None:
        try:
            users_collection.update_one(
                {"user_id": int(user_id)},
                {"$set": {"user_id": int(user_id), "first_name": user.get("first_name", ""), "username": user.get("username", "")}},
                upsert=True,
            )
        except Exception:
            log.exception("Could not save user")

    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return
    command = text.split()[0].split("@")[0].lower()
    args = text.split()[1:]

    if command in ("/start", "/help"):
        body = (
            "🤖 <b>Auto Approve Bot</b>\n\n"
            "I automatically approve Telegram channel/group join requests when I am added as an administrator "
            "with permission to add users.\n\n"
            "Commands:\n/start - Start the bot\n/help - Help\n"
            "/stats - Bot stats (admin)\n/broadcast - Reply to a message with /broadcast (admin)\n"
        )
        if IS_FSUB and not await is_admin(user_id):
            missing = await check_fsub(user_id)
            if missing:
                buttons = []
                for channel_id in missing:
                    info = await tg("getChat", {"chat_id": channel_id})
                    title = info.get("result", {}).get("title", f"Channel {channel_id}")
                    # Private invite links cannot be generated unless bot has suitable admin permissions.
                    invite = info.get("result", {}).get("invite_link")
                    if invite:
                        buttons.append([{"text": title, "url": invite}])
                buttons.append([{"text": "I've Joined — Check Again", "callback_data": "check_fsub"}])
                await send_message(chat_id, "🔒 Please join all required channels first.", {"inline_keyboard": buttons})
                return
        await send_message(chat_id, body)
        return

    if command == "/stats":
        if not await is_admin(user_id):
            await send_message(chat_id, "⛔ Admin only.")
            return
        count = users_collection.count_documents({}) if users_collection is not None else "MongoDB not configured"
        await send_message(chat_id, f"📊 <b>Bot stats</b>\nUsers: <code>{count}</code>")
        return

    if command == "/broadcast":
        if not await is_admin(user_id):
            await send_message(chat_id, "⛔ Admin only.")
            return
        reply = message.get("reply_to_message")
        if not reply:
            await send_message(chat_id, "Reply to a message with <code>/broadcast</code>.")
            return
        if users_collection is None:
            await send_message(chat_id, "Set DB_URI to enable broadcast.")
            return
        sent = failed = 0
        for row in users_collection.find({}, {"user_id": 1}):
            target = row.get("user_id")
            if not target:
                continue
            result = await tg("copyMessage", {"chat_id": int(target), "from_chat_id": chat_id, "message_id": reply["message_id"]})
            if result.get("ok"):
                sent += 1
            else:
                failed += 1
        await send_message(chat_id, f"Broadcast finished.\nSent: {sent}\nFailed: {failed}")
        return

    if command == "/maintenance":
        if not await is_admin(user_id):
            await send_message(chat_id, "⛔ Admin only.")
        else:
            await send_message(chat_id, "This Vercel webhook build does not include persistent maintenance-mode controls.")
        return

async def handle_join_request(update: dict):
    request = update.get("chat_join_request", {})
    chat = request.get("chat", {})
    user = request.get("from", {})
    chat_id = chat.get("id")
    user_id = user.get("id")
    if not chat_id or not user_id:
        return
    # The bot must be an administrator with "Invite Users / Add Users" permission.
    result = await tg("approveChatJoinRequest", {"chat_id": int(chat_id), "user_id": int(user_id)})
    if result.get("ok"):
        log.info("Approved join request: user=%s chat=%s", user_id, chat_id)
        if users_collection is not None:
            try:
                users_collection.update_one(
                    {"user_id": int(user_id)},
                    {"$set": {"user_id": int(user_id), "first_name": user.get("first_name", ""), "username": user.get("username", "")}},
                    upsert=True,
                )
            except Exception:
                log.exception("Could not save approved user")

@app.get("/")
async def root():
    return {"ok": True, "service": "Auto Approve Bot", "webhook_endpoint": "/api/index"}

@app.get("/webhook")
async def webhook_info():
    return {"ok": True, "message": "Telegram webhook endpoint is ready. Set this URL as your bot webhook."}

@app.post("/")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        if "chat_join_request" in update:
            await handle_join_request(update)
        elif "message" in update:
            await handle_message(update["message"])
        elif "callback_query" in update:
            query = update["callback_query"]
            if query.get("data") == "check_fsub":
                await tg("answerCallbackQuery", {"callback_query_id": query["id"], "text": "Please send /start again after joining."})
            else:
                await tg("answerCallbackQuery", {"callback_query_id": query["id"]})
        return JSONResponse({"ok": True})
    except Exception:
        log.exception("Webhook update failed")
        # Return success to Telegram to avoid infinite retries for malformed/unsupported updates.
        return JSONResponse({"ok": True})
