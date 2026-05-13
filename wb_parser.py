import asyncio
import re
import threading
import time
from DrissionPage import ChromiumPage, ChromiumOptions
from bs4 import BeautifulSoup

_browser_lock = threading.Lock()
_browser_page = None

def _get_browser_page():
    global _browser_page
    if _browser_page is not None:
        return _browser_page

    with _browser_lock:
        if _browser_page is not None:
            return _browser_page

        co = ChromiumOptions()
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--window-size=1920,1080')
        co.set_paths(browser_path='/usr/bin/chromium')

        page = ChromiumPage(co)
        _browser_page = page
        print("[DRISSION] Браузер запущен")
        return page

def get_imt_id_sync(article: str) -> str | None:
    """Не используется — заглушка для совместимости."""
    return article

async def get_imt_id(session, article):
    return article

async def get_imt_id_from_html(session, article):
    return article

def extract_article(url_or_article):
    if url_or_article.isdigit():
        return url_or_article
    patterns = [
        r'wildberries\.ru/catalog/(\d+)/detail\.aspx',
        r'wildberries\.by/catalog/(\d+)/detail\.aspx',
        r'wildberries\.ru/product\?card=(\d+)',
        r'wildberries\.ru/catalog/(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_article)
        if match:
            return match.group(1)
    digits = re.findall(r'\d{6,12}', url_or_article)
    return digits[0] if digits else None

def _parse_feedbacks_page(page, article):
    """Загружает страницу отзывов и парсит их универсальным способом."""
    url = f"https://www.wildberries.ru/catalog/{article}/feedbacks?size=100"
    print(f"[FEEDBACKS] Загружаю {url}")
    page.get(url, timeout=15)
    time.sleep(3)

    for _ in range(5):
        page.run_js("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

    # Попытка извлечь через JS
    reviews_js = page.run_js("""
        () => {
            const reviews = [];
            const items = document.querySelectorAll('li.comments__item.feedback[itemprop="review"]');
            items.forEach(el => {
                const authorEl = el.querySelector('.feedback__header');
                const author = authorEl ? authorEl.innerText.trim() : 'Аноним';
                const starsEl = el.querySelector('span.stars-line');
                let stars = 0;
                if (starsEl) {
                    const match = starsEl.className.match(/star(\\d+)/);
                    stars = match ? parseInt(match[1]) : 0;
                }
                const textEl = el.querySelector('p.feedback__text.j-feedback__text');
                let text = textEl ? textEl.innerText.trim() : '';
                const prosEl = el.querySelector('.feedback__text--item-pro');
                let pros = '';
                if (prosEl) {
                    const clone = prosEl.cloneNode(true);
                    const bold = clone.querySelector('.feedback__text--item-bold');
                    if (bold) bold.remove();
                    pros = clone.innerText.trim();
                }
                const consEl = el.querySelector('.feedback__text--item-con');
                let cons = '';
                if (consEl) {
                    const clone = consEl.cloneNode(true);
                    const bold = clone.querySelector('.feedback__text--item-bold');
                    if (bold) bold.remove();
                    cons = clone.innerText.trim();
                }
                const dateEl = el.querySelector('.feedback__date');
                const date = dateEl ? dateEl.innerText.trim() : '';
                const replyEl = el.querySelector('.feedback__text--sellers-reply');
                const reply = replyEl ? replyEl.innerText.trim() : '';
                reviews.push({ author, stars, text, pros, cons, date, reply });
            });
            return reviews;
        }
    """)

    if reviews_js and len(reviews_js) > 0:
        print(f"[FEEDBACKS] Найдено через JS: {len(reviews_js)}")
        return reviews_js

    # Запасной парсинг через BeautifulSoup
    print("[FEEDBACKS] JS не нашел отзывы, парсим HTML через BeautifulSoup...")
    html = page.html
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('li.comments__item.product-feedbacks__block-wrapper')
    reviews = []
    for item in items:
        author_el = item.select_one('.feedback__header')
        author = author_el.get_text(strip=True) if author_el else 'Аноним'
        stars_el = item.select_one('span.stars-line')
        stars = 0
        if stars_el:
            match = re.search(r'star(\d+)', ' '.join(stars_el.get('class', [])))
            if match:
                stars = int(match.group(1))
        text_el = item.select_one('p.feedback__text.j-feedback__text')
        text = text_el.get_text(strip=True) if text_el else ''
        pros_el = item.select_one('.feedback__text--item-pro')
        pros = ''
        if pros_el:
            bold = pros_el.select_one('.feedback__text--item-bold')
            if bold:
                bold.decompose()
            pros = pros_el.get_text(strip=True)
        cons_el = item.select_one('.feedback__text--item-con')
        cons = ''
        if cons_el:
            bold = cons_el.select_one('.feedback__text--item-bold')
            if bold:
                bold.decompose()
            cons = cons_el.get_text(strip=True)
        date_el = item.select_one('.feedback__date')
        date = date_el.get_text(strip=True) if date_el else ''
        reply_el = item.select_one('.feedback__text--sellers-reply')
        reply = reply_el.get_text(strip=True) if reply_el else ''
        reviews.append({
            "author": author,
            "stars": stars,
            "text": text,
            "pros": pros,
            "cons": cons,
            "date": date,
            "reply": reply
        })

    print(f"[FEEDBACKS] Найдено через BS4: {len(reviews)}")
    return reviews

def _parse_questions_page(page, article):
    """Загружает страницу вопросов и парсит их (селектор li.questions__item)."""
    url = f"https://www.wildberries.ru/catalog/{article}/questions"
    print(f"[QUESTIONS] Загружаю {url}")
    page.get(url, timeout=15)
    time.sleep(3)
    page.run_js("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    # JS-селектор
    questions_js = page.run_js("""
        () => {
            const qs = [];
            const items = document.querySelectorAll('li.questions__item');
            items.forEach(el => {
                const textEl = el.querySelector('.feedback__text');
                const text = textEl ? textEl.innerText.trim() : '';
                const authorEl = el.querySelector('.feedback__header');
                const author = authorEl ? authorEl.innerText.trim() : 'Аноним';
                const dateEl = el.querySelector('.feedback__date');
                const date = dateEl ? dateEl.innerText.trim() : '';
                const replyEl = el.querySelector('.feedback__text--sellers-reply__question, .feedback__text--sellers-reply');
                const reply = replyEl ? replyEl.innerText.trim() : '';
                if (text) {
                    qs.push({ text, author, date, reply });
                }
            });
            return qs;
        }
    """)

    if questions_js and len(questions_js) > 0:
        print(f"[QUESTIONS] Найдено через JS: {len(questions_js)}")
        return questions_js

    # Запасной BS4
    print("[QUESTIONS] JS не нашел вопросы, парсим HTML через BeautifulSoup...")
    html = page.html
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('li.questions__item')
    questions = []
    for item in items:
        text_el = item.select_one('.feedback__text')
        text = text_el.get_text(strip=True) if text_el else ''
        author_el = item.select_one('.feedback__header')
        author = author_el.get_text(strip=True) if author_el else 'Аноним'
        date_el = item.select_one('.feedback__date')
        date = date_el.get_text(strip=True) if date_el else ''
        reply_el = item.select_one('.feedback__text--sellers-reply__question, .feedback__text--sellers-reply')
        reply = reply_el.get_text(strip=True) if reply_el else ''
        if text:
            questions.append({"text": text, "author": author, "date": date, "reply": reply})
    print(f"[QUESTIONS] Найдено через BS4: {len(questions)}")
    return questions

async def collect_all(session, article, filter_type, progress_callback=None, batch_size=30):
    print(f"[COLLECT] Сбор данных для артикула {article}, фильтр: {filter_type}")
    try:
        page = _get_browser_page()

        reviews_raw = _parse_feedbacks_page(page, article)
        questions_raw = _parse_questions_page(page, article)

        # Формируем список отзывов в стандартном формате
        reviews_parsed = []
        for r in reviews_raw:
            reviews_parsed.append({
                "date": r.get("date", ""),
                "author": r.get("author", "Аноним"),
                "rating": int(r.get("stars", 0)) if r.get("stars") else 0,
                "text": r.get("text", ""),
                "pros": r.get("pros", ""),
                "cons": r.get("cons", ""),
                "seller_reply": r.get("reply", ""),
                "reply_date": "",
                "media_count": "0 фото / 0 видео"
            })

        questions_parsed = []
        for q in questions_raw:
            questions_parsed.append({
                "date": q.get("date", ""),
                "author": q.get("author", "Аноним"),
                "text": q.get("text", ""),
                "seller_reply": q.get("reply", ""),
                "reply_date": "",
                "other_answers": ""
            })

        total_raw_reviews = len(reviews_parsed)
        print(f"[COLLECT] Всего отзывов до фильтра: {total_raw_reviews}")

        # Применяем фильтр по звёздам
        if filter_type and filter_type != "all":
            if filter_type == "1":
                reviews_parsed = [r for r in reviews_parsed if r["rating"] == 1]
            elif filter_type == "1-2":
                reviews_parsed = [r for r in reviews_parsed if r["rating"] in (1, 2)]
            elif filter_type == "1-3":
                reviews_parsed = [r for r in reviews_parsed if r["rating"] in (1, 2, 3)]
            elif filter_type == "4-5":
                reviews_parsed = [r for r in reviews_parsed if r["rating"] in (4, 5)]
            elif "," in filter_type:
                stars_set = set(map(int, filter_type.split(",")))
                reviews_parsed = [r for r in reviews_parsed if r["rating"] in stars_set]
            else:
                # Одиночная цифра (например "5")
                try:
                    star = int(filter_type)
                    reviews_parsed = [r for r in reviews_parsed if r["rating"] == star]
                except ValueError:
                    pass

        print(f"[COLLECT] Отзывов после фильтра: {len(reviews_parsed)}")
        avg_rating = round(sum(r["rating"] for r in reviews_parsed) / len(reviews_parsed), 2) if reviews_parsed else 0

        return reviews_parsed, questions_parsed, avg_rating, total_raw_reviews, len(questions_parsed)

    except Exception as e:
        print(f"[COLLECT] Ошибка: {e}")
        return [], [], 0.0, 0, 0

# Заглушки для совместимости с ботом
async def fetch_reviews(session, imt_id, skip=0, take=30):
    return None
async def fetch_questions(session, imt_id, page=1, take=30):
    return None
def filter_reviews(reviews, filter_type):
    if filter_type == "all": return reviews
    if filter_type == "1": return [r for r in reviews if r.get("star") == 1]
    if filter_type == "1-2": return [r for r in reviews if r.get("star") in (1, 2)]
    if filter_type == "1-3": return [r for r in reviews if r.get("star") in (1, 2, 3)]
    if filter_type == "4-5": return [r for r in reviews if r.get("star") in (4, 5)]
    if "," in filter_type:
        stars = set(map(int, filter_type.split(",")))
        return [r for r in reviews if r.get("star") in stars]
    return reviews
def parse_review(r):
    photos_count = len(r.get("photo", [])) if r.get("photo") else 0
    videos_count = len(r.get("video", [])) if r.get("video") else 0
    return {
        "date": r.get("createdDate", "")[:10] if r.get("createdDate") else "",
        "author": r.get("wbUserDetails", {}).get("name", "Аноним"),
        "rating": r.get("star", 0),
        "text": r.get("text", ""),
        "pros": r.get("pros", ""),
        "cons": r.get("cons", ""),
        "seller_reply": r.get("answer", {}).get("text", ""),
        "reply_date": r.get("answer", {}).get("createdDate", "")[:10] if r.get("answer", {}).get("createdDate") else "",
        "media_count": f"{photos_count} фото / {videos_count} видео"
    }
def parse_question(q):
    other_answers = []
    if q.get("answers"):
        other_answers = [a.get("text", "") for a in q["answers"]]
    return {
        "date": q.get("createdDate", "")[:10] if q.get("createdDate") else "",
        "author": q.get("wbUserDetails", {}).get("name", "Аноним"),
        "text": q.get("text", ""),
        "seller_reply": q.get("supplierAnswer", {}).get("text", ""),
        "reply_date": q.get("supplierAnswer", {}).get("createdDate", "")[:10] if q.get("supplierAnswer", {}).get("createdDate") else "",
        "other_answers": " | ".join(other_answers)
    }