const TELEGRAM_API = "https://api.telegram.org";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

async function tg(env, method, payload) {
  const response = await fetch(`${TELEGRAM_API}/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    console.error(`Telegram ${method} failed`, JSON.stringify(result));
  }
  return result;
}

async function handleUpdate(update, env) {
  // Automatically approve only NEW join requests delivered after webhook setup.
  if (update.chat_join_request) {
    const request = update.chat_join_request;
    const result = await tg(env, "approveChatJoinRequest", {
      chat_id: request.chat.id,
      user_id: request.from.id,
    });

    if (result.ok && env.ADMIN_ID) {
      await tg(env, "sendMessage", {
        chat_id: env.ADMIN_ID,
        text: `✅ Join request approved\nChat: ${request.chat.title || request.chat.id}\nUser: ${request.from.first_name || "User"} (${request.from.id})`,
      });
    }
    return;
  }

  const message = update.message;
  if (!message || !message.text) return;
  const text = message.text.trim().split(/\s+/)[0].split("@")[0];

  if (text === "/start" || text === "/help") {
    await tg(env, "sendMessage", {
      chat_id: message.chat.id,
      text: "👋 Hello! I am an Auto-Approve Bot.\n\nWhen I am an administrator in your channel or group with permission to manage join requests, I automatically approve NEW join requests.\n\n⚠️ Requests that were already pending before webhook setup are not processed.\n\nAdd me as an administrator and enable the appropriate invite/join-request settings.",
    });
  } else if (text === "/stats" && env.ADMIN_ID && String(message.from?.id) === String(env.ADMIN_ID)) {
    await tg(env, "sendMessage", {
      chat_id: message.chat.id,
      text: "✅ Worker is running. This lightweight Cloudflare version does not store historical statistics.",
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return new Response("Auto-Approve Bot is running.", {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    if (request.method !== "POST" || url.pathname !== "/webhook") {
      return json({ ok: false, error: "Not found" }, 404);
    }

    if (!env.BOT_TOKEN) return json({ ok: false, error: "BOT_TOKEN secret is missing" }, 500);

    if (env.WEBHOOK_SECRET) {
      const supplied = request.headers.get("x-telegram-bot-api-secret-token");
      if (supplied !== env.WEBHOOK_SECRET) return json({ ok: false, error: "Unauthorized" }, 401);
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return json({ ok: false, error: "Invalid JSON" }, 400);
    }

    try {
      await handleUpdate(update, env);
      return json({ ok: true });
    } catch (error) {
      console.error("Update processing failed", error?.stack || String(error));
      // Return 200 to avoid Telegram retry storms for an update that caused a runtime error.
      return json({ ok: false, error: "Update processing failed" });
    }
  },
};
