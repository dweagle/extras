import os
import re
import requests
import datetime
import webbrowser
import logging
import time

# =================================================
# ================= CONFIGURATION =================
# =================================================

# Replace with your TMDB API Key
TMDB_API_KEY = "tmdb_api_key"

# DICTIONARY OF LIBRARIES EXAMPLES
# Format: "Library or Tab Name": "/path/to/folder"
# Delete unneeded or add multple 
LIBRARY_CONFIG = {
    "CL2K": "/path/to/folder",
    "MM2K": "/path/to/folder",
    "Logos": "C:/path/to/folder"
}

# Output files
REPORT_FILE = "poster_todo_list.html"
LOG_FILE = "check_seasons.log"

# How many days into the future to look?
# I wouldn't set this too far ahead as there are not usually poster assets
# available too far ahead unless the show is pretty mainstream.
LOOKAHEAD_DAYS = 21 

# =================================================
# ============= DO NOT EDIT PAST HERE =============
# =================================================

TMDB_REGEX = r'\{tmdb-(\d+)\}' 
TVDB_REGEX = r'\{tvdb-(\d+)\}'
SEASON_NUMBER_REGEX = r'(?i)\s-\sseason\s*(\d+)'
SPECIALS_REGEX = r'(?i)\s-\sspecials'

# Logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)

# Terminal Progress Bar
def print_progress(iteration, total, prefix='', suffix='', decimals=1, length=40):
    if total == 0:
        return
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end = '\r')
    if iteration == total: 
        print()

# Get Show From File Names
def get_show_name_from_file(filename):
    match = re.match(r'^(.*?)\s*[\(\{]', filename)
    if match:
        return match.group(1).strip()
    return filename 

# Organize File Names (buffer to organize)
def scan_library(path, library_name):
    inventory = {}
    log_buffer = {}
    
    logging.info(f"--- SCANNING LIBRARY: {library_name} ({path}) ---")
    print(f"\n[{library_name}] Scanning folders for existing posters...")
    
    if not os.path.exists(path):
        logging.error(f"Path not found: {path}")
        print(f"Error: Path not found: {path}")
        return {}

    for root, dirs, files in os.walk(path):
        for filename in files:
            tmdb_match = re.search(TMDB_REGEX, filename, re.IGNORECASE)
            
            if tmdb_match:
                tmdb_id = tmdb_match.group(1)
                
                # Check if the file is a show
                has_tvdb = re.search(TVDB_REGEX, filename, re.IGNORECASE)
                season_match = re.search(SEASON_NUMBER_REGEX, filename, re.IGNORECASE)
                specials_match = re.search(SPECIALS_REGEX, filename, re.IGNORECASE)

                if has_tvdb or season_match or specials_match:
                    if tmdb_id not in inventory:
                        inventory[tmdb_id] = set()
                    
                    if tmdb_id not in log_buffer:
                        show_name = get_show_name_from_file(filename)
                        log_buffer[tmdb_id] = {'name': show_name, 'main': [], 'seasons': set()}
                    
                    if season_match:
                        s_num = int(season_match.group(1))
                        inventory[tmdb_id].add(s_num)
                        log_buffer[tmdb_id]['seasons'].add(s_num)
                    
                    elif specials_match:
                        inventory[tmdb_id].add(0)
                        log_buffer[tmdb_id]['seasons'].add(0)
                        
                    else:
                        log_buffer[tmdb_id]['main'].append(filename)

    # Work with files and log
    sorted_shows = sorted(log_buffer.values(), key=lambda x: x['name'].lower())
    
    for show_data in sorted_shows:
        show_name = show_data['name']
        
        for main_file in show_data['main']:
            logging.info(f"Found Show file: {main_file}")
        
        if show_data['seasons']:
            sorted_seasons = sorted(list(show_data['seasons']))
            season_strings = [str(s) for s in sorted_seasons]
            season_log_line = ", ".join(season_strings)
            logging.info(f"    Found existing seasons for '{show_name}': {season_log_line}")

    logging.info(f"Scan complete for {library_name}. Found {len(inventory)} unique shows.")
    print(f"[{library_name}] Found {len(inventory)} unique shows.")
    return inventory

# TMDB API Show status search
def check_show_status(tmdb_id, existing_seasons):
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logging.error(f"Connection error for ID {tmdb_id}: {e}")
        return None
    
    if response.status_code != 200:
        logging.warning(f"API Error {response.status_code} for ID {tmdb_id}")
        return None

    data = response.json()
    name = data.get('name', 'Unknown')
    next_ep = data.get('next_episode_to_air')
    
    today = datetime.date.today()
    future_limit = today + datetime.timedelta(days=LOOKAHEAD_DAYS)

    if not next_ep:
        return None

    ep_date_str = next_ep.get('air_date')
    season_num = next_ep.get('season_number')
    episode_num = next_ep.get('episode_number')
    
    if not ep_date_str:
        return None

    ep_date = datetime.datetime.strptime(ep_date_str, "%Y-%m-%d").date()

    if (today <= ep_date <= future_limit) and (episode_num == 1):
        
        poster_exists = season_num in existing_seasons
        
        logging.info(f"MATCH: {name} - Season {season_num} starts {ep_date_str}. Poster exists: {poster_exists}")
        
        return {
            'name': name,
            'homepage': f"https://www.themoviedb.org/tv/{tmdb_id}",
            'season_number': season_num,
            'date': ep_date_str,
            'poster_exists': poster_exists
        }

    return None

# Results page
def generate_html_report(all_library_results):
    html_content = f"""
    <html>
    <head>
        <title>Poster To-Do List</title>
        <style>
            html {{
                overflow-y: scroll; /* Prevents layout shift */
            }}
            body {{ 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: #1a1a1a; 
                color: #e0e0e0; 
                padding: 20px;
                text-align: center; 
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
                text-align: left;
            }}
            h1 {{ color: #fff; border-bottom: 2px solid #444; padding-bottom: 5px; text-align: center; margin-bottom: 5px; }}
            
            .scan-range {{ 
                color: #4db8ff; 
                text-align: center; 
                font-size: 1.3em; 
                font-weight: bold;
                margin-bottom: 25px; 
                text-shadow: 0 0 10px rgba(77, 184, 255, 0.3);
            }}

            /* --- MODERN PILL TABS --- */
            .tab {{
                display: flex;
                flex-wrap: wrap;      /* Allow wrapping */
                gap: 8px;             /* Space between buttons */
                justify-content: center; /* Center the buttons */
                margin-bottom: 20px;
                border-bottom: 1px solid #444;
                padding-bottom: 20px;
            }}
            
            .tab button {{
                background-color: #333;
                border: 1px solid #555;
                border-radius: 30px;   /* Rounded Pill Shape */
                outline: none;
                cursor: pointer;
                padding: 10px 20px;
                transition: 0.3s;
                font-size: 15px;
                color: #ccc;
                font-weight: bold;
                
                /* Sizing Logic */
                flex: 1 1 auto;        /* Grow to fill space, shrink if needed */
                min-width: 100px;      /* Never get smaller than this */
                max-width: 250px;      /* Never get wider than this (prevents giant buttons) */
                text-align: center;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}

            .tab button:hover {{ 
                background-color: #444; 
                color: #fff; 
                border-color: #777;
            }}
            
            .tab button.active {{ 
                background-color: #4db8ff; 
                color: #111; 
                border-color: #4db8ff;
                box-shadow: 0 0 10px rgba(77, 184, 255, 0.4);
            }}
            
            .tabcontent {{
                display: none;
                animation: fadeEffect 0.5s;
                min-height: 200px; 
            }}
            @keyframes fadeEffect {{ from {{opacity: 0;}} to {{opacity: 1;}} }}
            
            /* STATS DASHBOARD */
            .stats-container {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 30px;
                gap: 15px;
                flex-wrap: wrap; 
            }}
            .stat-card {{
                background: #2d2d2d;
                flex: 1;
                min-width: 120px; 
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                box-shadow: 0 4px 6px rgba(0,0,0,0.2);
                border-top: 4px solid #444;
            }}
            .stat-number {{ font-size: 2em; font-weight: bold; display: block; }}
            .stat-label {{ font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; color: #888; }}
            
            /* Stat Colors */
            .stat-total {{ border-top-color: #4db8ff; }}
            .stat-total .stat-number {{ color: #4db8ff; }}
            .stat-upcoming {{ border-top-color: #9c27b0; }}
            .stat-upcoming .stat-number {{ color: #9c27b0; }}
            .stat-needed {{ border-top-color: #FF9800; }}
            .stat-needed .stat-number {{ color: #FF9800; }}
            .stat-ready {{ border-top-color: #4CAF50; }}
            .stat-ready .stat-number {{ color: #4CAF50; }}

            /* CARDS */
            .card {{ 
                background: #333; 
                padding: 12px 15px; 
                margin-bottom: 12px; 
                border-radius: 6px; 
                border-left: 6px solid #4db8ff; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.2); 
            }}
            .card.done {{ border-left-color: #4CAF50; opacity: 0.8; }}
            .card.todo {{ border-left-color: #FF9800; }}
            
            .show-title {{
                font-size: 1.3em;
                font-weight: bold;
                display: inline-block;
                color: #fff; 
                text-decoration: none;
                margin-bottom: 2px;
            }}
            .show-title:hover {{ text-decoration: underline; color: #ccc; }}
            
            .show-link {{ font-size: 0.75em; color: #666; display: block; margin-bottom: 5px; font-family: monospace; }}
            .meta {{ font-size: 1.0em; color: #ccc; }}
            .date {{ color: #fff; font-weight: bold; }}
            
            .badge-premiere {{ 
                background: #444; color: #fff; padding: 3px 6px; border-radius: 4px; 
                font-size: 0.7em; float: right; text-transform: uppercase; letter-spacing: 1px; margin-left: 8px;
            }}
            .status-icon {{
                float: right; font-weight: bold; font-size: 0.9em; margin-left: 10px; 
                padding: 3px 8px; border-radius: 4px;
            }}
            .status-todo {{ background: rgba(255, 152, 0, 0.2); color: #FF9800; border: 1px solid #FF9800; }}
            .status-done {{ background: rgba(76, 175, 80, 0.2); color: #4CAF50; border: 1px solid #4CAF50; }}
        </style>
        
        <script>
        function openTab(evt, libName) {{
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {{
                tabcontent[i].style.display = "none";
            }}
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {{
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }}
            document.getElementById(libName).style.display = "block";
            evt.currentTarget.className += " active";
        }}
        </script>
    </head>
    <body>
        <div class="container">
            <h1>TV Season Monitor</h1>
            <div class="scan-range">Scanning for premieres within the next {LOOKAHEAD_DAYS} days</div>
            
            <div class="tab">
    """
    
    first_lib = True
    for lib_name in all_library_results.keys():
        active_class = " active" if first_lib else ""
        html_content += f'<button class="tablinks{active_class}" onclick="openTab(event, \'{lib_name}\')">{lib_name}</button>\n'
        first_lib = False
        
    html_content += "</div>\n"

    # Create Tab Content
    is_first_content = True
    for lib_name, data in all_library_results.items():
        shows = data['shows']
        total_scanned = data['total_scanned']
        
        total_upcoming = len(shows)
        posters_needed = sum(1 for s in shows if not s['poster_exists'])
        posters_ready = total_upcoming - posters_needed
        
        display_style = "block" if is_first_content else "none"
        is_first_content = False
        
        html_content += f'<div id="{lib_name}" class="tabcontent" style="display: {display_style};">\n'
        
        html_content += f"""
            <div class="stats-container">
                <div class="stat-card stat-total">
                    <span class="stat-number">{total_scanned}</span>
                    <span class="stat-label">Unique Shows</span>
                </div>
                <div class="stat-card stat-upcoming">
                    <span class="stat-number">{total_upcoming}</span>
                    <span class="stat-label">Premieres Found</span>
                </div>
                <div class="stat-card stat-needed">
                    <span class="stat-number">{posters_needed}</span>
                    <span class="stat-label">Posters Needed</span>
                </div>
                <div class="stat-card stat-ready">
                    <span class="stat-number">{posters_ready}</span>
                    <span class="stat-label">Ready to Go</span>
                </div>
            </div>
        """
        
        if not shows:
             html_content += f"<p style='text-align:center;'>No upcoming premieres in this library.</p>"
        
        shows.sort(key=lambda x: x['date'])
        for show in shows:
            if show['poster_exists']:
                card_class = "done"
                status_html = '<span class="status-icon status-done">✅ Poster Ready</span>'
            else:
                card_class = "todo"
                status_html = '<span class="status-icon status-todo">🎨 Needs Poster</span>'
            
            season_text = f"Season {show['season_number']}"
            if show['season_number'] == 0:
                season_text = "Specials"

            html_content += f"""
            <div class="card {card_class}">
                <span class="badge-premiere">Season Premiere</span>
                {status_html}
                <a href="{show['homepage']}" target="_blank" class="show-title">
                    {show['name']} 🔗
                </a>
                <span class="show-link">{show['homepage']}</span>
                <div class="meta">
                    {season_text} starts: <span class="date">{show['date']}</span>
                </div>
            </div>
            """
        
        html_content += "</div>\n"

    html_content += """
        </div>
    </body>
    </html>
    """
    
    with open(REPORT_FILE, "w", encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\nReport generated: {os.path.abspath(REPORT_FILE)}")
    logging.info(f"Report generated.")

# MAIN
if __name__ == "__main__":
    
    all_results = {}
    
    for lib_name, lib_path in LIBRARY_CONFIG.items():
        inventory = scan_library(lib_path, lib_name)
        
        if not inventory and not os.path.exists(lib_path):
            all_results[lib_name] = {'shows': [], 'total_scanned': 0}
            continue

        tmdb_ids = list(inventory.keys())
        total = len(tmdb_ids)
        
        current_lib_shows = []
        
        print(f"[{lib_name}] Checking TMDB API for upcoming seasons...")
        print_progress(0, total, prefix='Progress:', suffix='Complete', length=40)

        for i, tmdb_id in enumerate(tmdb_ids):
            existing_seasons = inventory[tmdb_id]
            result = check_show_status(tmdb_id, existing_seasons)
            
            if result:
                current_lib_shows.append(result)
            
            # TMDB RATE LIMIT
            time.sleep(0.1)
            print_progress(i + 1, total, prefix='Progress:', suffix='Complete', length=40)
        
        all_results[lib_name] = {
            'shows': current_lib_shows,
            'total_scanned': len(inventory)
        }
        
    generate_html_report(all_results)
    webbrowser.open('file://' + os.path.abspath(REPORT_FILE))