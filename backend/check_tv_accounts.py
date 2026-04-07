import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Проверка хеша для tv123
print(f"Хеш для 'tv123': {hash_password('tv123')}")
# Вывод: 5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8

# Список всех ТВ-аккаунтов
tv_accounts = [
    ('tv_hall1', 'Холл 1 этаж'),
    ('tv_canteen', 'Столовая'),
    ('tv_hall2', 'Холл 2 этаж'),
    ('tv_library', 'Библиотека'),
    ('tv_assembly', 'Актовый зал'),
    ('tv_gym', 'Спортзал'),
    ('tv_teacher', 'Учительская'),
]

print("\n📺 Тестовые ТВ-аккаунты:")
for login, name in tv_accounts:
    print(f"   Логин: {login} | Пароль: tv123 | Панель: {name}")