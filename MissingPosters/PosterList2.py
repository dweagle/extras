import requests
import json
import os
import webbrowser
from difflib import SequenceMatcher
import re
import unicodedata
import urllib.parse

# =============================================
#               CONFIGURATION
# =============================================

# TMDB CONFIGURATION
TMDB_API_KEY = "tmdb_api_key"

# RADARR INSTANCE 1
RADARR1_URL = "http://localhost:7878" 
RADARR1_API_KEY = "radarr_api_key"

# RADARR INSTANCE 2 -Optional
RADARR2_URL = ""
RADARR2_API_KEY = ""

# SONARR INSTANCE 1
SONARR1_URL = "http://localhost:8989" 
SONARR1_API_KEY = "sonarr_api_key"

# SONARR INSTANCE 2 -Optional 
SONARR2_URL = ""
SONARR2_API_KEY = ""

# FILE SETTINGS
INPUT_FILE = "unmatched_dict.json"
OUTPUT_JSON = "unmatched_output.json"
OUTPUT_HTML = "unmatched_report.html"
OPEN_REPORT = True
ITEMS_PER_PAGE = 50 

# ============================================
#            Do not edit past here
# ============================================

def collect_servers(service_type):
    servers = []
    for i in range(1, 4):
        url_var = f"{service_type}{i}_URL"
        key_var = f"{service_type}{i}_API_KEY"
        url = globals().get(url_var, "").strip()
        key = globals().get(key_var, "").strip()
        if url and key:
            servers.append((url, key))
    return servers

def fetch_aggregated_library(servers, endpoint):
    aggregated_data = []
    if not servers:
        return []

    for url, api_key in servers:
        clean_url = url.rstrip('/')
        full_url = f"{clean_url}/api/v3/{endpoint}"
        print(f"   Connecting to {clean_url}...")
        try:
            response = requests.get(full_url, headers={"X-Api-Key": api_key}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                aggregated_data.extend(data)
                print(f"   ✅ Retrieved {len(data)} items.")
            else:
                print(f"   ❌ Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
    return aggregated_data

class SmartMatcher:
    def __init__(self, tmdb_key):
        self.tmdb_key = tmdb_key
        self.session = requests.Session()
        
        self.CANONICAL_ALIASES = {
            "&": "and", "and": "and", "vs.": "versus", "vs": "versus",
            "ep.": "episode", "ep": "episode", "vol.": "volume", "vol": "volume",
            "pt.": "part", "pt": "part", "dr.": "doctor", "dr": "doctor",
            "+": "and"
        }
        
        self.COLLECTION_SUFFIXES = [
            "collection", "saga", "trilogy", "series", "anthology", "box set", "set",
            "collezione", "serie", "ciclo", "trilogia", "coffret", "samling", "samle",
            "kokoelma", "kollektion"
        ]

    def normalize(self, s, is_collection=False):
        if not s: return ""
        
        s = re.sub(r"[’'`ʹʼ]", "", s)
        s = s.replace(":", " ")
        s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode()
        s = s.lower().strip()

        if is_collection:
            pattern = r"\b(" + "|".join(self.COLLECTION_SUFFIXES) + r")\b"
            s = re.sub(pattern, "", s).strip()
            s = s.replace("()", "").strip()

        words = re.split(r"(\W+)", s)
        normalized_words = [
            self.CANONICAL_ALIASES.get(w.strip(), w) if w.strip() else w 
            for w in words
        ]
        s = "".join(normalized_words)
        
        return re.sub(r"\s+", " ", s).strip()

    def jaccard_similarity(self, a, b):
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b: return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def check_collection_translations(self, collection_id, target_title):
        url = f"https://api.themoviedb.org/3/collection/{collection_id}"
        params = {
            'api_key': self.tmdb_key,
            'append_to_response': 'translations'
        }
        try:
            r = self.session.get(url, params=params)
            if r.status_code != 200: return False
            data = r.json()
            
            if self.normalize(data.get('name', ''), True) == target_title:
                return True
                
            translations = data.get('translations', {}).get('translations', [])
            for t in translations:
                t_name = t.get('data', {}).get('title', '') or t.get('data', {}).get('name', '')
                if self.normalize(t_name, True) == target_title:
                    return True
            return False
        except:
            return False

    def search_tmdb(self, title, year, media_type):
        if not self.tmdb_key or "YOUR_TMDB_API_KEY" in self.tmdb_key:
            return None

        endpoint_map = {
            'movie': 'search/movie',
            'series': 'search/tv',
            'collection': 'search/collection'
        }
        endpoint = endpoint_map.get(media_type)
        if not endpoint: return None

        url = f"https://api.themoviedb.org/3/{endpoint}"
        params = {
            'api_key': self.tmdb_key,
            'query': title,
            'include_adult': 'false',
            'page': 1
        }
        
        if year and media_type != 'collection':
            if media_type == 'movie': params['primary_release_year'] = year
            if media_type == 'series': params['first_air_date_year'] = year

        try:
            r = self.session.get(url, params=params)
            if r.status_code != 200: return None
            results = r.json().get('results', [])
        except:
            return None

        best_match = None
        highest_score = 0
        
        is_coll = (media_type == 'collection')
        norm_title = self.normalize(title, is_collection=is_coll)

        for res in results:
            r_title = res.get('title') or res.get('name')
            r_date = res.get('release_date') or res.get('first_air_date')
            r_year = int(r_date[:4]) if r_date and len(r_date) >= 4 else 0
            
            norm_r_title = self.normalize(r_title, is_collection=is_coll)
            
            seq_score = SequenceMatcher(None, norm_title, norm_r_title).ratio()
            jaccard_score = self.jaccard_similarity(norm_title, norm_r_title)
            
            year_score = 0
            if not is_coll:
                target_year = int(year) if year else 0
                if target_year == 0: year_score = 0.1
                elif r_year and abs(r_year - target_year) <= 1: year_score = 0.2
            
            final_score = (seq_score * 0.6) + (jaccard_score * 0.4) + year_score
            
            is_match = False
            
            if is_coll:
                if seq_score > 0.85: 
                    is_match = True
                elif seq_score < 0.85 and self.check_collection_translations(res['id'], norm_title):
                    is_match = True
                    final_score = 1.0 
            else:
                if seq_score > 0.9 and jaccard_score > 0.8: is_match = True
                elif seq_score > 0.8 and year_score >= 0.2: is_match = True
            
            if is_match and final_score > highest_score:
                highest_score = final_score
                best_match = res

        if not best_match:
            return None

        tmdb_id = best_match.get('id')
        tvdb_id = None
        if media_type == 'series' and tmdb_id:
            try:
                ext_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids"
                r_ext = self.session.get(ext_url, params={'api_key': self.tmdb_key})
                if r_ext.status_code == 200:
                    tvdb_id = r_ext.json().get('tvdb_id')
            except:
                pass
        
        return {
            "title": best_match.get('title') or best_match.get('name'),
            "year": best_match.get('release_date') or best_match.get('first_air_date'),
            "tmdbId": tmdb_id,
            "tvdbId": tvdb_id
        }

def find_match_hybrid(title, year, library_data, matcher, media_type):
    is_coll = (media_type == 'collection')
    clean_title = matcher.normalize(title, is_collection=is_coll)
    target_year = int(year) if year else 0
    
    for item in library_data:
        local_norm = matcher.normalize(item.get("title", ""), is_collection=is_coll)
        if local_norm == clean_title:
            match_year = item.get("year", 0)
            if is_coll or target_year == 0 or match_year == target_year or abs(match_year - target_year) <= 1:
                return item

    print(f"      ...Searching TMDB for: {title}...")
    remote_match = matcher.search_tmdb(title, year, media_type)
    if remote_match:
        print(f"      ✅ Found on TMDB: {remote_match['title']}")
        return remote_match

    return None

def generate_links(item, source_type):
    tmdb_id = item.get("tmdbId")
    tvdb_id = item.get("tvdbId")
    links = {
        "tmdbId": tmdb_id,
        "tvdbId": tvdb_id,
        "tmdbUrl": f"https://www.themoviedb.org/{source_type}/{tmdb_id}" if tmdb_id else None,
        "tvdbUrl": f"https://www.thetvdb.com/?tab=series&id={tvdb_id}" if tvdb_id else None
    }
    if source_type == "collection" and tmdb_id:
        links["tmdbUrl"] = f"https://www.themoviedb.org/collection/{tmdb_id}"
    return links

def create_html_report(data, filename):
    c_mov = len(data.get("movies", []))
    c_ser = len(data.get("series", []))
    c_col = len(data.get("collections", []))

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Poster Match Workflow</title>
        <style>
            :root {{
                --bg-color: #121212;
                --card-bg: #1e1e1e;
                --text-main: #e0e0e0;
                --text-muted: #a0a0a0;
                --accent: #bb86fc;
                --border: #333;
                --hover: #2c2c2c;
                --highlight: #2a2a40; 
                --tmdb: #01b4e4;
                --tvdb: #7cce02;
                --fanart: #4b6a90;
                --copy-btn-bg: #2d2d2d;
            }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg-color); color: var(--text-main); margin: 0; padding: 20px; }}
            .container {{ max-width: 1150px; margin: 0 auto; }}
            
            header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 15px; }}
            h1 {{ margin: 0; font-size: 24px; color: var(--accent); }}
            
            .controls-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px; }}
            
            .tabs {{ display: flex; gap: 10px; }}
            .tab-btn {{ background: transparent; border: 1px solid var(--border); color: var(--text-muted); padding: 8px 16px; cursor: pointer; border-radius: 4px; transition: all 0.2s; }}
            .tab-btn:hover {{ background: var(--hover); color: var(--text-main); }}
            .tab-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); font-weight: bold; }}
            
            .search-box {{ padding: 8px 12px; border-radius: 4px; border: 1px solid var(--border); background: var(--card-bg); color: var(--text-main); width: 250px; }}
            .action-btn {{ background: #cf6679; color: #000; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; margin-left: 10px; }}
            .undo-btn {{ background: #03dac6; color: #000; }}

            .tab-content {{ display: none; }}
            .tab-content.active {{ display: block; }}
            
            table {{ width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 8px; overflow: hidden; table-layout: fixed; margin-bottom: 20px; }}
            th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: middle; word-wrap: break-word; }}
            th {{ background-color: #252525; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }}
            
            /* Compact Columns */
            th.col-done {{ width: 40px; text-align: center; }}
            th.col-copy {{ width: 40px; text-align: center; }}
            th.col-links {{ width: 120px; text-align: center; }}
            th.col-assets {{ width: 160px; text-align: center; white-space: nowrap; }}
            th.col-title {{ width: 30%; }}
            th.col-year {{ width: 70px; }}
            th.col-missing {{ width: auto; }}
            
            tr {{ transition: background-color 0.1s; border-left: 4px solid transparent; }}
            tr:hover {{ background-color: var(--hover); }}
            
            /* Keyboard Selection Style */
            tr.selected {{ background-color: var(--highlight); border-left: 4px solid var(--accent); }}
            
            /* Asset Buttons: Compact, Single Line */
            .asset-btn {{ text-decoration: none; font-size: 14px; padding: 2px; margin: 0 1px; display: inline-block; opacity: 0.5; filter: none; transition: all 0.2s; }}
            tr:hover .asset-btn, tr.selected .asset-btn {{ opacity: 1; transform: scale(1.1); }}
            .asset-btn:hover {{ transform: scale(1.4) !important; opacity: 1; }}

            .badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; text-decoration: none; margin-right: 4px; color: white; margin-bottom: 2px; }}
            .tmdb {{ background-color: var(--tmdb); }}
            .tvdb {{ background-color: var(--tvdb); }}
            .fanart {{ background-color: var(--fanart); }}
            .season-tag {{ color: #ffb74d; font-size: 13px; font-weight: 500; }}
            .missing-text {{ color: var(--text-muted); font-style: italic; font-size: 12px; opacity: 0.5; }}
            
            .check-btn {{ background: transparent; border: 2px solid var(--text-muted); color: var(--text-muted); width: 24px; height: 24px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; margin: 0 auto; }}
            .check-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
            
            .copy-btn {{ background: var(--copy-btn-bg); border: 1px solid var(--border); color: var(--text-muted); width: 28px; height: 28px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; margin: 0 auto; }}
            .copy-btn:hover {{ background: var(--hover); color: var(--text-main); }}
            .copy-btn.copied {{ background: var(--tvdb); color: white; border-color: var(--tvdb); }}
            
            .pagination {{ display: flex; justify-content: center; align-items: center; gap: 5px; padding: 10px; background: var(--card-bg); border-radius: 8px; margin-top: 10px; }}
            .page-btn {{ background: var(--hover); border: none; color: var(--text-main); padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; }}
            .page-btn.active {{ background: var(--accent); color: #000; font-weight: bold; }}
            .page-btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}

            tr.hidden {{ display: none !important; }}
            
            .shortcuts-legend {{ font-size: 12px; color: var(--text-muted); background: var(--card-bg); padding: 8px 12px; border-radius: 4px; margin-bottom: 10px; display: inline-block; }}
            .key {{ background: #444; color: #fff; padding: 2px 6px; border-radius: 3px; font-family: monospace; font-weight: bold; }}
        </style>
    </head>
    <body>

    <div class="container">
        <header>
            <h1>Missing Posters</h1>
            <div>
                <button class="action-btn undo-btn" onclick="undoHide()">⎌ Undo (U)</button>
                <button class="action-btn" id="toggleHiddenBtn" onclick="toggleShowHidden()">Show All Hidden</button>
            </div>
        </header>

        <div class="shortcuts-legend">
            <strong>Hotkeys:</strong> <span class="key">↑</span> <span class="key">↓</span> Navigate &nbsp;|&nbsp; 
            <span class="key">←</span> <span class="key">→</span> Tabs &nbsp;|&nbsp; 
            <span class="key">Space</span> Toggle Done &nbsp;|&nbsp; 
            <span class="key">U</span> Undo &nbsp;|&nbsp; 
            <span class="key">C</span> Copy &nbsp;|&nbsp; 
            <span class="key">L</span> TMDB Logos &nbsp;|&nbsp; 
            <span class="key">P</span> TMDB Posters &nbsp;|&nbsp; 
            <span class="key">F</span> Fanart.tv
        </div>

        <div class="controls-bar">
            <div class="tabs">
                <button class="tab-btn active" onclick="openTab('movies')">Movies ({c_mov})</button>
                <button class="tab-btn" onclick="openTab('series')">Series ({c_ser})</button>
                <button class="tab-btn" onclick="openTab('collections')">Collections ({c_col})</button>
            </div>
            <input type="text" id="searchInput" class="search-box" placeholder="Search titles..." onkeyup="handleSearch()">
        </div>

    """

    categories = [("movies", "Movies"), ("series", "Series"), ("collections", "Collections")]

    for key, display_name in categories:
        items = data.get(key, [])
        active_class = "active" if key == "movies" else ""
        
        tmdb_type = "movie"
        if key == "series": tmdb_type = "tv"
        if key == "collections": tmdb_type = "collection"

        html_content += f"""
        <div id="{key}" class="tab-content {active_class}">
            <table id="table-{key}">
                <thead>
                    <tr>
                        <th class="col-done">Done</th>
                        <th class="col-copy">Copy</th>
                        <th class="col-links">Links</th>
                        <th class="col-assets">Assets</th>
                        <th class="col-title">Title</th>
                        <th class="col-year">Year</th>
                        <th class="col-missing">Missing</th>
                    </tr>
                </thead>
                <tbody id="tbody-{key}">
        """
        
        for item in items:
            title = item.get("title", "Unknown")
            year = item.get("year", "")
            
            missing_info = ""
            if key == "series":
                seasons = item.get("missing_seasons", [])
                if seasons:
                    formatted_seasons = ", ".join([f"S{s}" for s in sorted(seasons)])
                    missing_info = f'<span class="season-tag">{formatted_seasons}</span>'
                else:
                    missing_info = '<span class="missing-text">-</span>'
            else:
                missing_info = '<span class="missing-text">-</span>'

            unique_id = f"{key}_{title}_{year}".replace(" ", "").replace("'", "")
            tmdb_link = item.get("tmdbLink")
            tvdb_link = item.get("tvdbLink")
            tmdb_id = item.get("tmdbId")
            tvdb_id = item.get("tvdbId")
            
            assets_html = '<span class="missing-text">-</span>'
            
            # Fanart Search with Year + Sector All
            fanart_query = urllib.parse.quote(f"{title} ({year})")
            fanart_url = f"https://fanart.tv/?s={fanart_query}&sect=all"
            
            # Google Queries (Logo)
            google_url = f"https://www.google.com/search?tbm=isch&q={title}+({year})"
            
            bendodson_url = "https://bendodson.com/projects/apple-tv-movies-artwork-finder/pre-ios26/"
            
            if tmdb_id:
                logo_url = f"https://www.themoviedb.org/{tmdb_type}/{tmdb_id}/images/logos"
                poster_url = f"https://www.themoviedb.org/{tmdb_type}/{tmdb_id}/images/posters"
                
                clean_title_js = title.replace("'", "\\'")
                
                assets_html = f"""
                    <a href="{logo_url}" target="_blank" class="asset-btn btn-logo" title="TMDB Logos (L)">🎨</a>
                    <a href="{poster_url}" target="_blank" class="asset-btn btn-poster" title="TMDB Posters (P)">🖼️</a>
                    <a href="{fanart_url}" target="_blank" class="asset-btn btn-fanart" title="Fanart.tv (F)">📺</a>
                    <a href="#" onclick="openBenDodson('{clean_title_js}'); return false;" class="asset-btn" title="Copy & Open Apple TV Finder">🍎</a>
                    <a href="{google_url}" target="_blank" class="asset-btn" title="Google Search">🔎</a>
                """

            links_html = ""
            if tmdb_link: links_html += f'<a href="{tmdb_link}" target="_blank" class="badge tmdb">TMDB</a>'
            if tvdb_link: links_html += f'<a href="{tvdb_link}" target="_blank" class="badge tvdb">TVDB</a>'
            if not links_html: links_html = '<span class="missing-text">-</span>'

            if key == "collections":
                clean_t = title.strip()
                if not clean_t.lower().endswith("collection"):
                    copy_text = f"{clean_t} Collection"
                else:
                    copy_text = clean_t
            else:
                copy_text = f"{title} ({year})"
            
            safe_copy_text = copy_text.replace("'", "&#39;")
            js_copy_text = copy_text.replace("'", "\\'")

            html_content += f"""
            <tr id="row-{unique_id}" class="data-row" data-title="{title.lower()}">
                <td style="text-align: center;"><button class="check-btn" onclick="toggleHide('{unique_id}')" title="Mark as Done (Space)">✔</button></td>
                <td style="text-align: center;"><button class="copy-btn" onclick="copyToClipboard('{js_copy_text}', this)" title="Copy {safe_copy_text} (C)">📋</button></td>
                <td style="text-align: center;">{links_html}</td>
                <td style="text-align: center;" class="col-assets">{assets_html}</td>
                <td style="font-weight: 500;">{title}</td>
                <td style="color: var(--text-muted);">{year}</td>
                <td>{missing_info}</td>
            </tr>
            """
        
        html_content += f"""
                </tbody>
            </table>
            
            <div class="pagination" id="pagination-{key}"></div>
        </div>
        """

    html_content += f"""
    </div>

    <script>
        const ITEMS_PER_PAGE = {ITEMS_PER_PAGE};
        const STORAGE_KEY = 'poster_hidden_items';
        
        let state = {{
            movies: {{ page: 1, rows: [] }},
            series: {{ page: 1, rows: [] }},
            collections: {{ page: 1, rows: [] }}
        }};

        let currentTab = 'movies';
        let selectedIndex = 0; 
        let undoStack = [];
        let showHiddenMode = false;
        
        const tabKeys = ['movies', 'series', 'collections'];

        window.onload = function() {{
            ['movies', 'series', 'collections'].forEach(type => {{
                const tbody = document.getElementById('tbody-' + type);
                if(tbody) {{
                    state[type].rows = Array.from(tbody.getElementsByClassName('data-row'));
                }}
            }});
            renderTable('movies');
            renderTable('series');
            renderTable('collections');
            
            document.addEventListener('keydown', handleKeydown);
            
            // Explicitly highlight the first item of the starting tab on load
            setTimeout(() => {{
                const visibleRows = getVisibleRows();
                if(visibleRows.length > 0) {{
                    selectedIndex = 0;
                    highlightRow(visibleRows);
                }}
            }}, 100);
        }};

        function getHiddenItems() {{ 
            const stored = localStorage.getItem(STORAGE_KEY); 
            return stored ? JSON.parse(stored) : []; 
        }}
        
        function saveHiddenItems(items) {{ 
            localStorage.setItem(STORAGE_KEY, JSON.stringify(items)); 
        }}

        function renderTable(type) {{
            const s = state[type];
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const hiddenItems = getHiddenItems();
            
            const filteredRows = s.rows.filter(row => {{
                const rowId = row.id.replace('row-', '');
                const title = row.getAttribute('data-title');
                
                const matchesSearch = title.includes(searchTerm);
                const isHidden = hiddenItems.includes(rowId) && !showHiddenMode;
                
                if (showHiddenMode && hiddenItems.includes(rowId)) {{
                    row.style.opacity = '0.3';
                }} else {{
                    row.style.opacity = '1';
                }}

                return matchesSearch && !isHidden;
            }});

            s.rows.forEach(r => r.style.display = 'none');

            const totalPages = Math.ceil(filteredRows.length / ITEMS_PER_PAGE) || 1;
            if (s.page > totalPages) s.page = totalPages;
            if (s.page < 1) s.page = 1;

            const start = (s.page - 1) * ITEMS_PER_PAGE;
            const end = start + ITEMS_PER_PAGE;
            const visibleRows = filteredRows.slice(start, end);

            visibleRows.forEach(r => r.style.display = 'table-row');
            
            renderPagination(type, totalPages, s.page);
            
            // Only force reset/highlight if we are re-rendering the ACTIVE tab
            if (type === currentTab) {{
                selectedIndex = 0;
                highlightRow(visibleRows);
            }}
        }}

        function renderPagination(type, totalPages, currentPage) {{
            const container = document.getElementById(`pagination-${{type}}`);
            let html = '';
            
            html += `<button class="page-btn" onclick="setPage('${{type}}', ${{currentPage - 1}})" ${{currentPage === 1 ? 'disabled' : ''}}>Prev</button>`;
            
            let startPage = Math.max(1, currentPage - 2);
            let endPage = Math.min(totalPages, startPage + 4);
            if (endPage - startPage < 4) startPage = Math.max(1, endPage - 4);

            if (startPage > 1) html += `<span style="color:#666">...</span>`;

            for (let i = startPage; i <= endPage; i++) {{
                const activeClass = i === currentPage ? 'active' : '';
                html += `<button class="page-btn ${{activeClass}}" onclick="setPage('${{type}}', ${{i}})">${{i}}</button>`;
            }}

            if (endPage < totalPages) html += `<span style="color:#666">...</span>`;
            
            html += `<button class="page-btn" onclick="setPage('${{type}}', ${{currentPage + 1}})" ${{currentPage === totalPages ? 'disabled' : ''}}>Next</button>`;
            
            container.innerHTML = html;
        }}

        function setPage(type, pageNum) {{
            if (pageNum < 1) return;
            state[type].page = pageNum;
            renderTable(type);
        }}

        function getVisibleRows() {{
            const tbody = document.getElementById('tbody-' + currentTab);
            return Array.from(tbody.children).filter(r => r.style.display !== 'none');
        }}

        function handleKeydown(e) {{
            if (document.activeElement.tagName === 'INPUT') return;

            const visibleRows = getVisibleRows();
            
            if (e.key === 'ArrowDown') {{
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, visibleRows.length - 1);
                highlightRow(visibleRows);
                scrollToRow(visibleRows[selectedIndex]);
            }} else if (e.key === 'ArrowUp') {{
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, 0);
                highlightRow(visibleRows);
                scrollToRow(visibleRows[selectedIndex]);
            }} else if (e.key === 'ArrowRight') {{
                const idx = tabKeys.indexOf(currentTab);
                const nextIdx = (idx + 1) % tabKeys.length;
                openTab(tabKeys[nextIdx]);
            }} else if (e.key === 'ArrowLeft') {{
                const idx = tabKeys.indexOf(currentTab);
                const prevIdx = (idx - 1 + tabKeys.length) % tabKeys.length;
                openTab(tabKeys[prevIdx]);
            }} else if (e.key.toLowerCase() === 'u') {{
                undoHide();
            }} else if (visibleRows.length > 0 && selectedIndex >= 0 && selectedIndex < visibleRows.length) {{
                const row = visibleRows[selectedIndex];
                
                if (e.code === 'Space') {{
                    e.preventDefault();
                    row.querySelector('.check-btn').click();
                }} else if (e.key.toLowerCase() === 'c') {{
                    row.querySelector('.copy-btn').click();
                }} else if (e.key.toLowerCase() === 'l') {{
                    const link = row.querySelector('.btn-logo');
                    if(link) window.open(link.href, '_blank');
                }} else if (e.key.toLowerCase() === 'p') {{
                    const link = row.querySelector('.btn-poster');
                    if(link) window.open(link.href, '_blank');
                }} else if (e.key.toLowerCase() === 'f') {{
                    const link = row.querySelector('.btn-fanart');
                    if(link) window.open(link.href, '_blank');
                }}
            }}
        }}

        function highlightRow(visibleRows) {{
            document.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
            if (!visibleRows) visibleRows = getVisibleRows();
            
            if (visibleRows.length > 0) {{
                if(selectedIndex >= visibleRows.length) selectedIndex = visibleRows.length - 1;
                if(selectedIndex < 0) selectedIndex = 0;
                visibleRows[selectedIndex].classList.add('selected');
            }}
        }}

        function scrollToRow(row) {{
            if (row) {{
                row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}

        function handleSearch() {{
            state.movies.page = 1;
            state.series.page = 1;
            state.collections.page = 1;
            renderTable(currentTab);
        }}

        function openTab(tabName) {{
            currentTab = tabName;
            var i, x, tablinks;
            x = document.getElementsByClassName("tab-content");
            for (i = 0; i < x.length; i++) {{ x[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tab-btn");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
            document.getElementById(tabName).style.display = "block";
            
            const buttons = document.getElementsByClassName("tab-btn");
            if (tabName === 'movies') buttons[0].className += " active";
            if (tabName === 'series') buttons[1].className += " active";
            if (tabName === 'collections') buttons[2].className += " active";

            renderTable(tabName);
        }}

        function toggleHide(id) {{
            const row = document.getElementById('row-' + id);
            const hidden = getHiddenItems();
            
            if (hidden.includes(id)) {{
                // UNHIDE
                const newHidden = hidden.filter(i => i !== id);
                saveHiddenItems(newHidden);
            }} else {{
                // HIDE
                hidden.push(id);
                saveHiddenItems(hidden);
                undoStack.push(id); 
                if(undoStack.length > 20) undoStack.shift(); 
            }}
            
            if (showHiddenMode) {{
                // Just update styling without moving list
                if (row) {{
                    const isNowHidden = getHiddenItems().includes(id);
                    row.style.opacity = isNowHidden ? '0.3' : '1';
                }}
            }} else {{
                renderTable(currentTab);
            }}
        }}

        function undoHide() {{
            if (undoStack.length === 0) return;
            const idToRestore = undoStack.pop();
            
            const hidden = getHiddenItems();
            const newHidden = hidden.filter(id => id !== idToRestore);
            saveHiddenItems(newHidden);
            
            renderTable(currentTab);
        }}

        function toggleShowHidden() {{
            showHiddenMode = !showHiddenMode;
            const btn = document.getElementById('toggleHiddenBtn');
            btn.innerText = showHiddenMode ? "Hide Checked Items" : "Show All Hidden";
            renderTable(currentTab);
        }}

        function copyToClipboard(text, btn) {{
            navigator.clipboard.writeText(text).then(() => {{
                if(btn) {{
                    const originalContent = btn.innerHTML;
                    btn.innerHTML = '✔';
                    btn.classList.add('copied');
                    setTimeout(() => {{
                        btn.innerHTML = originalContent;
                        btn.classList.remove('copied');
                    }}, 2000);
                }}
            }}).catch(err => {{ console.error('Failed to copy', err); }});
        }}

        function openBenDodson(title) {{
            copyToClipboard(title, null);
            window.open("https://bendodson.com/projects/apple-tv-movies-artwork-finder/pre-ios26/", "_blank");
        }}
    </script>
    </body>
    </html>
    """
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ HTML Report generated: {filename}")

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: Input file '{INPUT_FILE}' not found.")
        return

    matcher = SmartMatcher(TMDB_API_KEY)

    radarr_servers = collect_servers("RADARR")
    sonarr_servers = collect_servers("SONARR")

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("📥 Fetching Radarr libraries...")
    radarr_movies = fetch_aggregated_library(radarr_servers, "movie")
    radarr_collections = fetch_aggregated_library(radarr_servers, "collection")

    print("📥 Fetching Sonarr libraries...")
    sonarr_series = fetch_aggregated_library(sonarr_servers, "series")

    print(f"🔎 Matching Movies...")
    for item in data.get("movies", []):
        match = find_match_hybrid(item["title"], item.get("year"), radarr_movies, matcher, "movie")
        if match:
            links = generate_links(match, "movie")
            item.update({"tmdbId": links["tmdbId"], "tmdbLink": links["tmdbUrl"], "tvdbId": links["tvdbId"], "tvdbLink": links["tvdbUrl"]})

    print(f"🔎 Matching Collections...")
    for item in data.get("collections", []):
        match = find_match_hybrid(item["title"], 0, radarr_collections, matcher, "collection")
        if match:
            links = generate_links(match, "collection")
            item.update({"tmdbId": links["tmdbId"], "tmdbLink": links["tmdbUrl"]})

    print(f"🔎 Matching Series...")
    for item in data.get("series", []):
        match = find_match_hybrid(item["title"], item.get("year"), sonarr_series, matcher, "series")
        if match:
            links = generate_links(match, "tv") 
            item.update({"tmdbId": links["tmdbId"], "tmdbLink": links["tmdbUrl"], "tvdbId": links["tvdbId"], "tvdbLink": links["tvdbUrl"]})

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"✅ JSON Output saved: {OUTPUT_JSON}")

    create_html_report(data, OUTPUT_HTML)
    
    if OPEN_REPORT:
        webbrowser.open('file://' + os.path.realpath(OUTPUT_HTML))

if __name__ == "__main__":
    main()