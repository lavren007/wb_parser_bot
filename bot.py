import asyncio
import aiohttp
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, WHITELIST, TEMP_DIR
from database import init_db, save_run, get_history
from wb_parser import extract_article, get_imt_id, collect_all
from excel_generator import create_reviews_excel, create_questions_excel, create_archive

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_sessions = {}

FILTER_OPTIONS = {
    "all": "⭐ Все отзывы",
    "1": "⭐ 1★",
    "1-2": "⭐ 1–2★",
    "1-3": "⭐ 1–3★",
    "4-5": "⭐ 4–5★",
    "custom": "🔢 Выбрать вручную (галочками)"
}

STAR_BUTTONS = [
    ("1 ★", "star_1"), ("2 ★", "star_2"), ("3 ★", "star_3"),
    ("4 ★", "star_4"), ("5 ★", "star_5"),
]

def is_whitelisted(user_id):
    return user_id in WHITELIST

def check_access(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        if not is_whitelisted(message.from_user.id):
            await message.answer("⛔ <b>Доступ запрещён.</b> Ваш Telegram ID отсутствует в белом списке.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

def build_filter_keyboard():
    builder = InlineKeyboardBuilder()
    for key, label in FILTER_OPTIONS.items():
        builder.add(InlineKeyboardButton(text=label, callback_data=f"filter_{key}"))
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

def build_star_keyboard(selected: set):
    builder = InlineKeyboardBuilder()
    for label, cb_data in STAR_BUTTONS:
        star_num = int(cb_data.split("_")[1])
        display = f"✅ {label}" if star_num in selected else label
        builder.add(InlineKeyboardButton(text=display, callback_data=cb_data))
    builder.add(InlineKeyboardButton(text="✅ Готово", callback_data="custom_done"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="filter_back"))
    builder.adjust(5, 2)
    return builder.as_markup()

@dp.message(Command("start"))
@check_access
async def cmd_start(message: types.Message, **kwargs):
    await message.answer(
        "👋 <b>Привет! Я парсер отзывов и вопросов Wildberries.</b>\n\n"
        "Отправь мне <b>ссылку на товар</b> или <b>артикул</b>, и я соберу данные.\n"
        "Пример ссылки: <code>https://www.wildberries.ru/catalog/12345678/detail.aspx</code>\n"
        "Или просто: <code>12345678</code>\n\n"
        "📋 Команда /history — история последних 10 запусков."
    )

@dp.message(Command("history"))
@check_access
async def cmd_history(message: types.Message, **kwargs):
    rows = get_history(message.from_user.id, limit=10)
    if not rows:
        await message.answer("📭 История пока пуста. Отправьте ссылку на товар, чтобы начать.")
        return
    text_lines = ["<b>📋 Последние запросы:</b>\n"]
    for i, row in enumerate(rows, 1):
        id_, article, filter_type, rev_cnt, q_cnt, avg_rating, rev_file, q_file, arch_file, created = row
        created_short = created[:16] if created else "?"
        text_lines.append(
            f"{i}. <b>Арт.{article}</b> | {FILTER_OPTIONS.get(filter_type, filter_type)}\n"
            f"   Отзывов: {rev_cnt} | Вопросов: {q_cnt} | Рейтинг: {avg_rating}\n"
            f"   📅 {created_short}"
        )
    builder = InlineKeyboardBuilder()
    for i, row in enumerate(rows, 1):
        id_ = row[0]
        builder.add(InlineKeyboardButton(text=f"📥 Скачать #{i}", callback_data=f"dl_{id_}"))
    builder.adjust(2)
    text_lines.append("\nНажмите кнопку, чтобы скачать файлы повторно.")
    await message.answer("\n".join(text_lines), reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("dl_"))
async def download_history(callback: types.CallbackQuery, **kwargs):
    if not is_whitelisted(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    run_id = int(callback.data.split("_")[1])
    rows = get_history(callback.from_user.id, limit=100)
    row = next((r for r in rows if r[0] == run_id), None)
    if not row:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    _, article, filter_type, rev_cnt, q_cnt, avg_rating, rev_file, q_file, arch_file, created = row
    files = []
    for f in [rev_file, q_file, arch_file]:
        if f and os.path.exists(f):
            files.append(FSInputFile(f))
    if not files:
        await callback.answer("Файлы не найдены.", show_alert=True)
        return
    await callback.message.answer(f"📦 Повторная отправка архива арт.{article}:")
    for f in files:
        await callback.message.answer_document(f)
    await callback.answer("Файлы отправлены!")

@dp.message()
@check_access
async def handle_message(message: types.Message, **kwargs):
    text = message.text.strip()
    article = extract_article(text)
    if not article:
        await message.answer("❌ Не удалось извлечь артикул.")
        return
    user_sessions[message.from_user.id] = {"article": article, "filter": None, "custom_stars": set()}
    await message.answer(
        f"✅ <b>Товар найден!</b> Артикул: <code>{article}</code>\n\nВыберите фильтр для отзывов:",
        reply_markup=build_filter_keyboard()
    )

@dp.callback_query(lambda c: c.data.startswith("filter_"))
async def filter_selected(callback: types.CallbackQuery, **kwargs):
    if not is_whitelisted(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    filter_key = callback.data.replace("filter_", "")
    session = user_sessions.get(callback.from_user.id)
    if not session:
        await callback.message.edit_text("⚠️ Сессия устарела.")
        return
    if filter_key == "custom":
        session["custom_stars"] = set()
        await callback.message.edit_text("🔢 <b>Выберите нужные оценки:</b>", reply_markup=build_star_keyboard(session["custom_stars"]))
        await callback.answer()
        return
    session["filter"] = filter_key
    await callback.message.edit_text(f"⏳ Запускаю сбор для арт.{session['article']}...")
    await callback.answer()
    await run_collection(callback.message, callback.from_user.id)

@dp.callback_query(lambda c: c.data in [f"star_{i}" for i in range(1, 6)])
async def toggle_star(callback: types.CallbackQuery, **kwargs):
    session = user_sessions.get(callback.from_user.id)
    if not session: return
    star = int(callback.data.split("_")[1])
    if star in session["custom_stars"]:
        session["custom_stars"].discard(star)
    else:
        session["custom_stars"].add(star)
    await callback.message.edit_reply_markup(reply_markup=build_star_keyboard(session["custom_stars"]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "custom_done")
async def custom_done(callback: types.CallbackQuery, **kwargs):
    session = user_sessions.get(callback.from_user.id)
    if not session: return
    if not session["custom_stars"]:
        await callback.answer("❌ Выберите хотя бы одну оценку!", show_alert=True)
        return
    filter_str = ",".join(map(str, sorted(session["custom_stars"])))
    session["filter"] = filter_str
    await callback.message.edit_text(f"⏳ Запускаю сбор для арт.{session['article']} с оценками {filter_str}...")
    await callback.answer()
    await run_collection(callback.message, callback.from_user.id)

@dp.callback_query(lambda c: c.data == "filter_back")
async def back_to_filter(callback: types.CallbackQuery, **kwargs):
    session = user_sessions.get(callback.from_user.id)
    if not session: return
    session["custom_stars"] = set()
    await callback.message.edit_text("Выберите фильтр для отзывов:", reply_markup=build_filter_keyboard())
    await callback.answer()

async def run_collection(message: types.Message, user_id: int):
    session = user_sessions.get(user_id)
    if not session:
        await message.edit_text("⚠️ Сессия устарела.")
        return
    article = session["article"]
    filter_type = session["filter"]
    filter_label = FILTER_OPTIONS.get(filter_type, f"★{filter_type}")

    try:
        async with aiohttp.ClientSession() as http_session:
            # Получаем imt_id
            imt_id = await get_imt_id(http_session, article)
            if not imt_id:
                await message.edit_text(
                    f"❌ Не удалось получить ID карточки для арт.{article}.\n"
                    "Возможно, товар недоступен или требуется прокси."
                )
                return

            progress_msg = await message.edit_text(
                f"🔍 Собираю данные...\nАртикул: <code>{article}</code>\n"
                "Отзывы: 0 (загрузка...)\nВопросы: 0 (загрузка...)"
            )

            async def update_progress(data_type, collected, total):
                nonlocal progress_msg
                if data_type == "reviews":
                    text = f"🔍 Собираю данные...\nАртикул: <code>{article}</code>\nОтзывы: {collected} из ~{total}\nВопросы: загрузка..."
                else:
                    text = f"🔍 Собираю данные...\nАртикул: <code>{article}</code>\nОтзывы: собрано\nВопросы: {collected} из ~{total}"
                try:
                    await progress_msg.edit_text(text)
                except:
                    pass

            reviews, questions, avg_rating, total_reviews_raw, total_questions_raw = await collect_all(
                http_session, imt_id, filter_type, progress_callback=update_progress
            )

        if not reviews and not questions:
            await message.edit_text(f"⚠️ Нет данных для арт.{article}")
            return

        await message.edit_text("📊 Генерирую Excel-файлы...")
        reviews_file = create_reviews_excel(reviews, article, filter_label)
        questions_file = create_questions_excel(questions, article)
        archive_file = create_archive(reviews_file, questions_file, article, filter_label)

        save_run(user_id, article, filter_type, len(reviews), len(questions),
                 avg_rating, reviews_file, questions_file, archive_file)

        summary = (
            f"✅ <b>Сбор завершён!</b>\n\n"
            f"📦 Артикул: <code>{article}</code>\n"
            f"🔍 Фильтр: {filter_label}\n"
            f"⭐ Отзывов собрано: <b>{len(reviews)}</b> (всего {total_reviews_raw} без фильтра)\n"
            f"❓ Вопросов собрано: <b>{len(questions)}</b>\n"
            f"📊 Средний рейтинг: <b>{avg_rating}</b>\n\n"
            f"Отправляю файлы..."
        )
        await message.edit_text(summary)

        await message.answer_document(FSInputFile(reviews_file), caption=f"📄 Отзывы_{article}_{filter_label}.xlsx")
        await message.answer_document(FSInputFile(questions_file), caption=f"📄 Вопросы_{article}.xlsx")
        await message.answer_document(FSInputFile(archive_file), caption=f"📦 Архив_{article}_{filter_label}.zip")

    except Exception as e:
        await message.edit_text(f"❌ Ошибка при сборе данных:\n<code>{str(e)[:500]}</code>")

async def main():
    init_db()
    print("✅ Бот запущен. Ожидаю сообщения...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())