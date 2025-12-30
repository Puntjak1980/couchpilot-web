import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import random

# --- KONFIGURATION ---
st.set_page_config(page_title="CouchPilot Cloud", page_icon="🎬", layout="wide")

# --- API KEY SICHER LADEN ---
# Versucht, den Key aus den Secrets zu laden.
try:
    TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ API-Key nicht gefunden! Bitte in den Streamlit-Settings unter 'Secrets' eintragen: TMDB_API_KEY = '...'")
    st.stop()
except KeyError:
    st.error("⚠️ API-Key 'TMDB_API_KEY' fehlt in den Secrets.")
    st.stop()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Dateinamen (müssen im selben Ordner liegen wie dieses Skript auf GitHub)
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
            # engine='openpyxl' ist wichtig für Streamlit Cloud
            xls = pd.ExcelFile(filename, engine='openpyxl')
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
                
                # Spalten finden (flexibel wie in der Desktop App)
                # Wir suchen nach Titel-Spalten, egal wie sie genau heißen
                cols = [str(c).lower() for c in df.columns]
                col_t = next((c for c in df.columns if str(c).lower() in ["titel", "name", "filmtitel"]), None)
                col_p = next((c for c in df.columns if str(c).lower() in ["ablageort", "ablage", "pfad", "path", "location"]), None)
                
                if col_t:
                    for _, row in df.iterrows():
                        t = str(row[col_t]).strip()
                        # Leere Einträge überspringen
                        if len(t) > 1:
                            # Pfad bestimmen (Blattname oder Spalte)
                            path = sheet_name
                            if col_p and pd.notna(row[col_p]) and len(str(row[col_p])) > 1:
                                path = str(row[col_p]).strip()
                            
                            library[t.lower()] = {"title": t, "path": path, "type": cat}
        except Exception as e:
            # Falls eine Datei fehlt, machen wir einfach mit der anderen weiter
            print(f"Info: Konnte {filename} nicht laden oder Datei fehlt. ({e})")
            
    return library

def fetch_tmdb(url):
    """Hilfsfunktion für API-Abfragen"""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}

def get_feed_items(url, tag_prefix):
    """Liest RSS Feeds (z.B. TV Spielfilm)"""
    items = []
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        tree = ET.fromstring(resp.content)
        for item in tree.findall('./channel/item'):
            title_node = item.find('title')
            if title_node is not None:
                title = title_node.text
                desc = item.find('description').text or ""
                items.append({"title": title, "desc": desc, "tag": tag_prefix})
    except:
        pass
    return items

# --- UI START ---

st.title("🎬 CouchPilot Cloud")

# Daten laden (passiert nur beim ersten Start oder Reboot schnell dank Cache)
local_lib = load_local_data()
if local_lib:
    st.sidebar.success(f"{len(local_lib)} lokale Titel geladen.")
else:
    st.sidebar.warning("Keine lokalen Excel-Listen gefunden.")

# Sidebar Menü
menu = st.sidebar.radio("Speisekarte", ["Suche & Inspiration", "TV- und Mediatheken", "Lokale Liste"])

# --- TAB 1: SUCHE & INSPIRATION ---
if menu == "Suche & Inspiration":
    st.header("Was schauen wir heute?")
    
    # Suchfeld
    col1, col2 = st.columns([4, 1])
    with col1:
        search_query = st.text_input("Suche Filme wie...", placeholder="z.B. Matrix oder Star Wars")
    with col2:
        st.write("") 
        st.write("")
        btn_search = st.button("🔍 Suchen")

    st.write("Oder wähle ein Genre:")
    
    # Genre Buttons
    g_col1, g_col2, g_col3, g_col4 = st.columns(4)
    genre_id = None
    
    # Kleine Helfer-Logik für Buttons
    if g_col1.button("😂 Komödie"): genre_id = 35
    if g_col2.button("😱 Thriller"): genre_id = 53
    if g_col3.button("❤️ Romantik"): genre_id = 10749
    if g_col4.button("🌍 Doku"): genre_id = 99

    results = []
    
    # LOGIK 1: Textsuche (Ähnliche Filme)
    if (btn_search or search_query) and not genre_id:
        if search_query:
            # Schritt A: Den eingegebenen Film suchen, um die ID zu bekommen
            search_url = f"{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={search_query}&language=de-DE"
            data = fetch_tmdb(search_url)
            
            if data.get('results'):
                first_movie = data['results'][0]
                st.info(f"Basis für Empfehlungen: **{first_movie['title']}**")
                
                # Schritt B: Empfehlungen basierend auf diesem Film holen
                rec_url = f"{TMDB_BASE_URL}/movie/{first_movie['id']}/recommendations?api_key={TMDB_API_KEY}&language=de-DE"
                rec_data = fetch_tmdb(rec_url)
                results = rec_data.get('results', [])
            else:
                st.warning("Keinen Film mit diesem Namen gefunden.")

    # LOGIK 2: Genre-Suche
    elif genre_id:
        # Zufällige Seite für Abwechslung
        page = random.randint(1, 5)
        url = f"{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_id}&sort_by=vote_average.desc&vote_count.gte=300&page={page}&language=de-DE"
        data = fetch_tmdb(url)
        results = data.get('results', [])

    # ERGEBNISSE ANZEIGEN
    if results:
        for movie in results:
            # Expander für jeden Film
            with st.expander(f"{movie.get('title')} ({str(movie.get('release_date'))[:4]}) - ⭐ {movie.get('vote_average')}"):
                c1, c2 = st.columns([1, 3])
                
                with c1:
                    poster = movie.get('poster_path')
                    if poster:
                        st.image(f"{IMAGE_BASE_URL}{poster}")
                    else:
                        st.text("Kein Bild")
                        
                with c2:
                    st.write(movie.get('overview'))
                    st.markdown("---")
                    
                    # Check: Haben wir den Film lokal?
                    title_lower = movie.get('title', '').lower()
                    found_local = local_lib.get(title_lower)
                    
                    # Unscharfe Suche (falls Titel leicht abweicht)
                    if not found_local:
                        for k, v in local_lib.items():
                            # Prüfen ob Teilstring übereinstimmt (nur bei Länge > 4 um Fehl-Matches zu vermeiden)
                            if (len(k) > 4) and (title_lower in k or k in title_lower):
                                found_local = v
                                break
                    
                    # Anzeige Status
                    if found_local:
                        st.success(f"💾 **LOKAL VORHANDEN!**\n\nPfad: {found_local['path']} ({found_local['type']})")
                    else:
                        st.caption("Nicht lokal gefunden.")
                        # Link zum Googeln generieren
                        search_url = f"https://www.google.com/search?q={movie.get('title')} stream deutsch"
                        st.markdown(f"[🌐 Auf Google/Stream suchen]({search_url})")

# --- TAB 2: TV & MEDIATHEKEN ---
elif menu == "TV- und Mediatheken":
    st.header("📺 Live TV & Tipps")
    
    tab1, tab2 = st.tabs(["TV Programm Jetzt", "Mediathek Tipps"])
    
    with tab1:
        if st.button("TV Aktualisieren"):
            st.session_state['tv_data'] = []
            urls = [
                "https://www.tvspielfilm.de/tv-programm/rss/heute2015.xml", 
                "https://www.tvspielfilm.de/tv-programm/rss/heute2200.xml"
            ]
            items = []
            with st.spinner("Lade TV-Daten..."):
                for u in urls:
                    items.extend(get_feed_items(u, "TV"))
            st.session_state['tv_data'] = items
        
        if 'tv_data' in st.session_state and st.session_state['tv_data']:
            for item in st.session_state['tv_data']:
                st.subheader(item['title'])
                st.write(item['desc'])
                st.divider()
        else:
            st.info("Klicke auf 'Aktualisieren', um das TV-Programm zu laden.")
                
    with tab2:
        if st.button("Mediathek Tipps laden"):
            with st.spinner("Lade Mediatheken..."):
                items = get_feed_items("https://www.filmdienst.de/rss/mediatheken", "Mediathek")
                if not items:
                    st.warning("Keine Daten empfangen.")
                for item in items:
                    st.markdown(f"**{item['title']}**")
                    st.caption(item['desc'])
                    st.divider()

# --- TAB 3: LOKALE LISTE ---
elif menu == "Lokale Liste":
    st.header("Deine komplette Sammlung")
    if local_lib:
        # Umwandeln in DataFrame für schöne Anzeige
        df_display = pd.DataFrame(local_lib.values())
        
        # Suche in der Tabelle
        filter_text = st.text_input("Liste filtern:", "")
        if filter_text:
            mask = df_display.apply(lambda x: x.astype(str).str.contains(filter_text, case=False).any(), axis=1)
            df_display = df_display[mask]
            
        st.dataframe(
            df_display, 
            column_config={
                "title": "Titel",
                "path": "Speicherort / Pfad",
                "type": "Typ"
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.error("Die Excel-Dateien konnten nicht geladen werden. Bitte Upload prüfen.")