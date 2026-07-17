import urllib.request
import urllib.parse
import json
import time
import os

# --- Настройки скрипта ---
API_KEY = "C45215C8-A7DA7F8F-193FF689-B6D7AAF2-70A3679C-282D8AD7-8617F835-D0D228D7"

# Bounding box (координаты прямоугольника для поиска)
# Формат: "долгота_мин, широта_мин, долгота_макс, широта_макс"
# Пример: Центр Москвы
BBOX = "37.60,55.70,37.65,55.75"

# Категории для поиска.
# 2390 - заброшенный объект
# 8680 - бункер
# 5701 - убежище
# 44690 - бомбоубежище
# 64188 - бомбоубежище (air-raid shelter)
CATEGORIES = ["2390", "8680", "5701", "44690", "64188"]

# Имя файла для сохранения результатов
OUTPUT_FILE = "abandoned_places.json"

# Лимит: 100 запросов за 5 минут. Это значит 1 запрос каждые 3 секунды.
# Для безопасности ставим 3.2 секунды.
DELAY_BETWEEN_REQUESTS = 3.2


def make_api_request(url):
    """
    Выполняет HTTP-запрос к API и возвращает разобранный JSON.
    Содержит обработку ошибок и автоматическую паузу.
    """
    print(f"Отправка запроса: {url}")

    # Задержка перед каждым запросом, чтобы не превысить лимит
    time.sleep(DELAY_BETWEEN_REQUESTS)

    try:
        # Указываем User-Agent, чтобы сервер не блокировал нас как подозрительного бота
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)

        # Читаем данные и декодируем из UTF-8
        raw_data = response.read().decode('utf-8')
        data = json.loads(raw_data)

        # Проверяем, вернул ли API какую-либо ошибку
        if "debug" in data and isinstance(data["debug"], list):
            print(f"Внимание, ошибка от API: {data['debug']}")
            return None
        elif "debug" in data and isinstance(data["debug"], dict):
            print(f"Внимание, ошибка от API: {data['debug'].get('message')}")
            return None

        return data

    except Exception as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None


def search_objects_in_bbox(bbox, category_id, page=1):
    """
    Ищет объекты в заданном прямоугольнике по ID категории.
    Возвращает список базовых данных об объектах на указанной странице.
    """
    url = (f"http://api.wikimapia.org/?function=box"
           f"&bbox={bbox}"
           f"&category={category_id}"
           f"&key={API_KEY}"
           f"&format=json"
           f"&page={page}")

    return make_api_request(url)


def get_object_details(object_id):
    """
    Получает подробную информацию об объекте по его ID.
    (Нужно для получения точного адреса и всех категорий)
    """
    url = (f"http://api.wikimapia.org/?function=place.getbyid"
           f"&id={object_id}"
           f"&key={API_KEY}"
           f"&format=json")

    return make_api_request(url)


def main():
    print("Начинаем сбор данных с Wikimapia...")

    all_places = {} # Используем словарь (по ID), чтобы избежать дубликатов

    # 1. Сначала ищем объекты по всем нужным категориям
    for cat in CATEGORIES:
        print(f"\n--- Поиск по категории {cat} ---")
        page = 1

        while True:
            # Запрашиваем страницу с результатами
            data = search_objects_in_bbox(BBOX, cat, page)

            # Если произошла ошибка или данные пустые - прерываем цикл для этой категории
            if not data or "folder" not in data:
                print("Не удалось получить данные или достигнут конец результатов.")
                break

            places_on_page = data["folder"]

            if not places_on_page:
                print(f"На странице {page} больше нет объектов.")
                break

            print(f"Найдено объектов на странице {page}: {len(places_on_page)}")

            for place in places_on_page:
                obj_id = place["id"]
                if obj_id not in all_places:
                    all_places[obj_id] = {
                        "id": obj_id,
                        "name": place.get("name", "Без названия"),
                        # Мы пока сохраним только базовые координаты, позже обновим
                        "coordinates": {
                            "lat": place.get("location", {}).get("lat"),
                            "lon": place.get("location", {}).get("lon")
                        }
                    }

            # Проверяем, есть ли еще страницы.
            # API возвращает 'count' (сколько вернул) и 'found' (сколько всего)
            # Если вернулось меньше 100 объектов (обычно это лимит на страницу), значит это последняя страница
            if len(places_on_page) < 100: # По умолчанию Wikimapia может отдавать 50-100 элементов
                # Проверим, достигли ли мы конца.
                # data["found"] содержит общее количество.
                break

            page += 1

    print(f"\nВсего уникальных объектов найдено (базовые данные): {len(all_places)}")

    # 2. Теперь получаем подробные данные (адрес, теги/категории) для каждого объекта
    # Внимание: это займет время из-за задержек (3.2 сек на каждый объект)
    final_results = []

    print("\nСбор детальной информации для каждого объекта...")
    for idx, (obj_id, base_info) in enumerate(all_places.items(), 1):
        print(f"[{idx}/{len(all_places)}] Получение деталей для ID {obj_id}...")

        details = get_object_details(obj_id)

        if details:
            # Пытаемся сформировать удобочитаемый адрес
            location = details.get("location", {})
            address_parts = []
            if location.get("country"): address_parts.append(location["country"])
            if location.get("state"): address_parts.append(location["state"])
            if location.get("place"): address_parts.append(location["place"])

            # В Wikimapia точного адреса (улица/дом) в этом ответе может не быть,
            # но мы собираем всю информацию о расположении.
            address_str = ", ".join(address_parts) if address_parts else "Нет адреса"

            # Извлекаем категории/теги
            categories = [tag["title"] for tag in details.get("tags", []) if "title" in tag]

            # Обновляем координаты на всякий случай
            lat = location.get("lat") or base_info["coordinates"]["lat"]
            lon = location.get("lon") or base_info["coordinates"]["lon"]

            # Собираем итоговый объект
            final_obj = {
                "id": obj_id,
                "name": details.get("title", base_info["name"]),
                "coordinates": {
                    "lat": lat,
                    "lon": lon
                },
                "address": address_str,
                "categories": categories
            }
            final_results.append(final_obj)
        else:
            # Если не удалось получить детали, сохраняем хотя бы базовые данные
            final_results.append({
                "id": base_info["id"],
                "name": base_info["name"],
                "coordinates": base_info["coordinates"],
                "address": "Нет данных",
                "categories": []
            })

    # 3. Сохранение данных в JSON
    print(f"\nСохранение данных в файл {OUTPUT_FILE}...")
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            # indent=4 делает файл читаемым (с отступами)
            # ensure_ascii=False сохраняет кириллицу (русские буквы) в нормальном виде
            json.dump(final_results, f, indent=4, ensure_ascii=False)
        print("Готово! Данные успешно сохранены.")
    except Exception as e:
        print(f"Ошибка при сохранении файла: {e}")

if __name__ == "__main__":
    main()
