from plexapi.server import PlexServer
import requests
import os
import re

PLEX_URL = "http://plex.url.here:32400"
PLEX_TOKEN = "your_token_here"
OUTPUT_DIR = "logos"
SECTION_KEYS = ["1", "2"]  # Only these libraries will be scanned

def debug(msg):
    print(f"[DEBUG] {msg}")

def sanitize_filename(text):
    # Keep only these characters: alphanumeric, space, period, parentheses, hyphen
    return re.sub(r'[^a-zA-Z0-9 .()-]', '', text)

summary = {}

debug(f"Connecting to Plex server at {PLEX_URL} with token {PLEX_TOKEN}")
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    debug("Connected to Plex server successfully.")
except Exception as e:
    debug(f"Failed to connect to Plex server: {e}")
    exit(1)

for section in plex.library.sections():
    debug(f"Checking section: {section.title} (key={section.key})")
    if str(section.key) not in SECTION_KEYS:
        debug(f"Skipping section: {section.title}")
        continue
    library_folder = os.path.join(OUTPUT_DIR, sanitize_filename(section.title))
    try:
        os.makedirs(library_folder, exist_ok=True)
        debug(f"Created/verified output directory: {library_folder}")
    except Exception as e:
        debug(f"Failed to create output directory {library_folder}: {e}")
        continue
    print(f"Scanning library: {section.title}")
    total_items = 0
    logo_found = 0
    logo_missing = 0
    for item in section.all():
        total_items += 1
        title = getattr(item, "title", "Unknown Title")
        year = getattr(item, "year", "Unknown Year")
        debug(f"Scanning item: {title} ({year}), ratingKey={getattr(item, 'ratingKey', 'N/A')}")
        logo_url = None
        # Try art field
        if hasattr(item, "art") and item.art and "clearlogo" in item.art.lower():
            logo_url = plex.url(item.art)
            debug(f"Found clearLogo via 'art' field: {logo_url}")
        # Try thumb field
        elif hasattr(item, "thumb") and item.thumb and "clearlogo" in item.thumb.lower():
            logo_url = plex.url(item.thumb)
            debug(f"Found clearLogo via 'thumb' field: {logo_url}")
        # Try images list
        else:
            for img in getattr(item, "images", []):
                debug(f"Checking image: type={getattr(img, 'type', '')}, url={getattr(img, 'url', '')}")
                if hasattr(img, "type") and img.type == "clearLogo":
                    logo_url = plex.url(img.url)
                    debug(f"Found clearLogo via 'images' list: {logo_url}")
                    break
        if logo_url:
            filename = f"{sanitize_filename(title)} ({year}) clearlogo.png"
            dest_path = os.path.join(library_folder, filename)
            debug(f"Attempting to download logo from URL: {logo_url}")
            try:
                response = requests.get(logo_url, headers={"X-Plex-Token": PLEX_TOKEN})
                debug(f"HTTP status code: {response.status_code}")
                debug(f"Response headers: {response.headers}")
                if response.status_code == 200:
                    with open(dest_path, "wb") as f:
                        f.write(response.content)
                    print(f"Downloaded: {dest_path}")
                    debug(f"Logo successfully saved: {dest_path}")
                    logo_found += 1
                else:
                    print(f"Failed to download logo for {title} ({year})")
                    debug(f"Failed to download logo: status={response.status_code}, content={response.text[:200]}")
                    logo_missing += 1
            except Exception as e:
                print(f"Failed to download logo for {title} ({year}) due to exception.")
                debug(f"Exception during download for {title} ({year}): {e}")
                logo_missing += 1
        else:
            print(f"No clearLogo for {title} ({year}) in {section.title}")
            debug(f"No clearLogo found for {title} ({year}) in {section.title}")
            logo_missing += 1
    summary[section.title] = {
        "total": total_items,
        "with_logo": logo_found,
        "missing_logo": logo_missing
    }
    debug(f"Section summary for {section.title}: total={total_items}, with_logo={logo_found}, missing_logo={logo_missing}")

print("\nSummary of logo download:")
for libname, stats in summary.items():
    print(f"Library: {libname}")
    print(f"  Items scanned: {stats['total']}")
    print(f"  With clearLogo: {stats['with_logo']}")
    print(f"  Missing clearLogo: {stats['missing_logo']}")
    print("-" * 30)
