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
import hashlib
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
COMMANDS_FILE = "pc_commands.json"
LOGS_FILE = "bot_logs.json"

# Инициализация бота
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
user_waiting_for_input = {}
ai_mode_active = {}
last_screenshots_check = {}
screenshots_folder_id = None

# Защита от повторного выполнения
command_cooldowns = {}  # Хранит время последней команды для пользователя
executed_commands_cache = set()  # Кэш выполненных команд
COMMAND_COOLDOWN_TIME = 30  # 30 секунд между одинаковыми командами

# Единственная модель
AI_MODEL = "allenai/molmo-2-8b:free"

# ========== УЛУЧШЕННОЕ ЛОГГИРОВАНИЕ ==========
class EnhancedLogger:
    def __init__(self):
        self.log_buffer = []
        self.log_lock = threading.Lock()
        self.max_buffer_size = 50
        
    def log_event(self, event_type, user_id, user_info=None, details="", action="", target=""):
        """Детальное логирование событий"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        if not user_info:
            try:
                if bot:
                    user = bot.get_chat(user_id)
                    user_info = {
                        "id": user_id,
                        "first_name": user.first_name or "",
                        "last_name": user.last_name or "",
                        "username": user.username or "",
                        "type": "user"
                    }
            except:
                user_info = {"id": user_id, "type": "unknown"}
        
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "user": user_info,
            "details": details,
            "action": action,
            "target": target,
            "bot_state": {
                "ai_mode_active": bool(ai_mode_active.get(user_id)),
                "waiting_for_input": user_waiting_for_input.get(user_id, "")
            }
        }
        
        # Вывод в консоль
        console_msg = f"[{timestamp}] [{event_type}] "
        if user_info.get("username"):
            console_msg += f"@{user_info['username']} "
        if user_info.get("first_name"):
            console_msg += f"{user_info['first_name']} "
        if action:
            console_msg += f"Action: {action} "
        if details:
            console_msg += f"- {details}"
        
        print(console_msg)
        
        # Сохранение в буфер
        with self.log_lock:
            self.log_buffer.append(log_entry)
            if len(self.log_buffer) > self.max_buffer_size:
                self.flush_logs_to_drive()
        
        return log_entry
    
    def flush_logs_to_drive(self):
        """Отправляет логи в Google Drive"""
        if not self.log_buffer:
            return
        
        with self.log_lock:
            # Загружаем существующие логи
            existing_logs = load_json_file(LOGS_FILE, {"logs": []})
            if not isinstance(existing_logs, dict) or "logs" not in existing_logs:
                existing_logs = {"logs": []}
            
            # Добавляем новые логи
            existing_logs["logs"].extend(self.log_buffer)
            
            # Ограничиваем размер (сохраняем последние 10000 записей)
            if len(existing_logs["logs"]) > 10000:
                existing_logs["logs"] = existing_logs["logs"][-10000:]
            
            # Сохраняем обратно
            save_json_file(LOGS_FILE, existing_logs)
            
            # Очищаем буфер
            self.log_buffer = []
    
    def get_recent_logs(self, count=50):
        """Получает последние логи"""
        logs_data = load_json_file(LOGS_FILE, {"logs": []})
        if isinstance(logs_data, dict) and "logs" in logs_data:
            return logs_data["logs"][-count:]
        return []

logger = EnhancedLogger()

# ========== GOOGLE DRIVE ФУНКЦИИ ==========
def get_drive_service():
    """Создает сервис для работы с Google Drive"""
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
            logger.log_event("DRIVE_TOKEN_LOADED", 0, {"type": "system"}, "Токен Google Drive загружен")
        except Exception as e:
            logger.log_event("DRIVE_TOKEN_ERROR", 0, {"type": "system"}, f"Ошибка загрузки токена: {e}")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.log_event("DRIVE_TOKEN_REFRESH", 0, {"type": "system"}, "Обновляю токен Google Drive...")
                creds.refresh(Request())
                logger.log_event("DRIVE_TOKEN_REFRESHED", 0, {"type": "system"}, "Токен обновлен")
            except Exception as e:
                logger.log_event("DRIVE_TOKEN_REFRESH_ERROR", 0, {"type": "system"}, f"Ошибка обновления токена: {e}")
                creds = None
        
        if not creds:
            try:
                logger.log_event("DRIVE_AUTH_REQUEST", 0, {"type": "system"}, "Запрашиваю авторизацию Google Drive...")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True)
                logger.log_event("DRIVE_AUTH_SUCCESS", 0, {"type": "system"}, "Авторизация успешна")
            except Exception as e:
                logger.log_event("DRIVE_AUTH_ERROR", 0, {"type": "system"}, f"Ошибка авторизации: {e}")
                return None
            
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
                logger.log_event("DRIVE_TOKEN_SAVED", 0, {"type": "system"}, "Токен сохранен")
    
    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.log_event("DRIVE_SERVICE_ERROR", 0, {"type": "system"}, f"Ошибка создания сервиса: {e}")
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
            logger.log_event("DRIVE_FOLDER_FOUND", 0, {"type": "system"}, f"Папка найдена: {GOOGLE_DRIVE_FOLDER_ID}")
            return GOOGLE_DRIVE_FOLDER_ID
        else:
            # Создаем папку
            folder_metadata = {
                'name': FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            GOOGLE_DRIVE_FOLDER_ID = folder.get('id')
            logger.log_event("DRIVE_FOLDER_CREATED", 0, {"type": "system"}, f"Папка создана: {GOOGLE_DRIVE_FOLDER_ID}")
            return GOOGLE_DRIVE_FOLDER_ID
    except Exception as e:
        logger.log_event("DRIVE_FOLDER_ERROR", 0, {"type": "system"}, f"Ошибка поиска/создания папки: {e}")
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
            logger.log_event("DRIVE_FILE_UPDATED", 0, {"type": "system"}, f"Файл обновлен: {file_name}")
            return file_id
        else:
            # Создаем файл
            file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            logger.log_event("DRIVE_FILE_CREATED", 0, {"type": "system"}, f"Файл создан: {file_name}")
            return file.get('id')
    except Exception as e:
        logger.log_event("DRIVE_FILE_SAVE_ERROR", 0, {"type": "system"}, f"Ошибка сохранения файла {file_name}: {e}")
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
            logger.log_event("DRIVE_BINARY_UPDATED", 0, {"type": "system"}, f"Бинарный файл обновлен: {file_name}")
            return file_id
        else:
            # Создаем файл
            file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
            media = MediaIoBaseUpload(io.BytesIO(binary_content), mimetype=mime_type)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            logger.log_event("DRIVE_BINARY_CREATED", 0, {"type": "system"}, f"Бинарный файл создан: {file_name}")
            return file.get('id')
    except Exception as e:
        logger.log_event("DRIVE_BINARY_SAVE_ERROR", 0, {"type": "system"}, f"Ошибка сохранения бинарного файла {file_name}: {e}")
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
            
            logger.log_event("DRIVE_FILE_LOADED", 0, {"type": "system"}, f"Файл загружен: {file_name}")
            return file_content.getvalue().decode('utf-8')
        return None
    except Exception as e:
        logger.log_event("DRIVE_FILE_LOAD_ERROR", 0, {"type": "system"}, f"Ошибка загрузки файла {file_name}: {e}")
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
            
            logger.log_event("DRIVE_BINARY_LOADED", 0, {"type": "system"}, f"Бинарный файл загружен: {file_name}")
            return file_content.getvalue()
        return None
    except Exception as e:
        logger.log_event("DRIVE_BINARY_LOAD_ERROR", 0, {"type": "system"}, f"Ошибка загрузки бинарного файла {file_name}: {e}")
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
        logger.flush_logs_to_drive()  # Сохраняем логи при каждом сохранении JSON
        return True
    except Exception as e:
        logger.log_event("JSON_SAVE_ERROR", 0, {"type": "system"}, f"Ошибка сохранения файла {filename}: {e}")
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
        logger.log_event("DATABASE_SAVE_ERROR", 0, {"type": "system"}, f"Ошибка сохранения базы данных: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ ПК ==========
def get_or_create_screenshots_folder(service):
    """Создает папку для скриншотов"""
    global screenshots_folder_id
    
    try:
        # Ищем папку
        query = f"name='Screenshots_PC' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        if folders:
            screenshots_folder_id = folders[0]['id']
            return screenshots_folder_id
        else:
            # Создаем папку
            folder_metadata = {
                'name': 'Screenshots_PC',
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [GOOGLE_DRIVE_FOLDER_ID]
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            screenshots_folder_id = folder.get('id')
            return screenshots_folder_id
    except Exception as e:
        logger.log_event("SCREENSHOTS_FOLDER_ERROR", 0, {"type": "system"}, f"Ошибка создания папки скриншотов: {e}")
        return None

def generate_command_hash(user_id, command_type, params=None):
    """Генерирует уникальный хеш для команды"""
    command_string = f"{user_id}_{command_type}_{json.dumps(params or {}, sort_keys=True)}"
    return hashlib.md5(command_string.encode()).hexdigest()

def is_command_in_cooldown(user_id, command_hash):
    """Проверяет, находится ли команда в кулдауне"""
    current_time = time.time()
    key = f"{user_id}_{command_hash}"
    
    if key in command_cooldowns:
        last_time = command_cooldowns[key]
        if current_time - last_time < COMMAND_COOLDOWN_TIME:
            return True
    
    command_cooldowns[key] = current_time
    return False

def is_command_already_executed(command_hash):
    """Проверяет, была ли команда уже выполнена"""
    return command_hash in executed_commands_cache

def save_pc_command(user_id, command_type, params=None):
    """Сохраняет команду для ПК с защитой от повторного выполнения"""
    try:
        # Генерируем уникальный хеш команды
        command_hash = generate_command_hash(user_id, command_type, params)
        
        # Проверяем кулдаун
        if is_command_in_cooldown(user_id, command_hash):
            logger.log_event("PC_COMMAND_COOLDOWN", user_id,
                           action="command_cooldown",
                           details=f"Command {command_type} is in cooldown")
            return None
        
        # Загружаем существующие команды
        commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
        
        if not isinstance(commands_data, dict):
            commands_data = {"commands": [], "last_id": 0}
        
        # Проверяем, нет ли уже такой же невыполненной команды
        pending_commands = [
            cmd for cmd in commands_data.get("commands", [])
            if cmd.get("status") == "pending"
            and cmd.get("command_hash") == command_hash
        ]
        
        if pending_commands:
            logger.log_event("PC_COMMAND_DUPLICATE", user_id,
                           action="duplicate_command",
                           details=f"Command {command_type} already pending")
            return None
        
        # Создаем новую команду
        command_id = commands_data.get("last_id", 0) + 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        command = {
            "id": command_id,
            "user_id": user_id,
            "command_type": command_type,
            "params": params or {},
            "timestamp": timestamp,
            "status": "pending",
            "executed_at": None,
            "result": None,
            "command_hash": command_hash,
            "retry_count": 0
        }
        
        commands_data["commands"].append(command)
        commands_data["last_id"] = command_id
        
        # Ограничиваем количество хранимых команд
        max_commands = 100
        if len(commands_data["commands"]) > max_commands:
            commands_data["commands"] = commands_data["commands"][-max_commands:]
        
        save_json_file(COMMANDS_FILE, commands_data)
        
        logger.log_event(
            "PC_COMMAND_CREATED", 
            user_id, 
            action=f"create_pc_command", 
            details=f"Command: {command_type}, Hash: {command_hash}", 
            target="PC"
        )
        
        return command_id
    except Exception as e:
        logger.log_event("PC_COMMAND_SAVE_ERROR", user_id, action="save_pc_command", details=f"Error: {e}")
        return None

def get_pending_commands():
    """Получает все ожидающие команды"""
    commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
    
    if not isinstance(commands_data, dict) or "commands" not in commands_data:
        return []
    
    pending_commands = [cmd for cmd in commands_data["commands"] if cmd["status"] == "pending"]
    return pending_commands

def mark_command_executed(command_id, result="success"):
    """Отмечает команду как выполненную"""
    try:
        commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
        
        if not isinstance(commands_data, dict) or "commands" not in commands_data:
            return False
        
        for cmd in commands_data["commands"]:
            if cmd["id"] == command_id:
                cmd["status"] = "executed"
                cmd["executed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cmd["result"] = result
                
                # Добавляем в кэш выполненных команд
                if "command_hash" in cmd:
                    executed_commands_cache.add(cmd["command_hash"])
                
                break
        
        save_json_file(COMMANDS_FILE, commands_data)
        
        # Логируем выполнение
        logger.log_event(
            "PC_COMMAND_EXECUTED", 
            0, 
            {"type": "system"}, 
            action="execute_pc_command", 
            details=f"Command ID: {command_id}, Result: {result}"
        )
        
        return True
    except Exception as e:
        logger.log_event("PC_COMMAND_MARK_ERROR", 0, {"type": "system"}, action="mark_command", details=f"Error: {e}")
        return False

def mark_command_failed(command_id, error_message):
    """Отмечает команду как неудачную"""
    try:
        commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
        
        if not isinstance(commands_data, dict) or "commands" not in commands_data:
            return False
        
        for cmd in commands_data["commands"]:
            if cmd["id"] == command_id:
                cmd["status"] = "failed"
                cmd["executed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cmd["result"] = f"error: {error_message}"
                cmd["retry_count"] = cmd.get("retry_count", 0) + 1
                break
        
        save_json_file(COMMANDS_FILE, commands_data)
        
        logger.log_event(
            "PC_COMMAND_FAILED", 
            0, 
            {"type": "system"}, 
            action="command_failed", 
            details=f"Command ID: {command_id}, Error: {error_message}"
        )
        
        return True
    except Exception as e:
        logger.log_event("PC_COMMAND_FAIL_ERROR", 0, {"type": "system"}, action="mark_failed", details=f"Error: {e}")
        return False

def check_new_screenshots():
    """Проверяет новые скриншоты в папке"""
    service = get_drive_service()
    if not service or not screenshots_folder_id:
        return []
    
    try:
        # Получаем все файлы в папке скриншотов
        query = f"'{screenshots_folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name, createdTime)').execute()
        files = results.get('files', [])
        
        # Сортируем по дате создания
        files.sort(key=lambda x: x['createdTime'])
        
        new_screenshots = []
        for file in files:
            if file['name'].lower().endswith(('.png', '.jpg', '.jpeg')):
                file_id = file['id']
                file_name = file['name']
                created_time = file['createdTime']
                
                # Проверяем, не отправляли ли уже этот скриншот
                if file_id not in last_screenshots_check:
                    new_screenshots.append({
                        'id': file_id,
                        'name': file_name,
                        'created_time': created_time
                    })
                    last_screenshots_check[file_id] = created_time
        
        return new_screenshots
    except Exception as e:
        logger.log_event("SCREENSHOTS_CHECK_ERROR", 0, {"type": "system"}, action="check_screenshots", details=f"Error: {e}")
        return []

def send_screenshot_to_admin(screenshot_info):
    """Отправляет скриншот администратору"""
    service = get_drive_service()
    if not service:
        return False
    
    try:
        # Скачиваем файл
        request = service.files().get_media(fileId=screenshot_info['id'])
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # Отправляем администратору
        admin_id = get_admin_user_id()
        if admin_id:
            bot.send_photo(admin_id, file_content.getvalue(), 
                          caption=f"📸 Скриншот ПК\n🕐 {screenshot_info['created_time']}")
            
            logger.log_event(
                "SCREENSHOT_SENT", 
                0, 
                {"type": "system"}, 
                action="send_screenshot", 
                details=f"File: {screenshot_info['name']}",
                target=f"Admin: {admin_id}"
            )
            return True
    
    except Exception as e:
        logger.log_event("SCREENSHOT_SEND_ERROR", 0, {"type": "system"}, action="send_screenshot", details=f"Error: {e}")
    
    return False

def get_admin_user_id():
    """Получает ID администратора"""
    auth_data = load_json_file(AUTH_USERS_FILE, {"users": []})
    
    if not isinstance(auth_data, dict) or "users" not in auth_data:
        return None
    
    for user in auth_data["users"]:
        if user["user_type"] == "admin":
            return user["user_id"]
    
    return None

def cleanup_old_commands():
    """Очищает старые выполненные команды"""
    try:
        commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
        
        if not isinstance(commands_data, dict) or "commands" not in commands_data:
            return
        
        # Удаляем команды старше 7 дней
        week_ago = datetime.now().timestamp() - (7 * 24 * 3600)
        
        filtered_commands = []
        for cmd in commands_data["commands"]:
            try:
                cmd_time = datetime.strptime(cmd.get("timestamp", ""), "%Y-%m-%d %H:%M:%S").timestamp()
                if cmd_time > week_ago or cmd.get("status") == "pending":
                    filtered_commands.append(cmd)
            except:
                filtered_commands.append(cmd)
        
        commands_data["commands"] = filtered_commands
        save_json_file(COMMANDS_FILE, commands_data)
        
        logger.log_event("COMMANDS_CLEANUP", 0, {"type": "system"}, action="cleanup_commands", details=f"Removed {len(commands_data['commands']) - len(filtered_commands)} old commands")
        
    except Exception as e:
        logger.log_event("COMMANDS_CLEANUP_ERROR", 0, {"type": "system"}, action="cleanup_commands", details=f"Error: {e}")

# ========== БАЗОВЫЕ ФУНКЦИИ ==========
def init_database():
    """Инициализирует базу данных"""
    try:
        db_content = load_database()
        
        if db_content and db_content.startswith(b'SQLite format 3\x00'):
            print("✅ Обнаружена SQLite база данных")
            
            temp_file = "temp_chats.db"
            with open(temp_file, 'wb') as f:
                f.write(db_content)
            
            conn = sqlite3.connect(temp_file)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"📊 Найдено таблиц: {len(tables)}")
            
            if 'user_chats' in tables:
                print("✅ Использую таблицу user_chats")
                
                cursor.execute("SELECT user_id, chat_id, chat_title, chat_username FROM user_chats")
                chats_data = cursor.fetchall()
                
                print(f"📊 Найдено {len(chats_data)} чатов в базе")
                
                new_conn = sqlite3.connect(':memory:')
                new_cursor = new_conn.cursor()
                
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
                
                for user_id, chat_id, chat_title, chat_username in chats_data:
                    new_cursor.execute('''
                        INSERT INTO chats (user_id, chat_id, chat_title, chat_username)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, chat_id, chat_title, chat_username))
                
                new_conn.commit()
                conn.close()
                new_conn.close()
                
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
                
                backup_conn = sqlite3.connect('new_chats.db')
                new_conn.backup(backup_conn)
                backup_conn.close()
                
                with open('new_chats.db', 'rb') as f:
                    new_db_content = f.read()
                
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
        db_content = load_database()
        
        if db_content and db_content.startswith(b'SQLite format 3\x00'):
            temp_file = "temp_read.db"
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
        else:
            return []
            
    except Exception as e:
        print(f"❌ Ошибка получения чатов: {e}")
        return []

def save_user_chat(user_id, chat_id, chat_title, chat_username=None, chat_type=None):
    """Сохраняет информацию о чате"""
    try:
        db_content = load_database()
        
        if not db_content or not db_content.startswith(b'SQLite format 3\x00'):
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
            temp_file = "temp_save.db"
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
        
        backup_conn = sqlite3.connect('final_chats.db')
        conn.backup(backup_conn)
        backup_conn.close()
        
        with open('final_chats.db', 'rb') as f:
            new_db_content = f.read()
        
        save_database(new_db_content)
        
        conn.close()
        if os.path.exists('final_chats.db'):
            os.remove('final_chats.db')
        if os.path.exists('temp_save.db'):
            os.remove('temp_save.db')
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка сохранения чата: {e}")
        return False

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
    logger.log_event("EMAIL_ADDED", user_id, f"Email: {email}")
    return True

def delete_email_by_admin(email):
    """Удаляет email"""
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
        logger.log_event("AUTH_ADDED", user_id, f"Type: {user_type}")
    
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

def ask_openrouter(user_message):
    """Запрос к OpenRouter"""
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

def handle_ai_request(user_id, user_message):
    """Обрабатывает запрос к ИИ"""
    logger.log_event("AI_REQUEST", user_id)
    
    bot.send_chat_action(user_id, 'typing')
    response = ask_openrouter(user_message)
    
    logger.log_event("AI_RESPONSE", user_id, f"Response length: {len(response)}")
    return response

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

# ========== ОБНОВЛЕННЫЕ ОБРАБОТЧИКИ ==========
def setup_bot_handlers():
    """Настраивает обработчики бота"""
    
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_id = message.from_user.id
        user_info = {
            "id": user_id,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "username": message.from_user.username
        }
        
        logger.log_event("USER_START", user_id, user_info, action="start_bot")
        
        if user_id in ai_mode_active:
            del ai_mode_active[user_id]
        
        access_level = check_user_access(user_id)
        
        if access_level == 'admin':
            show_admin_menu(message)
        elif access_level == 'platon':
            show_platon_menu(message)
        else:
            show_guest_menu(message)
    
    @bot.message_handler(func=lambda message: message.text == "🖥️ Управление ПК")
    def pc_management_handler(message):
        """Управление ПК"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level != 'admin':
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Только для администратора.</b>")
            logger.log_event("PC_ACCESS_DENIED", user_id, action="pc_management_access")
            return
        
        logger.log_event("PC_MENU_OPENED", user_id, action="open_pc_management")
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        
        # Основные команды
        btn_shutdown = types.KeyboardButton("🔴 Выключить ПК")
        btn_restart = types.KeyboardButton("🔄 Перезагрузить ПК")
        btn_sleep = types.KeyboardButton("😴 Спящий режим")
        btn_hibernate = types.KeyboardButton("💤 Режим гибернации")
        btn_lock = types.KeyboardButton("🔒 Заблокировать ПК")
        
        # Скриншоты
        btn_screenshot = types.KeyboardButton("📸 Сделать скриншот")
        
        # Запуск программ
        btn_notepad = types.KeyboardButton("📝 Блокнот")
        btn_paint = types.KeyboardButton("🎨 Paint")
        btn_explorer = types.KeyboardButton("📁 Проводник")
        btn_calculator = types.KeyboardButton("🧮 Калькулятор")
        btn_cmd = types.KeyboardButton("💻 Командная строка")
        
        # Назад
        btn_back = types.KeyboardButton("🔙 Назад в меню")
        
        markup.add(btn_shutdown, btn_restart, btn_sleep, btn_hibernate, btn_lock)
        markup.add(btn_screenshot)
        markup.add(btn_notepad, btn_paint, btn_explorer, btn_calculator, btn_cmd)
        markup.add(btn_back)
        
        bot.send_message(message.chat.id,
                        "<b>🖥️ Управление удалённым ПК</b>\n\n"
                        "<b>Основные команды:</b>\n"
                        "🔴 Выключить ПК\n"
                        "🔄 Перезагрузить ПК\n"
                        "😴 Спящий режим\n"
                        "💤 Режим гибернации\n"
                        "🔒 Заблокировать ПК\n\n"
                        "<b>Скриншоты:</b>\n"
                        "📸 Сделать скриншот\n\n"
                        "<b>Запуск программ:</b>\n"
                        "📝 Блокнот\n"
                        "🎨 Paint\n"
                        "📁 Проводник\n"
                        "🧮 Калькулятор\n"
                        "💻 Командная строка\n\n"
                        "<i>⚠️ Защита от повторного выполнения: одинаковые команды можно отправлять не чаще чем раз в 30 секунд</i>",
                        reply_markup=markup)
    
    @bot.message_handler(func=lambda message: message.text in ["🔴 Выключить ПК", "🔄 Перезагрузить ПК", "😴 Спящий режим", 
                                                               "💤 Режим гибернации", "🔒 Заблокировать ПК"])
    def pc_basic_commands_handler(message):
        """Обработчик базовых команд ПК с защитой от повторного выполнения"""
        user_id = message.from_user.id
        command_text = message.text
        
        command_map = {
            "🔴 Выключить ПК": "shutdown",
            "🔄 Перезагрузить ПК": "restart",
            "😴 Спящий режим": "sleep",
            "💤 Режим гибернации": "hibernate",
            "🔒 Заблокировать ПК": "lock"
        }
        
        command_type = command_map.get(command_text)
        if not command_type:
            return
        
        # Проверяем, не отправлялась ли уже такая команда недавно
        command_hash = generate_command_hash(user_id, command_type)
        
        if is_command_in_cooldown(user_id, command_hash):
            bot.send_message(message.chat.id,
                            f"<b>⏳ Команда '{command_text}' уже была отправлена недавно!</b>\n\n"
                            f"<i>Пожалуйста, подождите {COMMAND_COOLDOWN_TIME} секунд перед повторной отправкой этой команды.</i>")
            return
        
        if is_command_already_executed(command_hash):
            bot.send_message(message.chat.id,
                            f"<b>⚠️ Команда '{command_text}' уже была выполнена ранее!</b>\n\n"
                            f"<i>Чтобы отправить её снова, подождите {COMMAND_COOLDOWN_TIME} секунд.</i>")
            return
        
        command_id = save_pc_command(user_id, command_type)
        
        if command_id:
            bot.send_message(message.chat.id,
                            f"<b>✅ Команда отправлена на ПК!</b>\n\n"
                            f"Команда: {command_text}\n"
                            f"ID команды: {command_id}\n"
                            f"Статус: Ожидание выполнения\n\n"
                            f"<i>ПК выполнит команду в течение 5 секунд.</i>\n"
                            f"<i>Защита активирована: следующие {COMMAND_COOLDOWN_TIME} секунд эту команду нельзя будет отправить повторно.</i>")
            
            logger.log_event("PC_COMMAND_SENT", user_id, 
                            action="send_pc_command", 
                            details=f"Command: {command_type}, ID: {command_id}, Hash: {command_hash}")
        else:
            bot.send_message(message.chat.id, 
                            f"<b>❌ Ошибка при отправке команды!</b>\n\n"
                            f"<i>Возможно, такая команда уже ожидает выполнения.</i>")
    
    @bot.message_handler(func=lambda message: message.text == "📸 Сделать скриншот")
    def take_screenshot_handler(message):
        """Запрос скриншота"""
        user_id = message.from_user.id
        
        # Проверяем кулдаун
        command_hash = generate_command_hash(user_id, "screenshot")
        
        if is_command_in_cooldown(user_id, command_hash):
            bot.send_message(message.chat.id,
                            "<b>⏳ Скриншот уже был запрошен недавно!</b>\n\n"
                            f"<i>Пожалуйста, подождите {COMMAND_COOLDOWN_TIME} секунд перед повторным запросом.</i>")
            return
        
        command_id = save_pc_command(user_id, "screenshot")
        
        if command_id:
            bot.send_message(message.chat.id,
                            "<b>📸 Запрос скриншота отправлен!</b>\n\n"
                            f"ID команды: {command_id}\n"
                            f"Статус: Ожидание выполнения\n\n"
                            "<i>Скриншот будет сделан и отправлен вам в течение 10 секунд.</i>\n"
                            f"<i>Защита активирована: следующие {COMMAND_COOLDOWN_TIME} секунд нельзя будет запросить скриншот.</i>")
            
            logger.log_event("SCREENSHOT_REQUESTED", user_id, 
                            action="request_screenshot",
                            details=f"Command ID: {command_id}, Hash: {command_hash}")
        else:
            bot.send_message(message.chat.id, 
                            "<b>❌ Ошибка при запросе скриншота!</b>\n\n"
                            "<i>Возможно, скриншот уже запрошен и ожидает выполнения.</i>")
    
    @bot.message_handler(func=lambda message: message.text in ["📝 Блокнот", "🎨 Paint", "📁 Проводник", 
                                                               "🧮 Калькулятор", "💻 Командная строка"])
    def pc_programs_handler(message):
        """Запуск программ на ПК с защитой от повторного выполнения"""
        user_id = message.from_user.id
        program_text = message.text
        
        program_map = {
            "📝 Блокнот": "notepad",
            "🎨 Paint": "paint",
            "📁 Проводник": "explorer",
            "🧮 Калькулятор": "calculator",
            "💻 Командная строка": "cmd"
        }
        
        program_name = program_map.get(program_text)
        if not program_name:
            return
        
        # Проверяем кулдаун
        command_hash = generate_command_hash(user_id, "launch_program", {"program": program_name})
        
        if is_command_in_cooldown(user_id, command_hash):
            bot.send_message(message.chat.id,
                            f"<b>⏳ Команда '{program_text}' уже была отправлена недавно!</b>\n\n"
                            f"<i>Пожалуйста, подождите {COMMAND_COOLDOWN_TIME} секунд перед повторной отправкой.</i>")
            return
        
        command_id = save_pc_command(user_id, "launch_program", {"program": program_name})
        
        if command_id:
            bot.send_message(message.chat.id,
                            f"<b>✅ Команда отправлена на ПК!</b>\n\n"
                            f"Программа: {program_text}\n"
                            f"ID команды: {command_id}\n"
                            f"Статус: Ожидание выполнения\n\n"
                            f"<i>Программа будет запущена в течение 5 секунд.</i>\n"
                            f"<i>Защита активирована: следующие {COMMAND_COOLDOWN_TIME} секунд эту программу нельзя будет запустить повторно.</i>")
            
            logger.log_event("PC_PROGRAM_LAUNCHED", user_id,
                            action="launch_program",
                            details=f"Program: {program_name}, ID: {command_id}, Hash: {command_hash}")
        else:
            bot.send_message(message.chat.id,
                            f"<b>❌ Ошибка при отправке команды!</b>\n\n"
                            f"<i>Возможно, программа '{program_text}' уже запрошена к запуску.</i>")
    
    @bot.message_handler(func=lambda message: message.text == "🔙 Назад в меню")
    def back_to_menu_handler(message):
        """Возврат в главное меню"""
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if access_level == 'admin':
            show_admin_menu(message)
        elif access_level == 'platon':
            show_platon_menu(message)
        else:
            show_guest_menu(message)
    
    # Остальные существующие обработчики остаются без изменений
    # (команды авторизации, email, рассылки и т.д.)
    
    @bot.message_handler(func=lambda message: message.text == "🔐 Войти в систему")
    def auth_handler(message):
        user_id = message.from_user.id
        logger.log_event("AUTH_REQUEST", user_id)
        
        user_waiting_for_input[user_id] = 'password'
        bot.send_message(message.chat.id, "<b>🔐 Введите пароль для доступа к системе:</b>")
    
    @bot.message_handler(func=lambda message: message.text == "📧 Добавить email")
    def add_email_handler(message):
        user_id = message.from_user.id
        logger.log_event("EMAIL_ADD_REQUEST", user_id)
        
        user_waiting_for_input[user_id] = 'email'
        bot.send_message(message.chat.id,
                        "<b>📧 Введите ваш email адрес:</b>\n\n"
                        "Сообщения будут приходить от ermakartekovec@gmail.com\n"
                        "<i>Внимание: сообщения могут быть в папке спам.</i>")
    
    @bot.message_handler(func=lambda message: message.text == "🤖 ИИ-помощник")
    def ai_assistant_handler(message):
        user_id = message.from_user.id
        logger.log_event("AI_MENU", user_id)
        
        ai_mode_active[user_id] = True
        
        bot.send_message(message.chat.id,
                        "<b>🤖 ИИ-помощник активирован!</b>\n\n"
                        "Задайте любой вопрос, и я постараюсь помочь.\n\n"
                        "💡 <b>Безлимитное использование для всех</b>\n"
                        "⏸️ <i>Для выхода из режима ИИ нажмите кнопку '⏸️ Остановить ИИ'</i>")
    
    @bot.message_handler(func=lambda message: message.text == "⏸️ Остановить ИИ")
    def stop_ai_handler(message):
        user_id = message.from_user.id
        
        if user_id in ai_mode_active:
            del ai_mode_active[user_id]
            logger.log_event("AI_STOPPED", user_id)
        
        access_level = check_user_access(user_id)
        
        if access_level == 'admin':
            show_admin_menu(message)
        elif access_level == 'platon':
            show_platon_menu(message)
        else:
            show_guest_menu(message)
    
    @bot.message_handler(func=lambda message: message.text == "📤 Отправить сообщение")
    def send_message_handler(message):
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
        user_id = message.from_user.id
        access_level = check_user_access(user_id)
        
        if not access_level:
            bot.send_message(message.chat.id, "<b>❌ Доступ запрещен! Требуется авторизация.</b>")
            return
        
        logger.log_event("EMAILS_VIEW", user_id)
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
            
            elif operation == 'broadcast_users':
                process_broadcast_to_users(message)
                del user_waiting_for_input[user_id]
                return
            
            elif operation == 'broadcast_email':
                process_email_broadcast(message)
                del user_waiting_for_input[user_id]
                return
        
        menu_buttons = [
            "🔐 Войти в систему", "📧 Добавить email", "📤 Отправить сообщение",
            "📋 Мои чаты и каналы", "📧 Массовая рассылка", "👥 Управление email",
            "Платон🙌", "📢 Рассылка пользователям", "🤖 ИИ-помощник",
            "⏸️ Остановить ИИ", "📧 Мои email", "⚙️ Настройки",
            "🖥️ Управление ПК", "🔴 Выключить ПК", "🔄 Перезагрузить ПК",
            "😴 Спящий режим", "💤 Режим гибернации", "🔒 Заблокировать ПК",
            "📸 Сделать скриншот", "📝 Блокнот", "🎨 Paint", "📁 Проводник",
            "🧮 Калькулятор", "💻 Командная строка", "🔙 Назад в меню"
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
                logger.log_event("SEND_TO_CHAT", user_id, f"Chat: {chat_id}, Type: {message.content_type}")
                
                if message.content_type == 'text':
                    bot.send_message(chat_id, message.text)
                    bot.send_message(message.chat.id, f"<b>✅ Текст отправлен в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Text to chat {chat_id}")
                
                elif message.content_type == 'photo':
                    bot.send_photo(chat_id, message.photo[-1].file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Фото отправлено в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Photo to chat {chat_id}")
                
                elif message.content_type == 'video':
                    bot.send_video(chat_id, message.video.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Видео отправлено в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Video to chat {chat_id}")
                
                elif message.content_type == 'document':
                    bot.send_document(chat_id, message.document.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Документ отправлен в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Document to chat {chat_id}")
                
                elif message.content_type == 'audio':
                    bot.send_audio(chat_id, message.audio.file_id, caption=message.caption)
                    bot.send_message(message.chat.id, f"<b>✅ Аудио отправлено в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Audio to chat {chat_id}")
                
                elif message.content_type == 'voice':
                    bot.send_voice(chat_id, message.voice.file_id)
                    bot.send_message(message.chat.id, f"<b>✅ Голосовое сообщение отправлено в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Voice to chat {chat_id}")
                
                elif message.content_type == 'sticker':
                    bot.send_sticker(chat_id, message.sticker.file_id)
                    bot.send_message(message.chat.id, f"<b>✅ Стикер отправлен в чат</b>")
                    logger.log_event("SEND_SUCCESS", user_id, f"Sticker to chat {chat_id}")
                
                if user_id in selected_chats:
                    del selected_chats[user_id]
                
            except Exception as e:
                error_msg = str(e)
                bot.send_message(message.chat.id, f"<b>❌ Ошибка при отправке в чат:</b> {error_msg[:200]}")
                logger.log_event("SEND_ERROR", user_id, f"Chat {chat_id}: {error_msg}")
                
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
                logger.log_event("CHAT_ADDED", user_id, f"Chat: {chat.title}, ID: {chat.id}")
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Ошибка при добавлении чата: {error_msg}")
            logger.log_event("CHAT_ADD_ERROR", user_id, f"Error: {error_msg}")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def check_password(message):
    user_id = message.from_user.id
    password = message.text.strip()
    
    logger.log_event("PASSWORD_CHECK", user_id, f"Password: {'*' * len(password)}")
    
    if password == PASSWORD_ADMIN:
        save_auth_user('admin', user_id)
        logger.log_event("AUTH_SUCCESS", user_id, "Role: admin")
        bot.send_message(message.chat.id, "<b>✅ Пароль верный! Вы вошли как администратор.</b>")
        show_admin_menu(message)
    
    elif password == PASSWORD_PLATON:
        save_auth_user('platon', user_id)
        logger.log_event("AUTH_SUCCESS", user_id, "Role: platon")
        bot.send_message(message.chat.id, "<b>✅ Пароль верный!</b>")
        show_platon_menu(message)
    
    else:
        logger.log_event("AUTH_FAILED", user_id)
        bot.send_message(message.chat.id,
                        "<b>❌ Неверный пароль!</b>\n\n"
                        "Вы не являетесь ни админом, ни доверенным лицом.\n\n"
                        "Но вы можете использовать ИИ-помощника без ограничений!")
        show_guest_menu(message)

def save_email_step(message):
    user_id = message.from_user.id
    email = message.text.strip()
    
    logger.log_event("EMAIL_SAVE_ATTEMPT", user_id, f"Email: {email}")
    
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
    user_id = message.from_user.id
    email = message.text.strip()
    
    if delete_email_by_admin(email):
        bot.send_message(message.chat.id,
                        f"<b>✅ Email {email} успешно удален!</b>")
    else:
        bot.send_message(message.chat.id,
                        f"<b>❌ Email {email} не найден.</b>")

def send_to_platon(message):
    user_id = message.from_user.id
    platon_ids = get_platon_users()
    
    for platon_id in platon_ids:
        try:
            bot.send_message(platon_id, message.text)
            logger.log_event("SEND_TO_PLATON", user_id, f"To: {platon_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки Платону {platon_id}: {e}")
            logger.log_event("SEND_TO_PLATON_ERROR", user_id, f"To: {platon_id}, Error: {str(e)}")
    
    bot.send_message(message.chat.id,
                    f"<b>✅ Сообщение отправлено Платону</b>")

def broadcast_to_users_func(message_text):
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
    
    markup.add(btn_pc, btn_send, btn_chats, btn_email, btn_emails)
    markup.add(btn_platon, btn_broadcast, btn_ai, btn_stop_ai, btn_settings)
    
    welcome_text = f"""<b>{BOT_NAME} - Панель администратора</b>

<b>🖥️ НОВЫЕ ФУНКЦИИ УПРАВЛЕНИЯ ПК (с защитой от повторного выполнения):</b>
✅ Выключение/перезагрузка (кулдаун 30 сек)
✅ Скриншоты экрана (кулдаун 30 сек)
✅ Запуск программ (кулдаун 30 сек)
✅ Блокировка ПК (кулдаун 30 сек)

<b>Доступные функции:</b>
✅ 📤 Отправка сообщений в Telegram чаты/каналы
✅ 📧 Массовая EMAIL рассылка
✅ 👥 Управление email адресами (всех пользователей)
✅ Платон🙌 Управление пользователем Платон
✅ 📢 Рассылка всем пользователям бота (Telegram)
✅ 🤖 ИИ-помощник
✅ ⏸️ Остановить ИИ
✅ ⚙️ Настройки бота

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
   Я переделанный бот @jal_on_Plat_bot
   Ваш телефон под защитой ErmakProtect
   Начните с общения с ИИ
   Внимание: пользователь Ермак не может отправлять вам сообщения в этот чат
   Вы можете добавить свой email для получения рассылок

<b>Выберите действие из меню ниже 👇</b>"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# ========== ФОНТОВЫЕ ЗАДАЧИ ==========
def background_tasks():
    """Фоновые задачи для проверки скриншотов"""
    logger.log_event("BACKGROUND_TASKS_START", 0, {"type": "system"}, "Запуск фоновых задач")
    
    service = get_drive_service()
    if service:
        get_or_create_screenshots_folder(service)
    
    while True:
        try:
            # Проверка новых скриншотов каждые 10 секунд
            new_screenshots = check_new_screenshots()
            for screenshot in new_screenshots:
                send_screenshot_to_admin(screenshot)
                logger.log_event("SCREENSHOT_PROCESSED", 0, {"type": "system"}, 
                                action="process_screenshot", 
                                details=f"File: {screenshot['name']}")
            
            # Периодическое сохранение логов
            logger.flush_logs_to_drive()
            
            # Очистка старых команд раз в час
            if int(time.time()) % 3600 < 5:  # Каждый час
                cleanup_old_commands()
            
            time.sleep(10)
            
        except Exception as e:
            logger.log_event("BACKGROUND_TASK_ERROR", 0, {"type": "system"}, 
                            action="background_task", 
                            details=f"Error: {str(e)[:200]}")
            time.sleep(10)

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
    GOOGLE_DRIVE_FOLDER_ID = get_or_create_folder(service)
    if not GOOGLE_DRIVE_FOLDER_ID:
        print("❌ Не удалось создать папку")
        return False
    
    print(f"✅ Папка: https://drive.google.com/drive/folders/{GOOGLE_DRIVE_FOLDER_ID}")
    
    if not load_config_from_drive():
        print("❌ Не удалось загрузить конфигурацию")
        return False
    
    # Загрузка кэша выполненных команд
    try:
        commands_data = load_json_file(COMMANDS_FILE, {"commands": [], "last_id": 0})
        for cmd in commands_data.get("commands", []):
            if cmd.get("status") == "executed" and "command_hash" in cmd:
                executed_commands_cache.add(cmd["command_hash"])
        print(f"✅ Загружен кэш {len(executed_commands_cache)} выполненных команд")
    except:
        print("⚠️  Не удалось загрузить кэш выполненных команд")
    
    # Запуск фоновых задач в отдельном потоке
    bg_thread = threading.Thread(target=background_tasks, daemon=True)
    bg_thread.start()
    print("✅ Фоновые задачи запущены")
    
    print("✅ Система инициализирована")
    return True

# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"🚀 Запуск Google Ermak System")
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
    
    print(f"\n{'=' * 60}")
    print("🎯 ОСНОВНЫЕ ФУНКЦИИ БОТА:")
    print("   🖥️ НОВЫЕ ФУНКЦИИ УПРАВЛЕНИЯ ПК (с защитой):")
    print("   1. 🔴 Выключение ПК (кулдаун 30 сек)")
    print("   2. 🔄 Перезагрузка ПК (кулдаун 30 сек)")
    print("   3. 😴 Спящий режим (кулдаун 30 сек)")
    print("   4. 💤 Режим гибернации (кулдаун 30 сек)")
    print("   5. 🔒 Блокировка ПК (кулдаун 30 сек)")
    print("   6. 📸 Создание скриншотов (кулдаун 30 сек)")
    print("   7. 📝 Запуск Блокнота (кулдаун 30 сек)")
    print("   8. 🎨 Запуск Paint (кулдаун 30 сек)")
    print("   9. 📁 Запуск Проводника (кулдаун 30 сек)")
    print("   10. 🧮 Запуск Калькулятора (кулдаун 30 сек)")
    print("   11. 💻 Запуск Командной строки (кулдаун 30 сек)")
    print("\n   📊 УЛУЧШЕННЫЕ ЛОГИ:")
    print("   • Детальное логирование всех действий")
    print("   • Защита от повторного выполнения команд")
    print("   • Логи хранятся в Google Drive")
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