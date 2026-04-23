from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os
import json
import hashlib
import secrets
from pathlib import Path
from functools import wraps

app = Flask(__name__)
CORS(app)

# Настройки БД
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'school215',
    'user': 'postgres',
    'password': '2708'
}

PHOTO_STORAGE_PATH = "img/mero"
ANNOUNCEMENTS_DURATION = 45  # 45 секунд объявления
PHOTO_DURATION = 10  # 10 секунд фото

# Кэш для токенов
active_tokens = {}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def require_token(f):
    """Декоратор для проверки токена"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('X-TV-Token')
        if not token:
            return jsonify({'error': 'Token required'}), 401
        
        # Проверяем токен в БД
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT panel_name, location, is_active 
                FROM tv_panels 
                WHERE token = %s AND is_active = true
            """, (token,))
            panel = cur.fetchone()
            
            if not panel:
                return jsonify({'error': 'Invalid or expired token'}), 401
            
            # Обновляем last_seen
            cur.execute("""
                UPDATE tv_panels 
                SET last_seen = NOW(), last_update = NOW()
                WHERE token = %s
            """, (token,))
            conn.commit()
            
            request.panel_info = panel
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            cur.close()
            conn.close()
    
    return decorated_function

@app.route('/api/tv/login', methods=['POST'])
def tv_login():
    """Авторизация TV панели"""
    data = request.json
    panel_name = data.get('panel_name')
    location = data.get('location', '')
    mac_address = data.get('mac_address', '')
    
    if not panel_name:
        return jsonify({'error': 'panel_name required'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Генерируем уникальный токен
        token = secrets.token_hex(32)
        
        # Проверяем, существует ли уже панель с таким именем
        cur.execute("SELECT id FROM tv_panels WHERE panel_name = %s", (panel_name,))
        existing = cur.fetchone()
        
        if existing:
            # Обновляем существующую панель
            cur.execute("""
                UPDATE tv_panels 
                SET token = %s, location = %s, is_active = true, 
                    last_seen = NOW(), last_update = NOW(),
                    mode = 'normal'
                WHERE panel_name = %s
                RETURNING id, panel_name, token
            """, (token, location, panel_name))
        else:
            # Создаем новую панель
            cur.execute("""
                INSERT INTO tv_panels (panel_name, location, token, is_active, last_seen, last_update, mode)
                VALUES (%s, %s, %s, true, NOW(), NOW(), 'normal')
                RETURNING id, panel_name, token
            """, (panel_name, location, token))
        
        panel = cur.fetchone()
        conn.commit()
        
        return jsonify({
            'success': True,
            'token': token,
            'panel_id': panel[0],
            'panel_name': panel[1]
        })
        
    except Exception as e:
        conn.rollback()
        print(f"Ошибка авторизации: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/tv/logout', methods=['POST'])
@require_token
def tv_logout():
    """Выход TV панели"""
    token = request.headers.get('X-TV-Token')
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE tv_panels 
            SET is_active = false, mode = 'offline'
            WHERE token = %s
        """, (token,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/tv/check', methods=['GET'])
@require_token
def check_auth():
    """Проверка авторизации"""
    return jsonify({'valid': True, 'panel_info': request.panel_info})

@app.route('/api/tv/data', methods=['GET'])
@require_token
def get_tv_data():
    """Получает данные для TV панели"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Проверяем режим ЧС для этой панели
        cur.execute("""
            SELECT mode, emergency_message 
            FROM tv_panels 
            WHERE token = %s
        """, (request.headers.get('X-TV-Token'),))
        panel = cur.fetchone()
        
        # Если включен режим ЧС
        if panel and panel['mode'] == 'emergency':
            return jsonify({
                'mode': 'emergency',
                'emergency_message': panel['emergency_message'] or 'Внимание! Чрезвычайная ситуация!',
                'announcements': [],
                'photos': []
            })
        
        # Получаем активные объявления (не старше 7 дней)
        cur.execute("""
            SELECT id, title, content, author_name, announcement_type, target_class, created_at
            FROM announcements 
            WHERE created_at >= NOW() - INTERVAL '7 days'
            AND announcement_type != 'poll'
            ORDER BY 
                CASE announcement_type
                    WHEN 'emergency' THEN 1
                    WHEN 'event' THEN 2
                    WHEN 'announcement' THEN 3
                    WHEN 'schedule' THEN 4
                    ELSE 5
                END,
                created_at DESC
            LIMIT 20
        """)
        announcements = cur.fetchall()
        
        # Форматируем объявления для TV
        tv_announcements = []
        for ann in announcements:
            tv_announcements.append({
                'id': ann['id'],
                'title': ann['title'],
                'content': ann['content'],
                'author': ann['author_name'],
                'type': ann['announcement_type'],
                'time': ann['created_at'].strftime('%H:%M'),
                'target': ann['target_class'] or 'Все классы',
                'created_at': ann['created_at'].isoformat()
            })
        
        # Получаем фото для сегодняшнего дня из папки img/mero
        today = datetime.now().date()
        photo_folder = Path(PHOTO_STORAGE_PATH)
        photos = []
        
        if photo_folder.exists():
            for photo_file in sorted(photo_folder.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if photo_file.is_file() and photo_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    # Получаем время создания файла
                    file_time = datetime.fromtimestamp(photo_file.stat().st_mtime)
                    
                    # Показываем только фото за сегодня
                    if file_time.date() == today:
                        # Пытаемся получить описание из БД
                        cur.execute("""
                            SELECT message_text, user_id 
                            FROM bot_messages 
                            WHERE photo_url LIKE %s 
                            ORDER BY created_at DESC LIMIT 1
                        """, (f'%{photo_file.name}%',))
                        photo_info = cur.fetchone()
                        
                        caption = ""
                        if photo_info and photo_info['message_text']:
                            caption = photo_info['message_text'][:100]
                        
                        photos.append({
                            'photo_url': f'/img/mero/{photo_file.name}',
                            'caption': caption,
                            'created_at': file_time.isoformat(),
                            'filename': photo_file.name
                        })
        
        # Получаем статистику панелей
        cur.execute("SELECT COUNT(*) as active FROM tv_panels WHERE is_active = true")
        active_panels = cur.fetchone()['active'] or 0
        
        cur.execute("SELECT COUNT(*) as total FROM tv_panels")
        total_panels = cur.fetchone()['total'] or 0
        
        return jsonify({
            'mode': 'normal',
            'announcements': tv_announcements,
            'photos': photos,
            'announcements_duration': ANNOUNCEMENTS_DURATION,
            'photo_duration': PHOTO_DURATION,
            'system_status': 'работает',
            'panels_active': active_panels,
            'panels_total': total_panels,
            'panel_name': request.panel_info[0] if request.panel_info else 'TV Панель',
            'next_update': 30
        })
        
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/tv/emergency', methods=['POST'])
@require_token
def set_emergency_mode():
    """Установка режима ЧС на панели"""
    data = request.json
    mode = data.get('mode', 'normal')
    message = data.get('message', '')
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE tv_panels 
            SET mode = %s, emergency_message = %s, last_update = NOW()
            WHERE token = %s
        """, (mode, message, request.headers.get('X-TV-Token')))
        conn.commit()
        return jsonify({'success': True, 'mode': mode})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/img/mero/<path:filename>')
def serve_photo(filename):
    """Отдает фото для TV панели"""
    try:
        # Проверяем безопасность пути
        safe_path = os.path.normpath(os.path.join(PHOTO_STORAGE_PATH, filename))
        if not safe_path.startswith(os.path.normpath(PHOTO_STORAGE_PATH)):
            return jsonify({'error': 'Invalid path'}), 403
        
        if os.path.exists(safe_path):
            return send_file(safe_path, mimetype='image/jpeg')
        else:
            return jsonify({'error': 'Photo not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@app.route('/api/tv/panels', methods=['GET'])
def get_all_panels():
    """Получить список всех панелей (для администрирования)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, panel_name, location, is_active, mode, 
                   last_seen, last_update, emergency_message
            FROM tv_panels 
            ORDER BY panel_name
        """)
        panels = cur.fetchall()
        return jsonify({'panels': panels})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/tv/panels/<int:panel_id>', methods=['PUT'])
def update_panel(panel_id):
    """Обновить настройки панели"""
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        updates = []
        params = []
        
        if 'mode' in data:
            updates.append("mode = %s")
            params.append(data['mode'])
        if 'emergency_message' in data:
            updates.append("emergency_message = %s")
            params.append(data['emergency_message'])
        if 'is_active' in data:
            updates.append("is_active = %s")
            params.append(data['is_active'])
        
        if updates:
            params.append(panel_id)
            cur.execute(f"""
                UPDATE tv_panels 
                SET {', '.join(updates)}, last_update = NOW()
                WHERE id = %s
            """, params)
            conn.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Добавьте в конец файла tv_api.py, перед if __name__ == '__main__':

@app.route('/')
def index():
    """Главная страница"""
    return send_from_directory('.', 'tv-panel.html')

@app.route('/tv-panel')
def tv_panel():
    """Страница TV панели"""
    return send_from_directory('.', 'tv-panel.html')

@app.route('/tv-panel.html')
def tv_panel_html():
    """Страница TV панели"""
    return send_from_directory('.', 'tv-panel.html')

# Также добавьте поддержку статических файлов
@app.route('/static/<path:filename>')
def static_files(filename):
    """Статические файлы"""
    return send_from_directory('static', filename)

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 TV API Сервер запущен!")
    print(f"📸 Папка с фото: {PHOTO_STORAGE_PATH}")
    print(f"⏱ Объявления: {ANNOUNCEMENTS_DURATION} сек, Фото: {PHOTO_DURATION} сек")
    print("🌐 http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)