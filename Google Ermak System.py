import os
import sys
import time
import threading
import json
import smtplib
import pickle
import io
import sqlite3
import requests
import urllib3
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import telebot
from telebot import types
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========== КОНСТАНТЫ ==========
FOLDER_NAME = "Google Ermak System"
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "client_secrets.json"
CONFIG_FILE = "config.json"
CHATS_DB_FILE = "chats.db"
EMAILS_FILE = "emails.json"
SETTINGS_FILE = "settings.json"
AUTH_USERS_FILE = "auth_users.json"

# Инициализация бота (будет загружен из конфига)
bot = None
BOT_NAME = "Google Ermak System⚡"

# Глобальные переменные
GOOGLE_DRIVE_FOLDER_ID = None
BOT_TOKEN = None
PASSWORD_ADMIN = None
PASSWORD_PLATON = None
OPENROUTER_KEY = None
EMAIL_SENDER = None
EMAIL_PASSWORD = None

# Временные данные
selected_chats = {}
user_waiting_for_input = {}  # Пользователи, ожидающие ввода (не для ИИ)

# Единственная модель
AI_MODEL = "allenai/molmo-2-8b:free"

# ========== ЛОГГИРОВАНИЕ ==========
def log_event(event_type, user_id, details=""):
    """Логирует события в консоль"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f"User {user_id}"
    
    try:
        if bot:
            user = bot.get_chat(user_id)
            user_info = f"{user.first_name or 'User'} {user.last_name or ''} (@{user.username or 'no_username'})"
    except:
        pass
    
    log_message = f"[{timestamp}] [{event_type}] {user_info}"
    if details:
        log_message += f" - {details}"
    
    print(log_message)

# ========== GOOGLE DRIVE ФУНКЦИИ ==========
def get_drive_service():
    """Создает сервис для работы с Google Drive"""
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
            print("✅ Токен Google Drive загружен")
        except Exception as e:
            print(f"❌ Ошибка загрузки токена: {e}")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Обновляю токен Google Drive...")
                creds.refresh(Request())
                print("✅ Токен обновлен!")
            except Exception as e:
                print(f"⚠️ Ошибка обновления токена: {e}")
                creds = None
        
        if not creds:
            try:
                print("🔑 Запрашиваю авторизацию Google Drive...")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True)
                print("✅ Авторизация успешна!")
            except Exception as e:
                print(f"❌ Ошибка авторизации: {e}")
                return None
            
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
                print("✅ Токен сохранен")
    
    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Ошибка создания сервиса: {e}")
        return None

def get_or_create_folder(service):
    """Находит или создает папку в Google Drive"""
    global GOOGLE_DRIVE_FOLDER_ID
    
    try:
        # Ищем папку
        query = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        if folders:
            GOOGLE_DRIVE_FOLDER_ID = folders[0]['id']
            print(f"✅ Папка найдена: {GOOGLE_DRIVE_FOLDER_ID}")
            return GOOGLE_DRIVE_FOLDER_ID
        else:
            # Создаем папку
            folder_metadata = {
                'name': FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            GOOGLE_DRIVE_FOLDER_ID = folder.get('id')
            print(f"✅ Папка создана: {GOOGLE_DRIVE_FOLDER_ID}")
            return GOOGLE_DRIVE_FOLDER_ID
    except Exception as e:
        print(f"❌ Ошибка поиска/создания папки: {e}")
        return None

def save_file_to_drive(service, file_name, content, mime_type='application/json'):
    """Сохраняет файл в Google Drive"""
    try:
        # Ищем файл
        query = f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            # Обновляем файл
            file_id = files[0]['id']
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype=mime_type)
            service.files().update(fileId=file_id, media_body=media).execute()
            return file_id
        else:
            # Создаем файл
            file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
    except Exception as e:
        print(f"⚠️ Ошибка сохранения файла {file_name}: {e}")
        return None

def save_binary_file_to_drive(service, file_name, binary_content, mime_type='application/octet-stream'):
    """Сохраняет бинарный файл в Google Drive"""
    try:
        # Ищем файл
        query = f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            # Обновляем файл
            file_id = files[0]['id']
            media = MediaIoBaseUpload(io.BytesIO(binary_content), mimetype=mime_type)
            service.files().update(fileId=file_id, media_body=media).execute()
            return file_id
        else:
            # Создаем файл
            file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
            media = MediaIoBaseUpload(io.BytesIO(binary_content), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
    except Exception as e:
        print(f"⚠️ Ошибка сохранения бинарного файла {file_name}: {e}")
        return None

def load_file_from_drive(service, file_name):
    """Загружает файл из Google Drive"""
    try:
        query = f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            file_id = files[0]['id']
            request = service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            return file_content.getvalue().decode('utf-8')
        return None
    except Exception as e:
        print(f"⚠️ Ошибка загрузки файла {file_name}: {e}")
        return None

def load_binary_file_from_drive(service, file_name):
    """Загружает бинарный файл из Google Drive"""
    try:
        query = f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            file_id = files[0]['id']
            request = service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            return file_content.getvalue()
        return None
    except Exception as e:
        print(f"⚠️ Ошибка загрузки бинарного файла {file_name}: {e}")
        return None

# ========== РАБОТА С ФАЙЛАМИ В GOOGLE DRIVE ==========
def load_json_file(filename, default_data):
    """Загружает JSON файл из Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return default_data
    
    content = load_file_from_drive(service, filename)
    if content:
        try:
            return json.loads(content)
        except:
            return default_data
    else:
        # Сохраняем файл с данными по умолчанию
        save_json_file(filename, default_data)
        return default_data

def save_json_file(filename, data):
    """Сохраняет JSON файл в Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return False
    
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        save_file_to_drive(service, filename, content)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения файла {filename}: {e}")
        return False

def load_database():
    """Загружает базу данных из Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return None
    
    db_content = load_binary_file_from_drive(service, CHATS_DB_FILE)
    return db_content

def save_database(db_content):
    """Сохраняет базу данных в Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return False
    
    try:
        save_binary_file_to_drive(service, CHATS_DB_FILE, db_content, 'application/x-sqlite3')
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения базы данных: {e}")
        return False

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========
def init_database():
    """Инициализирует базу данных"""
    try:
        # Загружаем базу из Google Drive
        db_content = load_database()
        
        if db_content and db_content.startswith(b'SQLite format 3\x00'):
            print("✅ Обнаружена SQLite база данных")
            
            # Сохраняем во временный файл
            temp_file = "temp_chats.db"
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            # Подключаемся к базе данных
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
            # Получаем список таблиц
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"📊 Найдено таблиц: {len(tables)}")
            
            if 'user_chats' in tables:
                print("✅ Использую таблицу user_chats")
                
                # Получаем данные из user_chats
                cursor.execute("SELECT user_id, chat_id, chat_title, chat_username FROM user_chats")
                chats_data = cursor.fetchall()
                
                print(f"📊 Найдено {len(chats_data)} чатов в базе")
                
                # Создаем новую базу данных в памяти с правильной структурой
                new_conn = sqlite3.connect(':memory:')
                new_cursor = new_conn.cursor()
                
                # Создаем таблицу chats
                new_cursor.execute('''
                    CREATE TABLE chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        chat_title TEXT NOT NULL,
                        chat_username TEXT,
                        chat_type TEXT,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Переносим данные из user_chats в chats
                for user_id, chat_id, chat_title, chat_username in chats_data:
                    new_cursor.execute('''
                        INSERT INTO chats (user_id, chat_id, chat_title, chat_username)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, chat_id, chat_title, chat_username))
                
                new_conn.commit()
                conn.close()
                new_conn.close()
                
                # Сохраняем исправленную базу данных
                new_conn = sqlite3.connect(':memory:')
                new_cursor = new_conn.cursor()
                new_cursor.executescript('''
                    CREATE TABLE chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        chat_title TEXT NOT NULL,
                        chat_username TEXT,
                        chat_type TEXT,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                
                for user_id, chat_id, chat_title, chat_username in chats_data:
                    new_cursor.execute('''
                        INSERT INTO chats (user_id, chat_id, chat_title, chat_username)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, chat_id, chat_title, chat_username))
                
                new_conn.commit()
                
                # Экспортируем новую базу
                backup_conn = sqlite3.connect('new_chats.db')
                new_conn.backup(backup_conn)
                backup_conn.close()
                
                with open('new_chats.db', 'rb') as f:
                    new_db_content = f.read()
                
                # Сохраняем исправленную базу в Google Drive
                save_database(new_db_content)
                os.remove('new_chats.db')
                os.remove(temp_file)
                
                print("✅ База данных исправлена и сохранена")
                return True
                
        else:
            print("❌ База данных не найдена или повреждена")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка работы с базой данных: {e}")
        return False

def get_user_chats(user_id):
    """Получает чаты пользователя"""
    try:
        # Загружаем базу из Google Drive
        db_content = load_database()
        
        if db_content and db_content.startswith(b'SQLite format 3\x00'):
            temp_file = "temp_read.db"
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
            # Проверяем структуру таблицы
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            if 'chats' in tables:
                cursor.execute(
                    "SELECT chat_id, chat_title, chat_username FROM chats WHERE user_id = ? ORDER BY last_updated DESC",
                    (user_id,)
                )
                result = cursor.fetchall()
            elif 'user_chats' in tables:
                cursor.execute(
                    "SELECT chat_id, chat_title, chat_username FROM user_chats WHERE user_id = ?",
                    (user_id,)
                )
                result = cursor.fetchall()
            else:
                result = []
            
            conn.close()
            os.remove(temp_file)
            return result
        else:
            return []
            
    except Exception as e:
        print(f"❌ Ошибка получения чатов: {e}")
        return []

def save_user_chat(user_id, chat_id, chat_title, chat_username=None, chat_type=None):
    """Сохраняет информацию о чате"""
    try:
        # Загружаем текущую базу данных
        db_content = load_database()
        
        if not db_content or not db_content.startswith(b'SQLite format 3\x00'):
            # Создаем новую базу данных
            conn = sqlite3.connect(':memory:')
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    chat_title TEXT NOT NULL,
                    chat_username TEXT,
                    chat_type TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        else:
            # Загружаем существующую базу
            temp_file = "temp_save.db"
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
            # Проверяем и создаем таблицу chats если её нет
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chats'")
            if not cursor.fetchone():
                cursor.execute('''
                    CREATE TABLE chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        chat_title TEXT NOT NULL,
                        chat_username TEXT,
                        chat_type TEXT,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
        
        # Проверяем, существует ли уже чат
        cursor.execute(
            "SELECT id FROM chats WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute(
                "UPDATE chats SET chat_title = ?, chat_username = ?, chat_type = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                (chat_title, chat_username, chat_type, existing[0])
            )
        else:
            cursor.execute(
                "INSERT INTO chats (user_id, chat_id, chat_title, chat_username, chat_type) VALUES (?, ?, ?, ?, ?)",
                (user_id, chat_id, chat_title, chat_username, chat_type)
            )
        
        conn.commit()
        
        # Экспортируем базу данных
        backup_conn = sqlite3.connect('final_chats.db')
        conn.backup(backup_conn)
        backup_conn.close()
        
        with open('final_chats.db', 'rb') as f:
            new_db_content = f.read()
        
        # Сохраняем в Google Drive
        save_database(new_db_content)
        
        # Очищаем временные файлы
        conn.close()
        if os.path.exists('final_chats.db'):
            os.remove('final_chats.db')
        if os.path.exists('temp_save.db'):
            os.remove('temp_save.db')
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка сохранения чата: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def get_user_emails(user_id):
    """Получает email пользователя"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    # Гарантируем правильную структуру
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    
    user_emails = [email["email"] for email in emails_data["emails"] if email["user_id"] == user_id]
    return user_emails

def get_all_emails():
    """Получает все email"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    # Гарантируем правильную структуру
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    
    emails = list(set([email["email"] for email in emails_data["emails"]]))
    return emails

def save_user_email(user_id, email):
    """Сохраняет email пользователя"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    # Гарантируем правильную структуру
    if not isinstance(emails_data, dict):
        emails_data = {"emails": []}
    if "emails" not in emails_data:
        emails_data["emails"] = []
    
    # Проверяем, существует ли уже email для этого пользователя
    for item in emails_data["emails"]:
        if item["user_id"] == user_id and item["email"] == email:
            return False
    
    # Добавляем новый email
    emails_data["emails"].append({
        "user_id": user_id,
        "email": email,
        "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    save_json_file(EMAILS_FILE, emails_data)
    log_event("EMAIL_ADDED", user_id, f"Email: {email}")
    return True

def delete_email_by_admin(email):
    """Удаляет email"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    # Гарантируем правильную структуру
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        return False
    
    # Фильтруем email
    original_count = len(emails_data["emails"])
    emails_data["emails"] = [item for item in emails_data["emails"] if item["email"] != email]
    
    if len(emails_data["emails"]) < original_count:
        save_json_file(EMAILS_FILE, emails_data)
        return True
    
    return False

def check_user_access(user_id):
    """Проверяет доступ пользователя"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    # Гарантируем правильную структуру
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    for user in auth_data["users"]:
        if user["user_id"] == user_id:
            return user["user_type"]
    
    return None

def save_auth_user(user_type, user_id):
    """Сохраняет авторизованного пользователя"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    # Гарантируем правильную структуру
    if not isinstance(auth_data, dict):
        auth_data = {"users": []}
    if "users" not in auth_data:
        auth_data["users"] = []
    
    # Проверяем, существует ли уже пользователь
    user_exists = False
    for user in auth_data["users"]:
        if user["user_id"] == user_id and user["user_type"] == user_type:
            user_exists = True
            break
    
    if not user_exists:
        auth_data["users"].append({
            "user_id": user_id,
            "user_type": user_type,
            "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        save_json_file(AUTH_USERS_FILE, auth_data)
        log_event("AUTH_ADDED", user_id, f"Type: {user_type}")
    
    return True

def get_all_users():
    """Получает всех пользователей"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    # Гарантируем правильную структуру
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    all_users = set()
    
    # Добавляем пользователей с email
    for email_item in emails_data["emails"]:
        all_users.add(email_item["user_id"])
    
    # Добавляем авторизованных пользователей
    for auth_user in auth_data["users"]:
        all_users.add(auth_user["user_id"])
    
    return list(all_users)

def get_platon_users():
    """Получает всех пользователей Платон"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    # Гарантируем правильную структуру
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    platon_users = [user["user_id"] for user in auth_data["users"] if user["user_type"] == "platon"]
    return platon_users

def save_setting(key, value):
    """Сохраняет настройку"""
    settings_data = load_json_file(SETTINGS_FILE, {"settings": {}})
    
    # Гарантируем правильную структуру
    if not isinstance(settings_data, dict):
        settings_data = {"settings": {}}
    if "settings" not in settings_data:
        settings_data["settings"] = {}
    
    settings_data["settings"][key] = value
    save_json_file(SETTINGS_FILE, settings_data)
    return True

def load_setting(key, default=None):
    """Загружает настройку"""
    settings_data = load_json_file(SETTINGS_FILE, {"settings": {}})
    
    # Гарантируем правильную структуру
    if not isinstance(settings_data, dict) or "settings" not in settings_data:
        return default
    
    if key in settings_data["settings"]:
        return settings_data["settings"][key]
    
    return default

# ========== OPENROUTER API ==========
def ask_openrouter(user_message):
    """Запрос к OpenRouter с обработкой ошибок"""
    if not OPENROUTER_KEY:
        return "❌ Ключ OpenRouter не настроен"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Google Ermak System"
    }
    
    data = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": "Ты полезный AI-ассистент. Отвечай на русском языке кратко и по делу."},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 1000,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                return "❌ Не удалось получить ответ от ИИ."
        
        elif response.status_code == 429:
            return "❌ Лимит бесплатных запросов исчерпан. Попробуйте позже."
        
        elif response.status_code == 401:
            return "❌ Неверный ключ OpenRouter"
        
        else:
            return f"❌ Ошибка ИИ (код {response.status_code})"
            
    except requests.exceptions.Timeout:
        return "⏱️ Таймаут соединения. Попробуйте позже."
    
    except requests.exceptions.ConnectionError:
        return "🔌 Ошибка соединения. Проверьте интернет."
    
    except Exception as e:
        return f"⚠️ Ошибка: {str(e)[:100]}"

# ========== ИИ ФУНКЦИОНАЛ ==========
def handle_ai_request(user_id, user_message):
    """Обрабатывает запрос к ИИ"""
    log_event("AI_REQUEST", user_id)
    
    bot.send_chat_action(user_id, 'typing')
    response = ask_openrouter(user_message)
    
    log_event("AI_RESPONSE", user_id, f"Response length: {len(response)}")
    return response

# ========== EMAIL ФУНКЦИИ ==========
def send_email(to_email, subject, message_text):
    """Отправляет email"""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Данные для отправки email не настроены")
        return False
        
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message_text, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email отправлен на {to_email}")
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки email: {e}")
        return False

# ========== ЗАГРУЗКА КОНФИГУРАЦИИ ==========
def load_config_from_drive():
    """Загружает конфигурацию из Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        print("❌ Нет подключения к Google Drive")
        return False
    
    content = load_file_from_drive(service, CONFIG_FILE)
    if not content:
        print(f"❌ Файл {CONFIG_FILE} не найден в Google Drive")
        
        # Создаем пример конфигурации
        example_config = {
            "BOT_TOKEN": "ВАШ_ТОКЕН_ТЕЛЕГРАМ_БОТА",
            "PASSWORD_ADMIN": "админ_пароль",
            "PASSWORD_PLATON": "платон_пароль",
            "OPENROUTER_KEY": "sk-or-v1-ваш_ключ_openrouter",
            "EMAIL_SENDER": "ваш_email@gmail.com",
            "EMAIL_PASSWORD": "ваш_пароль_приложения"
        }
        
        save_file_to_drive(service, CONFIG_FILE, json.dumps(example_config, indent=2, ensure_ascii=False))
        print(f"✅ Файл {CONFIG_FILE} создан в Google Drive")
        print("⚠️  Заполните его вашими данными!")
        return False
    
    try:
        config = json.loads(content)
        
        global BOT_TOKEN, PASSWORD_ADMIN, PASSWORD_PLATON, OPENROUTER_KEY, EMAIL_SENDER, EMAIL_PASSWORD
        
        BOT_TOKEN = config.get("BOT_TOKEN")
        PASSWORD_ADMIN = config.get("PASSWORD_ADMIN")
        PASSWORD_PLATON = config.get("PASSWORD_PLATON")
        OPENROUTER_KEY = config.get("OPENROUTER_KEY")
        EMAIL_SENDER = config.get("EMAIL_SENDER")
        EMAIL_PASSWORD = config.get("EMAIL_PASSWORD")
        
        if not all([BOT_TOKEN, PASSWORD_ADMIN, PASSWORD_PLATON]):
            print("❌ Не все обязательные настройки заполнены в config.json")
            return False
        
        # Инициализируем бота
        global bot
        bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML', threaded=True)
        
        print("✅ Конфигурация загружена из Google Drive")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка загрузки конфигурации: {e}")
        return False

# ========== ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ ==========
def initialize_system():
    """Инициализирует всю систему"""
    print("=" * 60)
    print("🔗 Инициализация Google Drive...")
    
    service = get_drive_service()
    if not service:
        print("❌ Не удалось подключиться к Google Drive")
        return False
    
    # Получаем или создаем папку
    global GOOGLE_DRIVE_FOLDER_ID
    GOOGLE_DRIVE_FOLDER_ID = get_or_create_folder(service)
    if not GOOGLE_DRIVE_FOLDER_ID:
        print("❌ Не удалось создать папку")
        return False
    
    print(f"✅ Папка: https://drive.google.com/drive/folders/{GOOGLE_DRIVE_FOLDER_ID}")
    
    # Загружаем конфигурацию
    if not load_config_from_drive():
        print("❌ Не удалось загрузить конфигурацию")
        return False
    
    # Инициализируем базу данных
    print("🔗 Инициализация базы данных...")
    if not init_database():
        print("⚠️  База данных не найдена, будет создана при необходимости")
    
    print("✅ Система инициализирована")
    return True

# ========== ОБРАБОТЧИКИ КОМАНД ==========
def setup_bot_handlers():
    """Настраивает обработчики бота"""
    
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        """Обработчик команды /start"""
        user_id = message.from_user.id
        log_event("START", user_id)
        
        # Проверяем авторизацию для отображения правильного меню
        access_level = check_user_access(user_id)
        
        if access_level == 'admin':
            show_admin_menu(message)
        elif access_level == 'platon':
            show_platon_menu(message)
        else:
            show_guest_menu(message)
    
    @bot.message_handler(func=lambda message: message.text == "🔐 Войти в систему")
    def auth_handler(message):
        """Запрос пароля"""
        user_id = message.from_user.id
        log_event("AUTH_REQUEST", user_id)
        
        user_waiting_for_input[user_id] = 'password'
        bot.send_message(message.chat.id, "<b>🔐 Введите пароль для доступа к системе:</b>")
    
    @bot.message_handler(func=lambda message: message.text == "📧 Добавить email")
    def add_email_handler(message):
        """Добавление email"""
        user_id = message.from_user.id
        log_event("EMAIL_ADD_REQUEST", user_id)
        
        user_waiting_for_input[user_id] = 'email'
        bot.send_message(message.chat.id,
                        "<b>📧 Введите ваш email адрес:</b>\n\n"
                        "Сообщения будут приходить от ermakartekovec@gmail.com\n"
                        "<i>Внимание: сообщения могут быть в папке спам.</i>")
    
    @bot.message_handler(func=lambda message: message.text == "🤖 ИИ-помощник")
    def ai_assistant_handler(message):
        """ИИ-помощник"""
        user_id = message.from_user.id
        log_event("AI_MENU", user_id)
        
        user_waiting_for_input[user_id] = 'ai'
        bot.send_message(message.chat.id,
                        "<b>🤖 ИИ-помощник активирован!</b>\n\n"
                        "Задайте любой вопрос, и я постараюсь помочь.\n\n"
                        "💡 <b>Безлимитное использование для всех</b>\n"
                        "<i>⚠️ Используется бесплатная модель с ограничениями.</i>")
    
    @bot.message_handler(func=lambda message: message.text == "📤 Отправить сообщение")
    def send_message_handler(message):
        """Отправка сообщения в ТЕЛЕГРАМ чат/канал"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        chats = get_user_chats(user_id)
        
        if not chats:
            bot.send_message(message.chat.id, 
                            "<b>❌ Нет доступных чатов/каналов.</b>\n"
                            "Добавьте бота в чат/канал как администратора и перешлите сообщение из чата.")
            return
        
        markup = types.InlineKeyboardMarkup()
        
        for chat_id, title, username in chats:
            button_text = f"{title}"
            if username:
                button_text += f" (@{username})"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"select_chat_{chat_id}"))
        
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_send"))
        
        bot.send_message(message.chat.id, 
                        "<b>📤 Выберите чат/канал для отправки сообщения:</b>\n\n"
                        "<b>Поддерживаемые типы контента:</b>\n"
                        "📝 Текст, 🖼️ Фото, 🎬 Видео, 📄 Документы\n"
                        "🎵 Аудио, 🎤 Голосовые, 😊 Стикеры",
                        reply_markup=markup)
    
    @bot.message_handler(func=lambda message: message.text == "📋 Мои чаты и каналы")
    def show_user_chats_handler(message):
        """Показывает чаты пользователя"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        chats = get_user_chats(user_id)
        
        if not chats:
            bot.send_message(message.chat.id, 
                            "<b>📭 Бот не найден в чатах/каналах как администратор.</b>\n\n"
                            "<b>Чтобы добавить бота:</b>\n"
                            "1. Добавьте бота в чат/канал\n"
                            "2. Назначьте права администратора\n"
                            "3. Перешлите сообщение из чата этому боту")
            return
        
        response = "<b>📋 Ваши чаты и каналы:</b>\n\n"
        
        for i, (chat_id, title, username) in enumerate(chats, 1):
            chat_info = f"{i}. <b>{title}</b>\n"
            chat_info += f"   🆔: <code>{chat_id}</code>\n"
            if username:
                chat_info += f"   👤: @{username}\n"
            chat_info += "\n"
            response += chat_info
        
        response += "💡 <b>Для отправки сообщения используйте кнопку '📤 Отправить сообщение'</b>"
        
        bot.send_message(message.chat.id, response)
    
    @bot.message_handler(func=lambda message: message.text == "👥 Управление email")
    def admin_email_management(message):
        """Управление email"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            types.InlineKeyboardButton("📋 Все email", callback_data="admin_all_emails"),
            types.InlineKeyboardButton("➕ Добавить email", callback_data="admin_add_email"),
            types.InlineKeyboardButton("🗑️ Удалить email", callback_data="admin_delete_email"),
            types.InlineKeyboardButton("📊 Статистика", callback_data="admin_email_stats"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_email_back")
        ]
        markup.add(*buttons)
        
        bot.send_message(message.chat.id,
                        "<b>👥 Управление email адресами</b>\n\n"
                        "Вы можете просматривать, добавлять и удалять email адреса всех пользователей.",
                        reply_markup=markup)
    
    @bot.message_handler(func=lambda message: message.text == "Платон🙌")
    def platon_admin_handler(message):
        """Отправка сообщения Платону"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        platon_ids = get_platon_users()
        
        if not platon_ids:
            bot.send_message(message.chat.id, "<b>❌ Пользователь Платон ещё не авторизовался.</b>")
            return
        
        user_waiting_for_input[user_id] = 'platon_message'
        bot.send_message(message.chat.id,
                        "<b>✍️ Введите сообщение для Платона:</b>")
    
    @bot.message_handler(func=lambda message: message.text == "📢 Рассылка пользователям")
    def broadcast_to_users_handler(message):
        """Рассылка пользователям (ТЕЛЕГРАМ)"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        users_count = len(get_all_users())
        
        if users_count == 0:
            bot.send_message(message.chat.id, 
                            "<b>📭 Нет пользователей для рассылки.</b>\n\n"
                            "Пользователи появятся после авторизации или добавления email.")
            return
        
        user_waiting_for_input[user_id] = 'broadcast_users'
        bot.send_message(message.chat.id,
                        f"<b>📢 Рассылка всем пользователям бота (Telegram)</b>\n\n"
                        f"Найдено {users_count} пользователей.\n\n"
                        f"Введите сообщение для рассылки:")
    
    @bot.message_handler(func=lambda message: message.text == "📧 Массовая рассылка")
    def email_broadcast_handler(message):
        """Массовая EMAIL рассылка"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        emails = get_all_emails()
        
        if not emails:
            bot.send_message(message.chat.id, 
                            "<b>📭 Нет сохранённых email адресов для рассылки.</b>\n\n"
                            "Пользователи смогут оставить свои email через кнопку '📧 Добавить email'.")
            return
        
        user_waiting_for_input[user_id] = 'broadcast_email'
        bot.send_message(message.chat.id,
                        f"<b>📧 Готовлю массовую EMAIL рассылку</b>\n\n"
                        f"Найдено {len(emails)} email адресов.\n\n"
                        f"Введите сообщение для рассылки:")
    
    @bot.message_handler(func=lambda message: message.text == "📧 Мои email")
    def show_my_emails_handler(message):
        """Показывает email пользователя"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if not access_level:
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Требуется авторизация.</b>")
            return
        
        log_event("EMAILS_VIEW", user_id)
        emails = get_user_emails(user_id)
        
        if emails:
            response = "<b>📧 Ваши email адреса:</b>\n\n"
            for i, email in enumerate(emails, 1):
                response += f"{i}. {email}\n"
            bot.send_message(message.chat.id, response)
        else:
            bot.send_message(message.chat.id,
                            "<b>📭 У вас нет сохранённых email адресов.</b>\n\n"
                            "Добавьте email для получения уведомлений.")
    
    @bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
    def settings_handler(message):
        """Настройки бота"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        channel_auto_reply = load_setting("channel_auto_reply", "false") == "true"
        channel_id = load_setting("channel_id")
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        auto_reply_status = "✅ Включен" if channel_auto_reply else "❌ Выключен"
        markup.add(types.InlineKeyboardButton(
            f"🤖 Автоответ в канале: {auto_reply_status}",
            callback_data="toggle_auto_reply"
        ))
        
        channel_text = f"📢 Канал: настроен" if channel_id else "📢 Канал: не настроен"
        markup.add(types.InlineKeyboardButton(channel_text, callback_data="set_channel"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings_back"))
        
        bot.send_message(message.chat.id,
                        "<b>⚙️ Настройки бота</b>\n\n"
                        "Здесь вы можете настроить автоматический ответ в канале.",
                        reply_markup=markup)

    # ========== CALLBACK ОБРАБОТЧИКИ ==========
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback_query(call):
        """Обработчик callback запросов"""
        user_id = call.from_user.id
        
        if call.data.startswith("select_chat_"):
            chat_id = int(call.data.split("_")[2])
            selected_chats[user_id] = chat_id
            
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, 
                            "<b>✅ Чат выбран. Теперь отправьте сообщение любого типа:</b>\n\n"
                            "📝 Текст, 🖼️ Фото, 🎬 Видео, 📄 Документы\n"
                            "🎵 Аудио, 🎤 Голосовые, 😊 Стикеры")
        
        elif call.data == "cancel_send":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "<b>❌ Отправка отменена</b>")
            show_admin_menu(call.message)
        
        elif call.data == "admin_all_emails":
            emails = get_all_emails()
            
            if emails:
                response = "<b>📋 Все email адреса:</b>\n\n"
                for i, email in enumerate(emails, 1):
                    response += f"{i}. {email}\n"
                bot.edit_message_text(response, call.message.chat.id, call.message.message_id)
            else:
                bot.edit_message_text("<b>📭 Нет сохранённых email адресов.</b>", 
                                     call.message.chat.id, call.message.message_id)
        
        elif call.data == "admin_add_email":
            user_waiting_for_input[user_id] = 'admin_add_email'
            bot.edit_message_text("<b>➕ Добавить email</b>\n\nВведите email адрес для добавления:", 
                                 call.message.chat.id, call.message.message_id)
        
        elif call.data == "admin_delete_email":
            user_waiting_for_input[user_id] = 'admin_delete_email'
            emails = get_all_emails()
            
            if emails:
                response = "<b>🗑️ Удалить email</b>\n\nВведите email адрес для удаления:\n\n"
                for i, email in enumerate(emails, 1):
                    response += f"{i}. {email}\n"
                bot.edit_message_text(response, call.message.chat.id, call.message.message_id)
            else:
                bot.edit_message_text("<b>📭 Нет email адресов для удаления.</b>", 
                                     call.message.chat.id, call.message.message_id)
        
        elif call.data == "admin_email_stats":
            emails = get_all_emails()
            emails_data = load_json_file(EMAILS_FILE, {"emails": []})
            unique_users = len(set([email["user_id"] for email in emails_data.get("emails", [])]))
            
            response = f"""<b>📊 Статистика email</b>

Всего email адресов: {len(emails)}
Уникальных пользователей: {unique_users}

<b>Последние добавленные:</b>
"""
            recent_emails = emails_data.get("emails", [])[-5:] if len(emails_data.get("emails", [])) > 5 else emails_data.get("emails", [])
            for email in reversed(recent_emails):
                response += f"• {email['email']} ({email['added_date']})\n"
            
            bot.edit_message_text(response, call.message.chat.id, call.message.message_id)
        
        elif call.data == "admin_email_back":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)
        
        elif call.data == "toggle_auto_reply":
            current = load_setting("channel_auto_reply", "false")
            new_value = "false" if current == "true" else "true"
            save_setting("channel_auto_reply", new_value)
            
            status = "✅ Включен" if new_value == "true" else "❌ Выключен"
            bot.edit_message_text(f"<b>⚙️ Настройки бота</b>\n\nАвтоответ в канале: {status}", 
                                 call.message.chat.id, call.message.message_id,
                                 reply_markup=call.message.reply_markup)
        
        elif call.data == "settings_back":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)

    # ========== ОТПРАВКА В ЧАТЫ/КАНАЛЫ ==========
    @bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'], 
                        func=lambda message: message.chat.type == 'private')
    def handle_private_content_for_chats(message):
        """Обработчик контента для отправки в Telegram чаты/каналы"""
        user_id = message.from_user.id
        
        # Проверяем, ожидает ли пользователь ввода для определенной операции
        if user_id in user_waiting_for_input:
            operation = user_waiting_for_input[user_id]
            
            if operation == 'password':
                check_password(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'email':
                save_email_step(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'admin_add_email':
                save_admin_email_step(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'admin_delete_email':
                delete_admin_email_step(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'platon_message':
                send_to_platon(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'broadcast_users':
                process_broadcast_to_users(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'broadcast_email':
                process_email_broadcast(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'ai':
                # Обработка запроса к ИИ
                response = handle_ai_request(user_id, message.text)
                bot.send_message(message.chat.id, response)
                return
        
        # Проверяем, является ли это кнопкой меню
        menu_buttons = [
            "🔐 Войти в систему", "📧 Добавить email", "📤 Отправить сообщение",
            "📋 Мои чаты и каналы", "📧 Массовая рассылка", "👥 Управление email",
            "Платон🙌", "📢 Рассылка пользователям", "🤖 ИИ-помощник",
            "📧 Мои email", "⚙️ Настройки"
        ]
        
        if message.content_type == 'text' and message.text.strip() in menu_buttons:
            return
        
        # Проверяем, выбрал ли пользователь чат для отправки
        if user_id in selected_chats:
            access_level = check_user_access(user_id)
            
            if access_level != 'admin':
                if user_id in selected_chats:
                    del selected_chats[user_id]
                bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
                return
            
            chat_id = selected_chats[user_id]
            
            try:
                log_event("SEND_TO_CHAT", user_id, f"Chat: {chat_id}, Type: {message.content_type}")
                
                if message.content_type == 'text':
                    bot.send_message(chat_id, message.text)
                    bot.send_message(message.chat.id, f"<b>✅ Текст отправлен в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Text to chat {chat_id}")
                
                elif message.content_type == 'photo':
                    bot.send_photo(chat_id, message.photo[-1].file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Фото отправлено в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Photo to chat {chat_id}")
                
                elif message.content_type == 'video':
                    bot.send_video(chat_id, message.video.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Видео отправлено в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Video to chat {chat_id}")
                
                elif message.content_type == 'document':
                    bot.send_document(chat_id, message.document.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Документ отправлен в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Document to chat {chat_id}")
                
                elif message.content_type == 'audio':
                    bot.send_audio(chat_id, message.audio.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Аудио отправлено в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Audio to chat {chat_id}")
                
                elif message.content_type == 'voice':
                    bot.send_voice(chat_id, message.voice.file_id)
                    bot.send_message(message.chat.id, f"<b>✅ Голосовое сообщение отправлено в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Voice to chat {chat_id}")
                
                elif message.content_type == 'sticker':
                    bot.send_sticker(chat_id, message.sticker.file_id)
                    bot.send_message(message.chat.id, f"<b>✅ Стикер отправлен в чат</b>")
                    log_event("SEND_SUCCESS", user_id, f"Sticker to chat {chat_id}")
                
                # Очищаем выбранный чат
                if user_id in selected_chats:
                    del selected_chats[user_id]
                
            except Exception as e:
                error_msg = str(e)
                bot.send_message(message.chat.id, f"<b>❌ Ошибка при отправке в чат:</b> {error_msg[:200]}")
                log_event("SEND_ERROR", user_id, f"Chat {chat_id}: {error_msg}")
                
                if user_id in selected_chats:
                    del selected_chats[user_id]
            
            return
        
        # Если это обычное текстовое сообщение и не ИИ режим, то обрабатываем как ИИ
        if message.content_type == 'text':
            response = handle_ai_request(user_id, message.text)
            bot.send_message(message.chat.id, response)

    # ========== ОБРАБОТЧИК ПЕРЕСЛАННЫХ СООБЩЕНИЙ ==========
    @bot.message_handler(content_types=['text'], func=lambda message: message.forward_from_chat is not None)
    def handle_forwarded_message(message):
        """Обработчик пересланных сообщений для добавления чата"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            return
        
        chat = message.forward_from_chat
        
        try:
            member = bot.get_chat_member(chat.id, bot.get_me().id)
            if member.status in ['administrator', 'creator']:
                save_user_chat(user_id, chat.id, chat.title, getattr(chat, 'username', None), chat.type)
                
                bot.send_message(message.chat.id, 
                               f"<b>✅ Чат {chat.title} добавлен в список!</b>\n"
                               f"🆔: <code>{chat.id}</code>")
                log_event("CHAT_ADDED", user_id, f"Chat: {chat.title}, ID: {chat.id}")
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Ошибка при добавлении чата: {error_msg}")
            log_event("CHAT_ADD_ERROR", user_id, f"Error: {error_msg}")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def check_password(message):
    """Проверка пароля"""
    user_id = message.from_user.id
    password = message.text.strip()
    
    log_event("PASSWORD_CHECK", user_id, f"Password: {'*' * len(password)}")
    
    if password == PASSWORD_ADMIN:
        save_auth_user('admin', user_id)
        log_event("AUTH_SUCCESS", user_id, "Role: admin")
        bot.send_message(message.chat.id, "<b>✅ Пароль верный! Вы вошли как администратор.</b>")
        show_admin_menu(message)
    
    elif password == PASSWORD_PLATON:
        save_auth_user('platon', user_id)
        log_event("AUTH_SUCCESS", user_id, "Role: platon")
        bot.send_message(message.chat.id, "<b>✅ Пароль верный!</b>")
        show_platon_menu(message)
    
    else:
        log_event("AUTH_FAILED", user_id)
        bot.send_message(message.chat.id,
                        "<b>❌ Неверный пароль!</b>\n\n"
                        "Вы не являетесь ни админом, ни доверенным лицом.\n\n"
                        "Но вы можете использовать ИИ-помощника без ограничений!")
        show_guest_menu(message)

def save_email_step(message):
    """Сохранение email"""
    user_id = message.from_user.id
    email = message.text.strip()
    
    log_event("EMAIL_SAVE_ATTEMPT", user_id, f"Email: {email}")
    
    if '@' in email and '.' in email:
        if save_user_email(user_id, email):
            bot.send_message(message.chat.id,
                            f"<b>✅ Email {email} успешно добавлен!</b>\n\n"
                            f"Теперь вы будете получать уведомления о новых разработках.")
        else:
            bot.send_message(message.chat.id,
                            f"<b>⚠️ Этот email уже был добавлен ранее.</b>")
    else:
        bot.send_message(message.chat.id,
                        "<b>❌ Неверный формат email!</b>\n"
                        "Пожалуйста, введите корректный email адрес (например: user@example.com)")
        user_waiting_for_input[user_id] = 'email'

def save_admin_email_step(message):
    """Сохранение email администратором"""
    user_id = message.from_user.id
    email = message.text.strip()
    
    if '@' in email and '.' in email:
        # Используем фиктивный user_id для админских добавлений
        if save_user_email(0, email):
            bot.send_message(message.chat.id,
                            f"<b>✅ Email {email} успешно добавлен администратором!</b>")
        else:
            bot.send_message(message.chat.id,
                            f"<b>⚠️ Этот email уже был добавлен ранее.</b>")
    else:
        bot.send_message(message.chat.id,
                        "<b>❌ Неверный формат email!</b>\n"
                        "Пожалуйста, введите корректный email адрес.")
        user_waiting_for_input[user_id] = 'admin_add_email'

def delete_admin_email_step(message):
    """Удаление email администратором"""
    user_id = message.from_user.id
    email = message.text.strip()
    
    if delete_email_by_admin(email):
        bot.send_message(message.chat.id,
                        f"<b>✅ Email {email} успешно удален!</b>")
    else:
        bot.send_message(message.chat.id,
                        f"<b>❌ Email {email} не найден.</b>")

def send_to_platon(message):
    """Отправка сообщения Платону"""
    user_id = message.from_user.id
    platon_ids = get_platon_users()
    
    for platon_id in platon_ids:
        try:
            # Отправляем сообщение без пометок
            bot.send_message(platon_id, message.text)
            log_event("SEND_TO_PLATON", user_id, f"To: {platon_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки Платону {platon_id}: {e}")
            log_event("SEND_TO_PLATON_ERROR", user_id, f"To: {platon_id}, Error: {str(e)}")
    
    bot.send_message(message.chat.id,
                    f"<b>✅ Сообщение отправлено Платону</b>")

def broadcast_to_users_func(message_text):
    """Функция рассылки по Telegram"""
    users = get_all_users()
    success_count = 0
    fail_count = 0
    
    if not users:
        return 0, 0
    
    print(f"📢 Начинаю Telegram рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            bot.send_message(user_id, message_text)
            success_count += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"❌ Ошибка отправки пользователю {user_id}: {e}")
            fail_count += 1
    
    return success_count, fail_count

def process_broadcast_to_users(message):
    """Обработка Telegram рассылки"""
    broadcast_message = message.text
    users_count = len(get_all_users())
    
    bot.send_message(message.chat.id, 
                    f"<b>📢 Начинаю Telegram рассылку...</b>\n\n"
                    f"Сообщение: {broadcast_message[:50]}...\n"
                    f"Количество получателей: {users_count}")
    
    success_count, fail_count = broadcast_to_users_func(broadcast_message)
    
    bot.send_message(message.chat.id,
                    f"<b>✅ Telegram рассылка завершена!</b>\n\n"
                    f"Успешно отправлено: {success_count}\n"
                    f"Не удалось отправить: {fail_count}")

def process_email_broadcast(message):
    """Обработка EMAIL рассылки"""
    broadcast_message = message.text
    emails = get_all_emails()
    
    bot.send_message(message.chat.id, 
                    f"<b>📧 Начинаю EMAIL рассылку...</b>\n\n"
                    f"Сообщение: {broadcast_message[:50]}...\n"
                    f"Количество получателей: {len(emails)}")
    
    success_count = 0
    fail_count = 0
    
    for email in emails:
        if send_email(email, "Новости от Google Ermak System", broadcast_message):
            success_count += 1
        else:
            fail_count += 1
        time.sleep(1)
    
    bot.send_message(message.chat.id,
                    f"<b>✅ EMAIL рассылка завершена!</b>\n\n"
                    f"Успешно отправлено: {success_count}\n"
                    f"Не удалось отправить: {fail_count}")

def show_guest_menu(message):
    """Меню гостя"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_auth = types.KeyboardButton("🔐 Войти в систему")
    btn_email = types.KeyboardButton("📧 Добавить email")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    markup.add(btn_auth, btn_email, btn_ai)
    
    welcome_text = f"""<b>{BOT_NAME}</b>

<b>Доступные функции:</b>
✅ ИИ-помощник (безлимитно)
✅ Добавление email для уведомлений
✅ Авторизация для доступа к админским функциям

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

def show_admin_menu(message):
    """Меню админа"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_send = types.KeyboardButton("📤 Отправить сообщение")
    btn_chats = types.KeyboardButton("📋 Мои чаты и каналы")
    btn_email = types.KeyboardButton("📧 Массовая рассылка")
    btn_emails = types.KeyboardButton("👥 Управление email")
    btn_platon = types.KeyboardButton("Платон🙌")
    btn_broadcast = types.KeyboardButton("📢 Рассылка пользователям")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_settings = types.KeyboardButton("⚙️ Настройки")
    markup.add(btn_send, btn_chats, btn_email, btn_emails, btn_platon, btn_broadcast, btn_ai, btn_settings)
    
    welcome_text = f"""<b>{BOT_NAME} - Панель администратора</b>

<b>Доступные функции:</b>
✅ 📤 Отправка сообщений в Telegram чаты/каналы
✅ 📧 Массовая EMAIL рассылка
✅ 👥 Управление email адресами (всех пользователей)
✅ Платон🙌 Управление пользователем Платон
✅ 📢 Рассылка всем пользователям бота (Telegram)
✅ 🤖 ИИ-помощник
✅ ⚙️ Настройки бота

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

def show_platon_menu(message):
    """Меню Платона"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_email = types.KeyboardButton("📧 Мои email")
    markup.add(btn_ai, btn_email)
    
    welcome_text = f"""<b>Приветствуем вас, Платон Бердников!</b>

<b>Доступные функции:</b>
✅ ИИ-помощник для ответов на вопросы (безлимитно)
✅ Просмотр email адресов
   Я переделанный бот @jal_on_Plat_bot
   Ваш телефон под защитой ErmakProtect
   Начните с общения с ИИ
   Внимание: пользователь Ермак не может отправлять вам сообщения в этот чат
   Вы можете добавить свой email для получения рассылок

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"🚀 Запуск Google Ermak System")
    print(f"{'=' * 60}")
    
    # Проверяем наличие файла credentials
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Файл {CREDENTIALS_FILE} не найден!")
        print("   Скачайте файл client_secrets.json с Google Cloud Console")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    # Инициализируем систему
    if not initialize_system():
        print("❌ Критическая ошибка инициализации!")
        input("Нажмите Enter для выхода...")
        sys.exit(1)
    
    # Настраиваем обработчики
    setup_bot_handlers()
    
    print(f"\n{'=' * 60}")
    print("🎯 ОСНОВНЫЕ ФУНКЦИИ БОТА:")
    print("   1. 🔐 Авторизация по паролю (админ/Платон)")
    print("   2. 📧 Управление email адресами")
    print("   3. 🤖 ИИ-помощник (бесплатно для всех)")
    print("   4. 📢 Рассылка всем пользователям бота (Telegram)")
    print("   5. 📧 Массовая EMAIL рассылка")
    print("   6. 📤 Отправка сообщений в Telegram чаты/каналы")
    print("   7. 👥 Управление email (админ)")
    print("   8. ⚙️ Настройки бота (админ)")
    print("   9. 💾 Все данные в Google Drive")
    print(f"{'=' * 60}")
    print("⚡ Бот запущен и готов к работе!")
    print("   Для начала работы напишите /start в Telegram")
    print("=" * 60)
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        
    except Exception as e:
        print(f"\n❌ Ошибка в работе бота: {e}")
        print("🔄 Перезапускаю бота через 5 секунд...")
        time.sleep(5)
        
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e2:
            print(f"❌ Критическая ошибка: {e2}")
            input("Нажмите Enter для выхода...")
