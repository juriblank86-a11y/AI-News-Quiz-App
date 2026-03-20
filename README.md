# 🧠 AI News Quiz App

## Projektübersicht
Diese Full-Stack KI-Anwendung generiert vollautomatisch interaktive Lern-Quizzes aus beliebigen Inhalten (YouTube-Videos, Web-Artikeln oder lokalen Dokumenten). Das Projekt demonstriert den Aufbau einer kompletten AI-Pipeline: Von der robusten Datenextraktion über intelligentes Prompt-Engineering bis hin zur fortgeschrittenen Halluzinations-Validierung.

## Tech Stack & Features
- **Frontend:** Streamlit (Interaktive UI, State-Management)
- **AI / NLP:** OpenAI API, Faster-Whisper (lokale, ressourcenschonende Audio-Transkription), SpaCy (NLP Tokenizing)
- **Data Engineering:** BeautifulSoup4 (Web-Scraping), yt-dlp, PyMuPDF, `python-docx`
- **Backend/Logik:** Python Modular Architecture (`generator.py`, `validator.py`, `database.py`)

## Kernkomponenten der App

### 1. Multi-Source Ingestion & Caching
Smarte Integration verschiedenster Quellen:
- Direkter Download und lokale Audio-Extraktion von YouTube-Videos.
- Offline-Transkription via lokaler `faster-whisper` Instanz.
- Intelligentes Caching (`transcripts_cache/`) verhindert redundante Downloads und API-Calls.

### 2. LLM Quiz Generator (`generator.py`)
Dynamische Erstellung von Single/Multiple Choice Fragen, Wahr/Falsch-Aussagen sowie Lückentexten, die sich adaptiv an die Länge des extrahierten Kontexts anpassen.

### 3. Hallucination Validator (`validator.py`)
Ein massiver Vorteil gegenüber Standard-LLM-Apps: Das System checkt die durch das LLM generierten Fragen und Fakten automatisch gegen das Original-Transkript gegen. Durch Fuzzy-String-Matching und NLP-Scoring (`rapidfuzz`, `spacy`) werden KI-Halluzinationen minimiert und aussortiert.

### 4. Database Logging (`database.py`)
Persistenzschicht mit SQLite zur Speicherung generierter Quizzes und Token-Logging für Kostenkontrolle.

## Setup & Ausführung
Um das Projekt lokal auszuführen:

1. Erstelle eine `.env` Datei im Stammverzeichnis und füge deinen OpenAI API-Key ein:
   ```env
   OPENAI_API_KEY=sk-...
   ```
2. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
3. Starte die Streamlit App (aus dem Hauptverzeichnis):
   ```bash
   streamlit run src/app.py
   ```

## Business Value (Warum dieses Projekt?)
- **Full-Stack AI:** Zeigt, dass KI nicht nur im Jupyter Notebook genutzt werden kann, sondern als interaktives Produkt.
- **Kostenbewusstsein:** Lokale Transkription ("Whisper") und Caching-Mechanismen reduzieren API-Kosten extrem.
- **Safety First:** Die Implementierung von Faktencheck-Logiken (`validator.py`) behebt eines der größten Probleme aktueller GenAI Apps: Halluzination.
