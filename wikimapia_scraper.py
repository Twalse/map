import urllib.request
import urllib.parse
import json
import time
import urllib.error
import socket

# --- Настройки скрипта ---
API_KEY = "C45215C8-A7DA7F8F-193FF689-B6D7AAF2-70A3679C-282D8AD7-8617F835-D0D228D7"

# Bounding boxes (координаты прямоугольников для поиска)
# Формат: "долгота_мин, широта_мин, долгота_макс, широта_макс"
REGIONS = {
    "Санкт-Петербург": "29.50,59.70,30.70,60.20",
    "Москва": "37.30,55.50,37.90,55.90",
    "Воронежская область": "38.10,49.80,43.10,52.10"
}

# Категории для поиска.
# Заброшенное и убежища:
# 2390 - abandoned / shut down (заброшенное)
# 44923 - abandoned settlement (заброшенное поселение)
# 8680 - bunker (бункер)
# 5701 - shelter (убежище)
# 44690 - fallout shelter / bombshelter (бомбоубежище)
# 64188 - air-raid shelter (бомбоубежище)
# 73125 - abandoned mine/quarry (заброшенная шахта/карьер)
#
# Вышки и башни (интернет, радио, сигнальные):
# 168 - tower (башня, вышка)
# 5163 - telecommunication / radio antenna (радио/сотовая вышка)
# 61405 - observation tower (смотровая вышка)
# 36560 - water tower (водонапорная башня)
# 45762 - electricity pylon / transmission tower (опора ЛЭП)

CATEGORIES = [
    "2390", "44923", "8680", "5701", "44690", "64188", "73125",
    "168", "5163", "61405", "36560", "45762"
]

# Имя файла для сохранения результатов
OUTPUT_FILE = "abandoned_and_towers.json"

# Лимит: 100 запросов за 5 минут. Это значит 1 запрос каждые 3 секунды.
# Ставим 3.5 секунды для безопасности.
DELAY_BETWEEN_REQUESTS = 3.5


def make_api_request(url, retries=5):
    """
    Выполняет HTTP-запрос к API с обработкой ошибок и повторными попытками.
    """
    print(f"Отправка запроса: {url}")

    for attempt in range(retries):
        # Задержка перед каждым запросом
        time.sleep(DELAY_BETWEEN_REQUESTS)

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            # Добавлен таймаут (15 секунд), чтобы скрипт не зависал и не падал при долгом ответе
            response = urllib.request.urlopen(req, timeout=15)

            raw_data = response.read().decode('utf-8')
            data = json.loads(raw_data)

            # Проверяем, вернул ли API ошибку лимита ключа
            if "debug" in data:
                err_msg = ""
                if isinstance(data["debug"], list) and len(data["debug"]) > 0:
                    err_msg = str(data["debug"][0].get('message', data["debug"][0]))
                elif isinstance(data["debug"], dict):
                    err_msg = data["debug"].get('message', str(data["debug"]))

                print(f"Внимание, ошибка от API: {err_msg}")

                # Если превышен лимит, ждем 5 минут и пробуем снова
                if "limit" in err_msg.lower():
                    print("Достигнут лимит API (100 запросов/5 мин). Ждем 5 минут...")
                    time.sleep(305) # Ждем 5 минут + 5 сек
                    continue # Повторяем запрос
                return None

            return data

        except urllib.error.URLError as e:
            print(f"Ошибка сети (попытка {attempt+1}/{retries}): {e.reason}")
            time.sleep(5) # При ошибке сети просто подождем 5 секунд
        except socket.timeout:
            print(f"Таймаут ожидания ответа (попытка {attempt+1}/{retries})")
            time.sleep(5)
        except Exception as e:
            print(f"Непредвиденная ошибка (попытка {attempt+1}/{retries}): {e}")
            time.sleep(5)

    print(f"Не удалось выполнить запрос после {retries} попыток.")
    return None


def search_objects_in_bbox(bbox, category_id, page=1):
    url = (f"http://api.wikimapia.org/?function=box"
           f"&bbox={bbox}"
           f"&category={category_id}"
           f"&key={API_KEY}"
           f"&format=json"
           f"&page={page}")
    return make_api_request(url)


def get_object_details(object_id):
    url = (f"http://api.wikimapia.org/?function=place.getbyid"
           f"&id={object_id}"
           f"&key={API_KEY}"
           f"&format=json")
    return make_api_request(url)


def main():
    print("Начинаем сбор данных с Wikimapia...")
    all_places = {} # словарь по ID

    # 1. Поиск по всем регионам и категориям
    for region_name, bbox in REGIONS.items():
        print(f"\n=====================================")
        print(f"=== Поиск в регионе: {region_name} ===")
        print(f"=====================================")

        for cat in CATEGORIES:
            print(f"\n--- Категория {cat} ({region_name}) ---")
            page = 1

            while True:
                data = search_objects_in_bbox(bbox, cat, page)

                if not data or "folder" not in data:
                    print("Данные не получены (конец результатов или ошибка).")
                    break

                places_on_page = data["folder"]

                if not places_on_page:
                    break

                print(f"Найдено объектов на странице {page}: {len(places_on_page)}")

                for place in places_on_page:
                    obj_id = place["id"]
                    if obj_id not in all_places:
                        all_places[obj_id] = {
                            "id": obj_id,
                            "region": region_name,
                            "name": place.get("name", "Без названия"),
                            "coordinates": {
                                "lat": place.get("location", {}).get("lat"),
                                "lon": place.get("location", {}).get("lon")
                            }
                        }

                if len(places_on_page) < 100:
                    break

                page += 1

    total_objects = len(all_places)
    print(f"\nВсего уникальных объектов найдено (базовые данные): {total_objects}")

    # 2. Получение детальной информации
    final_results = []
    print("\nСбор детальной информации для каждого объекта...")

    for idx, (obj_id, base_info) in enumerate(all_places.items(), 1):
        print(f"[{idx}/{total_objects}] Детали для ID {obj_id} ({base_info['name']})...")
        details = get_object_details(obj_id)

        if details:
            location = details.get("location", {})
            address_parts = []
            for k in ["country", "state", "place"]:
                if location.get(k): address_parts.append(location[k])

            address_str = ", ".join(address_parts) if address_parts else "Нет адреса"
            categories = [tag["title"] for tag in details.get("tags", []) if "title" in tag]

            lat = location.get("lat") or base_info["coordinates"]["lat"]
            lon = location.get("lon") or base_info["coordinates"]["lon"]

            final_obj = {
                "id": obj_id,
                "region": base_info["region"],
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
            final_results.append({
                "id": base_info["id"],
                "region": base_info["region"],
                "name": base_info["name"],
                "coordinates": base_info["coordinates"],
                "address": "Нет данных",
                "categories": []
            })

    # 3. Сохранение
    print(f"\nСохранение данных в файл {OUTPUT_FILE}...")
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_results, f, indent=4, ensure_ascii=False)
        print("Готово! Данные успешно сохранены.")
    except Exception as e:
        print(f"Ошибка при сохранении файла: {e}")

if __name__ == "__main__":
    main()
