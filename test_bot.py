import requests
import time
import json
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import threading
import schedule
import pandas as pd
import io

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

# Хранилища для временных данных
temp_storage = {}
user_photo_state = {}
group_message_state = {}
scheduled_messages = {}
poll_state = {}
edit_state = {}
date_planning_state = {}

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

# Хранилище для опросов
polls_storage = {}

# ===== ФУНКЦИИ ДЛЯ ИМПОРТА РАСПИСАНИЯ =====

def parse_schedule_file(file_content, file_extension):
    """Парсит файл расписания (Excel или CSV)"""
    try:
        if file_extension in ['.xlsx', '.xls']:
            # Читаем Excel файл
            df = pd.read_excel(io.BytesIO(file_content))
        elif file_extension == '.csv':
            # Читаем CSV файл
            df = pd.read_csv(io.BytesIO(file_content), encoding='utf-8')
        else:
            return None, "Неподдерживаемый формат файла"
        
        # Проверяем наличие необходимых колонок
        required_columns = ['День', 'Время', 'Класс', 'Предмет', 'Кабинет']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return None, f"Отсутствуют колонки: {', '.join(missing_columns)}"
        
        # Преобразуем данные
        schedule_data = []
        days_map = {
            'Понедельник': 1, 'Вторник': 2, 'Среда': 3, 
            'Четверг': 4, 'Пятница': 5, 'Суббота': 6
        }
        
        for _, row in df.iterrows():
            day_name = row['День'].strip()
            if day_name not in days_map:
                continue
            
            # Парсим время
            time_str = row['Время'].strip()
            if '-' in time_str:
                start_time, end_time = time_str.split('-')
            else:
                start_time = time_str
                end_time = ""
            
            schedule_data.append({
                'class_name': row['Класс'].strip(),
                'day_of_week': days_map[day_name],
                'subject': row['Предмет'].strip(),
                'room': str(row['Кабинет']).strip(),
                'start_time': start_time.strip(),
                'end_time': end_time.strip(),
                'teacher': row.get('Учитель', '').strip() if 'Учитель' in df.columns else ''
            })
        
        # Статистика
        unique_classes = list(set([s['class_name'] for s in schedule_data]))
        unique_subjects = list(set([s['subject'] for s in schedule_data]))
        days_count = len(set([s['day_of_week'] for s in schedule_data]))
        
        return {
            'data': schedule_data,
            'stats': {
                'total': len(schedule_data),
                'classes': unique_classes,
                'classes_count': len(unique_classes),
                'subjects_count': len(unique_subjects),
                'days_count': days_count
            }
        }, None
    except Exception as e:
        return None, f"Ошибка парсинга файла: {str(e)}"

def import_schedule_to_db(schedule_data):
    """Импортирует расписание в базу данных"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Очищаем существующее расписание для этих классов
        classes = list(set([s['class_name'] for s in schedule_data]))
        for class_name in classes:
            cur.execute("DELETE FROM schedules WHERE class_name = %s", (class_name,))
        
        # Вставляем новые данные
        inserted = 0
        lesson_counter = {}
        
        for item in schedule_data:
            # Считаем номер урока для каждого класса и дня
            key = f"{item['class_name']}_{item['day_of_week']}"
            if key not in lesson_counter:
                lesson_counter[key] = 1
            else:
                lesson_counter[key] += 1
            
            cur.execute("""
                INSERT INTO schedules (class_name, day_of_week, lesson_number, start_time, end_time, subject, room, teacher_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                item['class_name'],
                item['day_of_week'],
                lesson_counter[key],
                item['start_time'],
                item['end_time'],
                item['subject'],
                item['room'],
                2  # teacher_id по умолчанию
            ))
            inserted += 1
        
        conn.commit()
        return inserted, None
    except Exception as e:
        conn.rollback()
        return 0, str(e)
    finally:
        cur.close()
        conn.close()

# ===== ФУНКЦИИ РАБОТЫ С БАЗОЙ ДАННЫХ =====

def get_admin_stats():
    """Получает расширенную статистику для администратора"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today.strftime("%Y-%m-%d %H:%M:%S")
        
        # Статистика пользователей
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'teacher'")
        teachers = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
        students = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admins = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'parent'")
        parents = cur.fetchone()[0] or 0
        
        # Статистика сообщений за сегодня
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s", (today_str,))
        total_messages = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND has_photo = true", (today_str,))
        photo_messages = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_type = 'emergency'", (today_str,))
        emergency_count = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE is_scheduled = true")
        scheduled = cur.fetchone()[0] or 0
        
        # Статистика TV панелей
        try:
            cur.execute("SELECT COUNT(*) FROM tv_panels WHERE is_active = true")
            active_tvs = cur.fetchone()[0] or 0
        except:
            active_tvs = 0
        
        try:
            cur.execute("SELECT COUNT(*) FROM tv_panels")
            total_tvs = cur.fetchone()[0] or 0
        except:
            total_tvs = 0
        
        # Панели с проблемами
        offline_panels = []
        try:
            cur.execute("SELECT panel_name, location FROM tv_panels WHERE is_active = false")
            offline_panels = cur.fetchall() or []
        except:
            offline_panels = []
        
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE created_at >= %s AND message_text LIKE '%Ошибка%'", (today_str,))
        errors = cur.fetchone()[0] or 0
        
        try:
            cur.execute("SELECT COUNT(*) FROM announcements WHERE created_at >= %s", (today_str,))
            today_announcements = cur.fetchone()[0] or 0
        except:
            today_announcements = 0
        
        avg_response_time = 2.3
        coverage = round((active_tvs / total_tvs) * 100) if total_tvs > 0 else 0
        
        return {
            "users": {"total": total_users, "teachers": teachers, "students": students, "admins": admins, "parents": parents},
            "activity": {"messages": total_messages, "photos": photo_messages, "errors": errors, "avg_response_time": avg_response_time, "announcements": today_announcements},
            "tv_panels": {"online": active_tvs, "total": total_tvs, "coverage": coverage, "offline_panels": offline_panels},
            "emergency": emergency_count, "scheduled": scheduled, "last_update": datetime.now().strftime("%H:%M")
        }
    except Exception as e:
        print(f"❌ Ошибка получения админ-статистики: {e}")
        return None
    finally:
        cur.close()
        conn.close()

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
        print(f"❌ Ошибка сохранения объявления: {e}")
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()

def save_bot_message_to_db(user_id, message_text, message_type, hashtag, target_groups=None, has_photo=False, photo_url=None, is_scheduled=False, scheduled_date=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        target_groups_json = json.dumps(target_groups) if target_groups else None
        cur.execute("""
            INSERT INTO bot_messages (user_id, message_text, message_type, hashtag, target_groups, has_photo, photo_url, is_scheduled, scheduled_date, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, message_text[:500] if message_text else None, message_type, hashtag, target_groups_json, has_photo, photo_url, is_scheduled, scheduled_date, datetime.now()))
        message_id = cur.fetchone()[0]
        conn.commit()
        return message_id
    except Exception as e:
        print(f"❌ Ошибка сохранения сообщения бота: {e}")
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()

def save_poll_to_db(poll_id, user_id, topic, options, created_at):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO polls (poll_id, user_id, topic, options, created_at, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (poll_id, user_id, topic, json.dumps(options), created_at, 'active'))
        poll_db_id = cur.fetchone()[0]
        conn.commit()
        return poll_db_id
    except Exception as e:
        print(f"❌ Ошибка сохранения опроса: {e}")
        conn.rollback()
        return None
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
        print(f"❌ Ошибка проверки прав: {e}")
        return False

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
                    schedule_count = schedule_count + %s,
                    emergency_count = emergency_count + %s,
                    polls_count = polls_count + %s
                WHERE id = %s
            """, (1 if message_type == 'announcement' else 0, 1 if message_type == 'event' else 0,
                  1 if message_type == 'schedule' else 0, 1 if message_type == 'emergency' else 0,
                  1 if message_type == 'poll' else 0, stat_id[0]))
        else:
            cur.execute("""
                INSERT INTO bot_stats (date, messages_count, announcements_count, events_count, schedule_count, emergency_count, polls_count)
                VALUES (%s, 1, %s, %s, %s, %s, %s)
            """, (datetime.now(), 1 if message_type == 'announcement' else 0, 1 if message_type == 'event' else 0,
                  1 if message_type == 'schedule' else 0, 1 if message_type == 'emergency' else 0,
                  1 if message_type == 'poll' else 0))
        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка обновления статистики: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def get_db_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cur.execute("""
            SELECT COALESCE(SUM(messages_count), 0) as messages_count,
                   COALESCE(SUM(announcements_count), 0) as announcements_count,
                   COALESCE(SUM(events_count), 0) as events_count,
                   COALESCE(SUM(schedule_count), 0) as schedule_count,
                   COALESCE(SUM(emergency_count), 0) as emergency_count,
                   COALESCE(SUM(polls_count), 0) as polls_count
            FROM bot_stats WHERE date >= %s
        """, (today,))
        stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) as count FROM tv_panels WHERE is_active = true")
        active_tvs = cur.fetchone()
        cur.execute("SELECT COUNT(*) as count FROM tv_panels")
        total_tvs = cur.fetchone()
        cur.execute("SELECT COUNT(*) as count FROM bot_messages WHERE is_scheduled = true")
        scheduled = cur.fetchone()
        return {
            "today_messages": stats['messages_count'] if stats else 0,
            "announcements": stats['announcements_count'] if stats else 0,
            "events": stats['events_count'] if stats else 0,
            "schedule": stats['schedule_count'] if stats else 0,
            "emergency": stats['emergency_count'] if stats else 0,
            "polls": stats['polls_count'] if stats else 0,
            "active_screens": active_tvs['count'] if active_tvs else 0,
            "total_screens": total_tvs['count'] if total_tvs else 0,
            "scheduled": scheduled['count'] if scheduled else 0
        }
    except Exception as e:
        return {"today_messages": 0, "announcements": 0, "events": 0, "schedule": 0, "emergency": 0, "polls": 0, "active_screens": 0, "total_screens": 0, "scheduled": 0}
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

def get_class_students_count(classes_list):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        students_count = {}
        total = 0
        for class_name in classes_list:
            cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student' AND class_name = %s", (class_name,))
            result = cur.fetchone()
            count = result['count'] if result else 0
            students_count[class_name] = count
            total += count
        return students_count, total
    except Exception as e:
        return {}, 0
    finally:
        cur.close()
        conn.close()

def get_all_classes_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT class_name, COUNT(*) as count FROM users WHERE role = 'student' AND class_name IS NOT NULL GROUP BY class_name ORDER BY class_name")
        results = cur.fetchall()
        return {row['class_name']: row['count'] for row in results}
    except Exception as e:
        return {}
    finally:
        cur.close()
        conn.close()

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАТАМИ =====

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

def detect_date_in_text(text):
    return parse_date_from_text(text)

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
    scheduled_id = save_scheduled_message_to_db(user_id, data['event_date'].strftime("%Y-%m-%d"), data['event_title'], data['content'], data['hashtag'], data['msg_type'], valid_selected)
    message_id = save_bot_message_to_db(user_id, data['content'], data['msg_type'], data['hashtag'], is_scheduled=True, scheduled_date=data['event_date'])
    delete_date = data['event_date'] + timedelta(days=1)
    send_message(user_id, f"✅ Сообщение запланировано!\n\n🗓 Расписание показа:\n" + "\n".join(schedule_list) + f"\n\n🔄 Автоматическое удаление: {delete_date.day} {get_month_name(delete_date.month)}\n📊 Будет показано: {len(valid_selected)} раза\n\n🆔 ID планирования: {scheduled_id}\n📋 ID сообщения: {message_id}\n\n📝 Тема: {data['event_title']}\n📅 Дата события: {data['event_date'].day} {get_month_name(data['event_date'].month)}", keyboard=create_main_keyboard())
    update_bot_stats(data['msg_type'])
    del date_planning_state[user_id]
    return True

def save_scheduled_message_to_db(user_id, event_date, event_title, content, hashtag, msg_type, scheduled_dates):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO bot_messages (user_id, message_text, message_type, hashtag, is_scheduled, scheduled_date, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (user_id, content, msg_type, hashtag, True, event_date, datetime.now()))
        scheduled_id = cur.fetchone()[0]
        conn.commit()
        return scheduled_id
    except Exception as e:
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С ОПРОСАМИ =====

def handle_poll_creation(user_id, hashtag, msg_type, topic):
    poll_state[user_id] = {"step": "awaiting_options", "hashtag": hashtag, "msg_type": msg_type, "topic": topic.strip()}
    send_message(user_id, f"🗳️ СОЗДАНИЕ ОПРОСА...\n\n📝 Введите варианты ответов (каждый с новой строки)\n\n📋 Пример:\n• Машинное обучение\n• Веб-разработка\n• Мобильные приложения\n• Игровая разработка\n\n❌ Отменить: /cancel_poll", keyboard=create_main_keyboard())
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
            send_message(user_id, "❌ Для опроса нужно минимум 2 варианта ответа.\n\n📝 Введите варианты снова (каждый с новой строки):\n\n📋 Пример:\nВариант 1\nВариант 2\nВариант 3")
            return True
        poll_state[user_id]["options"] = cleaned_options
        poll_state[user_id]["step"] = "confirm"
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(cleaned_options)])
        send_message(user_id, f"📊 ВАШИ ВАРИАНТЫ:\n\n{options_text}\n\n✅ Подтвердить создание опроса?\n/confirm_poll - Да, создать опрос\n❌ Отменить: /cancel_poll")
        return True
    return False

def handle_poll_confirmation(user_id):
    if user_id not in poll_state:
        send_message(user_id, "❌ Нет активного опроса для подтверждения.")
        return True
    state = poll_state[user_id]
    options = state.get("options", [])
    topic = state.get("topic", "Опрос")
    if not options or len(options) < 2:
        send_message(user_id, "❌ Ошибка: недостаточно вариантов для опроса.")
        del poll_state[user_id]
        return True
    poll_id = f"POLL_{int(time.time()) % 10000}"
    polls_storage[poll_id] = {"topic": topic, "options": options, "user_id": user_id, "created_at": datetime.now(), "votes": {i: 0 for i in range(len(options))}, "voters": set()}
    poll_db_id = save_poll_to_db(poll_id, user_id, topic, options, datetime.now())
    message_id = save_bot_message_to_db(user_id, f"Опрос: {topic}\nВарианты: {', '.join(options)}", "poll", "#опрос")
    vote_options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
    send_message(user_id, f"✅ Опрос создан!\n\n📊 Детали опроса:\n• ID: {poll_id}\n• Тема: {topic}\n• Вариантов: {len(options)}\n• Будет показан на TV-панелях\n• Результаты: через 3 дня\n\n🗳 Голосование:\n{vote_options}\n\n📝 Чтобы проголосовать, отправьте:\n/vote_{poll_id} [номер варианта]\nПример: /vote_{poll_id} 1", keyboard=create_main_keyboard())
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
    return {"one_time": False, "buttons": [[{"action": {"type": "text", "label": "📊 Статистика"}, "color": "primary"}, {"action": {"type": "text", "label": "📝 Мои сообщения"}, "color": "primary"}], [{"action": {"type": "text", "label": "📅 Запланированные"}, "color": "secondary"}, {"action": {"type": "text", "label": "❓ Помощь"}, "color": "secondary"}]]}

def detect_hashtag(text):
    hashtags = {"#объявление": "announcement", "#расписание": "schedule", "#мероприятие": "event", "#срочно": "emergency", "#опрос": "poll"}
    for ht, type_name in hashtags.items():
        if text.lower().startswith(ht):
            content = text[len(ht):].strip()
            return ht, type_name, content
    return None, None, text

def detect_group_mention(text):
    date_pattern = r'@\d{1,2}[a-zA-Zа-яА-Я]{3,}'
    if re.search(date_pattern, text):
        return None, None
    pattern = r'@([a-zA-Zа-яА-Я0-9]+)'
    matches = re.findall(pattern, text)
    if matches:
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
                photos.append({"url": largest.get("url"), "width": largest.get("width"), "height": largest.get("height"), "owner_id": photo.get("owner_id"), "id": photo.get("id")})
    return photos

def handle_group_message(user_id, hashtag, msg_type, content):
    group_key, target_groups = detect_group_mention(content)
    if group_key:
        clean_content = re.sub(r'@[a-zA-Zа-яА-Я0-9]+', '', content).strip()
        students_count, total = get_class_students_count(target_groups)
        class_list = [f"• {cls} класс ({students_count.get(cls, 0)} учеников)" for cls in target_groups]
        send_message(user_id, f"👥 ОБНАРУЖЕНА ГРУППА!\n\n🎯 Сообщение будет отправлено:\n" + "\n".join(class_list) + f"\n• Всего: {total} учеников\n\n📺 TV-панели:\n• Специальный блок для {group_key}\n• Информационные панели на этажах\n\n📝 Текст сообщения:\n{clean_content[:200]}\n\n❓ Подтвердить отправку классам?\n/confirm_group - Да, отправить\n/cancel - Отменить", keyboard=create_main_keyboard())
        group_message_state[f"group_{user_id}"] = {"hashtag": hashtag, "msg_type": msg_type, "content": clean_content, "target_groups": target_groups, "group_key": group_key, "total_students": total}
        return True
    return False

def get_admin_stats_simple():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'teacher'")
        teachers = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
        students = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admins = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'parent'")
        parents = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM bot_messages")
        total_messages = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE has_photo = true")
        photo_messages = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE message_type = 'emergency'")
        emergency_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE is_scheduled = true")
        scheduled = cur.fetchone()[0] or 0
        try:
            cur.execute("SELECT COUNT(*) FROM announcements")
            announcements_total = cur.fetchone()[0] or 0
        except:
            announcements_total = 0
        cur.execute("SELECT COUNT(*) FROM bot_messages WHERE message_text LIKE '%Ошибка%'")
        errors = cur.fetchone()[0] or 0
        return {"users": {"total": total_users, "teachers": teachers, "students": students, "admins": admins, "parents": parents}, "activity": {"messages": total_messages, "photos": photo_messages, "errors": errors, "avg_response_time": 2.3, "announcements": announcements_total}, "emergency": emergency_count, "scheduled": scheduled, "last_update": datetime.now().strftime("%H:%M")}
    except Exception as e:
        return None
    finally:
        cur.close()
        conn.close()

def check_database_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        tables = cur.fetchall()
        result = "📊 ТАБЛИЦЫ В БАЗЕ ДАННЫХ:\n"
        for table in tables:
            result += f"• {table[0]}\n"
        result += "\n📈 КОЛИЧЕСТВО ЗАПИСЕЙ:\n"
        for table in tables:
            table_name = table[0]
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cur.fetchone()[0]
                result += f"• {table_name}: {count}\n"
            except:
                result += f"• {table_name}: ошибка\n"
        return result
    except Exception as e:
        return f"❌ Ошибка проверки: {e}"
    finally:
        cur.close()
        conn.close()

def handle_command(user_id, text):
    text_lower = text.lower().strip()
    
    if handle_vote(user_id, text):
        return True
    if handle_date_selection(user_id, text):
        return True
    if text_lower == "/confirm_poll":
        handle_poll_confirmation(user_id)
        return True
    elif text_lower == "/cancel_poll":
        if user_id in poll_state:
            del poll_state[user_id]
            send_message(user_id, "❌ Создание опроса отменено.", keyboard=create_main_keyboard())
        else:
            send_message(user_id, "❌ Нет активного опроса для отмены.")
        return True
    elif text_lower in ["/checkdb", "checkdb", "проверка бд"]:
        result = check_database_tables()
        send_message(user_id, result, keyboard=create_main_keyboard())
        return True
    elif text_lower == "/confirm_schedule":
        schedule_key = f"schedule_import_{user_id}"
        if schedule_key in temp_storage and temp_storage[schedule_key].get("step") == "awaiting_confirmation":
            data = temp_storage[schedule_key]["data"]
            stats = temp_storage[schedule_key]["stats"]
            inserted, error = import_schedule_to_db(data)
            if error:
                send_message(user_id, f"❌ Ошибка импорта: {error}", keyboard=create_main_keyboard())
            else:
                send_message(user_id, f"✅ РАСПИСАНИЕ ИМПОРТИРОВАНО!\n\n📊 Результат:\n• Добавлено уроков: {inserted}\n• Классы: {', '.join(stats['classes'])}\n• Дней: {stats['days_count']}\n\n🔄 Старое расписание заменено", keyboard=create_main_keyboard())
            del temp_storage[schedule_key]
        else:
            send_message(user_id, "❌ Нет ожидающего импорта расписания.\nИспользуйте: #расписание import", keyboard=create_main_keyboard())
        return True
    elif text_lower == "/confirm_group":
        group_key = f"group_{user_id}"
        if group_key in group_message_state:
            data = group_message_state[group_key]
            announcement_id = save_announcement_to_db(f"📢 Для {data['group_key']}: {data['content'][:50]}", data['content'], f"VK Пользователь {user_id}", data['msg_type'], data['group_key'])
            message_id = save_bot_message_to_db(user_id, data['content'], data['msg_type'], data['hashtag'], target_groups=data['target_groups'])
            db_stats = get_db_stats()
            send_message(user_id, f"✅ Групповое сообщение отправлено!\n\n📢 Получатели:\n" + "\n".join([f"• {cls}" for cls in data['target_groups']]) + f"\n\n📺 TV-панели:\n• Уведомления: {data['total_students']} учеников\n• Активных панелей: {db_stats['active_screens']}\n• Время показа: специальный блок для {data['group_key']}\n• Длительность: до конца дня\n\n🆔 ID объявления: {announcement_id}\n📋 ID сообщения: {message_id}\n\n📝 Текст:\n{data['content'][:200]}...", keyboard=create_main_keyboard())
            update_bot_stats(data['msg_type'])
            del group_message_state[group_key]
        else:
            send_message(user_id, "❌ Нет ожидающих групповых сообщений.\n\nЧтобы отправить групповое сообщение, используйте:\n#объявление @9классы Текст сообщения", keyboard=create_main_keyboard())
        return True
    elif text_lower == "/confirm_emergency":
        emergency_key = f"emergency_{user_id}"
        if emergency_key in temp_storage:
            data = temp_storage[emergency_key]
            announcement_id = save_announcement_to_db("🚨 СРОЧНОЕ ОБЪЯВЛЕНИЕ", data['content'], f"VK Пользователь {user_id}", "emergency", None)
            message_id = save_bot_message_to_db(user_id, data['content'], "emergency", "#срочно")
            db_stats = get_db_stats()
            send_message(user_id, f"🚨 СООБЩЕНИЕ АКТИВИРОВАНО!\n\n📢 На всех {db_stats['active_screens']} TV-панелях\n🔴 Красный фон, мигающий текст\n⏱ Продолжительность: 15 минут\n🆔 ID объявления: {announcement_id}\n\n📝 Текст:\n{data['content'][:200]}\n\n❌ Отменить: /cancel_emergency", keyboard=create_main_keyboard())
            update_bot_stats("emergency")
            del temp_storage[emergency_key]
        else:
            send_message(user_id, "❌ Нет ожидающих срочных сообщений.\n\nЧтобы создать срочное сообщение, отправьте:\n#срочно Текст вашего сообщения", keyboard=create_main_keyboard())
        return True
    elif text_lower == "/cancel_emergency":
        emergency_key = f"emergency_{user_id}"
        if emergency_key in temp_storage:
            del temp_storage[emergency_key]
            send_message(user_id, "❌ Срочное сообщение отменено.\n\nВы можете создать новое сообщение с хештегом #срочно", keyboard=create_main_keyboard())
        else:
            send_message(user_id, "❌ Нет активных срочных сообщений.")
        return True
    elif text_lower == "/cancel":
        group_key = f"group_{user_id}"
        if group_key in group_message_state:
            del group_message_state[group_key]
            send_message(user_id, "❌ Групповое сообщение отменено.\n\nВы можете создать новое сообщение с упоминанием группы.", keyboard=create_main_keyboard())
        elif user_id in date_planning_state:
            del date_planning_state[user_id]
            send_message(user_id, "❌ Планирование сообщения отменено.\n\nВы можете создать новое сообщение с датой.", keyboard=create_main_keyboard())
        elif user_id in poll_state:
            del poll_state[user_id]
            send_message(user_id, "❌ Создание опроса отменено.", keyboard=create_main_keyboard())
        else:
            schedule_key = f"schedule_import_{user_id}"
            if schedule_key in temp_storage:
                del temp_storage[schedule_key]
                send_message(user_id, "❌ Импорт расписания отменен.", keyboard=create_main_keyboard())
            else:
                send_message(user_id, "❌ Нет активных операций для отмены.")
        return True
    elif text_lower in ["/admin_stats", "admin_stats", "/adminstat", "админ статистика"]:
        if not is_vk_group_admin(user_id):
            send_message(user_id, "❌ Доступ запрещен. Только для администраторов VK сообщества.", keyboard=create_main_keyboard())
            return True
        stats = get_admin_stats_simple()
        if not stats:
            send_message(user_id, "❌ Ошибка получения статистики. Используйте /checkdb для диагностики.", keyboard=create_main_keyboard())
            return True
        message = f"""👨‍💼 АДМИН-СТАТИСТИКА

👥 Пользователи:
• Всего: {stats['users']['total']}
• Учителя: {stats['users']['teachers']}
• Ученики: {stats['users']['students']}
• Родители: {stats['users']['parents']}
• Админы: {stats['users']['admins']}

📊 Активность (всего):
• Сообщений: {stats['activity']['messages']}
• Фото: {stats['activity']['photos']}
• Объявлений: {stats['activity']['announcements']}
• Ошибок в сообщениях: {stats['activity']['errors']}
• Среднее время ответа: {stats['activity']['avg_response_time']} сек

🚨 Срочные сообщения: {stats['emergency']}
📅 Запланировано: {stats['scheduled']} сообщений

🔄 Последнее обновление: {stats['last_update']}"""
        send_message(user_id, message, keyboard=create_main_keyboard())
        return True
    elif text_lower in ["📊 статистика", "/stats", "stats", "статистика"]:
        db_stats = get_db_stats()
        send_message(user_id, f"📊 СТАТИСТИКА СИСТЕМЫ (из БД)\n\n📈 Общая статистика:\n• Сообщений сегодня: {db_stats['today_messages']}\n• Объявлений: {db_stats['announcements']}\n• Мероприятий: {db_stats['events']}\n• Изменений расписания: {db_stats['schedule']}\n• Срочных: {db_stats['emergency']}\n• Опросов: {db_stats['polls']}\n\n📺 TV Панели:\n• Активных: {db_stats['active_screens']}/{db_stats['total_screens']}\n• Запланировано: {db_stats['scheduled']}\n\n🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}", keyboard=create_main_keyboard())
        return True
    elif text_lower.startswith("/edit_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            message = get_message_by_id(msg_id, user_id)
            if message:
                edit_state[user_id] = {"message_id": msg_id, "original_text": message['message_text']}
                send_message(user_id, f"✏️ РЕДАКТИРОВАНИЕ СООБЩЕНИЯ ID: {msg_id}\n\n📝 Текущий текст:\n{message['message_text'][:300]}\n\n📝 Введите новый текст сообщения:", keyboard=create_main_keyboard())
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except:
            send_message(user_id, "❌ Используйте формат: /edit_1547")
        return True
    elif text_lower.startswith("/delete_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            if delete_bot_message_from_db(msg_id, user_id):
                send_message(user_id, f"✅ Сообщение ID {msg_id} успешно удалено!")
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except:
            send_message(user_id, "❌ Используйте формат: /delete_1547")
        return True
    elif text_lower.startswith("/duplicate_"):
        try:
            msg_id = int(text_lower.split("_")[1])
            message = get_message_by_id(msg_id, user_id)
            if message:
                new_message_id = save_bot_message_to_db(user_id, message['message_text'], message['message_type'], message['hashtag'], has_photo=message['has_photo'], photo_url=message['photo_url'])
                if message['message_type'] == 'announcement':
                    announcement_id = save_announcement_to_db(message['message_text'][:100] if message['message_text'] else "Без заголовка", message['message_text'], f"VK Пользователь {user_id}", message['message_type'])
                    send_message(user_id, f"✅ Сообщение ID {msg_id} дублировано!\n\n🆔 Новый ID: {new_message_id}\n📋 ID объявления: {announcement_id}\n📝 Тип: {message['hashtag']}\n\n📝 Текст:\n{message['message_text'][:200]}...", keyboard=create_main_keyboard())
                else:
                    send_message(user_id, f"✅ Сообщение ID {msg_id} дублировано!\n\n🆔 Новый ID: {new_message_id}\n📝 Тип: {message['hashtag']}\n\n📝 Текст:\n{message['message_text'][:200]}...", keyboard=create_main_keyboard())
                update_bot_stats(message['message_type'])
            else:
                send_message(user_id, f"❌ Сообщение ID {msg_id} не найдено или не принадлежит вам.")
        except Exception as e:
            send_message(user_id, "❌ Используйте формат: /duplicate_1547")
        return True
    elif text_lower in ["📝 мои сообщения", "/my_messages", "my_messages", "мои сообщения"]:
        messages = get_user_messages_from_db(user_id, limit=10)
        if not messages:
            send_message(user_id, "📭 У вас пока нет опубликованных сообщений.\n\n📝 Чтобы создать сообщение, используйте хештеги:\n• #объявление Текст - для объявления\n• #мероприятие Текст - для события\n• #срочно Текст - для срочного сообщения\n• #расписание Текст - для изменения расписания\n• #опрос Тема - для создания опроса\n\n📅 Для планирования укажите дату:\n• #мероприятие @15dec Новогодний бал\n\n👥 Групповые сообщения:\n• #объявление @9классы Текст\n\n💡 Пример: #опрос Выбор темы хакатона", keyboard=create_main_keyboard())
            return True
        msg_list = []
        for msg in messages:
            type_emoji = {'announcement': '📢', 'event': '🎉', 'schedule': '📅', 'emergency': '🚨', 'poll': '📊'}.get(msg['message_type'], '📝')
            if msg['created_at']:
                now = datetime.now()
                msg_date = msg['created_at']
                diff = now - msg_date
                if diff.days == 0:
                    date_str = f"сегодня, {msg_date.strftime('%H:%M')}"
                elif diff.days == 1:
                    date_str = f"вчера, {msg_date.strftime('%H:%M')}"
                elif diff.days == 2:
                    date_str = f"позавчера, {msg_date.strftime('%H:%M')}"
                else:
                    date_str = msg_date.strftime('%d.%m.%Y, %H:%M')
            else:
                date_str = "дата неизвестна"
            photo_mark = " 📸" if msg['has_photo'] else ""
            scheduled_mark = " 📅" if msg['is_scheduled'] else ""
            msg_text = msg['message_text'][:60] + "..." if msg['message_text'] and len(msg['message_text']) > 60 else (msg['message_text'] or "Без текста")
            msg_list.append(f"{type_emoji} [ID: {msg['id']}] {msg['hashtag'] or 'без хештега'} {msg_text}{photo_mark}{scheduled_mark} ({date_str})")
        total_count = get_user_messages_count(user_id)
        send_message(user_id, f"📋 ВАШИ ПОСЛЕДНИЕ СООБЩЕНИЯ:\n\n" + "\n".join(msg_list) + f"\n\n📊 Статистика:\n• Всего сообщений: {total_count}\n• Показано: {len(messages)} из {total_count}\n\n🔧 Действия (укажите ID сообщения):\n• /edit_ID - Редактировать сообщение\n• /delete_ID - Удалить сообщение\n• /duplicate_ID - Дублировать сообщение\n\n💡 Примеры:\n/edit_{messages[0]['id']} - редактировать\n/delete_{messages[0]['id']} - удалить\n/duplicate_{messages[0]['id']} - дублировать\n\n📝 Новое сообщение: #объявление Текст\n📅 С планированием: #мероприятие @15dec Новогодний бал\n👥 Групповое: #объявление @9классы Текст\n📊 Опрос: #опрос Тема опроса", keyboard=create_main_keyboard())
        return True
    elif text_lower in ["📅 запланированные", "/scheduled", "scheduled", "запланированные"]:
        send_message(user_id, "📅 ЗАПЛАНИРОВАННЫЕ СООБЩЕНИЯ\n\nФункция просмотра запланированных сообщений в разработке.\n\n💡 Чтобы запланировать сообщение, укажите дату:\nПример: #мероприятие @15dec Новогодний концерт\n\n🗓 Поддерживаемые форматы:\n• @15dec - 15 декабря\n• 15 декабря - текст события\n\n📝 После обнаружения даты выберите дни показа через запятую\nПример: 10,14,15", keyboard=create_main_keyboard())
        return True
    elif text_lower in ["❓ помощь", "/help", "help", "помощь", "start", "/start"]:
        send_message(user_id, f"📚 ДОСТУПНЫЕ КОМАНДЫ:\n\n⚡ Основные:\n/start - Начать работу\n/help - Помощь\n/stats - Статистика системы\n/my_messages - Мои сообщения\n\n🏷️ Хештеги для сообщений:\n#объявление - Общие новости\n#мероприятие - События и мероприятия\n#срочно - Срочное сообщение\n#расписание - Изменение расписания\n#опрос - Создать опрос\n\n📅 Планирование событий:\nУкажите дату в сообщении:\n• #мероприятие @15dec Новогодний бал\n• #мероприятие 15 декабря Новогодний бал\n\n👥 Групповые сообщения:\nДобавьте @9классы, @10классы, @11классы или @всем\n\n📊 Опросы:\n• #опрос Тема опроса\n• Затем введите варианты (каждый с новой строки)\n• Подтвердите: /confirm_poll\n• Отменить: /cancel_poll\n\n📅 Импорт расписания:\n• #расписание import\n• Прикрепите файл .xlsx или .csv\n• Подтвердите: /confirm_schedule\n\n✏️ Управление сообщениями:\n/edit_ID - Редактировать сообщение\n/delete_ID - Удалить сообщение\n/duplicate_ID - Дублировать сообщение\n\n❌ Отмена операций:\n/cancel - Отменить текущую операцию\n\n📞 Поддержка: @admin_school215", keyboard=create_main_keyboard())
        return True
    elif text_lower in ["/myrole", "myrole", "моя роль", "мои права"]:
        is_admin = is_vk_group_admin(user_id)
        role_info = get_user_vk_role(user_id)
        if is_admin:
            message = f"👑 ВАШИ ПРАВА В СООБЩЕСТВЕ\n\n✅ Вы являетесь администратором VK сообщества!\n\nДоступные команды:\n• /admin_stats - Статистика системы\n• Все команды бота\n\nРоль: {role_info}"
        else:
            message = f"👤 ВАШИ ПРАВА В СООБЩЕСТВЕ\n\n❌ Вы не являетесь администратором сообщества.\n\nДоступные команды:\n• /start - Начать работу\n• /help - Помощь\n• /stats - Статистика\n• /my_messages - Мои сообщения\n\nРоль: {role_info}"
        send_message(user_id, message, keyboard=create_main_keyboard())
        return True
    return False

def process_message(user_id, text, attachments=None):
    """Обрабатывает сообщение от пользователя"""
    print(f"📩 Новое сообщение от {user_id}: {text[:50] if text else '[Фото]'}...")
    print(f"📎 Вложения: {attachments}")
    
    # ===== 1. ПРОВЕРКА РЕЖИМА РЕДАКТИРОВАНИЯ =====
    if user_id in edit_state:
        state = edit_state[user_id]
        if update_bot_message_in_db(state["message_id"], text):
            send_message(user_id,
                f"✅ Сообщение ID {state['message_id']} успешно обновлено!\n\n"
                f"📝 Новый текст:\n{text[:300]}",
                keyboard=create_main_keyboard()
            )
        else:
            send_message(user_id, f"❌ Ошибка при обновлении сообщения ID {state['message_id']}")
        del edit_state[user_id]
        return
    
    # ===== 2. ПРОВЕРКА НА ОЖИДАНИЕ ФАЙЛА ДЛЯ ИМПОРТА РАСПИСАНИЯ =====
    schedule_key = f"schedule_import_{user_id}"
    if schedule_key in temp_storage and temp_storage[schedule_key].get("step") == "awaiting_file":
        
        # Если пользователь отправил текстовую команду отмены
        if text and text.lower() in ["/cancel", "отмена", "cancel"]:
            del temp_storage[schedule_key]
            send_message(user_id, "❌ Импорт расписания отменен.", keyboard=create_main_keyboard())
            return
        
        # Проверяем, есть ли вложения
        if not attachments:
            send_message(user_id, 
                "❌ Файл не найден!\n\n"
                "📎 Пожалуйста, прикрепите файл с расписанием:\n"
                "• Формат: .xlsx или .csv\n"
                "• Нажмите на скрепку 📎 и выберите \"Документ\"",
                keyboard=create_main_keyboard())
            return
        
        # Ищем файл во вложениях
        file_attached = None
        for att in attachments:
            att_type = att.get('type', '')
            print(f"Тип вложения: {att_type}")
            
            if att_type == 'doc':
                file_attached = att.get('doc')
                break
            elif att_type == 'document':
                file_attached = att.get('document')
                break
        
        if not file_attached:
            send_message(user_id, 
                "❌ Не удалось найти файл во вложениях.\n\n"
                "📎 Убедитесь, что вы прикрепляете файл правильно:\n"
                "1. Нажмите на скрепку 📎\n"
                "2. Выберите \"Документ\"\n"
                "3. Загрузите файл .xlsx или .csv",
                keyboard=create_main_keyboard())
            del temp_storage[schedule_key]
            return
        
        # Получаем информацию о файле
        file_url = file_attached.get('url')
        file_title = file_attached.get('title', 'файл')
        file_ext = file_title.split('.')[-1].lower() if '.' in file_title else ''
        
        print(f"Файл: {file_title}, расширение: {file_ext}")
        
        if file_ext not in ['xlsx', 'xls', 'csv']:
            send_message(user_id, 
                f"❌ Неподдерживаемый формат файла: .{file_ext}\n\n"
                f"📎 Поддерживаются: .xlsx, .xls, .csv\n\n"
                f"Пожалуйста, прикрепите файл в правильном формате.",
                keyboard=create_main_keyboard())
            del temp_storage[schedule_key]
            return
        
        send_message(user_id, f"⏳ Загрузка и обработка файла \"{file_title}\"...\n\nЭто может занять несколько секунд...", keyboard=create_main_keyboard())
        
        try:
            response = requests.get(file_url, timeout=30)
            file_content = response.content
            
            result, error = parse_schedule_file(file_content, f".{file_ext}")
            
            if error:
                send_message(user_id, f"❌ Ошибка обработки файла:\n\n{error}", keyboard=create_main_keyboard())
                del temp_storage[schedule_key]
                return
            
            temp_storage[schedule_key] = {
                "step": "awaiting_confirmation", 
                "data": result['data'], 
                "stats": result['stats']
            }
            
            classes_list = ", ".join(result['stats']['classes'])
            message = (
                f"✅ ФАЙЛ УСПЕШНО ОБРАБОТАН!\n\n"
                f"📊 НАЙДЕНО В ФАЙЛЕ:\n"
                f"• Уроков: {result['stats']['total']}\n"
                f"• Классы: {classes_list}\n"
                f"• Дней: {result['stats']['days_count']}\n"
                f"• Предметов: {result['stats']['subjects_count']}\n\n"
                f"❓ Подтвердить импорт расписания?\n"
                f"/confirm_schedule - Да, импортировать\n"
                f"/cancel - Отменить"
            )
            send_message(user_id, message, keyboard=create_main_keyboard())
            
        except requests.exceptions.Timeout:
            send_message(user_id, "❌ Ошибка: таймаут при загрузке файла. Попробуйте еще раз.", keyboard=create_main_keyboard())
            del temp_storage[schedule_key]
        except Exception as e:
            print(f"Ошибка обработки файла: {e}")
            send_message(user_id, f"❌ Ошибка обработки файла:\n\n{str(e)[:200]}", keyboard=create_main_keyboard())
            del temp_storage[schedule_key]
        return
    
    # ===== 3. ПРОВЕРКА НА ПОДТВЕРЖДЕНИЕ ИМПОРТА РАСПИСАНИЯ =====
    if text and text.lower() == "/confirm_schedule":
        schedule_key = f"schedule_import_{user_id}"
        if schedule_key in temp_storage and temp_storage[schedule_key].get("step") == "awaiting_confirmation":
            data = temp_storage[schedule_key]["data"]
            stats = temp_storage[schedule_key]["stats"]
            
            inserted, error = import_schedule_to_db(data)
            
            if error:
                send_message(user_id, f"❌ Ошибка импорта: {error}", keyboard=create_main_keyboard())
            else:
                send_message(user_id,
                    f"✅ РАСПИСАНИЕ ИМПОРТИРОВАНО!\n\n"
                    f"📊 Результат:\n"
                    f"• Добавлено уроков: {inserted}\n"
                    f"• Классы: {', '.join(stats['classes'])}\n"
                    f"• Дней: {stats['days_count']}\n\n"
                    f"🔄 Старое расписание заменено",
                    keyboard=create_main_keyboard()
                )
            del temp_storage[schedule_key]
        else:
            send_message(user_id, "❌ Нет ожидающего импорта расписания.\n\nИспользуйте: #расписание import", keyboard=create_main_keyboard())
        return
    
    # ===== 4. ПРОВЕРКА КОМАНД (КНОПКИ) =====
    if handle_command(user_id, text):
        return
    
    # ===== 5. ПРОВЕРКА НА ОЖИДАНИЕ ФОТО =====
    if attachments:
        photos = get_photo_info(attachments)
        if photos:
            photo = photos[0]
            send_message(user_id,
                f"📸 Фото получено!\n\n"
                f"📏 Размер: {photo['width']}×{photo['height']}\n"
                f"✅ Обработка завершена\n\n"
                f"📝 Добавьте описание с хештегом:\n"
                f"#объявление - для объявления\n"
                f"#мероприятие - для события\n"
                f"#срочно - для срочного сообщения\n"
                f"#опрос - для создания опроса\n\n"
                f"📅 Для планирования укажите дату: @15dec\n\n"
                f"👥 Для группового сообщения добавьте @9классы\n\n"
                f"💡 Пример: #опрос Выбор темы хакатона",
                keyboard=create_main_keyboard()
            )
            
            user_photo_state[f"photo_{user_id}"] = {
                "url": photo["url"],
                "width": photo["width"],
                "height": photo["height"]
            }
            return
    
    # ===== 6. ПРОВЕРКА НАЛИЧИЯ ХЕШТЕГА =====
    hashtag, msg_type, content = detect_hashtag(text)
    
    if not hashtag:
        send_message(user_id,
            f"❌ Не указан тип сообщения\n\n"
            f"📝 Используйте хештеги:\n"
            f"• #объявление - общие новости\n"
            f"• #расписание - изменения расписания\n"
            f"• #мероприятие - события\n"
            f"• #срочно - срочные объявления\n"
            f"• #опрос - создать опрос\n\n"
            f"📅 Для планирования: #мероприятие @15dec Новогодний бал\n\n"
            f"👥 Для группового сообщения: #объявление @9классы Текст\n\n"
            f"💡 Пример: #объявление Уважаемые родители!",
            keyboard=create_main_keyboard()
        )
        return
    
    if not content and msg_type != "poll":
        send_message(user_id,
            f"❌ Текст сообщения не может быть пустым\n\n"
            f"📝 Пример: {hashtag} Текст вашего сообщения",
            keyboard=create_main_keyboard()
        )
        return
    
    # ===== 7. ОБРАБОТКА ИМПОРТА РАСПИСАНИЯ (КОМАНДА) =====
    if hashtag == "#расписание" and "import" in content.lower():
        send_message(user_id,
            f"📅 ИМПОРТ РАСПИСАНИЯ\n\n"
            f"📎 Прикрепите файл:\n"
            f"• Формат: .xlsx или .csv\n"
            f"• Или отправьте Google Sheets ссылку\n\n"
            f"💡 Пример структуры:\n"
            f"| День | Время | Класс | Предмет | Кабинет |",
            keyboard=create_main_keyboard()
        )
        temp_storage[f"schedule_import_{user_id}"] = {"step": "awaiting_file"}
        return
    
    # ===== 8. ОБРАБОТКА ОПРОСОВ =====
    if msg_type == "poll":
        handle_poll_creation(user_id, hashtag, msg_type, content)
        return
    
    # ===== 9. ОБРАБОТКА ГРУППОВЫХ СООБЩЕНИЙ =====
    group_key, target_groups = detect_group_mention(content)
    
    if group_key and msg_type in ["announcement", "event"]:
        handle_group_message(user_id, hashtag, msg_type, content)
        return
    
    # ===== 10. ОБРАБОТКА ПЛАНИРОВАНИЯ ПО ДАТЕ =====
    event_date = parse_date_from_text(content)
    
    if event_date and msg_type in ["event", "announcement"]:
        handle_date_planning(user_id, hashtag, msg_type, content, event_date)
        return
    
    # ===== 11. ОБРАБОТКА СРОЧНЫХ СООБЩЕНИЙ =====
    if msg_type == "emergency":
        send_message(user_id,
            f"⚠️ ПРИНЯТО СРОЧНОЕ СООБЩЕНИЕ!\n\n"
            f"Внимание! Сообщение будет показано на ВСЕХ панелях\n\n"
            f"📝 Текст: {content[:200]}\n\n"
            f"✅ Подтвердите отправку: /confirm_emergency\n"
            f"❌ Отменить: /cancel_emergency",
            keyboard=create_main_keyboard()
        )
        temp_storage[f"emergency_{user_id}"] = {
            "hashtag": hashtag, 
            "content": content,
            "msg_type": msg_type
        }
        return
    
    # ===== 12. СОХРАНЕНИЕ ОБЫЧНОГО СООБЩЕНИЯ =====
    message_id = save_bot_message_to_db(
        user_id=user_id,
        message_text=content,
        message_type=msg_type,
        hashtag=hashtag
    )
    
    # Если это объявление, сохраняем также в таблицу announcements
    if msg_type == "announcement":
        announcement_id = save_announcement_to_db(
            title=content[:100] if content else "Без заголовка",
            content=content,
            author_name=f"VK Пользователь {user_id}",
            announcement_type=msg_type
        )
        
        send_message(user_id,
            f"✅ Объявление опубликовано!\n\n"
            f"📢 Тип: {hashtag}\n"
            f"🆔 ID в БД: {message_id}\n"
            f"📋 ID объявления: {announcement_id}\n"
            f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"📝 Текст:\n{content[:300]}...\n\n"
            f"📺 Сообщение отправлено на TV-панели школы",
            keyboard=create_main_keyboard()
        )
    else:
        send_message(user_id,
            f"✅ Сообщение сохранено!\n\n"
            f"🏷 Тип: {hashtag}\n"
            f"🆔 ID: {message_id}\n"
            f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"📝 Текст:\n{content[:300]}...",
            keyboard=create_main_keyboard()
        )
    
    # Обновляем статистику
    update_bot_stats(msg_type)

def get_longpoll_server():
    params = {"group_id": GROUP_ID, "access_token": ACCESS_TOKEN, "v": "5.199"}
    response = requests.get(f"{VK_API_URL}groups.getLongPollServer", params=params)
    data = response.json()
    if "response" in data:
        return data["response"]["server"], data["response"]["key"], data["response"]["ts"]
    return None, None, None

def listen_messages():
    print("=" * 60)
    print("🚀 VK Бот запущен с подключением к PostgreSQL!")
    print(f"📱 Группа ID: {GROUP_ID}")
    print(f"🗄️ База данных: {DB_CONFIG['database']}")
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