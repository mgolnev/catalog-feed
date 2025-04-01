import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
import logging
import os

class CatalogDatabase:
    def __init__(self, dbname='catalog', user='postgres', password='postgres', host='localhost', port=5432):
        self.conn_params = {
            'dbname': dbname,
            'user': user,
            'password': password,
            'host': host,
            'port': port
        }
        self._pool = None
        
        # Настройка логирования
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(handler)
        
        # Инициализация базы данных
        self._init_database()

    def get_connection(self):
        """Получение соединения из пула"""
        if self._pool is None:
            from psycopg2 import pool
            self._pool = pool.SimpleConnectionPool(1, 20, **self.conn_params)
        return self._pool.getconn()

    def put_connection(self, conn):
        """Возврат соединения в пул"""
        self._pool.putconn(conn)

    def _init_database(self):
        """Инициализация базы данных"""
        self.logger.info("Инициализация базы данных")
        
        try:
            # Подключаемся к базе данных
            conn = self.get_connection()
            cur = conn.cursor()
            
            # Создаем расширение для полнотекстового поиска
            cur.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
            
            # Создаем таблицы
            cur.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES categories(id),
                    name TEXT NOT NULL
                )
            ''')
            
            cur.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    article TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price NUMERIC(10,2) NOT NULL,
                    url TEXT,
                    picture TEXT,
                    has_categories BOOLEAN DEFAULT FALSE,
                    search_vector tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('russian', coalesce(article,'')), 'A') ||
                        setweight(to_tsvector('russian', coalesce(name,'')), 'B')
                    ) STORED
                )
            ''')
            
            cur.execute('''
                CREATE TABLE IF NOT EXISTS product_categories (
                    product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
                    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
                    PRIMARY KEY (product_id, category_id)
                )
            ''')
            
            # Создаем индексы
            cur.execute('CREATE INDEX IF NOT EXISTS idx_products_article ON products(article)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_products_has_categories ON products(has_categories)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_product_categories_category ON product_categories(category_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_products_search ON products USING GIN(search_vector)')
            
            conn.commit()
            self.logger.info("Инициализация базы данных успешно завершена")
            
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            raise
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                self.put_connection(conn)

    def close(self):
        """Закрытие пула соединений"""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def add_category(self, category_id: int, name: str, parent_id: Optional[int] = None):
        """Добавление категории"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            self.logger.debug(f"Добавляем категорию {category_id}: {name}")
            cur.execute(
                'INSERT INTO categories (id, name, parent_id) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, parent_id = EXCLUDED.parent_id',
                (category_id, name, parent_id)
            )
            conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении категории {category_id}: {str(e)}")
            conn.rollback()
            raise
        finally:
            cur.close()
            self.put_connection(conn)

    def add_product(self, product_id: str, article: str, name: str, price: float, 
                   url: str, picture: Optional[str] = None, category_ids: List[int] = None):
        """Добавление товара"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            self.logger.debug(f"Добавляем товар {product_id}")
            
            # Добавляем товар
            has_categories = bool(category_ids)
            cur.execute(
                '''
                INSERT INTO products (id, article, name, price, url, picture, has_categories) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    article = EXCLUDED.article,
                    name = EXCLUDED.name,
                    price = EXCLUDED.price,
                    url = EXCLUDED.url,
                    picture = EXCLUDED.picture,
                    has_categories = EXCLUDED.has_categories
                ''',
                (product_id, article, name, price, url, picture, has_categories)
            )
            
            if category_ids:
                # Удаляем старые связи и добавляем новые
                cur.execute('DELETE FROM product_categories WHERE product_id = %s', (product_id,))
                cur.executemany(
                    'INSERT INTO product_categories (product_id, category_id) VALUES (%s, %s)',
                    [(product_id, cat_id) for cat_id in category_ids]
                )
            
            conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении товара {product_id}: {str(e)}")
            conn.rollback()
            raise
        finally:
            cur.close()
            self.put_connection(conn)

    def get_products_by_category(self, category_id: int, page: int = 1, per_page: int = 30) -> Dict:
        """Получение товаров по категории с пагинацией"""
        conn = self.get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Получаем общее количество товаров
            cur.execute('''
                WITH RECURSIVE subcategories AS (
                    SELECT id FROM categories WHERE id = %s
                    UNION ALL
                    SELECT c.id FROM categories c
                    INNER JOIN subcategories sc ON c.parent_id = sc.id
                )
                SELECT COUNT(DISTINCT p.id) as count
                FROM products p
                JOIN product_categories pc ON p.id = pc.product_id
                WHERE pc.category_id IN (SELECT id FROM subcategories)
            ''', (category_id,))
            
            total_count = cur.fetchone()['count']
            
            # Получаем товары для текущей страницы
            cur.execute('''
                WITH RECURSIVE subcategories AS (
                    SELECT id FROM categories WHERE id = %s
                    UNION ALL
                    SELECT c.id FROM categories c
                    INNER JOIN subcategories sc ON c.parent_id = sc.id
                ),
                product_list AS (
                    SELECT DISTINCT p.*
                    FROM products p
                    JOIN product_categories pc ON p.id = pc.product_id
                    WHERE pc.category_id IN (SELECT id FROM subcategories)
                    ORDER BY p.id
                    LIMIT %s OFFSET %s
                ),
                category_paths AS (
                    SELECT DISTINCT pc.product_id, 
                           (
                               WITH RECURSIVE path AS (
                                   SELECT c.id, c.parent_id, c.name, 1 as level
                                   FROM categories c
                                   WHERE c.id = pc.category_id
                                   UNION ALL
                                   SELECT c.id, c.parent_id, c.name, p.level + 1
                                   FROM categories c
                                   JOIN path p ON c.id = p.parent_id
                               )
                               SELECT string_agg(name, ' > ' ORDER BY level DESC)
                               FROM path
                           ) as path
                    FROM product_categories pc
                    JOIN product_list pl ON pc.product_id = pl.id
                    GROUP BY pc.product_id, pc.category_id
                )
                SELECT 
                    pl.id,
                    pl.article,
                    pl.name,
                    pl.price,
                    pl.url,
                    pl.picture,
                    array_agg(cp.path) as category_paths
                FROM product_list pl
                LEFT JOIN category_paths cp ON pl.id = cp.product_id
                GROUP BY pl.id, pl.article, pl.name, pl.price, pl.url, pl.picture
                ORDER BY pl.id
            ''', (category_id, per_page, (page - 1) * per_page))
            
            products = cur.fetchall()
            
            return {
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page,
                'items': [{
                    'id': row['id'],
                    'article': row['article'],
                    'name': row['name'],
                    'price': float(row['price']),
                    'url': row['url'],
                    'picture': row['picture'],
                    'category_paths': row['category_paths']
                } for row in products]
            }
            
        finally:
            cur.close()
            self.put_connection(conn)

    def search_products(self, query: str) -> List[Dict]:
        """Поиск товаров"""
        conn = self.get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute('''
                WITH RECURSIVE category_paths AS (
                    SELECT pc.product_id,
                           (
                               WITH RECURSIVE path AS (
                                   SELECT c.id, c.parent_id, c.name, 1 as level
                                   FROM categories c
                                   WHERE c.id = pc.category_id
                                   UNION ALL
                                   SELECT c.id, c.parent_id, c.name, p.level + 1
                                   FROM categories c
                                   JOIN path p ON c.id = p.parent_id
                               )
                               SELECT string_agg(name, ' > ' ORDER BY level DESC)
                               FROM path
                           ) as path
                    FROM product_categories pc
                ),
                search_results AS (
                    SELECT DISTINCT ON (p.id)
                        p.*,
                        array_agg(cp.path) OVER (PARTITION BY p.id) as category_paths,
                        ts_rank(p.search_vector, plainto_tsquery('russian', %s)) as rank
                    FROM products p
                    LEFT JOIN category_paths cp ON p.id = cp.product_id
                    WHERE p.search_vector @@ plainto_tsquery('russian', %s)
                    ORDER BY p.id, rank DESC
                    LIMIT 50
                )
                SELECT *
                FROM search_results
                ORDER BY rank DESC
            ''', (query, query))
            
            products = cur.fetchall()
            
            return [{
                'id': row['id'],
                'article': row['article'],
                'name': row['name'],
                'price': float(row['price']),
                'url': row['url'],
                'picture': row['picture'],
                'category_paths': row['category_paths']
            } for row in products]
            
        finally:
            cur.close()
            self.put_connection(conn)

    def get_statistics(self) -> Dict:
        """Получение статистики каталога"""
        conn = self.get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Общая статистика
            cur.execute('''
                SELECT 
                    (SELECT COUNT(*) FROM categories) as total_categories,
                    (SELECT COUNT(*) FROM products) as total_products,
                    (SELECT COUNT(*) FROM products WHERE picture IS NOT NULL) as products_with_images,
                    (SELECT COUNT(DISTINCT category_id) FROM product_categories) as categories_with_products,
                    (SELECT AVG(price) FROM products) as average_price,
                    (SELECT MIN(price) FROM products) as min_price,
                    (SELECT MAX(price) FROM products) as max_price
            ''')
            
            stats = cur.fetchone()
            
            return {
                'total_categories': stats['total_categories'],
                'total_products': stats['total_products'],
                'products_with_images': stats['products_with_images'],
                'categories_with_products': stats['categories_with_products'],
                'average_price': round(float(stats['average_price']), 2) if stats['average_price'] else 0,
                'min_price': round(float(stats['min_price']), 2) if stats['min_price'] else 0,
                'max_price': round(float(stats['max_price']), 2) if stats['max_price'] else 0
            }
            
        finally:
            cur.close()
            self.put_connection(conn)

    def get_category_tree(self) -> List[Dict]:
        """Получение дерева категорий"""
        conn = self.get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Получаем все категории с количеством товаров, включая подкатегории
            cur.execute('''
                WITH RECURSIVE subcategories AS (
                    SELECT c.id, c.name, c.parent_id, 1 as level, ARRAY[c.id] as path
                    FROM categories c
                    WHERE c.parent_id IS NULL
                    
                    UNION ALL
                    
                    SELECT c.id, c.name, c.parent_id, s.level + 1, s.path || c.id
                    FROM categories c
                    JOIN subcategories s ON c.parent_id = s.id
                    WHERE NOT c.id = ANY(s.path)
                ),
                category_products AS (
                    SELECT 
                        c.id,
                        COUNT(DISTINCT CASE WHEN pc.product_id IS NOT NULL AND p.id IS NOT NULL THEN pc.product_id END) as direct_count,
                        (
                            WITH RECURSIVE child_categories AS (
                                SELECT id FROM categories WHERE id = c.id
                                UNION ALL
                                SELECT ch.id 
                                FROM categories ch
                                JOIN child_categories cc ON ch.parent_id = cc.id
                            )
                            SELECT COUNT(DISTINCT CASE WHEN pc2.product_id IS NOT NULL AND p2.id IS NOT NULL THEN pc2.product_id END)
                            FROM product_categories pc2
                            LEFT JOIN products p2 ON pc2.product_id = p2.id
                            WHERE pc2.category_id IN (SELECT id FROM child_categories)
                        ) as product_count,
                        array_agg(DISTINCT CASE WHEN pc.product_id IS NOT NULL AND p.id IS NOT NULL THEN pc.product_id END) FILTER (WHERE pc.product_id IS NOT NULL AND p.id IS NOT NULL) as product_ids
                    FROM categories c
                    LEFT JOIN product_categories pc ON c.id = pc.category_id
                    LEFT JOIN products p ON pc.product_id = p.id
                    GROUP BY c.id
                )
                SELECT s.id, s.name, s.parent_id, s.level, s.path,
                       COALESCE(cp.direct_count, 0) as direct_product_count,
                       COALESCE(cp.product_count, 0) as product_count,
                       cp.product_ids
                FROM subcategories s
                LEFT JOIN category_products cp ON s.id = cp.id
                ORDER BY s.path;
            ''')
            
            categories = cur.fetchall()
            
            # Создаем словарь для быстрого доступа к категориям
            categories_dict = {cat['id']: cat for cat in categories}
            
            # Функция для получения всех родительских категорий
            def get_parent_categories(category_id):
                parents = []
                current_id = category_id
                while current_id in categories_dict and categories_dict[current_id]['parent_id']:
                    parent_id = categories_dict[current_id]['parent_id']
                    if parent_id in categories_dict:
                        parents.append(parent_id)
                        current_id = parent_id
                    else:
                        break
                return parents
            
            # Добавляем продукты в родительские категории
            for cat in categories:
                if cat['product_ids'] and cat['product_ids'][0] is not None:  # Проверяем, что есть реальные товары
                    parent_ids = get_parent_categories(cat['id'])
                    for parent_id in parent_ids:
                        if parent_id in categories_dict:
                            parent = categories_dict[parent_id]
                            if parent['product_ids'] is None:
                                parent['product_ids'] = []
                            elif parent['product_ids'][0] is None:
                                parent['product_ids'] = []
                            parent['product_ids'].extend(cat['product_ids'])
            
            # Преобразуем плоский список в дерево
            def build_tree(categories_list, parent_id=None):
                tree = []
                for cat in categories_list:
                    if cat['parent_id'] == parent_id:
                        children = build_tree(categories_list, cat['id'])
                        category = {
                            'id': cat['id'],
                            'name': cat['name'],
                            'product_count': len(set(filter(None, cat['product_ids']))) if cat['product_ids'] else 0
                        }
                        if children:
                            category['children'] = children
                        tree.append(category)
                return tree
            
            # Получаем корневые категории
            root_categories = build_tree(categories)
            
            return root_categories
            
        finally:
            cur.close()
            self.put_connection(conn) 