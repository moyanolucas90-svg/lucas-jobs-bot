import os, json, time, requests
from datetime import date
from google.oauth2.service_account import Credentials
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
APIFY_TOKEN    = os.environ["APIFY_TOKEN"]
GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDENTIALS", "")
SHEET_ID       = "1Me87izYyYleO4v5by0Y5HsWG24PQOnhQj7xfffahWHI"
ACTOR_ID       = "worldunboxer~rapid-linkedin-scraper"
NL = chr(10)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
HEADERS = ["Link","Titulo","Empresa","Match CV","Salario","Easy Apply","Postulantes","Publicado","Fecha","Me postule","Novedades"]
SEARCHES = [
    dict(job_title="IT Help Desk",         location="Argentina",     jobs_entries=10, work_schedule="2"),
    dict(job_title="IT Support Specialist", location="Argentina",     jobs_entries=10, work_schedule="2"),
    dict(job_title="IT Support",           location="Latin America", jobs_entries=10, work_schedule="2"),
    dict(job_title="System Administrator", location="Argentina",     jobs_entries=10, work_schedule="2"),
    dict(job_title="Service Desk",         location="Latin America", jobs_entries=10, work_schedule="2"),
]

def get_match(title):
    t = title.lower()
    if any(k in t for k in ["help desk","helpdesk","service desk","it support","soporte de ti","soporte ti"]):
        return "***"
    if any(k in t for k in ["sysadmin","system admin","infrastructure","infraestructura","noc","operations"]):
        return "**"
    return "*"

def get_sheet():
    if not GOOGLE_CREDS: return None
    try:
        creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDS), scopes=SCOPES)
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print("Sheet connect error:", e)
        return None

def append_to_sheet(jobs):
    sheet = get_sheet()
    if not sheet: return False
    try:
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(HEADERS, value_input_option="USER_ENTERED")
            existing = [HEADERS]
        seen_urls = set()
        for row in existing[1:]:
            for cell in row:
                if "HYPERLINK" in cell:
                    parts = cell.split(chr(34))
                    if len(parts) > 1: seen_urls.add(parts[1])
        today = date.today().strftime("%d/%m/%Y")
        rows = []
        for job in jobs:
            url = job.get("job_url", "")
            if url in seen_urls: continue
            title = job.get("job_title", "Sin titulo")
            q = chr(34)
            formula = "=HYPERLINK(" + q + url + q + "," + q + title + q + ")" if url else title
            rows.append([formula, title, job.get("company_name",""), get_match(title),
                         job.get("salary_range") or "No especificado",
                         "Si" if job.get("easy_apply") else "No",
                         job.get("num_applicants","N/D"), job.get("time_posted",""),
                         today, "", ""])
        if rows:
            sheet.append_rows(rows, value_input_option="USER_ENTERED")
            print(len(rows), "filas agregadas al sheet.")
        return True
    except Exception as e:
        print("Sheet write error:", e)
        return False

def run_apify_search(params):
    resp = requests.post(f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs",
                         params=dict(token=APIFY_TOKEN), json=params, timeout=30)
    resp.raise_for_status()
    d = resp.json()["data"]
    run_id, dataset_id = d["id"], d["defaultDatasetId"]
    for _ in range(24):
        time.sleep(10)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}",
                              params=dict(token=APIFY_TOKEN), timeout=15).json()["data"]["status"]
        if status == "SUCCEEDED": break
        if status in ("FAILED","ABORTED","TIMED-OUT"): return []
    r = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                     params=dict(token=APIFY_TOKEN, limit=10), timeout=30)
    return r.json() if r.status_code == 200 else []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Iniciar busqueda", callback_data="search")]]
    await update.message.reply_text(
        "Hola Lucas! Presiona el boton para buscar empleos IT remotos en LinkedIn:",
        reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    msg = await context.bot.send_message(chat_id, "Iniciando busqueda...")
    all_jobs, seen = [], set()
    for i, p in enumerate(SEARCHES, 1):
        try:
            jt  = p["job_title"]
            loc = p["location"]
            await context.bot.edit_message_text(f"Busqueda {i}/{len(SEARCHES)}: {jt} en {loc}...",
                                                chat_id=chat_id, message_id=msg.message_id)
            for job in run_apify_search(p):
                jid = job.get("job_id")
                if jid and jid not in seen:
                    seen.add(jid); all_jobs.append(job)
        except Exception:
            continue
    await context.bot.delete_message(chat_id, msg.message_id)
    if not all_jobs:
        kb = [[InlineKeyboardButton("Reintentar", callback_data="search")]]
        await context.bot.send_message(chat_id, "Sin resultados.", reply_markup=InlineKeyboardMarkup(kb))
        return
    def sort_key(j):
        p = j.get("time_posted","")
        return 0 if "hour" in p else 1 if "day" in p else 2 if "week" in p else 3
    all_jobs.sort(key=sort_key)
    sheet_ok = append_to_sheet(all_jobs)
    today_str = date.today().strftime("%d/%m/%Y")
    await context.bot.send_message(chat_id, f"Resultados {today_str} - {len(all_jobs)} empleos encontrados")
    for job in all_jobs[:20]:
        title     = job.get("job_title","Sin titulo")
        company   = job.get("company_name","")
        applicants= job.get("num_applicants","N/D")
        posted    = job.get("time_posted","")
        salary    = job.get("salary_range") or "No especificado"
        url       = job.get("job_url","")
        easy      = "Easy Apply: Si" if job.get("easy_apply") else "Easy Apply: No"
        match     = get_match(title)
        text = NL.join([f"{match} [{title}]({url})", company, f"{salary} | {easy}", f"Postulantes: {applicants} | {posted}"])
        try:
            await context.bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True)
            time.sleep(0.3)
        except Exception:
            pass
    note = "Guardado en Google Sheet." if sheet_ok else "No se pudo guardar en Sheet."
    kb = [[InlineKeyboardButton("Nueva busqueda", callback_data="search")]]
    await context.bot.send_message(chat_id, f"Busqueda completada. {note}", reply_markup=InlineKeyboardMarkup(kb))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()