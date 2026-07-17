import urllib.request
import urllib.parse
import json
import time
import urllib.error
import socket
import sys
import os

# --- Настройки скрипта ---
API_KEY = "C45215C8-A7DA7F8F-193FF689-B6D7AAF2-70A3679C-282D8AD7-8617F835-D0D228D7"

REGIONS = {
    "Санкт-Петербург": "29.50,59.70,30.70,60.20",
    "Москва": "37.30,55.50,37.90,55.90",
    "Воронежская область": "38.10,49.80,43.10,52.10"
}

CATEGORIES = [
    "2390", "44923", "8680", "5701", "44690", "64188", "73125",
    "168", "5163", "61405", "36560", "45762"
]

OUTPUT_FILE = "abandoned_and_towers.json"
PROGRESS_FILE = "progress.json"
DELAY_BETWEEN_REQUESTS = 3.5
GRID_STEP = 0.1  # Размер сетки в градусах

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Ошибка загрузки {PROGRESS_FILE}: {e}")
    return set()

def save_progress(progress_set):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(progress_set), f, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения {PROGRESS_FILE}: {e}")

def load_data():
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_data(data):
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения {OUTPUT_FILE}: {e}")

def split_bbox(bbox_str, step):
    """
    Разбивает большой прямоугольник на маленькие сетки.
    """
    lon_min, lat_min, lon_max, lat_max = map(float, bbox_str.split(','))
    grids = []

    current_lon = lon_min
    while current_lon < lon_max:
        next_lon = min(current_lon + step, lon_max)
        current_lat = lat_min
        while current_lat < lat_max:
            next_lat = min(current_lat + step, lat_max)
            grids.append(f"{current_lon:.4f},{current_lat:.4f},{next_lon:.4f},{next_lat:.4f}")
            current_lat = next_lat
        current_lon = next_lon

    return grids

def countdown_timer(seconds):
    """
    Выводит обратный отсчет в консоль на одной строке.
    """
    for i in range(seconds, 0, -1):
        sys.stdout.write(f"\rЛимит исчерпан, ждем {seconds} секунд: {i:03d}... ")
        sys.stdout.flush()
        time.sleep(1)
    print("\nПродолжаем работу.")

class ApiLimitReached(Exception):
    pass

def make_api_request(url, retries=5):
    """
    Выполняет HTTP-запрос. При лимите вызывает ожидание.
    """
    for attempt in range(retries):
        time.sleep(DELAY_BETWEEN_REQUESTS)

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=15)

            raw_data = response.read().decode('utf-8')
            data = json.loads(raw_data)

            if "debug" in data:
                err_msg = ""
                if isinstance(data["debug"], list) and len(data["debug"]) > 0:
                    err_msg = str(data["debug"][0].get('message', data["debug"][0]))
                elif isinstance(data["debug"], dict):
                    err_msg = data["debug"].get('message', str(data["debug"]))

                if "limit" in err_msg.lower():
                    countdown_timer(305) # 5 минут + 5 сек
                    continue # Повторяем запрос
                else:
                    print(f"Внимание, ошибка от API: {err_msg}")
                    return None

            return data

        except urllib.error.URLError as e:
            print(f"Ошибка сети (попытка {attempt+1}/{retries}): {e.reason}")
            time.sleep(5)
        except socket.timeout:
            print(f"Таймаут (попытка {attempt+1}/{retries})")
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
    print("Начинаем сбор данных с Wikimapia (режим малых квадратов)...")

    progress = load_progress()
    all_places_list = load_data()
    # Конвертируем список в словарь для быстрого поиска/обновления
    all_places = {str(item["id"]): item for item in all_places_list}

    # ФАЗА 1: Поиск объектов (базовые данные)
    for region_name, bbox_str in REGIONS.items():
        print(f"\n=== Регион: {region_name} ===")
        grids = split_bbox(bbox_str, GRID_STEP)

        for cat in CATEGORIES:
            for grid_idx, grid in enumerate(grids, 1):
                task_key = f"search_{region_name}_cat{cat}_grid{grid}"

                if task_key in progress:
                    # Пропускаем, если уже обработали этот квадрат для этой категории
                    continue

                print(f"Поиск: Кат {cat} | Сетка {grid_idx}/{len(grids)} [{grid}]")
                page = 1

                while True:
                    data = search_objects_in_bbox(grid, cat, page)

                    if not data or "folder" not in data:
                        break

                    places_on_page = data["folder"]
                    if not places_on_page:
                        break

                    for place in places_on_page:
                        obj_id = str(place["id"])
                        if obj_id not in all_places:
                            all_places[obj_id] = {
                                "id": obj_id,
                                "region": region_name,
                                "name": place.get("name", "Без названия"),
                                "coordinates": {
                                    "lat": place.get("location", {}).get("lat"),
                                    "lon": place.get("location", {}).get("lon")
                                },
                                "details_fetched": False
                            }

                    if len(places_on_page) < 100:
                        break
                    page += 1

                # Отмечаем квадрат как пройденный и сохраняем прогресс и данные
                progress.add(task_key)
                save_progress(progress)
                save_data(list(all_places.values()))

    # ФАЗА 2: Сбор деталей
    print("\nСбор детальной информации для каждого объекта...")
    total_objects = len(all_places)

    for idx, (obj_id, base_info) in enumerate(all_places.items(), 1):
        if base_info.get("details_fetched"):
            continue

        print(f"[{idx}/{total_objects}] Детали для ID {obj_id} ({base_info['name']})...")
        details = get_object_details(obj_id)

        if details:
            location = details.get("location", {})
            address_parts = [location[k] for k in ["country", "state", "place"] if location.get(k)]

            base_info["address"] = ", ".join(address_parts) if address_parts else "Нет адреса"
            base_info["categories"] = [tag["title"] for tag in details.get("tags", []) if "title" in tag]
            base_info["name"] = details.get("title", base_info["name"])

            if location.get("lat"): base_info["coordinates"]["lat"] = location["lat"]
            if location.get("lon"): base_info["coordinates"]["lon"] = location["lon"]
        else:
            base_info["address"] = "Нет данных"
            base_info["categories"] = []

        base_info["details_fetched"] = True

        # Сохраняем каждый шаг, чтобы ничего не потерять
        save_data(list(all_places.values()))

    print("\nГотово! Все данные успешно собраны и сохранены.")

if __name__ == "__main__":
    main()
