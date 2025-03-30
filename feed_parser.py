import xml.etree.ElementTree as ET
from typing import Dict, Set
from database import CatalogDatabase
import logging
import time
from collections import defaultdict

class FeedParser:
    def __init__(self, xml_file: str, db: CatalogDatabase):
        self.xml_file = xml_file
        self.db = db
        self.processed_categories: Set[int] = set()
        self.processed_products: Set[str] = set()
        self.category_tree = {}
        self.all_categories = {}
        
        # Настройка логирования
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # Добавляем обработчик для вывода в консоль
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(handler)

    def _collect_all_categories(self, categories_element) -> Dict:
        """Сбор всех категорий, включая родительские"""
        categories = {}
        parent_refs = set()

        # Первый проход: собираем все категории и ссылки на родителей
        for category in categories_element.findall('category'):
            try:
                category_id = int(category.get('id'))
                parent_id = category.get('parentId')
                parent_id = int(parent_id) if parent_id is not None else None
                name = category.text.strip() if category.text else ''

                categories[category_id] = {
                    'id': category_id,
                    'name': name,
                    'parent_id': parent_id,
                    'children': set()
                }

                if parent_id is not None:
                    parent_refs.add(parent_id)

            except (ValueError, TypeError) as e:
                self.logger.error(f"Ошибка при обработке категории {category.get('id')}: {str(e)}")
                continue

        # Создаем отсутствующие родительские категории
        for parent_id in parent_refs:
            if parent_id not in categories:
                self.logger.info(f"Создаем отсутствующую родительскую категорию {parent_id}")
                categories[parent_id] = {
                    'id': parent_id,
                    'name': f'Категория {parent_id}',
                    'parent_id': None,
                    'children': set()
                }

        # Строим связи между категориями
        for category in categories.values():
            if category['parent_id'] is not None:
                parent = categories.get(category['parent_id'])
                if parent:
                    parent['children'].add(category['id'])

        return categories

    def _process_categories(self):
        """Рекурсивная обработка категорий"""
        def process_category(category_id):
            if category_id in self.processed_categories:
                return

            category = self.all_categories[category_id]
            
            # Сначала обрабатываем родительскую категорию
            if category['parent_id'] is not None:
                process_category(category['parent_id'])
            
            # Добавляем текущую категорию
            try:
                self.logger.debug(f"Добавляем категорию: id={category_id}, name='{category['name']}', parent_id={category['parent_id']}")
                self.db.add_category(
                    category_id=category_id,
                    name=category['name'],
                    parent_id=category['parent_id']
                )
                self.processed_categories.add(category_id)
                
                # Обрабатываем дочерние категории
                for child_id in category['children']:
                    process_category(child_id)
            
            except Exception as e:
                self.logger.error(f"Ошибка при добавлении категории {category_id}: {str(e)}")

        # Обрабатываем все категории
        for category_id in self.all_categories:
            if category_id not in self.processed_categories:
                process_category(category_id)

    def parse(self):
        """Парсинг XML-фида"""
        self.logger.info("Начинаем парсинг XML...")
        start_time = time.time()
        
        try:
            tree = ET.parse(self.xml_file)
            root = tree.getroot()
            shop = root.find('shop')
            
            if shop is None:
                raise ValueError("Не найден элемент shop в XML")
            
            categories = shop.find('categories')
            offers = shop.find('offers')
            
            if categories is None:
                raise ValueError("Не найден элемент categories в XML")
            if offers is None:
                raise ValueError("Не найден элемент offers в XML")
            
            # Собираем все категории
            self.all_categories = self._collect_all_categories(categories)
            self.logger.info(f"Найдено {len(self.all_categories)} категорий")
            
            # Обрабатываем категории
            self._process_categories()
            self.logger.info(f"Обработано {len(self.processed_categories)} категорий")
            
            # Обрабатываем товары
            self._process_products(offers)
            
            end_time = time.time()
            self.logger.info(f"Парсинг завершен за {end_time - start_time:.2f} секунд")
        
        except ET.ParseError as e:
            self.logger.error(f"Ошибка при парсинге XML файла: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при парсинге: {str(e)}")
            raise

    def _process_products(self, offers_element):
        """Обработка товаров"""
        if offers_element is None:
            return
        
        processed_count = 0
        error_count = 0
        skipped_count = 0
        
        for offer in offers_element.findall('offer'):
            try:
                product_id = offer.get('id')
                if not product_id:
                    self.logger.warning("Пропущен товар без ID")
                    skipped_count += 1
                    continue
                
                if product_id in self.processed_products:
                    continue
                
                # Получаем основные данные товара
                article = offer.find('vendorCode')
                article = article.text if article is not None else product_id
                
                name = offer.find('name')
                if name is None or not name.text:
                    self.logger.warning(f"Пропускаем товар {product_id}: отсутствует название")
                    skipped_count += 1
                    continue
                name = name.text.strip()
                
                price = offer.find('price')
                if price is None or not price.text:
                    self.logger.warning(f"Пропускаем товар {product_id}: отсутствует цена")
                    skipped_count += 1
                    continue
                try:
                    price = float(price.text)
                except (ValueError, TypeError):
                    self.logger.warning(f"Пропускаем товар {product_id}: некорректная цена")
                    skipped_count += 1
                    continue
                
                url = offer.find('url')
                url = url.text.strip() if url is not None and url.text else None
                
                picture = offer.find('picture')
                picture = picture.text.strip() if picture is not None and picture.text else None
                
                # Получаем категории товара
                category_ids = set()  # Используем set для уникальных категорий
                
                # Проверяем оба варианта указания категорий
                # Вариант 1: категории внутри тега categories
                categories_element = offer.find('categories')
                if categories_element is not None:
                    for category in categories_element.findall('categoryId'):
                        try:
                            category_id = int(category.text)
                            if category_id in self.all_categories:
                                category_ids.add(category_id)
                        except (ValueError, TypeError):
                            continue
                
                # Вариант 2: categoryId напрямую в offer
                category = offer.find('categoryId')
                if category is not None and category.text:
                    try:
                        category_id = int(category.text)
                        if category_id in self.all_categories:
                            category_ids.add(category_id)
                    except (ValueError, TypeError):
                        pass
                
                # Добавляем родительские категории
                parent_categories = set()
                for category_id in category_ids.copy():
                    current_id = category_id
                    while current_id is not None:
                        category = self.all_categories.get(current_id)
                        if category and category['parent_id']:
                            parent_categories.add(category['parent_id'])
                            current_id = category['parent_id']
                        else:
                            break
                
                # Объединяем прямые и родительские категории
                category_ids.update(parent_categories)
                
                if not category_ids:
                    self.logger.warning(f"Пропускаем товар {product_id}: нет действительных категорий")
                    skipped_count += 1
                    continue
                
                # Добавляем товар в базу
                self.db.add_product(
                    product_id=product_id,
                    article=article,
                    name=name,
                    price=price,
                    url=url,
                    picture=picture,
                    category_ids=list(category_ids)
                )
                
                self.processed_products.add(product_id)
                processed_count += 1
                
                if processed_count % 1000 == 0:
                    self.logger.info(f"Обработано {processed_count} товаров (ошибок: {error_count}, пропущено: {skipped_count})")
            
            except Exception as e:
                error_count += 1
                self.logger.error(f"Ошибка при обработке товара {offer.get('id')}: {str(e)}")
                continue
        
        self.logger.info(f"Обработка товаров завершена. Всего: {processed_count}, ошибок: {error_count}, пропущено: {skipped_count}") 