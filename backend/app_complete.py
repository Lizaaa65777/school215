from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import hashlib
import secrets
import os

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = 'school215-secret-key-2024'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
CORS(app, supports_credentials=True)

import os

# Для Render.com
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)


app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'postgresql://postgres:2708@localhost:5432/school215'
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

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author_name = db.Column(db.String(255))
    announcement_type = db.Column(db.String(50), default='general')
    target_class = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TVPanel(db.Model):
    __tablename__ = 'tv_panels'
    id = db.Column(db.Integer, primary_key=True)
    panel_name = db.Column(db.String(100))
    location = db.Column(db.String(200))
    # is_active - больше не используем, статус вычисляется по last_seen
    is_active = db.Column(db.Boolean, default=True)  # можно оставить для совместимости
    last_update = db.Column(db.DateTime, default=datetime.utcnow)
    mode = db.Column(db.String(20), default='normal')
    emergency_message = db.Column(db.Text, nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(100), unique=True)
    
    @property
    def is_online(self):
        """Возвращает True, если панель онлайн (была активна в последние 2 минуты)"""
        if not self.last_seen:
            return False
        return datetime.utcnow() - self.last_seen < timedelta(minutes=2)

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

with app.app_context():
    db.create_all()
    print("✅ База данных готова")
    
    #TVPanel.query.update({TVPanel.last_seen: datetime.utcnow() - timedelta(hours=1)})
    #db.session.commit()
    #print("🔄 Сброшен статус всех TV-панелей на 'оффлайн'")
    
    # Генерируем токены для существующих ТВ-панелей (если их нет)
    import secrets
    panels_without_token = TVPanel.query.filter(TVPanel.token.is_(None)).all()
    for panel in panels_without_token:
        panel.token = secrets.token_urlsafe(32)
        print(f"🔑 Сгенерирован токен для {panel.panel_name}")
    if panels_without_token:
        db.session.commit()
        print(f"✅ Обновлено {len(panels_without_token)} панелей")
    
    # Создание тестовых пользователей
    if User.query.count() == 0:
        print("Создание тестовых пользователей...")
        
        admin = User(username='admin', password_hash=hash_password('admin123'), full_name='Администратор Системы', role='admin')
        teacher = User(username='ivanova', password_hash=hash_password('teacher123'), full_name='Иванова Мария Сергеевна', role='teacher')
        student1 = User(username='ivanov_i', password_hash=hash_password('student123'), full_name='Иванов Иван', role='student', class_name='9А')
        student2 = User(username='petrova_m', password_hash=hash_password('student123'), full_name='Петрова Мария', role='student', class_name='9А')
        student3 = User(username='sidorov_a', password_hash=hash_password('student123'), full_name='Сидоров Алексей', role='student', class_name='9А')
        
        # Создаем родителя для Иванова Ивана
        parent = User(username='ivanova_e', password_hash=hash_password('parent123'), full_name='Иванова Елена Петровна', role='parent', parent_id=None)
        
        db.session.add_all([admin, teacher, student1, student2, student3, parent])
        db.session.commit()
        
        # Привязываем родителя к ученику
        student1.parent_id = parent.id
        db.session.commit()
        
        # Создаем оценки
        grades = [
            Grade(student_id=student1.id, teacher_id=teacher.id, subject='Алгебра', grade_value=5, work_type='Контрольная', topic='Квадратные уравнения'),
            Grade(student_id=student1.id, teacher_id=teacher.id, subject='Геометрия', grade_value=4, work_type='Самостоятельная', topic='Теорема Пифагора'),
            Grade(student_id=student2.id, teacher_id=teacher.id, subject='Алгебра', grade_value=5, work_type='Контрольная', topic='Квадратные уравнения'),
            Grade(student_id=student3.id, teacher_id=teacher.id, subject='Алгебра', grade_value=3, work_type='Домашняя работа', topic='Уравнения'),
        ]
        db.session.add_all(grades)
        db.session.commit()
        
        print("✅ Тестовые пользователи созданы")
    
    # Добавляем расписание
    if Schedule.query.filter_by(class_name='9А').count() == 0:
        print("📅 Добавляем расписание...")
        schedules_data = [
            {'class_name': '9А', 'day_of_week': 1, 'lesson_number': 1, 'start_time': '08:30', 'end_time': '09:15', 'subject': 'Алгебра', 'room': '215', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 1, 'lesson_number': 2, 'start_time': '09:25', 'end_time': '10:10', 'subject': 'Русский язык', 'room': '112', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 1, 'lesson_number': 3, 'start_time': '10:20', 'end_time': '11:05', 'subject': 'Физика', 'room': '315', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 2, 'lesson_number': 1, 'start_time': '08:30', 'end_time': '09:15', 'subject': 'Геометрия', 'room': '215', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 2, 'lesson_number': 2, 'start_time': '09:25', 'end_time': '10:10', 'subject': 'Алгебра', 'room': '215', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 3, 'lesson_number': 1, 'start_time': '08:30', 'end_time': '09:15', 'subject': 'Английский язык', 'room': '305', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 4, 'lesson_number': 1, 'start_time': '08:30', 'end_time': '09:15', 'subject': 'История', 'room': '210', 'teacher_id': 2},
            {'class_name': '9А', 'day_of_week': 5, 'lesson_number': 1, 'start_time': '08:30', 'end_time': '09:15', 'subject': 'Биология', 'room': '320', 'teacher_id': 2},
        ]
        for s_data in schedules_data:
            schedule = Schedule(**s_data)
            db.session.add(schedule)
        db.session.commit()
        print("✅ Расписание добавлено")
    
    # Добавляем TV панели
    if TVPanel.query.count() == 0:
        print("📺 Добавляем TV панели...")
        tv_panels = [
            TVPanel(panel_name='Холл 1 этаж', location='Главный холл', is_active=True),
            TVPanel(panel_name='Столовая', location='Столовая', is_active=True),
            TVPanel(panel_name='Холл 2 этаж', location='Возле кабинета 215', is_active=False),
        ]
        db.session.add_all(tv_panels)
        db.session.commit()
        print("✅ TV панели добавлены")

# ==================== СТРАНИЦЫ ====================

@app.route('/')
def index():
    return send_from_directory('../', 'index.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('../', 'ADMIN_PANEL.html')

@app.route('/parent')
def parent_page():
    return send_from_directory('../', 'PARENT_PANEL.html')

@app.route('/tv')
def tv_panel_page():
    """Страница ТВ-панели"""
    return send_from_directory('../', 'tv.html')

@app.route('/tv-login')
def tv_login_page():
    """Страница входа для ТВ-панели"""
    return send_from_directory('../', 'tv-login.html')

# ==================== АУТЕНТИФИКАЦИЯ ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify({'error': 'Неверный логин или пароль'}), 401
        
        session['user_id'] = user.id
        session['user_role'] = user.role
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'fullName': user.full_name,
                'role': user.role,
                'class_name': user.class_name,
                'parent_id': user.parent_id
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Не авторизован'}), 401
    user = User.query.get(user_id)
    return jsonify({
        'id': user.id,
        'username': user.username,
        'fullName': user.full_name,
        'role': user.role,
        'class_name': user.class_name,
        'parent_id': user.parent_id
    })

# ==================== ПОЛЬЗОВАТЕЛИ ====================

@app.route('/api/users', methods=['GET'])
def get_users():
    try:
        users = User.query.all()
        return jsonify([{
            'id': u.id,
            'username': u.username,
            'fullName': u.full_name,
            'role': u.role,
            'class_name': u.class_name,
            'parent_id': u.parent_id
        } for u in users])
    except Exception as e:
        print(f"Users error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== ОЦЕНКИ ====================

@app.route('/api/grades', methods=['GET'])
def get_grades():
    try:
        student_id = request.args.get('student_id')
        if student_id:
            grades = Grade.query.filter_by(student_id=student_id).order_by(Grade.date.desc()).all()
        else:
            grades = Grade.query.order_by(Grade.date.desc()).all()
        
        return jsonify([{
            'id': g.id,
            'student_id': g.student_id,
            'subject': g.subject,
            'grade': g.grade_value,
            'work_type': g.work_type,
            'topic': g.topic or '',
            'date': g.date.isoformat(),
            'comment': g.comment or ''
        } for g in grades])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ДОМАШНИЕ ЗАДАНИЯ ====================

@app.route('/api/homework', methods=['GET'])
def get_homework():
    try:
        class_name = request.args.get('class')
        if class_name:
            homeworks = Homework.query.filter_by(class_name=class_name).order_by(Homework.deadline).all()
        else:
            homeworks = Homework.query.order_by(Homework.deadline).all()
        
        return jsonify([{
            'id': h.id,
            'class_name': h.class_name,
            'subject': h.subject,
            'task': h.task,
            'deadline': h.deadline.isoformat() if h.deadline else None,
            'created_at': h.created_at.isoformat()
        } for h in homeworks])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== РАСПИСАНИЕ ====================

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    try:
        class_name = request.args.get('class')
        if class_name:
            schedules = Schedule.query.filter_by(class_name=class_name).order_by(Schedule.day_of_week, Schedule.lesson_number).all()
        else:
            schedules = Schedule.query.all()
        
        return jsonify([{
            'id': s.id,
            'class_name': s.class_name,
            'day_of_week': s.day_of_week,
            'lesson_number': s.lesson_number,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'subject': s.subject,
            'room': s.room
        } for s in schedules])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/schedule/day', methods=['GET'])
def get_schedule_by_day():
    try:
        class_name = request.args.get('class')
        day_of_week = request.args.get('day')
        
        if not class_name or not day_of_week:
            return jsonify({'error': 'Не указан класс или день'}), 400
        
        schedules = Schedule.query.filter_by(
            class_name=class_name,
            day_of_week=int(day_of_week)
        ).order_by(Schedule.lesson_number).all()
        
        return jsonify([{
            'id': s.id,
            'time': f"{s.start_time}-{s.end_time}",
            'subject': s.subject,
            'room': s.room
        } for s in schedules])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ОБЪЯВЛЕНИЯ ====================

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = User.query.get(user_id)
        
        query = Announcement.query
        if user.role == 'parent':
            query = query.filter(db.or_(Announcement.target_class == 'parents', Announcement.target_class.is_(None)))
        
        announcements = query.order_by(Announcement.created_at.desc()).all()
        
        return jsonify([{
            'id': a.id,
            'title': a.title,
            'content': a.content,
            'author_name': a.author_name,
            'announcement_type': a.announcement_type,
            'created_at': a.created_at.isoformat()
        } for a in announcements])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = User.query.get(user_id)
        if user.role not in ['admin']:
            return jsonify({'error': 'Недостаточно прав'}), 403
        
        data = request.json
        
        announcement = Announcement(
            title=data['title'],
            content=data['content'],
            author_id=user_id,
            author_name=user.full_name,
            announcement_type=data.get('announcement_type', 'general'),
            target_class=data.get('target_class')
        )
        
        db.session.add(announcement)
        db.session.commit()
        
        return jsonify({'success': True, 'announcement_id': announcement.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== TV ПАНЕЛИ ====================

@app.route('/api/tv-panels', methods=['GET'])
def get_tv_panels():
    try:
        panels = TVPanel.query.all()
        # Считаем панель онлайн, если last_seen был менее 2 минут назад
        now = datetime.utcnow()
        two_minutes_ago = now - timedelta(minutes=2)
        
        return jsonify([{
            'id': p.id,
            'panel_name': p.panel_name,
            'location': p.location,
            'is_active': p.last_seen > two_minutes_ago if p.last_seen else False,  # Онлайн только если недавно был контакт
            'last_update': p.last_update.isoformat() if p.last_update else None,
            'last_seen': p.last_seen.isoformat() if p.last_seen else None,
            'mode': p.mode or 'normal',
            'has_token': bool(p.token)
        } for p in panels])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/login', methods=['POST'])
def tv_login():
    """Авторизация ТВ-панели по логину/паролю"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        print(f"\n{'='*50}")
        print(f"📺 ПОПЫТКА ВХОДА В ТВ")
        print(f"   Логин: {username}")
        print(f"   Пароль: {password}")
        print(f"{'='*50}")
        
        # Ищем пользователя
        user = User.query.filter_by(username=username).first()
        
        if not user:
            print(f"❌ Пользователь '{username}' не найден в БД!")
            return jsonify({'error': f'Пользователь "{username}" не найден'}), 401
        
        print(f"✅ Пользователь найден:")
        print(f"   ID: {user.id}")
        print(f"   Username: {user.username}")
        print(f"   Full name: {user.full_name}")
        print(f"   Role: {user.role}")
        print(f"   Password hash: {user.password_hash[:30]}...")
        
        # Проверяем пароль
        input_hash = hash_password(password)
        print(f"   Хеш введенного пароля: {input_hash[:50]}...")
        print(f"   Хеш из БД: {user.password_hash[:30]}...")
        
        if input_hash != user.password_hash:
            print(f"❌ ПАРОЛЬ НЕВЕРНЫЙ!")
            print(f"   Ожидалось: {user.password_hash}")
            print(f"   Получено: {input_hash}")
            return jsonify({'error': 'Неверный пароль'}), 401
        
        print(f"✅ Пароль верный!")
        
        # Проверяем роль
        if user.role != 'tv':
            print(f"❌ Неверная роль: {user.role}, ожидается 'tv'")
            return jsonify({'error': f'Доступ запрещен. Роль "{user.role}" не имеет доступа к ТВ-панели'}), 401
        
        print(f"✅ Роль подходит: tv")
        
        # Ищем или создаем ТВ-панель
        tv_panel = TVPanel.query.filter_by(panel_name=user.full_name).first()
        
        if not tv_panel:
            print(f"📺 Создаем новую ТВ-панель: {user.full_name}")
            tv_panel = TVPanel(
                panel_name=user.full_name,
                location='Не указано',
                token=secrets.token_urlsafe(32),
                last_seen=datetime.utcnow() - timedelta(hours=1),
                mode='normal'
            )
            db.session.add(tv_panel)
        else:
            print(f"📺 Найдена существующая ТВ-панель: {tv_panel.panel_name}")
        
        # Обновляем токен
        tv_panel.token = secrets.token_urlsafe(32)
        tv_panel.last_seen = datetime.utcnow()
        db.session.commit()
        
        print(f"✅ Вход выполнен успешно!")
        print(f"   Токен: {tv_panel.token[:30]}...")
        print(f"{'='*50}\n")
        
        return jsonify({
            'success': True,
            'token': tv_panel.token,
            'panel_id': tv_panel.id,
            'panel_name': tv_panel.panel_name,
            'message': f'Добро пожаловать, {tv_panel.panel_name}!'
        })
        
    except Exception as e:
        print(f"❌ ОШИБКА: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/logout', methods=['POST'])
def tv_logout():
    """Выход из ТВ-панели"""
    try:
        token = request.headers.get('X-TV-Token')
        if token:
            tv_panel = TVPanel.query.filter_by(token=token).first()
            if tv_panel:
                # Отмечаем панель как оффлайн
                tv_panel.last_seen = datetime.utcnow() - timedelta(hours=1)
                db.session.commit()
        
        return jsonify({'success': True, 'message': 'Выход выполнен'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/data', methods=['GET'])
def tv_data():
    """Получение данных для ТВ-панели по токену"""
    try:
        token = request.headers.get('X-TV-Token')
        if not token:
            return jsonify({'error': 'Требуется токен авторизации'}), 401
        
        tv = TVPanel.query.filter_by(token=token).first()
        if not tv:
            return jsonify({'error': 'Неверный токен'}), 401
        
        # Обновляем время последнего контакта (онлайн статус)
        tv.last_seen = datetime.utcnow()
        db.session.commit()
        
        # Получаем объявления в зависимости от режима
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
            query = Announcement.query.order_by(Announcement.created_at.desc()).limit(8)
            for a in query:
                announcements.append({
                    'title': a.title,
                    'content': a.content,
                    'type': a.announcement_type,
                    'author': a.author_name,
                    'time': a.created_at.strftime('%H:%M'),
                    'target': a.target_class or 'Все классы'
                })
        
        # Расписание на сегодня
        today = datetime.now().weekday() + 1
        schedule_today = Schedule.query.filter_by(
            class_name='9А', 
            day_of_week=today
        ).order_by(Schedule.lesson_number).all()
        
        schedule_list = [{
            'time': f"{s.start_time}-{s.end_time}",
            'subject': s.subject,
            'room': s.room
        } for s in schedule_today]
        
        # Статистика (активные панели - те, у кого last_seen был менее 5 минут назад)
        total_panels = TVPanel.query.count()
        active_panels = TVPanel.query.filter(
            TVPanel.last_seen > datetime.utcnow() - timedelta(minutes=5)
        ).count()
        
        return jsonify({
            'mode': tv.mode,
            'panel_name': tv.panel_name,
            'announcements': announcements,
            'schedule': schedule_list,
            'current_time': datetime.now().strftime('%H:%M:%S'),
            'current_date': datetime.now().strftime('%d.%m.%Y'),
            'system_status': 'online',
            'panels_total': total_panels,
            'panels_active': active_panels,
            'next_update': 45
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/tv/<int:tv_id>/mode', methods=['PUT'])
def set_tv_mode(tv_id):
    """Установка режима ТВ-панели (только для админа)"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = User.query.get(user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Доступ запрещен. Требуются права администратора'}), 403
        
        tv = TVPanel.query.get(tv_id)
        if not tv:
            return jsonify({'error': 'ТВ-панель не найдена'}), 404
        
        data = request.json
        new_mode = data.get('mode', 'normal')
        
        if new_mode not in ['normal', 'emergency', 'night']:
            return jsonify({'error': 'Неверный режим. Доступны: normal, emergency, night'}), 400
        
        tv.mode = new_mode
        
        if new_mode == 'emergency' and data.get('emergency_message'):
            tv.emergency_message = data['emergency_message']
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Режим изменен на {new_mode}',
            'panel_id': tv.id,
            'mode': tv.mode
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/tv/all/mode', methods=['PUT'])
def set_all_tv_mode():
    """Установка режима для всех ТВ-панелей (только для админа)"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Не авторизован'}), 401
        
        user = User.query.get(user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Доступ запрещен'}), 403
        
        data = request.json
        new_mode = data.get('mode', 'normal')
        
        if new_mode not in ['normal', 'emergency', 'night']:
            return jsonify({'error': 'Неверный режим'}), 400
        
        panels = TVPanel.query.all()
        for tv in panels:
            tv.mode = new_mode
            if new_mode == 'emergency' and data.get('emergency_message'):
                tv.emergency_message = data['emergency_message']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Режим изменен на {new_mode} для {len(panels)} панелей'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== СТАТУС ====================

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

# ВРЕМЕННЫЙ ТЕСТ ХЕШЕЙ
with app.app_context():
    print("\n" + "="*60)
    print("ТЕСТ ХЕШЕЙ ПАРОЛЕЙ")
    print("="*60)
    
    test_password = "tv123"
    correct_hash = hash_password(test_password)
    print(f"Хеш для '{test_password}': {correct_hash}")
    
    tv_users = User.query.filter_by(role='tv').all()
    if tv_users:
        for user in tv_users:
            print(f"\nПользователь: {user.username}")
            print(f"  Хеш в БД: {user.password_hash}")
            print(f"  Длина хеша: {len(user.password_hash)}")
            print(f"  Совпадает с правильным: {user.password_hash == correct_hash}")
            if user.password_hash != correct_hash:
                print(f"  ⚠️ ХЕШ НЕ СОВПАДАЕТ! Обновляем...")
                user.password_hash = correct_hash
        db.session.commit()
        print("\n✅ Хеши обновлены!")
    else:
        print("\n❌ Нет ТВ-пользователей в БД!")
    
    print("="*60 + "\n")

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🏫 Школа 215 - Система управления")
    print("="*60)
    print(f"🐘 Подключено к PostgreSQL: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    print("🌐 Сервер: http://localhost:5000")
    print("📋 Тестовые аккаунты:")
    print("   👑 Админ: admin / admin123")
    print("   👨‍🏫 Учитель: ivanova / teacher123")
    print("   👨‍🎓 Ученик: ivanov_i / student123")
    print("   👪 Родитель: ivanova_e / parent123")
    print("="*60)
    print("\nНажмите Ctrl+C для остановки сервера\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
