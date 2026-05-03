import os
import json
import time
import requests
from datetime import date
from google.oauth2.service_account import Credentials
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS", "")
SHEET_ID = "1Me87izYyYleO4v5by0Y5HsWG24PQOnhQj7xfffahWHI"
ACTOR_ID = "worldunboxer~rapid-linkedin-scraper"
NL = chr(10)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Link", "Titulo", "Empresa", "Match CV",
    "Salario", "Easy Apply", "Postulantes", "Publicado",
    "Fecha busqueda", "Me postule", "Novedades"
]

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
        return "***"
    if any(k in t for k in ["sysadmin", "system admin", "infrastructure", "infraestructura", "noc", "operations"]):
        return "**"
    return "*"


def get_sheet():
    if not GOOGLE_CREDENTIALS:
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        return gc.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print(f"[Sheet] Error al conectar: {e}")
        return None


def append_to_sheet(jobs):
    sheet = get_sheet()
    if not sheet:
        return False
    try:
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(HEADERS, value_input_option="USER_ENTERED")
            existing = [HEADERS]
        existing_urls = set()
        for row in existing[1:]:
            for cell in row:
                if cell.startswith("=HYPERLINK("):
                    try:
                        url = cell.split(chr(34))[1]
                        existing_urls.add(url)
                    except Exception:
                        pass
        today = date.today().strftime("%d/%m/%Y")
        rows_to_add = []
        for job in jobs:
            url = job.get("job_url", "")
            if url in existing_urls:
                continue
            title = job.get("job_title", "Sin titulo")
            company = job.get("company_name", "")
            match = get_match(title)
            salary = job.get("salary_range") or "No especificado"
            easy = "Si" if job.get("easy_apply") else "No"
            applicants = job.get("num_applicants", "N/D")
            posted = job.get("time_posted", "")
            q = chr(34)
            link_formula = f"=HYPERLINK({q}{url}{q},{q}{title}{q})" if url else title
            rows_to_add.append([link_formula, title, company, match, salary, easy, applicants, posted, today, "", ""])
        if rows_to_add:
            sheet.append_rows(rows_to_add, value_input_option="USER_ENTERED")
            print(f"[Sheet] {len(rows_to_add)} filas agregadas.")
        else:
            print("[Sheet] Sin filas nuevas (todos duplicados).")
        return True
    except Exception as e:
        print(f"[Sheet] Error al escribir: {e}")
        return False


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
    for _ in range(24):
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
    keyboard = [[InlineKeyboardButton("Iniciar busqueda", callback_data="search")]]
    await update.message.reply_text(
        "Hola Lucas! Presiona el boton para buscar empleos IT remotos en LinkedIn (Argentina / LATAM):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    status_msg = await context.bot.send_message(chat_id, "Iniciando busqueda...", parse_mode="Markdown")
    all_jobs = []
    seen_ids = set()
    for i, params in enumerate(SEARCHES, 1):
        try:
            await context.bot.edit_message_text(
                f"Busqueda {i}/{len(SEARCHES)}: {params[chr(39)]job_title{chr(39)}} en {params[chr(39)]location{chr(39)}}...",
                chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown"
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
        keyboard = [[InlineKeyboardButton("Reintentar", callback_data="search")]]
        await context.bot.send_message(chat_id, "Sin resultados. Intenta de nuevo.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    def sort_key(j):
        p = j.get("time_posted", "")
        if "hour" in p: return 0
        if "day" in p: return 1
        if "week" in p: return 2
        return 3
    all_jobs.sort(key=sort_key)
    sheet_ok = append_to_sheet(all_jobs)
    await context.bot.send_message(chat_id, f"Resultados del {date.today().strftime(chr(37)+chr(100)+chr(47)+chr(37)+chr(109)+chr(47)+chr(37)+chr(89))} - {len(all_jobs)} empleos encontrados", parse_mode="Markdown")
    for job in all_jobs[:20]:
        title = job.get("job_title", "Sin titulo")
        company = job.get("company_name", "")
        applicants = job.get("num_applicants", "N/D")
        posted = job.get("time_posted", "")
        salary = job.get("salary_range") or "No especificado"
        url = job.get("job_url", "")
        easy = "Easy Apply: Si" if job.get("easy_apply") else "Easy Apply: No"
        match = get_match(title)
        line1 = f"{match} [{title}]({url})"
        line2 = company
        line3 = f"{salary} | {easy}"
        line4 = f"Postulantes: {applicants} | {posted}"
        text = NL.join([line1, line2, line3, line4])
        try:
            await context.bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True)
            time.sleep(0.3)
        except Exception:
            pass
    sheet_note = "Resultados guardados en Google Sheet." if sheet_ok else "No se pudo guardar en el Sheet."
    keyboard = [[InlineKeyboardButton("Nueva busqueda", callback_data="search")]]
    await context.bot.send_message(chat_id, f"Busqueda completada. {sheet_note}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()