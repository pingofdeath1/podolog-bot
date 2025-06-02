# bot.py
import os
import re
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from telegram import (
    ReplyKeyboardMarkup, Update,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# Загрузка настроек из .env
load_dotenv()
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE   = os.getenv("AIRTABLE_TABLE")
AIRTABLE_TOKEN   = os.getenv("AIRTABLE_TOKEN")
STAFF_CHAT_ID    = int(os.getenv("STAFF_CHAT_ID"))

# Состояния диалога
NAME, PHONE, SERVICES, DATE_SELECT, TIME_SELECT, CONFIRM = range(6)

# Полный список услуг
SERVICES_LIST = [
    "Полный SMART-педикюр (пальцы + стопы + покрытие)",
    "Педикюр с покрытием (только пальцы)",
    "SMART-педикюр без покрытия",
    "Педикюр с обработкой (пальцы или стопы)",
    "Установка тампонады (1 шт.)",
    "Установка титановой нити",
    "Коррекция титановой нити",
    "Онихолизис рук (1 ноготь)",
    "Онихолизис рук (все ногти)",
    "Зачистка псевдонихии",
    "Удаление вросшего ногтя (2 стороны)",
    "Удаление 2 вросших ногтей",
    "Перевязка после удаления",
    "Зачистка онихогрифоза (1 ноготь)",
    "Онихогрифоз (2 ногтя)",
    "Парамедицинский педикюр",
    "Обработка стопы (трещины, гиперкератоз)",
    "Обработка стопы с микозом",
    "Зачистка микоза (1 ноготь)",
    "Зачистка всех ногтей",
    "Удаление онихолизиса (1 ноготь)",
    "Удаление стержневой мозоли (2 шт.)",
    "Первичное выведение бородавки",
    "Повторное выведение бородавки"
]

def nav_buttons():
    """Кнопки «◀️ Назад» и «❌ Отмена»"""
    return [
        [
            InlineKeyboardButton("◀️ Назад", callback_data="back"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel")
        ]
    ]

def get_next_workdays(n=12):
    """
    Возвращает следующие n рабочих дней (Пн, Вт, Ср, Пт, Сб), начиная со
    следующего дня от today. По умолчанию n=12, чтобы покрыть две недели.
    """
    days = []
    d = date.today() + timedelta(days=1)
    while len(days) < n:
        if d.weekday() in (0, 1, 2, 4, 5):  # Пн=0, Вт=1, Ср=2, Пт=4, Сб=5
            days.append(d)
        d += timedelta(days=1)
    return days

def get_taken_times(date_iso: str) -> set[str]:
    """Возвращает занятые слоты 'HH:MM' для переданной даты."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    params = {
        "filterByFormula": f"DATETIME_FORMAT({{Date}}, 'YYYY-MM-DD') = '{date_iso}'"
    }
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    taken = set()
    for rec in resp.json().get("records", []):
        dt = rec["fields"].get("Date")
        if dt:
            taken.add(dt.split("T")[1][:5])
    return taken

def format_display(date_iso: str, time_str: str) -> str:
    """Форматирует ISO-дату и время 'HH:MM' в 'дд.мм.ГГГГ ЧЧ:ММ'."""
    dt = datetime.fromisoformat(f"{date_iso}T{time_str}:00")
    return dt.strftime("%d.%m.%Y %H:%M")

def add_appointment(name: str, phone: str, services: list[str], date_iso: str, time_str: str):
    """Создаёт новую запись в Airtable."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    iso_full = f"{date_iso}T{time_str}:00.000Z"
    fields = {
        "ФИО":     name,
        "Телефон": phone,
        "Услуга":  ", ".join(services),
        "Date":    iso_full
    }
    resp = requests.post(url, json={"fields": fields}, headers=headers)
    resp.raise_for_status()

async def notify_staff(ctx: ContextTypes.DEFAULT_TYPE,
                       name: str, phone: str,
                       services: list[str],
                       date_iso: str, time_str: str):
    """Отправляет уведомление staff-чату о новой записи."""
    display = format_display(date_iso, time_str)
    text = (
        f"📌 *Новая запись на приём*\n"
        f"👤 ФИО: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"💅 Услуги: {', '.join(services)}\n"
        f"⏰ Дата/время: {display}"
    )
    await ctx.bot.send_message(chat_id=STAFF_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)

# --- Handlers ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню бота."""
    context.user_data.clear()
    kb = ReplyKeyboardMarkup([
        ["💅 Прайс-лист", "Запись на приём"],
        ["⏰ График работы", "📋 Подготовка"],
        ["❓ Помощь"]
    ], resize_keyboard=True)
    await update.message.reply_markdown(
        "👋 *Добро пожаловать*! Выберите действие:", reply_markup=kb
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню помощи."""
    await update.message.reply_markdown(
        "❓ *Меню помощи*:\n"
        "💅 Прайс-лист — цены на услуги\n"
        "Запись на приём — оформить бронь\n"
        "⏰ График работы — расписание салона\n"
        "📋 Подготовка — как подготовиться к процедуре\n"
        "❓ Помощь — это сообщение"
    )

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прайс-лист."""
    with open("price.jpg", "rb") as f:
        await update.message.reply_photo(f)

async def graf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает график работы."""
    with open("graf.jpg", "rb") as f:
        await update.message.reply_photo(
            f, caption="⏰ *График работы*", parse_mode=ParseMode.MARKDOWN
        )

async def prep_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о подготовке."""
    with open("podg.jpg", "rb") as f:
        await update.message.reply_photo(
            f, caption="📋 *Подготовка к процедуре*", parse_mode=ParseMode.MARKDOWN
        )

async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущий бронирование и завершает диалог."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("❌ Запись отменена.")
    return ConversationHandler.END

async def back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает пользователя к началу бронирования."""
    await update.callback_query.answer()
    return await book_start(update.callback_query, context)

# 1) Ввод имени (ФИО)
async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 1: Спрашиваем ФИО.
    Если вызвано через callback_query, редактируем текст сообщения,
    иначе отправляем новый.
    """
    if update.callback_query:
        m = update.callback_query.message
        await m.edit_text("Введите ваше ФИО:")
    else:
        await update.message.reply_text("Введите ваше ФИО:")
    return NAME

async def book_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняем ФИО и переходим к вводу телефона."""
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Введите телефон (11 цифр):",
        reply_markup=InlineKeyboardMarkup(nav_buttons())
    )
    return PHONE

# 2) Ввод телефона
async def book_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяем формат телефона и переходим к выбору услуг."""
    text = update.message.text.strip()
    if not re.fullmatch(r"\d{11}", text):
        await update.message.reply_text("Неверный формат. Введите 11 цифр.")
        return PHONE

    context.user_data["phone"] = text

    # Кнопки с услугами + навигация
    buttons = [
        [InlineKeyboardButton(svc, callback_data=f"toggle_{i}")]
        for i, svc in enumerate(SERVICES_LIST)
    ]
    buttons.append([InlineKeyboardButton("Готово", callback_data="services_done")])
    buttons.extend(nav_buttons())
    await update.message.reply_text("Выберите услугу(и):", reply_markup=InlineKeyboardMarkup(buttons))
    return SERVICES

# 3) Переключение услуг
async def service_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмечаем/снимаем отметку у услуги и обновляем меню."""
    q = update.callback_query; await q.answer()
    idx = int(q.data.split("_")[1])
    sel = context.user_data.setdefault("services", [])
    if idx in sel:
        sel.remove(idx)
    else:
        sel.append(idx)

    # Перестройка кнопок
    buttons = [
        [InlineKeyboardButton(("✅ " if i in sel else "") + svc, callback_data=f"toggle_{i}")]
        for i, svc in enumerate(SERVICES_LIST)
    ]
    buttons.append([InlineKeyboardButton("Готово", callback_data="services_done")])
    buttons.extend(nav_buttons())
    try:
        await q.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except BadRequest as e:
        # Иногда Telegram считает, что кнопки не изменились
        if "not modified" not in str(e).lower():
            raise
    return SERVICES

async def services_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переходим к выбору даты после того, как услуги выбраны."""
    q = update.callback_query; await q.answer()
    days = get_next_workdays(12)  # Две недели рабочих дней
    abbr = {0:'Пн',1:'Вт',2:'Ср',4:'Пт',5:'Сб'}
    rows = []
    # Выводим по 3 даты в ряд
    for i in range(0, len(days), 3):
        rows.append([
            InlineKeyboardButton(
                f"{abbr[d.weekday()]} {d.strftime('%d.%m')}",
                callback_data=f"date_{d.isoformat()}"
            )
            for d in days[i:i+3]
        ])
    rows.extend(nav_buttons())
    await q.edit_message_text("Выберите дату приёма:", reply_markup=InlineKeyboardMarkup(rows))
    return DATE_SELECT

# 4) Выбор даты
async def date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Сохраняем выбранную дату, проверяем свободные слоты и
    предлагаем выбор времени. Если свободных нет, предупреждаем.
    """
    q = update.callback_query; await q.answer()
    date_iso = q.data.split("_",1)[1]
    context.user_data["date"] = date_iso

    taken = get_taken_times(date_iso)
    slots = ["10:00", "14:00", "17:00"]
    free = [s for s in slots if s not in taken]
    if not free:
        await q.message.reply_text("❌ Нет свободных слотов на эту дату. Выберите другую.")
        return DATE_SELECT

    buttons = [[InlineKeyboardButton(s, callback_data=f"time_{s}")] for s in free]
    buttons.extend(nav_buttons())
    await q.edit_message_text("Выберите время приёма:", reply_markup=InlineKeyboardMarkup(buttons))
    return TIME_SELECT

# 5) Выбор времени и подтверждение
async def time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["time"] = q.data.split("_",1)[1]

    data = context.user_data
    summary = (
        f"👤 ФИО: {data['name']}\n"
        f"📱 Телефон: {data['phone']}\n"
        f"💅 Услуги: {', '.join(SERVICES_LIST[i] for i in data.get('services', []))}\n"
        f"⏰ Дата/время: {format_display(data['date'], data['time'])}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        *nav_buttons()
    ])
    await q.edit_message_text("Проверьте вашу запись:\n\n" + summary, reply_markup=kb)
    return CONFIRM

# 6) Финализация записи
async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = context.user_data
    add_appointment(
        data["name"], data["phone"],
        [SERVICES_LIST[i] for i in data.get("services", [])],
        data["date"], data["time"]
    )
    await notify_staff(
        context, data["name"], data["phone"],
        [SERVICES_LIST[i] for i in data.get("services", [])],
        data["date"], data["time"]
    )
    await q.edit_message_text("🎉 Запись подтверждена! До встречи.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^Запись на при[её]м$"), book_start)],
        states={
            NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, book_name)],
            PHONE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, book_phone),
                          CallbackQueryHandler(back_cb, pattern="^back$")],
            SERVICES:    [
                CallbackQueryHandler(service_toggle, pattern=r"^toggle_\d+$"),
                CallbackQueryHandler(services_done,    pattern="^services_done$"),
                CallbackQueryHandler(back_cb,          pattern="^back$")
            ],
            DATE_SELECT: [
                CallbackQueryHandler(date_selected,   pattern=r"^date_\d{4}-\d{2}-\d{2}$"),
                CallbackQueryHandler(back_cb,         pattern="^back$")
            ],
            TIME_SELECT: [
                CallbackQueryHandler(time_selected,   pattern=r"^time_\d{2}:\d{2}$"),
                CallbackQueryHandler(back_cb,         pattern="^back$")
            ],
            CONFIRM:     [
                CallbackQueryHandler(finalize,        pattern="^confirm$"),
                CallbackQueryHandler(back_cb,         pattern="^back$"),
                CallbackQueryHandler(cancel_cb,       pattern="^cancel$")
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_cb, pattern="^cancel$")],
        allow_reentry=True
    )
    app.add_handler(conv)

    # Меню вне разговора
    app.add_handler(CommandHandler("start",     start_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^💅 Прайс-лист$"),    price_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^⏰ График работы$"),  graf_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Подготовка$"),     prep_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^❓ Помощь$"),         help_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
