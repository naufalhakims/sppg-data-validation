import argparse
import csv
import math
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


RESULT_COLUMNS = [
    "Status",
    "GMaps_Nama",
    "GMaps_Alamat",
    "GMaps_Longitude",
    "GMaps_Latitude",
    "GMaps_Rating",
    "GMaps_Reviews",
    "GMaps_Foto",
    "GMaps_Foto_URL",
    "GMaps_Distance_Meter",
    "GMaps_Name_Score",
    "GMaps_Source",
    "GMaps_Query",
    "GMaps_Candidate_Count",
    "GMaps_Filtered_Candidate_Count",
    "GMaps_Is_SPPG_Like",
    "GMaps_Error",
]


COORD_RE = re.compile(r"^-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$")
SPPG_LIKE_PHRASES = [
    "sppg",
    "satuan pelayanan pemenuhan gizi",
    "pelayanan pemenuhan gizi",
    "satuan pelayanan gizi",
    "pemenuhan gizi",
    "dapur mbg",
    "mbg",
]


def clean_text(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_name(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(
        r"\b(sppg|satuan|pelayanan|pemenuhan|gizi|dapur|mbg|program|makan|bergizi|gratis|kab|kabupaten|kec|kecamatan)\b",
        " ",
        value,
    )
    return clean_text(value)


def normalize_keyword_text(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return clean_text(value)


def is_sppg_like_text(value):
    text = normalize_keyword_text(value)
    if not text:
        return False
    if any(phrase in text for phrase in SPPG_LIKE_PHRASES):
        return True

    tokens = set(text.split())
    return {"satuan", "pelayanan", "gizi"}.issubset(tokens) or {"pemenuhan", "gizi"}.issubset(tokens)


def place_is_sppg_like(place):
    combined = " ".join(
        [
            place.get("candidate_name", ""),
            place.get("name", ""),
            place.get("address", ""),
        ]
    )
    return is_sppg_like_text(combined)


def levenshtein_distance(left, right):
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def name_score(expected, actual):
    expected_norm = normalize_name(expected)
    actual_norm = normalize_name(actual)
    if not expected_norm or not actual_norm:
        return 0.0
    if expected_norm in actual_norm or actual_norm in expected_norm:
        return 1.0

    expected_tokens = set(expected_norm.split())
    actual_tokens = set(actual_norm.split())
    token_score = len(expected_tokens & actual_tokens) / max(len(expected_tokens), 1)
    ratio_score = SequenceMatcher(None, expected_norm, actual_norm).ratio()
    max_len = max(len(expected_norm), len(actual_norm), 1)
    levenshtein_score = 1 - (levenshtein_distance(expected_norm, actual_norm) / max_len)
    return max(token_score, ratio_score, levenshtein_score)


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_driver(args):
    options = Options()
    if args.headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=id-ID")
    options.add_argument("--window-size=1366,900")
    if args.profile_dir:
        Path(args.profile_dir).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={Path(args.profile_dir).resolve()}")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(args.timeout)
    return driver


def wait_for_maps(driver, timeout):
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: "google." in d.current_url.lower() or "maps" in d.title.lower())
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))


def click_consent_if_present(driver):
    labels = [
        "Accept all",
        "I agree",
        "Saya setuju",
        "Terima semua",
        "Setuju",
    ]
    for label in labels:
        xpath = f"//button//*[contains(normalize-space(.), '{label}')]/ancestor::button"
        buttons = driver.find_elements(By.XPATH, xpath)
        if buttons:
            try:
                buttons[0].click()
                time.sleep(2)
                return
            except WebDriverException:
                pass


def first_text(driver, selectors):
    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            text = clean_text(element.text or element.get_attribute("aria-label"))
            if text:
                return text
    return ""


def extract_title(driver):
    title = first_text(
        driver,
        [
            (By.CSS_SELECTOR, "h1.DUwDvf"),
            (By.CSS_SELECTOR, "h1"),
            (By.CSS_SELECTOR, "[role='main'] h1"),
        ],
    )
    title = re.sub(r"^Hasil untuk\s+", "", title, flags=re.IGNORECASE)
    if COORD_RE.match(title) or title.lower() in {"dropped pin", "pin dipasang"}:
        return ""
    return title


def extract_address(driver):
    selectors = [
        (By.CSS_SELECTOR, "button[data-item-id='address']"),
        (By.CSS_SELECTOR, "button[aria-label^='Alamat:']"),
        (By.CSS_SELECTOR, "button[aria-label^='Address:']"),
        (By.XPATH, "//*[contains(@aria-label, 'Alamat:') or contains(@aria-label, 'Address:')]"),
    ]
    text = first_text(driver, selectors)
    text = re.sub(r"^(Alamat|Address):\s*", "", text, flags=re.IGNORECASE)
    return clean_text(text)


def extract_rating(driver):
    candidates = []
    selectors = [
        (By.CSS_SELECTOR, "div.F7nice span[aria-hidden='true']"),
        (By.CSS_SELECTOR, "span.MW4etd"),
        (By.XPATH, "//*[contains(@aria-label, 'bintang') or contains(@aria-label, 'stars')]"),
    ]
    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            text = clean_text(element.text or element.get_attribute("aria-label"))
            if text:
                candidates.append(text)
    for text in candidates:
        match = re.search(r"(\d+(?:[,.]\d+)?)", text)
        if match:
            return match.group(1).replace(",", ".")
    return ""


def parse_review_count(text):
    text = clean_text(text).lower()
    match = re.search(r"([\d.,]+)\s*(?:ulasan|review|reviews)", text)
    if not match:
        match = re.search(r"\(([\d.,]+)\)", text)
    if not match:
        return None

    value = match.group(1).replace(".", "").replace(",", "")
    try:
        return int(value)
    except ValueError:
        return None


def extract_review_count(driver):
    candidates = []
    selectors = [
        (By.CSS_SELECTOR, "button.HHrUdb"),
        (By.CSS_SELECTOR, "span.UY7F9"),
        (By.CSS_SELECTOR, "div.F7nice"),
        (By.XPATH, "//*[contains(text(), 'ulasan') or contains(text(), 'review') or contains(text(), 'reviews')]"),
        (By.XPATH, "//*[contains(@aria-label, 'ulasan') or contains(@aria-label, 'review') or contains(@aria-label, 'reviews')]"),
    ]
    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            text = clean_text(element.text or element.get_attribute("aria-label"))
            if text:
                candidates.append(text)

    for text in candidates:
        parsed = parse_review_count(text)
        if parsed is not None:
            return parsed
    return 0


def extract_photo(driver):
    selectors = [
        "button[jsaction*='pane.heroHeaderImage'] img",
        "button[aria-label*='Foto'] img",
        "button[aria-label*='Photo'] img",
        "[role='main'] img[src*='googleusercontent']",
    ]
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            src = element.get_attribute("src") or ""
            if src and not src.startswith("data:"):
                return "ADA", src
    return "TIDAK ADA", ""


def extract_coords_from_url(url):
    match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url)
    if match:
        return float(match.group(1)), float(match.group(2))

    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url)
    if match:
        return float(match.group(1)), float(match.group(2))

    return None, None


def load_maps_url(driver, url, timeout, delay):
    driver.get(url)
    wait_for_maps(driver, timeout)
    click_consent_if_present(driver)
    time.sleep(delay)


def scrape_current_place(driver):
    title = extract_title(driver)
    address = extract_address(driver)
    rating = extract_rating(driver)
    review_count = extract_review_count(driver)
    photo_status, photo_url = extract_photo(driver)
    lat, lon = extract_coords_from_url(driver.current_url)
    return {
        "name": title,
        "address": address,
        "rating": rating,
        "review_count": review_count,
        "photo_status": photo_status,
        "photo_url": photo_url,
        "lat": lat,
        "lon": lon,
    }


def has_place_data(place):
    return bool(place["name"] or place["address"] or place["rating"] or place["review_count"] or place["photo_url"])


def extract_search_results(driver, max_results):
    results = []
    seen = set()
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/'], a[href*='www.google.com/maps/place/']")
    for link in links:
        href = link.get_attribute("href") or ""
        if not href or href in seen:
            continue

        label = clean_text(link.get_attribute("aria-label") or link.text)
        if not label:
            continue
        label = label.split("\n")[0]
        if COORD_RE.match(label):
            continue

        seen.add(href)
        results.append({"name": label, "href": href})
        if len(results) >= max_results:
            break
    return results


def build_search_query(row):
    return clean_text(row.get("Nama_SPPG", ""))


def scrape_search_candidates(driver, row, args):
    query = build_search_query(row)
    url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
    load_maps_url(driver, url, args.timeout, args.delay)

    candidates = extract_search_results(driver, args.max_candidates)
    places = []
    if candidates:
        for index, candidate in enumerate(candidates, start=1):
            load_maps_url(driver, candidate["href"], args.timeout, args.delay)
            place = scrape_current_place(driver)
            if not place["name"]:
                place["name"] = candidate["name"]
            place["candidate_name"] = candidate["name"]
            place["is_sppg_like"] = place_is_sppg_like(place)
            place["source"] = f"search_result_{index}"
            place["query"] = query
            place["candidate_count"] = len(candidates)
            places.append(place)
    else:
        place = scrape_current_place(driver)
        place["candidate_name"] = ""
        place["is_sppg_like"] = place_is_sppg_like(place)
        place["source"] = "search_direct"
        place["query"] = query
        place["candidate_count"] = 1 if has_place_data(place) else 0
        places.append(place)

    return places


def choose_best_candidate(row, places, args):
    expected_name = row.get("Nama_SPPG", "")
    filtered_places = [place for place in places if place.get("is_sppg_like")]
    candidate_pool = filtered_places if filtered_places else places
    scored = []
    for place in candidate_pool:
        score = name_score(expected_name, place["name"])
        place["filtered_candidate_count"] = len(filtered_places)
        scored.append((score, place))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return {
            "name": "",
            "address": "",
            "rating": "",
            "review_count": 0,
            "photo_status": "TIDAK ADA",
            "photo_url": "",
            "lat": None,
            "lon": None,
            "candidate_name": "",
            "is_sppg_like": False,
            "filtered_candidate_count": 0,
            "source": "search_no_result",
            "query": build_search_query(row),
            "candidate_count": 0,
        }

    if len(places) > 1 and not filtered_places:
        return {
            "name": "",
            "address": "",
            "rating": "",
            "review_count": 0,
            "photo_status": "TIDAK ADA",
            "photo_url": "",
            "lat": None,
            "lon": None,
            "candidate_name": "",
            "is_sppg_like": False,
            "filtered_candidate_count": 0,
            "source": "search_no_sppg_like_result",
            "query": build_search_query(row),
            "candidate_count": len(places),
        }

    best_score, best_place = scored[0]
    if best_score >= args.name_threshold:
        return best_place

    best_place["source"] = f"{best_place['source']}_low_similarity"
    return best_place


def evaluate(row, place, args):
    source_lat = parse_float(row.get("Latitude"))
    source_lon = parse_float(row.get("Longitude"))
    expected_name = row.get("Nama_SPPG", "")

    score = name_score(expected_name, place["name"])
    distance = None
    if source_lat is not None and source_lon is not None and place["lat"] is not None and place["lon"] is not None:
        distance = haversine_m(source_lat, source_lon, place["lat"], place["lon"])

    errors = []
    if not has_place_data(place):
        errors.append("Tidak ada data tempat terdeteksi di Google Maps")
    if not place["name"]:
        errors.append("Nama tempat tidak terdeteksi")
    if not place.get("is_sppg_like"):
        errors.append("Nama/alamat kandidat tidak mengandung SPPG atau Satuan Pelayanan Pemenuhan Gizi")
    if score < args.name_threshold:
        errors.append(f"Nama tidak cocok dengan CSV (score {score:.2f})")
    if place["photo_status"] == "TIDAK ADA" and int(place.get("review_count") or 0) == 0:
        errors.append("Tidak ada foto dan 0 review")
    if distance is None:
        errors.append("Koordinat tempat dari Google Maps tidak terdeteksi")
    elif distance > args.distance_threshold_m:
        errors.append(f"Jarak koordinat {distance:.1f} m melebihi ambang {args.distance_threshold_m:.1f} m")

    status = "VALID" if not errors else "TIDAK VALID"
    return {
        "Status": status,
        "GMaps_Nama": place["name"],
        "GMaps_Alamat": place["address"],
        "GMaps_Longitude": "" if place["lon"] is None else f"{place['lon']:.8f}",
        "GMaps_Latitude": "" if place["lat"] is None else f"{place['lat']:.8f}",
        "GMaps_Rating": place["rating"],
        "GMaps_Reviews": str(place.get("review_count", 0)),
        "GMaps_Foto": place["photo_status"],
        "GMaps_Foto_URL": place["photo_url"],
        "GMaps_Distance_Meter": "" if distance is None else f"{distance:.1f}",
        "GMaps_Name_Score": f"{score:.2f}",
        "GMaps_Source": place["source"],
        "GMaps_Query": place.get("query", ""),
        "GMaps_Candidate_Count": str(place.get("candidate_count", "")),
        "GMaps_Filtered_Candidate_Count": str(place.get("filtered_candidate_count", "")),
        "GMaps_Is_SPPG_Like": "YA" if place.get("is_sppg_like") else "TIDAK",
        "GMaps_Error": "; ".join(errors),
    }


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    return reader.fieldnames or [], rows


def processed_count(output_path):
    if not output_path.exists():
        return 0
    with open(output_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


def output_header_fields(output_path):
    if not output_path.exists():
        return []
    with open(output_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or []


def prepare_writer(output_path, fieldnames, append):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(output_path, "a" if append else "w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    if not append:
        writer.writeheader()
    return handle, writer


def main():
    parser = argparse.ArgumentParser(
        description="Validasi Nama_SPPG, longitude, dan latitude ke Google Maps memakai Selenium."
    )
    parser.add_argument("--input", default="./data/sppg_jawa_timur (1).csv", help="Path CSV sumber.")
    parser.add_argument("--output", default="", help="Path CSV hasil. Default: outputs/sppg_validated_<timestamp>.csv")
    parser.add_argument("--profile-dir", default="selenium_chrome_profile", help="Folder profil Chrome untuk menyimpan sesi/consent.")
    parser.add_argument("--headless", action="store_true", help="Jalankan Chrome tanpa UI. Tidak disarankan untuk Google Maps.")
    parser.add_argument("--delay", type=float, default=4.0, help="Jeda setelah membuka halaman Google Maps.")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout Selenium per halaman.")
    parser.add_argument("--distance-threshold-m", type=float, default=500.0, help="Ambang jarak koordinat CSV vs Google Maps.")
    parser.add_argument("--name-threshold", type=float, default=0.55, help="Ambang kecocokan nama 0-1.")
    parser.add_argument("--max-candidates", type=int, default=3, help="Jumlah hasil teratas Google Maps yang dicek saat muncul daftar.")
    parser.add_argument("--start-row", type=int, default=1, help="Mulai dari baris data ke-N, 1-based.")
    parser.add_argument("--limit", type=int, default=0, help="Batasi jumlah baris diproses. 0 berarti semua.")
    parser.add_argument("--resume", action="store_true", help="Lanjutkan output yang sudah ada dengan melewati baris terproses.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input tidak ditemukan: {input_path}", file=sys.stderr)
        return 2

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("outputs") / f"sppg_validated_{timestamp}.csv"

    source_fields, rows = read_rows(input_path)
    required = {"Nama_SPPG", "Longitude", "Latitude"}
    missing = sorted(required - set(source_fields))
    if missing:
        print(f"Kolom wajib tidak ada: {', '.join(missing)}", file=sys.stderr)
        return 2

    fieldnames = source_fields + [col for col in RESULT_COLUMNS if col not in source_fields]
    if args.resume and output_path.exists():
        existing_fields = output_header_fields(output_path)
        missing_output_fields = [field for field in fieldnames if field not in existing_fields]
        if missing_output_fields:
            print(
                "Output lama tidak kompatibel dengan format kolom terbaru. "
                f"Buat output baru atau hapus file lama. Kolom hilang: {', '.join(missing_output_fields)}",
                file=sys.stderr,
            )
            return 2

    start_index = max(args.start_row - 1, 0)
    if args.resume:
        start_index = max(start_index, processed_count(output_path))
    selected_rows = rows[start_index:]
    if args.limit:
        selected_rows = selected_rows[: args.limit]

    append = args.resume and output_path.exists() and processed_count(output_path) > 0
    handle, writer = prepare_writer(output_path, fieldnames, append=append)
    driver = build_driver(args)

    try:
        total = len(selected_rows)
        for offset, row in enumerate(selected_rows, start=1):
            row_number = start_index + offset
            name = row.get("Nama_SPPG", "")
            lat = parse_float(row.get("Latitude"))
            lon = parse_float(row.get("Longitude"))
            result = {col: "" for col in RESULT_COLUMNS}

            print(f"[{offset}/{total}] Baris {row_number}: {name}")
            try:
                if lat is None or lon is None:
                    result["Status"] = "TIDAK VALID"
                    result["GMaps_Error"] = "Longitude/Latitude CSV tidak valid"
                else:
                    places = scrape_search_candidates(driver, row, args)
                    place = choose_best_candidate(row, places, args)
                    result.update(evaluate(row, place, args))
            except TimeoutException:
                result["Status"] = "TIDAK VALID"
                result["GMaps_Error"] = "Timeout saat membuka Google Maps"
            except WebDriverException as exc:
                result["Status"] = "TIDAK VALID"
                result["GMaps_Error"] = f"Selenium error: {clean_text(str(exc))[:300]}"
            except Exception as exc:
                result["Status"] = "TIDAK VALID"
                result["GMaps_Error"] = f"Error tidak terduga: {clean_text(str(exc))[:300]}"

            output_row = dict(row)
            output_row.update(result)
            writer.writerow(output_row)
            handle.flush()
            print(f"    -> {result['Status']} | {result.get('GMaps_Nama', '')} | {result.get('GMaps_Error', '')}")
    finally:
        handle.close()
        driver.quit()

    print(f"Selesai. Output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
