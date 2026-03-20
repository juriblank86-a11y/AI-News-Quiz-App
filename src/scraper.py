import logging
import re
import feedparser
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtubesearchpython import VideosSearch, ChannelsSearch, Playlist, playlist_from_channel_id

logger = logging.getLogger(__name__)

# =============================================================================
# NEWS SOURCES CONFIGURATION
# =============================================================================

NEWS_SOURCES = {
    "tagesschau_video": {
        "name": "Tagesschau (Video)",
        "type": "youtube",
        "description": "20-Uhr-Nachrichten als Video"
    },
    "tagesschau_mediathek": {
        "name": "Tagesschau Mediathek",
        "type": "mediathek",
        "url": "https://www.tagesschau.de/multimedia/video/videoarchiv2~_date-{date}.html",
        "description": "Videos aus der ARD Mediathek"
    },
    "tagesschau_channel": {
        "name": "Tagesschau YouTube-Kanal",
        "type": "youtube_channel",
        "channel_handle": "@tagesschau",
        "description": "Alle Videos vom offiziellen YouTube-Kanal"
    },
    "tagesschau": {
        "name": "Tagesschau",
        "type": "rss",
        "url": "https://www.tagesschau.de/xml/rss2/",
        "language": "de"
    },
    "zeit": {
        "name": "Zeit Online",
        "type": "rss",
        "url": "https://newsfeed.zeit.de/all",
        "language": "de"
    },
    "spiegel": {
        "name": "Spiegel",
        "type": "rss",
        "url": "https://www.spiegel.de/schlagzeilen/tops/index.rss",
        "language": "de"
    },
    "euronews": {
        "name": "Euronews",
        "type": "rss",
        "url": "https://www.euronews.com/rss?level=theme&name=news",
        "language": "en"
    },
}


def get_available_sources():
    """Gibt die Liste der verfügbaren Nachrichtenquellen zurück."""
    return [{"id": k, **v} for k, v in NEWS_SOURCES.items()]


# =============================================================================
# YOUTUBE / TAGESSCHAU VIDEO FUNKTIONEN
# =============================================================================

def get_video_id_from_url(url):
    """Extrahiert die Video-ID aus einer YouTube-URL."""
    match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
    if match:
        return match.group(1)
    return None


def find_latest_tagesschau():
    """Findet das neueste 'Tagesschau 20:00 Uhr' Video."""
    videos = find_recent_tagesschau(limit=1)
    return videos[0] if videos else None


def find_recent_tagesschau(limit=15):
    """Findet aktuelle 'Tagesschau 20:00 Uhr' Videos via YouTube-Suche."""
    logger.info(f"Suche nach {limit} aktuellen Tagesschau Videos...")
    # Erhöhe Limit für bessere Abdeckung
    videos_search = VideosSearch('Tagesschau 20 Uhr', limit=limit + 10)
    results = videos_search.result()

    if not results or 'result' not in results:
        return []
    
    found_videos = []
    for video in results['result']:
        title = video['title']
        if "tagesschau" in title.lower() and ("20" in title or "20:00" in title):
            found_videos.append({
                "id": video['id'],
                "title": title,
                "link": video['link'],
                "publishedTime": video.get('publishedTime', 'Unbekannt'),
                "type": "video"
            })
            if len(found_videos) >= limit:
                break
    
    return found_videos


def fetch_youtube_channel_videos(channel_handle="@tagesschau", limit=30):
    """
    Ruft Videos direkt vom Tagesschau YouTube-Kanal ab.
    Nutzt eine Suche nach dem Kanal-Handle für bessere Ergebnisse.
    """
    logger.info(f"Lade Videos vom YouTube-Kanal {channel_handle}...")
    
    try:
        # Suche nach Videos vom Kanal
        search = VideosSearch(f'site:youtube.com/{channel_handle} tagesschau', limit=limit)
        results = search.result()
        
        if not results or 'result' not in results:
            # Fallback: Allgemeine Suche
            search = VideosSearch(f'{channel_handle} tagesschau 20 Uhr', limit=limit)
            results = search.result()
        
        if not results or 'result' not in results:
            return []
        
        videos = []
        for video in results['result']:
            # Filtere auf tagesschau-relevante Videos
            title = video.get('title', '')
            channel = video.get('channel', {}).get('name', '').lower()
            
            if 'tagesschau' in channel or 'tagesschau' in title.lower():
                videos.append({
                    "id": video['id'],
                    "title": title,
                    "link": video['link'],
                    "publishedTime": video.get('publishedTime', 'Unbekannt'),
                    "type": "video"
                })
        
        logger.info(f"{len(videos)} Videos vom Kanal gefunden")
        return videos[:limit]
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Kanal-Videos: {e}")
        return []


def fetch_mediathek_videos(limit=20):
    """
    Scraped die Tagesschau Mediathek/Videoarchiv für aktuelle Videos.
    """
    logger.info("Lade Videos aus der Tagesschau Mediathek...")
    
    videos = []
    
    try:
        # Tagesschau Videoarchiv Seiten
        urls_to_try = [
            "https://www.tagesschau.de/multimedia/sendung/tagesschau_20_uhr",
            "https://www.tagesschau.de/multimedia/video",
            "https://www.tagesschau.de/multimedia/sendung",
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        for base_url in urls_to_try:
            try:
                response = requests.get(base_url, headers=headers, timeout=10)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Suche nach Video-Links - verschiedene Patterns
                video_links = soup.find_all('a', href=re.compile(r'/video/|/multimedia/video/'))
                
                for link in video_links:
                    href = link.get('href', '')
                    
                    # Extrahiere Titel aus verschiedenen Elementen
                    title = ''
                    original_title = ''
                    
                    # Versuche Titel aus verschachtelten Elementen
                    title_elem = link.find(['h2', 'h3', 'h4', 'span', 'p'])
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                    
                    # Fallback: Gesamttext des Links
                    if not title:
                        title = link.get_text(strip=True)
                    
                    original_title = title  # Behalte Original für Fallback
                    
                    # Bereinige Titel (entferne "Video" Prefix und Datum)
                    if title.startswith('Video'):
                        # Versuche den eigentlichen Titel nach dem Datum zu extrahieren
                        # Format: "Video11.01.2026 · 15:00 UhrTitel hier"
                        if 'Uhr' in title:
                            parts = title.split('Uhr', 1)
                            if len(parts) > 1 and parts[1].strip():
                                title = parts[1].strip()
                            else:
                                # Kein Text nach Uhr, behalte Original ohne "Video" Prefix
                                title = original_title[5:].strip() if len(original_title) > 5 else original_title
                        else:
                            title = title[5:].strip()  # Entferne nur "Video"
                    
                    # Fallback: Wenn Titel leer, nutze Video-ID aus URL
                    if not title and href:
                        video_id_match = re.search(r'video-(\d+)', href)
                        if video_id_match:
                            title = f"Tagesschau Video {video_id_match.group(1)}"
                        else:
                            title = f"Video {len(videos)+1}"
                    
                    if href:
                        full_url = f"https://www.tagesschau.de{href}" if href.startswith('/') else href
                        
                        # Prüfe auf Duplikate
                        if not any(v['link'] == full_url for v in videos):
                            videos.append({
                                "id": href,
                                "title": title,
                                "link": full_url,
                                "publishedTime": "Aktuell",
                                "type": "mediathek"
                            })
                
                if len(videos) >= limit:
                    break
                    
            except Exception as e:
                logger.warning(f"Fehler bei {base_url}: {e}")
                continue
        
        logger.info(f"{len(videos)} Videos aus Mediathek gefunden")
        return videos[:limit]
        
    except Exception as e:
        logger.error(f"Fehler beim Mediathek-Scraping: {e}")
        return []


def get_transcript(video_id, preferred_languages=None):
    """
    Holt das Transkript für eine Video-ID.
    Unterstützt mehrere Sprachen mit Fallback.
    
    Args:
        video_id: YouTube Video-ID
        preferred_languages: Liste bevorzugter Sprachen (Standard: ['de', 'en'])
    
    Returns:
        Transkript-Daten oder None
    """
    if preferred_languages is None:
        preferred_languages = ['de', 'en', 'de-DE', 'en-US', 'en-GB']
    
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)
        
        # Versuche bevorzugte Sprachen in Reihenfolge
        for lang in preferred_languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                logger.info(f"Transkript gefunden: {lang}")
                return transcript.fetch()
            except:
                pass
        
        # Versuche generierte Transkripte für bevorzugte Sprachen
        for lang in preferred_languages:
            try:
                transcript = transcript_list.find_generated_transcript([lang])
                logger.info(f"Generiertes Transkript gefunden: {lang}")
                return transcript.fetch()
            except:
                pass
        
        # Letzer Fallback: Nimm das erste verfügbare Transkript
        try:
            available = list(transcript_list)
            if available:
                first_transcript = available[0]
                logger.info(f"Fallback-Transkript verwendet: {first_transcript.language_code}")
                return first_transcript.fetch()
        except Exception as e:
            logger.warning(f"Kein Fallback-Transkript verfügbar: {e}")
        
        logger.error("Kein Transkript gefunden für dieses Video.")
        return None
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Transkripts: {e}")
        return None


def transcript_to_text(transcript_data):
    """Konvertiert die Liste von Transkript-Objekten zu einem einzelnen String."""
    if not transcript_data:
        return ""
    return " ".join([item.text for item in transcript_data])


# =============================================================================
# RSS FEED FUNKTIONEN
# =============================================================================

def fetch_rss_articles(source_id, limit=15):
    """
    Ruft Artikel von einem RSS-Feed ab.
    Gibt eine Liste von Artikel-Dicts zurück mit id, title, link, summary, publishedTime.
    """
    if source_id not in NEWS_SOURCES:
        logger.error(f"Unbekannte Quelle: {source_id}")
        return []
    
    source = NEWS_SOURCES[source_id]
    if source["type"] != "rss":
        logger.error(f"Quelle {source_id} ist kein RSS-Feed")
        return []
    
    logger.info(f"Lade RSS-Feed von {source['name']}...")
    
    try:
        feed = feedparser.parse(source["url"])
        articles = []
        
        for entry in feed.entries[:limit]:
            # Extrahiere Zusammenfassung/Beschreibung
            summary = ""
            if hasattr(entry, 'summary'):
                summary = entry.summary
            elif hasattr(entry, 'description'):
                summary = entry.description
            
            # Entferne HTML aus Zusammenfassung
            if summary:
                soup = BeautifulSoup(summary, 'html.parser')
                summary = soup.get_text()
            
            articles.append({
                "id": entry.get('id', entry.get('link', '')),
                "title": entry.get('title', 'Untitled'),
                "link": entry.get('link', ''),
                "summary": summary[:500] if summary else "",
                "publishedTime": entry.get('published', 'Unknown'),
                "type": "article"
            })
        
        logger.info(f"{len(articles)} Artikel von {source['name']} gefunden")
        return articles
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des RSS-Feeds: {e}")
        return []


def fetch_article_content(url):
    """
    Ruft den vollständigen Textinhalt eines Artikels von seiner URL ab.
    Nutzt BeautifulSoup um Artikel-Text zu extrahieren.
    """
    logger.info(f"Lade Artikelinhalt von {url}...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Entferne Script- und Style-Elemente
        for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
            script.decompose()
        
        # Versuche typische Artikel-Container
        article_selectors = [
            'article',
            '[class*="article-body"]',
            '[class*="article-content"]',
            '[class*="story-body"]',
            '[class*="content-body"]',
            'main',
            '.post-content',
        ]
        
        content = ""
        for selector in article_selectors:
            elements = soup.select(selector)
            if elements:
                content = " ".join([el.get_text() for el in elements])
                break
        
        if not content:
            # Fallback: Hole allen Absatz-Text
            paragraphs = soup.find_all('p')
            content = " ".join([p.get_text() for p in paragraphs])
        
        # Bereinige Leerzeichen
        content = " ".join(content.split())
        
        logger.info(f"{len(content)} Zeichen aus Artikel extrahiert")
        return content
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Artikels: {e}")
        return ""


def fetch_all_articles_combined(source_id: str, limit: int = 20) -> dict:
    """
    Ruft alle Artikel einer Quelle ab und kombiniert deren Inhalt.
    
    Args:
        source_id: ID der Nachrichtenquelle
        limit: Maximale Anzahl der Artikel
    
    Returns:
        Dict mit 'title', 'content' (kombinierter Text), 'count' (Anzahl Artikel)
    """
    logger.info(f"Sammle alle Artikel von {source_id}...")
    
    articles = fetch_rss_articles(source_id, limit=limit)
    
    if not articles:
        return {"title": "", "content": "", "count": 0}
    
    combined_texts = []
    successful_count = 0
    
    for article in articles:
        logger.info(f"Lade Artikel: {article['title'][:50]}...")
        
        # Hole vollständigen Artikelinhalt
        content = fetch_article_content(article['link'])
        
        if content and len(content) > 100:
            # Füge Artikeltitel als Überschrift hinzu
            article_text = f"\n\n=== {article['title']} ===\n\n{content}"
            combined_texts.append(article_text)
            successful_count += 1
        elif article.get('summary') and len(article['summary']) > 50:
            # Fallback auf Summary
            article_text = f"\n\n=== {article['title']} ===\n\n{article['summary']}"
            combined_texts.append(article_text)
            successful_count += 1
    
    combined_content = "\n".join(combined_texts)
    
    # Hole Quellennamen
    source_name = NEWS_SOURCES.get(source_id, {}).get('name', source_id)
    title = f"Alle Artikel von {source_name} ({successful_count} Artikel)"
    
    logger.info(f"Kombiniert: {successful_count} Artikel, {len(combined_content)} Zeichen")
    
    return {
        "title": title,
        "content": combined_content,
        "count": successful_count
    }


# =============================================================================
# EINHEITLICHE CONTENT-FUNKTIONEN
# =============================================================================

def get_content_for_item(item, source_id):
    """
    Holt den vollständigen Textinhalt für ein Element (Video oder Artikel).
    Gibt den Text zurück, der für die Quiz-Generierung geeignet ist.
    """
    item_type = item.get("type", "")
    
    if item_type == "video":
        # YouTube-Video: Transkript abrufen
        transcript_data = get_transcript(item["id"])
        return transcript_to_text(transcript_data)
    
    elif item_type == "mediathek":
        # Mediathek-Video: Versuche lokale Transkription
        try:
            from transcriber import transcribe_video_url, is_transcription_available
            
            if is_transcription_available():
                logger.info("Starte lokale Transkription für Mediathek-Video...")
                transcript = transcribe_video_url(item["link"], language="de")
                if transcript and len(transcript) > 100:
                    logger.info(f"Transkription erfolgreich: {len(transcript)} Zeichen")
                    return transcript
                else:
                    logger.warning("Transkription zu kurz oder fehlgeschlagen")
            else:
                logger.info("Lokale Transkription nicht verfügbar, nutze Web-Scraping")
        except ImportError:
            logger.info("transcriber Modul nicht verfügbar, nutze Web-Scraping")
        except Exception as e:
            logger.warning(f"Transkription fehlgeschlagen: {e}")
        
        # Fallback: Seite scrapen für Beschreibung
        content = fetch_article_content(item["link"])
        if content and len(content) > 50:
            return content
        
        # Letzter Fallback: Titel
        return item.get("title", "")
    
    else:
        # Artikel: Versuche vollständigen Inhalt zu holen
        content = fetch_article_content(item["link"])
        if not content and item.get("summary"):
            content = item["summary"]
        return content


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test RSS
    print("\n=== Testing Tagesschau RSS ===")
    articles = fetch_rss_articles("tagesschau", limit=3)
    for a in articles:
        print(f"- {a['title']}")
    
    print("\n=== Testing Zeit RSS ===")
    articles = fetch_rss_articles("zeit", limit=3)
    for a in articles:
        print(f"- {a['title']}")
