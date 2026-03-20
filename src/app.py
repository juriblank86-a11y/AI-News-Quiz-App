import streamlit as st
import os
import re
import datetime
import logging
from dotenv import load_dotenv

# Unsere Module importieren
import database
import scraper
import generator
import validator

# Logging einrichten
# Logging einrichten
# File Handler für Debugging hinzufügen
# Root Logger konfigurieren - DEBUG für alles, damit wir "alles" sehen
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG) 

# Noise-Filter: Externe Bibliotheken etwas ruhiger stellen
for lib in ["httpx", "httpcore", "urllib3", "openai", "streamlit", "watchdog", "git"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

# File Handler (behält alles ab DEBUG)
file_handler = logging.FileHandler("debug.log", mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG) # Alles ins File
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Verhindern dass Handler mehrfach hinzugefügt werden
if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
    root_logger.addHandler(file_handler)

# Console Handler hinzufügen (damit es auch im CMD erscheint)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG) # Alles in die Konsole
console_handler.setFormatter(formatter)
if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
    root_logger.addHandler(console_handler)

# Expliziter Logger Name statt __name__, um sicherzustellen dass er nicht von Streamlit verschluckt wird
logger = logging.getLogger("NewsQuizApp")
logger.setLevel(logging.DEBUG)

# Umgebungsvariablen laden
load_dotenv()

st.set_page_config(page_title="News Quiz Generator", page_icon="📰", layout="centered")

# Benutzerdefiniertes CSS für Hintergrund und Glasmorphismus
import base64

def get_base64_image(image_path):
    """Kodiert ein Bild zu Base64 für den CSS-Hintergrund."""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except:
        return None

# Hintergrundbild laden
bg_path = os.path.join(os.path.dirname(__file__), "background.png")
bg_base64 = get_base64_image(bg_path)

# CSS laden
try:
    with open(os.path.join(os.path.dirname(__file__), "style.css"), "r") as f:
        # Ersetze die Standard :root Variablen wenn im Dark Mode
        css_content = f.read()
except:
    css_content = ""

# Prüfe Theme
is_dark = st.session_state.get('theme', 'dark') == 'dark'

# Theme-Klasse injecten (Einfacher Trick: Wir hängen die Klasse an den Root Container)
# Da wir CSS Variablen nutzen, definieren wir die Variablen einfach per JS oder überschreiben :root
if is_dark:
    # Füge Dark-Mode Variablen hinzu (überschreibt :root Werte im CSS)
    css_content += """
    :root {
        --bg-overlay: rgba(20, 30, 40, 0.85);
        --bg-overlay-2: rgba(10, 15, 25, 0.95);
        --sidebar-bg: rgba(25, 30, 45, 0.75);
        --main-bg: rgba(30, 35, 50, 0.75);
        --text-primary: #e0e0e0;
        --text-secondary: #ffffff;
        --border-color: rgba(100, 100, 100, 0.3);
        --shadow-color: rgba(0, 0, 0, 0.4);
    }
    """
else:
    # Light Mode (Standard :root Werte werden genutzt, evtl. hier explizit überschreiben falls nötig)
    css_content += """
    :root {
        --bg-overlay: rgba(240, 245, 255, 0.4);
        --bg-overlay-2: rgba(255, 255, 255, 0.6);
        --sidebar-bg: rgba(255, 255, 255, 0.85);
        --main-bg: rgba(255, 255, 255, 0.90);
        --text-primary: #2c3e50;
        --text-secondary: #1a1a2e;
        --border-color: rgba(200, 200, 200, 0.3);
        --shadow-color: rgba(0, 0, 0, 0.1);
    }
    """

if bg_base64:
    # Nutze CSS Variablen für den Gradient
    css_content += f"""
    .stApp {{
        background-image: linear-gradient(var(--bg-overlay), var(--bg-overlay-2)), url("data:image/png;base64,{bg_base64}");
    }}
    """

st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)


def process_and_save_quiz(content, video_data, api_key, provider, model, status_container, language="German", quiz_mode="Multiple Choice"):
    """
    Zentrale Funktion zum Generieren, Validieren und Speichern eines Quizzes.
    Wird von allen Quiz-Arten (Video, Artikel, Upload, Kombiniert) verwendet.
    """
    logger.info(f"Starte process_and_save_quiz. Sprache: {language}, Modus: {quiz_mode}, Textlänge: {len(content)}")
    status_container.update(label=f"📝 Analysiere {len(content)} Zeichen Text...", state="running")
    st.write(f"Textlänge: {len(content)} Zeichen")
    
    st.write("🧠 Denke nach und generiere Fragen...")
    gen = generator.QuizGenerator(api_key=api_key, provider=provider, model=model)
    # Passe Fragenanzahl an Content-Länge an (min 5, max 12) - mehr generieren wegen Validierungs-Filter
    num_questions = min(12, max(5, int(len(content) / 1500)))
    
    questions = gen.generate_quiz(content, num_questions=num_questions, language=language, quiz_mode=quiz_mode)
    
    if not questions:
        logger.error("Keine Fragen generiert.")
        status_container.update(label="Fehler bei der Fragenerstellung.", state="error")
        return None
    
    logger.info(f"{len(questions)} Roh-Fragen generiert.")
    st.write(f"✅ {len(questions)} Fragen erstellt.")
    
    # Duplikate filtern
    status_container.update(label="🔍 Prüfe auf Duplikate...", state="running")
    st.write("Prüfe auf bereits gestellte Fragen...")
    existing_questions = database.get_all_question_texts()
    unique_questions = generator.filter_duplicate_questions(questions, existing_questions)
    
    if len(questions) != len(unique_questions):
        logger.warning(f"{len(questions) - len(unique_questions)} Duplikate entfernt.")
    questions = unique_questions
    
    if not questions:
        logger.warning("Alle Fragen waren Duplikate.")
        status_container.update(label="Alle Fragen waren Duplikate. Bitte anderen Inhalt wählen.", state="error")
        return None
    
    st.write(f"✨ {len(questions)} einzigartige Fragen.")
    
    # Validierung durchführen
    status_container.update(label="🕵️‍♀️ Vorbereitung zur Validierung...", state="running")
    
    validation_text = content
    if language != "German":
        status_container.update(label=f"🌍 Übersetze Text ins {language} für Validierung...", state="running")
        st.write(f"Übersetze Quelltext ins {language}...")
        logger.info(f"Starte Übersetzung nach {language} für Validierung.")
        validation_text = gen.translate_text(content, language)
        st.write("Übersetzung abgeschlossen.")

    status_container.update(label="🕵️‍♀️ Validiere Fakten...", state="running")
    st.write("Validiere Antworten gegen Quelltext...")
    validation_result = validator.validate_quiz(questions, validation_text)
    
    # Logge Validierungsdetails
    logger.info("Validierungsergebnisse:")
    for i, q_res in enumerate(validation_result['questions']):
        log_msg = f"Frage {i+1}: Valid={q_res['is_valid']}, Score={q_res['validation_score']:.2f}, Type={q_res['correct_answer_validation']['match_type']} - '{q_res['question']}'"
        logger.info(log_msg)
        if not q_res['is_valid']:
            msg_1 = f"  ❌ FRAGE ABGELEHNT: Antwort '{q_res['correct_answer']}' nicht im Text gefunden."
            msg_2 = f"     Grund: {q_res['correct_answer_validation']['details']}"
            msg_3 = f"     Frage war: '{q_res['question']}'"
            
            logger.warning(msg_1)
            logger.warning(msg_2)
            logger.warning(msg_3)
            # Fallback print für CMD falls Logger zickt
            print(f"WARNING: {msg_1}")
            print(f"WARNING: {msg_2}")
            print(f"WARNING: {msg_3}")

    # STRIKTER FILTER: Nur Fragen behalten, die validiert wurden
    valid_questions = []
    for i, q in enumerate(questions):
        if validation_result['questions'][i]['is_valid']:
            valid_questions.append(q)
    
    discarded_count = len(questions) - len(valid_questions)
    if discarded_count > 0:
        logger.warning(f"{discarded_count} Fragen wegen fehlender Validierung entfernt.")
        st.warning(f"⚠️ {discarded_count} Fragen wurden entfernt, da die Antwort nicht im Text gefunden wurde.")
        
    questions = valid_questions
    
    # Fallback: Wenn zu wenig Fragen übrig (< 4), zeige Warnung aber fahre fort
    if not questions:
        logger.error("Keine Fragen übrig nach Validierung.")
        status_container.update(label="Keine Fragen konnten validiert werden (Antworten nicht im Text gefunden).", state="error")
        return None
    elif len(questions) < 4:
        logger.warning(f"Nur {len(questions)} Fragen übrig - zeige Warnung aber fahre fort.")
        st.warning(f"⚠️ Nur {len(questions)} Fragen konnten validiert werden. Für bessere Ergebnisse wähle längeren Content.")
        
    st.write(f"✓ {len(questions)} geprüfte Fragen bereit.")
    
    # Erneute Validierung für sauberen State
    validation_result = validator.validate_quiz(questions, validation_text)
    
    # State speichern
    st.session_state.validation = validation_result
    st.session_state.source_content = content
    st.session_state.original_questions = questions
    st.session_state.current_quiz_mode = quiz_mode
    
    status_container.update(label="💾 Speichere Quiz...", state="running")
    st.write("Speichere Quiz...")
    database.save_quiz(video_data, content[:5000], questions, 
               validation=st.session_state.get('validation'))
    
    logger.info("Quiz erfolgreich gespeichert.")
    status_container.update(label="🎉 Quiz fertig!", state="complete")
    return True


def generate_quiz_for_item(item, source_id, api_key, provider, model, language="German", quiz_mode="Multiple Choice"):
    """Generiert ein Quiz für ein bestimmtes Element (Video oder Artikel)."""
    with st.status("🚀 Starte Quiz-Maschine...", expanded=True) as status:
        st.write(f"📄 {item['title']}")
        
        status.update(label="🌐 Lade Inhalt...", state="running")
        st.write("Lade Inhalt...")
        content = scraper.get_content_for_item(item, source_id)
        
        if not content:
            status.update(label="Kein Inhalt gefunden.", state="error")
            return None
            
        video_data = {
            "id": item.get("id", item.get("link", "")),
            "title": item["title"],
            "url": item.get("link", item.get("url", ""))
        }
        
        if process_and_save_quiz(content, video_data, api_key, provider, model, status, language=language, quiz_mode=quiz_mode):
             return database.get_daily_quiz()
        return None

def load_models(provider, api_key):
    gen=generator.QuizGenerator(api_key=api_key, provider=provider)
    #return gen.client.models.list()
    return [m.id for m in gen.client.models.list()]


def main():
    st.title("📰 News Quiz Generator")
    
    # Datenbank initialisieren
    if 'db_initialized' not in st.session_state:
        database.init_db()
        st.session_state['db_initialized'] = True

    # Session-States initialisieren
    if 'available_items' not in st.session_state:
        st.session_state.available_items = []
    if 'selected_source' not in st.session_state:
        st.session_state.selected_source = "tagesschau_video"

    # Seitenleiste
    with st.sidebar:
        st.header("📜 Verlauf")
        
        # Historie laden
        history_list = database.get_quiz_history(limit=50)
        
        if not history_list:
            st.caption("Noch keine Quizze gespeichert.")
        else:
            # Optionen für Selectbox erstellen
            # Wir nutzen ein Dict für Mapping: Anzeige -> ID
            history_options = {}
            for h in history_list:
                # Datum schön formatieren
                try:
                    date_obj = datetime.datetime.strptime(h['created_at'], "%Y-%m-%dT%H:%M:%S.%f")
                    date_str = date_obj.strftime("%d.%m. %H:%M")
                except:
                    date_str = h['date_str']
                
                label = f"{date_str}: {h['video_title'][:40]}..."
                history_options[label] = h['id']
            
            # Selectbox
            # Wir wollen, dass standardmäßig das Neueste (oder gar nichts?) ausgewählt ist
            # Aber wir reagieren auf Änderungen
            
            selected_hist_label = st.selectbox(
                "Früheres Quiz laden:",
                options=list(history_options.keys()),
                index=None,
                placeholder="Bitte wählen...",
                key="history_selector"
            )
            
            if selected_hist_label:
                st.session_state.selected_history_id = history_options[selected_hist_label]
            else:
                # Wenn nichts ausgewählt (X geklickt), dann Reset auf Neuestes
                st.session_state.selected_history_id = None
                
        st.markdown("---")
        st.header("⚙️ Einstellungen")
        
        # Anbieter-Auswahl
        provider_options = {
            "Groq (Cloud, schnell)": "groq",
            "Ollama (Lokal)": "ollama",
            "LM Studio (Lokal)": "lmstudio",
            "OpenAI": "openai",
        }
        selected_provider_label = st.selectbox(
            "KI-Anbieter",
            options=list(provider_options.keys()),
            index=0
        )
        provider = provider_options[selected_provider_label]
        
        provider_obj = next((p for p in generator.providers if p["key"] == provider), None)
        print(provider_obj["name"])
        print(type(provider_obj["api_key_required"]))
        # API-Schlüssel
        if not provider_obj["api_key_required"]:# provider in ["ollama", "lmstudio"]:
            api_key = "not-needed"
            st.info("Kein API Key nötig für lokale Modelle.")
        else:
            # Streamlit Cloud: st.secrets > Env Vars > Manual Input
            default_key = ""
            try:
                if provider == "groq":
                    default_key = st.secrets.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", os.environ.get("API_KEY", "")))
                elif provider == "openai":
                    default_key = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", os.environ.get("API_KEY", "")))
                else:
                    default_key = os.environ.get("API_KEY", "")
            except Exception:
                default_key = os.environ.get("API_KEY", "")
            
            api_key = st.text_input("API Key", value=default_key, type="password")
            if not api_key:
                st.warning("Bitte API Key eingeben.")
        
        # Modell-Auswahl
        default_models = {
            "groq": "llama-3.3-70b-versatile",
            "ollama": "llama3.2",
            "lmstudio": "local-model",
            "openai": "gpt-3.5-turbo",
        }

        
        # Modelle holen (nur wenn nötig)
        models = []
        if provider == "groq" and api_key or provider in ["ollama", "lmstudio"]:
            try:
                models = load_models(provider,api_key)
            except Exception as e:
                st.error(f"Fehler beim Laden der Modelle: {provider} - {api_key} {e}")

        key_name = f"model_{provider}"
        if key_name not in st.session_state:
            st.session_state[key_name] = default_models.get(provider, "")

        if models:
            model = st.selectbox(
                "Modell",
                models,
                index=models.index(st.session_state[key_name]) if st.session_state[key_name] in models else 0,
                key=key_name
            )
        else:
            model = st.text_input("Modell", st.session_state[key_name], key=key_name)



        # Falls Modelle vorhanden → Dropdown, sonst Textbox
        #if models:
        #    model = st.selectbox("Modell", models)
        #else:
        #    model = st.text_input("Modell", value=default_models.get(provider, ""))
        #model = st.text_input("Modell", value=default_models.get(provider, ""))

        st.markdown("---")
        st.header("🌐 Sprache / Language")
        
        language_options = {
            "🇩🇪 Deutsch": "German",
            "🇬🇧 English": "English",
            "🇫🇷 Français": "French",
            "🇪🇸 Español": "Spanish",
            "🇮🇹 Italiano": "Italian",
            "🇹🇷 Türkçe": "Turkish",
            "🇷🇺 Русский": "Russian",
            "🇯🇵 日本語": "Japanese",
            "🇮🇷 فارسی": "Persian",
        }
        
        selected_language_label = st.selectbox(
            "Quiz-Sprache",
            options=list(language_options.keys()),
            index=0
        )
        selected_language = language_options[selected_language_label]
        
        st.markdown("---")
        st.header("🎯 Quiz-Modus")
        
        quiz_mode = st.radio(
            "Antwort-Format",
            options=["Multiple Choice", "Freitext"],
            index=0,
            help="Multiple Choice: 4 Optionen zum Auswählen. Freitext: Selbst tippen."
        )
        
        st.markdown("---")
        st.header("🎨 Design")
        
        # Theme Toggle
        if 'theme' not in st.session_state:
            st.session_state.theme = 'dark'
            
        def toggle_theme():
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            
        st.toggle("☀️ Light Mode", value=(st.session_state.theme == 'light'), on_change=toggle_theme)

        st.markdown("---")
        st.header("📺 Quelle & Inhalt")
        
        # Quellenauswahl
        sources = scraper.get_available_sources()
        source_options = {s["name"]: s["id"] for s in sources}
        selected_source_label = st.selectbox(
            "Nachrichtenquelle",
            options=list(source_options.keys())
        )
        source_id = source_options[selected_source_label]
        
        # Ausgewählte Quelle im Session-State aktualisieren
        st.session_state.selected_source = source_id
        
        # Elemente automatisch laden wenn leer oder Quelle geändert
        def load_items_for_source(src_id):
            if src_id == "tagesschau_video":
                return scraper.find_recent_tagesschau(limit=20)
            elif src_id == "tagesschau_channel":
                return scraper.fetch_youtube_channel_videos(limit=30)
            elif src_id == "tagesschau_mediathek":
                return scraper.fetch_mediathek_videos(limit=20)
            else:
                return scraper.fetch_rss_articles(src_id, limit=15)
        
        # Elemente immer anzeigen - bei Bedarf laden
        if not st.session_state.available_items:
            with st.spinner("Lade verfügbare Inhalte..."):
                st.session_state.available_items = load_items_for_source(source_id)
        
        # Manueller Neu-Laden Button
        if st.button("🔄 Neu laden", use_container_width=True):
            with st.spinner("Lade verfügbare Inhalte..."):
                st.session_state.available_items = load_items_for_source(source_id)
        
        # Inhaltsauswahl-Dropdown
        if st.session_state.available_items:
            item_options = {
                f"{item['title'][:50]}..." if len(item['title']) > 50 else item['title']: i 
                for i, item in enumerate(st.session_state.available_items)
            }
            selected_item_label = st.selectbox(
                "Inhalt auswählen",
                options=list(item_options.keys())
            )
            selected_item_idx = item_options.get(selected_item_label, 0)
            selected_item = st.session_state.available_items[selected_item_idx]
            
            # Speichere aktuellen Inhalt für "Neues Quiz" Button
            st.session_state.last_selected_item = selected_item
            st.session_state.last_source_id = source_id
            
            # Quiz-Generieren Button oder automatische Neugenerierung
            should_generate = st.button("✨ Quiz generieren", type="primary", use_container_width=True)
            
            # Prüfe ob "Neues Quiz" geklickt wurde
            if st.session_state.get('regenerate_quiz', False):
                should_generate = True
                st.session_state.regenerate_quiz = False
            
            if should_generate:
                if api_key:
                    # database.delete_daily_quiz() - REMOVED for persistence
                    generate_quiz_for_item(selected_item, source_id, api_key, provider, model, language=selected_language, quiz_mode=quiz_mode)
                    st.session_state.last_source_type = "source"  # Markiere als normale Quelle
                    st.session_state.submitted = False
                    st.session_state.user_answers = {}
                    st.session_state.attempt_saved = False
                    st.session_state.selected_history_id = None
                    st.rerun()
            
            # Button für alle Artikel (nur bei RSS-Quellen)
            current_source = next((s for s in sources if s["id"] == source_id), None)
            if current_source and current_source.get("type") == "rss":
                st.markdown("**oder:**")
                num_articles = st.slider("Anzahl Artikel", min_value=5, max_value=30, value=15)
                
                if st.button("📚 Alle Artikel kombinieren", use_container_width=True):
                    if api_key:
                        with st.status("Sammle alle Artikel...", expanded=True) as status:
                            st.write(f"Lade {num_articles} Artikel von {current_source['name']}...")
                            
                            result = scraper.fetch_all_articles_combined(source_id, limit=num_articles)
                            
                            if result["count"] > 0:
                                st.write(f"✅ {result['count']} Artikel geladen ({len(result['content'])} Zeichen)")
                                
                                video_data = {
                                    "id": f"combined_{source_id}",
                                    "title": result["title"],
                                    "url": current_source.get("url", "")
                                }
                                
                                if process_and_save_quiz(result["content"][:15000], video_data, api_key, provider, model, status, language=selected_language, quiz_mode=quiz_mode):
                                    # Speichere für "Neues Quiz"
                                    st.session_state.last_upload_content = result["content"]
                                    st.session_state.last_upload_title = result["title"]
                                    st.session_state.last_source_type = "upload"
                                    
                                    st.session_state.submitted = False
                                    st.session_state.user_answers = {}
                                    st.session_state.attempt_saved = False
                                    st.rerun()
                            else:
                                status.update(label="Keine Artikel gefunden", state="error")
        
        # Eigener Link Bereich
        st.markdown("---")
        st.header("🔗 Eigener Link")
        
        custom_url = st.text_input(
            "YouTube-Video oder Artikel-URL",
            placeholder="https://youtube.com/watch?v=... oder https://...",
            help="Füge einen YouTube-Link (für Transkription) oder einen Artikel-Link ein"
        )
        
        if custom_url:
            # Prüfe ob es ein YouTube-Link ist
            youtube_match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', custom_url)
            
            # Prüfe ob es ein Tagesschau-Mediathek-Link ist (Audio oder Video)
            tagesschau_match = re.search(r'tagesschau\.de/.*/(audio|video)-(\d+)', custom_url)
            
            if youtube_match:
                video_id = youtube_match.group(1)
                st.success(f"✅ YouTube-Video erkannt (ID: {video_id})")
                
                if st.button("🎬 Quiz aus Video generieren", use_container_width=True):
                    if api_key:
                        custom_item = {
                            "id": video_id,
                            "title": f"YouTube Video: {video_id}",
                            "link": custom_url,
                            "type": "video"
                        }
                        # database.delete_daily_quiz() - REMOVED
                        generate_quiz_for_item(custom_item, "custom", api_key, provider, model, language=selected_language)
                        st.session_state.submitted = False
                        st.session_state.user_answers = {}
                        st.session_state.attempt_saved = False
                        st.session_state.selected_history_id = None
                        st.rerun()
            
            elif tagesschau_match:
                media_type = tagesschau_match.group(1)  # 'audio' oder 'video'
                media_id = tagesschau_match.group(2)
                
                if media_type == 'audio':
                    st.success(f"🎙️ Tagesschau Audio/Podcast erkannt (ID: {media_id})")
                    button_label = "🎙️ Quiz aus Audio generieren"
                else:
                    st.success(f"📺 Tagesschau Video erkannt (ID: {media_id})")
                    button_label = "📺 Quiz aus Video generieren"
                
                st.info("⏳ Das Audio/Video wird heruntergeladen und transkribiert. Dies kann einige Minuten dauern.")
                
                custom_title = st.text_input("Titel (optional)", placeholder="z.B. Tagesschau 20 Uhr...")
                
                if st.button(button_label, use_container_width=True):
                    if api_key:
                        custom_item = {
                            "id": f"tagesschau_{media_type}_{media_id}",
                            "title": custom_title if custom_title else f"Tagesschau {media_type.capitalize()}: {media_id}",
                            "link": custom_url,
                            "type": "mediathek"  # Nutzt lokale Transkription
                        }
                        # database.delete_daily_quiz() - REMOVED
                        generate_quiz_for_item(custom_item, "custom", api_key, provider, model, language=selected_language)
                        st.session_state.submitted = False
                        st.session_state.user_answers = {}
                        st.session_state.attempt_saved = False
                        st.session_state.selected_history_id = None
                        st.rerun()
            else:
                st.info("📄 Artikel-URL erkannt")
                
                custom_title = st.text_input("Titel (optional)", placeholder="Artikelüberschrift...")
                
                if st.button("📝 Quiz aus Artikel generieren", use_container_width=True):
                    if api_key:
                        custom_item = {
                            "id": custom_url,
                            "title": custom_title if custom_title else "Benutzerdefinierter Artikel",
                            "link": custom_url,
                            "type": "article"
                        }
                        # database.delete_daily_quiz() - REMOVED
                        generate_quiz_for_item(custom_item, "custom", api_key, provider, model, language=selected_language)
                        st.session_state.submitted = False
                        st.session_state.user_answers = {}
                        st.session_state.attempt_saved = False
                        st.session_state.selected_history_id = None
                        st.rerun()
        
        # Datei-Upload Bereich
        st.markdown("---")
        st.header("📁 Datei hochladen")
        
        uploaded_file = st.file_uploader(
            "Video oder Dokument",
            type=["mp4", "mp3", "wav", "webm", "m4a", "pdf", "docx", "txt"],
            help="Lade ein Video (wird transkribiert) oder Dokument (PDF, DOCX, TXT) hoch"
        )
        
        if uploaded_file is not None:
            file_ext = uploaded_file.name.split('.')[-1].lower()
            
            # Zeige Dateiinfo
            st.info(f"📄 **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")
            
            # Bestimme Dateityp
            video_types = ['mp4', 'mp3', 'wav', 'webm', 'm4a', 'ogg']
            is_video = file_ext in video_types
            
            if is_video:
                st.warning("⏳ Video-Transkription kann einige Minuten dauern...")
            
            upload_title = st.text_input(
                "Titel für das Quiz",
                value=uploaded_file.name.rsplit('.', 1)[0],
                key="upload_title"
            )
            
            if st.button("📤 Quiz aus Datei generieren", use_container_width=True, type="primary"):
                if api_key:
                    import tempfile
                    import os as os_module
                    from transcriber import process_uploaded_file
                    
                    # Speichere hochgeladene Datei temporär
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp_file:
                        tmp_file.write(uploaded_file.getbuffer())
                        tmp_path = tmp_file.name
                    
                    try:
                        with st.status(f"Verarbeite {uploaded_file.name}...", expanded=True) as status:
                            # Extrahiere Text
                            content = process_uploaded_file(tmp_path, file_ext)
                            
                            if content and len(content) > 100:
                                st.write(f"✅ {len(content)} Zeichen extrahiert")
                                
                                video_data = {
                                    "id": f"upload_{uploaded_file.name}",
                                    "title": upload_title,
                                    "url": ""
                                }
                                
                                if process_and_save_quiz(content, video_data, api_key, provider, model, status, language=selected_language, quiz_mode=quiz_mode):
                                    # Speichere Upload-Info für "Neues Quiz"
                                    st.session_state.last_upload_content = content
                                    st.session_state.last_upload_title = upload_title
                                    st.session_state.last_source_type = "upload"
                                    
                                    st.session_state.submitted = False
                                    st.session_state.user_answers = {}
                                    st.session_state.attempt_saved = False
                                    st.session_state.selected_history_id = None
                                    st.rerun()
                            else:
                                status.update(label="Konnte keinen Text extrahieren", state="error")
                    finally:
                        # Lösche temporäre Datei
                        try:
                            os_module.remove(tmp_path)
                        except:
                            pass
                else:
                    st.error("Bitte API Key eingeben")
    if not api_key:
        st.info("Bitte gib einen API Key ein, um zu starten.")
        return

    # Bestehendes Quiz laden
    if st.session_state.get('selected_history_id'):
        quiz = database.get_quiz_by_id(st.session_state.selected_history_id)
        if not quiz:
            # Fallback falls ID ungültig
            quiz = database.get_daily_quiz()
    else:
        quiz = database.get_daily_quiz()
    
    if not quiz:
        st.info("👈 Wähle links eine Quelle und einen Inhalt aus, dann klicke auf 'Quiz generieren'.")
        return
    
    # Quiz-Zustand initialisieren
    if 'user_answers' not in st.session_state:
        st.session_state.user_answers = {}
    if 'submitted' not in st.session_state:
        st.session_state.submitted = False
        
    # Quiz anzeigen
    st.subheader(f"📝 {quiz['video_title']}")
    
    # Link zur Originalquelle anzeigen (wenn vorhanden)
    source_url = quiz.get('source_url', '')
    if source_url:
        if 'youtube.com' in source_url or 'youtu.be' in source_url:
            st.markdown(f"📺 [Video auf YouTube ansehen]({source_url})")
        elif 'tagesschau.de' in source_url:
            st.markdown(f"🎙️ [Tagesschau Beitrag öffnen]({source_url})")
        else:
            st.markdown(f"📄 [Artikel lesen]({source_url})")
    
    total_questions = len(quiz['questions'])
    
    # Prüfe Quiz-Modus (gespeichert in Session State oder aus Quiz-Daten)
    current_quiz_mode = st.session_state.get('current_quiz_mode', 'Multiple Choice')
    
    # Quiz-Formular
    with st.form("quiz_form"):
        for i, q in enumerate(quiz['questions']):
            st.markdown(f"---")
            st.write(f"**Frage {i+1}:** {q['question']}")
            st.caption(f"Schwierigkeit: {'⭐' * q.get('difficulty', 1)}")
            
            options = q.get('options', [])
            
            if current_quiz_mode == "Freitext" or not options:
                # Freitext-Modus: Text-Eingabe
                user_input = st.text_input(
                    f"Deine Antwort:",
                    key=f"q_{i}",
                    placeholder="Tippe deine Antwort..."
                )
                st.session_state.user_answers[i] = user_input
            else:
                # Multiple Choice: Radio Buttons
                selected = st.radio(
                    f"Wähle eine Antwort:",
                    options=options,
                    key=f"q_{i}",
                    index=None,
                    label_visibility="collapsed"
                )
                st.session_state.user_answers[i] = selected
        
        submitted = st.form_submit_button("📊 Quiz auswerten", type="primary")
    
    # Ergebnisse
    if submitted:
        st.session_state.submitted = True
    
    if st.session_state.submitted:
        st.markdown("---")
        st.subheader("📊 Ergebnis")
        
        score = 0
        for i, q in enumerate(quiz['questions']):
            user_answer = st.session_state.user_answers.get(i)
            correct_answer = q.get('correct_answer')
            
            # Für Freitext: Fuzzy Matching
            is_correct = False
            description=""
            if user_answer and correct_answer:
                if current_quiz_mode == "Freitext" or not q.get('options'):
                    gen = generator.QuizGenerator(api_key=api_key, provider= provider, model=model)
                    print(api_key)
                    print(provider)
                    print(model)
                    result = gen.validate_answer(q.get('question'),  user_answer, q.get('correct_answer'))
                    print(result)
                    is_correct = result.get('answer_is_correct')
                    description=result.get('description')
                    print(result)
                    # Fuzzy Match für Freitext
                    ##from difflib import SequenceMatcher
                    #u#ser_normalized = user_answer.lower().strip()
                    #correct_normalized = correct_answer.lower().strip()
                    
                    # Exakte Übereinstimmung oder hohe Ähnlichkeit (>70%)
                    #ratio = SequenceMatcher(None, user_normalized, correct_normalized).ratio()
                    #is_correct = (ratio >= 0.7) or (user_normalized in correct_normalized) or (correct_normalized in user_normalized)
                else:
                    # Multiple Choice: Exakte Übereinstimmung
                    is_correct = (user_answer == correct_answer)
            
            if is_correct:
                score += 1
                st.success(f"✅ Frage {i+1}: Richtig!")
            else:
                if current_quiz_mode == "Freitext" or not q.get('options'):
                    st.error(f"❌ Frage {i+1}: Nicht ganz. Richtige Antwort: **{correct_answer}** (Deine: {user_answer}) {description}")
                else:
                    st.error(f"❌ Frage {i+1}: Falsch. Richtige Antwort: **{correct_answer}**")
        
        percentage = (score / total_questions) * 100 if total_questions > 0 else 0
        st.markdown(f"### Dein Ergebnis: **{score}/{total_questions}** ({percentage:.0f}%)")
        
        if percentage >= 80:
            st.balloons()
            st.success("🎉 Hervorragend!")
        elif percentage >= 50:
            st.info("👍 Gut gemacht!")
        else:
            st.warning("📚 Lies den Artikel nochmal!")
        
        # Leaderboard: Versuch speichern und Ranking anzeigen
        # Nur speichern wenn noch nicht für diese Session gespeichert
        if not st.session_state.get('attempt_saved', False):
            quiz_id = quiz.get('id', 0)
            database.save_quiz_attempt(quiz_id, score, total_questions)
            st.session_state.attempt_saved = True
        
        # Leaderboard-Statistiken anzeigen
        ranking = database.get_user_ranking(percentage)
        stats = database.get_leaderboard_stats()
        
        st.markdown("---")
        st.subheader("🏆 Dein Ranking")
        
        # Hauptranking-Anzeige
        if stats['total_attempts'] > 1:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    label="Besser als",
                    value=f"{ranking['better_than_percent']:.0f}%",
                    delta=ranking['rank_label']
                )
            with col2:
                st.metric(
                    label="Durchschnitt aller Spieler",
                    value=f"{stats['average_percentage']:.0f}%"
                )
            with col3:
                st.metric(
                    label="Anzahl Versuche",
                    value=f"{stats['total_attempts']}"
                )
            
            # Motivierende Nachricht
            if ranking['better_than_percent'] >= 75:
                st.success(f"🌟 **{ranking['rank_label']}** Du gehörst zu den besten Spielern!")
            elif ranking['better_than_percent'] >= 50:
                st.info(f"📈 **{ranking['rank_label']}** Du liegst über dem Durchschnitt von {stats['average_percentage']:.0f}%!")
            else:
                st.info(f"💪 **{ranking['rank_label']}** Der Durchschnitt liegt bei {stats['average_percentage']:.0f}%. Versuch's nochmal!")
        else:
            st.info("🎉 **Erster Versuch gespeichert!** Spiele mehr Quizze um dein Ranking zu sehen.")
        
        # Validierungs-Anzeige
        if st.session_state.get('validation'):
            validation = st.session_state.validation
            st.markdown("---")
            
            # Farbcodierung basierend auf Risiko
            if validation['hallucination_risk'] == 'low':
                box_color = "✅"
                box_type = st.success
            elif validation['hallucination_risk'] == 'medium':
                box_color = "⚠️"
                box_type = st.warning
            else:
                box_color = "❌"
                box_type = st.error
            
            box_type(f"{box_color} **Validierung:** {validation['valid_count']}/{validation['total_count']} Antworten im Quelltext gefunden | Halluzinationsrisiko: **{validation['hallucination_risk_label']}**")
            
            # Detaillierte Analyse im Expander
            with st.expander("🔍 Detaillierte Validierungs-Analyse"):
                for idx, q_val in enumerate(validation['questions']):
                    status_icon = "✅" if q_val['is_valid'] else "⚠️"
                    st.markdown(f"**Frage {idx+1}:** {status_icon}")
                    st.write(f"*{q_val['question']}*")
                    
                    if q_val['correct_answer_validation']:
                        match_info = q_val['correct_answer_validation']
                        confidence = match_info['confidence'] * 100
                        st.write(f"→ Korrekte Antwort: **{q_val['correct_answer']}**")
                        st.write(f"→ Match-Typ: `{match_info['match_type']}` | Konfidenz: {confidence:.0f}%")
                        st.write(f"→ {match_info['details']}")
                        
                        # Zeige Zitat aus dem Originaltext
                        if match_info.get('matched_context'):
                            st.markdown(f"> 📖 *\"{match_info['matched_context']}\"*")
                    st.markdown("---")

    # Untere Buttons
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Dieses Quiz löschen", use_container_width=True):
            # Lösche nur dieses spezifische Quiz
            quiz_id = quiz.get('id')
            if quiz_id:
                database.delete_quiz_by_id(quiz_id)
            st.session_state.submitted = False
            st.session_state.user_answers = {}
            st.session_state.attempt_saved = False
            st.rerun()
    with col2:
        if st.button("🔄 Neues Quiz", use_container_width=True):
            # Nicht löschen - Session nur zurücksetzen für neues Quiz
            st.session_state.submitted = False
            st.session_state.user_answers = {}
            st.session_state.attempt_saved = False
            
            # Prüfe ob letztes Quiz aus Upload war
            if st.session_state.get('last_source_type') == 'upload' and st.session_state.get('last_upload_content'):
                # Generiere neues Quiz aus gespeichertem Upload-Content
                content = st.session_state.last_upload_content
                title = st.session_state.get('last_upload_title', 'Hochgeladene Datei')
                
                with st.status(f"Generiere neues Quiz für '{title}'...", expanded=True) as status:
                    video_data = {"id": "upload_regenerated", "title": title, "url": ""}
                    
                    if process_and_save_quiz(content, video_data, api_key, provider, model, status, quiz_mode=st.session_state.get('current_quiz_mode', 'Multiple Choice')):
                         pass # Erfolgreich, kein rerun hier nötig da es unten passiert
                    else:
                        st.warning("Konnte kein Quiz generieren.")
            else:
                # Setze Flag zum Neugenerieren aus ausgewählter Quelle
                st.session_state.regenerate_quiz = True
            
            st.rerun()
            
    # Debug-Log Viewer
    st.markdown("---")
    with st.expander("🛠️ Debug-Logs & Details", expanded=False):
        st.write("Hier kannst du sehen, was im Hintergrund passiert ist (z.B. warum Fragen aussortiert wurden).")
        if os.path.exists("debug.log"):
            try:
                with open("debug.log", "r", encoding="utf-8") as f:
                    logs = f.readlines()
                    # Zeige die letzten 100 Zeilen
                    st.code("".join(logs[-100:]), language="text")
                
                if st.button("🗑️ Logs löschen"):
                    with open("debug.log", "w", encoding="utf-8") as f:
                        f.write("")
                    st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Lesen der Logs: {e}")
        else:
            st.info("Noch keine Logs verfügbar.")

if __name__ == "__main__":
    main()
