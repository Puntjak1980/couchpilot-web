import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import random

# --- KONFIGURATION ---
st.set_page_config(page_title="CouchPilot Web", page_icon="🎬", layout="wide")

# API Key (hier hardcodiert für den einfachen Start, später via Secrets empfohlen)
TMDB_API_KEY = "fc4c90dcd97dc764ad920d9491893a01"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Dateinamen (müssen im selben Ordner liegen wie dieses Skript)
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
            # Excel mit allen Blättern laden
            xls = pd.ExcelFile(filename)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
                
                # Spalten finden (flexibel wie in der Desktop App)
                cols = [str(c).lower() for c in df.columns]
                col_t = next((c for c in df.columns if str(c).lower() in ["titel", "name", "filmtitel"]), None)
                col_p = next((c for c in df.columns if str(c).lower() in ["ablageort", "ablage", "pfad", "path", "location"]), None)
                
                if col_t:
                    for _, row in df.iterrows():
                        t = str(row[col_t]).strip()
                        if len(t) > 1:
                            # Pfad bestimmen (Blattname oder Spalte)
                            path = sheet_name
                            if col_p and pd.notna(row[col_p]) and len(str(row[col_p])) > 1:
                                path = str(row[col_p]).strip()
                            
                            library[t.lower()] = {"title": t, "path": path, "type": cat}
        except Exception as e:
            print(f"Fehler bei {filename}: {e}")
            
    return library

def fetch_tmdb(url):
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except:
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
    except:
        pass
    return items

# --- UI START ---

st.title("🎬 CouchPilot Cloud")

# Daten laden
local_lib = load_local_data()
st.sidebar.success(f"{len(local_lib)} lokale Titel geladen.")

# Sidebar Menü
menu = st.sidebar.radio("Menü", ["Suche & Inspiration", "TV & Mediatheken", "Lokale Liste"])

if menu == "Suche & Inspiration":
    st.header("Was schauen wir heute?")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input("Suche Filme wie...", placeholder="z.B. Matrix oder Star Wars")
    with col2:
        st.write("") 
        st.write("")
        btn_search = st.button("🔍 Suchen")

    # Quick Buttons für Genres
    st.caption("Oder wähle ein Genre:")
    g_col1, g_col2, g_col3, g_col4 = st.columns(4)
    genre_id = None
    if g_col1.button("😂 Komödie"): genre_id = 35
    if g_col2.button("😱 Thriller"): genre_id = 53
    if g_col3.button("❤️ Romantik"): genre_id = 10749
    if g_col4.button("🌍 Doku"): genre_id = 99

    results = []
    
    # 1. Logik: Textsuche
    if (btn_search or search_query) and not genre_id:
        # Erst ID finden
        search_url = f"{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={search_query}&language=de-DE"
        data = fetch_tmdb(search_url)
        if data.get('results'):
            first_movie = data['results'][0]
            st.info(f"Basis für Empfehlungen: **{first_movie['title']}**")
            # Dann Empfehlungen holen
            rec_url = f"{TMDB_BASE_URL}/movie/{first_movie['id']}/recommendations?api_key={TMDB_API_KEY}&language=de-DE"
            rec_data = fetch_tmdb(rec_url)
            results = rec_data.get('results', [])
        else:
            st.warning("Nichts gefunden.")

    # 2. Logik: Genre
    elif genre_id:
        url = f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_id}&sort_by=vote_average.desc&vote_count.gte=300&page={random.randint(1,5)}&language=de-DE"
        data = fetch_tmdb(url)
        results = data.get('results', [])

    # ERGEBNISSE ANZEIGEN
    if results:
        for movie in results:
            with st.expander(f"{movie.get('title')} ({str(movie.get('release_date'))[:4]}) - ⭐ {movie.get('vote_average')}"):
                c1, c2 = st.columns([1, 3])
                with c1:
                    poster = movie.get('poster_path')
                    if poster:
                        st.image(f"{IMAGE_BASE_URL}{poster}")
                with c2:
                    st.write(movie.get('overview'))
                    
                    # Check Lokal
                    title_lower = movie.get('title', '').lower()
                    found_local = local_lib.get(title_lower)
                    
                    # Unscharfe Suche falls nicht exakt gefunden
                    if not found_local:
                        for k, v in local_lib.items():
                            if title_lower in k or k in title_lower:
                                if len(k) > 4: # Zu kurze Titel ignorieren
                                    found_local = v
                                    break
                    
                    if found_local:
                        st.success(f"💾 **LOKAL VORHANDEN!**\n\nPfad: {found_local['path']} ({found_local['type']})")
                    else:
                        st.caption("Nicht lokal gefunden.")
                        # Stream check Link
                        if st.button(f"Google Stream Suche: {movie.get('title')}", key=movie['id']):
                            st.write(f"Suche auf Google nach: {movie.get('title')} stream")

elif menu == "TV & Mediatheken":
    st.header("📺 Live TV & Tipps")
    
    tab1, tab2 = st.tabs(["TV Programm Jetzt", "Mediathek Tipps"])
    
    with tab1:
        if st.button("TV Aktualisieren"):
            st.session_state['tv_data'] = []
            urls = ["https://www.tvspielfilm.de/tv-programm/rss/heute2015.xml", "https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml"]
            items = []
            for u in urls:
                items.extend(get_feed_items(u, "TV"))
            st.session_state['tv_data'] = items
        
        if 'tv_data' in st.session_state:
            for item in st.session_state['tv_data']:
                st.subheader(item['title'])
                st.write(item['desc'])
                st.divider()
                
    with tab2:
        if st.button("Mediathek laden"):
            items = get_feed_items("https://www.filmdienst.de/rss/mediatheken", "Mediathek")
            for item in items:
                st.markdown(f"**{item['title']}**")
                st.caption(item['desc'])
                st.divider()

elif menu == "Lokale Liste":
    st.header("Deine Sammlung")
    df_display = pd.DataFrame(local_lib.values())
    st.dataframe(df_display, use_container_width=True)