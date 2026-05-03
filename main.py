import os
import time
import requests
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
ACTOR_ID = "worldunboxer~rapid-linkedin-scraper"

SEARCHES = [
    {"job_title": "IT Help Desk",         "location": "Argentina",     "jobs_entries": 10, "work_schedule": "2"},
    {"job_title": "IT Support Specialist","location": "Argentina",     "jobs_entries": 10, "work_schedule": "2"},
    {"job_title": "IT Support",           "location": "Latin America", "jobs_entries": 10, "work_schedule": "2"},
    {"job_title": "System Administrator", "location": "Argentina",     "jobs_entries": 10, "work_schedule": "2"},
    {"job_title": "Service Desk",         "location": "Latin America", "jobs_entries": 10, "work_schedule": "2"},
]

def get_match(title):
    t = title.lower()
    if any(k in t for k in ["help desk", "helpdesk", "service desk", "it support", "soporte de ti", "soporte ti"]):
        return "⭐⭐⭐"
    if any(k in t for k in ["sysadmin", "system admin", "infrastructure", "infraestructura", "noc", "operations"]):
        return "⭐⭐"
    return "⭐"

def run_apify_search(params):
    resp = requests.post(
        f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs",
        params={"token": APIFY_TOKEN},
        json=params,
        timeout=30
    )
    resp.raise_for_status()
    run_data = resp.json()["data"]
    run_id = run_data["id"]
    dataset_id = run_data["defaultDatasetId"]

    for _ in range(24):  # max ~4 min
        time.sleep(10)
        r = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN},
            timeout=15
        )
        status = r.json()["data"]["status"]
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            return []

    items_resp = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN, "limit": 10},
        timeout=30
    )
    return items_resp.json() if items_resp.status_code == 200 else []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔍 Iniciar búsqueda", callback_data="search")]]
    await update.message.reply_text(
        "👋 Hola Lucas!\n\nPresioná el botón para buscar empleos IT remotos en LinkedIn (Argentina / LATAM):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    status_msg = await context.bot.send_message(
        chat_id,
        "🔍 *Iniciando búsqueda...*",
        parse_mode="Markdown"
    )

    all_jobs = []
    seen_ids = set()

    for i, params in enumerate(SEARCHES, 1):
        try:
            await context.bot.edit_message_text(
                f"🔍 *Búsqueda {i}/{len(SEARCHES)}:* {params['job_title']} en {params['location']}...",
                chat_id=chat_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
            jobs = run_apify_search(params)
            for job in jobs:
                jid = job.get("job_id")
                if jid and jid not in seen_ids:
                    seen_ids.add(jid)
                    all_jobs.append(job)
        except Exception:
            continue

    await context.bot.delete_message(chat_id, status_msg.message_id)

    if not all_jobs:
        keyboard = [[InlineKeyboardButton("🔄 Reintentar", callback_data="search")]]
        await context.bot.send_message(
            chat_id, "❌ Sin resultados. Intentá de nuevo.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Sort by recency
    def sort_key(j):
        p = j.get("time_posted", "")
        if "hour" in p: return 0
        if "day" in p: return 1
        if "week" in p: return 2
        return 3

    all_jobs.sort(key=sort_key)

    await context.bot.send_message(
        chat_id,
        f"📋 *Resultados — {date.today().strftime('%d/%m/%Y')}*\n_{len(all_jobs)} empleos encontrados_",
        parse_mode="Markdown"
    )

    for job in all_jobs[:20]:
        title     = job.get("job_title", "Sin título")
        company   = job.get("company_name", "")
        applicants= job.get("num_applicants", "N/D")
        posted    = job.get("time_posted", "")
        salary    = job.get("salary_range") or "No especificado"
        url       = job.get("job_url", "")
        easy      = "✅ Easy Apply" if job.get("easy_apply") else "❌ Sin Easy Apply"
        match     = get_match(title)

        text = (
            f"{match} *[{title}]({url})*\n"
            f"🏢 _{company}_\n"
            f"💰 {salary}  |  {easy}\n"
            f"👥 {applicants}  🕐 {posted}"
        )

        try:
            await context.bot.send_message(
                chat_id, text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            time.sleep(0.3)
        except Exception:
            pass

    keyboard = [[InlineKeyboardButton("🔍 Nueva búsqueda", callback_data="search")]]
    await context.bot.send_message(
        chat_id,
        "✅ *Búsqueda completada.*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Bot corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
