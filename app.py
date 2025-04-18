from flask import Flask, jsonify, render_template, request, Response
from database import CatalogDatabase
from feed_parser import FeedParser
import os
from datetime import datetime
import signal
import sys
import subprocess
from threading import Timer, Lock
import time
import logging
from functools import wraps
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Добавляем обработчик для вывода в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Конфигурация
XML_FILE = "catalog_feed.xml"
PORT = 5003

# Блокировка для обновления каталога
update_lock = Lock()

# Параметры подключения к базе данных
def get_db_params():
    """Получение параметров подключения к базе данных"""
    # Проверяем наличие DATABASE_URL (для Render.com)
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # Парсим URL подключения к базе данных
        # Формат: postgres://user:password@host:port/dbname
        import re
        match = re.match(r'postgres://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', database_url)
        if match:
            user, password, host, port, dbname = match.groups()
            return {
                'dbname': dbname,
                'user': user,
                'password': password,
                'host': host,
                'port': port
            }
    
    # Если DATABASE_URL не указан, используем отдельные переменные
    return {
        'dbname': os.getenv('DB_NAME', 'catalog'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'postgres'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432')
    }

# Глобальная переменная для базы данных
db = None

def init_database(max_retries=5, retry_delay=5):
    """Инициализация базы данных с повторными попытками"""
    global db
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Попытка подключения к базе данных ({retry_count + 1}/{max_retries})...")
            db_params = get_db_params()
            logger.info(f"Параметры подключения: host={db_params['host']}, port={db_params['port']}, dbname={db_params['dbname']}, user={db_params['user']}")
            db = CatalogDatabase(**db_params)
            logger.info("База данных успешно инициализирована")
            return True
        except Exception as e:
            retry_count += 1
            logger.error(f"Ошибка при подключении к базе данных: {str(e)}")
            if retry_count < max_retries:
                logger.info(f"Повторная попытка через {retry_delay} секунд...")
                time.sleep(retry_delay)
            else:
                logger.error("Превышено максимальное количество попыток подключения")
                return False

def get_db():
    """Получение экземпляра базы данных"""
    global db
    if db is None:
        if not init_database():
            raise Exception("Не удалось инициализировать базу данных")
    return db

# Настройка базовой аутентификации
def check_auth(username, password):
    """Проверяет учетные данные пользователя"""
    return username == os.environ.get('AUTH_USERNAME', 'admin') and password == os.environ.get('AUTH_PASSWORD', 'password')

def authenticate():
    """Отправляет 401 ответ с запросом базовой аутентификации"""
    return Response(
        'Требуется авторизация', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# Применяем аутентификацию ко всем маршрутам, кроме API
@app.before_request
def before_request():
    if not request.path.startswith('/api/'):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
    # Проверяем подключение к базе данных
    try:
        get_db()
    except Exception as e:
        return jsonify({'error': 'Database connection error'}), 500

def update_catalog():
    """Обновление каталога из XML-фида"""
    if not os.path.exists(XML_FILE):
        raise FileNotFoundError(f'Файл {XML_FILE} не найден')
    
    # Используем блокировку для предотвращения параллельных обновлений
    if not update_lock.acquire(blocking=False):
        raise RuntimeError('Обновление каталога уже выполняется')
    
    try:
        parser = FeedParser(XML_FILE, get_db())
        parser.parse()
    finally:
        update_lock.release()

@app.route('/')
def index():
    """Отображает главную страницу каталога"""
    return render_template('categories.html')

@app.route('/update')
def update_catalog_route():
    """Обработчик для обновления каталога"""
    try:
        start_time = datetime.now()
        update_catalog()
        execution_time = (datetime.now() - start_time).total_seconds()
        
        stats = get_db().get_statistics()
        
        return jsonify({
            'success': True,
            'message': 'Каталог успешно обновлен',
            'stats': {
                **stats,
                'execution_time': execution_time
            }
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/search')
def search_api():
    """API для поиска товаров"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:  # Минимальная длина запроса - 2 символа
        return jsonify([])
    
    try:
        products = get_db().search_products(query)
        return jsonify(products)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/statistics')
def statistics_api():
    """API для получения статистики каталога"""
    return jsonify(get_db().get_statistics())

@app.route('/api/categories')
def categories_api():
    """API для получения дерева категорий"""
    return jsonify(get_db().get_category_tree())

@app.route('/api/products/<category_id>')
def get_products(category_id):
    """Получение товаров по категории"""
    try:
        logger.debug(f"Получен запрос на товары для категории {category_id}")
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 30, type=int)
        
        if page < 1 or per_page < 1:
            logger.error(f"Некорректные параметры пагинации: page={page}, per_page={per_page}")
            return jsonify({'error': 'Invalid pagination parameters'}), 400
            
        logger.debug(f"Параметры пагинации: page={page}, per_page={per_page}")
        
        products = get_db().get_products_by_category(category_id, page, per_page)
        logger.debug(f"Получено {len(products['items'])} товаров")
        
        return jsonify(products)
    except Exception as e:
        logger.error(f"Ошибка при получении товаров: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/restart')
def restart_server():
    """Перезапускает сервер"""
    return jsonify({
        'success': False,
        'error': 'Restart is not supported in development mode'
    }), 500

if __name__ == '__main__':
    try:
        # Инициализируем базу данных
        if not init_database():
            logger.error("Не удалось инициализировать базу данных")
            sys.exit(1)
        
        # Запускаем сервер
        logger.info(f"Запуск сервера на порту {PORT}...")
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', PORT)), debug=False)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске сервера: {str(e)}")
        sys.exit(1) 