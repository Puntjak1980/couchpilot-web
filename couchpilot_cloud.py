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
# NEU: Für intelligenten Textvergleich (Navy CIS vs NCIS)
from rapidfuzz import process, fuzz

# --- 1. KONFIGURATION ---
st.set_page_config(page_title="CouchPilot", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# --- 2. TÜRSTEHER (LOGIN SCHUTZ) ---
def check_password():
    """Prüft das Passwort, bevor die App lädt."""
    if "APP_PASSWORD" not in st.secrets:
        st.warning("⚠️ ACHTUNG: 'APP_PASSWORD' fehlt in den Secrets! Die App ist ungeschützt.")
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

# --- SESSION STATE ---
if 'tv_infos' not in st.session_state: st.session_state['tv_infos'] = {}
if 'search_results' not in st.session_state: st.session_state['search_results'] = []

# --- GENRE MAPPING ---
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

# --- SECRETS CHECK ---
try:
    TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
except (FileNotFoundError, KeyError):
    st.error("⚠️ Secrets fehlen! Bitte TMDB_API_KEY hinterlegen.")
    st.stop()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# --- URLS ---
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

def get_feed_items(url, tag_prefix):
    items = []
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            tree = ET.fromstring(resp.content)
            for item in tree.findall('./channel/item'):
                title = item.find('title').text
                raw_desc = item.find('description').text or ""
                desc = clean_html(raw_desc)
                items.append({"title": title, "desc": desc, "tag": tag_prefix})
    except: pass
    return items

# --- NEUE FUNKTION: INTELLIGENTE SUCHE (FUZZY) ---
def find_local_fuzzy(tmdb_title, library):
    """Sucht intelligent nach einem Titel in der lokalen Bibliothek."""
    if not tmdb_title: return None
    
    # 1. Exakter Treffer (schnell)
    if tmdb_title.lower() in library:
        return library[tmdb_title.lower()]
    
    # 2. Bereinigter Vergleich (entfernt Sonderzeichen für "NCIS: Sydney" == "NCIS Sydney")
    def clean(s):
        return re.sub(r'[^a-zA-Z0-9]', '', s).lower()
    
    tmdb_clean = clean(tmdb_title)
    clean_keys_map = {clean(k): v for k, v in library.items()}
    
    if tmdb_clean in clean_keys_map:
        return clean_keys_map[tmdb_clean]

    # 3. Fuzzy Match (Unscharf für "Navy CIS" vs "NCIS")
    choices = list(library.keys())
    # score_cutoff=85 bedeutet: Hohe Ähnlichkeit erforderlich
    match = process.extractOne(tmdb_title.lower(), choices, scorer=fuzz.WRatio, score_cutoff=85)
    
    if match:
        found_key = match[0]
        return library[found_key]
        
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
        df = conn.read(spreadsheet=SHEET_URL, usecols=list(range(9)), ttl=0)
        cols = ["id", "title", "poster_path", "release_date", "vote_average", "overview", "status", "added_date", "source"]
        if df.empty: return pd.DataFrame(columns=cols)
        df['id'] = df['id'].astype(str)
        for c in cols:
            if c not in df.columns: df[c] = ""
        return df
    except:
        return pd.DataFrame(columns=["id", "title", "poster_path", "release_date", "vote_average", "overview", "status", "added_date", "source"])

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
                "source": origin
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            st.toast(f"Neu: '{title}' ({origin})")

    try:
        conn.update(spreadsheet=SHEET_URL, data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Fehler beim Speichern: {e}")

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
    search_query = c_search.text_input("Titel oder Schauspieler...", placeholder="z.B. Brad Pitt oder Matrix", label_visibility="collapsed")
    
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
    
    c_rnd1, c_rnd2 = st.columns(2)
    if c_rnd1.button("🎲 Film Zufall", use_container_width=True): 
        selected_gid = "rnd_movie"
        trigger_search = True
    if c_rnd2.button("🎲 Serien Zufall", use_container_width=True): 
        selected_gid = "rnd_tv"
        trigger_search = True

    if trigger_search:
        results = []
        if search_query and not selected_gid:
            data = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=de-DE")
            if data.get('results'):
                top = data['results'][0]
                if top.get('media_type') == 'person':
                    st.toast(f"Schauspieler: {top['name']}")
                    res = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_cast={top['id']}&sort_by=popularity.desc&language=de-DE")
                    results = res.get('results', [])
                else:
                    st.toast(f"Suche nach: {top.get('title')}")
                    results = data['results'][:5] 
                    recs = fetch_tmdb(f"{TMDB_BASE_URL}/movie/{top['id']}/recommendations?api_key={TMDB_API_KEY}&language=de-DE")
                    if recs.get('results'):
                        results.extend(recs.get('results')[:5])
            else: st.warning("Nichts gefunden.")
        
        elif selected_gid:
            page = random.randint(1, 10)
            if selected_gid == "rnd_movie":
                results = fetch_tmdb(f"{TMDB_BASE_URL}/movie/popular?api_key={TMDB_API_KEY}&language=de-DE&page={page}").get('results', [])
            elif selected_gid == "rnd_tv":
                results = fetch_tmdb(f"{TMDB_BASE_URL}/tv/popular?api_key={TMDB_API_KEY}&language=de-DE&page={page}").get('results', [])
            elif selected_gid == "classic":
                results = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&sort_by=vote_average.desc&vote_count.gte=1000&primary_release_date.lte=2000-01-01&page={page}&language=de-DE").get('results', [])
            else:
                results = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres={selected_gid}&sort_by=vote_average.desc&vote_count.gte=200&page={random.randint(1,5)}&language=de-DE").get('results', [])
            
            if results: random.shuffle(results)
        
        st.session_state['search_results'] = results

    if st.session_state['search_results']:
        st.write(f"Treffer: {len(st.session_state['search_results'])}")
        
        for m in st.session_state['search_results']:
            title = m.get('title') or m.get('name')
            original_title = m.get('original_title') or m.get('original_name')
            year = str(m.get('release_date', m.get('first_air_date', '')))[0:4]
            rating = round(m.get('vote_average', 0), 1)
            g_text = get_genres_string(m.get('genre_ids', []))
            if g_text: g_text = f" • {g_text}"
            
            # --- INTELLIGENTE SUCHE ---
            found_local = find_local_fuzzy(title, local_lib)
            if not found_local and original_title:
                found_local = find_local_fuzzy(original_title, local_lib)
            
            # QUELLE BESTIMMEN
            source_label = "💾 Lokal" if found_local else "🔍 Suche"
            color_prefix = "🟢 " if found_local else ""

            with st.expander(f"{color_prefix}{title} ({year}) ⭐ {rating} {g_text}"):
                if found_local:
                    st.success(f"✅ **IN DEINER SAMMLUNG!** Ort: {found_local['path']} ({found_local['type']})")
                    if found_local['title'].lower() != title.lower():
                        st.caption(f"Gefunden als: '{found_local['title']}'")
                
                c1, c2 = st.columns([1, 3])
                if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
                with c2:
                    st.write(m.get('overview'))
                    st.markdown("---")
                    
                    m_id = str(m['id'])
                    media_type = "movie" if m.get('title') else "tv"
                    
                    in_wl = any(str(x['id']) == m_id for x in watchlist_items)
                    in_seen = any(str(x['id']) == m_id for x in seen_items)
                    
                    b1, b2, b3 = st.columns([1, 1, 1.5])
                    if b1.button("🎫 Merken", key=f"s_wl_{m_id}", disabled=in_wl):
                        update_db_status(m, 'watchlist', origin=source_label)
                        st.rerun()
                    if b2.button("✅ Gesehen", key=f"s_sn_{m_id}", disabled=in_seen):
                        update_db_status(m, 'seen', origin=source_label)
                        st.rerun()
                    
                    # --- ÄHNLICHE TITEL BUTTON ---
                    if b3.button("🔗 Ähnliche anzeigen", key=f"sim_{m_id}"):
                        with st.spinner("Suche ähnliche Titel..."):
                            url = f"{TMDB_BASE_URL}/{media_type}/{m_id}/recommendations?api_key={TMDB_API_KEY}&language=de-DE"
                            recs = fetch_tmdb(url)
                            if recs.get('results'):
                                st.session_state['search_results'] = recs.get('results')[:10]
                                st.toast(f"Empfehlungen für '{title}' geladen!")
                                st.rerun()
                            else:
                                st.warning("Keine ähnlichen Titel gefunden.")

                    if not found_local:
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
                st.warning("⚠️ Morgen-Vorschau n/a. Zeige Spätprogramm von heute!")
                items = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml", "TV Spät")
            st.session_state['tv_data'] = items
            st.rerun()
        
        if 'tv_data' in st.session_state:
            for item in st.session_state['tv_data']:
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
                            if bt1.button("🎫 Merken", key=f"tv_wl_{m_id}", disabled=in_wl):
                                update_db_status(info, 'watchlist', origin="📺 TV Programm")
                                st.rerun()
                            if bt2.button("✅ Gesehen", key=f"tv_sn_{m_id}", disabled=in_seen):
                                update_db_status(info, 'seen', origin="📺 TV Programm")
                                st.rerun()
                    else:
                        if st.button("🔍 Infos laden", key=f"tv_{item_id}"):
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
            for item in st.session_state['mediathek_data']:
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
                        if st.button("🔍 Cover & Genre laden", key=f"med_{item_id}"):
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
                        if bm1.button("🎫 Merken", key=f"med_wl_{m_id}", disabled=in_wl):
                            update_db_status(info, 'watchlist', origin=f"▶️ Mediathek ({sender})")
                            st.rerun()
                        if bm2.button("✅ Gesehen", key=f"med_sn_{m_id}", disabled=in_seen):
                            update_db_status(info, 'seen', origin=f"▶️ Mediathek ({sender})")
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
    
    sort_option = st.selectbox("Sortieren nach:", ["🕒 Hinzugefügt (Neu)", "🅰️ Titel (A-Z)", "⭐ Bewertung (Beste)", "📅 Release (Neu)"])
    
    if target_list:
        if "🅰️" in sort_option:
            target_list.sort(key=lambda x: x['title'].lower())
        elif "⭐" in sort_option:
            target_list.sort(key=lambda x: float(x.get('vote_average', 0)), reverse=True)
        elif "📅" in sort_option:
            target_list.sort(key=lambda x: x.get('release_date', ''), reverse=True)
        else: 
            target_list.reverse()

    if not target_list: st.info("Liste ist leer.")
    
    for m in target_list:
        title = m.get('title')
        year = str(m.get('release_date', ''))[:4]
        rating = m.get('vote_average')
        date_added = m.get('added_date', '')
        source = m.get('source', '')
        
        meta_info = ""
        if date_added: meta_info += f" | 📅 {date_added}"
        if source: meta_info += f" | Quelle: {source}"
        
        with st.expander(f"{title} ({year}) ⭐ {rating}{meta_info}"):
            c1, c2 = st.columns([1, 3])
            if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
            with c2:
                st.write(m.get('overview'))
                st.markdown("---")
                b1, b2 = st.columns(2)
                list_prefix = "seen" if is_seen else "wl"
                m_id = str(m['id'])
                
                if b1.button("🗑️ Löschen", key=f"del_{list_prefix}_{m_id}"):
                    update_db_status(m, 'delete')
                    st.rerun()
                
                if is_seen:
                    if b2.button("⬅️ Zur Watchlist", key=f"mov_to_wl_{m_id}"):
                         update_db_status(m, 'watchlist')
                         st.rerun()
                else:
                    if b2.button("✅ Gesehen", key=f"mov_to_seen_{m_id}"):
                        update_db_status(m, 'seen')
                        st.rerun()
