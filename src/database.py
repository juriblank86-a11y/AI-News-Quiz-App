import sqlite3
import datetime
import json
from typing import List, Dict, Any

DB_NAME = "news_quiz.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    """Initialisiert die Datenbanktabellen."""
    conn = get_connection()
    c = conn.cursor()
    
    # Quizzes-Tabelle (alle Quizze werden dauerhaft gespeichert)
    # Bereinigt: Keine Validierungs-Metriken mehr, da wir strikt filtern
    c.execute('''
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_str TEXT,
            video_id TEXT,
            video_title TEXT,
            source_url TEXT,
            transcript_text TEXT,
            cache_path TEXT,
            created_at TEXT
        )
    ''')
    
    # Fragen-Tabelle (mit Validierung pro Frage)
    # Bereinigt: is_validated entfernt (implizit immer True)
    c.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            question TEXT,
            answer TEXT,
            options TEXT,
            correct_answer TEXT,
            difficulty INTEGER,
            match_type TEXT,
            confidence REAL,
            FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
        )
    ''')
    
    # Quiz-Versuche Tabelle (NEU: für Leaderboard/Statistiken)
    c.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            score INTEGER,
            total_questions INTEGER,
            percentage REAL,
            completed_at TEXT,
            FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
        )
    ''')
    
    # Migrationen (nur noch relevante)
    try:
        c.execute("ALTER TABLE quizzes ADD COLUMN cache_path TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE quizzes ADD COLUMN created_at TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE quizzes ADD COLUMN source_url TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE questions ADD COLUMN match_type TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE questions ADD COLUMN confidence REAL")
    except: pass
    
    conn.commit()
    conn.close()

def save_quiz(video_data: Dict, transcript: str, questions: List[Dict], 
              validation: Dict = None, cache_path: str = None) -> int:
    """
    Speichert ein generiertes Quiz in der Datenbank.
    Alle Fragen sind nun strikt validiert, daher speichern wir keine Validierungs-Metriken mehr.
    
    Returns:
        quiz_id: Die ID des gespeicherten Quiz, oder 0 bei Fehler
    """
    date_str = datetime.date.today().isoformat()
    created_at = datetime.datetime.now().isoformat()
    
    # Extrahiere Source URL aus video_data
    source_url = video_data.get('url', video_data.get('link', ''))
    
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute('''
            INSERT INTO quizzes (date_str, video_id, video_title, source_url, transcript_text, 
                                cache_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (date_str, video_data['id'], video_data['title'], source_url, transcript,
              cache_path, created_at))
        
        quiz_id = c.lastrowid
        
        # Speichere Fragen
        for i, q in enumerate(questions):
            options_json = json.dumps(q.get('options', []))
            
            # Hole Detail-Infos für diese Frage (match_type, confidence) falls vorhanden
            match_type = None
            confidence = None
            
            if validation and 'questions' in validation and i < len(validation['questions']):
                q_val = validation['questions'][i]
                if q_val.get('correct_answer_validation'):
                    match_info = q_val['correct_answer_validation']
                    match_type = match_info.get('match_type')
                    confidence = match_info.get('confidence', 0)
            
            c.execute('''
                INSERT INTO questions (quiz_id, question, answer, options, correct_answer, 
                                      difficulty, match_type, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (quiz_id, q['question'], q.get('answer', ''), options_json, 
                  q.get('correct_answer', ''), q.get('difficulty', 1),
                  match_type, confidence))
            
        conn.commit()
        return quiz_id
    except Exception as e:
        print(f"DB Error: {e}")
        return 0
    finally:
        conn.close()

def get_daily_quiz(date_str: str = None) -> Dict[str, Any]:
    """
    Ruft das neueste Quiz ab.
    Falls date_str angegeben, wird das neueste Quiz für dieses Datum geholt,
    sonst das allerneueste Quiz.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if date_str:
        c.execute("SELECT * FROM quizzes WHERE date_str = ? ORDER BY id DESC LIMIT 1", (date_str,))
    else:
        # Hole das allerneueste Quiz
        c.execute("SELECT * FROM quizzes ORDER BY id DESC LIMIT 1")
    
    quiz_row = c.fetchone()
    
    if not quiz_row:
        conn.close()
        return None
        
    quiz_data = dict(quiz_row)
    
    c.execute("SELECT * FROM questions WHERE quiz_id = ?", (quiz_row['id'],))
    questions = []
    for row in c.fetchall():
        q = dict(row)
        # Parse Optionen aus JSON
        if q.get('options'):
            try:
                q['options'] = json.loads(q['options'])
            except:
                q['options'] = []
        questions.append(q)
    
    quiz_data['questions'] = questions
    conn.close()
    
    return quiz_data

def get_quiz_by_id(quiz_id: int) -> Dict[str, Any]:
    """
    Ruft ein spezifisches Quiz anhand seiner ID ab.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
    quiz_row = c.fetchone()
    
    if not quiz_row:
        conn.close()
        return None
        
    quiz_data = dict(quiz_row)
    
    c.execute("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,))
    questions = []
    for row in c.fetchall():
        q = dict(row)
        # Parse Optionen aus JSON
        if q.get('options'):
            try:
                q['options'] = json.loads(q['options'])
            except:
                q['options'] = []
        questions.append(q)
    
    quiz_data['questions'] = questions
    conn.close()
    
    return quiz_data

# Alias für Klarheit
get_latest_quiz = get_daily_quiz

def get_quiz_history(limit: int = 10) -> List[Dict]:
    """Ruft die Historie der letzten Quizze ab."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''
        SELECT id, date_str, video_title, created_at
        FROM quizzes 
        ORDER BY date_str DESC 
        LIMIT ?
    ''', (limit,))
    
    history = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return history

def delete_quiz_by_id(quiz_id: int) -> bool:
    """Löscht ein spezifisches Quiz anhand seiner ID."""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Lösche zuerst die Fragen
        c.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
        # Lösche das Quiz
        c.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"DB Delete Error: {e}")
        return False
    finally:
        conn.close()

def delete_daily_quiz(date_str: str = None) -> bool:
    """Löscht das NEUESTE Quiz (für Session-Reset, nicht alle Quizze)."""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Hole das neueste Quiz
        c.execute("SELECT id FROM quizzes ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if row:
            quiz_id = row[0]
            # Lösche zuerst die Fragen
            c.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
            # Lösche das Quiz
            c.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
            conn.commit()
            return True
        return False
    except Exception as e:
        print(f"DB Delete Error: {e}")
        return False
    finally:
        conn.close()


def get_all_question_texts() -> List[str]:
    """
    Gibt alle bisherigen Fragetexte zurück für Duplikat-Check.
    Wird verwendet um zu verhindern, dass gleiche Fragen wiederholt werden.
    """
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT question FROM questions")
    questions = [row[0] for row in c.fetchall()]
    conn.close()
    
    return questions


# =============================================================================
# LEADERBOARD FUNKTIONEN
# =============================================================================

def save_quiz_attempt(quiz_id: int, score: int, total_questions: int) -> bool:
    """
    Speichert einen Quiz-Versuch für die Leaderboard-Statistik.
    
    Args:
        quiz_id: ID des Quizzes
        score: Erreichte Punktzahl
        total_questions: Gesamtanzahl der Fragen
    
    Returns:
        True wenn erfolgreich gespeichert
    """
    percentage = (score / total_questions * 100) if total_questions > 0 else 0
    completed_at = datetime.datetime.now().isoformat()
    
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute('''
            INSERT INTO quiz_attempts (quiz_id, score, total_questions, percentage, completed_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (quiz_id, score, total_questions, percentage, completed_at))
        conn.commit()
        return True
    except Exception as e:
        print(f"DB Error saving attempt: {e}")
        return False
    finally:
        conn.close()


def get_leaderboard_stats() -> Dict[str, Any]:
    """
    Berechnet Leaderboard-Statistiken aus allen bisherigen Quiz-Versuchen.
    
    Returns:
        Dict mit:
        - total_attempts: Gesamtanzahl Versuche
        - average_percentage: Durchschnittliche Prozentzahl
        - median_percentage: Median der Prozentzahlen
        - best_percentage: Beste erreichte Prozentzahl
        - percentiles: Dict mit 25., 50., 75. Perzentil
    """
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Hole alle Prozent-Werte
        c.execute("SELECT percentage FROM quiz_attempts ORDER BY percentage")
        rows = c.fetchall()
        
        if not rows:
            return {
                "total_attempts": 0,
                "average_percentage": 0,
                "median_percentage": 0,
                "best_percentage": 0,
                "percentiles": {"25": 0, "50": 0, "75": 0}
            }
        
        percentages = [row[0] for row in rows]
        n = len(percentages)
        
        # Berechne Statistiken
        avg = sum(percentages) / n
        median = percentages[n // 2] if n % 2 == 1 else (percentages[n // 2 - 1] + percentages[n // 2]) / 2
        best = max(percentages)
        
        # Perzentile
        p25 = percentages[int(n * 0.25)] if n >= 4 else percentages[0]
        p50 = median
        p75 = percentages[int(n * 0.75)] if n >= 4 else percentages[-1]
        
        return {
            "total_attempts": n,
            "average_percentage": round(avg, 1),
            "median_percentage": round(median, 1),
            "best_percentage": round(best, 1),
            "percentiles": {
                "25": round(p25, 1),
                "50": round(p50, 1),
                "75": round(p75, 1)
            }
        }
    finally:
        conn.close()


def get_user_ranking(user_percentage: float) -> Dict[str, Any]:
    """
    Berechnet das Ranking eines Users basierend auf seinem Ergebnis.
    
    Args:
        user_percentage: Die erreichte Prozentzahl des Users
    
    Returns:
        Dict mit:
        - better_than_percent: Prozent der Spieler die schlechter waren
        - rank_position: Position von unten (1 = schlechtester)
        - total_attempts: Gesamtanzahl aller Versuche
        - rank_label: Textuelle Beschreibung (z.B. "Top 10%")
    """
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Zähle Versuche die schlechter waren
        c.execute("SELECT COUNT(*) FROM quiz_attempts WHERE percentage < ?", (user_percentage,))
        worse_count = c.fetchone()[0]
        
        # Gesamtanzahl (inklusive diesem neuen Versuch)
        c.execute("SELECT COUNT(*) FROM quiz_attempts")
        total = c.fetchone()[0]
        
        if total == 0:
            return {
                "better_than_percent": 0,
                "rank_position": 1,
                "total_attempts": 1,
                "rank_label": "Erster Spieler! 🎉"
            }
        
        # Berechne Perzentil (wie viel % waren schlechter)
        better_than = (worse_count / total * 100) if total > 0 else 0
        
        # Bestimme Rang-Label
        if better_than >= 90:
            rank_label = "🏆 Top 10%!"
        elif better_than >= 75:
            rank_label = "🥇 Top 25%!"
        elif better_than >= 50:
            rank_label = "👍 Überdurchschnittlich!"
        elif better_than >= 25:
            rank_label = "📚 Durchschnittlich"
        else:
            rank_label = "💪 Weiter üben!"
        
        return {
            "better_than_percent": round(better_than, 0),
            "rank_position": worse_count + 1,
            "total_attempts": total,
            "rank_label": rank_label
        }
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized with validation and leaderboard support.")

