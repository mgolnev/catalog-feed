# Каталог товаров

Веб-приложение для отображения и поиска товаров из XML-фида.

## Локальная разработка

1. Установите PostgreSQL и создайте базу данных:
   ```
   createdb catalog
   ```

2. Создайте виртуальное окружение и установите зависимости:
   ```
   python -m venv .venv
   source .venv/bin/activate  # для Linux/Mac
   # или
   .venv\Scripts\activate  # для Windows
   pip install -r requirements.txt
   ```

3. Создайте файл `.env` с настройками:
   ```
   DB_NAME=catalog
   DB_USER=postgres
   DB_PASSWORD=postgres
   DB_HOST=localhost
   DB_PORT=5432
   AUTH_USERNAME=admin
   AUTH_PASSWORD=password
   ```

4. Запустите приложение:
   ```
   FLASK_DEBUG=1 FLASK_APP=app.py flask run --port 5003
   ```

## Развертывание на Render.com

1. Создайте новый веб-сервис на Render.com, подключив репозиторий.
2. Создайте базу данных PostgreSQL на Render.com.
3. Настройте переменные окружения:
   - `DATABASE_URL` (автоматически заполняется из базы данных)
   - `AUTH_USERNAME` (по умолчанию: admin)
   - `AUTH_PASSWORD` (генерируется автоматически)

## API

- `/api/categories` - получение дерева категорий
- `/api/products/<category_id>` - получение товаров по категории
- `/api/search?q=<query>` - поиск товаров
- `/api/statistics` - получение статистики каталога 