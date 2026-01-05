import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import random
import html
import io
import re
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
from rapidfuzz import process, fuzz

# --- 1. KONFIGURATION ---
st.set_page_config(page_title="CouchPilot", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# --- 2. TÜRSTEHER (LOGIN SCHUTZ) ---
def check_password():
    if "APP_PASSWORD" not in st.secrets:
        st.warning("⚠️ ACHTUNG: 'APP_PASSWORD' fehlt in den Secrets!")
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 CouchPilot Zugang:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 CouchPilot Zugang:", type="password", on_change=password_entered, key="password")
        st.error("😕 Zugriff verweigert.")
        return False
    else:
        return True

if not check_password():
    st.stop() 

# --- 3. HAUPTPROGRAMM ---

if 'tv_infos' not in st.session_state: st.session_state['tv_infos'] = {}
if 'search_results' not in st.session_state: st.session_state['search_results'] = []
if 'local_match_data' not in st.session_state: st.session_state['local_match_data'] = None

GENRE_MAP = {
    28: "Action", 12: "Abenteuer", 16: "Animation", 35: "Komödie",
    80: "Krimi", 99: "Doku", 18: "Drama", 10751: "Familie",
    14: "Fantasy", 36: "Historie", 27: "Horror", 10402: "Musik",
    9648: "Mystery", 10749: "Romantik", 878: "Sci-Fi", 10770: "TV-Film",
    53: "Thriller", 10752: "Kriegsfilm", 37: "Western",
    10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap",
    10767: "Talk", 10768: "War & Politics"
}

try:
    TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
except (FileNotFoundError, KeyError):
    st.error("⚠️ Secrets fehlen!")
    st.stop()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

FILM_URL_DE = "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Filme_Rosi_2025_DE.xlsx"
FILM_URL_KAIRO = "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Filme_Rosi_2025_Kairo.xlsx"
SERIEN_URL = "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Serien_Rosi_2025.xlsx"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1kXU0mgitV_a9dUS1gJto5qX108H9-2HygxL-r3vQ_Hk/edit"

# --- HELFER FUNKTIONEN ---

def get_genres_string(ids):
    if not ids: return ""
    names = [GENRE_MAP.get(i, "") for i in ids]
    return ", ".join(filter(None, names))

def clean_html(raw_text):
    if not raw_text: return ""
    text = html.unescape(raw_text)
    text = re.sub(r'<[^>]+>', '', text) 
    return text.strip()

def fetch_tmdb(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200: return response.json()
    except: pass
    return {}

def is_fresh(date_str):
    if not date_str or len(str(date_str)) < 4: return False
    try:
        year = int(str(date_str)[:4])
        current_year = datetime.now().year
        return year >= (current_year - 1)
    except:
        return False

def get_tv_details(tmdb_id):
    url = f"{TMDB_BASE_URL}/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=de-DE"
    data = fetch_tmdb(url)
    if not data: return None, None, ""
    seasons = data.get('number_of_seasons', 0)
    episodes = data.get('number_of_episodes', 0)
    status_raw = data.get('status', '')
    status_map = {
        "Returning Series": "🟢 Läuft",
        "Ended": "🔴 Beendet",
        "Canceled": "🚫 Abgesetzt",
        "Miniseries": "⚪ Miniserie",
        "In Production": "⚙️ In Produktion",
        "Planned": "📅 Geplant",
        "Pilot": "🎬 Pilot"
    }
    status_de = status_map.get(status_raw, status_raw)
    return seasons, episodes, status_de

def get_feed_items(url, tag_prefix):
    items = []
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            tree = ET.fromstring(resp.content)
            for item in tree.findall('./channel/item'):
                title = item.find('title').text
                desc = clean_html(item.find('description').text or "")
                items.append({"title": title, "desc": desc, "tag": tag_prefix})
    except: pass
    return items

def find_local_fuzzy(tmdb_title, library):
    if not tmdb_title: return None
    if tmdb_title.lower() in library: return library[tmdb_title.lower()]
    def clean(s): return re.sub(r'[^a-zA-Z0-9]', '', s).lower()
    tmdb_clean = clean(tmdb_title)
    clean_keys_map = {clean(k): v for k, v in library.items()}
    if tmdb_clean in clean_keys_map: return clean_keys_map[tmdb_clean]
    choices = list(library.keys())
    match = process.extractOne(tmdb_title.lower(), choices, scorer=fuzz.WRatio, score_cutoff=85)
    if match: return library[match[0]]
    return None

@st.cache_data(ttl=3600)
def load_data_from_github():
    library = {}
    files = {FILM_URL_DE: "Film (DE)", FILM_URL_KAIRO: "Film (Kairo)", SERIEN_URL: "Serie"}
    headers = {}
    if GITHUB_TOKEN: headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    for url, cat in files.items():
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                with io.BytesIO(response.content) as f:
                    xls = pd.ExcelFile(f, engine='openpyxl')
                    for sheet_name in xls.sheet_names:
                        df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
                        col_t = next((c for c in df.columns if str(c).lower() in ["titel", "name", "filmtitel"]), None)
                        col_p = next((c for c in df.columns if str(c).lower() in ["ablageort", "ablage", "pfad", "path", "location"]), None)
                        col_a = next((c for c in df.columns if str(c).lower() in ["schauspieler", "darsteller", "cast"]), None)
                        col_d = next((c for c in df.columns if str(c).lower() in ["handlung", "inhalt", "plot"]), None)
                        col_g = next((c for c in df.columns if str(c).lower() in ["genre", "genres"]), None)

                        if col_t:
                            for _, row in df.iterrows():
                                t = str(row[col_t]).strip()
                                if len(t) > 1:
                                    path = sheet_name
                                    if col_p and pd.notna(row[col_p]) and len(str(row[col_p])) > 1:
                                        path = str(row[col_p]).strip()
                                    actors = str(row[col_a]) if col_a and pd.notna(row[col_a]) else ""
                                    plot = str(row[col_d]) if col_d and pd.notna(row[col_d]) else ""
                                    genre = str(row[col_g]) if col_g and pd.notna(row[col_g]) else ""

                                    library[t.lower()] = {
                                        "title": t, "path": path, "type": cat,
                                        "actors": actors, "plot": plot, "genre": genre
                                    }
        except: pass
    return library

# --- DATENBANK FUNKTIONEN ---

def get_db_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        # Lese jetzt 10 Spalten (inklusive my_rating)
        df = conn.read(spreadsheet=SHEET_URL, usecols=list(range(10)), ttl=0)
        cols = ["id", "title", "poster_path", "release_date", "vote_average", "overview", "status", "added_date", "source", "my_rating"]
        if df.empty: return pd.DataFrame(columns=cols)
        df['id'] = df['id'].astype(str)
        # Fehlende Spalten auffüllen
        for c in cols:
            if c not in df.columns: df[c] = ""
        # Rating Spalte numerisch machen
        df['my_rating'] = pd.to_numeric(df['my_rating'], errors='coerce').fillna(0).astype(int)
        return df
    except:
        return pd.DataFrame(columns=["id", "title", "poster_path", "release_date", "vote_average", "overview", "status", "added_date", "source", "my_rating"])

def update_db_status(movie, new_status, origin="Unbekannt"):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = get_db_data()
    movie_id = str(movie['id'])
    title = movie.get('title') or movie.get('name') or "Unbekannt"
    today_str = datetime.now().strftime("%d.%m.%Y")
    
    if movie_id in df['id'].values:
        if new_status == 'delete':
            df = df[df['id'] != movie_id]
            st.toast(f"🗑️ '{title}' entfernt.")
        else:
            df.loc[df['id'] == movie_id, 'status'] = new_status
            st.toast(f"Updated: '{title}' -> {new_status}")
    else:
        if new_status != 'delete':
            new_row = pd.DataFrame([{
                "id": movie_id,
                "title": title,
                "poster_path": movie.get('poster_path', ''),
                "release_date": str(movie.get('release_date', '') or movie.get('first_air_date', ''))[:10],
                "vote_average": movie.get('vote_average', 0),
                "overview": clean_html(movie.get('overview', '')),
                "status": new_status,
                "added_date": today_str,
                "source": origin,
                "my_rating": 0
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            st.toast(f"Neu: '{title}' ({origin})")

    try:
        conn.update(spreadsheet=SHEET_URL, data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Fehler beim Speichern: {e}")

def save_personal_rating(movie_id, rating):
    """Speichert NUR die persönliche Bewertung."""
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = get_db_data()
    
    if str(movie_id) in df['id'].values:
        df.loc[df['id'] == str(movie_id), 'my_rating'] = rating
        try:
            conn.update(spreadsheet=SHEET_URL, data=df)
            st.cache_data.clear()
            st.toast(f"Bewertung gespeichert: {rating}/10")
        except Exception as e:
            st.error(f"Fehler: {e}")

# --- UI START ---

st.title("🎬 CouchPilot Cloud")

if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

try:
    db_df = get_db_data()
    watchlist_items = db_df[db_df['status'] == 'watchlist'].to_dict('records')
    seen_items = db_df[db_df['status'] == 'seen'].to_dict('records')
except:
    watchlist_items = []
    seen_items = []

local_lib = load_data_from_github()
if local_lib: st.sidebar.success(f"{len(local_lib)} Titel (GitHub).")
else: st.sidebar.warning("Keine lokalen Daten.")

menu = st.sidebar.radio("Speisekarte", ["Suche & Inspiration", "TV- und Mediatheken", "Lokale Liste", f"Watchlist ({len(watchlist_items)})", f"Schon gesehen ({len(seen_items)})"])

st.sidebar.markdown("---")
st.sidebar.link_button("📊 Datenbank öffnen", SHEET_URL)

# --- TAB 1: SUCHE & INSPIRATION ---
if menu == "Suche & Inspiration":
    st.header("Was schauen wir heute?")
    
    c_search, c_btn = st.columns([5, 1])
    search_query = c_search.text_input("Titel oder Schauspieler...", placeholder="z.B. Navy CIS, The Rookie...", label_visibility="collapsed")
    
    st.write("Oder Inspiration:")
    cols = st.columns(5)
    genres = [("😂 Komödie", 35), ("😱 Thriller", 53), ("❤️ Romantik", 10749), ("🌍 Doku", 99), ("🏛️ Klassiker", "classic")]
    
    selected_gid = None
    trigger_search = False

    if c_btn.button("🔍", use_container_width=True): trigger_search = True

    for idx, (name, gid) in enumerate(genres):
        if cols[idx].button(name, use_container_width=True): 
            selected_gid = gid
            trigger_search = True
    
    if trigger_search:
        st.session_state['local_match_data'] = None
        if search_query:
            found = find_local_fuzzy(search_query, local_lib)
            if found:
                st.session_state['local_match_data'] = found
        
        final_results = []
        seen_ids = set()

        if search_query and not selected_gid:
            data = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=de-DE")
            
            if data.get('results'):
                top_hits = data['results'][:5]
                for hit in top_hits:
                    if str(hit['id']) not in seen_ids:
                        final_results.append(hit)
                        seen_ids.add(str(hit['id']))
                
                best_match = data['results'][0]
                if best_match.get('media_type') != 'person':
                    m_id = best_match['id']
                    m_type = "tv" if best_match.get('name') else "movie"
                    rec_url = f"{TMDB_BASE_URL}/{m_type}/{m_id}/recommendations?api_key={TMDB_API_KEY}&language=de-DE"
                    rec_data = fetch_tmdb(rec_url)
                    if rec_data.get('results'):
                        for rec in rec_data.get('results')[:20]:
                            if str(rec['id']) not in seen_ids:
                                final_results.append(rec)
                                seen_ids.add(str(rec['id']))
            
            st.session_state['search_results'] = final_results

        elif selected_gid:
            page = random.randint(1, 10)
            if selected_gid == "classic":
                res = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&sort_by=vote_average.desc&vote_count.gte=1000&primary_release_date.lte=2000-01-01&page={page}&language=de-DE")
            else:
                base = "movie" if selected_gid != "rnd_tv" else "tv"
                if selected_gid in ["rnd_movie", "rnd_tv"]:
                    res = fetch_tmdb(f"{TMDB_BASE_URL}/{base}/popular?api_key={TMDB_API_KEY}&language=de-DE&page={page}")
                else:
                    res = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres={selected_gid}&sort_by=vote_average.desc&vote_count.gte=200&page={random.randint(1,5)}&language=de-DE")
            
            if res.get('results'):
                items = res.get('results')
                random.shuffle(items)
                st.session_state['search_results'] = items

    # 1. LOKALE TREFFER
    if st.session_state.get('local_match_data'):
        lm = st.session_state['local_match_data']
        st.markdown("### 📂 In deiner lokalen Sammlung gefunden:")
        st.success(f"**{lm['title']}** liegt auf: `{lm['path']}` ({lm['type']})")
        with st.expander("Details anzeigen"):
            st.write(f"**Inhalt:** {lm.get('plot', 'n/a')}")
            st.caption(f"Genre: {lm.get('genre')} | Darsteller: {lm.get('actors')}")
        st.markdown("---")

    # 2. ERGEBNISSE
    if st.session_state['search_results']:
        st.header("Das könnte dir gefallen:")
        st.caption("Suchergebnisse & Empfehlungen")
        
        for idx, m in enumerate(st.session_state['search_results']):
            title = m.get('title') or m.get('name')
            r_date = m.get('release_date') or m.get('first_air_date')
            year = str(r_date)[:4] if r_date else ""
            new_badge = " ✨ NEU" if is_fresh(r_date) else ""
            
            rating = round(m.get('vote_average', 0), 1)
            overview = m.get('overview', 'Keine Inhaltsangabe verfügbar.')
            g_text = get_genres_string(m.get('genre_ids', []))
            
            media_type = m.get('media_type')
            if not media_type: media_type = "tv" if m.get('name') else "movie"
            m_id = str(m['id'])
            
            extra_info = ""
            if media_type == 'tv':
                s_num, e_num, s_status = get_tv_details(m_id)
                if s_num:
                    extra_info = f" | 📺 {s_num} Staffeln ({e_num} Eps.) | {s_status}"
            
            meta_line = f"{g_text}{extra_info}" if g_text else extra_info

            is_also_local = find_local_fuzzy(title, local_lib) is not None
            color_prefix = "🟢 " if is_also_local else ""

            with st.expander(f"{color_prefix}{title} ({year}){new_badge} ⭐ {rating} • {meta_line}"):
                c1, c2 = st.columns([1, 3])
                if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
                else: c1.text("Kein Bild")

                with c2:
                    st.write(overview)
                    st.markdown("---")
                    
                    in_wl = any(str(x['id']) == m_id for x in watchlist_items)
                    in_seen = any(str(x['id']) == m_id for x in seen_items)
                    
                    b1, b2, b3 = st.columns([1, 1, 1.5])
                    
                    if b1.button("🎫 Merken", key=f"s_wl_{m_id}_{idx}", disabled=in_wl):
                        update_db_status(m, 'watchlist', origin="Suche/Empfehlung")
                        st.rerun()
                    if b2.button("✅ Gesehen", key=f"s_sn_{m_id}_{idx}", disabled=in_seen):
                        update_db_status(m, 'seen', origin="Suche/Empfehlung")
                        st.rerun()
                    if b3.button("🔗 Ähnliche laden", key=f"sim_{m_id}_{idx}"):
                        with st.spinner(f"Suche Alternativen zu {title}..."):
                            rec_url = f"{TMDB_BASE_URL}/{media_type}/{m_id}/recommendations?api_key={TMDB_API_KEY}&language=de-DE"
                            rec_data = fetch_tmdb(rec_url)
                            if rec_data.get('results'):
                                st.session_state['search_results'] = rec_data.get('results')[:15]
                                st.rerun()

                    if not is_also_local:
                         st.link_button("🌐 Wer streamt es?", f"https://www.google.com/search?q={title}+stream+deutsch")

# --- TAB 2: TV & MEDIATHEKEN ---
elif menu == "TV- und Mediatheken":
    st.header("📺 Live TV & Tipps")
    tab1, tab2 = st.tabs(["TV Programm", "Mediathek"])
    
    with tab1:
        c1, c2 = st.columns(2)
        if c1.button("Heute 20:15 ✨", use_container_width=True):
            st.session_state['tv_data'] = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/heute2015.xml", "TV")
            st.rerun()
        if c2.button("Morgen Highlights (20:15) 🔮", use_container_width=True):
            items = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/morgen2015.xml", "TV")
            if not items:
                items = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml", "TV Spät")
            st.session_state['tv_data'] = items
            st.rerun()
        
        if 'tv_data' in st.session_state:
            for idx, item in enumerate(st.session_state['tv_data']):
                item_id = str(hash(item['title']))
                info_text = ""
                if item_id in st.session_state['tv_infos']:
                    info = st.session_state['tv_infos'][item_id]
                    if info: 
                        g_text = get_genres_string(info.get('genre_ids', []))
                        info_text = f" ⭐ {round(info.get('vote_average',0), 1)} | {g_text}"

                with st.expander(f"⏰ {item['title']} {info_text}"):
                    st.markdown(item['desc'])
                    
                    if item_id in st.session_state['tv_infos']:
                        info = st.session_state['tv_infos'][item_id]
                        if info:
                            st.image(f"{IMAGE_BASE_URL}{info.get('poster_path')}", width=150)
                            st.caption(f"{info.get('overview')}")
                            st.markdown("---")
                            m_id = str(info['id'])
                            in_wl = any(str(x['id']) == m_id for x in watchlist_items)
                            in_seen = any(str(x['id']) == m_id for x in seen_items)
                            bt1, bt2 = st.columns(2)
                            if bt1.button("🎫 Merken", key=f"tv_wl_{m_id}_{idx}", disabled=in_wl):
                                update_db_status(info, 'watchlist', origin="TV Programm")
                                st.rerun()
                            if bt2.button("✅ Gesehen", key=f"tv_sn_{m_id}_{idx}", disabled=in_seen):
                                update_db_status(info, 'seen', origin="TV Programm")
                                st.rerun()
                    else:
                        if st.button("🔍 Infos laden", key=f"tv_{item_id}_{idx}"):
                            clean = item['title'].split('|')[-1].strip()
                            data = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={clean}&language=de-DE")
                            if data.get('results'):
                                st.session_state['tv_infos'][item_id] = data['results'][0]
                                st.rerun()
                            else: st.warning("Nichts gefunden.")

    with tab2:
        if st.button("Mediathek Tipps laden"):
            st.session_state['mediathek_data'] = get_feed_items("https://www.filmdienst.de/rss/mediatheken", "Mediathek")
            st.rerun()
        if 'mediathek_data' in st.session_state:
            for idx, item in enumerate(st.session_state['mediathek_data']):
                sender = "Mediathek"
                if "arte" in item['desc'].lower(): sender = "ARTE"
                elif "zdf" in item['desc'].lower(): sender = "ZDF"
                elif "ard" in item['desc'].lower(): sender = "ARD"
                elif "3sat" in item['desc'].lower(): sender = "3sat"
                
                item_id = str(hash(item['title']+"med"))
                info_text = ""
                if item_id in st.session_state['tv_infos']:
                    info = st.session_state['tv_infos'][item_id]
                    if info: 
                        g_text = get_genres_string(info.get('genre_ids', []))
                        info_text = f" ⭐ {round(info.get('vote_average',0), 1)} | {g_text}"

                with st.expander(f"▶ {sender}: {item['title']} {info_text}"):
                    st.markdown(item['desc'])
                    
                    if item_id not in st.session_state['tv_infos']:
                        if st.button("🔍 Cover & Genre laden", key=f"med_{item_id}_{idx}"):
                             clean = item['title'].replace("Serie:", "").replace("Film:", "").strip()
                             data = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={clean}&language=de-DE")
                             if data.get('results'):
                                 st.session_state['tv_infos'][item_id] = data['results'][0]
                                 st.rerun()
                    elif st.session_state['tv_infos'][item_id]:
                        info = st.session_state['tv_infos'][item_id]
                        st.image(f"{IMAGE_BASE_URL}{info.get('poster_path')}", width=150)
                        st.markdown("---")
                        m_id = str(info['id'])
                        in_wl = any(str(x['id']) == m_id for x in watchlist_items)
                        in_seen = any(str(x['id']) == m_id for x in seen_items)
                        bm1, bm2 = st.columns(2)
                        if bm1.button("🎫 Merken", key=f"med_wl_{m_id}_{idx}", disabled=in_wl):
                            update_db_status(info, 'watchlist', origin=f"Mediathek ({sender})")
                            st.rerun()
                        if bm2.button("✅ Gesehen", key=f"med_sn_{m_id}_{idx}", disabled=in_seen):
                            update_db_status(info, 'seen', origin=f"Mediathek ({sender})")
                            st.rerun()

# --- TAB 3: LOKALE LISTE ---
elif menu == "Lokale Liste":
    st.header("📂 Deine GitHub Sammlung")
    if local_lib:
        c_loc_search, c_loc_btn = st.columns([5,1])
        term = c_loc_search.text_input("Filtern:", placeholder="Titel, Schauspieler...", label_visibility="collapsed")
        c_loc_btn.button("🔍", use_container_width=True, key="btn_local")

        df = pd.DataFrame(local_lib.values())
        cols_to_show = ['title', 'actors', 'genre', 'plot', 'path']
        cols_final = [c for c in cols_to_show if c in df.columns]
        df_show = df[cols_final].copy()
        
        if term:
            df_show = df_show[df_show.apply(lambda x: x.astype(str).str.contains(term, case=False).any(), axis=1)]
        st.dataframe(df_show, use_container_width=True, hide_index=True)

# --- TAB 4 & 5: WATCHLIST / GESEHEN ---
elif "Watchlist" in menu or "Schon gesehen" in menu:
    is_seen = "Schon gesehen" in menu
    target_list = seen_items if is_seen else watchlist_items
    st.header(f"{'✅ Gesehen' if is_seen else '🎫 Deine Watchlist'}")
    
    sort_option = st.selectbox("Sortieren nach:", ["🕒 Hinzugefügt (Neu)", "🅰️ Titel (A-Z)", "⭐ Bewertung (Beste)", "📅 Release (Neu)", "👤 Meine Bewertung"])
    
    if target_list:
        if "🅰️" in sort_option:
            target_list.sort(key=lambda x: str(x.get('title', '')).lower())
        elif "⭐" in sort_option:
            target_list.sort(key=lambda x: float(x.get('vote_average', 0) or 0), reverse=True)
        elif "📅" in sort_option:
            target_list.sort(key=lambda x: str(x.get('release_date', '')), reverse=True)
        elif "👤" in sort_option:
            # Sortierung nach eigener Bewertung
            target_list.sort(key=lambda x: int(x.get('my_rating', 0) or 0), reverse=True)
        else: 
            target_list.reverse()

    if not target_list: st.info("Liste ist leer.")
    
    for idx, m in enumerate(target_list):
        title = m.get('title')
        r_date = m.get('release_date', '')
        year = str(r_date)[:4] if r_date else ""
        new_badge = " ✨ NEU" if is_fresh(r_date) else ""
        
        rating = m.get('vote_average')
        date_added = m.get('added_date', '')
        source = m.get('source', '')
        
        # --- EIGENE BEWERTUNG ---
        my_rate = m.get('my_rating', 0)
        user_rating_display = f" | 👤 {my_rate}/10" if my_rate > 0 else ""

        meta_info = ""
        if date_added: meta_info += f" | 📅 {date_added}"
        if source: meta_info += f" | Quelle: {source}"
        
        with st.expander(f"{title} ({year}){new_badge} ⭐ {rating}{user_rating_display}{meta_info}"):
            c1, c2 = st.columns([1, 3])
            if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
            with c2:
                st.write(m.get('overview'))
                
                # --- BEWERTUNGSSLIDER NUR BEI GESEHEN ---
                if is_seen:
                    st.markdown("---")
                    st.caption("Deine Bewertung:")
                    c_rate, c_save = st.columns([3, 1])
                    # Slider Value auf aktuellen Wert setzen (oder 5 als Standard)
                    current_val = int(my_rate) if my_rate > 0 else 5
                    new_val = c_rate.slider("Sterne", 1, 10, current_val, key=f"sl_{m['id']}_{idx}", label_visibility="collapsed")
                    
                    if c_save.button("💾 Speichern", key=f"sv_{m['id']}_{idx}"):
                        save_personal_rating(m['id'], new_val)
                        st.rerun()

                st.markdown("---")
                b1, b2 = st.columns(2)
                list_prefix = "seen" if is_seen else "wl"
                m_id = str(m['id'])
                
                if b1.button("🗑️ Löschen", key=f"del_{list_prefix}_{m_id}_{idx}"):
                    update_db_status(m, 'delete')
                    st.rerun()
                
                if is_seen:
                    if b2.button("⬅️ Zur Watchlist", key=f"mov_to_wl_{m_id}_{idx}"):
                         update_db_status(m, 'watchlist')
                         st.rerun()
                else:
                    if b2.button("✅ Gesehen", key=f"mov_to_seen_{m_id}_{idx}"):
                        update_db_status(m, 'seen')
                        st.rerun()
