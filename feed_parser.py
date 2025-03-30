import xml.etree.ElementTree as ET
from typing import Dict, Set
from database import CatalogDatabase

class FeedParser:
    def __init__(self, xml_file: str, db: CatalogDatabase):
        self.xml_file = xml_file
        self.db = db
        
    def parse(self):
        """Парсинг XML-фида и заполнение базы данных"""
        print("Начинаем парсинг XML...")
        
        # Очищаем базу перед заполнением
        self.db.clear_data()
        
        # Парсим XML
        tree = ET.parse(self.xml_file)
        root = tree.getroot()
        
        # Находим элемент shop
        shop = root.find('shop')
        if not shop:
            raise ValueError("Не найден элемент shop в XML")
        
        print("Обрабатываем категории...")
        # Сначала добавляем все категории
        self._process_categories(shop)
        
        print("Обрабатываем товары...")
        # Затем добавляем товары
        self._process_products(shop)
        
        print("Парсинг завершен")
        
    def _process_categories(self, shop: ET.Element):
        """Обработка категорий из XML"""
        # Находим секцию categories
        categories_section = shop.find('categories')
        if not categories_section:
            raise ValueError("Не найдена секция categories в XML")
        
        # Сначала собираем все категории
        categories: Dict[str, Dict] = {}
        
        # Получаем все категории
        for category in categories_section.findall('category'):
            cat_id = category.get('id')
            if cat_id and category.text:
                categories[cat_id] = {
                    'id': int(cat_id),
                    'name': category.text.strip(),
                    'parent_id': int(category.get('parentId')) if category.get('parentId') else None
                }
        
        print(f"Найдено {len(categories)} категорий")
        
        # Добавляем категории в базу
        for category in categories.values():
            self.db.add_category(
                category_id=category['id'],
                name=category['name'],
                parent_id=category['parent_id']
            )
    
    def _process_products(self, shop: ET.Element):
        """Обработка товаров из XML"""
        # Находим секцию offers
        offers_section = shop.find('offers')
        if not offers_section:
            raise ValueError("Не найдена секция offers в XML")
        
        count = 0
        for offer in offers_section.findall('offer'):
            try:
                # Получаем основные данные о товаре
                article = offer.get('id')  # Используем id оффера как артикул
                url = offer.find('url')
                price = offer.find('price')
                name = offer.find('name')
                
                # Проверяем наличие обязательных полей
                if not all([article, url is not None, price is not None, name is not None]):
                    continue
                
                if url.text and price.text and name.text:
                    # Получаем категории товара
                    category_ids = []
                    
                    # Проверяем оба варианта расположения categoryId
                    categories_section = offer.find('categories')
                    if categories_section is not None:
                        # Если есть секция categories
                        for category in categories_section.findall('categoryId'):
                            if category.text:
                                category_ids.append(int(category.text))
                    else:
                        # Если categoryId находится напрямую в offer
                        for category in offer.findall('categoryId'):
                            if category.text:
                                category_ids.append(int(category.text))
                    
                    # Получаем изображения товара
                    images = []
                    for picture in offer.findall('picture'):
                        if picture.text:
                            images.append(picture.text)
                    
                    # Добавляем товар в базу
                    self.db.add_product(
                        article=article,
                        name=name.text,
                        price=float(price.text),
                        url=url.text.strip(),
                        category_ids=category_ids,
                        images=images
                    )
                    count += 1
                    if count % 1000 == 0:
                        print(f"Обработано {count} товаров")
            except Exception as e:
                print(f"Ошибка при обработке товара {offer.get('id')}: {str(e)}")
                continue
        
        print(f"Всего обработано {count} товаров") 