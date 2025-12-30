import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import random

# --- KONFIGURATION ---
st.set_page_config(page_title="CouchPilot Cloud", page_icon="🎬", layout="wide")

# --- API KEY SICHER LADEN ---
try:
    TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
except (FileNotFoundError, KeyError):
    st.error("⚠️ API-Key fehlt! Bitte in Streamlit 'Secrets' hinterlegen.")
    st.stop()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
FILM_FILE = "Filme_Rosi_2025_DE.xlsx"
SERIEN_FILE = "Serien_Rosi_2025.xlsx"

# --- FUNKTIONEN ---

@st.cache_data
def load_local_data():
    """Lädt die Excel-Dateien und erstellt einen Suchindex."""
    library = {}
    files = {FILM_FILE: "Film", SERIEN_FILE: "Serie"}
    
    for filename, cat in files.items():
        try:
            xls = pd.ExcelFile(filename, engine='openpyxl')
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
                col_t = next((c for c in df.columns if str(c).lower() in ["titel", "name", "filmtitel"]), None)
                col_p = next((c for c in df.columns if str(c).lower() in ["ablageort", "ablage", "pfad", "path", "location"]), None)
                
                if col_t:
                    for _, row in df.iterrows():
                        t = str(row[col_t]).strip()
                        if len(t) > 1:
                            path = sheet_name
                            if col_p and pd.notna(row[col_p]) and len(str(row[col_p])) > 1:
                                path = str(row[col_p]).strip()
                            library[t.lower()] = {"title": t, "path": path, "type": cat}
        except Exception as e:
            print(f"Info: {filename} nicht geladen: {e}")
    return library

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
        tree = ET.fromstring(resp.content)
        for item in tree.findall('./channel/item'):
            title = item.find('title').text
            desc = item.find('description').text or ""
            items.append({"title": title, "desc": desc, "tag": tag_prefix})
    except: pass
    return items

# --- UI START ---

st.title("🎬 CouchPilot Cloud")

local_lib = load_local_data()
if local_lib:
    st.sidebar.success(f"{len(local_lib)} lokale Titel geladen.")
else:
    st.sidebar.warning("Keine lokalen Excel-Listen gefunden.")

menu = st.sidebar.radio("Speisekarte", ["Suche & Inspiration", "TV- und Mediatheken", "Lokale Liste"])

# --- TAB 1: SUCHE ---
if menu == "Suche & Inspiration":
    st.header("Was schauen wir heute?")
    col1, col2 = st.columns([4, 1])
    with col1:
        search_query = st.text_input("Suche Filme wie...", placeholder="z.B. Matrix")
    with col2:
        st.write(""); st.write("")
        btn_search = st.button("🔍 Suchen")

    st.write("Oder wähle ein Genre:")
    g_col1, g_col2, g_col3, g_col4 = st.columns(4)
    genre_id = None
    if g_col1.button("😂 Komödie"): genre_id = 35
    if g_col2.button("😱 Thriller"): genre_id = 53
    if g_col3.button("❤️ Romantik"): genre_id = 10749
    if g_col4.button("🌍 Doku"): genre_id = 99

    results = []
    if (btn_search or search_query) and not genre_id:
        if search_query:
            data = fetch_tmdb(f"{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={search_query}&language=de-DE")
            if data.get('results'):
                first = data['results'][0]
                st.info(f"Basis: **{first['title']}**")
                results = fetch_tmdb(f"{TMDB_BASE_URL}/movie/{first['id']}/recommendations?api_key={TMDB_API_KEY}&language=de-DE").get('results', [])
            else: st.warning("Nichts gefunden.")
    elif genre_id:
        results = fetch_tmdb(f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_id}&sort_by=vote_average.desc&vote_count.gte=300&page={random.randint(1,5)}&language=de-DE").get('results', [])

    if results:
        for movie in results:
            with st.expander(f"{movie.get('title')} ({str(movie.get('release_date'))[:4]}) - ⭐ {movie.get('vote_average')}"):
                c1, c2 = st.columns([1, 3])
                with c1:
                    if movie.get('poster_path'): st.image(f"{IMAGE_BASE_URL}{movie.get('poster_path')}")
                with c2:
                    st.write(movie.get('overview'))
                    st.markdown("---")
                    found = local_lib.get(movie.get('title', '').lower())
                    if not found:
                        for k, v in local_lib.items():
                            if (len(k)>4) and (movie.get('title','').lower() in k): found = v; break
                    
                    if found: st.success(f"💾 **LOKAL: {found['path']}**")
                    else: st.markdown(f"[🌐 Google Stream Suche](https://www.google.com/search?q={movie.get('title')}+stream+deutsch)")

# --- TAB 2: TV & MEDIATHEK (KOMPAKT) ---
elif menu == "TV- und Mediatheken":
    st.header("📺 Live TV & Tipps")
    
    tab1, tab2 = st.tabs(["TV Programm Jetzt", "Mediathek Tipps"])
    
    with tab1:
        if st.button("TV Aktualisieren", type="primary"):
            urls = ["https://www.tvspielfilm.de/tv-programm/rss/heute2015.xml", "https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml"]
            items = []
            with st.spinner("Lade TV-Daten..."):
                for u in urls: items.extend(get_feed_items(u, "TV"))
            st.session_state['tv_data'] = items
        
        if 'tv_data' in st.session_state and st.session_state['tv_data']:
            for item in st.session_state['tv_data']:
                # Container mit weniger Innenabstand
                with st.container(border=True):
                    parts = item['title'].split('|')
                    
                    if len(parts) >= 3:
                        time_str = parts[0].strip()
                        sender_str = parts[1].strip()
                        title_str = " | ".join(parts[2:]).strip()
                        
                        col_time, col_content = st.columns([1, 6])
                        
                        with col_time:
                            # Zeit kompakter, aber immer noch orange/fett
                            st.markdown(f"<div style='text-align: center; color: #e67e22; font-weight: bold; font-size: 1.1em;'>{time_str}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div style='text-align: center; font-size: 0.8em; color: gray;'>{sender_str}</div>", unsafe_allow_html=True)
                            
                        with col_content:
                            # TITEL: Fett aber normale Größe (statt subheader)
                            st.markdown(f"**{title_str}**")
                            # Beschreibung: Kleinere Schrift
                            st.caption(item['desc'])
                    else:
                        st.markdown(f"**{item['title']}**")
                        st.caption(item['desc'])
        else:
            st.info("Klicke oben auf 'TV Aktualisieren'.")

    with tab2:
        if st.button("Mediathek Tipps laden"):
            with st.spinner("Lade Mediatheken..."):
                items = get_feed_items("https://www.filmdienst.de/rss/mediatheken", "Mediathek")
                for item in items:
                    with st.container(border=True):
                        # Titel fett, normale Größe
                        st.markdown(f"**{item['title']}**")
                        # unsafe_allow_html sorgt dafür, dass <br> und &uuml; richtig angezeigt werden
                        st.markdown(f"<div style='font-size: 0.9em; color: #444;'>{item['desc']}</div>", unsafe_allow_html=True)

# --- TAB 3: LISTE ---
elif menu == "Lokale Liste":
    st.header("Deine Sammlung")
    if local_lib:
        search = st.text_input("Filtern:", "")
        df = pd.DataFrame(local_lib.values())
        if search:
            df = df[df.apply(lambda x: x.astype(str).str.contains(search, case=False).any(), axis=1)]
        st.dataframe(df, use_container_width=True, hide_index=True)