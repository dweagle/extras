import requests
import xml.etree.ElementTree as ET
import os
import re

PLEX_URL = "http://address_here:32400"
PLEX_TOKEN = "token_here"
OUTPUT_DIR = "logos"
SECTION_KEYS = ["1", "2"]  # Only these libraries will be scanned

def debug(msg):
    print(f"[DEBUG] {msg}")

def sanitize_filename(text):
    return re.sub(r'[^a-zA-Z0-9 .()-]', '', text)

def get_sections():
    url = f"{PLEX_URL}/library/sections?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    sections = []
    for directory in root.findall(".//Directory"):
        key = directory.attrib.get("key")
        title = directory.attrib.get("title")
        if key in SECTION_KEYS:
            sections.append({"key": key, "title": title})
    return sections

def get_items(section_key):
    url = f"{PLEX_URL}/library/sections/{section_key}/all?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    items = []
    for item in root.findall(".//Video"):
        ratingKey = item.attrib.get("ratingKey")
        title = item.attrib.get("title")
        year = item.attrib.get("year", "")
        items.append({"ratingKey": ratingKey, "title": title, "year": year})
    for item in root.findall(".//Directory"):
        ratingKey = item.attrib.get("ratingKey")
        title = item.attrib.get("title")
        year = item.attrib.get("year", "")
        items.append({"ratingKey": ratingKey, "title": title, "year": year})
    return items

def find_clearlogo(ratingKey):
    url = f"{PLEX_URL}/library/metadata/{ratingKey}?X-Plex-Token={PLEX_TOKEN}"
    resp = requests.get(url)
    root = ET.fromstring(resp.text)
    logo_path = None
    for image in root.iter("Image"):
        if image.attrib.get("type") == "clearLogo":
            logo_path = image.attrib.get("url")
            break
    if not logo_path:
        for el in root.iter("clearLogo"):
            logo_path = el.text
            break
    return logo_path

def main():
    debug(f"Scanning Plex libraries: {SECTION_KEYS}")
    sections = get_sections()
    summary = {}

    for section in sections:
        debug(f"Scanning library: {section['title']} (key={section['key']})")
        library_folder = os.path.join(OUTPUT_DIR, sanitize_filename(section["title"]))
        os.makedirs(library_folder, exist_ok=True)
        items = get_items(section["key"])
        total_items = 0
        logo_found = 0
        logo_missing = 0
        for item in items:
            total_items += 1
            debug(f"Scanning item: {item['title']} ({item['year']}), ratingKey={item['ratingKey']}")
            logo_path = find_clearlogo(item["ratingKey"])
            if logo_path:
                filename = f"{sanitize_filename(item['title'])} ({item['year']}) clearlogo.png"
                dest_path = os.path.join(library_folder, filename)
                logo_url = f"{PLEX_URL}{logo_path}?X-Plex-Token={PLEX_TOKEN}"
                debug(f"Downloading clearLogo from {logo_url}")
                response = requests.get(logo_url)
                if response.status_code == 200:
                    with open(dest_path, "wb") as f:
                        f.write(response.content)
                    print(f"Downloaded: {dest_path}")
                    logo_found += 1
                else:
                    print(f"Failed to download logo for {item['title']} ({item['year']})")
                    debug(f"HTTP status: {response.status_code}, content: {response.text[:200]}")
                    logo_missing += 1
            else:
                print(f"No clearLogo for {item['title']} ({item['year']}) in {section['title']}")
                debug(f"No clearLogo found for {item['title']} ({item['year']}) in {section['title']}")
                logo_missing += 1
        summary[section['title']] = {
            "total": total_items,
            "with_logo": logo_found,
            "missing_logo": logo_missing
        }
        debug(f"Section summary for {section['title']}: total={total_items}, with_logo={logo_found}, missing_logo={logo_missing}")

    print("\nSummary of logo download:")
    for libname, stats in summary.items():
        print(f"Library: {libname}")
        print(f"  Items scanned: {stats['total']}")
        print(f"  With clearLogo: {stats['with_logo']}")
        print(f"  Missing clearLogo: {stats['missing_logo']}")
        print("-" * 30)

if __name__ == "__main__":
    main()
