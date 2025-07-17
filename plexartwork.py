import requests
import xml.etree.ElementTree as ET
import os
import re

# --- USER SETTINGS ---
PLEX_URL = "http://your.address:32400"       # Plex server URL
PLEX_TOKEN = "your_token"                    # Plex token
OUTPUT_DIR = "plex_artwork"                  # Output folder
SECTION_KEYS = ["1", "2"]                    # Library section keys to process
MAX_ITEMS = 10                               # Max items per section to process (set to None for all)
MAX_POSTERS_PER_PROVIDER = 10                # Max agent posters per provider (e.g. TMDB, TVDB, etc.)

PROCESSED_SHOWS_FILE = os.path.join(OUTPUT_DIR, "processed_shows.txt")
PROCESSED_MOVIES_FILE = os.path.join(OUTPUT_DIR, "processed_movies.txt")

def sanitize_filename(text):
    return re.sub(r'[^a-zA-Z0-9 .()_-]', '', text)

def get_file_extension(url, default=".jpg"):
    ext = os.path.splitext(url.split("?")[0])[-1]
    if ext.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
        return ext
    return default

def safe_year(year):
    return f" ({year})" if year else ""

def load_processed_ids(path):
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return set(line.strip() for line in f if line.strip())

def mark_id_processed(path, ratingKey):
    with open(path, "a") as f:
        f.write(f"{ratingKey}\n")

def get_sections():
    url = f"{PLEX_URL}/library/sections?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    sections = []
    for directory in root.findall(".//Directory"):
        key = directory.attrib.get("key")
        title = directory.attrib.get("title")
        section_type = directory.attrib.get("type")
        if key in SECTION_KEYS:
            sections.append({"key": key, "title": title, "type": section_type})
    return sections

def get_items(section_key, section_type):
    url = f"{PLEX_URL}/library/sections/{section_key}/all?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    items = []
    if section_type == "movie":
        for item in root.findall(".//Video"):
            ratingKey = item.attrib.get("ratingKey")
            title = item.attrib.get("title")
            year = item.attrib.get("year", "")
            items.append({"ratingKey": ratingKey, "title": title, "year": year})
    elif section_type == "show":
        for item in root.findall(".//Directory"):
            ratingKey = item.attrib.get("ratingKey")
            title = item.attrib.get("title")
            year = item.attrib.get("year", "")
            items.append({"ratingKey": ratingKey, "title": title, "year": year})
    return items

def get_seasons(show_rating_key):
    url = f"{PLEX_URL}/library/metadata/{show_rating_key}/children?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    seasons = []
    for elem in root.findall(".//Directory"):
        if elem.attrib.get("type") == "season":
            ratingKey = elem.attrib.get("ratingKey")
            title = elem.attrib.get("title")
            index = elem.attrib.get("index", "")
            year = elem.attrib.get("year", "")
            seasons.append({
                "ratingKey": ratingKey,
                "title": title,
                "index": index,
                "year": year
            })
    return seasons

def get_artwork(ratingKey, exclude_types=None):
    # 1. Posters (agent ones), up to MAX_POSTERS_PER_PROVIDER per provider
    posters_url = f"{PLEX_URL}/library/metadata/{ratingKey}/posters?X-Plex-Token={PLEX_TOKEN}"
    posters_resp = requests.get(posters_url)
    posters_root = ET.fromstring(posters_resp.text)
    posters_by_provider = {}
    for photo in posters_root.findall(".//Photo"):
        provider = photo.attrib.get("provider")
        key = photo.attrib.get("key")
        if provider and key:
            posters_by_provider.setdefault(provider, []).append({"type": "poster", "provider": provider, "key": key})
    # Only keep up to MAX_POSTERS_PER_PROVIDER posters per provider
    limited_posters = []
    for provider_posters in posters_by_provider.values():
        limited_posters.extend(provider_posters[:MAX_POSTERS_PER_PROVIDER])

    # 2. Other artwork from metadata endpoint (attributes and <Image> tags)
    artwork = []
    # a) From attributes (EXCLUDING "thumb" and "coverPoster" and any passed types)
    artwork_attrs = [
        "clearLogo", "background"
    ]
    url = f"{PLEX_URL}/library/metadata/{ratingKey}?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    for elem in root.iter():
        if elem.tag not in ("Directory", "Video"):
            continue
        for attr in artwork_attrs:
            if attr in elem.attrib:
                if exclude_types and attr.lower() in exclude_types:
                    continue
                artwork.append({"type": attr.lower(), "provider": "plex", "key": elem.attrib[attr]})

    # b) From <Image type="..." url="..."/> child elements (EXCLUDING type="thumb", "coverPoster", and any passed types)
    for image in root.findall(".//Image"):
        img_type = image.attrib.get("type")
        url = image.attrib.get("url")
        if img_type and url:
            lower_type = img_type.lower()
            if lower_type in ["thumb", "coverposter"]:
                continue
            if exclude_types and lower_type in exclude_types:
                continue
            artwork.append({"type": lower_type, "provider": "plex", "key": url})

    return limited_posters + artwork

def download_artwork(item_folder, index, item_title, item_year, art_type, provider, key):
    safe_title = sanitize_filename(item_title)
    safe_provider = sanitize_filename(provider)
    safe_type = sanitize_filename(art_type)
    safe_year_str = safe_year(item_year)
    ext = get_file_extension(key)
    filename = f"{safe_title}{safe_year_str} - {safe_type} - {safe_provider} - file{index}{ext}"
    dest_path = os.path.join(item_folder, filename)

    if key.startswith("http://") or key.startswith("https://"):
        url = key
    else:
        url = f"{PLEX_URL}{key}?X-Plex-Token={PLEX_TOKEN}"
    try:
        resp = requests.get(url)
        if resp.status_code == 200 and resp.content:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            print(f"Downloaded: {filename}")
        else:
            print(f"Failed: {filename} [{resp.status_code}]")
    except Exception as e:
        print(f"Exception: {filename} - {e}")

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    processed_shows = load_processed_ids(PROCESSED_SHOWS_FILE)
    processed_movies = load_processed_ids(PROCESSED_MOVIES_FILE)

    sections = get_sections()
    for section in sections:
        section_type = section["type"]
        section_folder = "Movies" if section_type == "movie" else "TV Shows"
        print(f"\nScanning {section['title']} ({section_folder})")
        items = get_items(section["key"], section_type)
        if MAX_ITEMS:
            items = items[:MAX_ITEMS]
        for item in items:
            # Resume logic for both shows and movies
            if section_type == "show" and item["ratingKey"] in processed_shows:
                print(f"Skipping already processed show: {item['title']} ({item['year']})")
                continue
            if section_type == "movie" and item["ratingKey"] in processed_movies:
                print(f"Skipping already processed movie: {item['title']} ({item['year']})")
                continue

            folder_name = sanitize_filename(item['title'])
            if item['year']:
                folder_name += f" ({item['year']})"
            item_folder = os.path.join(OUTPUT_DIR, section_folder, folder_name)
            os.makedirs(item_folder, exist_ok=True)
            found = False
            # Show/movie-level artwork
            artwork = get_artwork(item['ratingKey'])
            # Group by (type, provider) for indexing
            group = {}
            for art in artwork:
                k = (art["type"], art["provider"])
                group.setdefault(k, []).append(art)
            for (art_type, provider), arts in group.items():
                for idx, art in enumerate(arts, 1):
                    download_artwork(item_folder, idx, item['title'], item['year'], art_type, provider, art["key"])
                    found = True
            if not found:
                print(f"No artwork for {item['title']} ({item['year']})")
            # ---- SEASON ARTWORK FOR SHOWS ----
            if section_type == "show":
                seasons = get_seasons(item['ratingKey'])
                for season in seasons:
                    season_folder_name = sanitize_filename(item['title'])
                    if item['year']:
                        season_folder_name += f" ({item['year']})"
                    season_folder_name += f"/Season {season['index']}"
                    season_folder = os.path.join(OUTPUT_DIR, section_folder, season_folder_name)
                    os.makedirs(season_folder, exist_ok=True)
                    season_artwork = get_artwork(season['ratingKey'], exclude_types=["clearlogo", "background"])
                    group = {}
                    for art in season_artwork:
                        k = (art["type"], art["provider"])
                        group.setdefault(k, []).append(art)
                    found_season = False
                    for (art_type, provider), arts in group.items():
                        for idx, art in enumerate(arts, 1):
                            download_artwork(
                                season_folder,
                                idx,
                                f"{item['title']} - Season {season['index']}",
                                season['year'],
                                art_type,
                                provider,
                                art["key"]
                            )
                            found_season = True
                    if not found_season:
                        print(f"No artwork for {item['title']} Season {season['index']}")
                mark_id_processed(PROCESSED_SHOWS_FILE, item["ratingKey"])
            elif section_type == "movie":
                mark_id_processed(PROCESSED_MOVIES_FILE, item["ratingKey"])

if __name__ == "__main__":
    main()
