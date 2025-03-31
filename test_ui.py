from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import time
import json
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CatalogUITester:
    def __init__(self):
        self.setup_driver()
        
    def setup_driver(self):
        """Инициализация и настройка драйвера Chrome"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')  # Запуск в фоновом режиме
        options.add_argument('--window-size=1920,1080')  # Установка размера окна
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)
        
    def test_page_scroll(self):
        """Тестирование прокрутки страницы"""
        try:
            # Прокрутка в конец страницы
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)  # Ждем завершения прокрутки
            
            # Прокрутка в начало страницы
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            # Плавная прокрутка через JavaScript
            self.driver.execute_script("""
                window.scrollTo({
                    top: document.body.scrollHeight,
                    behavior: 'smooth'
                });
            """)
            time.sleep(2)
            
            return True
        except Exception as e:
            logger.error(f"Error during scroll testing: {str(e)}")
            return False
            
    def test_categories_api(self):
        """Тестирование API категорий"""
        try:
            categories_response = self.driver.execute_script(
                "return fetch('/api/categories').then(r => r.json())"
            )
            logger.info("Categories API Response: " + json.dumps(categories_response, indent=2, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error testing categories API: {str(e)}")
            return False
            
    def test_statistics_api(self):
        """Тестирование API статистики"""
        try:
            stats_response = self.driver.execute_script(
                "return fetch('/api/statistics').then(r => r.json())"
            )
            logger.info("Statistics API Response: " + json.dumps(stats_response, indent=2, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error testing statistics API: {str(e)}")
            return False
            
    def test_categories_ui(self):
        """Тестирование UI категорий"""
        try:
            categories_container = self.wait.until(
                EC.presence_of_element_located((By.ID, "categories"))
            )
            
            # Проверяем структуру категорий
            categories_html = categories_container.get_attribute('innerHTML')
            logger.info("Categories HTML structure found")
            
            # Проверяем кликабельность категорий
            category_items = self.driver.find_elements(By.CLASS_NAME, "category-item")
            if category_items:
                category_items[0].click()
                time.sleep(1)  # Ждем обновления UI
                logger.info("Category click test passed")
            
            return True
        except Exception as e:
            logger.error(f"Error testing categories UI: {str(e)}")
            return False
    
    def run_tests(self):
        """Запуск всех тестов"""
        try:
            logger.info("Starting UI tests...")
            self.driver.get('http://localhost:5003')
            
            # Выполняем все тесты
            tests = [
                self.test_categories_ui,
                self.test_categories_api,
                self.test_statistics_api,
                self.test_page_scroll
            ]
            
            results = []
            for test in tests:
                test_name = test.__name__
                logger.info(f"Running {test_name}...")
                result = test()
                results.append((test_name, result))
                
            # Выводим результаты
            logger.info("\nTest Results:")
            for test_name, result in results:
                status = "PASSED" if result else "FAILED"
                logger.info(f"{test_name}: {status}")
                
            return all(result for _, result in results)
            
        except Exception as e:
            logger.error(f"Error during test execution: {str(e)}")
            return False
            
        finally:
            self.driver.quit()

if __name__ == "__main__":
    tester = CatalogUITester()
    success = tester.run_tests()
    exit(0 if success else 1) 