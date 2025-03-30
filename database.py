import sqlite3
from typing import List, Dict, Optional
import os

class CatalogDatabase:
    def __init__(self, db_path: str = "catalog.db"):
        self.db_path = db_path
        self.create_tables()
    
    def create_tables(self):
        """Создание таблиц базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица категорий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id INTEGER,
                    FOREIGN KEY (parent_id) REFERENCES categories (id)
                )
            ''')
            
            # Таблица товаров
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article TEXT UNIQUE,
                    name TEXT NOT NULL,
                    price REAL NOT NULL,
                    url TEXT NOT NULL
                )
            ''')
            
            # Создаем виртуальную FTS таблицу для поиска по товарам
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
                    article,
                    name,
                    content='products',
                    content_rowid='id'
                )
            ''')
            
            # Создаем триггеры для синхронизации FTS таблицы
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
                    INSERT INTO products_fts(rowid, article, name) VALUES (new.id, new.article, new.name);
                END;
            ''')
            
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
                    INSERT INTO products_fts(products_fts, rowid, article, name) VALUES('delete', old.id, old.article, old.name);
                END;
            ''')
            
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
                    INSERT INTO products_fts(products_fts, rowid, article, name) VALUES('delete', old.id, old.article, old.name);
                    INSERT INTO products_fts(rowid, article, name) VALUES (new.id, new.article, new.name);
                END;
            ''')
            
            # Таблица изображений товаров
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    image_url TEXT NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Таблица связей товаров с категориями
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_categories (
                    product_id INTEGER,
                    category_id INTEGER,
                    PRIMARY KEY (product_id, category_id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (category_id) REFERENCES categories (id)
                )
            ''')
            
            conn.commit()
    
    def clear_data(self):
        """Очистка всех таблиц"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM product_categories")
            cursor.execute("DELETE FROM product_images")
            cursor.execute("DELETE FROM products_fts")
            cursor.execute("DELETE FROM products")
            cursor.execute("DELETE FROM categories")
            conn.commit()
    
    def add_category(self, category_id: int, name: str, parent_id: Optional[int] = None):
        """Добавление категории"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO categories (id, name, parent_id) VALUES (?, ?, ?)",
                (category_id, name, parent_id)
            )
    
    def add_product(self, article: str, name: str, price: float, url: str, 
                   category_ids: List[int], images: List[str]):
        """Добавление товара"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Добавляем товар
            cursor.execute(
                "INSERT OR REPLACE INTO products (article, name, price, url) VALUES (?, ?, ?, ?)",
                (article, name, price, url)
            )
            product_id = cursor.lastrowid
            
            # Добавляем изображения
            for image_url in images:
                cursor.execute(
                    "INSERT INTO product_images (product_id, image_url) VALUES (?, ?)",
                    (product_id, image_url)
                )
            
            # Добавляем связи с категориями
            for category_id in category_ids:
                cursor.execute(
                    "INSERT OR REPLACE INTO product_categories (product_id, category_id) VALUES (?, ?)",
                    (product_id, category_id)
                )
    
    def get_category_tree(self) -> Dict:
        """Получение дерева категорий с количеством товаров"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Получаем все категории с их прямыми товарами
            cursor.execute("""
                WITH RECURSIVE category_tree AS (
                    -- Базовый случай: все категории с их прямыми товарами
                    SELECT 
                        c.id,
                        c.name,
                        c.parent_id,
                        COUNT(DISTINCT pc.product_id) as direct_product_count
                    FROM categories c
                    LEFT JOIN product_categories pc ON c.id = pc.category_id
                    GROUP BY c.id
                    
                    UNION ALL
                    
                    -- Рекурсивная часть: добавляем товары из подкатегорий
                    SELECT 
                        p.id,
                        p.name,
                        p.parent_id,
                        ct.direct_product_count
                    FROM categories p
                    JOIN category_tree ct ON p.id = ct.parent_id
                ),
                category_totals AS (
                    -- Суммируем количество товаров для каждой категории и её подкатегорий
                    SELECT 
                        ct.id,
                        ct.name,
                        ct.parent_id,
                        SUM(ct.direct_product_count) as total_products
                    FROM category_tree ct
                    GROUP BY ct.id
                )
                SELECT 
                    id,
                    name,
                    parent_id,
                    total_products as product_count
                FROM category_totals
                ORDER BY id
            """)
            
            categories = {}
            for row in cursor.fetchall():
                categories[row['id']] = {
                    'id': row['id'],
                    'name': row['name'],
                    'parent_id': row['parent_id'],
                    'product_count': row['product_count'],
                    'children': []
                }
            
            # Строим дерево
            root = {}
            for cat_id, cat_data in categories.items():
                if cat_data['parent_id'] is None:
                    root[cat_id] = cat_data
                else:
                    parent = categories.get(cat_data['parent_id'])
                    if parent:
                        parent['children'].append(cat_data)
            
            return root
    
    def get_category_path(self, category_id: int) -> List[Dict]:
        """Получение пути категории от корня до указанной категории"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                WITH RECURSIVE category_path AS (
                    -- Базовый случай: начальная категория
                    SELECT id, name, parent_id, 1 as level
                    FROM categories
                    WHERE id = ?
                    
                    UNION ALL
                    
                    -- Рекурсивная часть: родительские категории
                    SELECT c.id, c.name, c.parent_id, cp.level + 1
                    FROM categories c
                    JOIN category_path cp ON c.id = cp.parent_id
                )
                SELECT id, name
                FROM category_path
                ORDER BY level DESC
            """, (category_id,))
            
            return [dict(row) for row in cursor.fetchall()]

    def get_products_by_category(self, category_id: int, page: int = 1, per_page: int = 30) -> Dict:
        """Получение товаров по категории с пагинацией"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Создаем временную таблицу для хранения всех ID подкатегорий
            cursor.execute("""
                WITH RECURSIVE subcategories AS (
                    SELECT id FROM categories WHERE id = ?
                    UNION ALL
                    SELECT c.id FROM categories c
                    JOIN subcategories sc ON c.parent_id = sc.id
                )
                SELECT COUNT(DISTINCT p.id) as total_count
                FROM products p
                JOIN product_categories pc ON p.id = pc.product_id
                WHERE pc.category_id IN subcategories
            """, (category_id,))
            
            total_count = cursor.fetchone()['total_count']
            total_pages = (total_count + per_page - 1) // per_page
            
            # Получаем товары для текущей страницы
            cursor.execute("""
                WITH RECURSIVE subcategories AS (
                    SELECT id FROM categories WHERE id = ?
                    UNION ALL
                    SELECT c.id FROM categories c
                    JOIN subcategories sc ON c.parent_id = sc.id
                )
                SELECT DISTINCT 
                    p.id,
                    p.article,
                    p.name,
                    p.price,
                    p.url,
                    pc.category_id,
                    (SELECT image_url FROM product_images WHERE product_id = p.id LIMIT 1) as picture
                FROM products p
                JOIN product_categories pc ON p.id = pc.product_id
                WHERE pc.category_id IN subcategories
                ORDER BY p.id
                LIMIT ? OFFSET ?
            """, (category_id, per_page, (page - 1) * per_page))
            
            products = [{
                'id': row['id'],
                'article': row['article'],
                'name': row['name'],
                'price': row['price'],
                'url': row['url'],
                'picture': row['picture'],
                'category_id': row['category_id']
            } for row in cursor.fetchall()]
            
            return {
                'products': products,
                'total_pages': total_pages,
                'current_page': page,
                'per_page': per_page,
                'total_count': total_count
            }
    
    def normalize_text(self, text: str) -> str:
        """Нормализация текста для поиска"""
        return text.lower().strip()

    def search_products(self, query: str) -> List[Dict]:
        """Поиск товаров"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT
                    p.id,
                    p.article,
                    p.name,
                    p.price,
                    p.url,
                    pc.category_id,
                    (SELECT image_url FROM product_images WHERE product_id = p.id LIMIT 1) as picture
                FROM products p
                JOIN products_fts f ON p.id = f.rowid
                LEFT JOIN product_categories pc ON p.id = pc.product_id
                WHERE products_fts MATCH ?
                ORDER BY rank
                LIMIT 50
            """, (query,))
            
            return [{
                'id': row['id'],
                'article': row['article'],
                'name': row['name'],
                'price': row['price'],
                'url': row['url'],
                'picture': row['picture'],
                'category_id': row['category_id']
            } for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        """Получение статистики каталога"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем статистику
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM categories) as categories_count,
                    COUNT(*) as products_count,
                    ROUND(AVG(price), 2) as average_price
                FROM products
            """)
            
            row = cursor.fetchone()
            return {
                'categories_count': row[0],
                'products_count': row[1],
                'average_price': row[2] or 0
            } 