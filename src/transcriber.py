"""
Transkriptions-Modul mit faster-whisper für lokale Speech-to-Text.
Unterstützt das Herunterladen und Transkribieren von Videos aus der ARD Mediathek.
Inklusive Caching für bereits transkribierte Videos.
"""

import os
import re
import logging
import tempfile
import subprocess
import hashlib
import requests
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Cache-Verzeichnis für Transkriptionen
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "transcripts_cache")

# Globale Whisper-Model Instanz (wird beim ersten Aufruf geladen)
_whisper_model = None
_whisper_model_name = "small"  # Optionen: tiny, base, small, medium, large-v2


def get_cache_path(url: str) -> str:
    """Generiert einen eindeutigen Cache-Pfad für eine URL."""
    # Erstelle Hash aus URL für eindeutigen Dateinamen
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    # Extrahiere Video-ID für lesbaren Namen
    video_id_match = re.search(r'video-(\d+)', url)
    video_id = video_id_match.group(1) if video_id_match else url_hash
    
    return os.path.join(CACHE_DIR, f"transcript_{video_id}_{url_hash}.txt")


def load_cached_transcript(url: str) -> Optional[str]:
    """Lädt eine gecachte Transkription falls vorhanden."""
    cache_path = get_cache_path(url)
    
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                transcript = f.read()
            if transcript and len(transcript) > 100:
                logger.info(f"Transkription aus Cache geladen: {os.path.basename(cache_path)}")
                return transcript
        except Exception as e:
            logger.warning(f"Fehler beim Laden des Cache: {e}")
    
    return None


def save_transcript_to_cache(url: str, transcript: str) -> bool:
    """Speichert eine Transkription im Cache."""
    if not transcript or len(transcript) < 100:
        return False
    
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = get_cache_path(url)
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(transcript)
        
        logger.info(f"Transkription gecached: {os.path.basename(cache_path)}")
        return True
    except Exception as e:
        logger.warning(f"Fehler beim Speichern des Cache: {e}")
        return False


def get_whisper_model(model_name: str = None):
    """
    Lädt das Whisper-Modell (cached für wiederholte Aufrufe).
    """
    global _whisper_model, _whisper_model_name
    
    if model_name:
        _whisper_model_name = model_name
    
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            
            logger.info(f"Lade Whisper-Modell '{_whisper_model_name}'...")
            
            # Versuche GPU zu nutzen, fallback auf CPU
            use_gpu = False
            try:
                import torch
                if torch.cuda.is_available():
                    # Teste ob CUDA wirklich funktioniert
                    torch.zeros(1).cuda()
                    use_gpu = True
            except Exception as e:
                logger.warning(f"CUDA nicht verfügbar: {e}")
            
            if use_gpu:
                try:
                    _whisper_model = WhisperModel(
                        _whisper_model_name, 
                        device="cuda", 
                        compute_type="float16"
                    )
                    logger.info("Whisper läuft auf GPU (CUDA)")
                except Exception as e:
                    logger.warning(f"GPU-Initialisierung fehlgeschlagen: {e}")
                    use_gpu = False
            
            if not use_gpu:
                _whisper_model = WhisperModel(
                    _whisper_model_name, 
                    device="cpu", 
                    compute_type="int8"
                )
                logger.info("Whisper läuft auf CPU")
                
        except ImportError:
            logger.error("faster-whisper nicht installiert. Bitte 'pip install faster-whisper' ausführen.")
            return None
    
    return _whisper_model


def is_tagesschau_media_url(url: str) -> bool:
    """
    Prüft ob eine URL eine Tagesschau Mediathek Audio- oder Video-Seite ist.
    Erkennt Patterns wie: tagesschau.de/.../audio-*.html oder video-*.html
    """
    if not url or 'tagesschau.de' not in url:
        return False
    return bool(re.search(r'tagesschau\.de/.*/(audio|video)-\d+', url))


def extract_tagesschau_media_url(page_url: str) -> Optional[tuple]:
    """
    Extrahiert die direkte Media-URL (MP4 oder MP3) aus einer Tagesschau-Seite.
    
    Returns:
        Tuple (url, media_type) wobei media_type 'video' oder 'audio' ist,
        oder None wenn keine Media-URL gefunden wurde.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(page_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        html_content = response.text
        
        # Suche nach MP4 URLs (Video)
        mp4_urls = re.findall(r'https?://[^\s"\'<>]+\.mp4(?:[^\s"\'<>]*)?', html_content)
        
        if mp4_urls:
            # Bereinige URL (entferne HTML-Entities)
            clean_url = mp4_urls[0].replace('&quot;', '').replace('&amp;', '&')
            # Bevorzuge höhere Qualität (webxxl > webl > webm > webs)
            for quality in ['webxxl', 'webl', 'webm', 'webs']:
                for url in mp4_urls:
                    if quality in url:
                        return (url.replace('&quot;', '').replace('&amp;', '&'), 'video')
            return (clean_url, 'video')
        
        # Suche nach MP3 URLs (Audio/Podcast)
        mp3_urls = re.findall(r'https?://[^\s"\'<>]+\.mp3(?:[^\s"\'<>]*)?', html_content)
        
        if mp3_urls:
            clean_url = mp3_urls[0].replace('&quot;', '').replace('&amp;', '&')
            logger.info(f"MP3-URL gefunden: {clean_url[:80]}...")
            return (clean_url, 'audio')
        
        # Fallback: Suche in JSON-LD nach contentUrl
        json_ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>([^<]+)</script>', html_content)
        if json_ld_match:
            import json
            try:
                ld_data = json.loads(json_ld_match.group(1))
                content_url = ld_data.get('contentUrl', '')
                if content_url:
                    if '.mp4' in content_url:
                        return (content_url, 'video')
                    elif '.mp3' in content_url:
                        return (content_url, 'audio')
            except json.JSONDecodeError:
                pass
        
        return None
        
    except Exception as e:
        logger.error(f"Fehler beim Extrahieren der Media-URL: {e}")
        return None


def download_video_direct(url: str, output_path: str) -> bool:
    """
    Lädt eine Video-Datei direkt per HTTP herunter.
    """
    try:
        logger.info(f"Lade Video herunter: {url[:80]}...")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, stream=True, timeout=300)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        file_size = os.path.getsize(output_path)
        logger.info(f"Video heruntergeladen: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Fehler beim Video-Download: {e}")
        return False


def download_video_audio(url: str, output_dir: str = None) -> Optional[str]:
    """
    Lädt Audio/Video von einer URL herunter.
    Unterstützt Tagesschau direkt und YouTube via yt-dlp.
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()
    
    safe_name = re.sub(r'[^\w\-]', '_', url[-30:])
    
    # Spezialbehandlung für Tagesschau
    if 'tagesschau.de' in url:
        logger.info("Erkenne Tagesschau-URL, extrahiere Media-Stream...")
        media_result = extract_tagesschau_media_url(url)
        
        if media_result:
            media_url, media_type = media_result
            ext = 'mp4' if media_type == 'video' else 'mp3'
            output_path = os.path.join(output_dir, f"{media_type}_{safe_name}.{ext}")
            if download_video_direct(media_url, output_path):
                return output_path
        else:
            logger.error("Konnte keine Media-URL aus Tagesschau-Seite extrahieren")
        return None
    
    # Für andere URLs: versuche yt-dlp
    output_path = os.path.join(output_dir, f"audio_{safe_name}")
    
    try:
        logger.info(f"Lade Audio von {url[:50]} via yt-dlp...")
        
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", f"{output_path}.%(ext)s",
            "--no-playlist",
            "--quiet",
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            logger.error(f"yt-dlp Fehler: {result.stderr}")
            return None
        
        for ext in ['mp3', 'wav', 'm4a', 'webm', 'opus']:
            full_path = f"{output_path}.{ext}"
            if os.path.exists(full_path):
                return full_path
        
        return None
        
    except Exception as e:
        logger.error(f"Fehler beim Audio-Download: {e}")
        return None


def transcribe_audio(audio_path: str, language: str = "de") -> Optional[str]:
    """
    Transkribiert eine Audio/Video-Datei mit faster-whisper.
    """
    model = get_whisper_model()
    if model is None:
        return None
    
    try:
        logger.info(f"Transkribiere {os.path.basename(audio_path)}...")
        
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        
        full_text = " ".join(text_parts)
        
        logger.info(f"Transkription abgeschlossen: {len(full_text)} Zeichen")
        return full_text
        
    except Exception as e:
        logger.error(f"Fehler bei Transkription: {e}")
        return None


def transcribe_video_url(url: str, language: str = "de", cleanup: bool = True) -> Optional[str]:
    """
    Lädt ein Video herunter und transkribiert es.
    Nutzt Cache für bereits transkribierte Videos.
    """
    # Prüfe zuerst den Cache
    cached_transcript = load_cached_transcript(url)
    if cached_transcript:
        return cached_transcript
    
    media_path = None
    
    try:
        media_path = download_video_audio(url)
        if media_path is None:
            return None
        
        transcript = transcribe_audio(media_path, language)
        
        # Speichere erfolgreiche Transkription im Cache
        if transcript and len(transcript) > 100:
            save_transcript_to_cache(url, transcript)
        
        return transcript
        
    finally:
        if cleanup and media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
                logger.info(f"Temporäre Datei gelöscht")
            except:
                pass


def is_transcription_available() -> bool:
    """Prüft ob die Transkriptions-Funktionalität verfügbar ist."""
    try:
        import faster_whisper
        return True
    except:
        return False


# =============================================================================
# DATEI-UPLOAD FUNKTIONEN
# =============================================================================

def extract_text_from_pdf(file_path: str) -> Optional[str]:
    """
    Extrahiert Text aus einer PDF-Datei.
    """
    try:
        import fitz  # PyMuPDF
        
        logger.info(f"Extrahiere Text aus PDF: {os.path.basename(file_path)}")
        
        doc = fitz.open(file_path)
        text_parts = []
        
        for page in doc:
            text_parts.append(page.get_text())
        
        doc.close()
        
        full_text = "\n".join(text_parts)
        logger.info(f"PDF-Extraktion erfolgreich: {len(full_text)} Zeichen")
        return full_text.strip()
        
    except ImportError:
        logger.error("PyMuPDF nicht installiert. Bitte 'pip install PyMuPDF' ausführen.")
        return None
    except Exception as e:
        logger.error(f"Fehler beim Extrahieren aus PDF: {e}")
        return None


def extract_text_from_docx(file_path: str) -> Optional[str]:
    """
    Extrahiert Text aus einer DOCX-Datei.
    """
    try:
        from docx import Document
        
        logger.info(f"Extrahiere Text aus DOCX: {os.path.basename(file_path)}")
        
        doc = Document(file_path)
        text_parts = []
        
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)
        
        full_text = "\n".join(text_parts)
        logger.info(f"DOCX-Extraktion erfolgreich: {len(full_text)} Zeichen")
        return full_text.strip()
        
    except ImportError:
        logger.error("python-docx nicht installiert. Bitte 'pip install python-docx' ausführen.")
        return None
    except Exception as e:
        logger.error(f"Fehler beim Extrahieren aus DOCX: {e}")
        return None


def extract_text_from_txt(file_path: str) -> Optional[str]:
    """
    Liest Text aus einer TXT-Datei.
    """
    try:
        logger.info(f"Lese TXT-Datei: {os.path.basename(file_path)}")
        
        # Versuche verschiedene Encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    text = f.read()
                logger.info(f"TXT gelesen ({encoding}): {len(text)} Zeichen")
                return text.strip()
            except UnicodeDecodeError:
                continue
        
        logger.error("Konnte TXT-Datei mit keinem Encoding lesen")
        return None
        
    except Exception as e:
        logger.error(f"Fehler beim Lesen der TXT-Datei: {e}")
        return None


def transcribe_local_video(file_path: str, language: str = "de") -> Optional[str]:
    """
    Transkribiert eine lokale Video-/Audio-Datei.
    """
    if not is_transcription_available():
        logger.error("faster-whisper nicht verfügbar")
        return None
    
    try:
        logger.info(f"Transkribiere lokale Datei: {os.path.basename(file_path)}")
        return transcribe_audio(file_path, language)
        
    except Exception as e:
        logger.error(f"Fehler bei lokaler Transkription: {e}")
        return None


def process_uploaded_file(file_path: str, file_type: str, language: str = "de") -> Optional[str]:
    """
    Verarbeitet eine hochgeladene Datei und extrahiert den Text.
    
    Args:
        file_path: Pfad zur hochgeladenen Datei
        file_type: Dateityp ('pdf', 'docx', 'txt', 'video')
        language: Sprache für Video-Transkription
    
    Returns:
        Extrahierter Text oder None
    """
    file_type = file_type.lower()
    
    if file_type == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_type == 'docx':
        return extract_text_from_docx(file_path)
    elif file_type == 'txt':
        return extract_text_from_txt(file_path)
    elif file_type in ['video', 'mp4', 'mp3', 'wav', 'webm', 'm4a', 'ogg']:
        return transcribe_local_video(file_path, language)
    else:
        logger.error(f"Unbekannter Dateityp: {file_type}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Tagesschau Transkription Test ===\n")
    print("Prüfe Verfügbarkeit...")
    
    if is_transcription_available():
        print("✅ faster-whisper verfügbar")
        
        test_url = "https://www.tagesschau.de/video/video-1544010.html"
        print(f"\nTest-URL: {test_url}")
        
        # Teste erst die Video-Extraktion
        print("\n1. Extrahiere Video-URL...")
        video_url_data = extract_tagesschau_media_url(test_url)
        if video_url_data:
            video_url, _ = video_url_data
            print(f"   ✅ Video-URL gefunden: {video_url[:80]}...")
        else:
            print("   ❌ Keine Video-URL gefunden")
            exit(1)
        
        print("\n2. Starte Transkription (dies kann einige Minuten dauern)...")
        text = transcribe_video_url(test_url)
        
        if text:
            print(f"\n✅ Transkription erfolgreich ({len(text)} Zeichen):")
            print("-" * 50)
            print(text[:800] + "..." if len(text) > 800 else text)
        else:
            print("❌ Transkription fehlgeschlagen")
    else:
        print("❌ faster-whisper nicht verfügbar")
        print("Bitte installieren: pip install faster-whisper")
