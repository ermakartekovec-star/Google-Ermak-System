# bot_full.py
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
import uuid
import hashlib
from datetime import datetime, timedelta
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
FOLDER_NAME = "E-Genius AI"
SCREENSHOTS_FOLDER = "Screenshots"
PC_COMMANDS_FILE = "pc_commands.json"
PC_STATUS_FILE = "pc_status.json"
CHATS_DB_FILE = "chats.db"
DELAYED_TASKS_FILE = "delayed_tasks.json"
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "client_secrets.json"
CONFIG_FILE = "config.json"
EMAILS_FILE = "emails.json"
SETTINGS_FILE = "settings.json"
AUTH_USERS_FILE = "auth_users.json"
PLATON_APP_FILE = "platon_app_settings.json"
PLATON_TOKENS_FILE = "platon_tokens.json"

# Инициализация бота
bot = None
BOT_NAME = "E-Genius AI⚡"

# Глобальные переменные
GOOGLE_DRIVE_FOLDER_ID = None
SCREENSHOTS_FOLDER_ID = None
BOT_TOKEN = None
PASSWORD_ADMIN = None
PASSWORD_PLATON = None
OPENROUTER_KEY = None
EMAIL_SENDER = None
EMAIL_PASSWORD = None

# Временные данные
selected_chats = {}
user_waiting_for_input = {}
ai_mode_active = {}
user_selected_emails = {}
user_temp_data = {}

# Единственная модель
AI_MODEL = "allenai/molmo-2-8b:free"

# Время задержки для отложенных сообщений
DELAY_TIMES = {
    "1min": 60,
    "5min": 300,
    "10min": 600,
    "30min": 1800
}

# ========== СИСТЕМА БЕЗОПАСНОСТИ ВЕБ-ПРИЛОЖЕНИЯ ==========
def generate_secure_token(user_id):
    """Генерирует защищенный токен с временем жизни"""
    unique_id = str(uuid.uuid4())
    timestamp = int(time.time())
    secret_salt = "EGENIUS_SECURE_SALT_v2"
    
    data_to_hash = f"{user_id}:{unique_id}:{timestamp}:{secret_salt}"
    verification_hash = hashlib.sha256(data_to_hash.encode()).hexdigest()[:16]
    
    token = f"{user_id}_{timestamp}_{unique_id}_{verification_hash}"
    
    save_platon_token(token, user_id)
    
    return token

def verify_secure_token(token):
    """Проверяет токен доступа"""
    try:
        parts = token.split('_')
        if len(parts) != 4:
            return False
        
        user_id_str, timestamp_str, unique_id, received_hash = parts
        
        try:
            user_id = int(user_id_str)
            timestamp = int(timestamp_str)
        except ValueError:
            return False
        
        current_time = int(time.time())
        if current_time - timestamp > 86400:
            delete_platon_token(token)
            return False
        
        secret_salt = "EGENIUS_SECURE_SALT_v2"
        data_to_hash = f"{user_id}:{unique_id}:{timestamp}:{secret_salt}"
        expected_hash = hashlib.sha256(data_to_hash.encode()).hexdigest()[:16]
        
        if received_hash != expected_hash:
            return False
        
        token_data = get_platon_token(token)
        if not token_data:
            return False
        
        if token_data["user_id"] != user_id:
            return False
        
        if token_data.get("used", False):
            return False
        
        if not is_platon_app_enabled():
            return False
        
        mark_token_as_used(token)
        
        return user_id
        
    except Exception as e:
        print(f"❌ Ошибка проверки токена: {e}")
        return False

def save_platon_token(token, user_id):
    """Сохраняет токен в базе"""
    try:
        tokens_data = load_json_file(PLATON_TOKENS_FILE, {"tokens": {}})
        
        tokens_data["tokens"][token] = {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(),
            "used": False
        }
        
        save_json_file(PLATON_TOKENS_FILE, tokens_data)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения токена: {e}")
        return False

def get_platon_token(token):
    """Получает информацию о токене"""
    try:
        tokens_data = load_json_file(PLATON_TOKENS_FILE, {"tokens": {}})
        return tokens_data.get("tokens", {}).get(token)
    except Exception as e:
        print(f"❌ Ошибка получения токена: {e}")
        return None

def mark_token_as_used(token):
    """Помечает токен как использованный"""
    try:
        tokens_data = load_json_file(PLATON_TOKENS_FILE, {"tokens": {}})
        
        if token in tokens_data.get("tokens", {}):
            tokens_data["tokens"][token]["used"] = True
            tokens_data["tokens"][token]["used_at"] = datetime.now().isoformat()
            save_json_file(PLATON_TOKENS_FILE, tokens_data)
            return True
        return False
    except Exception as e:
        print(f"❌ Ошибка отметки токена: {e}")
        return False

def delete_platon_token(token):
    """Удаляет токен"""
    try:
        tokens_data = load_json_file(PLATON_TOKENS_FILE, {"tokens": {}})
        
        if token in tokens_data.get("tokens", {}):
            del tokens_data["tokens"][token]
            save_json_file(PLATON_TOKENS_FILE, tokens_data)
            return True
        return False
    except Exception as e:
        print(f"❌ Ошибка удаления токена: {e}")
        return False

def revoke_all_platon_tokens():
    """Аннулирует ВСЕ токены доступа"""
    try:
        tokens_data = {"tokens": {}, "revoked_at": datetime.now().isoformat()}
        save_json_file(PLATON_TOKENS_FILE, tokens_data)
        log_event("TOKENS_REVOKED", "admin", "All tokens revoked")
        return True
    except Exception as e:
        print(f"❌ Ошибка отзыва токенов: {e}")
        return False

def cleanup_expired_tokens():
    """Очищает просроченные токены"""
    try:
        tokens_data = load_json_file(PLATON_TOKENS_FILE, {"tokens": {}})
        current_time = datetime.now()
        expired_count = 0
        
        tokens_to_delete = []
        
        for token, token_data in tokens_data.get("tokens", {}).items():
            expires_at = datetime.fromisoformat(token_data.get("expires_at", "2000-01-01"))
            if current_time > expires_at:
                tokens_to_delete.append(token)
        
        for token in tokens_to_delete:
            del tokens_data["tokens"][token]
            expired_count += 1
        
        if expired_count > 0:
            save_json_file(PLATON_TOKENS_FILE, tokens_data)
        
        return expired_count
    except Exception as e:
        print(f"❌ Ошибка очистки токенов: {e}")
        return 0

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

def get_or_create_folder(service, folder_name, parent_id=None):
    """Находит или создает папку в Google Drive"""
    try:
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = service.files().list(q=query, fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        if folders:
            return folders[0]['id']
        else:
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                folder_metadata['parents'] = [parent_id]
            
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            return folder.get('id')
    except Exception as e:
        print(f"❌ Ошибка поиска/создания папки: {e}")
        return None

def save_file_to_drive(service, file_name, content, folder_id, mime_type='application/json'):
    """Сохраняет файл в Google Drive"""
    try:
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            file_id = files[0]['id']
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype=mime_type)
            service.files().update(fileId=file_id, media_body=media).execute()
            return file_id
        else:
            file_metadata = {'name': file_name, 'parents': [folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
    except Exception as e:
        print(f"⚠️ Ошибка сохранения файла {file_name}: {e}")
        return None

def save_binary_file_to_drive(service, file_name, binary_content, folder_id, mime_type='application/octet-stream'):
    """Сохраняет бинарный файл в Google Drive"""
    try:
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            file_id = files[0]['id']
            media = MediaIoBaseUpload(io.BytesIO(binary_content), mimetype=mime_type)
            service.files().update(fileId=file_id, media_body=media).execute()
            return file_id
        else:
            file_metadata = {'name': file_name, 'parents': [folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(binary_content), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
    except Exception as e:
        print(f"⚠️ Ошибка сохранения бинарного файла {file_name}: {e}")
        return None

def load_file_from_drive(service, file_name, folder_id):
    """Загружает файл из Google Drive"""
    try:
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
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

def load_binary_file_from_drive(service, file_name, folder_id):
    """Загружает бинарный файл из Google Drive"""
    try:
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
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
    
    content = load_file_from_drive(service, filename, GOOGLE_DRIVE_FOLDER_ID)
    if content:
        try:
            return json.loads(content)
        except:
            return default_data
    else:
        save_json_file(filename, default_data)
        return default_data

def save_json_file(filename, data):
    """Сохраняет JSON файл в Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return False
    
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        save_file_to_drive(service, filename, content, GOOGLE_DRIVE_FOLDER_ID)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения файла {filename}: {e}")
        return False

# ========== СИСТЕМА ОТЛОЖЕННЫХ ЗАДАЧ ==========
def load_delayed_tasks():
    """Загружает отложенные задачи"""
    return load_json_file(DELAYED_TASKS_FILE, {"tasks": []})

def save_delayed_tasks(tasks):
    """Сохраняет отложенные задачи"""
    return save_json_file(DELAYED_TASKS_FILE, tasks)

def add_delayed_task(task_type, target_id, message, delay_seconds, user_id, additional_data=None):
    """Добавляет отложенную задачу"""
    tasks = load_delayed_tasks()
    
    task = {
        "id": str(uuid.uuid4()),
        "type": task_type,
        "target_id": target_id,
        "message": message,
        "scheduled_time": (datetime.now() + timedelta(seconds=delay_seconds)).isoformat(),
        "created_by": user_id,
        "created_at": datetime.now().isoformat(),
        "status": "scheduled",
        "additional_data": additional_data or {}
    }
    
    tasks["tasks"].append(task)
    save_delayed_tasks(tasks)
    
    threading.Timer(delay_seconds, execute_delayed_task, args=[task["id"]]).start()
    
    log_event("DELAYED_TASK_ADDED", user_id, f"Type: {task_type}, Delay: {delay_seconds} sec")
    return task["id"]

def execute_delayed_task(task_id):
    """Выполняет отложенную задачу"""
    tasks = load_delayed_tasks()
    task = None
    task_index = -1
    
    for i, t in enumerate(tasks["tasks"]):
        if t["id"] == task_id and t["status"] == "scheduled":
            task = t
            task_index = i
            break
    
    if not task:
        return
    
    try:
        if task["type"] == "platon_message":
            platon_ids = get_platon_users()
            for platon_id in platon_ids:
                try:
                    bot.send_message(platon_id, task["message"])
                    log_event("DELAYED_PLATON_SENT", task["created_by"], f"To: {platon_id}")
                except Exception as e:
                    print(f"❌ Ошибка отправки отложенного сообщения Платону: {e}")
        
        elif task["type"] == "email_broadcast":
            emails = task["target_id"] if isinstance(task["target_id"], list) else [task["target_id"]]
            success_count = 0
            
            for email in emails:
                if send_email(email, "Новости от E-Genius AI", task["message"]):
                    success_count += 1
                time.sleep(1)
            
            log_event("DELAYED_EMAIL_SENT", task["created_by"], f"Emails: {success_count}/{len(emails)}")
        
        tasks["tasks"][task_index]["status"] = "completed"
        tasks["tasks"][task_index]["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        print(f"❌ Ошибка выполнения отложенной задачи: {e}")
        tasks["tasks"][task_index]["status"] = "failed"
        tasks["tasks"][task_index]["error"] = str(e)
    
    save_delayed_tasks(tasks)

def restore_delayed_tasks():
    """Восстанавливает отложенные задачи при запуске бота"""
    tasks = load_delayed_tasks()
    current_time = datetime.now()
    
    for task in tasks["tasks"]:
        if task["status"] == "scheduled":
            try:
                scheduled_time = datetime.fromisoformat(task["scheduled_time"])
                delay_seconds = (scheduled_time - current_time).total_seconds()
                
                if delay_seconds > 0:
                    threading.Timer(delay_seconds, execute_delayed_task, args=[task["id"]]).start()
                    print(f"✅ Восстановлена отложенная задача: {task['type']} (через {delay_seconds:.0f} сек)")
                else:
                    task["status"] = "overdue"
                    save_delayed_tasks(tasks)
            except Exception as e:
                print(f"❌ Ошибка восстановления задачи: {e}")

# ========== НАСТРОЙКИ ВЕБ-ПРИЛОЖЕНИЯ ПЛАТОНА ==========
def load_platon_app_settings():
    """Загружает настройки веб-приложения Платона"""
    settings = load_json_file(PLATON_APP_FILE, {"enabled": True, "last_updated": None})
    return settings

def save_platon_app_settings(settings):
    """Сохраняет настройки веб-приложения Платона"""
    settings["last_updated"] = datetime.now().isoformat()
    return save_json_file(PLATON_APP_FILE, settings)

def is_platon_app_enabled():
    """Проверяет, включено ли веб-приложение Платона"""
    settings = load_platon_app_settings()
    return settings.get("enabled", True)

def toggle_platon_app(enabled):
    """Включает/выключает веб-приложение Платона"""
    settings = load_platon_app_settings()
    settings["enabled"] = enabled
    save_platon_app_settings(settings)
    
    if not enabled:
        revoke_all_platon_tokens()
        
        platon_ids = get_platon_users()
        for user_id in platon_ids:
            try:
                bot.send_message(user_id, 
                    "⛔ Веб-приложение 🙌MAX_APP временно отключено администратором.\n"
                    "Все предыдущие ссылки более недействительны."
                )
                show_platon_menu(user_id)
            except Exception as e:
                print(f"❌ Ошибка уведомления пользователя {user_id}: {e}")
    
    log_event("PLATON_APP_TOGGLE", "admin", f"Enabled: {enabled}")
    return True

# ========== РАБОТА С БАЗОЙ ДАННЫХ chats.db ==========
def load_chats_db():
    """Загружает базу данных chats.db из Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return None
    
    db_content = load_binary_file_from_drive(service, CHATS_DB_FILE, GOOGLE_DRIVE_FOLDER_ID)
    return db_content

def save_chats_db(db_content):
    """Сохраняет базу данных chats.db в Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return False
    
    try:
        save_binary_file_to_drive(service, CHATS_DB_FILE, db_content, GOOGLE_DRIVE_FOLDER_ID, 'application/x-sqlite3')
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения базы данных: {e}")
        return False

def get_user_chats_from_db(user_id):
    """Получает чаты пользователя из базы данных"""
    try:
        db_content = load_chats_db()
        
        if not db_content or not db_content.startswith(b'SQLite format 3\x00'):
            print("❌ База данных chats.db не найдена или повреждена")
            return []
        
        temp_file = "temp_chats.db"
        with open(temp_file, 'wb') as f:
            f.write(db_content)
        
        conn = sqlite3.connect(temp_file)
        cursor = conn.cursor()
        
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
        
    except Exception as e:
        print(f"❌ Ошибка получения чатов: {e}")
        return []

def save_chat_to_db(user_id, chat_id, chat_title, chat_username=None, chat_type=None):
    """Сохраняет информацию о чате в базу данных"""
    try:
        db_content = load_chats_db()
        
        temp_file = "temp_save.db"
        
        if not db_content or not db_content.startswith(b'SQLite format 3\x00'):
            conn = sqlite3.connect(temp_file)
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
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
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
        
        with open(temp_file, 'rb') as f:
            new_db_content = f.read()
        
        save_chats_db(new_db_content)
        
        conn.close()
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка сохранения чата: {e}")
        if os.path.exists('temp_save.db'):
            os.remove('temp_save.db')
        return False

def init_chats_database():
    """Инициализирует базу данных чатов"""
    try:
        db_content = load_chats_db()
        
        if db_content and db_content.startswith(b'SQLite format 3\x00'):
            print("✅ База данных chats.db загружена из Google Drive")
            
            temp_file = "temp_check.db"
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"📊 Найдено таблиц: {tables}")
            
            conn.close()
            os.remove(temp_file)
            return True
        else:
            print("❌ База данных chats.db не найдена, будет создана при необходимости")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка работы с базой данных: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def get_user_emails(user_id):
    """Получает email пользователя"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    
    user_emails = [email["email"] for email in emails_data["emails"] if email["user_id"] == user_id]
    return user_emails

def get_all_emails():
    """Получает все email"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    
    emails = list(set([email["email"] for email in emails_data["emails"]]))
    return emails

def get_emails_with_users():
    """Получает все email с информацией о пользователях"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    
    result = []
    for item in emails_data["emails"]:
        result.append({
            "user_id": item["user_id"],
            "email": item["email"],
            "added_date": item.get("added_date", "Unknown")
        })
    
    return result

def save_user_email(user_id, email):
    """Сохраняет email пользователя"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    if not isinstance(emails_data, dict):
        emails_data = {"emails": []}
    if "emails" not in emails_data:
        emails_data["emails"] = []
    
    for item in emails_data["emails"]:
        if item["user_id"] == user_id and item["email"] == email:
            return False
    
    emails_data["emails"].append({
        "user_id": user_id,
        "email": email,
        "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    save_json_file(EMAILS_FILE, emails_data)
    log_event("EMAIL_ADDED", user_id, f"Email: {email}")
    return True

def delete_email_by_admin(email):
    """Уделяет email"""
    emails_data = load_json_file(EMAILS_FILE, {"emails": []})
    
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        return False
    
    original_count = len(emails_data["emails"])
    emails_data["emails"] = [item for item in emails_data["emails"] if item["email"] != email]
    
    if len(emails_data["emails"]) < original_count:
        save_json_file(EMAILS_FILE, emails_data)
        return True
    
    return False

def check_user_access(user_id):
    """Проверяет доступ пользователя"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    for user in auth_data["users"]:
        if user["user_id"] == user_id:
            return user["user_type"]
    
    return None

def save_auth_user(user_type, user_id):
    """Сохраняет авторизованного пользователя"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    if not isinstance(auth_data, dict):
        auth_data = {"users": []}
    if "users" not in auth_data:
        auth_data["users"] = []
    
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
    
    if not isinstance(emails_data, dict) or "emails" not in emails_data:
        emails_data = {"emails": []}
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    all_users = set()
    
    for email_item in emails_data["emails"]:
        all_users.add(email_item["user_id"])
    
    for auth_user in auth_data["users"]:
        all_users.add(auth_user["user_id"])
    
    return list(all_users)

def get_platon_users():
    """Получает всех пользователей Платон"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        auth_data = {"users": []}
    
    platon_users = [user["user_id"] for user in auth_data["users"] if user["user_type"] == "platon"]
    return platon_users

def save_setting(key, value):
    """Сохраняет настройку"""
    settings_data = load_json_file(SETTINGS_FILE, {"settings": {}})
    
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
        "X-Title": "E-Genius AI"
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

# ========== ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ ПК ==========
def get_pc_commands():
    """Получает список команд управления ПК"""
    commands_data = load_json_file(PC_COMMANDS_FILE, {"commands": []})
    return commands_data.get("commands", [])

def save_pc_command(command):
    """Сохраняет команду управления ПК"""
    commands_data = load_json_file(PC_COMMANDS_FILE, {"commands": []})
    commands_data["commands"].append(command)
    return save_json_file(PC_COMMANDS_FILE, commands_data)

def get_pc_status():
    """Получает статусы всех ПК"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        return []
    
    content = load_file_from_drive(service, PC_STATUS_FILE, GOOGLE_DRIVE_FOLDER_ID)
    if not content:
        return []
    
    try:
        status_data = json.loads(content)
        if isinstance(status_data, list):
            return status_data
        elif isinstance(status_data, dict):
            return [status_data]
    except:
        return []
    
    return []

def generate_command_id():
    """Генерирует уникальный ID для команды"""
    return str(uuid.uuid4())

def send_pc_command(pc_id, command_type, user_id, additional_data=None):
    """Отправляет команду на ПК"""
    command = {
        "id": generate_command_id(),
        "type": command_type,
        "pc_id": pc_id,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "additional_data": additional_data or {}
    }
    
    if save_pc_command(command):
        log_event("PC_COMMAND_SENT", user_id, f"Type: {command_type}, PC: {pc_id}")
        return True
    return False

def get_available_pcs():
    """Получает список доступных ПК"""
    pcs = get_pc_status()
    return [pc for pc in pcs if datetime.fromisoformat(pc.get('last_seen', '2000-01-01')).timestamp() > time.time() - 300]

def check_screenshots(user_id):
    """Проверяет и отправляет новые скриншоты"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID or not SCREENSHOTS_FOLDER_ID:
        return []
    
    query = f"'{SCREENSHOTS_FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields='files(id, name, mimeType, createdTime)').execute()
    files = results.get('files', [])
    
    screenshots_sent = []
    
    for file in files:
        if file['mimeType'].startswith('image/'):
            filename = file['name']
            
            meta_filename = f"{filename}.meta.json"
            meta_content = load_file_from_drive(service, meta_filename, SCREENSHOTS_FOLDER_ID)
            
            if meta_content:
                try:
                    metadata = json.loads(meta_content)
                    
                    if metadata.get('status') == 'new':
                        request = service.files().get_media(fileId=file['id'])
                        image_content = io.BytesIO()
                        downloader = MediaIoBaseDownload(image_content, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                        
                        image_content.seek(0)
                        
                        if filename.endswith('.png'):
                            bot.send_photo(user_id, image_content, 
                                         caption=f"📸 Скриншот от {metadata.get('pc_id', 'Unknown')}\n"
                                                f"📅 {metadata.get('created_at', 'Unknown')}")
                        else:
                            bot.send_document(user_id, image_content, 
                                            caption=f"📸 Скриншот от {metadata.get('pc_id', 'Unknown')}")
                        
                        metadata['status'] = 'sent'
                        metadata['sent_to'] = user_id
                        metadata['sent_at'] = datetime.now().isoformat()
                        
                        save_file_to_drive(service, meta_filename, 
                                          json.dumps(metadata, indent=2, ensure_ascii=False),
                                          SCREENSHOTS_FOLDER_ID)
                        
                        screenshots_sent.append(filename)
                        log_event("SCREENSHOT_SENT", user_id, f"File: {filename}")
                        
                except Exception as e:
                    print(f"❌ Ошибка обработки скриншота {filename}: {e}")
    
    return screenshots_sent

# ========== ЗАГРУЗКА КОНФИГУРАЦИИ ==========
def load_config_from_drive():
    """Загружает конфигурацию из Google Drive"""
    service = get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        print("❌ Нет подключения к Google Drive")
        return False
    
    content = load_file_from_drive(service, CONFIG_FILE, GOOGLE_DRIVE_FOLDER_ID)
    if not content:
        print(f"❌ Файл {CONFIG_FILE} не найден в Google Drive")
        
        example_config = {
            "BOT_TOKEN": "ВАШ_ТОКЕН_ТЕЛЕГРАМ_БОТА",
            "PASSWORD_ADMIN": "админ_пароль",
            "PASSWORD_PLATON": "платон_пароль",
            "OPENROUTER_KEY": "sk-or-v1-ваш_ключ_openrouter",
            "EMAIL_SENDER": "ваш_email@gmail.com",
            "EMAIL_PASSWORD": "ваш_пароль_приложения"
        }
        
        save_file_to_drive(service, CONFIG_FILE, json.dumps(example_config, indent=2, ensure_ascii=False), GOOGLE_DRIVE_FOLDER_ID)
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
    
    global GOOGLE_DRIVE_FOLDER_ID
    query = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields='files(id, name)').execute()
    folders = results.get('files', [])
    
    if folders:
        GOOGLE_DRIVE_FOLDER_ID = folders[0]['id']
    else:
        folder_metadata = {
            'name': FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        GOOGLE_DRIVE_FOLDER_ID = folder.get('id')
    
    print(f"✅ Папка: https://drive.google.com/drive/folders/{GOOGLE_DRIVE_FOLDER_ID}")
    
    global SCREENSHOTS_FOLDER_ID
    SCREENSHOTS_FOLDER_ID = get_or_create_folder(service, SCREENSHOTS_FOLDER, GOOGLE_DRIVE_FOLDER_ID)
    
    if not load_config_from_drive():
        print("❌ Не удалось загрузить конфигурацию")
        return False
    
    init_chats_database()
    
    initial_files = [
        (PC_COMMANDS_FILE, {"commands": []}),
        (PC_STATUS_FILE, []),
        (EMAILS_FILE, {"emails": []}),
        (AUTH_USERS_FILE, {"users": []}),
        (SETTINGS_FILE, {"settings": {}}),
        (PLATON_APP_FILE, {"enabled": True, "last_updated": None}),
        (PLATON_TOKENS_FILE, {"tokens": {}}),
        (DELAYED_TASKS_FILE, {"tasks": []})
    ]
    
    for filename, default_data in initial_files:
        content = load_file_from_drive(service, filename, GOOGLE_DRIVE_FOLDER_ID)
        if not content:
            save_file_to_drive(service, filename, json.dumps(default_data, indent=2, ensure_ascii=False), GOOGLE_DRIVE_FOLDER_ID)
    
    print("✅ Система инициализирована")
    return True

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С КОМАНДАМИ ПК ==========
def show_pc_selection(call, command_type, message_text):
    """Показывает выбор ПК для команды"""
    user_id = call.from_user.id
    pcs = get_available_pcs()
    
    if not pcs:
        bot.edit_message_text(
            "<b>❌ Нет доступных ПК в сети.</b>\n\n"
            "Убедитесь, что скрипт управления ПК запущен на целевом компьютере.",
            call.message.chat.id,
            call.message.message_id
        )
        return
    
    markup = types.InlineKeyboardMarkup()
    
    for pc in pcs:
        pc_id = pc.get('pc_id', 'Unknown')
        hostname = pc.get('hostname', 'Unknown')
        last_seen = datetime.fromisoformat(pc.get('last_seen', '2000-01-01')).strftime("%H:%M:%S")
        
        button_text = f"{hostname} (последний раз: {last_seen})"
        callback_data = f"pc_select_{command_type}_{pc_id}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
    
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="pc_cancel"))
    
    bot.edit_message_text(
        message_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# ========== ОБРАБОТЧИКИ КОМАНД ==========
def setup_bot_handlers():
    """Настраивает обработчики бота"""
    
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        """Обработчик команды /start"""
        user_id = message.from_user.id
        log_event("START", user_id)
        
        if user_id in ai_mode_active:
            del ai_mode_active[user_id]
        
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
        
        ai_mode_active[user_id] = True
        
        bot.send_message(message.chat.id,
                        "<b>🤖 ИИ-помощник активирован!</b>\n\n"
                        "Задайте любой вопрос, и я постараюсь помочь.\n\n"
                        "💡 <b>Безлимитное использование для всех</b>\n"
                        "⏸️ <i>Для выхода из режима ИИ нажмите кнопку '⏸️ Остановить ИИ'</i>")
    
    @bot.message_handler(func=lambda message: message.text == "⏸️ Остановить ИИ")
    def stop_ai_handler(message):
        """Остановка режима ИИ"""
        user_id = message.from_user.id
        
        if user_id in ai_mode_active:
            del ai_mode_active[user_id]
            log_event("AI_STOPPED", user_id)
        
        access_level = check_user_access(user_id)
        
        if access_level == 'admin':
            show_admin_menu(message)
        elif access_level == 'platon':
            show_platon_menu(message)
        else:
            show_guest_menu(message)
    
    @bot.message_handler(func=lambda message: message.text == "👍ERMAK APP")
    def ermak_app_handler(message):
        """Открытие веб-приложения ERMAK"""
        user_id = message.from_user.id
        log_event("ERMAK_APP_OPEN", user_id)
        
        markup = types.InlineKeyboardMarkup()
        app_button = types.InlineKeyboardButton(
            "🌐 Открыть ERMAK APP", 
            url="https://t.me/EGenius_AI_bot/ermak_app"
        )
        markup.add(app_button)
        
        bot.send_message(
            message.chat.id,
            "<b>🚀 Откройте ERMAK APP прямо сейчас!</b>\n\n"
            "Нажмите на кнопку ниже, чтобы мгновенно открыть веб-приложение:",
            reply_markup=markup
        )
    
    @bot.message_handler(func=lambda message: message.text == "🙌MAX_APP")
    def platon_app_handler(message):
        """Открытие веб-приложения MAX для Платона"""
        user_id = message.from_user.id
        
        if not is_platon_app_enabled():
            bot.send_message(message.chat.id, 
                           "<b>⛔ Веб-приложение временно отключено администратором.</b>")
            return
        
        access_level = check_user_access(user_id)
        if access_level != 'platon':
            bot.send_message(message.chat.id, "<b>❌ Доступ к этому приложению только у Платона.</b>")
            return
        
        log_event("PLATON_APP_OPEN", user_id)
        
        token = generate_secure_token(user_id)
        app_url = f"https://t.me/Ermak_MAX_bot/platon_app?startapp={token}"
        
        markup = types.InlineKeyboardMarkup()
        app_button = types.InlineKeyboardButton(
            "🌐 Открыть MAX APP (одноразовая ссылка)", 
            url=app_url
        )
        markup.add(app_button)
        
        refresh_button = types.InlineKeyboardButton(
            "🔄 Получить новую ссылку", 
            callback_data="refresh_platon_app"
        )
        markup.add(refresh_button)
        
        bot.send_message(
            message.chat.id,
            f"<b>🚀 Откройте MAX APP прямо сейчас!</b>\n\n"
            f"Нажмите на кнопку ниже, чтобы мгновенно открыть веб-приложение:\n\n"
            f"<b>⚠️ Важно:</b>\n"
            f"• Ссылка действительна 24 часа\n"
            f"• Каждая ссылка работает только один раз\n"
            f"• При блокировке приложения все ссылки становятся недействительными\n\n"
            f"<i>Для получения новой ссылки нажмите '🔄 Получить новую ссылку'</i>",
            reply_markup=markup
        )
    
    @bot.message_handler(func=lambda message: message.text == "📤 Отправить сообщение")
    def send_message_handler(message):
        """Отправка сообщения в ТЕЛЕГРАМ чат/канал"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        chats = get_user_chats_from_db(user_id)
        
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
        
        chats = get_user_chats_from_db(user_id)
        
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
            types.InlineKeyboardButton("📧 Выборочная рассылка", callback_data="selective_email"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_email_back")
        ]
        markup.add(*buttons)
        
        bot.send_message(message.chat.id,
                        "<b>👥 Управление email адресами</b>\n\n"
                        "Вы можете просматривать, добавлять и удалять email адреса всех пользователей.",
                        reply_markup=markup)
    
    @bot.message_handler(func=lambda message: message.text == "Платон🙌")
    def platon_admin_handler(message):
        """Меню управления Платоном"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✍️ Отправить сообщение", callback_data="send_to_platon"),
            types.InlineKeyboardButton("⏰ Отложенная отправка", callback_data="delayed_platon"),
            types.InlineKeyboardButton("📋 Пользователи Платон", callback_data="platon_users"),
            types.InlineKeyboardButton("⚙️ Управление MAX APP", callback_data="manage_platon_app"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="platon_back")
        )
        
        platon_count = len(get_platon_users())
        app_status = "✅ Включено" if is_platon_app_enabled() else "❌ Отключено"
        
        bot.send_message(message.chat.id,
                        f"<b>👤 Управление пользователем Платон</b>\n\n"
                        f"📊 Пользователей с доступом: {platon_count}\n"
                        f"🌐 Веб-приложение MAX: {app_status}\n\n"
                        f"<b>Выберите действие:</b>",
                        reply_markup=markup)
    
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
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📧 Всем пользователям", callback_data="email_broadcast_all"),
            types.InlineKeyboardButton("🎯 Выборочная рассылка", callback_data="email_selective_start"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="email_broadcast_back")
        )
        
        bot.send_message(message.chat.id,
                        f"<b>📧 Массовая EMAIL рассылка</b>\n\n"
                        f"Найдено {len(emails)} email адресов.\n\n"
                        f"<b>Выберите тип рассылки:</b>",
                        reply_markup=markup)
    
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
        platon_app_enabled = is_platon_app_enabled()
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        auto_reply_status = "✅ Включен" if channel_auto_reply else "❌ Выключен"
        markup.add(types.InlineKeyboardButton(
            f"🤖 Автоответ в канале: {auto_reply_status}",
            callback_data="toggle_auto_reply"
        ))
        
        channel_text = f"📢 Канал: настроен" if channel_id else "📢 Канал: не настроен"
        markup.add(types.InlineKeyboardButton(channel_text, callback_data="set_channel"))
        
        platon_app_status = "✅ Включено" if platon_app_enabled else "❌ Отключено"
        markup.add(types.InlineKeyboardButton(
            f"🌐 Веб-приложение Платона: {platon_app_status}",
            callback_data="toggle_platon_app"
        ))
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings_back"))
        
        bot.send_message(message.chat.id,
                        "<b>⚙️ Настройки бота</b>\n\n"
                        "Здесь вы можете настроить различные функции бота.",
                        reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == "🖥️ Управление ПК")
    def pc_control_handler(message):
        """Обработчик управления ПК"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            return
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            types.InlineKeyboardButton("🔄 Завершение работы", callback_data="pc_shutdown"),
            types.InlineKeyboardButton("🔁 Перезагрузка", callback_data="pc_restart"),
            types.InlineKeyboardButton("😴 Спящий режим", callback_data="pc_sleep"),
            types.InlineKeyboardButton("💤 Гибернация", callback_data="pc_hibernate"),
            types.InlineKeyboardButton("🔒 Блокировка", callback_data="pc_lock"),
            types.InlineKeyboardButton("📸 Скриншот", callback_data="pc_screenshot"),
            types.InlineKeyboardButton("🔍 Проверить скриншоты", callback_data="pc_check_screenshots"),
            types.InlineKeyboardButton("📊 Статус ПК", callback_data="pc_status"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="pc_back")
        ]
        
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                markup.add(buttons[i], buttons[i+1])
            else:
                markup.add(buttons[i])
        
        pcs = get_available_pcs()
        pc_list = "\n".join([f"• {pc.get('hostname', 'Unknown')} ({pc.get('pc_id', 'Unknown')})" for pc in pcs]) if pcs else "❌ ПК не найдены"
        
        bot.send_message(message.chat.id,
                        f"<b>🖥️ Управление ПК</b>\n\n"
                        f"<b>Доступные ПК:</b>\n{pc_list}\n\n"
                        f"<b>Выберите действие:</b>",
                        reply_markup=markup)

    # ========== CALLBACK ОБРАБОТЧИКИ ==========
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback_query(call):
        """Обработчик callback запросов"""
        user_id = call.from_user.id
        access_level = check_user_access(user_id)
        
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
        
        elif call.data == "selective_email":
            emails_list = get_emails_with_users()
            
            if not emails_list:
                bot.edit_message_text("<b>📭 Нет email адресов для выбора.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            user_selected_emails[user_id] = []
            user_temp_data[user_id] = {
                "email_list": emails_list,
                "current_page": 0
            }
            
            show_email_selection_page(call.message, user_id, 0)
        
        elif call.data.startswith("email_select_"):
            email_index = int(call.data.split("_")[2])
            
            if user_id in user_temp_data and user_id in user_selected_emails:
                emails_list = user_temp_data[user_id]["email_list"]
                current_page = user_temp_data[user_id]["current_page"]
                items_per_page = 5
                start_index = current_page * items_per_page
                
                if 0 <= email_index < len(emails_list):
                    email_info = emails_list[email_index]
                    email_address = email_info["email"]
                    
                    if email_address in user_selected_emails[user_id]:
                        user_selected_emails[user_id].remove(email_address)
                    else:
                        user_selected_emails[user_id].append(email_address)
                    
                    show_email_selection_page(call.message, user_id, current_page)
        
        elif call.data.startswith("email_page_"):
            page_num = int(call.data.split("_")[2])
            show_email_selection_page(call.message, user_id, page_num)
        
        elif call.data == "email_finish_selection":
            if user_id in user_selected_emails and user_selected_emails[user_id]:
                selected_count = len(user_selected_emails[user_id])
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                buttons = [
                    types.InlineKeyboardButton("⏱️ 1 минута", callback_data="delay_60"),
                    types.InlineKeyboardButton("⏱️ 5 минут", callback_data="delay_300"),
                    types.InlineKeyboardButton("⏱️ 10 минут", callback_data="delay_600"),
                    types.InlineKeyboardButton("⏱️ 30 минут", callback_data="delay_1800"),
                    types.InlineKeyboardButton("🚀 Отправить сейчас", callback_data="delay_0"),
                    types.InlineKeyboardButton("❌ Отмена", callback_data="email_cancel_selection")
                ]
                markup.add(*buttons)
                
                bot.edit_message_text(
                    f"<b>✅ Выбрано {selected_count} email адресов</b>\n\n"
                    f"<b>Выберите время отправки:</b>\n\n"
                    f"💡 Отложенная отправка позволит отправить сообщение через указанное время.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup
                )
                
                user_waiting_for_input[user_id] = 'selective_email_message'
            else:
                bot.edit_message_text("<b>❌ Не выбрано ни одного email адреса.</b>", 
                                     call.message.chat.id, call.message.message_id)
        
        elif call.data == "email_cancel_selection":
            if user_id in user_selected_emails:
                del user_selected_emails[user_id]
            if user_id in user_temp_data:
                del user_temp_data[user_id]
            
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)
        
        elif call.data.startswith("delay_"):
            delay_seconds = int(call.data.split("_")[1])
            
            if user_id in user_waiting_for_input and user_waiting_for_input[user_id] == 'selective_email_message':
                user_temp_data[user_id] = {"delay": delay_seconds}
                
                bot.edit_message_text(
                    "<b>✍️ Введите сообщение для рассылки:</b>\n\n"
                    "Сообщение будет отправлено на выбранные email адреса.",
                    call.message.chat.id,
                    call.message.message_id
                )
        
        elif call.data == "email_broadcast_all":
            emails = get_all_emails()
            
            if not emails:
                bot.edit_message_text("<b>📭 Нет email адресов для рассылки.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            buttons = [
                types.InlineKeyboardButton("⏱️ 1 минута", callback_data="broadcast_delay_60"),
                types.InlineKeyboardButton("⏱️ 5 минут", callback_data="broadcast_delay_300"),
                types.InlineKeyboardButton("⏱️ 10 минут", callback_data="broadcast_delay_600"),
                types.InlineKeyboardButton("⏱️ 30 минут", callback_data="broadcast_delay_1800"),
                types.InlineKeyboardButton("🚀 Отправить сейчас", callback_data="broadcast_delay_0"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="email_broadcast_back")
            ]
            markup.add(*buttons)
            
            bot.edit_message_text(
                f"<b>📧 Рассылка всем пользователям</b>\n\n"
                f"Найдено {len(emails)} email адресов.\n\n"
                f"<b>Выберите время отправки:</b>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        
        elif call.data == "email_selective_start":
            emails_list = get_emails_with_users()
            
            if not emails_list:
                bot.edit_message_text("<b>📭 Нет email адресов для выбора.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            user_selected_emails[user_id] = []
            user_temp_data[user_id] = {
                "email_list": emails_list,
                "current_page": 0
            }
            
            show_email_selection_page(call.message, user_id, 0)
        
        elif call.data == "email_broadcast_back":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)
        
        elif call.data.startswith("broadcast_delay_"):
            delay_seconds = int(call.data.split("_")[2])
            user_waiting_for_input[user_id] = 'broadcast_email'
            user_temp_data[user_id] = {"delay": delay_seconds}
            
            bot.edit_message_text(
                "<b>✍️ Введите сообщение для массовой рассылки:</b>\n\n"
                "Сообщение будет отправлено на все email адреса.",
                call.message.chat.id,
                call.message.message_id
            )
        
        elif call.data == "toggle_auto_reply":
            current = load_setting("channel_auto_reply", "false")
            new_value = "false" if current == "true" else "true"
            save_setting("channel_auto_reply", new_value)
            
            status = "✅ Включен" if new_value == "true" else "❌ Выключен"
            bot.edit_message_text(f"<b>⚙️ Настройки бота</b>\n\nАвтоответ в канале: {status}", 
                                 call.message.chat.id, call.message.message_id,
                                 reply_markup=call.message.reply_markup)
        
        elif call.data == "toggle_platon_app":
            current_status = is_platon_app_enabled()
            new_status = not current_status
            
            toggle_platon_app(new_status)
            
            status_text = "✅ Включено" if new_status else "❌ Отключено"
            bot.edit_message_text(f"<b>⚙️ Настройки бота</b>\n\nВеб-приложение Платона: {status_text}", 
                                 call.message.chat.id, call.message.message_id,
                                 reply_markup=call.message.reply_markup)
            
            if not new_status:
                platon_users = get_platon_users()
                for platon_id in platon_users:
                    try:
                        bot.send_message(platon_id, "⛔ Веб-приложение 🙌MAX_APP временно отключено администратором.")
                        show_platon_menu(platon_id)
                    except Exception as e:
                        print(f"❌ Ошибка уведомления пользователя {platon_id}: {e}")
        
        elif call.data == "settings_back":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)
        
        elif call.data == "set_channel":
            user_waiting_for_input[user_id] = 'set_channel_id'
            bot.edit_message_text("<b>📢 Настройка канала</b>\n\nВведите ID канала (например: -1001234567890):", 
                                 call.message.chat.id, call.message.message_id)
        
        elif call.data.startswith("pc_"):
            if access_level != 'admin':
                bot.answer_callback_query(call.id, "❌ Доступ запрещен!")
                return
            
            if call.data == "pc_shutdown":
                show_pc_selection(call, "shutdown", "🔄 Выберите ПК для завершения работы:")
            
            elif call.data == "pc_restart":
                show_pc_selection(call, "restart", "🔁 Выберите ПК для перезагрузки:")
            
            elif call.data == "pc_sleep":
                show_pc_selection(call, "sleep", "😴 Выберите ПК для перевода в спящий режим:")
            
            elif call.data == "pc_hibernate":
                show_pc_selection(call, "hibernate", "💤 Выберите ПК для перевода в гибернацию:")
            
            elif call.data == "pc_lock":
                show_pc_selection(call, "lock", "🔒 Выберите ПК для блокировки:")
            
            elif call.data == "pc_screenshot":
                show_pc_selection(call, "screenshot", "📸 Выберите ПК для создания скриншота:")
            
            elif call.data == "pc_check_screenshots":
                sent_screenshots = check_screenshots(user_id)
                
                if sent_screenshots:
                    bot.answer_callback_query(call.id, f"✅ Отправлено {len(sent_screenshots)} скриншотов")
                else:
                    bot.answer_callback_query(call.id, "❌ Новых скриншотов нет")
            
            elif call.data == "pc_status":
                pcs = get_available_pcs()
                
                if not pcs:
                    bot.edit_message_text(
                        "<b>❌ Нет доступных ПК в сети.</b>",
                        call.message.chat.id,
                        call.message.message_id
                    )
                    return
                
                response = "<b>📊 Статус ПК:</b>\n\n"
                
                for pc in pcs:
                    last_seen = datetime.fromisoformat(pc.get('last_seen', '2000-01-01'))
                    time_diff = datetime.now() - last_seen
                    status = "✅ Онлайн" if time_diff.total_seconds() < 60 else "⚠️ Недавно" if time_diff.total_seconds() < 300 else "❌ Оффлайн"
                    
                    response += f"<b>{pc.get('hostname', 'Unknown')}</b>\n"
                    response += f"ID: <code>{pc.get('pc_id', 'Unknown')}</code>\n"
                    response += f"Пользователь: {pc.get('username', 'Unknown')}\n"
                    response += f"Статус: {status}\n"
                    response += f"IP: {pc.get('ip_address', 'Unknown')}\n"
                    response += f"CPU: {pc.get('cpu_usage', 0)}%\n"
                    response += f"Память: {pc.get('memory_usage', 0)}%\n"
                    response += f"Последний раз: {last_seen.strftime('%H:%M:%S')}\n"
                    response += "─" * 20 + "\n"
                
                bot.edit_message_text(
                    response,
                    call.message.chat.id,
                    call.message.message_id
                )
            
            elif call.data == "pc_back":
                bot.delete_message(call.message.chat.id, call.message.message_id)
                show_admin_menu(call.message)
            
            elif call.data == "pc_cancel":
                bot.delete_message(call.message.chat.id, call.message.message_id)
                show_admin_menu(call.message)
            
            elif call.data.startswith("pc_select_"):
                parts = call.data.split("_")
                if len(parts) >= 4:
                    command_type = parts[2]
                    pc_id = "_".join(parts[3:])
                    
                    if send_pc_command(pc_id, command_type, user_id):
                        pcs = get_available_pcs()
                        pc_info = next((pc for pc in pcs if pc.get('pc_id') == pc_id), {})
                        
                        command_names = {
                            'shutdown': 'завершение работы',
                            'restart': 'перезагрузка',
                            'sleep': 'спящий режим',
                            'hibernate': 'гибернация',
                            'lock': 'блокировка',
                            'screenshot': 'скриншот'
                        }
                        
                        command_name = command_names.get(command_type, command_type)
                        
                        bot.edit_message_text(
                            f"<b>✅ Команда отправлена!</b>\n\n"
                            f"<b>Команда:</b> {command_name}\n"
                            f"<b>ПК:</b> {pc_info.get('hostname', pc_id)}\n"
                            f"<b>Время:</b> {datetime.now().strftime('%H:%M:%S')}\n\n"
                            f"<i>Команда будет выполнена в течение 10 секунд.</i>",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    else:
                        bot.edit_message_text(
                            "<b>❌ Ошибка отправки команды.</b>",
                            call.message.chat.id,
                            call.message.message_id
                        )
        
        elif call.data == "send_to_platon":
            platon_ids = get_platon_users()
            
            if not platon_ids:
                bot.edit_message_text("<b>❌ Пользователь Платон ещё не авторизовался.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            user_waiting_for_input[user_id] = 'platon_message'
            bot.edit_message_text("<b>✍️ Введите сообщение для Платона:</b>", 
                                 call.message.chat.id, call.message.message_id)
        
        elif call.data == "delayed_platon":
            platon_ids = get_platon_users()
            
            if not platon_ids:
                bot.edit_message_text("<b>❌ Пользователь Платон ещё не авторизовался.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            buttons = [
                types.InlineKeyboardButton("⏱️ 1 минута", callback_data="platon_delay_60"),
                types.InlineKeyboardButton("⏱️ 5 минут", callback_data="platon_delay_300"),
                types.InlineKeyboardButton("⏱️ 10 минут", callback_data="platon_delay_600"),
                types.InlineKeyboardButton("⏱️ 30 минут", callback_data="platon_delay_1800"),
                types.InlineKeyboardButton("🚀 Отправить сейчас", callback_data="platon_delay_0"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="platon_back")
            ]
            markup.add(*buttons)
            
            bot.edit_message_text(
                "<b>⏰ Отложенная отправка Платону</b>\n\n"
                "Выберите время, через которое отправить сообщение:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        
        elif call.data == "platon_users":
            platon_ids = get_platon_users()
            
            if not platon_ids:
                bot.edit_message_text("<b>❌ Нет пользователей с доступом Платон.</b>", 
                                     call.message.chat.id, call.message.message_id)
                return
            
            response = "<b>👤 Пользователи с доступом Платон:</b>\n\n"
            
            for i, platon_id in enumerate(platon_ids, 1):
                try:
                    user = bot.get_chat(platon_id)
                    username = f"@{user.username}" if user.username else "нет username"
                    response += f"{i}. {user.first_name or ''} {user.last_name or ''} ({username})\n"
                    response += f"   🆔: <code>{platon_id}</code>\n\n"
                except:
                    response += f"{i}. Пользователь {platon_id}\n\n"
            
            bot.edit_message_text(response, call.message.chat.id, call.message.message_id)
        
        elif call.data == "manage_platon_app":
            app_status = is_platon_app_enabled()
            status_text = "✅ Включено" if app_status else "❌ Отключено"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            if app_status:
                markup.add(types.InlineKeyboardButton("🚫 Отключить", callback_data="disable_platon_app"))
            else:
                markup.add(types.InlineKeyboardButton("✅ Включить", callback_data="enable_platon_app"))
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="platon_back"))
            
            bot.edit_message_text(
                f"<b>⚙️ Управление веб-приложением Платона</b>\n\n"
                f"Текущий статус: {status_text}\n\n"
                f"Ссылка: https://t.me/Ermak_MAX_bot/platon_app\n\n"
                f"<b>При отключении:</b>\n"
                f"• Кнопка 🙌MAX_APP исчезнет у всех пользователей Платона\n"
                f"• Все ранее выданные токены становятся недействительными\n"
                f"• Даже сохраненные ссылки перестанут работать",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        
        elif call.data in ["disable_platon_app", "enable_platon_app"]:
            new_status = call.data == "enable_platon_app"
            toggle_platon_app(new_status)
            
            status_text = "✅ Включено" if new_status else "❌ Отключено"
            bot.edit_message_text(
                f"<b>✅ Веб-приложение Платона {status_text.lower()}</b>\n\n"
                f"Изменения применены ко всем пользователям.",
                call.message.chat.id,
                call.message.message_id
            )
        
        elif call.data == "platon_back":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            show_admin_menu(call.message)
        
        elif call.data.startswith("platon_delay_"):
            delay_seconds = int(call.data.split("_")[2])
            user_waiting_for_input[user_id] = 'delayed_platon_message'
            user_temp_data[user_id] = {"delay": delay_seconds}
            
            bot.edit_message_text(
                "<b>✍️ Введите сообщение для отложенной отправки Платону:</b>",
                call.message.chat.id,
                call.message.message_id
            )
        
        elif call.data == "refresh_platon_app":
            access_level = check_user_access(user_id)
            if access_level != 'platon':
                bot.answer_callback_query(call.id, "❌ Доступно только для Платона")
                return
            
            if not is_platon_app_enabled():
                bot.answer_callback_query(call.id, "❌ Приложение отключено")
                return
            
            token = generate_secure_token(user_id)
            app_url = f"https://t.me/Ermak_MAX_bot/platon_app?startapp={token}"
            
            markup = types.InlineKeyboardMarkup()
            app_button = types.InlineKeyboardButton(
                "🌐 Открыть MAX APP (новая ссылка)", 
                url=app_url
            )
            markup.add(app_button)
            
            refresh_button = types.InlineKeyboardButton(
                "🔄 Получить новую ссылку", 
                callback_data="refresh_platon_app"
            )
            markup.add(refresh_button)
            
            bot.edit_message_text(
                f"<b>🔄 Новая ссылка сгенерирована!</b>\n\n"
                f"Нажмите на кнопку ниже, чтобы открыть веб-приложение:\n\n"
                f"<b>⚠️ Важно:</b>\n"
                f"• Ссылка действительна 24 часа\n"
                f"• Каждая ссылка работает только один раз",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            
            bot.answer_callback_query(call.id, "✅ Новая ссылка сгенерирована")

    # ========== ФУНКЦИЯ ДЛЯ ПОКАЗА ВЫБОРА EMAIL ==========
    def show_email_selection_page(message, user_id, page_num):
        """Показывает страницу выбора email адресов"""
        if user_id not in user_temp_data:
            return
        
        emails_list = user_temp_data[user_id]["email_list"]
        items_per_page = 5
        total_pages = (len(emails_list) + items_per_page - 1) // items_per_page
        
        if page_num >= total_pages:
            page_num = 0
        
        user_temp_data[user_id]["current_page"] = page_num
        
        start_index = page_num * items_per_page
        end_index = min(start_index + items_per_page, len(emails_list))
        
        markup = types.InlineKeyboardMarkup()
        
        for i in range(start_index, end_index):
            email_info = emails_list[i]
            email_address = email_info["email"]
            user_id_info = email_info["user_id"]
            
            is_selected = email_address in user_selected_emails.get(user_id, [])
            checkbox = "✅" if is_selected else "⬜"
            
            button_text = f"{checkbox} {email_address}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"email_select_{i}"))
        
        nav_buttons = []
        if page_num > 0:
            nav_buttons.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"email_page_{page_num-1}"))
        
        if page_num < total_pages - 1:
            nav_buttons.append(types.InlineKeyboardButton("Вперед ▶️", callback_data=f"email_page_{page_num+1}"))
        
        if nav_buttons:
            markup.add(*nav_buttons)
        
        action_buttons = []
        if user_id in user_selected_emails and user_selected_emails[user_id]:
            selected_count = len(user_selected_emails[user_id])
            action_buttons.append(types.InlineKeyboardButton(f"✅ Выбрано: {selected_count}", callback_data="email_finish_selection"))
        
        action_buttons.append(types.InlineKeyboardButton("❌ Отмена", callback_data="email_cancel_selection"))
        markup.add(*action_buttons)
        
        bot.edit_message_text(
            f"<b>📧 Выберите email адреса для рассылки</b>\n\n"
            f"Страница {page_num + 1} из {total_pages}\n"
            f"Нажмите на email, чтобы выбрать/снять выбор\n\n"
            f"✅ - выбран\n⬜ - не выбран",
            message.chat.id,
            message.message_id,
            reply_markup=markup
        )

    # ========== ОТПРАВКА В ЧАТЫ/КАНАЛЫ ==========
    @bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'], 
                        func=lambda message: message.chat.type == 'private')
    def handle_private_content_for_chats(message):
        """Обработчик контента для отправки в Telegram чаты/каналы"""
        user_id = message.from_user.id
        
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
            
            elif operation == 'delayed_platon_message':
                process_delayed_platon(message)
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
            
            elif operation == 'selective_email_message':
                process_selective_email(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'set_channel_id':
                process_set_channel(message)
                del user_waiting_for_input[user_id]
                return
        
        menu_buttons = [
            "🔐 Войти в систему", "📧 Добавить email", "📤 Отправить сообщение",
            "📋 Мои чаты и каналы", "📧 Массовая рассылка", "👥 Управление email",
            "Платон🙌", "📢 Рассылка пользователям", "🤖 ИИ-помощник",
            "⏸️ Остановить ИИ", "📧 Мои email", "⚙️ Настройки", "🖥️ Управление ПК",
            "👍ERMAK APP", "🙌MAX_APP"
        ]
        
        if message.content_type == 'text' and message.text.strip() in menu_buttons:
            return
        
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
                
                if user_id in selected_chats:
                    del selected_chats[user_id]
                
            except Exception as e:
                error_msg = str(e)
                bot.send_message(message.chat.id, f"<b>❌ Ошибка при отправке в чат:</b> {error_msg[:200]}")
                log_event("SEND_ERROR", user_id, f"Chat {chat_id}: {error_msg}")
                
                if user_id in selected_chats:
                    del selected_chats[user_id]
            
            return
        
        if user_id in ai_mode_active and ai_mode_active[user_id]:
            response = handle_ai_request(user_id, message.text if message.content_type == 'text' else "Я получил от вас медиа-сообщение, но могу обрабатывать только текстовые запросы.")
            bot.send_message(message.chat.id, response)
            return
        
        if message.content_type == 'text':
            access_level = check_user_access(user_id)
            if access_level == 'admin':
                bot.send_message(message.chat.id, "<b>ℹ️ Для общения с ИИ нажмите кнопку '🤖 ИИ-помощник'</b>")
                show_admin_menu(message)
            elif access_level == 'platon':
                bot.send_message(message.chat.id, "<b>ℹ️ Для общения с ИИ нажмите кнопку '🤖 ИИ-помощник'</b>")
                show_platon_menu(message)
            else:
                bot.send_message(message.chat.id, "<b>ℹ️ Для общения с ИИ нажмите кнопку '🤖 ИИ-помощник'</b>")
                show_guest_menu(message)

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
                save_chat_to_db(user_id, chat.id, chat.title, getattr(chat, 'username', None), chat.type)
                
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
            bot.send_message(platon_id, message.text)
            log_event("SEND_TO_PLATON", user_id, f"To: {platon_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки Платону {platon_id}: {e}")
            log_event("SEND_TO_PLATON_ERROR", user_id, f"To: {platon_id}, Error: {str(e)}")
    
    bot.send_message(message.chat.id,
                    f"<b>✅ Сообщение отправлено Платону</b>")

def process_delayed_platon(message):
    """Обработка отложенной отправки Платону"""
    user_id = message.from_user.id
    platon_ids = get_platon_users()
    
    if not platon_ids:
        bot.send_message(message.chat.id, "<b>❌ Пользователь Платон не найден.</b>")
        return
    
    delay_seconds = user_temp_data.get(user_id, {}).get("delay", 0)
    
    if delay_seconds > 0:
        task_id = add_delayed_task(
            task_type="platon_message",
            target_id=platon_ids[0],
            message=message.text,
            delay_seconds=delay_seconds,
            user_id=user_id
        )
        
        delay_text = ""
        if delay_seconds == 60:
            delay_text = "через 1 минуту"
        elif delay_seconds == 300:
            delay_text = "через 5 минут"
        elif delay_seconds == 600:
            delay_text = "через 10 минут"
        elif delay_seconds == 1800:
            delay_text = "через 30 минут"
        
        bot.send_message(message.chat.id,
                        f"<b>✅ Сообщение будет отправлено Платону {delay_text}</b>\n\n"
                        f"ID задачи: <code>{task_id}</code>")
    else:
        send_to_platon(message)

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
    """Обработка массовой EMAIL рассылки"""
    broadcast_message = message.text
    emails = get_all_emails()
    delay_seconds = user_temp_data.get(message.from_user.id, {}).get("delay", 0)
    
    if delay_seconds > 0:
        task_id = add_delayed_task(
            task_type="email_broadcast",
            target_id=emails,
            message=broadcast_message,
            delay_seconds=delay_seconds,
            user_id=message.from_user.id
        )
        
        delay_text = ""
        if delay_seconds == 60:
            delay_text = "через 1 минуту"
        elif delay_seconds == 300:
            delay_text = "через 5 минут"
        elif delay_seconds == 600:
            delay_text = "через 10 минут"
        elif delay_seconds == 1800:
            delay_text = "через 30 минут"
        
        bot.send_message(message.chat.id,
                        f"<b>✅ Рассылка будет отправлена {delay_text}</b>\n\n"
                        f"Получателей: {len(emails)}\n"
                        f"ID задачи: <code>{task_id}</code>")
    else:
        bot.send_message(message.chat.id, 
                        f"<b>📧 Начинаю EMAIL рассылку...</b>\n\n"
                        f"Сообщение: {broadcast_message[:50]}...\n"
                        f"Количество получателей: {len(emails)}")
        
        success_count = 0
        fail_count = 0
        
        for email in emails:
            if send_email(email, "Новости от E-Genius AI", broadcast_message):
                success_count += 1
            else:
                fail_count += 1
            time.sleep(1)
        
        bot.send_message(message.chat.id,
                        f"<b>✅ EMAIL рассылка завершена!</b>\n\n"
                        f"Успешно отправлено: {success_count}\n"
                        f"Не удалось отправить: {fail_count}")

def process_selective_email(message):
    """Обработка выборочной email рассылки"""
    user_id = message.from_user.id
    
    if user_id not in user_selected_emails or not user_selected_emails[user_id]:
        bot.send_message(message.chat.id, "<b>❌ Не выбрано ни одного email адреса.</b>")
        return
    
    selected_emails = user_selected_emails[user_id]
    delay_seconds = user_temp_data.get(user_id, {}).get("delay", 0)
    
    if delay_seconds > 0:
        task_id = add_delayed_task(
            task_type="email_broadcast",
            target_id=selected_emails,
            message=message.text,
            delay_seconds=delay_seconds,
            user_id=user_id
        )
        
        delay_text = ""
        if delay_seconds == 60:
            delay_text = "через 1 минуту"
        elif delay_seconds == 300:
            delay_text = "через 5 минут"
        elif delay_seconds == 600:
            delay_text = "через 10 минут"
        elif delay_seconds == 1800:
            delay_text = "через 30 минут"
        
        bot.send_message(message.chat.id,
                        f"<b>✅ Выборочная рассылка будет отправлена {delay_text}</b>\n\n"
                        f"Получателей: {len(selected_emails)}\n"
                        f"ID задачи: <code>{task_id}</code>")
    else:
        bot.send_message(message.chat.id, 
                        f"<b>📧 Начинаю выборочную рассылку...</b>\n\n"
                        f"Получателей: {len(selected_emails)}")
        
        success_count = 0
        fail_count = 0
        
        for email in selected_emails:
            if send_email(email, "Новости от E-Genius AI", message.text):
                success_count += 1
            else:
                fail_count += 1
            time.sleep(1)
        
        bot.send_message(message.chat.id,
                        f"<b>✅ Выборочная рассылка завершена!</b>\n\n"
                        f"Успешно отправлено: {success_count}\n"
                        f"Не удалось отправить: {fail_count}")
    
    if user_id in user_selected_emails:
        del user_selected_emails[user_id]
    if user_id in user_temp_data:
        del user_temp_data[user_id]

def process_set_channel(message):
    """Обработка установки ID канала"""
    try:
        channel_id = int(message.text.strip())
        save_setting("channel_id", str(channel_id))
        bot.send_message(message.chat.id, f"<b>✅ ID канала установлен: {channel_id}</b>")
    except ValueError:
        bot.send_message(message.chat.id, "<b>❌ Неверный формат ID. Введите числовой ID.</b>")
        user_waiting_for_input[message.from_user.id] = 'set_channel_id'

def show_guest_menu(message_or_user_id):
    """Меню гостя"""
    if isinstance(message_or_user_id, int):
        user_id = message_or_user_id
        chat_id = user_id
    else:
        user_id = message_or_user_id.from_user.id
        chat_id = message_or_user_id.chat.id
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_auth = types.KeyboardButton("🔐 Войти в систему")
    btn_email = types.KeyboardButton("📧 Добавить email")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    btn_ermak = types.KeyboardButton("👍ERMAK APP")
    markup.add(btn_auth, btn_email, btn_ai, btn_stop_ai, btn_ermak)
    
    welcome_text = f"""<b>{BOT_NAME}</b>

<b>Доступные функции:</b>
✅ ИИ-помощник (безлимитно)
✅ Добавление email для уведомлений
✅ Авторизация для доступа к админским функциям
✅ 👍 Открытие веб-приложения ERMAK

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(chat_id, welcome_text, reply_markup=markup)

def show_admin_menu(message):
    """Меню админа"""
    user_id = message.from_user.id
    platon_app_enabled = is_platon_app_enabled()
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_pc = types.KeyboardButton("🖥️ Управление ПК")
    btn_send = types.KeyboardButton("📤 Отправить сообщение")
    btn_chats = types.KeyboardButton("📋 Мои чаты и каналы")
    btn_email = types.KeyboardButton("📧 Массовая рассылка")
    btn_emails = types.KeyboardButton("👥 Управление email")
    btn_platon = types.KeyboardButton("Платон🙌")
    btn_broadcast = types.KeyboardButton("📢 Рассылка пользователям")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    btn_settings = types.KeyboardButton("⚙️ Настройки")
    btn_ermak = types.KeyboardButton("👍ERMAK APP")
    
    if platon_app_enabled:
        btn_max_app = types.KeyboardButton("🙌MAX_APP")
        markup.add(btn_pc, btn_send, btn_chats, btn_email, btn_emails, 
                   btn_platon, btn_broadcast, btn_ai, btn_stop_ai, btn_settings, 
                   btn_ermak, btn_max_app)
    else:
        markup.add(btn_pc, btn_send, btn_chats, btn_email, btn_emails, 
                   btn_platon, btn_broadcast, btn_ai, btn_stop_ai, btn_settings, btn_ermak)
    
    welcome_text = f"""<b>{BOT_NAME} - Панель администратора</b>

<b>Доступные функции:</b>
✅ 🖥️ Управление ПК (выключение, перезагрузка, скриншоты и т.д.)
✅ 📤 Отправка сообщений в Telegram чаты/каналы
✅ 📧 Массовая EMAIL рассылка (с отложенной отправкой)
✅ 👥 Управление email адресами (всех пользователей)
✅ Платон🙌 Управление пользователем Платон (с отложенной отправкой)
✅ 📢 Рассылка всем пользователям бота (Telegram)
✅ 🤖 ИИ-помощник
✅ ⏸️ Остановить ИИ
✅ ⚙️ Настройки бота
✅ 👍 Открытие веб-приложения ERMAK"""
    
    if platon_app_enabled:
        welcome_text += "\n✅ 🙌 Открытие веб-приложения MAX (только для вас)"
    
    welcome_text += "\n\n<b>Выберите действие из меню ниже 👇</b>"
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

def show_platon_menu(message_or_user_id):
    """Меню Платона (УДАЛЕНА КНОПКА ERMAK APP)"""
    if isinstance(message_or_user_id, int):
        user_id = message_or_user_id
        chat_id = user_id
    else:
        user_id = message_or_user_id.from_user.id
        chat_id = message_or_user_id.chat.id
    
    platon_app_enabled = is_platon_app_enabled()
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    btn_email = types.KeyboardButton("📧 Мои email")
    # Кнопка ERMAK APP УДАЛЕНА для Платона
    
    if platon_app_enabled:
        btn_max_app = types.KeyboardButton("🙌MAX_APP")
        markup.add(btn_ai, btn_stop_ai, btn_email, btn_max_app)
    else:
        markup.add(btn_ai, btn_stop_ai, btn_email)
    
    welcome_text = f"""<b>Приветствуем вас, Платон Бердников!</b>

<b>Доступные функции:</b>
✅ ИИ-помощник для ответов на вопросы (безлимитно)
✅ ⏸️ Остановить ИИ
✅ Просмотр email адресов"""
    # Упоминание ERMAK APP УДАЛЕНО
    
    if platon_app_enabled:
        welcome_text += "\n✅ 🙌 Открытие веб-приложения MAX"
    else:
        welcome_text += "\n⛔ 🙌 Веб-приложение MAX временно отключено"
    
    welcome_text += "\n\n<b>Выберите действие из меню ниже 👇</b>"
    
    bot.send_message(chat_id, welcome_text, reply_markup=markup)

# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"🚀 Запуск E-Genius AI")
    print(f"{'=' * 60}")
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Файл {CREDENTIALS_FILE} не найден!")
        print("   Скачайте файл client_secrets.json с Google Cloud Console")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    if not initialize_system():
        print("❌ Критическая ошибка инициализации!")
        input("Нажмите Enter для выхода...")
        sys.exit(1)
    
    setup_bot_handlers()
    
    restore_delayed_tasks()
    
    # Очищаем просроченные токены при запуске
    expired_count = cleanup_expired_tokens()
    if expired_count > 0:
        print(f"✅ Очищено {expired_count} просроченных токенов")
    
    # Запускаем проверку скриншотов в отдельном потоке
    def screenshot_checker():
        """Проверяет новые скриншоты каждые 30 секунд"""
        while True:
            try:
                auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
                admins = [user["user_id"] for user in auth_data.get("users", []) 
                         if user["user_type"] == "admin"]
                
                for admin_id in admins:
                    check_screenshots(admin_id)
                
                time.sleep(30)
            except Exception as e:
                print(f"Ошибка в проверке скриншотов: {e}")
                time.sleep(30)
    
    threading.Thread(target=screenshot_checker, daemon=True).start()
    
    # Запускаем очистку токенов каждые 6 часов
    def token_cleanup_scheduler():
        """Очищает просроченные токены каждые 6 часов"""
        while True:
            try:
                time.sleep(6 * 3600)  # 6 часов
                expired_count = cleanup_expired_tokens()
                if expired_count > 0:
                    print(f"🔄 Автоматическая очистка: удалено {expired_count} просроченных токенов")
            except Exception as e:
                print(f"Ошибка в планировщике очистки токенов: {e}")
    
    threading.Thread(target=token_cleanup_scheduler, daemon=True).start()
    
    print(f"\n{'=' * 60}")
    print("🎯 ОСНОВНЫЕ ФУНКЦИИ БОТА:")
    print("   1. 🔐 Авторизация по паролю (админ/Платон)")
    print("   2. 📧 Управление email адресами")
    print("   3. 🤖 ИИ-помощник (бесплатно для всех)")
    print("   4. ⏸️ Остановить ИИ")
    print("   5. 👍 Открытие веб-приложения ERMAK (кроме Платона)")
    print("   6. 🙌 Открытие веб-приложения MAX (только Платон)")
    print("   7. 📢 Рассылка всем пользователям бота (Telegram)")
    print("   8. 📧 Массовая EMAIL рассылка (всем/выборочно)")
    print("   9. 📤 Отправка сообщений в Telegram чаты/каналы")
    print("   10. 👥 Управление email (админ)")
    print("   11. ⚙️ Настройки бота (админ)")
    print("   12. 🖥️ Управление ПК (админ)")
    print("   13. ⏰ Отложенная отправка сообщений Платону")
    print("   14. ⏰ Отложенная EMAIL рассылка")
    print("   15. 🔒 Защищенный доступ к веб-приложению MAX")
    print("   16. 💾 Все данные в Google Drive")
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