"""
Validierungsmodul für Quiz-Antworten.
Prüft ob Antworten im Originaltext vorkommen (Halluzinations-Check).
Merge von validator.py und validator_v2.py: Nutzt rapidfuzz + spaCy falls vorhanden, sonst difflib.
"""

import re
import logging
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Optional: rapidfuzz für schnelleres/besseres Fuzzy-Matching
try:
    from rapidfuzz import fuzz
    USE_RAPIDFUZZ = True
    logger.info("RapidFuzz verfügbar - nutze optimiertes Matching")
except ImportError:
    USE_RAPIDFUZZ = False
    logger.info("RapidFuzz nicht installiert - nutze difflib als Fallback")

# Optional: spaCy für Lemmatization und NER
try:
    import spacy
    nlp = spacy.load("de_core_news_sm")
    USE_SPACY = True
    logger.info("spaCy verfügbar - nutze NLP-basierte Validierung")
except (ImportError, OSError):
    USE_SPACY = False
    nlp = None
    logger.info("spaCy nicht installiert - nutze einfache Keyword-Extraktion")


# -------------------------
# Text-Normalisierung
# -------------------------
def normalize_text(text: str) -> str:
    """
    Normalisiert Text für den Vergleich.
    Entfernt Satzzeichen, macht alles lowercase.
    """
    text = text.lower()
    text = re.sub(r'[^\w\s\-äöüß]', '', text)
    return ' '.join(text.split())


# -------------------------
# Stoppwörter (Deutsch + International)
# -------------------------
STOPWORDS = {
    'der', 'die', 'das', 'und', 'oder', 'aber', 'dass', 'wenn', 'weil',
    'als', 'war', 'ist', 'sind', 'hat', 'haben', 'wird', 'werden', 'kann',
    'können', 'mit', 'bei', 'von', 'für', 'auf', 'nach', 'vor', 'über',
    'unter', 'eine', 'einer', 'einem', 'ein', 'sich', 'auch', 'noch',
    'nur', 'schon', 'mehr', 'sehr', 'etwa', 'sein',
    # Englisch
    'the', 'and', 'or', 'but', 'that', 'this', 'with', 'for', 'from',
    'have', 'has', 'was', 'were', 'are', 'is', 'can', 'will', 'would'
}


def extract_key_words(text: str, min_length: int = 4) -> set:
    """
    Extrahiert wichtige Schlüsselwörter aus dem Text.
    Nutzt spaCy für Lemmatization falls verfügbar, sonst einfache Wortextraktion.
    """
    if USE_SPACY and nlp:
        doc = nlp(normalize_text(text))
        return {
            token.lemma_
            for token in doc
            if token.is_alpha
            and len(token.lemma_) >= min_length
            and token.lemma_ not in STOPWORDS
        }
    else:
        normalized = normalize_text(text)
        words = normalized.split()
        return {w for w in words if len(w) >= min_length and w not in STOPWORDS}


# -------------------------
# Exact Match (robust mit Wortgrenzen)
# -------------------------
def check_exact_match(answer: str, source_text: str) -> bool:
    """
    Prüft ob die Antwort wörtlich im Quelltext vorkommt.
    Nutzt Wortgrenzen für robustere Erkennung.
    """
    answer_norm = normalize_text(answer)
    source_norm = normalize_text(source_text)
    
    # Wortgrenzen-Pattern für robustere Erkennung
    pattern = r"\b" + re.escape(answer_norm) + r"\b"
    return bool(re.search(pattern, source_norm))


# -------------------------
# Partial Match (Schlüsselwörter)
# -------------------------
def check_partial_match(answer: str, source_text: str, threshold: float = 0.6) -> Tuple[bool, float, set]:
    """
    Prüft ob wichtige Wörter der Antwort im Quelltext vorkommen.
    
    Returns:
        Tuple von (ist_teilmatch, übereinstimmungs_rate, gefundene_wörter)
    """
    answer_words = extract_key_words(answer)
    source_words = extract_key_words(source_text)
    
    if not answer_words:
        return False, 0.0, set()
    
    matches = answer_words.intersection(source_words)
    match_rate = len(matches) / len(answer_words)
    
    return match_rate >= threshold, match_rate, matches


# -------------------------
# Fuzzy Match (RapidFuzz oder difflib)
# -------------------------
def check_fuzzy_match(answer: str, source_text: str, threshold: float = 0.8) -> Tuple[bool, float]:
    """
    Prüft auf ähnliche Textstellen mittels Fuzzy-Matching.
    Nutzt RapidFuzz falls verfügbar, sonst difflib.
    """
    answer_norm = normalize_text(answer)
    source_norm = normalize_text(source_text)
    
    if USE_RAPIDFUZZ:
        # RapidFuzz partial_ratio ist schneller und oft genauer
        score = fuzz.partial_ratio(answer_norm, source_norm)
        return score >= threshold * 100, score / 100.0
    else:
        # Fallback: difflib mit Sliding Window
        answer_len = len(answer_norm)
        best_ratio = 0.0
        
        for i in range(len(source_norm) - answer_len + 1):
            window = source_norm[i:i + answer_len]
            ratio = SequenceMatcher(None, answer_norm, window).ratio()
            best_ratio = max(best_ratio, ratio)
            
            if ratio >= 0.95:
                break
        
        return best_ratio >= threshold, best_ratio


# -------------------------
# Kontextprüfung (Named Entity Recognition)
# -------------------------
def check_named_entities(answer: str, source_text: str) -> bool:
    """
    Prüft ob gleiche benannte Entitäten (Personen, Orte, Organisationen)
    in Antwort und Quelltext vorkommen.
    Nur verfügbar wenn spaCy installiert ist.
    """
    if not USE_SPACY or not nlp:
        return False
    
    answer_doc = nlp(answer)
    source_doc = nlp(source_text[:10000])  # Limitiere für Performance
    
    answer_entities = {(ent.text.lower(), ent.label_) for ent in answer_doc.ents}
    source_entities = {(ent.text.lower(), ent.label_) for ent in source_doc.ents}
    
    return bool(answer_entities.intersection(source_entities))


# -------------------------
# Kontext-Extraktion (Satz mit Antwort)
# -------------------------
def extract_sentence_context(answer: str, source_text: str, context_chars: int = 150) -> str:
    """
    Extrahiert den Satz oder Textabschnitt, in dem die Antwort gefunden wurde.
    
    Returns:
        String mit dem Kontext-Zitat oder leer wenn nicht gefunden.
    """
    answer_lower = answer.lower()
    source_lower = source_text.lower()
    
    # Finde Position der Antwort im Text
    pos = source_lower.find(answer_lower)
    
    if pos == -1:
        # Versuche einzelne wichtige Wörter zu finden
        words = [w for w in answer_lower.split() if len(w) >= 4]
        for word in words:
            pos = source_lower.find(word)
            if pos != -1:
                break
    
    if pos == -1:
        return ""
    
    # Finde Satzgrenzen um die Position
    # Suche nach Satzende vor der Position
    start = max(0, pos - context_chars)
    end = min(len(source_text), pos + len(answer) + context_chars)
    
    # Suche nach Satzbegrenzern
    sentence_delimiters = '.!?\n'
    
    # Finde Satzanfang
    for i in range(pos, start, -1):
        if source_text[i] in sentence_delimiters:
            start = i + 1
            break
    
    # Finde Satzende
    for i in range(pos + len(answer), end):
        if source_text[i] in sentence_delimiters:
            end = i + 1
            break
    
    context = source_text[start:end].strip()
    
    # Kürze wenn zu lang
    if len(context) > 300:
        context = context[:297] + "..."
    
    return context


# -------------------------
# Zentrale Validierung
# -------------------------
def validate_answer(answer: str, source_text: str) -> Dict:
    """
    Validiert eine einzelne Antwort gegen den Quelltext.
    
    Returns:
        Dict mit Validierungsergebnis:
        - match_type: 'exact', 'partial', 'fuzzy', 'context', 'weak', 'none'
        - confidence: 0.0 - 1.0
        - found_in_text: True/False
        - details: Erklärung
    """
    # Kontext extrahieren für Zitat-Anzeige
    context = extract_sentence_context(answer, source_text)
    
    # 1. Exakte Übereinstimmung prüfen
    if check_exact_match(answer, source_text):
        return {
            "match_type": "exact",
            "confidence": 1.0,
            "found_in_text": True,
            "matched_context": context,
            "details": "Antwort kommt wörtlich im Text vor"
        }
    
    # 2. Partielle Übereinstimmung (Schlüsselwörter)
    partial_match, partial_rate, matches = check_partial_match(answer, source_text)
    if partial_match:
        return {
            "match_type": "partial",
            "confidence": partial_rate,
            "found_in_text": True,
            "matched_context": context,
            "matched_keywords": list(matches),
            "details": f"Schlüsselwörter gefunden ({partial_rate*100:.0f}%)"
        }
    
    # 3. Fuzzy-Matching
    fuzzy_match, fuzzy_rate = check_fuzzy_match(answer, source_text)
    if fuzzy_match:
        return {
            "match_type": "fuzzy",
            "confidence": fuzzy_rate,
            "found_in_text": True,
            "matched_context": context,
            "details": f"Ähnliche Textstelle gefunden ({fuzzy_rate*100:.0f}%)"
        }
    
    # 4. Kontextprüfung (Named Entity Recognition) - nur mit spaCy
    if check_named_entities(answer, source_text):
        return {
            "match_type": "context",
            "confidence": 0.5,
            "found_in_text": True,
            "matched_context": context,
            "details": "Gleiche benannte Entitäten im Kontext erkannt"
        }
    
    # 5. Schwache Übereinstimmung
    if partial_rate >= 0.3:
        return {
            "match_type": "weak",
            "confidence": partial_rate,
            "found_in_text": False,
            "details": f"Schwache Übereinstimmung ({partial_rate*100:.0f}%)"
        }
    
    # 6. Keine Übereinstimmung - potentielle Halluzination
    return {
        "match_type": "none",
        "confidence": 0.0,
        "found_in_text": False,
        "details": "Nicht im Text gefunden - mögliche Halluzination"
    }


def validate_question(question: Dict, source_text: str) -> Dict:
    """
    Validiert eine komplette Frage mit allen Antwortoptionen.
    
    Returns:
        Dict mit Validierungsergebnis für die Frage und alle Optionen
    """
    result = {
        "question": question.get("question", ""),
        "correct_answer": question.get("correct_answer", ""),
        "correct_answer_validation": None,
        "options_validation": [],
        "is_valid": False,
        "validation_score": 0.0
    }
    
    # Validiere die korrekte Antwort
    correct = question.get("correct_answer", "")
    if correct:
        result["correct_answer_validation"] = validate_answer(correct, source_text)
        result["is_valid"] = result["correct_answer_validation"]["found_in_text"]
    
    # Validiere alle Optionen
    options = question.get("options", [])
    for option in options:
        validation = validate_answer(option, source_text)
        validation["option"] = option
        validation["is_correct"] = (option == correct)
        result["options_validation"].append(validation)
    
    # Berechne Gesamt-Score
    if result["correct_answer_validation"]:
        result["validation_score"] = result["correct_answer_validation"]["confidence"]
    
    return result


def validate_quiz(questions: List[Dict], source_text: str) -> Dict:
    """
    Validiert ein komplettes Quiz gegen den Quelltext.
    
    Returns:
        Dict mit Gesamtvalidierung:
        - questions: Liste der validierten Fragen
        - valid_count: Anzahl gültiger Fragen
        - total_count: Gesamtanzahl Fragen
        - validation_rate: Prozentsatz gültiger Fragen
        - average_confidence: Durchschnittliche Konfidenz
        - hallucination_risk: 'low', 'medium', 'high'
    """
    validated_questions = []
    valid_count = 0
    total_confidence = 0.0
    
    for q in questions:
        validation = validate_question(q, source_text)
        validated_questions.append(validation)
        
        if validation["is_valid"]:
            valid_count += 1
        total_confidence += validation["validation_score"]
    
    total_count = len(questions)
    validation_rate = (valid_count / total_count * 100) if total_count > 0 else 0
    avg_confidence = (total_confidence / total_count) if total_count > 0 else 0
    
    # Bestimme Halluzinationsrisiko
    if validation_rate >= 80:
        risk = "low"
        risk_label = "Niedrig"
    elif validation_rate >= 50:
        risk = "medium"
        risk_label = "Mittel"
    else:
        risk = "high"
        risk_label = "Hoch"
    
    return {
        "questions": validated_questions,
        "valid_count": valid_count,
        "total_count": total_count,
        "validation_rate": validation_rate,
        "average_confidence": avg_confidence,
        "hallucination_risk": risk,
        "hallucination_risk_label": risk_label
    }


# Für direkte Tests
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print(f"RapidFuzz: {'[OK]' if USE_RAPIDFUZZ else '[NEIN]'}")
    print(f"spaCy: {'[OK]' if USE_SPACY else '[NEIN]'}")
    
    # Test
    test_text = """
    Der Bundeskanzler Olaf Scholz hat heute eine neue Klimaschutz-Initiative vorgestellt.
    Die Maßnahmen sollen bis 2030 umgesetzt werden. Deutschland plant 100 Milliarden Euro
    in erneuerbare Energien zu investieren.
    """
    
    test_question = {
        "question": "Wer hat die Klimaschutz-Initiative vorgestellt?",
        "options": ["Angela Merkel", "Olaf Scholz", "Robert Habeck", "Friedrich Merz"],
        "correct_answer": "Olaf Scholz"
    }
    
    result = validate_question(test_question, test_text)
    print(f"Frage: {result['question']}")
    print(f"Korrekte Antwort: {result['correct_answer']}")
    print(f"Gültig: {result['is_valid']}")
    print(f"Score: {result['validation_score']:.2f}")
    print(f"Details: {result['correct_answer_validation']['details']}")
