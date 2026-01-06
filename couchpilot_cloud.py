import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import random
import html
import io
import re
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta
from rapidfuzz import process, fuzz
import calendar

# --- 1. KONFIGURATION ---
st.set_page_config(page_title="CouchPilot", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# --- 2. TÜRSTEHER (LOGIN SCHUTZ MIT URL-SUPPORT) ---
def check_password():
    """Prüft das Passwort via Eingabe oder URL-Parameter."""
    if "APP_PASSWORD" not in st.secrets:
        st.warning("⚠️ ACHTUNG: 'APP_PASSWORD' fehlt in den Secrets!")
        return True

    # 1. Prüfen, ob Passwort in der URL steht (?pw=...)
    # Wir holen den Parameter 'pw' aus der URL
    query_params = st.query_params
    url_password = query_params.get("pw", None)

    if url_password == st.secrets["APP_PASSWORD"]:
        st.session_state["password_correct"] = True
    
    # 2. Prüfen, ob User bereits eingeloggt ist
    if st.session_state.get("password_correct", False):
        return True

    # 3. Manuelle Eingabe (Falls URL leer oder falsch)
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    st.text_input("🔒 CouchPilot Zugang:", type="password", on_change=password_entered, key="password")
    
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Zugriff verweigert.")
        
    return False

if not check_password():
    st.stop()

# --- 3. SESSION STATE ---
if 'tv_infos' not in st.session_state: st.session_state['tv_infos'] = {}
if 'search_results' not in st.session_state: st.session_state['search_results'] = []
if 'explore_results' not in st.session_state: st.session_state['explore_results'] = []
if 'search_query' not in st.session_state: st.session_state['search_query'] = ""
if 'tv_data' not in st.session_state: st.session_state['tv_data'] = []
if 'mediathek_data' not in st.session_state: st.session_state['mediathek_data'] = []

# --- KONSTANTEN & API ---
GENRE_MAP = {
    28: "Action", 12: "Abenteuer", 16: "Animation", 35: "Komödie", 80: "Krimi", 99: "Doku", 18: "Drama", 
    10751: "Familie", 14: "Fantasy", 36: "Historie", 27: "Horror", 10402: "Musik", 9648: "Mystery", 
    10749: "Romantik", 878: "Sci-Fi", 10770: "TV-Film", 53: "Thriller", 10752: "Kriegsfilm", 37: "Western",
    10759: "Action & Adventure", 10762: "Kids", 10765: "Sci-Fi & Fantasy"
}

TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1kXU0mgitV_a9dUS1gJto5qX108H9-2HygxL-r3vQ_Hk/edit"

# --- HELFER FUNKTIONEN ---
def get_genres_string(ids):
    if not ids: return ""
    return ", ".join(filter(None, [GENRE_MAP.get(i, "") for i in ids]))

def clean_html(raw_text):
    if not raw_text: return ""
    return re.sub(r'<[^>]+>', '', html.unescape(raw_text)).strip()

def fetch_tmdb(url):
    try:
        response = requests.get(url, timeout=5)
        return response.json() if response.status_code == 200 else {}
    except: return {}

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

def find_local_fuzzy(tmdb_title, library):
    if not tmdb_title or not library: return None
    t_clean = tmdb_title.lower()
    if t_clean in library: return library[t_clean]
    choices = list(library.keys())
    match = process.extractOne(t_clean, choices, scorer=fuzz.WRatio, score_cutoff=85)
    return library[match[0]] if match else None

@st.cache_data(ttl=3600)
def load_data_from_github():
    library = {}
    urls = [
        "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Filme_Rosi_2025_DE.xlsx",
        "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Filme_Rosi_2025_Kairo.xlsx",
        "https://raw.githubusercontent.com/Puntjak1980/meine-filmdatenbank/main/Serien_Rosi_2025.xlsx"
    ]
    headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                with io.BytesIO(response.content) as f:
                    xls = pd.ExcelFile(f, engine='openpyxl')
                    for sheet in xls.sheet_names:
                        df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
                        col_t = next((c for c in df.columns if str(c).lower() in ["titel", "name", "filmtitel"]), None)
                        col_g = next((c for c in df.columns if str(c).lower() in ["genre", "genres"]), None)
                        col_a = next((c for c in df.columns if str(c).lower() in ["schauspieler", "darsteller", "cast"]), None)
                        col_p = next((c for c in df.columns if str(c).lower() in ["handlung", "inhalt", "plot", "beschreibung"]), None)
                        
                        if col_t:
                            for _, row in df.iterrows():
                                t = str(row[col_t]).strip()
                                if len(t) > 1:
                                    cat = "Serie" if "Serie" in url else "Film"
                                    genre = str(row[col_g]) if col_g and pd.notna(row[col_g]) else ""
                                    actors = str(row[col_a]) if col_a and pd.notna(row[col_a]) else ""
                                    plot = str(row[col_p]) if col_p and pd.notna(row[col_p]) else ""
                                    library[t.lower()] = {
                                        "title": t, "path": sheet, "type": cat,
                                        "genre": genre, "actors": actors, "plot": plot
                                    }
        except: pass
    return library

def get_db_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df = conn.read(spreadsheet=SHEET_URL, ttl=0)
        if df.empty: return pd.DataFrame(columns=["id", "title", "status", "user_rating", "added_date", "source"])
        if "user_rating" not in df.columns: df["user_rating"] = 0.0
        if "added_date" not in df.columns: df["added_date"] = ""
        if "source" not in df.columns: df["source"] = ""
        df['id'] = df['id'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except: return pd.DataFrame()

def update_db_status(movie, new_status, origin="Unbekannt", user_rating=None):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = get_db_data()
    m_id = str(movie['id']).replace('.0', '')
    title = movie.get('title') or movie.get('name') or "Unbekannt"
    today_str = datetime.now().strftime("%d.%m.%Y")

    if m_id in df['id'].values:
        if new_status == 'delete':
            df = df[df['id'] != m_id]
        else:
            df.loc[df['id'] == m_id, 'status'] = new_status
            if user_rating is not None:
                df.loc[df['id'] == m_id, 'user_rating'] = float(user_rating)
            if 'added_date' in df.columns and pd.isna(df.loc[df['id'] == m_id, 'added_date']).any():
                 df.loc[df['id'] == m_id, 'added_date'] = today_str
            if 'source' in df.columns and pd.isna(df.loc[df['id'] == m_id, 'source']).any():
                 df.loc[df['id'] == m_id, 'source'] = origin
    else:
        if new_status != 'delete':
            new_row = pd.DataFrame([{
                "id": m_id, "title": title, "poster_path": movie.get('poster_path', ''),
                "vote_average": movie.get('vote_average', 0), "status": new_status,
                "added_date": today_str, "source": origin,
                "user_rating": user_rating if user_rating else 0.0
            }])
            df = pd.concat([df, new_row], ignore_index=True)
    conn.update(spreadsheet=SHEET_URL, data=df)
    st.cache_data.clear()

# --- 4. UI SEITENLEISTE ---
st.sidebar.title("🛠️ Admin")
if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.link_button("📊 Datenbank öffnen", SHEET_URL)

local_lib = load_data_from_github()
db_df = get_db_data()
watchlist = db_df[db_df['status'] == 'watchlist'].to_dict('records') if not db_df.empty else []
seen_list = db_df[db_df['status'] == 'seen'].to_dict('records') if not db_df.empty else []

menu = st.sidebar.radio("Speisekarte", [
    "Suche & Inspiration", "Entdecker-Modus ✨", "TV- und Mediatheken", 
    "Lokale Liste", f"Watchlist ({len(watchlist)})", f"Schon gesehen ({len(seen_list)})"
])

# --- TAB: SUCHE ---
if menu == "Suche & Inspiration":
    st.header("Was schauen wir heute?")
    c_search, c_btn = st.columns([5, 1])
    search_input = c_search.text_input("Titel oder Schauspieler...", value=st.session_state['search_query'])
    
    if c_btn.button("🔍") or (search_input and search_input != st.session_state['search_query']):
        st.session_state['search_query'] = search_input
        data = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={search_input}&language=de-DE")
        results = data.get('results', [])
        if results and results[0].get('media_type') == 'person':
            person_id = results[0]['id']
            st.toast(f"Lade Filme von: {results[0]['name']}")
            res_movies = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_cast={person_id}&sort_by=popularity.desc&language=de-DE")
            st.session_state['search_results'] = res_movies.get('results', [])[:15]
        else:
            st.session_state['search_results'] = results[:15]

    for m in st.session_state['search_results']:
        title = m.get('title') or m.get('name')
        if not title: continue
        m_id = str(m['id']).replace('.0', '')
        found = find_local_fuzzy(title, local_lib)
        
        # DATEN FÜR HEADER
        rating = round(m.get('vote_average', 0), 1)
        year = str(m.get('release_date', m.get('first_air_date', '')))[:4]
        genre_str = get_genres_string(m.get('genre_ids', []))
        
        # HEADER STRING
        header = f"{'🟢 ' if found else ''}{title} (⭐ {rating} | 📅 {year} | {genre_str})"
        
        with st.expander(header):
            if found: st.success(f"✅ In deiner Sammlung: {found['path']}")
            c1, c2 = st.columns([1, 3])
            if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
            with c2:
                st.write(m.get('overview'))
                st.write("**Schauspieler:**")
                credits = fetch_tmdb(f"{TMDB_BASE_URL}/{'movie' if 'title' in m else 'tv'}/{m_id}/credits?api_key={TMDB_API_KEY}")
                if credits.get('cast'):
                    cols = st.columns(4)
                    for i, actor in enumerate(credits['cast'][:4]):
                        if cols[i].button(actor['name'], key=f"src_act_{m_id}_{i}"):
                            st.session_state['search_query'] = actor['name']
                            st.rerun()
                st.markdown("---")
                b1, b2, b3 = st.columns([1, 1, 1])
                if b1.button("🎫 Wunschliste", key=f"src_wl_{m_id}"):
                    update_db_status(m, 'watchlist', "Suche")
                    st.rerun()
                if b2.button("✅ Gesehen", key=f"src_sn_{m_id}"):
                    update_db_status(m, 'seen', "Suche")
                    st.rerun()
                with b3:
                    st.link_button("🌐 Wer streamt?", f"https://www.google.com/search?q=wer+streamt+{title}")

# --- TAB: ENTDECKER MODUS ---
elif menu == "Entdecker-Modus ✨":
    st.header("✨ Entdecker-Modus")
    
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            timeframe = st.selectbox("Zeitraum:", ["Alles", "✨ Brandneu (ab 2024)", "📅 Dieser Monat", "🔮 Nächster Monat"])
        with c2:
            genre_list = ["Beliebig"] + list(GENRE_MAP.values())
            selected_genre = st.selectbox("Genre:", genre_list)
        with c3:
            min_stars = st.slider("Mindestbewertung:", 0.0, 10.0, 7.0)
            m_type = st.radio("Format:", ["Filme", "Serien"], horizontal=True)

    if st.button("🚀 Inspiration finden", use_container_width=True):
        type_path = "movie" if m_type == "Filme" else "tv"
        
        genre_query = ""
        if selected_genre != "Beliebig":
            g_id = [k for k, v in GENRE_MAP.items() if v == selected_genre][0]
            genre_query = f"&with_genres={g_id}"

        date_query = ""
        today = datetime.now()
        
        if timeframe == "✨ Brandneu (ab 2024)":
            date_query = "&primary_release_date.gte=2024-01-01" if type_path == "movie" else "&first_air_date.gte=2024-01-01"
        elif timeframe == "📅 Dieser Monat":
            start_date = today.replace(day=1)
            _, last_day = calendar.monthrange(today.year, today.month)
            end_date = today.replace(day=last_day)
            d_field = "primary_release_date" if type_path == "movie" else "first_air_date"
            date_query = f"&{d_field}.gte={start_date.strftime('%Y-%m-%d')}&{d_field}.lte={end_date.strftime('%Y-%m-%d')}"
        elif timeframe == "🔮 Nächster Monat":
            if today.month == 12:
                next_month = 1; next_year = today.year + 1
            else:
                next_month = today.month + 1; next_year = today.year
            start_date = datetime(next_year, next_month, 1)
            _, last_day = calendar.monthrange(next_year, next_month)
            end_date = start_date.replace(day=last_day)
            d_field = "primary_release_date" if type_path == "movie" else "first_air_date"
            date_query = f"&{d_field}.gte={start_date.strftime('%Y-%m-%d')}&{d_field}.lte={end_date.strftime('%Y-%m-%d')}"

        url = f"{TMDB_BASE_URL}/discover/{type_path}?api_key={TMDB_API_KEY}&language=de-DE{genre_query}{date_query}&vote_average.gte={min_stars}&vote_count.gte=100&sort_by=popularity.desc"
        st.session_state['explore_results'] = fetch_tmdb(url).get('results', [])[:15]

    for m in st.session_state.get('explore_results', []):
        t = m.get('title') or m.get('name')
        m_id = str(m['id']).replace('.0', '')
        found = find_local_fuzzy(t, local_lib)
        with st.expander(f"{'🟢 ' if found else ''}{t} ⭐ {m.get('vote_average')}"):
            if found: st.success(f"📂 Speicherort: {found['path']} ({found['type']})")
            c1, c2 = st.columns([1, 3])
            if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}")
            with c2:
                st.write(m.get('overview'))
                st.write("**Cast:**")
                credits = fetch_tmdb(f"{TMDB_BASE_URL}/{'movie' if 'title' in m else 'tv'}/{m_id}/credits?api_key={TMDB_API_KEY}")
                if credits.get('cast'):
                    cols = st.columns(3)
                    for i, person in enumerate(credits['cast'][:6]):
                        if cols[i % 3].button(person['name'], key=f"exp_p_{m_id}_{i}"):
                            st.session_state['search_query'] = person['name']
                            st.rerun()
                st.markdown("---")
                b1, b2 = st.columns(2)
                if b1.button("🎫 Wunschliste", key=f"ex_wl_{m_id}"):
                    update_db_status(m, 'watchlist', "Entdecker")
                    st.rerun()
                if b2.button("✅ Gesehen", key=f"ex_sn_{m_id}"):
                    update_db_status(m, 'seen', "Entdecker")
                    st.rerun()

# --- TAB: TV & MEDIATHEK ---
elif menu == "TV- und Mediatheken":
    st.header("📺 Live TV & Mediathek")
    t1, t2 = st.tabs(["TV Programm", "Mediathek Tipps"])
    
    with t1:
        c_tv1, c_tv2 = st.columns(2)
        if c_tv1.button("Heute 20:15", use_container_width=True):
            st.session_state['tv_data'] = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/heute2015.xml", "TV")
        if c_tv2.button("Heute 22:00", use_container_width=True):
            st.session_state['tv_data'] = get_feed_items("https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml", "TV")

        for item in st.session_state['tv_data']:
            item_hash = str(hash(item['title']))
            details = st.session_state['tv_infos'].get(item_hash)
            expander_title = f"⏰ {item['title']}"
            if details: expander_title += f" | ⭐ {round(details.get('vote_average', 0), 1)}"
            with st.expander(expander_title):
                if details:
                    c1, c2 = st.columns([1, 3])
                    if details.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{details.get('poster_path')}")
                    with c2:
                        st.caption(f"Genre: {get_genres_string(details.get('genre_ids'))}")
                        st.write(details.get('overview'))
                        st.markdown("---")
                        b1, b2 = st.columns(2)
                        m_id = str(details['id'])
                        if b1.button("🎫 Wunschliste", key=f"tv_wl_{m_id}"):
                            update_db_status(details, 'watchlist', "TV")
                            st.toast("Gespeichert!")
                        if b2.button("✅ Gesehen", key=f"tv_sn_{m_id}"):
                            update_db_status(details, 'seen', "TV")
                            st.toast("Markiert!")
                else:
                    st.write(item['desc'])
                    if st.button("ℹ️ Infos laden", key=f"tv_load_{item_hash}"):
                        clean_name = item['title'].split('|')[-1].strip()
                        res = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={clean_name}&language=de-DE")
                        if res.get('results'):
                            st.session_state['tv_infos'][item_hash] = res['results'][0]
                            st.rerun()

    with t2:
        if st.button("Mediathek Tipps laden", use_container_width=True):
            st.session_state['mediathek_data'] = get_feed_items("https://www.filmdienst.de/rss/mediatheken", "Mediathek")
        
        for item in st.session_state['mediathek_data']:
            item_hash = str(hash(item['title'] + "med"))
            details = st.session_state['tv_infos'].get(item_hash)
            expander_title = f"▶️ {item['title']}"
            if details: 
                expander_title += f" | ⭐ {round(details.get('vote_average', 0), 1)} | {get_genres_string(details.get('genre_ids'))}"

            with st.expander(expander_title):
                if details:
                    c1, c2 = st.columns([1, 3])
                    if details.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{details.get('poster_path')}")
                    with c2:
                        st.write(details.get('overview'))
                        st.markdown("---")
                        b1, b2 = st.columns(2)
                        m_id = str(details['id'])
                        if b1.button("🎫 Wunschliste", key=f"med_wl_{m_id}"):
                            update_db_status(details, 'watchlist', "Mediathek")
                            st.toast("Gespeichert!")
                        if b2.button("✅ Gesehen", key=f"med_sn_{m_id}"):
                            update_db_status(details, 'seen', "Mediathek")
                            st.toast("Markiert!")
                else:
                    st.write(item['desc'])
                    if st.button("ℹ️ Infos laden", key=f"med_load_{item_hash}"):
                        clean = item['title'].replace("Film:", "").replace("Serie:", "").strip()
                        res = fetch_tmdb(f"{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={clean}&language=de-DE")
                        if res.get('results'):
                            st.session_state['tv_infos'][item_hash] = res['results'][0]
                            st.rerun()

# --- TAB: WATCHLIST & GESEHEN ---
elif "Watchlist" in menu or "Schon gesehen" in menu:
    is_seen = "Schon gesehen" in menu
    target = seen_list if is_seen else watchlist
    st.header("✅ Gesehen" if is_seen else "🎫 Watchlist")
    
    sort_mode = st.selectbox("Sortieren nach:", ["Hinzugefügt (Neu zuerst)", "Titel (A-Z)", "Bewertung (Hoch zuerst)"])
    if sort_mode == "Titel (A-Z)": target.sort(key=lambda x: x['title'].lower())
    elif sort_mode == "Bewertung (Hoch zuerst)": target.sort(key=lambda x: float(x.get('vote_average', 0)), reverse=True)
    else: target.reverse()

    for i, m in enumerate(target):
        m_id = str(m['id']).replace('.0', '')
        u_rating = float(m.get('user_rating', 0.0))
        added = m.get('added_date', 'Unbekannt')
        source = m.get('source', 'Unbekannt')
        
        title_str = f"{m['title']} (⭐ {m.get('vote_average')})"
        
        if is_seen:
             if u_rating > 0: title_str += f" \t 👤 ⭐ {u_rating}"
             title_str += f" \t | 📅 {added}"
        else:
             title_str += f" \t | 📅 {added} | 🔗 {source}"
        
        with st.expander(title_str):
            c1, c2 = st.columns([1, 4])
            if m.get('poster_path'): c1.image(f"{IMAGE_BASE_URL}{m.get('poster_path')}", width=100)
            with c2:
                if not is_seen: st.caption(f"Hinzugefügt: {added} | Via: {source}")
                st.write(m.get('overview'))
                
                if is_seen:
                    c_sl, c_btn = st.columns([3, 1])
                    new_val = c_sl.slider("Deine Bewertung:", 0.0, 10.0, u_rating, 0.5, key=f"rat_{m_id}_{i}")
                    if c_btn.button("💾 Speichern", key=f"save_{m_id}_{i}"):
                        update_db_status(m, 'seen', user_rating=new_val)
                        st.toast("Gespeichert!")
                        st.rerun()
                else:
                    if st.button("✅ Gesehen", key=f"mv_sn_{m_id}_{i}"):
                        update_db_status(m, 'seen', origin="Watchlist")
                        st.rerun()

                if st.button("🗑️ Löschen", key=f"del_{m_id}_{i}"):
                    update_db_status(m, 'delete')
                    st.rerun()

# --- TAB: LOKALE LISTE ---
elif menu == "Lokale Liste":
    st.header("📂 Deine GitHub Sammlung")
    term = st.text_input("🔎 Lokale Suche:", placeholder="Titel, Schauspieler eingeben...")
    
    if local_lib:
        df = pd.DataFrame(local_lib.values())
        if not df.empty:
            cols_to_show = ['title', 'type', 'path', 'genre', 'actors', 'plot']
            available_cols = [c for c in cols_to_show if c in df.columns]
            df = df[available_cols]
            rename_map = {"title": "Titel", "type": "Typ", "path": "Ablageort", "genre": "Genre", "actors": "Schauspieler", "plot": "Handlung"}
            df = df.rename(columns=rename_map)
            
            if term: 
                df = df[
                    df['Titel'].str.contains(term, case=False) | 
                    df['Schauspieler'].str.contains(term, case=False)
                ]
            st.dataframe(df, use_container_width=True, hide_index=True)
