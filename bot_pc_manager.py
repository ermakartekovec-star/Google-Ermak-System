# bot_pc_manager.py
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
SCREENSHOTS_FOLDER = "Screenshots"
PC_COMMANDS_FILE = "pc_commands.json"
PC_STATUS_FILE = "pc_status.json"
EXECUTED_COMMANDS_FILE = "executed_commands.json"
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
pc_selection_data = {}  # Данные для выбора ПК

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

def get_or_create_folder(service, folder_name, parent_id=None):
    """Находит или создает папку в Google Drive"""
    try:
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = service.files().list(q=query, fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        if folders:
            print(f"✅ Папка найдена: {folders[0]['id']}")
            return folders[0]['id']
        else:
            # Создаем папку
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                folder_metadata['parents'] = [parent_id]
            
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            print(f"✅ Папка создана: {folder.get('id')}")
            return folder.get('id')
    except Exception as e:
        print(f"❌ Ошибка поиска/создания папки: {e}")
        return None

def save_file_to_drive(service, file_name, content, folder_id, mime_type='application/json'):
    """Сохраняет файл в Google Drive"""
    try:
        # Ищем файл
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
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
        # Ищем файл
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
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
        save_file_to_drive(service, filename, content, GOOGLE_DRIVE_FOLDER_ID)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения файла {filename}: {e}")
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

def save_pc_status(status_data):
    """Сохраняет статус ПК"""
    return save_json_file(PC_STATUS_FILE, status_data)

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
    
    # Получаем все файлы в папке скриншотов
    query = f"'{SCREENSHOTS_FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields='files(id, name, mimeType, createdTime)').execute()
    files = results.get('files', [])
    
    screenshots_sent = []
    
    for file in files:
        # Проверяем, является ли файл изображением
        if file['mimeType'].startswith('image/'):
            filename = file['name']
            
            # Проверяем метаданные
            meta_filename = f"{filename}.meta.json"
            meta_content = load_file_from_drive(service, meta_filename, SCREENSHOTS_FOLDER_ID)
            
            if meta_content:
                try:
                    metadata = json.loads(meta_content)
                    
                    # Если скриншот новый и не отправлен этому пользователю
                    if metadata.get('status') == 'new':
                        # Скачиваем изображение
                        request = service.files().get_media(fileId=file['id'])
                        image_content = io.BytesIO()
                        downloader = MediaIoBaseDownload(image_content, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                        
                        # Отправляем пользователю
                        image_content.seek(0)
                        
                        # Определяем тип контента
                        if filename.endswith('.png'):
                            bot.send_photo(user_id, image_content, 
                                         caption=f"📸 Скриншот от {metadata.get('pc_id', 'Unknown')}\n"
                                                f"📅 {metadata.get('created_at', 'Unknown')}")
                        else:
                            bot.send_document(user_id, image_content, 
                                            caption=f"📸 Скриншот от {metadata.get('pc_id', 'Unknown')}")
                        
                        # Обновляем статус
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
        
        # Создаем пример конфигурации
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
    query = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields='files(id, name)').execute()
    folders = results.get('files', [])
    
    if folders:
        GOOGLE_DRIVE_FOLDER_ID = folders[0]['id']
    else:
        # Создаем папку
        folder_metadata = {
            'name': FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        GOOGLE_DRIVE_FOLDER_ID = folder.get('id')
    
    print(f"✅ Папка: https://drive.google.com/drive/folders/{GOOGLE_DRIVE_FOLDER_ID}")
    
    # Получаем или создаем папку для скриншотов
    global SCREENSHOTS_FOLDER_ID
    SCREENSHOTS_FOLDER_ID = get_or_create_folder(service, SCREENSHOTS_FOLDER, GOOGLE_DRIVE_FOLDER_ID)
    
    # Загружаем конфигурацию
    if not load_config_from_drive():
        print("❌ Не удалось загрузить конфигурацию")
        return False
    
    # Создаем начальные файлы если их нет
    initial_files = [
        (PC_COMMANDS_FILE, {"commands": []}),
        (PC_STATUS_FILE, []),
        (EMAILS_FILE, {"emails": []}),
        (AUTH_USERS_FILE, {"users": []}),
        (SETTINGS_FILE, {"settings": {}})
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
        
        # Сбрасываем режим ИИ при старте
        if user_id in ai_mode_active:
            del ai_mode_active[user_id]
        
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
        
        # Включаем режим ИИ
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
            types.InlineKeyboardButton("🔊 Громкость +", callback_data="pc_volume_up"),
            types.InlineKeyboardButton("🔈 Громкость -", callback_data="pc_volume_down"),
            types.InlineKeyboardButton("🔇 Отключить звук", callback_data="pc_volume_mute"),
            types.InlineKeyboardButton("⏯️ Воспр./Пауза", callback_data="pc_media_play_pause"),
            types.InlineKeyboardButton("⏹️ Остановить", callback_data="pc_media_stop"),
            types.InlineKeyboardButton("⏭️ Следующий", callback_data="pc_media_next"),
            types.InlineKeyboardButton("⏮️ Предыдущий", callback_data="pc_media_previous"),
            types.InlineKeyboardButton("📊 Статус ПК", callback_data="pc_status"),
            types.InlineKeyboardButton("🔄 Проверить скриншоты", callback_data="pc_check_screenshots"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="pc_back")
        ]
        
        # Добавляем кнопки по 2 в ряд
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                markup.add(buttons[i], buttons[i+1])
            else:
                markup.add(buttons[i])
        
        # Получаем список доступных ПК
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
        
        # Обработка команд ПК
        if call.data.startswith("pc_"):
            access_level = check_user_access(user_id)
            
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
            
            elif call.data == "pc_volume_up":
                show_pc_selection(call, "volume_up", "🔊 Выберите ПК для увеличения громкости:")
            
            elif call.data == "pc_volume_down":
                show_pc_selection(call, "volume_down", "🔈 Выберите ПК для уменьшения громкости:")
            
            elif call.data == "pc_volume_mute":
                show_pc_selection(call, "volume_mute", "🔇 Выберите ПК для отключения звука:")
            
            elif call.data == "pc_media_play_pause":
                show_pc_selection(call, "media_play_pause", "⏯️ Выберите ПК для воспроизведения/паузы:")
            
            elif call.data == "pc_media_stop":
                show_pc_selection(call, "media_stop", "⏹️ Выберите ПК для остановки воспроизведения:")
            
            elif call.data == "pc_media_next":
                show_pc_selection(call, "media_next", "⏭️ Выберите ПК для следующего трека:")
            
            elif call.data == "pc_media_previous":
                show_pc_selection(call, "media_previous", "⏮️ Выберите ПК для предыдущего трека:")
            
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
            
            elif call.data == "pc_check_screenshots":
                sent_screenshots = check_screenshots(user_id)
                
                if sent_screenshots:
                    bot.answer_callback_query(call.id, f"✅ Отправлено {len(sent_screenshots)} скриншотов")
                else:
                    bot.answer_callback_query(call.id, "❌ Новых скриншотов нет")
            
            elif call.data == "pc_back":
                bot.delete_message(call.message.chat.id, call.message.message_id)
                show_admin_menu(call.message)
            
            elif call.data == "pc_cancel":
                bot.delete_message(call.message.chat.id, call.message.message_id)
                show_admin_menu(call.message)
            
            # Обработка выбора конкретного ПК
            elif call.data.startswith("pc_select_"):
                parts = call.data.split("_")
                if len(parts) >= 4:
                    command_type = parts[2]
                    pc_id = "_".join(parts[3:])  # На случай если в ID есть подчеркивания
                    
                    # Отправляем команду
                    if send_pc_command(pc_id, command_type, user_id):
                        # Получаем информацию о ПК
                        pcs = get_available_pcs()
                        pc_info = next((pc for pc in pcs if pc.get('pc_id') == pc_id), {})
                        
                        command_names = {
                            'shutdown': 'завершение работы',
                            'restart': 'перезагрузка',
                            'sleep': 'спящий режим',
                            'hibernate': 'гибернация',
                            'lock': 'блокировка',
                            'screenshot': 'скриншот',
                            'volume_up': 'увеличение громкости',
                            'volume_down': 'уменьшение громкости',
                            'volume_mute': 'отключение звука',
                            'media_play_pause': 'воспроизведение/пауза',
                            'media_stop': 'остановка воспроизведения',
                            'media_next': 'следующий трек',
                            'media_previous': 'предыдущий трек'
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
    
    # ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ==========
    @bot.message_handler(content_types=['text'], func=lambda message: message.chat.type == 'private')
    def handle_private_text(message):
        """Обработчик текстовых сообщений"""
        user_id = message.from_user.id
        
        # Проверяем, ожидает ли пользователь ввода
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
        
        # Проверяем, активирован ли режим ИИ
        if user_id in ai_mode_active and ai_mode_active[user_id]:
            # Обработка запроса к ИИ
            bot.send_chat_action(user_id, 'typing')
            response = ask_openrouter(message.text)
            bot.send_message(message.chat.id, response)
            return
        
        # Проверяем, является ли это кнопкой меню
        menu_buttons = [
            "🔐 Войти в систему", "📧 Добавить email", "🖥️ Управление ПК",
            "📤 Отправить сообщение", "📋 Мои чаты и каналы", "📧 Массовая рассылка",
            "👥 Управление email", "Платон🙌", "📢 Рассылка пользователям",
            "🤖 ИИ-помощник", "⏸️ Остановить ИИ", "📧 Мои email", "⚙️ Настройки"
        ]
        
        if message.text.strip() in menu_buttons:
            return
        
        # Если это обычное текстовое сообщение и не ИИ режим
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

def show_guest_menu(message):
    """Меню гостя"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_auth = types.KeyboardButton("🔐 Войти в систему")
    btn_email = types.KeyboardButton("📧 Добавить email")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    markup.add(btn_auth, btn_email, btn_ai, btn_stop_ai)
    
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
    btn_pc_control = types.KeyboardButton("🖥️ Управление ПК")
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    markup.add(btn_pc_control, btn_ai, btn_stop_ai)
    
    welcome_text = f"""<b>{BOT_NAME} - Панель администратора</b>

<b>Доступные функции:</b>
✅ 🖥️ Управление ПК (выключение, скриншоты, управление медиа и т.д.)
✅ 🤖 ИИ-помощник
✅ ⏸️ Остановить ИИ

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

def show_platon_menu(message):
    """Меню Платона"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_ai = types.KeyboardButton("🤖 ИИ-помощник")
    btn_stop_ai = types.KeyboardButton("⏸️ Остановить ИИ")
    btn_email = types.KeyboardButton("📧 Мои email")
    markup.add(btn_ai, btn_stop_ai, btn_email)
    
    welcome_text = f"""<b>Приветствуем вас, Платон Бердников!</b>

<b>Доступные функции:</b>
✅ ИИ-помощник для ответов на вопросы (безлимитно)
✅ ⏸️ Остановить ИИ
✅ Просмотр email адресов

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"🚀 Запуск Google Ermak System с управлением ПК")
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
    print("   1. 🖥️ Управление ПК через Google Drive")
    print("   2. 🤖 ИИ-помощник (бесплатно для всех)")
    print("   3. ⏸️ Остановить ИИ")
    print("   4. 🔐 Авторизация по паролю")
    print("   5. 📧 Управление email")
    print("   6. 💾 Все данные в Google Drive")
    print(f"{'=' * 60}")
    print("⚡ Бот запущен и готов к работе!")
    print("   Для начала работы напишите /start в Telegram")
    print("=" * 60)
    
    # Запускаем проверку скриншотов в отдельном потоке
    def screenshot_checker():
        """Проверяет новые скриншоты каждые 30 секунд"""
        while True:
            try:
                # Получаем всех админов
                auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
                admins = [user["user_id"] for user in auth_data.get("users", []) 
                         if user["user_type"] == "admin"]
                
                for admin_id in admins:
                    check_screenshots(admin_id)
                
                time.sleep(30)  # Проверяем каждые 30 секунд
            except Exception as e:
                print(f"Ошибка в проверке скриншотов: {e}")
                time.sleep(30)
    
    # Запускаем проверку скриншотов в отдельном потоке
    threading.Thread(target=screenshot_checker, daemon=True).start()
    
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