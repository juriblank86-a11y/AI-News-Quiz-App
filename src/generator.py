import os
import json
import logging
from openai import OpenAI
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Anbieter-Konstanten
PROVIDER_OPENAI = "openai"
PROVIDER_GROQ = "groq"
PROVIDER_OLLAMA = "ollama"
PROVIDER_LMSTUDIO = "lmstudio"

# Standard-Endpunkte
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
LMSTUDIO_BASE_URL = "http://localhost:1234/v1"

# Standard-Modelle pro Anbieter
DEFAULT_MODELS = {
    PROVIDER_OPENAI: "gpt-3.5-turbo",
    PROVIDER_GROQ: "llama-3.3-70b-versatile",
    PROVIDER_OLLAMA: "llama3.2",
    PROVIDER_LMSTUDIO: "local-model",
}

providers = [
    {
        "name":"Groq (Cloud, schnell)",
        "key": "groq",
        "api_key_required": True,
        "url": "https://api.groq.com/openai/v1",
        "default_model":"llama-3.3-70b-versatile"
    },
    {
        "name":"Ollama (Lokal)",
        "key": "ollama",
        "api_key_required": False,
        "url": "http://localhost:11434/v1",
        "default_model":"llama3.2"
    },
    {
        "name":"LM Studio (Lokal)",
        "key": "lmstudio",
        "api_key_required": False,
        "url": "http://localhost:1234/v1",
        "default_model":"local-model"
    }
    
]

class QuizGenerator:
    def __init__(self, api_key=None, provider=None, base_url=None, model=None):
        """
        Initialisiert den QuizGenerator mit flexibler Anbieter-Unterstützung.
        
        Args:
            api_key: API-Schlüssel (nicht benötigt für Ollama/LM Studio)
            provider: Einer von 'openai', 'groq', 'ollama', 'lmstudio'
            base_url: Benutzerdefinierte Basis-URL (optional, automatisch pro Anbieter)
            model: Modellname (optional, nutzt Anbieter-Standard)
        """
        key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
        
        # Erkenne Anbieter automatisch anhand des Schlüssels
        if not provider:
            if key and key.startswith("gsk_"):
                provider = PROVIDER_GROQ
            elif key and key.startswith("sk-"):
                provider = PROVIDER_OPENAI
            else:
                # Standard: OpenAI-kompatibel
                provider = PROVIDER_OPENAI
        
        self.provider = provider
                
        # Setze Modell
        self.model = model or DEFAULT_MODELS.get(provider, "gpt-3.5-turbo")
        
        # Konfiguration basierend auf Anbieter               
        if provider == PROVIDER_GROQ:
            self.client = OpenAI(api_key=key, base_url=base_url or GROQ_BASE_URL)
            logger.info(f"Nutze Groq ({self.model})")
            
        elif provider == PROVIDER_OLLAMA:
            # Ollama benötigt keinen API-Schlüssel
            self.client = OpenAI(api_key="ollama", base_url=base_url or OLLAMA_BASE_URL)
            logger.info(f"Nutze Ollama (lokal) ({self.model})")
            
        elif provider == PROVIDER_LMSTUDIO:
            # LM Studio benötigt keinen API-Schlüssel
            self.client = OpenAI(api_key="lm-studio", base_url=base_url or LMSTUDIO_BASE_URL)
            logger.info(f"Nutze LM Studio (lokal) ({self.model})")
            
        else:
            # Standard OpenAI
            self.client = OpenAI(api_key=key, base_url=base_url)
            logger.info(f"Nutze OpenAI ({self.model})")

    def generate_quiz(self, text: str, num_questions: int = 5, language: str = "German", quiz_mode: str = "Multiple Choice") -> List[Dict]:
        """
        Generiert Quiz-Fragen aus dem gegebenen Text.
        
        Args:
            text: Der Quelltext
            num_questions: Anzahl der Fragen
            language: Sprache für Fragen und Antworten
            quiz_mode: "Multiple Choice" oder "Freitext"
            
        Gibt eine Liste von Dicts zurück.
        """
        context_text = text[:8000]
        
        # DEBUG: Log which mode is being used
        logger.info(f"=== GENERATOR: quiz_mode='{quiz_mode}' ===")
        
        if quiz_mode == "Freitext":
            logger.info(">>> NUTZE FREITEXT PROMPT (keine Optionen)")
            # Freitext Modus: Kurze faktische Antworten
            prompt = f"""
            You are a quiz generator creating FREE TEXT questions (no options).
            Based on the following news text, generate {num_questions} unique questions.
            
            IMPORTANT: All questions and answers MUST be in {language}.
            
            Constraints:
            1. Each question must have a SHORT, factual answer (1-5 words max).
            2. The answer should be directly found in or derivable from the text.
            3. Questions should ask for specific facts: names, numbers, places, dates.
            4. Provide a difficulty score from 1 (easy) to 5 (hard).
            5. Output MUST be valid JSON with a "questions" key containing a list of objects.
            6. Each object must have: "question", "correct_answer" (short text), "difficulty".
            
            Example format:
            {{"questions": [
                {{
                    "question": "Wer hat die Initiative vorgestellt?",
                    "correct_answer": "Olaf Scholz",
                    "difficulty": 2
                }},
                {{
                    "question": "Wie viel Euro sollen investiert werden?",
                    "correct_answer": "100 Milliarden",
                    "difficulty": 3
                }}
            ]}}
            
            News Text:
            {context_text}
            
            Output JSON:
            """
        else:
            logger.info(">>> NUTZE MULTIPLE CHOICE PROMPT (mit Optionen)")
            # Multiple Choice Modus (Standard)
            prompt = f"""
            You are a quiz generator creating MULTIPLE CHOICE questions.
            Based on the following news text, generate {num_questions} unique questions.
            
            IMPORTANT: All questions and answer options MUST be in {language}.
            
            Constraints:
            1. Each question must have exactly 4 answer options (A, B, C, D).
            2. One option must be the correct answer.
            3. The correct answer should be based on information from the text.
            4. Wrong options should be plausible but clearly incorrect based on the text.
            5. Provide a difficulty score from 1 (easy) to 5 (hard).
            6. Output MUST be valid JSON with a "questions" key containing a list of objects.
            7. Each object must have: "question", "options" (list of 4 strings), "correct_answer" (the correct option text), "difficulty".
            
            Example format:
            {{"questions": [
                {{
                    "question": "Example Question in {language}?",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_answer": "Option B",
                    "difficulty": 2
                }}
            ]}}
            
            News Text:
            {context_text}
            
            Output JSON:
            """

        try:
            # OpenAI-kompatible API (funktioniert für OpenAI, Groq, Ollama, LM Studio)
            messages = [
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ]
            
            # Groq und OpenAI unterstützen response_format, Ollama/LM Studio möglicherweise nicht
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
            }
            
            if self.provider in [PROVIDER_OPENAI, PROVIDER_GROQ]:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            
            # Behandle leere Antwort
            if not content or not content.strip():
                logger.error("LLM lieferte leere Antwort")
                return []
            
            # Logge erste 200 Zeichen für Debugging
            logger.debug(f"LLM Antwort (erste 200 Zeichen): {content[:200]}")
            
            # Versuche JSON aus Markdown-Codeblöcken zu extrahieren
            content = content.strip()
            if content.startswith("```"):
                # Entferne Markdown-Codeblock-Markierungen
                lines = content.split("\n")
                # Entferne erste Zeile (```json oder ```) und letzte Zeile (```)
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            
            data = json.loads(content)
            
            # Behandle verschiedene JSON-Strukturen
            questions = data.get("questions", data)
            if isinstance(questions, list):
                valid_questions = self._validate_questions(questions, text)
                return valid_questions
            else:
                logger.error("JSON Struktur ungültig (keine Liste)")
                return []

        except json.JSONDecodeError as e:
            logger.error(f"Ungültiges JSON vom LLM: {e}")
            logger.error(f"Antwort-Inhalt: {content[:500] if content else 'LEER'}")
            return []
        except Exception as e:
            logger.error(f"Fehler beim Aufruf des LLM: {e}")
            return []
    def validate_answer(self,question:str,  user_answer:str, correct_answer:str):
        prompt = f"""
            Dies ist ein Quiz. Die Frage lautete: "{question}".
            Die korrekte Muster-Antwort wäre: "{correct_answer}".
            Der Quizteilnehmer antwortete "{user_answer}".
            Kann diese Antwort als korrekt angesegen werden? Antworte im JSON-Format. 
            In "answer_is_correct" soll True für korrekte und "False" für falsche Antwort und in "description" soll im Falle einer falschen Antwort eine kurze Richtigstellung ausgegeben werden.
            Beispiel:
            {{
                "answer_is_correct": "True",
                "description":""
            }}
        """

        try:
            # OpenAI-kompatible API (funktioniert für OpenAI, Groq, Ollama, LM Studio)
            messages = [
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ]
            
            # Groq und OpenAI unterstützen response_format, Ollama/LM Studio möglicherweise nicht
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
            }
            
            if self.provider in [PROVIDER_OPENAI, PROVIDER_GROQ]:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            
            # Behandle leere Antwort
            if not content or not content.strip():
                logger.error("LLM lieferte leere Antwort")
                return []
            
            # Logge erste 200 Zeichen für Debugging
            logger.debug(f"LLM Antwort (erste 200 Zeichen): {content[:200]}")
            
            # Versuche JSON aus Markdown-Codeblöcken zu extrahieren
            content = content.strip()
            if content.startswith("```"):
                # Entferne Markdown-Codeblock-Markierungen
                lines = content.split("\n")
                # Entferne erste Zeile (```json oder ```) und letzte Zeile (```)
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            
            data = json.loads(content)        
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Ungültiges JSON vom LLM: {e}")
            logger.error(f"Antwort-Inhalt: {content[:500] if content else 'LEER'}")
            return []
        except Exception as e:
            logger.error(f"Fehler beim Aufruf des LLM: {e}")
            return []

    def _validate_questions(self, questions: List[Dict], text: str) -> List[Dict]:
        """
        Validiert Fragen. Unterstützt beide Modi:
        - Multiple-Choice: Muss 4 Optionen und correct_answer in options haben
        - Freitext: Muss nur question und correct_answer haben
        """
        validated = []
        for q in questions:
            # Prüfe erforderliche Felder (gemeinsam)
            if not q.get("question"):
                logger.warning("Frage verworfen: Feld 'question' fehlt")
                continue
            if not q.get("correct_answer"):
                logger.warning(f"Frage '{q.get('question')}' verworfen: Feld 'correct_answer' fehlt")
                continue
            
            # Prüfe ob Multiple-Choice oder Freitext
            has_options = q.get("options") and len(q.get("options", [])) >= 2
            
            if has_options:
                # Multiple-Choice Validierung
                if len(q.get("options", [])) != 4:
                    logger.warning(f"Frage '{q.get('question')[:50]}...' verworfen: Muss genau 4 Antwortmöglichkeiten haben (hat {len(q.get('options', []))})")
                    continue
                if q.get("correct_answer") not in q.get("options", []):
                    logger.warning(f"Frage '{q.get('question')[:50]}...' verworfen: Korrekte Antwort nicht in den Optionen enthalten")
                    continue
            else:
                # Freitext: Nur basic checks, kein options check
                logger.info(f"Freitext-Frage akzeptiert: '{q.get('question')[:50]}...' -> '{q.get('correct_answer')}'")
            
            validated.append(q)
        
        logger.info(f"Validierung: {len(validated)}/{len(questions)} Fragen akzeptiert")
        return validated

    def translate_text(self, text: str, target_language: str) -> str:
        """
        Übersetzt einen Text in die Zielsprache.
        Genutzt für Validierung bei Fremdsprachen.
        """
        prompt = f"""
        Translate the following news text into {target_language}.
        Maintain the original meaning and key facts exactly.
        Output ONLY the translated text, no explanation.
        
        Text:
        {text[:4000]}
        """
        
        try:
            messages = [
                {"role": "system", "content": "You are a professional translator."},
                {"role": "user", "content": prompt}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Fehler bei Übersetzung: {e}")
            return text  # Fallback auf Originaltext


def filter_duplicate_questions(new_questions: List[Dict], existing_questions: List[str], 
                                threshold: float = 0.7) -> List[Dict]:
    """
    Filtert Fragen heraus, die zu ähnlich zu bereits existierenden Fragen sind.
    
    Args:
        new_questions: Liste neuer generierter Fragen
        existing_questions: Liste aller bisherigen Fragetexte aus der Datenbank
        threshold: Ähnlichkeitsschwelle (0.7 = 70% Ähnlichkeit)
    
    Returns:
        Liste der Fragen die NICHT als Duplikate erkannt wurden
    """
    from difflib import SequenceMatcher
    
    if not existing_questions:
        return new_questions
    
    unique_questions = []
    
    for q in new_questions:
        question_text = q.get('question', '').lower().strip()
        is_duplicate = False
        
        for existing in existing_questions:
            existing_text = existing.lower().strip()
            
            # Berechne Ähnlichkeit
            similarity = SequenceMatcher(None, question_text, existing_text).ratio()
            
            if similarity >= threshold:
                logger.info(f"Duplikat gefunden ({similarity*100:.0f}% ähnlich): '{question_text[:50]}...'")
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_questions.append(q)
    
    filtered_count = len(new_questions) - len(unique_questions)
    if filtered_count > 0:
        logger.info(f"{filtered_count} Duplikat-Fragen herausgefiltert")
    
    return unique_questions


    




if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_text = "Der Bundeskanzler Olaf Scholz hat heute in Berlin eine neue Initiative angekündigt."
    gen = QuizGenerator(api_key="sk-dummy")
    print("Generator init done.")

