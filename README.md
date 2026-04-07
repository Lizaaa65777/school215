## Установка и запуск

1. Клонируй репозиторий:
   ```bash
   git clone ...
   cd project
Установи зависимости:

bash
pip install -r requirements.txt
Настрой переменные окружения:

bash
cp .env.example .env
# отредактируй .env под свои нужды
Инициализируй базу данных:

bash
python setup_db.py
# или
php artisan migrate --seed
Запусти проект:

bash
python app.py
База данных: Используется SQLite, файл app.db создастся автоматически.