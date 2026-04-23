from flask import Flask, jsonify, request, send_from_directory, session, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import hashlib
import secrets
import os
import mimetypes

app = Flask(__name__, static_folder='../frontend', static_url_path='')
app.config['SECRET_KEY'] = 'school215-secret-key-2024'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
CORS(app, supports_credentials=True)

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'school215',
    'user': 'postgres',
    'password': '2708'
}

app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}

db = SQLAlchemy(app)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password, hash_value):
    return hash_password(password) == hash_value

# ==================== МОДЕЛИ ====================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='teacher')
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    class_name = db.Column(db.String(50))
    parent_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Grade(db.Model):
    __tablename__ = 'grades'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    subject = db.Column(db.String(100))
    grade_value = db.Column(db.Integer)
    work_type = db.Column(db.String(50))
    topic = db.Column(db.String(200))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.Text)

class Homework(db.Model):
    __tablename__ = 'homeworks'
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50))
    subject = db.Column(db.String(100))
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    task = db.Column(db.Text)
    deadline = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Schedule(db.Model):
    __tablename__ = 'schedules'
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50))
    day_of_week = db.Column(db.Integer)
    lesson_number = db.Column(db.Integer)
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    subject = db.Column(db.String(100))
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    room = db.Column(db.String(50))

class TVPanel(db.Model):
    __tablename__ = 'tv_panels'
    id = db.Column(db.Integer, primary_key=True)
    panel_name = db.Column(db.String(100))
    location = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    last_update = db.Column(db.DateTime, default=datetime.utcnow)
    mode = db.Column(db.String(20), default='normal')
    urgent_only = db.Column(db.Boolean, default=False)  # Добавлено поле
    emergency_message = db.Column(db.Text, nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(100), unique=True)
    
    @property
    def is_online(self):
        if not self.last_seen:
            return False
        return datetime.utcnow() - self.last_seen < timedelta(minutes=2)

# Таблица связи
class AnnouncementTVPanel(db.Model):
    __tablename__ = 'announcement_tv_panels'
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), primary_key=True)
    tv_panel_id = db.Column(db.Integer, db.ForeignKey('tv_panels.id', ondelete='CASCADE'), primary_key=True)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author_name = db.Column(db.String(255))
    announcement_type = db.Column(db.String(50), default='general')
    target_class = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tv_panels = db.relationship('TVPanel', secondary='announcement_tv_panels',
                                primaryjoin="Announcement.id == AnnouncementTVPanel.announcement_id",
                                secondaryjoin="TVPanel.id == AnnouncementTVPanel.tv_panel_id",
                                viewonly=False, lazy='dynamic')

# ==================== СТРАНИЦЫ ====================

@app.route('/')
def index():
    return send_from_directory('../frontend', 'login.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('../frontend', 'ADMIN_PANEL.html')

@app.route('/parent')
def parent_page():
    return send_from_directory('../frontend', 'PARENT_PANEL.html')

@app.route('/tv')
def tv_panel_page():
    return send_from_directory('../frontend', 'tv.html')

@app.route('/tv-login')
def tv_login_page():
    return send_from_directory('../frontend', 'tv-login.html')

# ==================== ОБЪЯВЛЕНИЯ ====================

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
        
        result = []
        for a in announcements:
            # Получаем связи через прямую таблицу
            links = db.session.query(AnnouncementTVPanel).filter_by(announcement_id=a.id).all()
            tv_panel_ids = [link.tv_panel_id for link in links]
            
            result.append({
                'id': a.id,
                'title': a.title,
                'content': a.content,
                'author_name': a.author_name,
                'announcement_type': a.announcement_type,
                'target_class': a.target_class,
                'created_at': a.created_at.isoformat(),
                'tv_panel_ids': tv_panel_ids
            })
        
        print(f"📋 Возвращено {len(result)} объявлений")
        return jsonify(result)
    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if user.role not in ['admin']:
            return jsonify({'error': 'Недостаточно прав'}), 403
        
        data = request.json
        print(f"📝 Создание объявления, получены данные: {data}")
        
        announcement = Announcement(
            title=data['title'],
            content=data['content'],
            author_id=user_id,
            author_name=user.full_name,
            announcement_type=data.get('announcement_type', 'general'),
            target_class=data.get('target_class')
        )
        
        db.session.add(announcement)
        db.session.flush()
        
        # Сохраняем связи с TV панелями
        tv_panel_ids = data.get('tv_panel_ids', [])
        print(f"📺 TV панели для объявления {announcement.id}: {tv_panel_ids}")
        
        for panel_id in tv_panel_ids:
            tv_panel = db.session.get(TVPanel, panel_id)
            if tv_panel:
                link = AnnouncementTVPanel(
                    announcement_id=announcement.id, 
                    tv_panel_id=panel_id
                )
                db.session.add(link)
                print(f"   ✅ Добавлена связь с панелью {panel_id} ({tv_panel.panel_name})")
            else:
                print(f"   ❌ Панель {panel_id} не найдена")
        
        db.session.commit()
        print(f"✅ Объявление {announcement.id} создано с {len(tv_panel_ids)} TV панелями")
        
        return jsonify({'success': True, 'announcement_id': announcement.id})
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements/<int:announcement_id>', methods=['PUT'])
def update_announcement(announcement_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if user.role not in ['admin']:
            return jsonify({'error': 'Недостаточно прав'}), 403
        
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return jsonify({'error': 'Объявление не найдено'}), 404
        
        data = request.json
        announcement.title = data.get('title', announcement.title)
        announcement.content = data.get('content', announcement.content)
        announcement.announcement_type = data.get('announcement_type', announcement.announcement_type)
        announcement.target_class = data.get('target_class', announcement.target_class)
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements/<int:announcement_id>', methods=['DELETE'])
def delete_announcement(announcement_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if user.role not in ['admin']:
            return jsonify({'error': 'Недостаточно прав'}), 403
        
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return jsonify({'error': 'Объявление не найдено'}), 404
        
        db.session.query(AnnouncementTVPanel).filter_by(announcement_id=announcement_id).delete()
        db.session.delete(announcement)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements/<int:announcement_id>/tv', methods=['PUT'])
def update_announcement_tv_panels(announcement_id):
    """Обновление списка TV-панелей для объявления"""
    try:
        user_id = session.get('user_id')
        print(f"🔍 user_id из сессии: {user_id}")
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        print(f"🔍 Найден пользователь: {user.username if user else 'None'}, роль: {user.role if user else 'None'}")
        if not user or user.role not in ['admin']:
            return jsonify({'error': f'Недостаточно прав. Ваша роль: {user.role if user else "None"}'}), 403
        
        announcement = db.session.get(Announcement, announcement_id)
        if not announcement:
            return jsonify({'error': 'Объявление не найдено'}), 404
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400
        
        tv_panel_ids = data.get('tv_panel_ids', [])
        
        print(f"📺 Обновление TV-панелей для объявления {announcement_id}: {tv_panel_ids}")
        
        # Удаляем старые связи
        deleted = db.session.query(AnnouncementTVPanel).filter_by(announcement_id=announcement_id).delete()
        print(f"   Удалено старых связей: {deleted}")
        
        # Добавляем новые связи
        added_count = 0
        for panel_id in tv_panel_ids:
            tv_panel = db.session.get(TVPanel, panel_id)
            if tv_panel:
                link = AnnouncementTVPanel(announcement_id=announcement_id, tv_panel_id=panel_id)
                db.session.add(link)
                added_count += 1
                print(f"   Добавлена связь с панелью {panel_id} ({tv_panel.panel_name})")
        
        db.session.commit()
        print(f"✅ Сохранено {added_count} связей для объявления {announcement_id}")
        
        return jsonify({
            'success': True, 
            'message': f'Настройки TV-панелей сохранены',
            'added': added_count
        })
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка при сохранении: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ==================== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ====================

@app.route('/api/users', methods=['GET'])
def get_users():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        
        if user.role == 'parent':
            users = User.query.filter(User.role.in_(['student', 'parent'])).order_by(User.full_name).all()
        else:
            users = User.query.order_by(User.role, User.full_name).all()
        
        return jsonify([{
            'id': u.id,
            'fullName': u.full_name,
            'full_name': u.full_name,
            'username': u.username,
            'role': u.role,
            'class_name': u.class_name,
            'parent_id': u.parent_id,
            'created_at': u.created_at.isoformat() if u.created_at else None
        } for u in users])
    except Exception as e:
        print(f"Ошибка в /api/users: {e}")
        return jsonify([])

@app.route('/api/users', methods=['POST'])
def create_user():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        admin = db.session.get(User, user_id)
        if admin.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        data = request.json
        
        if not data.get('full_name'):
            return jsonify({'error': 'Введите ФИО'}), 400
        if not data.get('username'):
            return jsonify({'error': 'Введите логин'}), 400
        if not data.get('password') or len(data.get('password')) < 6:
            return jsonify({'error': 'Пароль должен быть минимум 6 символов'}), 400
        
        existing = User.query.filter_by(username=data['username']).first()
        if existing:
            return jsonify({'error': f'Пользователь с логином "{data["username"]}" уже существует'}), 400
        
        new_user = User(
            full_name=data['full_name'],
            username=data['username'],
            password_hash=hash_password(data['password']),
            role=data.get('role', 'student'),
            class_name=data.get('class_name') if data.get('role') == 'student' else None,
            parent_id=data.get('parent_id')
        )
        
        # Если создается TV-панель, создаем запись в TVPanel
        if new_user.role == 'tv':
            tv_panel = TVPanel(
                panel_name=new_user.full_name,
                location='Не указано',
                token=secrets.token_urlsafe(32),
                last_seen=datetime.utcnow(),
                mode='normal',
                urgent_only=False
            )
            db.session.add(tv_panel)
        
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'user': {
                'id': new_user.id,
                'fullName': new_user.full_name,
                'username': new_user.username,
                'role': new_user.role,
                'class_name': new_user.class_name,
                'parent_id': new_user.parent_id
            }
        })
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка создания пользователя: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    try:
        admin_id = session.get('user_id')
        if not admin_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        admin = db.session.get(User, admin_id)
        if admin.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        data = request.json
        
        user.full_name = data.get('full_name', user.full_name)
        user.role = data.get('role', user.role)
        user.class_name = data.get('class_name')
        
        if 'parent_id' in data:
            user.parent_id = data['parent_id']
        
        if data.get('password'):
            user.password_hash = hash_password(data['password'])
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        admin_id = session.get('user_id')
        if not admin_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        admin = db.session.get(User, admin_id)
        if admin.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        if user.id == admin_id:
            return jsonify({'error': 'Нельзя удалить самого себя'}), 400
        
        # Если удаляем TV-пользователя, удаляем и TVPanel
        if user.role == 'tv':
            tv_panel = TVPanel.query.filter_by(panel_name=user.full_name).first()
            if tv_panel:
                # Удаляем связи с объявлениями
                db.session.query(AnnouncementTVPanel).filter_by(tv_panel_id=tv_panel.id).delete()
                db.session.delete(tv_panel)
        
        if user.role == 'parent':
            children = User.query.filter_by(parent_id=user.id).all()
            for child in children:
                child.parent_id = None
            print(f"👪 Отвязано {len(children)} детей от родителя {user.full_name}")
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка при удалении: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:user_id>/reset-password', methods=['POST'])
def reset_user_password(user_id):
    try:
        admin_id = session.get('user_id')
        if not admin_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        admin = db.session.get(User, admin_id)
        if admin.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        data = request.json
        new_password = data.get('password', '123456')
        user.password_hash = hash_password(new_password)
        db.session.commit()
        
        return jsonify({'success': True, 'new_password': new_password})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/parents', methods=['GET'])
def get_parents():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        parents = User.query.filter_by(role='parent').order_by(User.full_name).all()
        return jsonify([{
            'id': p.id,
            'full_name': p.full_name
        } for p in parents])
    except Exception as e:
        return jsonify([])

@app.route('/api/students/unassigned', methods=['GET'])
def get_unassigned_students():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        students = User.query.filter_by(role='student').filter(User.parent_id.is_(None)).order_by(User.full_name).all()
        return jsonify([{
            'id': s.id,
            'full_name': s.full_name,
            'class_name': s.class_name
        } for s in students])
    except Exception as e:
        return jsonify([])

# ==================== TV ПАНЕЛИ ====================

@app.route('/api/tv-panels', methods=['GET'])
def get_tv_panels():
    try:
        panels = TVPanel.query.all()
        now = datetime.utcnow()
        two_minutes_ago = now - timedelta(minutes=2)
        
        result = []
        for p in panels:
            try:
                result.append({
                    'id': p.id,
                    'panel_name': p.panel_name or 'Без названия',
                    'location': p.location or 'Не указано',
                    'is_active': p.last_seen > two_minutes_ago if p.last_seen else False,
                    'last_update': p.last_update.isoformat() if p.last_update else None,
                    'last_seen': p.last_seen.isoformat() if p.last_seen else None,
                    'mode': p.mode or 'normal',
                    'urgent_only': getattr(p, 'urgent_only', False),  # Безопасное получение
                    'has_token': bool(p.token)
                })
            except Exception as e:
                print(f"⚠️ Ошибка при обработке панели {p.id}: {e}")
                continue
        
        print(f"✅ Загружено {len(result)} TV-панелей")
        return jsonify(result)
    except Exception as e:
        print(f"❌ Ошибка в /api/tv-panels: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200  # Возвращаем пустой массив вместо ошибки 500

@app.route('/api/tv/login', methods=['POST'])
def tv_login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify({'error': 'Неверный логин или пароль'}), 401
        
        if user.role != 'tv':
            return jsonify({'error': 'Доступ запрещен'}), 401
        
        tv_panel = TVPanel.query.filter_by(panel_name=user.full_name).first()
        if not tv_panel:
            tv_panel = TVPanel(
                panel_name=user.full_name,
                location='Не указано',
                token=secrets.token_urlsafe(32),
                last_seen=datetime.utcnow() - timedelta(hours=1),
                mode='normal',
                urgent_only=False
            )
            db.session.add(tv_panel)
        
        tv_panel.token = secrets.token_urlsafe(32)
        tv_panel.last_seen = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'token': tv_panel.token,
            'panel_id': tv_panel.id,
            'panel_name': tv_panel.panel_name
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/logout', methods=['POST'])
def tv_logout():
    try:
        token = request.headers.get('X-TV-Token')
        if token:
            tv_panel = TVPanel.query.filter_by(token=token).first()
            if tv_panel:
                tv_panel.last_seen = datetime.utcnow() - timedelta(hours=1)
                db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/check', methods=['GET'])
def tv_check():
    token = request.headers.get('X-TV-Token')
    if not token:
        return jsonify({'error': 'Token required'}), 401
    
    tv_panel = TVPanel.query.filter_by(token=token).first()
    if not tv_panel:
        return jsonify({'error': 'Invalid token'}), 401
    
    tv_panel.last_seen = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'valid': True, 
        'panel_name': tv_panel.panel_name,
        'panel_id': tv_panel.id,
        'mode': tv_panel.mode,
        'urgent_only': tv_panel.urgent_only
    })

@app.route('/api/tv/data', methods=['GET'])
def tv_data():
    """Получение данных для ТВ-панели по токену"""
    try:
        token = request.headers.get('X-TV-Token')
        if not token:
            print("❌ Нет токена в запросе")
            return jsonify({'error': 'Требуется токен авторизации'}), 401
        
        print(f"🔍 Поиск панели по токену: {token[:30]}...")
        
        tv = TVPanel.query.filter_by(token=token).first()
        if not tv:
            print(f"❌ Панель не найдена для токена: {token[:30]}...")
            return jsonify({'error': 'Неверный токен'}), 401
        
        print(f"✅ Найдена панель: {tv.panel_name} (ID: {tv.id})")
        print(f"   Режим панели: mode={tv.mode}, urgent_only={tv.urgent_only}")
        
        # Обновляем время последнего контакта
        tv.last_seen = datetime.utcnow()
        db.session.commit()
        
        # Получаем объявления
        announcements = []
        
        if tv.mode == 'emergency':
            announcements = [{
                'title': '⚠️ ЧРЕЗВЫЧАЙНАЯ СИТУАЦИЯ ⚠️',
                'content': tv.emergency_message or 'Следуйте указаниям персонала',
                'type': 'emergency',
                'author': 'Администрация',
                'time': datetime.now().strftime('%H:%M'),
                'target': 'ВСЯ ШКОЛА'
            }]
        else:
            # Получаем все объявления
            all_announcements = Announcement.query.order_by(Announcement.created_at.desc()).limit(20).all()
            print(f"   Всего объявлений в БД: {len(all_announcements)}")
            
            for a in all_announcements:
                # Получаем ID TV-панелей для этого объявления
                links = db.session.query(AnnouncementTVPanel).filter_by(announcement_id=a.id).all()
                tv_panel_ids = [link.tv_panel_id for link in links]
                
                print(f"   Объявление {a.id} '{a.title[:30]}': тип={a.announcement_type}, TV панели = {tv_panel_ids}")
                
                # Проверяем, должно ли объявление показываться на этой панели
                if len(tv_panel_ids) == 0:
                    print(f"      ⏭️ Пропущено (не назначено ни одной панели)")
                    continue
                
                if tv.id not in tv_panel_ids:
                    print(f"      ⏭️ Пропущено (не для этой панели)")
                    continue
                
                # Если включен режим "только срочные", показываем только срочные объявления
                if tv.urgent_only and a.announcement_type != 'emergency':
                    print(f"      ⏭️ Пропущено (режим 'только срочные', а объявление не срочное)")
                    continue
                
                announcements.append({
                    'title': a.title,
                    'content': a.content,
                    'type': a.announcement_type,
                    'author': a.author_name,
                    'time': a.created_at.strftime('%H:%M') if a.created_at else '',
                    'target': a.target_class or 'Все классы'
                })
                print(f"      ✅ ДОБАВЛЕНО для панели {tv.panel_name}")
            
            announcements = announcements[:8]
            print(f"   Итого объявлений для панели {tv.panel_name}: {len(announcements)}")
        
        # Статистика
        total_panels = TVPanel.query.count()
        active_panels = TVPanel.query.filter(
            TVPanel.last_seen > datetime.utcnow() - timedelta(minutes=5)
        ).count()
        
        result = {
            'mode': tv.mode,
            'urgent_only': tv.urgent_only,
            'panel_mode': 'urgent_only' if tv.urgent_only else tv.mode,
            'panel_name': tv.panel_name,
            'announcements': announcements,
            'system_status': 'online',
            'panels_total': total_panels,
            'panels_active': active_panels,
            'next_update': 45
        }
        
        print(f"✅ Ответ отправлен, объявлений: {len(announcements)}")
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА в /api/tv/data: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'details': 'Internal server error'}), 500

@app.route('/api/tv/photos', methods=['GET'])
def get_tv_photos():
    try:
        token = request.headers.get('X-TV-Token')
        if not token:
            return jsonify({'error': 'Требуется токен'}), 401
        
        tv = TVPanel.query.filter_by(token=token).first()
        if not tv:
            return jsonify({'error': 'Неверный токен'}), 401
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        photo_folder = os.path.join(current_dir, '..', 'img', 'mero')
        photo_folder = os.path.abspath(photo_folder)
        
        photos = []
        
        if os.path.exists(photo_folder):
            for filename in os.listdir(photo_folder):
                if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    filepath = os.path.join(photo_folder, filename)
                    file_time = os.path.getmtime(filepath)
                    file_datetime = datetime.fromtimestamp(file_time)
                    
                    if datetime.now() - file_datetime < timedelta(days=7):
                        caption = os.path.splitext(filename)[0].replace('_', ' ').replace('-', ' ')
                        photos.append({
                            'photo_url': f'/api/tv/photo/{filename}',
                            'caption': caption,
                            'created_at': file_datetime.isoformat(),
                            'filename': filename
                        })
            
            photos.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({'photos': photos})
    except Exception as e:
        return jsonify({'photos': []})

@app.route('/api/tv/photo/<path:filename>')
def serve_tv_photo(filename):
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        photo_folder = os.path.join(current_dir, '..', 'img', 'mero')
        photo_folder = os.path.abspath(photo_folder)
        
        filepath = os.path.join(photo_folder, filename)
        filepath = os.path.abspath(filepath)
        
        if not filepath.startswith(photo_folder):
            return jsonify({'error': 'Invalid path'}), 403
        
        if os.path.exists(filepath):
            return send_file(filepath, mimetype='image/jpeg')
        else:
            return jsonify({'error': 'Photo not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 404

# ============ НОВЫЕ ОБРАБОТЧИКИ ДЛЯ РЕЖИМА "ТОЛЬКО СРОЧНЫЕ" ============

@app.route('/api/admin/tv/<int:tv_id>/urgent', methods=['PUT'])
def set_tv_urgent_mode(tv_id):
    """Включение/выключение режима 'только срочные' для конкретной панели"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        tv = TVPanel.query.get(tv_id)
        if not tv:
            return jsonify({'error': 'ТВ-панель не найдена'}), 404
        
        data = request.json
        urgent_only = data.get('urgent_only', False)
        
        tv.urgent_only = urgent_only
        
        # Если включаем режим "только срочные", сбрасываем emergency режим
        if urgent_only and tv.mode == 'emergency':
            tv.mode = 'normal'
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'urgent_only': tv.urgent_only,
            'message': 'Режим "Только срочные" включен' if urgent_only else 'Режим "Только срочные" выключен'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/tv/<int:tv_id>/mode', methods=['PUT'])
def set_tv_mode(tv_id):
    """Установка режима панели (normal, emergency, urgent_only)"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        tv = TVPanel.query.get(tv_id)
        if not tv:
            return jsonify({'error': 'ТВ-панель не найдена'}), 404
        
        data = request.json
        new_mode = data.get('mode', 'normal')
        
        # Поддерживаемые режимы: normal, emergency, urgent_only
        if new_mode not in ['normal', 'emergency', 'urgent_only']:
            return jsonify({'error': 'Неверный режим. Доступные: normal, emergency, urgent_only'}), 400
        
        tv.mode = new_mode
        
        # Если режим emergency, обновляем сообщение
        if new_mode == 'emergency' and data.get('emergency_message'):
            tv.emergency_message = data['emergency_message']
        
        # Если режим urgent_only, сбрасываем emergency
        if new_mode == 'urgent_only':
            tv.urgent_only = True
        elif new_mode == 'normal':
            tv.urgent_only = False
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'mode': tv.mode,
            'urgent_only': tv.urgent_only,
            'message': f'Режим изменен на {new_mode}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/tv/all/mode', methods=['PUT'])
def set_all_tv_mode():
    """Применение режима ко всем TV-панелям"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        data = request.json
        new_mode = data.get('mode', 'normal')
        
        if new_mode not in ['normal', 'emergency', 'urgent_only']:
            return jsonify({'error': 'Неверный режим. Доступные: normal, emergency, urgent_only'}), 400
        
        panels = TVPanel.query.all()
        for tv in panels:
            tv.mode = new_mode
            if new_mode == 'emergency' and data.get('emergency_message'):
                tv.emergency_message = data['emergency_message']
            elif new_mode == 'urgent_only':
                tv.urgent_only = True
            elif new_mode == 'normal':
                tv.urgent_only = False
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Режим изменен для {len(panels)} панелей'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==================== АВТОРИЗАЦИЯ ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Введите логин и пароль'}), 400
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not check_password(password, user.password_hash):
            return jsonify({'error': 'Неверный логин или пароль'}), 401
        
        session.clear()
        
        session['user_id'] = user.id
        session['user_role'] = user.role
        session['user_name'] = user.full_name
        session.permanent = True
        session.modified = True
        
        print(f"✅ Успешный вход: {username} (ID: {user.id}, роль: {user.role})")
        
        if user.role == 'admin':
            redirect_url = '/admin'
        elif user.role == 'parent':
            redirect_url = '/parent'
        elif user.role == 'tv':
            redirect_url = '/tv'
        else:
            redirect_url = '/'
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'fullName': user.full_name,
                'role': user.role,
                'class_name': user.class_name,
                'parent_id': user.parent_id
            },
            'redirect': redirect_url
        })
    except Exception as e:
        print(f"❌ Ошибка при входе: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Не авторизован'}), 401
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Пользователь не найден'}), 401
    return jsonify({
        'id': user.id,
        'username': user.username,
        'fullName': user.full_name,
        'role': user.role,
        'class_name': user.class_name,
        'parent_id': user.parent_id
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        return jsonify({
            'authenticated': True,
            'user_id': user_id,
            'role': user.role if user else None
        })
    return jsonify({'authenticated': False})

# ==================== ДРУГИЕ ЭНДПОИНТЫ ====================

@app.route('/api/grades', methods=['GET'])
def get_grades():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        student_id = request.args.get('student_id')
        if not student_id:
            return jsonify([])
        
        grades = Grade.query.filter_by(student_id=student_id).order_by(Grade.date.desc()).all()
        return jsonify([{
            'id': g.id,
            'grade': g.grade_value,
            'subject': g.subject,
            'date': g.date.isoformat() if g.date else None,
            'comment': g.comment
        } for g in grades])
    except Exception as e:
        return jsonify([])

@app.route('/api/homework', methods=['GET'])
def get_homework():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        homework = Homework.query.order_by(Homework.created_at.desc()).all()
        return jsonify([{
            'id': h.id,
            'class_name': h.class_name,
            'subject': h.subject,
            'task': h.task,
            'deadline': h.deadline.isoformat() if h.deadline else None,
            'created_at': h.created_at.isoformat() if h.created_at else None
        } for h in homework])
    except Exception as e:
        return jsonify([])

@app.route('/api/schedule/day', methods=['GET'])
def get_schedule_day():
    try:
        class_name = request.args.get('class')
        day = request.args.get('day')
        
        if not class_name or day is None:
            return jsonify([])
        
        schedules = Schedule.query.filter_by(
            class_name=class_name,
            day_of_week=int(day)
        ).order_by(Schedule.lesson_number).all()
        
        return jsonify([{
            'id': s.id,
            'subject': s.subject,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'room': s.room,
            'lesson_number': s.lesson_number
        } for s in schedules])
    except Exception as e:
        return jsonify([])

@app.route('/api/parent/children', methods=['GET'])
def get_parent_children():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = db.session.get(User, user_id)
        if user.role != 'parent':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        children = User.query.filter_by(parent_id=user_id, role='student').order_by(User.full_name).all()
        
        return jsonify([{
            'id': c.id,
            'fullName': c.full_name,
            'full_name': c.full_name,
            'class_name': c.class_name,
            'role': c.role
        } for c in children])
    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify([])

@app.route('/api/status', methods=['GET'])
def status():
    try:
        user_count = User.query.count()
        return jsonify({
            'status': 'online',
            'database': 'PostgreSQL',
            'user_count': user_count,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/test-announcements', methods=['GET'])
def test_announcements():
    try:
        from sqlalchemy import text
        result = db.session.execute(text("SELECT * FROM announcements LIMIT 5"))
        rows = [dict(row._mapping) for row in result]
        return jsonify({'success': True, 'data': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/announcements/classes', methods=['GET'])
def get_announcement_classes():
    try:
        classes = ['all', 'parents', 'teachers']
        return jsonify({'classes': classes})
    except Exception as e:
        return jsonify({'classes': ['all', 'parents', 'teachers']})

# Добавьте этот код перед if __name__ == '__main__':
# Автоматическая миграция базы данных
with app.app_context():
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        
        # Проверяем наличие таблиц
        if not inspector.has_table('tv_panels'):
            print("⚠️ Таблица tv_panels не найдена, создаем...")
            db.create_all()
        
        # Проверяем наличие колонки urgent_only
        columns = [col['name'] for col in inspector.get_columns('tv_panels')] if inspector.has_table('tv_panels') else []
        if 'urgent_only' not in columns:
            print("🔧 Добавление колонки urgent_only в таблицу tv_panels...")
            db.session.execute(text('ALTER TABLE tv_panels ADD COLUMN IF NOT EXISTS urgent_only BOOLEAN DEFAULT FALSE'))
            db.session.commit()
            print("✅ Колонка urgent_only добавлена")
        
        # Проверяем наличие колонки mode
        if 'mode' not in columns:
            print("🔧 Добавление колонки mode в таблицу tv_panels...")
            db.session.execute(text('ALTER TABLE tv_panels ADD COLUMN mode VARCHAR(20) DEFAULT \'normal\''))
            db.session.commit()
            print("✅ Колонка mode добавлена")
            
    except Exception as e:
        print(f"⚠️ Ошибка при миграции: {e}")
        
# Добавьте этот эндпоинт в ваш серверный код (app_complete.py) после эндпоинта логина

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.json
        print(f"📝 Регистрация нового пользователя: {data}")
        
        # Валидация
        if not data.get('full_name'):
            return jsonify({'error': 'Введите ФИО'}), 400
        if not data.get('username'):
            return jsonify({'error': 'Введите логин'}), 400
        if not data.get('password') or len(data.get('password')) < 6:
            return jsonify({'error': 'Пароль должен быть минимум 6 символов'}), 400
        
        # Проверка существования
        existing = User.query.filter_by(username=data['username']).first()
        if existing:
            return jsonify({'error': f'Пользователь с логином "{data["username"]}" уже существует'}), 400
        
        # Создание пользователя
        new_user = User(
            full_name=data['full_name'],
            username=data['username'],
            password_hash=hash_password(data['password']),
            role=data.get('role', 'student'),
            class_name=data.get('class_name') if data.get('role') == 'student' else None
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        print(f"✅ Пользователь {new_user.username} зарегистрирован (ID: {new_user.id})")
        
        return jsonify({
            'success': True,
            'message': 'Регистрация успешна!',
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'fullName': new_user.full_name,
                'role': new_user.role,
                'class_name': new_user.class_name
            }
        })
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка регистрации: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🏫 Школа 215 - Система управления")
    print("="*60)
    print(f"🐘 Подключено к PostgreSQL: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    print("🌐 Сервер: http://localhost:5000")
    print("="*60)
    print("\nНажмите Ctrl+C для остановки сервера\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)