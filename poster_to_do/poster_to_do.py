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
    "Logos": "C:/path/to/folder" #possible Windows example
}

# DISCORD SETTINGS
# Paste your Webhook URL here. Leave empty "" to disable Discord.
DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"

# Set to True if you ONLY want pings when a poster is MISSING.
DISCORD_NOTIFY_MISSING_ONLY = False

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

# TRANSPARENT SPACER IMAGE TO KEEP DISCORD MESSAGES CONSISTANT WIDTH
SPACER_IMAGE_URL = "https://raw.githubusercontent.com/dweagle/extras/refs/heads/main/poster_to_do/spacer.png"

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

# DISCORD FUNCTIONS
def send_discord_start():
    # Sends a start message to Discord
    if not DISCORD_WEBHOOK_URL:
        return
    
    folder_names = "\n".join([f"• {name}" for name in LIBRARY_CONFIG.keys()])
    
    data = {
        "embeds": [{
            "title": "🚀 Season Monitor Started",
            "color": 5093631, # Blue
            "fields": [
                {"name": "Scanning Folders", "value": folder_names, "inline": True},
                {"name": "Timeframe", "value": f"Next {LOOKAHEAD_DAYS} Days", "inline": True},
                {"name": "Display", "value": "Needed Only" if DISCORD_NOTIFY_MISSING_ONLY else "All Items", "inline": True}
            ],
            "footer": {"text": "Season Monitor Script"},
            "image": {"url": SPACER_IMAGE_URL}
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        print(" [Discord] Start notification sent.")
    except Exception as e:
        logging.error(f"Discord Start Failed: {e}")

def send_discord_end(global_scanned, global_upcoming, global_needed):
    # Sends a completion message to Discord
    if not DISCORD_WEBHOOK_URL:
        return
    
    folder_names = "\n".join([f"• {name}" for name in LIBRARY_CONFIG.keys()])

    data = {
        "embeds": [{
            "title": "🏁 Season Monitor Finished",
            "description": "**Folders Scanned:**\n" + folder_names,
            "color": 5093631, # Blue
            "fields": [
                {"name": "Total Scanned", "value": str(global_scanned), "inline": True},
                {"name": "Premieres Found", "value": str(global_upcoming), "inline": True},
                {"name": "Total Missing", "value": str(global_needed), "inline": True}
            ],
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "footer": {"text": "Season Monitor Script"},
            "image": {"url": SPACER_IMAGE_URL}
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        print(" [Discord] Completion notification sent.")
    except Exception as e:
        logging.error(f"Discord End Failed: {e}")

def send_discord_library_report(library_name, shows, total_scanned):
    # Sends a final report.
    if not DISCORD_WEBHOOK_URL:
        return

    # Filter based on user preference
    if DISCORD_NOTIFY_MISSING_ONLY:
        shows_to_report = [s for s in shows if not s['poster_exists']]
    else:
        shows_to_report = shows

    # Calculate Stats
    count_upcoming = len(shows)
    count_needed = sum(1 for s in shows if not s['poster_exists'])
    
    if not shows_to_report and DISCORD_NOTIFY_MISSING_ONLY:
        return

    # Determine Sidebar Color
    if count_needed > 0:
        color = 16750592 # Orange (Needs Action)
    else:
        color = 5025616  # Green (All Good)

    # Sort Chronologically
    shows_to_report.sort(key=lambda x: x['date'])

    # Build the List
    description_lines = []
    for s in shows_to_report:
        icon = "🎨" if not s['poster_exists'] else "✅"
        season_txt = "Specials" if s['season_number'] == 0 else f"S{s['season_number']:02d}"
        
        line = f"{icon} **[{s['name']}]({s['homepage']})** ({season_txt})\n`{s['date']}`"
        description_lines.append(line)

    if not description_lines:
        description_lines.append("_No upcoming premieres found._")

    full_description = "\n".join(description_lines)
    
    if len(full_description) > 3800:
        full_description = full_description[:3800] + "\n\n...(List truncated)..."

    data = {
        "embeds": [{
            "title": "Posters Needed", 
            "color": color,
            "fields": [
                {
                    "name": "📂 Folder",
                    "value": f"**{library_name}**",
                    "inline": True
                },
                {
                    "name": "🔎 Premieres",
                    "value": f"{count_upcoming} Found",
                    "inline": True
                },
                {
                    "name": "🎨 Action",
                    "value": f"{count_needed} Needed",
                    "inline": True
                }
            ],
            "description": f"**Upcoming Seasons:**\n\n{full_description}",
            "footer": {
                "text": f"Scanned {total_scanned} items"
            },
            "image": {"url": SPACER_IMAGE_URL}
        }]
    }

    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        print(f" [Discord] Report sent for '{library_name}'.")
    except Exception as e:
        logging.error(f"Discord Library Report Failed: {e}")


def get_show_name_from_file(filename):
    match = re.match(r'^(.*?)\s*[\(\{]', filename)
    if match:
        return match.group(1).strip()
    return filename 

def scan_library(path, library_name):
    inventory = {}
    log_buffer = {}
    
    logging.info(f"--- SCANNING FOLDER: {library_name} ({path}) ---")
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

def generate_html_report(all_library_results):
    html_content = f"""
    <html>
    <head>
        <title>Poster To-Do List</title>
        <style>
            html {{ overflow-y: scroll; }}
            body {{ 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: #1a1a1a; 
                color: #e0e0e0; 
                padding: 20px;
                text-align: center; 
            }}
            .container {{ max-width: 800px; margin: 0 auto; text-align: left; }}
            h1 {{ color: #fff; border-bottom: 2px solid #444; padding-bottom: 5px; text-align: center; margin-bottom: 5px; }}
            .scan-range {{ color: #4db8ff; text-align: center; font-size: 1.3em; font-weight: bold; margin-bottom: 25px; text-shadow: 0 0 10px rgba(77, 184, 255, 0.3); }}
            /* TABS */
            .tab {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 20px; border-bottom: 1px solid #444; padding-bottom: 20px; }}
            .tab button {{ background-color: #333; border: 1px solid #555; border-radius: 30px; outline: none; cursor: pointer; padding: 10px 20px; transition: 0.3s; font-size: 15px; color: #ccc; font-weight: bold; flex: 1 1 auto; min-width: 100px; max-width: 250px; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
            .tab button:hover {{ background-color: #444; color: #fff; border-color: #777; }}
            .tab button.active {{ background-color: #4db8ff; color: #111; border-color: #4db8ff; box-shadow: 0 0 10px rgba(77, 184, 255, 0.4); }}
            .tabcontent {{ display: none; animation: fadeEffect 0.5s; min-height: 200px; }}
            @keyframes fadeEffect {{ from {{opacity: 0;}} to {{opacity: 1;}} }}
            /* STATS */
            .stats-container {{ display: flex; justify-content: space-between; margin-bottom: 30px; gap: 15px; flex-wrap: wrap; }}
            .stat-card {{ background: #2d2d2d; flex: 1; min-width: 120px; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.2); border-top: 4px solid #444; }}
            .stat-number {{ font-size: 2em; font-weight: bold; display: block; }}
            .stat-label {{ font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; color: #888; }}
            .stat-total {{ border-top-color: #4db8ff; }} .stat-total .stat-number {{ color: #4db8ff; }}
            .stat-upcoming {{ border-top-color: #9c27b0; }} .stat-upcoming .stat-number {{ color: #9c27b0; }}
            .stat-needed {{ border-top-color: #FF9800; }} .stat-needed .stat-number {{ color: #FF9800; }}
            .stat-ready {{ border-top-color: #4CAF50; }} .stat-ready .stat-number {{ color: #4CAF50; }}
            /* CARDS */
            .card {{ background: #333; padding: 12px 15px; margin-bottom: 12px; border-radius: 6px; border-left: 6px solid #4db8ff; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
            .card.done {{ border-left-color: #4CAF50; opacity: 0.8; }} .card.todo {{ border-left-color: #FF9800; }}
            .show-title {{ font-size: 1.3em; font-weight: bold; display: inline-block; color: #fff; text-decoration: none; margin-bottom: 2px; }}
            .show-title:hover {{ text-decoration: underline; color: #ccc; }}
            .show-link {{ font-size: 0.75em; color: #666; display: block; margin-bottom: 5px; font-family: monospace; }}
            .meta {{ font-size: 1.0em; color: #ccc; }} .date {{ color: #fff; font-weight: bold; }}
            .badge-premiere {{ background: #444; color: #fff; padding: 3px 6px; border-radius: 4px; font-size: 0.7em; float: right; text-transform: uppercase; letter-spacing: 1px; margin-left: 8px; }}
            .status-icon {{ float: right; font-weight: bold; font-size: 0.9em; margin-left: 10px; padding: 3px 8px; border-radius: 4px; }}
            .status-todo {{ background: rgba(255, 152, 0, 0.2); color: #FF9800; border: 1px solid #FF9800; }}
            .status-done {{ background: rgba(76, 175, 80, 0.2); color: #4CAF50; border: 1px solid #4CAF50; }}
        </style>
        <script>
        function openTab(evt, libName) {{
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {{ tabcontent[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
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
             html_content += f"<p style='text-align:center;'>No upcoming premieres in this folder.</p>"
        
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
    
    # Start message
    send_discord_start()

    all_results = {}
    
    # Global Discord Summary
    global_scanned = 0
    global_upcoming = 0
    global_needed = 0

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
            
            time.sleep(0.1)
            print_progress(i + 1, total, prefix='Progress:', suffix='Complete', length=40)
        
        # SEND FOLDER REPORT
        scanned_count = len(inventory)
        send_discord_library_report(lib_name, current_lib_shows, scanned_count)
        
        # Track globals
        upcoming = len(current_lib_shows)
        needed = sum(1 for s in current_lib_shows if not s['poster_exists'])
        
        global_scanned += scanned_count
        global_upcoming += upcoming
        global_needed += needed

        all_results[lib_name] = {
            'shows': current_lib_shows,
            'total_scanned': scanned_count
        }
    
    # SEND END MESSAGE
    send_discord_end(global_scanned, global_upcoming, global_needed)
    
    # HTML report
    generate_html_report(all_results)
    webbrowser.open('file://' + os.path.abspath(REPORT_FILE))
