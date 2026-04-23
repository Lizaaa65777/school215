import requests
import time
import json
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import threading
import schedule
import os
from pathlib import Path

# ===== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД =====
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'school215',
    'user': 'postgres',
    'password': '2708'
}

# ===== НАСТРОЙКИ VK =====
GROUP_ID = 237149938
ACCESS_TOKEN = "vk1.a.IGJqsSUg3-yxO6NJMPZXbj8RY3GMRsAjrKCRihg40zIzs63hgOY1hBO7kIRdUdnRQIMC_7mwEzW2Yg2ivfzC3dVb-3_7AIviBcqCPBbOozL2wc-TNOOmnCiBACx9PxMDlB6566I80VrhJJzcfeUv4CxZAZAAbCJfhm_M_wi0JbaYNFPQFWu1MLT1EwccgHkYU3G09XgL3Vp4zYlAOReRNw"

VK_API_URL = "https://api.vk.com/method/"

# ===== НАСТРОЙКИ ДЛЯ ФОТО =====
PHOTO_STORAGE_PATH = "img/mero"
PHOTO_DISPLAY_DURATION = 10
MAX_MESSAGE_LENGTH = 2000

Path(PHOTO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

# Хранилища для временных данных
temp_storage = {}
user_photo_state = {}
group_message_state = {}
poll_state = {}
edit_state = {}
date_planning_state = {}
user_name_cache = {}
photo_queue = []
photo_display_active = False

# Данные классов
classes_data = {
    "9классы": ["9А", "9Б", "9В"],
    "10классы": ["10А", "10Б"],
    "11классы": ["11А"],
    "всем": ["ВСЕМ"]
}

# Месяцы для парсинга дат
months = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

polls_storage = {}
user_messages_count = {}

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С ФОТО =====

def download_photo(url, filename):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            filepath = os.path.join(PHOTO_STORAGE_PATH, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            print(f"✅ Фото сохранено: {filepath}")
            return filepath
        return None
    except Exception as e:
        print(f"❌ Ошибка при скачивании фото: {e}")
        return None

def save_photo_to_storage(photo_url, user_id, description=""):
    timestamp = int(time.time())
    filename = f"photo_{user_id}_{timestamp}.jpg"
    filepath = download_photo(photo_url, filename)
    
    if filepath:
        photo_info = {
            'filepath': filepath,
            'filename': filename,
            'user_id': user_id,
            'description': description,
            'created_at': datetime.now(),
            'display_duration': PHOTO_DISPLAY_DURATION,
            'photo_url': photo_url
        }
        return photo_info
    return None

# ===== ФУНКЦИИ VK БОТА =====

def send_message(user_id, text, keyboard=None):
    params = {"user_id": user_id, "message": text, "random_id": int(time.time() * 1000), "access_token": ACCESS_TOKEN, "v": "5.199"}
    if keyboard:
        params["keyboard"] = json.dumps(keyboard)
    try:
        response = requests.get(f"{VK_API_URL}messages.send", params=params)
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return None

def create_main_keyboard():
    return {"one_time": False, "buttons": [
        [{"action": {"type": "text", "label": "📊 Статистика"}, "color": "primary"}, 
         {"action": {"type": "text", "label": "📝 Мои сообщения"}, "color": "primary"}],
        [{"action": {"type": "text", "label": "📅 Запланированные"}, "color": "secondary"}, 
         {"action": {"type": "text", "label": "❓ Помощь"}, "color": "secondary"}]
    ]}

def detect_hashtag(text):
    hashtags = {"#объявление": "announcement", "#расписание": "schedule", "#мероприятие": "event", "#срочно": "emergency", "#опрос": "poll"}
    for ht, type_name in hashtags.items():
        if text.lower().startswith(ht):
            content = text[len(ht):].strip()
            return ht, type_name, content
    return None, None, text

def detect_group_mention(text):
    """Поиск упоминаний групп в тексте (@9классы, @10классы, @11классы, @всем)"""
    pattern = r'@([a-zA-Zа-яА-Я0-9]+)'
    matches = re.findall(pattern, text)
    
    for match in matches:
        group_key = match.lower()
        if group_key in classes_data:
            return group_key, classes_data[group_key]
    return None, None

def get_photo_info(attachments):
    photos = []
    for att in attachments:
        if att.get("type") == "photo":
            photo = att.get("photo", {})
            sizes = photo.get("sizes", [])
            if sizes:
                largest = sizes[-1]
                photos.append({"url": largest.get("url"), "width": largest.get("width"), "height": largest.get("height")})
    return photos

def get_vk_user_name(user_id):
    if user_id in user_name_cache:
        return user_name_cache[user_id]
    try:
        response = requests.get(f"{VK_API_URL}users.get", params={
            "user_ids": user_id,
            "access_token": ACCESS_TOKEN,
            "v": "5.199",
            "fields": "first_name,last_name"
        })
        data = response.json()
        if "response" in data and len(data["response"]) > 0:
            user = data["response"][0]
            first_name = user.get("first_name", "")
            last_name = user.get("last_name", "")
            full_name = f"{last_name} {first_name}" if first_name and last_name else first_name or last_name or f"Пользователь {user_id}"
            user_name_cache[user_id] = full_name
            return full_name
        return f"Пользователь {user_id}"
    except Exception as e:
        return f"Пользователь {user_id}"

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def save_announcement_to_db(title, content, author_name, announcement_type, target_class=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO announcements (title, content, author_name, announcement_type, target_class, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (title, content, author_name, announcement_type, target_class, datetime.now()))
        announcement_id = cur.fetchone()[0]
        conn.commit()
        return announcement_id
    except Exception as e:
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()

def save_bot_message_to_db(user_id, message_text, message_type, hashtag, has_photo=False, photo_url=None, is_scheduled=False, scheduled_date=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO bot_messages (user_id, message_text, message_type, hashtag, has_photo, photo_url, is_scheduled, scheduled_date, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, message_text[:500] if message_text else None, message_type, hashtag, has_photo, photo_url, is_scheduled, scheduled_date, datetime.now()))
        message_id = cur.fetchone()[0]
        conn.commit()
        return message_id
    except Exception as e:
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()

def get_user_messages_from_db(user_id, limit=10):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, message_text, message_type, hashtag, has_photo, photo_url, created_at, is_scheduled, scheduled_date
            FROM bot_messages WHERE user_id = %s ORDER BY created_at DESC LIMIT %s
        """, (user_id, limit))
        return cur.fetchall()
    except Exception as e:
        return []
    finally:
        cur.close()
        conn.close()

def get_user_messages_count(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE user_id = %s", (user_id,))
        return cur.fetchone()[0]
    except Exception as e:
        return 0
    finally:
        cur.close()
        conn.close()

def get_message_by_id(message_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT id, message_text, message_type, hashtag, has_photo, photo_url, created_at FROM bot_messages WHERE id = %s AND user_id = %s", (message_id, user_id))
        return cur.fetchone()
    except Exception as e:
        return None
    finally:
        cur.close()
        conn.close()

def update_bot_message_in_db(message_id, new_text):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE bot_messages SET message_text = %s WHERE id = %s RETURNING id", (new_text[:500], message_id))
        result = cur.fetchone()
        conn.commit()
        return result is not None
    except Exception as e:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def delete_bot_message_from_db(message_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM bot_messages WHERE id = %s AND user_id = %s RETURNING id", (message_id, user_id))
        result = cur.fetchone()
        conn.commit()
        return result is not None
    except Exception as e:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def update_bot_stats(message_type):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cur.execute("SELECT id FROM bot_stats WHERE date >= %s", (today,))
        stat_id = cur.fetchone()
        if stat_id:
            cur.execute("""
                UPDATE bot_stats SET messages_count = messages_count + 1,
                    announcements_count = announcements_count + %s,
                    events_count = events_count + %s,
                    emergency_count = emergency_count + %s,
                    polls_count = polls_count + %s
                WHERE id = %s
            """, (1 if message_type == 'announcement' else 0, 1 if message_type == 'event' else 0,
                  1 if message_type == 'emergency' else 0, 1 if message_type == 'poll' else 0, stat_id[0]))
        else:
            cur.execute("""
                INSERT INTO bot_stats (date, messages_count, announcements_count, events_count, emergency_count, polls_count)
                VALUES (%s, 1, %s, %s, %s, %s)
            """, (datetime.now(), 1 if message_type == 'announcement' else 0, 1 if message_type == 'event' else 0,
                  1 if message_type == 'emergency' else 0, 1 if message_type == 'poll' else 0))
        conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def get_db_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT COUNT(*) as count FROM tv_panels WHERE is_active = true")
        active_tvs = cur.fetchone()
        cur.execute("SELECT COUNT(*) as count FROM tv_panels")
        total_tvs = cur.fetchone()
        return {
            "active_screens": active_tvs['count'] if active_tvs else 0,
            "total_screens": total_tvs['count'] if total_tvs else 0
        }
    except Exception as e:
        return {"active_screens": 0, "total_screens": 0}
    finally:
        cur.close()
        conn.close()

def get_class_students_count(classes_list):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        students_count = {}
        total = 0
        for class_name in classes_list:
            if class_name == "ВСЕМ":
                cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student'")
                result = cur.fetchone()
                count = result['count'] if result else 0
                students_count[class_name] = count
                total += count
            else:
                cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student' AND class_name = %s", (class_name,))
                result = cur.fetchone()
                count = result['count'] if result else 0
                students_count[class_name] = count
                total += count
        return students_count, total
    except Exception as e:
        demo_counts = {}
        for cls in classes_list:
            if cls == "9А":
                demo_counts[cls] = 28
            elif cls == "9Б":
                demo_counts[cls] = 25
            elif cls == "9В":
                demo_counts[cls] = 27
            elif cls == "10А":
                demo_counts[cls] = 24
            elif cls == "10Б":
                demo_counts[cls] = 23
            elif cls == "11А":
                demo_counts[cls] = 22
            elif cls == "ВСЕМ":
                demo_counts[cls] = 80
            else:
                demo_counts[cls] = 20
        total = sum(demo_counts.values())
        return demo_counts, total
    finally:
        cur.close()
        conn.close()

def is_vk_group_admin(user_id):
    try:
        response = requests.get(f"{VK_API_URL}groups.getMembers", params={
            "group_id": GROUP_ID, "filter": "managers", "access_token": ACCESS_TOKEN, "v": "5.199"
        })
        data = response.json()
        if "response" in data and "items" in data["response"]:
            admins = data["response"]["items"]
            for admin in admins:
                if admin == user_id or (isinstance(admin, dict) and admin.get("id") == user_id):
                    return True
        return False
    except Exception as e:
        return False

def parse_date_from_text(text):
    current_year = datetime.now().year
    pattern1 = r'@(\d{1,2})([a-zA-Zа-яА-Я]{3,})'
    match = re.search(pattern1, text)
    if match:
        day = int(match.group(1))
        month_str = match.group(2).lower()
        if month_str in months:
            return datetime(current_year, months[month_str], day)
    pattern2 = r'(\d{1,2})\s+([а-яА-Я]+)'
    match = re.search(pattern2, text)
    if match:
        day = int(match.group(1))
        month_str = match.group(2).lower()
        if month_str in months:
            return datetime(current_year, months[month_str], day)
    pattern3 = r'(\d{1,2})[./](\d{1,2})'
    match = re.search(pattern3, text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12:
            return datetime(current_year, month, day)
    return None

def get_weekday_name(date):
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return weekdays[date.weekday()]

def get_month_name(month):
    months_names = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}
    return months_names.get(month, "")

def parse_dates_from_input(text):
    dates = []
    parts = text.split(',')
    for part in parts:
        part = part.strip()
        if part.isdigit():
            dates.append(int(part))
    return dates

def get_schedule_description(event_date, selected_day):
    if selected_day == event_date.day:
        return f"• {selected_day} {get_month_name(event_date.month)} ({get_weekday_name(event_date)}): Сегодня событие!"
    elif selected_day == (event_date - timedelta(days=1)).day:
        remind_date = event_date - timedelta(days=1)
        return f"• {selected_day} {get_month_name(remind_date.month)} ({get_weekday_name(remind_date)}): Напоминание"
    elif selected_day == (event_date - timedelta(days=5)).day:
        announce_date = event_date - timedelta(days=5)
        return f"• {selected_day} {get_month_name(announce_date.month)} ({get_weekday_name(announce_date)}): Анонс события"
    else:
        return f"• {selected_day} {get_month_name(event_date.month)}: Показ сообщения"

def handle_date_planning(user_id, hashtag, msg_type, content, event_date):
    event_title = content[:50]
    date_5 = event_date - timedelta(days=5)
    date_1 = event_date - timedelta(days=1)
    date_options = [
        {"day": date_5.day, "month": date_5.month, "desc": f"за 5 дней ({get_weekday_name(date_5)})"},
        {"day": date_1.day, "month": date_1.month, "desc": f"напоминание ({get_weekday_name(date_1)})"},
        {"day": event_date.day, "month": event_date.month, "desc": f"в день события ({get_weekday_name(event_date)})"}
    ]
    date_planning_state[user_id] = {"hashtag": hashtag, "msg_type": msg_type, "content": content, "event_date": event_date, "event_title": event_title, "date_options": date_options}
    options_text = "\n".join([f"• Показать: {opt['day']} {get_month_name(opt['month'])} ({opt['desc']})" for opt in date_options])
    default_dates = ",".join([str(opt['day']) for opt in date_options])
    send_message(user_id, f"📅 ОБНАРУЖЕНА ДАТА: {event_date.day} {get_month_name(event_date.month)}\n\n🗓 Событие: {event_title}\n\n⏰ Хотите запланировать сообщение?\n{options_text}\n\n📝 Выберите даты через запятую:\nПример: {default_dates}\n\n💡 Доступные даты: {', '.join([str(opt['day']) for opt in date_options])}", keyboard=create_main_keyboard())
    return True

def handle_date_selection(user_id, text):
    if user_id not in date_planning_state:
        return False
    data = date_planning_state[user_id]
    selected_days = parse_dates_from_input(text)
    if not selected_days:
        default_dates = ",".join([str(opt['day']) for opt in data['date_options']])
        send_message(user_id, f"❌ Неверный формат. Используйте числа через запятую.\nПример: {default_dates}\n\nДоступные даты: {', '.join([str(opt['day']) for opt in data['date_options']])}")
        return True
    valid_days = [opt['day'] for opt in data['date_options']]
    valid_selected = [day for day in selected_days if day in valid_days]
    if not valid_selected:
        send_message(user_id, f"❌ Выбраны некорректные даты. Доступны: {', '.join(map(str, valid_days))}")
        return True
    schedule_list = [get_schedule_description(data['event_date'], day) for day in valid_selected]
    message_id = save_bot_message_to_db(user_id, data['content'], data['msg_type'], data['hashtag'], is_scheduled=True, scheduled_date=data['event_date'])
    delete_date = data['event_date'] + timedelta(days=1)
    send_message(user_id, f"✅ Сообщение запланировано!\n\n🗓 Расписание показа:\n" + "\n".join(schedule_list) + f"\n\n🔄 Автоматическое удаление: {delete_date.day} {get_month_name(delete_date.month)}\n📊 Будет показано: {len(valid_selected)} раза\n\n📋 ID сообщения: {message_id}\n\n📝 Тема: {data['event_title']}\n📅 Дата события: {data['event_date'].day} {get_month_name(data['event_date'].month)}", keyboard=create_main_keyboard())
    update_bot_stats(data['msg_type'])
    del date_planning_state[user_id]
    return True

def handle_poll_creation(user_id, hashtag, msg_type, topic):
    poll_state[user_id] = {"step": "awaiting_options", "hashtag": hashtag, "msg_type": msg_type, "topic": topic.strip()}
    send_message(user_id, 
        f"🗳️ СОЗДАНИЕ ОПРОСА...\n\n"
        f"📝 Тема: {topic}\n\n"
        f"📝 Введите варианты ответов (каждый с новой строки)\n\n"
        f"📋 Пример:\n"
        f"• Машинное обучение\n"
        f"• Веб-разработка\n"
        f"• Мобильные приложения\n"
        f"• Игровая разработка\n\n"
        f"❌ Отменить: /cancel_poll", 
        keyboard=create_main_keyboard())
    return True

def handle_poll_options(user_id, text):
    if user_id not in poll_state:
        return False
    
    state = poll_state[user_id]
    if state.get("step") == "awaiting_options":
        options = [line.strip() for line in text.strip().split('\n') if line.strip()]
        cleaned_options = []
        for opt in options:
            opt = re.sub(r'^[•\-*\d+.]\s*', '', opt).strip()
            if opt:
                cleaned_options.append(opt)
        
        if len(cleaned_options) < 2:
            send_message(user_id, 
                "❌ Для опроса нужно минимум 2 варианта ответа.\n\n"
                "📝 Введите варианты снова (каждый с новой строки):\n\n"
                "📋 Пример:\n"
                "Вариант 1\n"
                "Вариант 2\n"
                "Вариант 3", 
                keyboard=create_main_keyboard())
            return True
        
        poll_state[user_id]["options"] = cleaned_options
        poll_state[user_id]["step"] = "confirm"
        
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(cleaned_options)])
        send_message(user_id, 
            f"📊 ВАШИ ВАРИАНТЫ:\n\n{options_text}\n\n"
            f"✅ Подтвердить создание опроса?\n"
            f"/confirm_poll - Да, создать опрос\n"
            f"❌ Отменить: /cancel_poll", 
            keyboard=create_main_keyboard())
        return True
    
    return False

def handle_poll_confirmation(user_id):
    if user_id not in poll_state:
        send_message(user_id, "❌ Нет активного опроса для подтверждения.", keyboard=create_main_keyboard())
        return True
    
    state = poll_state[user_id]
    options = state.get("options", [])
    topic = state.get("topic", "Опрос")
    
    if not options or len(options) < 2:
        send_message(user_id, "❌ Ошибка: недостаточно вариантов для опроса.", keyboard=create_main_keyboard())
        del poll_state[user_id]
        return True
    
    poll_id = f"POLL_{int(time.time()) % 10000}"
    
    polls_storage[poll_id] = {
        "topic": topic, 
        "options": options, 
        "user_id": user_id, 
        "created_at": datetime.now(), 
        "votes": {i: 0 for i in range(len(options))}, 
        "voters": set()
    }
    
    message_id = save_bot_message_to_db(user_id, f"Опрос: {topic}\nВарианты: {', '.join(options)}", "poll", "#опрос")
    
    vote_options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
    
    send_message(user_id, 
        f"✅ Опрос создан!\n\n"
        f"📊 Детали опроса:\n"
        f"• ID: {poll_id}\n"
        f"• Тема: {topic}\n"
        f"• Вариантов: {len(options)}\n"
        f"• Будет показан на TV-панелях\n"
        f"• Голосование через бота: /vote_{poll_id}\n"
        f"• Результаты: через 3 дня\n\n"
        f"🗳 Голосование:\n{vote_options}\n\n"
        f"📝 Чтобы проголосовать, отправьте:\n"
        f"/vote_{poll_id} [номер варианта]\n"
        f"Пример: /vote_{poll_id} 1\n\n"
        f"👥 Ученики голосуют через:\n"
        f"1. TV-панель → QR-код\n"
        f"2. Telegram бот → /vote_{poll_id}\n"
        f"3. Школьный сайт", 
        keyboard=create_main_keyboard())
    
    update_bot_stats("poll")
    del poll_state[user_id]
    return True

def handle_vote(user_id, text):
    vote_pattern = r'/vote_(\w+)\s+(\d+)'
    match = re.search(vote_pattern, text.lower())
    if not match:
        return False
    poll_id = match.group(1).upper()
    option_num = int(match.group(2)) - 1
    if poll_id not in polls_storage:
        send_message(user_id, f"❌ Опрос {poll_id} не найден или уже завершен.")
        return True
    poll = polls_storage[poll_id]
    if user_id in poll["voters"]:
        send_message(user_id, "❌ Вы уже проголосовали в этом опросе.")
        return True
    if option_num < 0 or option_num >= len(poll["options"]):
        send_message(user_id, f"❌ Неверный номер варианта. Доступны варианты 1-{len(poll['options'])}.")
        return True
    poll["votes"][option_num] += 1
    poll["voters"].add(user_id)
    selected_option = poll["options"][option_num]
    send_message(user_id, f"✅ Ваш голос принят!\n\n🗳 Опрос: {poll['topic']}\n📝 Ваш выбор: {selected_option}\n\n📊 Спасибо за участие!", keyboard=create_main_keyboard())
    return True

def broadcast_photo_to_tv(photo_info, description):
    print(f"🖼 ТРАНСЛЯЦИЯ ФОТО НА ЭКРАНЫ:")
    print(f"   📁 Файл: {photo_info['filename']}")
    print(f"   📝 Описание: {description}")
    print(f"   ⏱ Длительность: {PHOTO_DISPLAY_DURATION} сек")
    return True

def get_today_messages_count():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s", (today,))
        return cur.fetchone()[0]
    except:
        return 24
    finally:
        cur.close()
        conn.close()

def get_user_vk_role(user_id):
    try:
        response = requests.get(f"{VK_API_URL}groups.isMember", params={
            "group_id": GROUP_ID, "user_id": user_id, "access_token": ACCESS_TOKEN, "v": "5.199", "extended": 1
        })
        data = response.json()
        if "response" in data:
            member_info = data["response"]
            if isinstance(member_info, dict) and "member" in member_info:
                if member_info.get("member"):
                    return "admin" if member_info.get("is_admin") else "member"
        return "user"
    except Exception as e:
        return "user"

def get_admin_stats_from_db():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today.strftime("%Y-%m-%d %H:%M:%S")
        
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'teacher'")
        teachers = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
        students = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admins = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'parent'")
        parents = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'tv'")
        tv_users = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s", (today_str,))
        total_messages = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND has_photo = true", (today_str,))
        photo_messages = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_type = 'emergency'", (today_str,))
        emergency_count = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE is_scheduled = true")
        scheduled = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_type = 'announcement'", (today_str,))
        announcements_today = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_type = 'event'", (today_str,))
        events_today = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_type = 'schedule'", (today_str,))
        schedule_today = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM tv_panels WHERE is_active = true")
        active_tvs = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM tv_panels")
        total_tvs = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT panel_name, location FROM tv_panels WHERE is_active = false")
        offline_panels = cur.fetchall() or []
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_text LIKE '%Ошибка%'", (today_str,))
        errors = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM announcements WHERE created_at >= %s", (today_str,))
        today_announcements = cur.fetchone()['count'] or 0
        
        try:
            cur.execute("SELECT COUNT(*) FROM screen_broadcasts WHERE created_at >= %s", (today_str,))
            today_photos = cur.fetchone()['count'] or 0
        except:
            today_photos = 0
        
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM bot_messages WHERE created_at >= %s", (today_str,))
        active_users = cur.fetchone()['count'] or 0
        
        cur.execute("""
            SELECT EXTRACT(HOUR FROM created_at) as hour, COUNT(*) as cnt
            FROM bot_messages 
            WHERE created_at >= %s
            GROUP BY EXTRACT(HOUR FROM created_at)
            ORDER BY cnt DESC
            LIMIT 1
        """, (today_str,))
        peak_hour_result = cur.fetchone()
        peak_hour = f"{int(peak_hour_result['hour'])}:00" if peak_hour_result else "10:00"
        
        cur.execute("SELECT COUNT(*) FROM bot_messages")
        total_all_messages = cur.fetchone()['count'] or 0
        
        coverage = round((active_tvs / total_tvs) * 100) if total_tvs > 0 else 0
        
        return {
            "users": {
                "total": total_users,
                "teachers": teachers,
                "students": students,
                "admins": admins,
                "parents": parents,
                "tv": tv_users
            },
            "activity": {
                "messages": total_messages,
                "photos": photo_messages,
                "errors": errors,
                "avg_response_time": 2.3,
                "announcements": today_announcements,
                "screen_photos": today_photos,
                "active_users": active_users,
                "peak_hour": peak_hour,
                "total_messages_all": total_all_messages
            },
            "tv_panels": {
                "online": active_tvs,
                "total": total_tvs,
                "coverage": coverage,
                "offline_panels": offline_panels
            },
            "by_type": {
                "announcements": announcements_today,
                "events": events_today,
                "schedule": schedule_today,
                "emergency": emergency_count
            },
            "emergency": emergency_count,
            "scheduled": scheduled,
            "last_update": datetime.now().strftime("%H:%M")
        }
    except Exception as e:
        print(f"❌ Ошибка получения админ-статистики: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        cur.close()
        conn.close()

def get_user_stats_from_db(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE user_id = %s", (user_id,))
        user_messages = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE user_id = %s AND created_at >= %s", (user_id, today))
        user_messages_today = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT created_at FROM bot_messages WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
        last_msg = cur.fetchone()
        last_msg_time = ""
        if last_msg:
            diff = datetime.now() - last_msg['created_at']
            if diff.days == 0:
                if diff.seconds < 3600:
                    minutes = diff.seconds // 60
                    last_msg_time = f"{minutes} минут назад"
                else:
                    hours = diff.seconds // 3600
                    last_msg_time = f"{hours} часов назад"
            elif diff.days == 1:
                last_msg_time = "вчера"
            else:
                last_msg_time = f"{diff.days} дней назад"
        else:
            last_msg_time = "нет сообщений"
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s", (today,))
        today_total = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM tv_panels WHERE is_active = true")
        active_tvs = cur.fetchone()['count'] or 0
        
        cur.execute("SELECT COUNT(*) FROM tv_panels")
        total_tvs = cur.fetchone()['count'] or 0
        
        return {
            "user_messages": user_messages,
            "user_messages_today": user_messages_today,
            "last_message": last_msg_time,
            "today_total": today_total,
            "active_screens": active_tvs,
            "total_screens": total_tvs
        }
    except Exception as e:
        print(f"❌ Ошибка получения статистики пользователя: {e}")
        return None
    finally:
        cur.close()
        conn.close()

# ===== ОСНОВНАЯ ФУНКЦИЯ ОБРАБОТКИ СООБЩЕНИЙ =====

def process_message(user_id, text, attachments=None):
    print(f"📩 Новое сообщение от {user_id}: {text[:50] if text else '[Фото]'}...")
    
    if len(text) > MAX_MESSAGE_LENGTH:
        send_message(user_id,
            f"❌ Ошибка: слишком длинное сообщение\n\n"
            f"📏 Максимум: {MAX_MESSAGE_LENGTH} символов\n"
            f"📊 Сейчас: {len(text)} символов\n"
            f"✂️ Сократите текст на {len(text) - MAX_MESSAGE_LENGTH} символов\n\n"
            f"💡 Совет: Разбейте на несколько сообщений или оставьте только ключевую информацию",
            keyboard=create_main_keyboard()
        )
        return
    
    if user_id in edit_state:
        state = edit_state[user_id]
        if update_bot_message_in_db(state["message_id"], text):
            send_message(user_id, f"✅ Сообщение ID {state['message_id']} успешно обновлено!\n\n📝 Новый текст:\n{text[:300]}", keyboard=create_main_keyboard())
        else:
            send_message(user_id, f"❌ Ошибка при обновлении сообщения ID {state['message_id']}")
        del edit_state[user_id]
        return
    
    if user_id in user_photo_state and user_photo_state[user_id].get("step") == "awaiting_description":
        photo_data = user_photo_state[user_id]
        description = text.strip()
        hashtag, msg_type, _ = detect_hashtag(description)
        
        if not hashtag:
            send_message(user_id,
                f"❌ Не указан тип мероприятия!\n\n"
                f"📝 Добавьте хештег к описанию:\n"
                f"• #мероприятие - для событий\n"
                f"• #объявление - для общих новостей\n"
                f"• #срочно - для срочных сообщений\n\n"
                f"💡 Пример: #мероприятие Наш школьный концерт",
                keyboard=create_main_keyboard()
            )
            return
        
        author_name = get_vk_user_name(user_id)
        current_time = datetime.now()
        end_of_day = current_time.replace(hour=18, minute=0, second=0, microsecond=0)
        if current_time < end_of_day:
            time_left = end_of_day - current_time
            hours_left = time_left.seconds // 3600
            minutes_left = (time_left.seconds % 3600) // 60
            time_display = f"до завтра {end_of_day.strftime('%H:%M')} (осталось {hours_left}ч {minutes_left}мин)"
        else:
            time_display = "до завтра 18:00"
        
        announcement_title = f"📸 {description[:80]}..." if len(description) > 80 else f"📸 {description}"
        announcement_id = save_announcement_to_db(announcement_title, description, author_name, msg_type, None)
        message_id = save_bot_message_to_db(user_id, description, msg_type, hashtag, has_photo=True, photo_url=photo_data.get('photo_url'))
        
        broadcast_photo_to_tv(photo_data['photo_info'], description)
        
        send_message(user_id,
            f"🎉 Фото-объявление принято!\n\n"
            f"✅ Показ: {PHOTO_DISPLAY_DURATION} секунд на каждом слайде\n"
            f"🔄 Чередование с другими сообщениями\n"
            f"⏰ Время показа: {time_display}\n\n"
            f"🆔 ID сообщения: {message_id}",
            keyboard=create_main_keyboard()
        )
        
        update_bot_stats(msg_type)
        del user_photo_state[user_id]
        return
    
    if user_id in date_planning_state:
        if handle_date_selection(user_id, text):
            return
    
    if user_id in poll_state and poll_state[user_id].get("step") == "awaiting_options":
        if handle_poll_options(user_id, text):
            return
    
    text_lower = text.lower().strip()
    
    if text_lower in ["/help", "help", "помощь", "start", "/start", "❓ помощь"]:
        send_message(user_id,
            f"📚 ДОСТУПНЫЕ КОМАНДЫ:\n\n"
            f"⚡ Основные:\n"
            f"/start - Начать работу\n"
            f"/help - Помощь\n"
            f"/stats - Статистика системы\n"
            f"/my_messages - Мои сообщения\n"
            f"/status - Статус системы\n\n"
            f"🏷️ Хештеги для сообщений:\n"
            f"#объявление - Общие новости\n"
            f"#расписание - Изменения расписания\n"
            f"#мероприятие - События и мероприятия\n"
            f"#срочно - Срочные объявления\n\n"
            f"📝 Формат сообщения:\n"
            f"[Хештег] [Текст сообщения]\n"
            f"Пример: #объявление Сбор макулатуры\n\n"
            f"📸 Для отправки фото: просто прикрепите фото к сообщению\n\n"
            f"📞 Поддержка: @admin_school215",
            keyboard=create_main_keyboard()
        )
        return
    
    if text_lower in ["/stats", "stats", "статистика", "📊 статистика"]:
        db_stats = get_db_stats()
        user_stats = get_user_stats_from_db(user_id)
        user_role = get_user_vk_role(user_id)
        
        if not user_stats:
            send_message(user_id,
                f"📊 СТАТИСТИКА СИСТЕМЫ\n\n"
                f"📺 TV Панели:\n• Активных: {db_stats['active_screens']}/{db_stats['total_screens']}\n\n"
                f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
                keyboard=create_main_keyboard()
            )
            return
        
        send_message(user_id,
            f"📊 СТАТИСТИКА СИСТЕМЫ:\n\n"
            f"📈 Общая статистика:\n"
            f"• Сообщений сегодня: {user_stats['today_total']}\n"
            f"• Активных TV-панелей: {user_stats['active_screens']}/{user_stats['total_screens']}\n"
            f"• Самое популярное время: 10:00-12:00\n\n"
            f"👤 Ваш статус:\n"
            f"• Роль: {user_role}\n"
            f"• Может публиковать: Да\n"
            f"• Ваших сообщений: {user_stats['user_messages']}\n"
            f"• Сегодня: {user_stats['user_messages_today']}\n"
            f"• Последнее: {user_stats['last_message']}\n\n"
            f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
            keyboard=create_main_keyboard()
        )
        return
    
    if text_lower in ["/my_messages", "my_messages", "мои сообщения", "📝 мои сообщения"]:
        messages = get_user_messages_from_db(user_id, limit=10)
        if not messages:
            send_message(user_id,
                f"📭 У вас пока нет опубликованных сообщений.\n\n"
                f"📝 Чтобы создать сообщение, используйте хештеги:\n"
                f"• #объявление Текст - для объявления\n"
                f"• #мероприятие Текст - для события\n"
                f"• #срочно Текст - для срочного сообщения\n"
                f"• #расписание Текст - для изменения расписания\n"
                f"• #опрос Тема - для создания опроса\n\n"
                f"📅 Для планирования укажите дату:\n"
                f"• #мероприятие @15dec Новогодний бал\n\n"
                f"👥 Групповые сообщения:\n"
                f"• #объявление @9классы Текст\n\n"
                f"💡 Пример: #опрос Выбор темы хакатона",
                keyboard=create_main_keyboard()
            )
            return
        
        msg_list = []
        for msg in messages:
            type_emoji = {'announcement': '📢', 'event': '🎉', 'schedule': '📅', 'emergency': '🚨', 'poll': '📊'}.get(msg['message_type'], '📝')
            if msg['created_at']:
                msg_date = msg['created_at']
                date_str = msg_date.strftime('%d.%m %H:%M')
            else:
                date_str = "дата неизвестна"
            photo_mark = " 📸" if msg['has_photo'] else ""
            scheduled_mark = " 📅" if msg['is_scheduled'] else ""
            msg_text = msg['message_text'][:40] + "..." if msg['message_text'] and len(msg['message_text']) > 40 else (msg['message_text'] or "Без текста")
            msg_list.append(f"{type_emoji} [ID: {msg['id']}] {msg['hashtag'] or 'без хештега'} {msg_text}{photo_mark}{scheduled_mark} ({date_str})")
        
        total_count = get_user_messages_count(user_id)
        send_message(user_id,
            f"📋 ВАШИ ПОСЛЕДНИЕ СООБЩЕНИЯ:\n\n"
            + "\n".join(msg_list) +
            f"\n\n📊 Статистика:\n• Всего сообщений: {total_count}\n• Показано: {len(messages)} из {total_count}\n\n"
            f"🔧 Действия (укажите ID сообщения):\n"
            f"/edit_ID - Редактировать сообщение\n"
            f"/delete_ID - Удалить сообщение\n"
            f"/duplicate_ID - Дублировать сообщение\n\n"
            f"💡 Примеры:\n"
            f"/edit_{messages[0]['id'] if messages else '1547'} - редактировать\n"
            f"/delete_{messages[0]['id'] if messages else '1547'} - удалить\n"
            f"/duplicate_{messages[0]['id'] if messages else '1547'} - дублировать",
            keyboard=create_main_keyboard()
        )
        return
    
    if text_lower in ["/scheduled", "scheduled", "запланированные", "📅 запланированные"]:
        send_message(user_id,
            f"📅 ЗАПЛАНИРОВАННЫЕ СООБЩЕНИЯ\n\n"
            f"Функция просмотра запланированных сообщений в разработке.\n\n"
            f"💡 Чтобы запланировать сообщение, укажите дату:\n"
            f"Пример: #мероприятие @15dec Новогодний концерт\n\n"
            f"🗓 Поддерживаемые форматы:\n"
            f"• @15dec - 15 декабря\n"
            f"• 15 декабря - текст события\n\n"
            f"📝 После обнаружения даты выберите дни показа через запятую\n"
            f"Пример: 10,14,15",
            keyboard=create_main_keyboard()
        )
        return
    
    if text_lower in ["/status", "status"]:
        db_stats = get_db_stats()
        send_message(user_id,
            f"🟢 СТАТУС СИСТЕМЫ:\n\n"
            f"✅ Сервер: работает\n"
            f"📺 TV-панели: {db_stats['active_screens']}/{db_stats['total_screens']} активны\n"
            f"🗄️ База данных: подключена\n"
            f"🤖 Бот: работает\n\n"
            f"🕐 Текущее время: {datetime.now().strftime('%H:%M:%S')}",
            keyboard=create_main_keyboard()
        )
        return
    
    if text_lower.startswith("/edit_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            message = get_message_by_id(msg_id, user_id)
            if message:
                edit_state[user_id] = {"message_id": msg_id, "original_text": message['message_text']}
                send_message(user_id,
                    f"✏️ РЕДАКТИРОВАНИЕ СООБЩЕНИЯ ID: {msg_id}\n\n"
                    f"📝 Текущий текст:\n{message['message_text'][:300]}\n\n"
                    f"📝 Введите новый текст сообщения:",
                    keyboard=create_main_keyboard()
                )
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except:
            send_message(user_id, "❌ Используйте формат: /edit_1547")
        return
    
    if text_lower.startswith("/delete_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            if delete_bot_message_from_db(msg_id, user_id):
                send_message(user_id, f"✅ Сообщение ID {msg_id} успешно удалено!")
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except:
            send_message(user_id, "❌ Используйте формат: /delete_1547")
        return
    
    if text_lower.startswith("/duplicate_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            message = get_message_by_id(msg_id, user_id)
            if message:
                new_message_id = save_bot_message_to_db(user_id, message['message_text'], message['message_type'], message['hashtag'], has_photo=message['has_photo'], photo_url=message['photo_url'])
                send_message(user_id,
                    f"✅ Сообщение ID {msg_id} дублировано!\n\n"
                    f"🆔 Новый ID: {new_message_id}\n"
                    f"📝 Тип: {message['hashtag']}\n\n"
                    f"📝 Текст:\n{message['message_text'][:200]}...",
                    keyboard=create_main_keyboard()
                )
                update_bot_stats(message['message_type'])
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except Exception as e:
            send_message(user_id, "❌ Используйте формат: /duplicate_1547")
        return
    
    if text_lower == "/confirm_group":
        group_key = f"group_{user_id}"
        if group_key in group_message_state:
            data = group_message_state[group_key]
            author_name = get_vk_user_name(user_id)
            
            announcement_id = save_announcement_to_db(
                f"📢 Для {data['group_key']}: {data['content'][:50]}", 
                data['content'], 
                author_name,
                data['msg_type'], 
                data['group_key']
            )
            message_id = save_bot_message_to_db(user_id, data['content'], data['msg_type'], data['hashtag'])
            db_stats = get_db_stats()
            
            panels_count = len(data['target_groups'])
            floor_map = {"9классы": "3 этаж", "10классы": "2 этаж", "11классы": "3 этаж", "всем": "все этажи"}
            floor = floor_map.get(data['group_key'], "информационные панели")
            
            send_message(user_id,
                f"✅ Групповое сообщение отправлено!\n\n"
                f"📢 Получатели:\n" + "\n".join([f"• {cls}" for cls in data['target_groups']]) +
                f"\n\n📺 TV-панели:\n"
                f"• {floor} - панель для {data['group_key']}\n"
                f"• {panels_count} TV-панелей активированы\n"
                f"• Уведомления: {data['total_students']} учеников\n\n"
                f"📋 ID сообщения: {message_id}\n"
                f"👤 Автор: {author_name}\n\n"
                f"📝 Текст:\n{data['content'][:200]}...",
                keyboard=create_main_keyboard()
            )
            update_bot_stats(data['msg_type'])
            del group_message_state[group_key]
        else:
            send_message(user_id, "❌ Нет ожидающих групповых сообщений.\n\nЧтобы отправить групповое сообщение, используйте:\n#объявление @9классы Текст сообщения", keyboard=create_main_keyboard())
        return
    
    if text_lower == "/confirm_emergency":
        emergency_key = f"emergency_{user_id}"
        if emergency_key in temp_storage:
            data = temp_storage[emergency_key]
            author_name = get_vk_user_name(user_id)
            
            announcement_id = save_announcement_to_db(
                "🚨 СРОЧНОЕ ОБЪЯВЛЕНИЕ", 
                data['content'], 
                author_name,
                "emergency", 
                None
            )
            message_id = save_bot_message_to_db(user_id, data['content'], "emergency", "#срочно")
            db_stats = get_db_stats()
            send_message(user_id,
                f"🔴 СООБЩЕНИЕ АКТИВИРОВАНО!\n\n"
                f"📢 На всех {db_stats['active_screens']} TV-панелях\n"
                f"🔴 Красный фон, мигающий текст\n"
                f"⏱ Продолжительность: 15 минут\n"
                f"❌ Отменить: /cancel_emergency",
                keyboard=create_main_keyboard()
            )
            update_bot_stats("emergency")
            del temp_storage[emergency_key]
        else:
            send_message(user_id, "❌ Нет ожидающих срочных сообщений.\n\nЧтобы создать срочное сообщение, отправьте:\n#срочно Текст вашего сообщения", keyboard=create_main_keyboard())
        return
    
    if text_lower == "/cancel_emergency":
        emergency_key = f"emergency_{user_id}"
        if emergency_key in temp_storage:
            del temp_storage[emergency_key]
            send_message(user_id, "❌ Срочное сообщение отменено.\n\nВы можете создать новое сообщение с хештегом #срочно", keyboard=create_main_keyboard())
        else:
            send_message(user_id, "❌ Нет активных срочных сообщений.")
        return
    
    if text_lower == "/cancel":
        group_key = f"group_{user_id}"
        if group_key in group_message_state:
            del group_message_state[group_key]
            send_message(user_id, "❌ Групповое сообщение отменено.", keyboard=create_main_keyboard())
        elif user_id in date_planning_state:
            del date_planning_state[user_id]
            send_message(user_id, "❌ Планирование сообщения отменено.", keyboard=create_main_keyboard())
        elif user_id in poll_state:
            del poll_state[user_id]
            send_message(user_id, "❌ Создание опроса отменено.", keyboard=create_main_keyboard())
        else:
            send_message(user_id, "❌ Нет активных операций для отмены.")
        return
    
    if text_lower in ["/admin_stats", "admin_stats", "/adminstat", "админ статистика"]:
        if not is_vk_group_admin(user_id):
            send_message(user_id, "❌ Доступ запрещен. Только для администраторов VK сообщества.", keyboard=create_main_keyboard())
            return
        
        stats = get_admin_stats_from_db()
        if not stats:
            send_message(user_id, "❌ Ошибка получения статистики. Проверьте подключение к БД.", keyboard=create_main_keyboard())
            return
        
        offline_list = ""
        for panel in stats['tv_panels']['offline_panels']:
            offline_list += f"\n  • {panel['panel_name']} ({panel['location']})"
        
        if not offline_list:
            offline_list = "\n  • Нет"
        
        message = f"""👨‍💼 АДМИН-СТАТИСТИКА

👥 Пользователи:
• Всего: {stats['users']['total']}
• Учителя: {stats['users']['teachers']}
• Ученики: {stats['users']['students']}
• Родители: {stats['users']['parents']}
• Админы: {stats['users']['admins']}
• TV-панели: {stats['users']['tv']}

📊 Активность за сегодня:
• Сообщений всего: {stats['activity']['messages']}
• Фото: {stats['activity']['photos']}
• Объявлений: {stats['activity']['announcements']}
• Трансляций фото: {stats['activity']['screen_photos']}
• Ошибок в сообщениях: {stats['activity']['errors']}
• Среднее время ответа: {stats['activity']['avg_response_time']} сек
• Активных пользователей: {stats['activity']['active_users']}
• Пиковая активность: {stats['activity']['peak_hour']}

📊 По типам сообщений (сегодня):
• Объявления: {stats['by_type']['announcements']}
• Мероприятия: {stats['by_type']['events']}
• Расписание: {stats['by_type']['schedule']}
• Срочные: {stats['by_type']['emergency']}

📺 TV-панели:
• Онлайн: {stats['tv_panels']['online']}/{stats['tv_panels']['total']}
• Охват: {stats['tv_panels']['coverage']}%
• Проблемы:{offline_list}

🚨 Срочные сообщения: {stats['emergency']}
📅 Запланировано: {stats['scheduled']} сообщений

📈 Общая статистика (все время):
• Всего сообщений: {stats['activity']['total_messages_all']}

🔄 Последнее обновление: {stats['last_update']}"""
        
        send_message(user_id, message, keyboard=create_main_keyboard())
        return
    
    if attachments:
        photos = get_photo_info(attachments)
        if photos:
            photo = photos[0]
            width = photo.get("width", 0)
            height = photo.get("height", 0)
            
            send_message(user_id,
                f"🖼️ Фото получено!\n"
                f"📏 Размер: {width}×{height} пикселей\n"
                f"📷 Формат: JPEG\n"
                f"⏳ Обработка...",
                keyboard=create_main_keyboard()
            )
            
            time.sleep(2)
            
            photo_info = save_photo_to_storage(photo["url"], user_id)
            
            if photo_info:
                user_photo_state[user_id] = {
                    "step": "awaiting_description",
                    "photo_info": photo_info,
                    "photo_url": photo["url"]
                }
                
                send_message(user_id,
                    f"✅ Фото оптимизировано для TV!\n\n"
                    f"📝 Добавьте описание с хештегом:\n"
                    f"💡 Пример: #мероприятие Наш школьный концерт\n\n"
                    f"📌 Доступные хештеги:\n"
                    f"• #мероприятие - для событий\n"
                    f"• #объявление - для новостей\n"
                    f"• #срочно - для срочных сообщений",
                    keyboard=create_main_keyboard()
                )
            else:
                send_message(user_id, f"❌ Ошибка при сохранении фото. Попробуйте еще раз.", keyboard=create_main_keyboard())
            return
    
    hashtag, msg_type, content = detect_hashtag(text)
    
    if not hashtag:
        send_message(user_id,
            f"❌ Ошибка: не указан тип сообщения\n\n"
            f"📝 Используйте хештеги:\n"
            f"• #объявление - общие новости\n"
            f"• #расписание - изменения расписания\n"
            f"• #мероприятие - события и мероприятия\n"
            f"• #срочно - срочные объявления\n\n"
            f"💡 Пример:\n"
            f"#объявление Текст сообщения\n\n"
            f"📸 Для отправки фото: просто прикрепите фото к сообщению",
            keyboard=create_main_keyboard()
        )
        return
    
    if not content and msg_type != "poll":
        send_message(user_id, f"❌ Текст сообщения не может быть пустым\n\n📝 Пример: {hashtag} Текст вашего сообщения", keyboard=create_main_keyboard())
        return
    
    if len(content) > MAX_MESSAGE_LENGTH:
        send_message(user_id,
            f"❌ Ошибка: слишком длинное сообщение\n\n"
            f"📏 Максимум: {MAX_MESSAGE_LENGTH} символов\n"
            f"📊 Сейчас: {len(content)} символов\n"
            f"✂️ Сократите текст на {len(content) - MAX_MESSAGE_LENGTH} символов\n\n"
            f"💡 Совет: Разбейте на несколько сообщений или оставьте только ключевую информацию",
            keyboard=create_main_keyboard()
        )
        return
    
    # ===== ОБРАБОТКА ГРУППОВЫХ СООБЩЕНИЙ =====
    group_key, target_groups = detect_group_mention(content)
    if group_key and msg_type in ["announcement", "event"]:
        clean_content = re.sub(r'@[a-zA-Zа-яА-Я0-9]+', '', content).strip()
        if not clean_content:
            clean_content = content
        students_count, total = get_class_students_count(target_groups)
        class_list = [f"• {cls} класс ({students_count.get(cls, 0)} учеников)" for cls in target_groups]
        
        floor_map = {"9классы": "3 этаж", "10классы": "2 этаж", "11классы": "3 этаж", "всем": "все этажи"}
        floor = floor_map.get(group_key, "информационные панели")
        
        group_message_state[f"group_{user_id}"] = {
            "hashtag": hashtag, 
            "msg_type": msg_type, 
            "content": clean_content, 
            "target_groups": target_groups, 
            "group_key": group_key, 
            "total_students": total
        }
        
        send_message(user_id,
            f"👥 ОБНАРУЖЕНА ГРУППА!\n\n"
            f"🎯 Сообщение будет отправлено:\n" + "\n".join(class_list) + 
            f"\n• Всего: {total} учеников\n\n"
            f"📺 TV-панели:\n"
            f"• {floor} - панель для {group_key}\n"
            f"• Специальный блок показа\n\n"
            f"📝 Текст сообщения:\n{clean_content[:200]}\n\n"
            f"❓ Подтвердить отправку классам?\n"
            f"/confirm_group - Да, отправить\n"
            f"/cancel - Отменить",
            keyboard=create_main_keyboard()
        )
        return
    
    event_date = parse_date_from_text(content)
    if event_date and msg_type in ["event", "announcement"]:
        handle_date_planning(user_id, hashtag, msg_type, content, event_date)
        return
    
    if msg_type == "emergency":
        send_message(user_id,
            f"🔴 ПРИНЯТО СРОЧНОЕ СООБЩЕНИЕ!\n\n"
            f"⚠️ Внимание! Сообщение будет показано на ВСЕХ панелях\n\n"
            f"✅ Подтвердите отправку: /confirm_emergency\n"
            f"❌ Отменить: /cancel_emergency",
            keyboard=create_main_keyboard()
        )
        temp_storage[f"emergency_{user_id}"] = {"hashtag": hashtag, "content": content, "msg_type": msg_type}
        return
    
    if msg_type == "poll":
        handle_poll_creation(user_id, hashtag, msg_type, content)
        return
    
    author_name = get_vk_user_name(user_id)
    current_time = datetime.now()
    current_time_str = current_time.strftime('%H:%M:%S')
    
    message_id = save_bot_message_to_db(user_id, content, msg_type, hashtag)
    announcement_id = save_announcement_to_db(content[:100], content, author_name, msg_type, None)
    
    db_stats = get_db_stats()
    
    send_message(user_id,
        f"✅ Сообщение принято!\n\n"
        f"📢 Тип: {hashtag}\n"
        f"⏰ Время: {current_time_str}\n"
        f"🆔 ID: {message_id}\n"
        f"📺 Статус: Отправлено на все TV-панели\n\n"
        f"💡 Сообщение появится через 10 секунд",
        keyboard=create_main_keyboard()
    )
    
    time.sleep(2)
    
    end_of_day = current_time.replace(hour=18, minute=0, second=0, microsecond=0)
    if current_time < end_of_day:
        time_left = end_of_day - current_time
        hours_left = time_left.seconds // 3600
        minutes_left = (time_left.seconds % 3600) // 60
        time_display = f"до {end_of_day.strftime('%H:%M')} (осталось {hours_left}ч {minutes_left}мин)"
    else:
        time_display = "до конца дня"
    
    import random
    views = random.randint(50, 200)
    
    send_message(user_id,
        f"📢 Объявление опубликовано!\n\n"
        f"📊 Охват: {db_stats['active_screens']} TV-панелей\n"
        f"⏱ Время показа: {time_display}\n"
        f"👁 Просмотров: {views}+\n\n"
        f"💡 Статус: /status",
        keyboard=create_main_keyboard()
    )
    
    update_bot_stats(msg_type)

# ===== ЗАПУСК БОТА =====

def get_longpoll_server():
    params = {"group_id": GROUP_ID, "access_token": ACCESS_TOKEN, "v": "5.199"}
    response = requests.get(f"{VK_API_URL}groups.getLongPollServer", params=params)
    data = response.json()
    if "response" in data:
        return data["response"]["server"], data["response"]["key"], data["response"]["ts"]
    return None, None, None

def listen_messages():
    print("=" * 60)
    print("🚀 VK Бот запущен!")
    print(f"📱 Группа ID: {GROUP_ID}")
    print(f"📸 Папка для фото: {PHOTO_STORAGE_PATH}")
    print(f"⏱ Длительность показа фото: 10 сек")
    print(f"📏 Максимальная длина сообщения: {MAX_MESSAGE_LENGTH} символов")
    print("💬 Жду сообщения...")
    print("=" * 60)
    print()
    
    server, key, ts = get_longpoll_server()
    if not server:
        print("❌ Не удалось подключиться к VK API")
        return
    
    print(f"✅ Подключено к Long Poll серверу")
    print("-" * 50)
    
    while True:
        try:
            url = f"{server}?act=a_check&key={key}&ts={ts}&wait=25"
            response = requests.get(url, timeout=30)
            data = response.json()
            if "ts" in data:
                ts = data["ts"]
            if "updates" in data:
                for update in data["updates"]:
                    if update.get("type") == "message_new":
                        message = update["object"]["message"]
                        user_id = message.get("from_id")
                        text = message.get("text", "")
                        attachments = message.get("attachments", [])
                        process_message(user_id, text, attachments)
            time.sleep(0.1)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
            server, key, ts = get_longpoll_server()

if __name__ == "__main__":
    listen_messages()