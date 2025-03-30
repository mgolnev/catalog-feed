from flask import Flask, jsonify, render_template, request
from database import CatalogDatabase
from feed_parser import FeedParser
import os
from datetime import datetime
import signal
import sys
import subprocess
from threading import Timer
import time

app = Flask(__name__)

# Конфигурация
XML_FILE = "catalog_feed.xml"
DB_FILE = "catalog.db"
PORT = 5003

# Инициализация базы данных
db = CatalogDatabase(DB_FILE)

def update_catalog():
    """Обновление каталога из XML-фида"""
    if not os.path.exists(XML_FILE):
        raise FileNotFoundError(f'Файл {XML_FILE} не найден')
    
    parser = FeedParser(XML_FILE, db)
    parser.parse()

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
        
        stats = db.get_statistics()
        
        # Запускаем новый процесс
        subprocess.Popen([sys.executable, __file__])
        
        # Завершаем текущий процесс
        def shutdown():
            try:
                # Получаем все процессы на порту 5003
                result = subprocess.run(['lsof', '-ti', f'tcp:{PORT}'], 
                                     capture_output=True, text=True)
                if result.stdout.strip():
                    # Завершаем все процессы
                    for pid in result.stdout.strip().split('\n'):
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                        except:
                            pass
            except:
                pass
        
        Timer(2.0, shutdown).start()
        
        return jsonify({
            'success': True,
            'message': 'Каталог успешно обновлен, сервер перезапускается',
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

@app.route('/api/categories/<category_id>/products')
def get_products_api(category_id):
    """API для получения товаров по категории"""
    try:
        products = db.get_products_by_category(int(category_id))
        return jsonify(products)
    except ValueError:
        return jsonify({'error': 'Неверный ID категории'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/search')
def search_api():
    """API для поиска товаров"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:  # Уменьшаем минимальную длину запроса до 2 символов
        return jsonify([])
    
    try:
        products = db.search_products(query)
        return jsonify(products)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/statistics')
def statistics_api():
    """API для получения статистики каталога"""
    return jsonify(db.get_statistics())

@app.route('/api/categories')
def categories_api():
    """API для получения дерева категорий"""
    return jsonify(db.get_category_tree())

@app.route('/restart')
def restart_server():
    """Перезапускает сервер"""
    try:
        # Получаем PID текущего процесса
        pid = os.getpid()
        
        # Запускаем новый процесс
        subprocess.Popen([sys.executable] + sys.argv)
        
        # Завершаем текущий процесс
        def shutdown():
            os.kill(pid, signal.SIGTERM)
        
        # Планируем завершение через 1 секунду
        Timer(1.0, shutdown).start()
        
        return jsonify({
            'success': True,
            'message': 'Сервер перезапускается'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    # Завершаем все процессы на порту 5003
    try:
        result = subprocess.run(['lsof', '-ti', f'tcp:{PORT}'], 
                             capture_output=True, text=True)
        if result.stdout.strip():
            # Завершаем все процессы
            for pid in result.stdout.strip().split('\n'):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except:
                    pass
        # Даем время на освобождение порта
        time.sleep(1)
    except:
        pass
    
    # Всегда обновляем каталог при запуске
    print("Обновление каталога...")
    update_catalog()
    print("Каталог обновлен")
    
    # Запускаем сервер
    app.run(host='0.0.0.0', port=PORT) 