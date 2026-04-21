from __future__ import annotations

import asyncio
import html
import logging
import random
import re
from typing import Any

import aiohttp

from bot.models import TriviaQuestion

LOGGER = logging.getLogger(__name__)

SUPPORTED_CATEGORIES = [
    "artliterature",
    "language",
    "sciencenature",
    "general",
    "fooddrink",
    "peopleplaces",
    "geography",
    "historyholidays",
    "entertainment",
    "toysgames",
    "music",
    "mathematics",
    "religionmythology",
    "sportsleisure",
]

SUPPORTED_DIFFICULTIES = ["easy", "medium", "hard"]

QUIZAPI_CATEGORY_HINTS: dict[str, list[str]] = {
    "artliterature": ["art", "literature", "poetry", "author", "novel", "painting"],
    "language": ["language", "word", "grammar", "alphabet", "vocabulary", "spelling"],
    "sciencenature": ["science", "biology", "chemistry", "physics", "nature", "planet"],
    "general": ["general", "trivia", "culture", "knowledge"],
    "fooddrink": ["food", "drink", "cooking", "ingredient", "cuisine"],
    "peopleplaces": ["people", "person", "place", "city", "country", "famous"],
    "geography": ["geography", "capital", "country", "ocean", "desert", "mountain"],
    "historyholidays": ["history", "historical", "holiday", "war", "president", "year"],
    "entertainment": ["entertainment", "movie", "film", "tv", "anime", "celebrity"],
    "toysgames": ["games", "toy", "board game", "chess", "puzzle"],
    "music": ["music", "song", "band", "instrument", "composer"],
    "mathematics": ["math", "mathematics", "algebra", "geometry", "equation", "number"],
    "religionmythology": ["religion", "mythology", "myth", "god", "goddess", "norse", "greek"],
    "sportsleisure": ["sports", "soccer", "basketball", "tennis", "olympics", "league"],
}

FALLBACK_QUESTIONS: list[dict[str, str]] = [
    {"category": "general", "question": "What color do you get by mixing blue and yellow?", "answer": "Green"},
    {"category": "general", "question": "How many continents are there on Earth?", "answer": "7"},
    {"category": "general", "question": "What is the largest ocean on Earth?", "answer": "Pacific Ocean"},
    {"category": "historyholidays", "question": "Who was the first President of the United States?", "answer": "George Washington"},
    {"category": "historyholidays", "question": "In which year did World War II end?", "answer": "1945"},
    {"category": "historyholidays", "question": "The pyramids are primarily located in which country?", "answer": "Egypt"},
    {"category": "sciencenature", "question": "What gas do plants absorb from the atmosphere?", "answer": "Carbon dioxide"},
    {"category": "sciencenature", "question": "What is the chemical symbol for gold?", "answer": "Au"},
    {"category": "sciencenature", "question": "What planet is known as the Red Planet?", "answer": "Mars"},
    {"category": "geography", "question": "What is the capital city of Japan?", "answer": "Tokyo"},
    {"category": "geography", "question": "Which desert is the largest hot desert in the world?", "answer": "Sahara"},
    {"category": "geography", "question": "Mount Everest lies on the border of Nepal and which region?", "answer": "Tibet"},
    {"category": "music", "question": "How many strings does a standard guitar typically have?", "answer": "6"},
    {"category": "music", "question": "Which clef is commonly used for higher-pitched instruments?", "answer": "Treble clef"},
    {"category": "sportsleisure", "question": "How many players are on a soccer team on the field at once?", "answer": "11"},
    {"category": "sportsleisure", "question": "In basketball, how many points is a free throw worth?", "answer": "1"},
    {"category": "entertainment", "question": "Which animated studio created 'Spirited Away'?", "answer": "Studio Ghibli"},
    {"category": "entertainment", "question": "What is the name of Sherlock Holmes' friend and assistant?", "answer": "Dr. Watson"},
    {"category": "fooddrink", "question": "What ingredient gives bread its structure and chew?", "answer": "Gluten"},
    {"category": "fooddrink", "question": "Which fruit is known for having seeds on the outside?", "answer": "Strawberry"},
    {"category": "language", "question": "How many letters are in the English alphabet?", "answer": "26"},
    {"category": "language", "question": "What do we call words with opposite meanings?", "answer": "Antonyms"},
    {"category": "toysgames", "question": "In chess, which piece can move in an L-shape?", "answer": "Knight"},
    {"category": "toysgames", "question": "How many sides does a standard six-sided die have?", "answer": "6"},
    {"category": "peopleplaces", "question": "Who painted the Mona Lisa?", "answer": "Leonardo da Vinci"},
    {"category": "peopleplaces", "question": "Which city is known as the City of Love?", "answer": "Paris"},
    {"category": "mathematics", "question": "What is 9 multiplied by 7?", "answer": "63"},
    {"category": "mathematics", "question": "What is the square root of 144?", "answer": "12"},
    {"category": "religionmythology", "question": "In Greek mythology, who is the god of the sea?", "answer": "Poseidon"},
    {"category": "religionmythology", "question": "In Norse mythology, who wields Mjolnir?", "answer": "Thor"},
    {"category": "artliterature", "question": "Who wrote 'Romeo and Juliet'?", "answer": "William Shakespeare"},
    {"category": "artliterature", "question": "What is the art style that uses tiny dots of color?", "answer": "Pointillism"},
]

CATEGORY_DISTRACTORS: dict[str, list[str]] = {
    "general": [
        "Red",
        "Orange",
        "Purple",
        "Atlantic Ocean",
        "Indian Ocean",
        "Europe",
        "Africa",
        "Pacific Ocean",
    ],
    "sciencenature": [
        "Nitrogen",
        "Oxygen",
        "Hydrogen",
        "Venus",
        "Jupiter",
        "Silver",
        "Iron",
        "Neptune",
    ],
    "geography": [
        "Seoul",
        "Bangkok",
        "Atlantic Ocean",
        "Gobi Desert",
        "Andes",
        "Rome",
        "Canberra",
        "Sahara",
    ],
    "historyholidays": [
        "1918",
        "1939",
        "1969",
        "Thomas Jefferson",
        "Abraham Lincoln",
        "Greece",
        "Mexico",
        "1945",
    ],
    "entertainment": [
        "Pixar",
        "DreamWorks",
        "Dr. Watson",
        "Studio Ghibli",
        "Frodo",
        "Darth Vader",
        "Hogwarts",
    ],
    "sportsleisure": ["9", "10", "12", "2", "3", "11", "6", "1"],
    "fooddrink": [
        "Yeast",
        "Starch",
        "Banana",
        "Blueberry",
        "Gluten",
        "Tomato",
        "Lemon",
    ],
    "music": ["Bass clef", "Alto clef", "4", "5", "7", "Treble clef", "8"],
    "mathematics": ["54", "56", "64", "10", "11", "13", "72", "81"],
    "toysgames": ["Bishop", "Rook", "Pawn", "4", "8", "10", "Knight"],
    "religionmythology": ["Zeus", "Hades", "Odin", "Loki", "Thor", "Poseidon"],
    "peopleplaces": [
        "Vincent van Gogh",
        "Pablo Picasso",
        "London",
        "Rome",
        "Paris",
        "Leonardo da Vinci",
    ],
    "language": ["Synonyms", "Homonyms", "Vowels", "24", "25", "26", "Antonyms"],
    "artliterature": [
        "Charles Dickens",
        "Jane Austen",
        "Cubism",
        "Impressionism",
        "Pointillism",
        "Mark Twain",
    ],
}

QUESTION_KEYWORD_DISTRACTORS: dict[str, list[str]] = {
    "color": ["Red", "Orange", "Purple", "Brown", "Black", "White"],
    "mixing": ["Red", "Orange", "Purple", "Brown"],
    "ocean": ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean", "Southern Ocean"],
    "continent": ["5", "6", "8", "9"],
    "capital": ["Seoul", "Canberra", "Bangkok", "Rome"],
    "planet": ["Venus", "Jupiter", "Saturn", "Neptune"],
    "desert": ["Gobi Desert", "Kalahari Desert", "Arabian Desert", "Mojave Desert"],
    "president": ["Thomas Jefferson", "Abraham Lincoln", "John Adams", "Theodore Roosevelt"],
    "year": ["1918", "1939", "1944", "1946", "1969"],
    "guitar": ["4", "5", "7", "8"],
    "soccer": ["9", "10", "12", "13"],
    "basketball": ["2", "3", "4"],
}

OPENTDB_CATEGORY_MAP: dict[str, int] = {
    "general": 9,
    "artliterature": 10,
    "language": 9,
    "sciencenature": 17,
    "fooddrink": 9,
    "peopleplaces": 26,
    "geography": 22,
    "historyholidays": 23,
    "entertainment": 11,
    "toysgames": 16,
    "music": 12,
    "mathematics": 19,
    "religionmythology": 20,
    "sportsleisure": 21,
}


class TriviaAPI:
    OPENTDB_URL = "https://opentdb.com/api.php"
    QUIZAPI_URL = "https://quizapi.io/api/v1/questions"

    def __init__(self, *, quizapi_key: str) -> None:
        self.quizapi_key = quizapi_key.strip()
        self._session: aiohttp.ClientSession | None = None
        self._missing_quizapi_key_warned = False

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch_questions(
        self,
        *,
        category: str | None,
        limit: int,
        difficulty: str = "medium",
        exclude_questions: set[str] | None = None,
    ) -> list[TriviaQuestion]:
        clean_limit = max(1, min(30, limit))
        clean_category = self.normalize_category(category)
        clean_difficulty = self.normalize_difficulty(difficulty)
        excluded_keys = {
            self._question_key(text)
            for text in (exclude_questions or set())
            if text and text.strip()
        }

        questions = await self._fetch_opentdb_questions(
            clean_category,
            clean_limit,
            clean_difficulty,
            excluded_keys,
        )

        current_keys = excluded_keys | {self._question_key(q.question) for q in questions}
        if len(questions) < clean_limit and self.quizapi_key:
            needed = clean_limit - len(questions)
            questions.extend(
                await self._fetch_quizapi_questions(
                    clean_category,
                    needed,
                    clean_difficulty,
                    current_keys,
                )
            )
        elif len(questions) < clean_limit and not self._missing_quizapi_key_warned:
            LOGGER.info(
                "QUIZAPI_KEY is missing. Using Open Trivia DB + local fallback only."
            )
            self._missing_quizapi_key_warned = True

        fetched_keys = {self._question_key(q.question) for q in questions}
        if len(questions) < clean_limit:
            needed = clean_limit - len(questions)
            fallback = self._build_fallback_questions(
                clean_category, needed, clean_difficulty, excluded_keys | fetched_keys
            )
            questions.extend(fallback)

        unique: list[TriviaQuestion] = []
        seen: set[str] = set()
        for question in questions:
            key = self._question_key(question.question)
            if key in seen:
                continue
            seen.add(key)
            unique.append(question)
            if len(unique) >= clean_limit:
                break
        return unique[:clean_limit]

    def choose_random_category(self) -> str:
        return random.choice(SUPPORTED_CATEGORIES)

    @staticmethod
    def normalize_category(category: str | None) -> str:
        if not category:
            return "general"
        normalized = category.strip().lower()
        if normalized == "random":
            return "general"
        if normalized not in SUPPORTED_CATEGORIES:
            return "general"
        return normalized

    @staticmethod
    def normalize_difficulty(difficulty: str | None) -> str:
        normalized = (difficulty or "medium").strip().lower()
        if normalized not in SUPPORTED_DIFFICULTIES:
            return "medium"
        return normalized

    async def _session_or_create(
        self, timeout: aiohttp.ClientTimeout
    ) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _fetch_opentdb_questions(
        self,
        category: str,
        limit: int,
        difficulty: str,
        excluded_keys: set[str],
    ) -> list[TriviaQuestion]:
        multiplier = {"easy": 2, "medium": 3, "hard": 4}[difficulty]
        request_limit = max(limit, min(50, limit * multiplier))
        params = {
            "amount": str(request_limit),
            "type": "multiple",
            "difficulty": difficulty,
        }
        mapped_category = OPENTDB_CATEGORY_MAP.get(category)
        if mapped_category is not None:
            params["category"] = str(mapped_category)

        timeout = aiohttp.ClientTimeout(total=10)
        backoff = 1.0
        errors: list[str] = []

        for attempt in range(1, 4):
            try:
                session = await self._session_or_create(timeout)
                async with session.get(self.OPENTDB_URL, params=params) as response:
                    if response.status != 200:
                        body = await response.text()
                        errors.append(f"HTTP {response.status}: {body[:160]}")
                        if attempt < 3:
                            await asyncio.sleep(backoff)
                            backoff *= 1.5
                        continue

                    payload = await response.json()
                    parsed = self._parse_opentdb_payload(
                        payload=payload,
                        requested_category=category,
                        requested_difficulty=difficulty,
                        limit=request_limit,
                        excluded_keys=excluded_keys,
                    )
                    if parsed:
                        return self._select_questions_by_difficulty(
                            parsed, limit, difficulty
                        )
                    errors.append(self._opentdb_empty_reason(payload))
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unexpected Open Trivia DB error")
                errors.append(str(exc))

            if attempt < 3:
                await asyncio.sleep(backoff)
                backoff *= 1.5

        if errors:
            LOGGER.warning("Open Trivia DB failed after retries: %s", " | ".join(errors))
        return []

    def _parse_opentdb_payload(
        self,
        *,
        payload: Any,
        requested_category: str,
        requested_difficulty: str,
        limit: int,
        excluded_keys: set[str],
    ) -> list[TriviaQuestion]:
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []

        parsed: list[TriviaQuestion] = []
        seen: set[str] = set(excluded_keys)

        for item in results:
            if not isinstance(item, dict):
                continue
            question_text = html.unescape(str(item.get("question") or "").strip())
            correct_answer = html.unescape(str(item.get("correct_answer") or "").strip())
            incorrect_answers = item.get("incorrect_answers")
            if (
                not question_text
                or not correct_answer
                or not isinstance(incorrect_answers, list)
            ):
                continue

            qkey = self._question_key(question_text)
            if qkey in seen:
                continue

            wrong: list[str] = []
            wrong_seen: set[str] = {correct_answer.lower()}
            for raw in incorrect_answers:
                candidate = html.unescape(str(raw or "").strip())
                if not candidate:
                    continue
                lowered = candidate.lower()
                if lowered in wrong_seen:
                    continue
                wrong_seen.add(lowered)
                wrong.append(candidate)

            if len(wrong) >= 3:
                options = [correct_answer, wrong[0], wrong[1], wrong[2]]
                random.shuffle(options)
                correct_index = options.index(correct_answer)
            else:
                options, correct_index = self._build_options(
                    question_text=question_text,
                    correct_answer=correct_answer,
                    category=requested_category,
                    difficulty=requested_difficulty,
                    extra_answers=wrong,
                )

            parsed.append(
                TriviaQuestion(
                    question=question_text,
                    correct_answer=correct_answer,
                    options=options,
                    correct_index=correct_index,
                    category=requested_category,
                )
            )
            seen.add(qkey)
            if len(parsed) >= limit:
                break

        return parsed

    async def _fetch_quizapi_questions(
        self,
        category: str,
        limit: int,
        difficulty: str,
        excluded_keys: set[str],
    ) -> list[TriviaQuestion]:
        multiplier = {"easy": 2, "medium": 3, "hard": 4}[difficulty]
        request_limit = max(limit, min(50, limit * multiplier))
        params = {
            "limit": str(request_limit),
            "random": "true",
        }

        timeout = aiohttp.ClientTimeout(total=10)
        headers = {"Authorization": f"Bearer {self.quizapi_key}"}
        backoff = 1.0
        errors: list[str] = []

        for attempt in range(1, 4):
            try:
                session = await self._session_or_create(timeout)
                async with session.get(
                    self.QUIZAPI_URL, params=params, headers=headers
                ) as response:
                    if response.status == 429:
                        retry_after = response.headers.get("Retry-After")
                        retry_seconds = (
                            max(1, int(retry_after)) if retry_after and retry_after.isdigit() else 60
                        )
                        errors.append(f"HTTP 429 (retry after {retry_seconds}s)")
                        if attempt < 3:
                            await asyncio.sleep(min(5.0, float(retry_seconds)))
                        continue

                    if response.status != 200:
                        body = await response.text()
                        errors.append(f"HTTP {response.status}: {body[:160]}")
                        if attempt < 3:
                            await asyncio.sleep(backoff)
                            backoff *= 1.5
                        continue

                    payload = await response.json()
                    parsed = self._parse_quizapi_payload(
                        payload=payload,
                        requested_category=category,
                        requested_difficulty=difficulty,
                        limit=request_limit,
                        excluded_keys=excluded_keys,
                    )
                    if parsed:
                        return self._select_questions_by_difficulty(
                            parsed, limit, difficulty
                        )
                    errors.append(self._quizapi_empty_reason(payload))
                    # Empty-but-valid payloads are not transient; retrying won't help.
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unexpected QuizAPI error")
                errors.append(str(exc))

            if attempt < 3:
                await asyncio.sleep(backoff)
                backoff *= 1.5

        if errors:
            LOGGER.warning("QuizAPI failed after retries: %s", " | ".join(errors))
        return []

    def _parse_quizapi_payload(
        self,
        *,
        payload: Any,
        requested_category: str,
        requested_difficulty: str,
        limit: int,
        excluded_keys: set[str],
    ) -> list[TriviaQuestion]:
        if isinstance(payload, dict):
            raw_items = payload.get("data")
            if not isinstance(raw_items, list):
                raw_items = payload.get("results")
            if not isinstance(raw_items, list):
                return []
        elif isinstance(payload, list):
            raw_items = payload
        else:
            return []

        parsed: list[tuple[int, TriviaQuestion]] = []
        seen: set[str] = set(excluded_keys)

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            question_text = str(item.get("text") or item.get("question") or "").strip()
            if not question_text:
                continue

            question_key = self._question_key(question_text)
            if question_key in seen:
                continue

            options, correct_index = self._extract_quizapi_options(item)
            if len(options) < 2 or correct_index < 0:
                continue

            raw_category = self._extract_textish_value(item.get("category"))
            tags = item.get("tags")
            tag_values: list[str] = []
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str):
                        tag_values.append(tag)
                    elif isinstance(tag, dict):
                        name = self._extract_textish_value(
                            tag.get("name") or tag.get("label") or tag.get("value")
                        )
                        if name:
                            tag_values.append(name)
            quiz_title = str(item.get("quizTitle") or item.get("quiz_title") or "").strip()

            relevance = self._quizapi_relevance_score(
                requested_category=requested_category,
                question_text=question_text,
                raw_category=raw_category,
                tags=tag_values,
                quiz_title=quiz_title,
            )
            if requested_category != "general" and relevance < 2:
                continue

            # QuizAPI categories don't map 1:1 with our domain categories;
            # keep user-selected category for consistent UX.
            normalized_category = requested_category

            answer_text = options[correct_index]
            question = TriviaQuestion(
                question=question_text,
                correct_answer=answer_text,
                options=options,
                correct_index=correct_index,
                category=normalized_category,
            )
            seen.add(question_key)

            difficulty_score = self._difficulty_score(question_text, answer_text)
            target = {"easy": 25, "medium": 50, "hard": 75}[requested_difficulty]
            closeness = abs(difficulty_score - target)
            ranking = (relevance * 100) - closeness
            parsed.append((ranking, question))

            if len(parsed) >= limit * 2:
                break

        parsed.sort(key=lambda item: item[0], reverse=True)
        return [question for _, question in parsed[:limit]]

    def _extract_quizapi_options(self, item: dict[str, Any]) -> tuple[list[str], int]:
        # New QuizAPI format: answers = [{text, isCorrect}, ...]
        answers = item.get("answers")
        if isinstance(answers, list):
            return self._extract_quizapi_new_format_options(answers)

        # Legacy QuizAPI format:
        # answers = {"answer_a": "...", ...}
        # correct_answers = {"answer_a_correct": "true", ...}
        if isinstance(answers, dict):
            return self._extract_quizapi_legacy_options(item)

        # Alternate format:
        # options = ["...", "..."]
        # correct_answer = "..." or 1-based/0-based index
        options = item.get("options")
        if isinstance(options, list):
            return self._extract_quizapi_alt_options(item)

        return [], -1

    def _extract_quizapi_new_format_options(
        self, answers: list[Any]
    ) -> tuple[list[str], int]:
        options: list[str] = []
        correct_indices: list[int] = []

        for answer in answers:
            if not isinstance(answer, dict):
                continue
            text = str(answer.get("text") or "").strip()
            if not text:
                continue
            if text.lower() in {opt.lower() for opt in options}:
                continue
            options.append(text)
            flag = answer.get("isCorrect", answer.get("is_correct"))
            if self._to_bool(flag):
                correct_indices.append(len(options) - 1)

        if not options or not correct_indices:
            return [], -1

        correct_index = correct_indices[0]
        if len(options) > 4:
            selected = [options[correct_index]]
            remaining = [opt for idx, opt in enumerate(options) if idx != correct_index]
            random.shuffle(remaining)
            selected.extend(remaining[:3])
            random.shuffle(selected)
            return selected, selected.index(options[correct_index])

        return options, correct_index

    def _extract_quizapi_legacy_options(
        self, item: dict[str, Any]
    ) -> tuple[list[str], int]:
        answers = item.get("answers")
        correct_map = item.get("correct_answers")
        if not isinstance(answers, dict):
            return [], -1

        normalized_correct_key = str(item.get("correct_answer") or "").strip().lower()
        pairs: list[tuple[str, bool]] = []
        for key, value in answers.items():
            if not isinstance(key, str):
                continue
            text = self._extract_textish_value(value)
            if not text:
                continue
            flag_key = f"{key}_correct"
            is_correct = False
            if isinstance(correct_map, dict):
                is_correct = self._to_bool(correct_map.get(flag_key))
            if not is_correct and normalized_correct_key:
                is_correct = normalized_correct_key == key.strip().lower()
            pairs.append((text, is_correct))

        if not pairs:
            return [], -1

        options: list[str] = []
        correct_text: str | None = None
        for text, is_correct in pairs:
            if text.lower() in {x.lower() for x in options}:
                continue
            options.append(text)
            if is_correct and correct_text is None:
                correct_text = text

        if correct_text is None:
            return [], -1

        if len(options) > 4:
            selected = [correct_text]
            remaining = [opt for opt in options if opt.lower() != correct_text.lower()]
            random.shuffle(remaining)
            selected.extend(remaining[:3])
            random.shuffle(selected)
            return selected, selected.index(correct_text)

        for idx, text in enumerate(options):
            if text.lower() == correct_text.lower():
                return options, idx
        return [], -1

    def _extract_quizapi_alt_options(
        self, item: dict[str, Any]
    ) -> tuple[list[str], int]:
        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            return [], -1

        options: list[str] = []
        for option in raw_options:
            text = str(option or "").strip()
            if not text:
                continue
            if text.lower() in {opt.lower() for opt in options}:
                continue
            options.append(text)

        if len(options) < 2:
            return [], -1

        raw_correct = item.get("correct_answer", item.get("correctAnswer"))
        if raw_correct is None:
            return [], -1

        if isinstance(raw_correct, int):
            if 0 <= raw_correct < len(options):
                return options, raw_correct
            one_based = raw_correct - 1
            if 0 <= one_based < len(options):
                return options, one_based
            return [], -1

        correct_text = str(raw_correct).strip()
        if correct_text.isdigit():
            idx = int(correct_text)
            if 0 <= idx < len(options):
                return options, idx
            one_based = idx - 1
            if 0 <= one_based < len(options):
                return options, one_based
        for idx, option in enumerate(options):
            if option.lower() == correct_text.lower():
                return options, idx
        return [], -1

    def _quizapi_relevance_score(
        self,
        *,
        requested_category: str,
        question_text: str,
        raw_category: str,
        tags: list[str],
        quiz_title: str,
    ) -> int:
        keywords = QUIZAPI_CATEGORY_HINTS.get(requested_category, [])
        if not keywords:
            return 0

        metadata_haystack = " ".join([raw_category, quiz_title, " ".join(tags)]).lower()
        question_haystack = question_text.lower()
        metadata_hits = self._keyword_hits(metadata_haystack, keywords)
        question_hits = self._keyword_hits(question_haystack, keywords)

        if requested_category == "general":
            # In general mode, keep broader availability.
            return max(metadata_hits, question_hits, 1)

        # For category-specific rounds, require meaningful evidence that the
        # question actually belongs to the selected category.
        if metadata_hits == 0 and question_hits < 2:
            return 0
        return (metadata_hits * 3) + question_hits

    def _keyword_hits(self, haystack: str, keywords: list[str]) -> int:
        hits = 0
        for keyword in keywords:
            pattern = rf"\b{re.escape(keyword.lower())}\b"
            if re.search(pattern, haystack):
                hits += 1
        return hits

    def _extract_textish_value(self, raw: Any) -> str:
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            for key in ("name", "title", "label", "value"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return str(raw).strip()
        if raw is None:
            return ""
        return str(raw).strip()

    def _to_bool(self, raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return False
        return str(raw).strip().lower() in {"1", "true", "yes", "y"}

    def _quizapi_empty_reason(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return f"QuizAPI returned no usable questions: {value.strip()[:180]}"
            keys = list(payload.keys())
            if keys:
                return f"QuizAPI returned no usable questions (payload keys: {', '.join(keys[:8])})"
        if isinstance(payload, list):
            return f"QuizAPI returned {len(payload)} item(s), none parseable for this quiz mode."
        return "QuizAPI returned empty/unsupported payload."

    def _opentdb_empty_reason(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "Open Trivia DB returned unsupported payload."
        response_code = payload.get("response_code")
        reasons = {
            1: "No results for the selected query.",
            2: "Invalid query parameters.",
            3: "Session token not found.",
            4: "Session token exhausted.",
        }
        if isinstance(response_code, int):
            if response_code == 0:
                return "Open Trivia DB returned zero parseable questions."
            return f"Open Trivia DB response_code={response_code}: {reasons.get(response_code, 'Unknown error')}"
        return "Open Trivia DB returned no usable questions."

    def _build_fallback_questions(
        self,
        category: str,
        limit: int,
        difficulty: str,
        excluded_keys: set[str],
    ) -> list[TriviaQuestion]:
        if limit <= 0:
            return []

        def rank_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
            scored = sorted(
                items,
                key=lambda item: self._difficulty_score(item["question"], item["answer"]),
            )
            if difficulty == "hard":
                return list(reversed(scored))
            if difficulty == "medium":
                return sorted(
                    scored,
                    key=lambda item: abs(
                        self._difficulty_score(item["question"], item["answer"]) - 50
                    ),
                )
            return scored

        filtered = [
            item
            for item in FALLBACK_QUESTIONS
            if self.normalize_category(item["category"]) == category
            and self._question_key(item["question"]) not in excluded_keys
        ]
        picks: list[dict[str, str]] = rank_items(filtered)[:limit]
        used_keys = {self._question_key(item["question"]) for item in picks}

        if len(picks) < limit:
            if category == "general":
                broader_pool = [
                    item
                    for item in FALLBACK_QUESTIONS
                    if self._question_key(item["question"]) not in excluded_keys
                    and self._question_key(item["question"]) not in used_keys
                ]
                extra = rank_items(broader_pool)[: limit - len(picks)]
                picks.extend(extra)
            else:
                LOGGER.info(
                    "Fallback pool has only %s question(s) for category '%s'.",
                    len(picks),
                    category,
                )

        fallback: list[TriviaQuestion] = []
        for item in picks:
            options, correct_index = self._build_options(
                question_text=item["question"],
                correct_answer=item["answer"],
                category=self.normalize_category(item["category"]),
                difficulty=difficulty,
            )
            fallback.append(
                TriviaQuestion(
                    question=item["question"],
                    correct_answer=item["answer"],
                    options=options,
                    correct_index=correct_index,
                    category=self.normalize_category(item["category"]),
                )
            )
        return fallback

    def _build_options(
        self,
        *,
        question_text: str,
        correct_answer: str,
        category: str,
        difficulty: str = "medium",
        extra_answers: list[str] | None = None,
    ) -> tuple[list[str], int]:
        cleaned_correct = correct_answer.strip()
        answer_kind = self._answer_kind(cleaned_correct)
        question_lower = question_text.strip().lower()
        distractors: list[str] = []
        seen: set[str] = {cleaned_correct.lower()}

        def add_candidates(candidates: list[str]) -> None:
            for raw in candidates:
                candidate = self._clean_candidate(raw)
                if not candidate:
                    continue
                key = candidate.lower()
                if key in seen:
                    continue
                if not self._is_kind_compatible(candidate, cleaned_correct, answer_kind):
                    continue
                seen.add(key)
                distractors.append(candidate)
                if len(distractors) >= 3:
                    return

        keyword_pool: list[str] = []
        for keyword, values in QUESTION_KEYWORD_DISTRACTORS.items():
            if keyword in question_lower:
                keyword_pool.extend(values)
        category_answers = [
            item["answer"]
            for item in FALLBACK_QUESTIONS
            if self.normalize_category(item["category"]) == category
        ]
        random.shuffle(category_answers)

        add_candidates(keyword_pool)
        if difficulty == "hard":
            if len(distractors) < 3 and extra_answers:
                shuffled = [x for x in extra_answers if x]
                random.shuffle(shuffled)
                add_candidates(shuffled)
            if len(distractors) < 3:
                add_candidates(category_answers)
            if len(distractors) < 3:
                add_candidates(CATEGORY_DISTRACTORS.get(category, []))
        else:
            if len(distractors) < 3:
                add_candidates(CATEGORY_DISTRACTORS.get(category, []))
            if len(distractors) < 3:
                add_candidates(category_answers)
            if len(distractors) < 3 and extra_answers:
                shuffled = [x for x in extra_answers if x]
                random.shuffle(shuffled)
                add_candidates(shuffled)

        if len(distractors) < 3:
            all_answers = [item["answer"] for item in FALLBACK_QUESTIONS]
            random.shuffle(all_answers)
            add_candidates(all_answers)

        while len(distractors) < 3:
            synthetic = self._synthetic_option(
                cleaned_correct,
                answer_kind=answer_kind,
                category=category,
                difficulty=difficulty,
            )
            add_candidates([synthetic])

        options = [cleaned_correct, *distractors[:3]]
        random.shuffle(options)
        correct_index = options.index(cleaned_correct)
        return options, correct_index

    def _synthetic_option(
        self,
        correct_answer: str,
        *,
        answer_kind: str,
        category: str,
        difficulty: str,
    ) -> str:
        stripped = correct_answer.strip()
        if answer_kind == "year":
            value = int(stripped)
            if difficulty == "hard":
                delta = random.choice([1, 2, 3, 4])
            elif difficulty == "easy":
                delta = random.choice([8, 10, 20, 30])
            else:
                delta = random.choice([1, 2, 3, 5, 10, 20, 30])
            direction = -1 if random.random() < 0.5 else 1
            return str(value + (direction * delta))

        if answer_kind == "number":
            value = int(stripped)
            if difficulty == "hard":
                delta = random.choice([1, 2, 3])
            elif difficulty == "easy":
                delta = random.choice([5, 7, 10, 12])
            else:
                delta = random.choice([1, 2, 3, 5, 7, 10])
            candidate = value + delta if random.random() > 0.5 else max(0, value - delta)
            return str(candidate)

        if answer_kind == "boolean":
            lowered = stripped.lower()
            if lowered in {"true", "yes"}:
                return "False"
            if lowered in {"false", "no"}:
                return "True"
            return random.choice(["True", "False", "Yes", "No"])

        if answer_kind == "acronym":
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            size = min(5, max(2, len(stripped)))
            return "".join(random.choice(letters) for _ in range(size))

        category_pool = CATEGORY_DISTRACTORS.get(category, [])
        if category_pool:
            for candidate in random.sample(category_pool, k=min(5, len(category_pool))):
                if candidate.lower() != stripped.lower():
                    return candidate

        words = stripped.split()
        if len(words) > 1:
            shuffled = words[:]
            random.shuffle(shuffled)
            candidate = " ".join(shuffled)
            if candidate.lower() != stripped.lower():
                return candidate
        return f"{stripped} Alt"

    def _answer_kind(self, answer: str) -> str:
        stripped = answer.strip()
        lowered = stripped.lower()
        if re.fullmatch(r"\d{4}", stripped) and 1000 <= int(stripped) <= 2100:
            return "year"
        if re.fullmatch(r"\d+", stripped):
            return "number"
        if lowered in {"true", "false", "yes", "no"}:
            return "boolean"
        if re.fullmatch(r"[A-Z]{2,6}", stripped):
            return "acronym"
        if " " in stripped:
            return "phrase"
        return "word"

    def _is_kind_compatible(self, candidate: str, correct_answer: str, answer_kind: str) -> bool:
        if candidate.strip().lower() == correct_answer.strip().lower():
            return False

        if answer_kind in {"year", "number"}:
            return bool(re.fullmatch(r"\d+", candidate.strip()))
        if answer_kind == "boolean":
            return candidate.strip().lower() in {"true", "false", "yes", "no"}
        if answer_kind == "acronym":
            return bool(re.fullmatch(r"[A-Z]{2,6}", candidate.strip()))
        if answer_kind == "phrase":
            return " " in candidate.strip() or len(candidate.strip()) >= 5
        return bool(candidate.strip())

    def _clean_candidate(self, value: str) -> str:
        return " ".join(value.strip().split())

    @staticmethod
    def _question_key(text: str) -> str:
        return " ".join(text.strip().lower().split())

    def _select_questions_by_difficulty(
        self, questions: list[TriviaQuestion], limit: int, difficulty: str
    ) -> list[TriviaQuestion]:
        if len(questions) <= limit:
            return questions

        scored = sorted(
            questions,
            key=lambda q: self._difficulty_score(q.question, q.correct_answer),
        )
        if difficulty == "hard":
            return list(reversed(scored))[:limit]
        if difficulty == "easy":
            return scored[:limit]

        return sorted(
            questions,
            key=lambda q: abs(self._difficulty_score(q.question, q.correct_answer) - 50),
        )[:limit]

    def _difficulty_score(self, question_text: str, answer_text: str) -> int:
        question = " ".join(question_text.strip().split())
        answer = answer_text.strip()
        q_lower = question.lower()

        words = [w for w in re.split(r"\s+", question) if w]
        word_count = len(words)
        avg_word_len = (sum(len(w.strip(".,?!")) for w in words) / word_count) if word_count else 0
        answer_words = [w for w in re.split(r"\s+", answer) if w]

        score = 20
        score += min(30, max(0, (word_count - 6) * 2))
        score += min(12, max(0, int((avg_word_len - 4.5) * 3)))
        score += min(12, max(0, (len(answer_words) - 1) * 4))

        harder_markers = [
            "which of the following",
            "according to",
            "except",
            "least",
            "most",
            "mythology",
            "chemical",
            "symbol",
            "border",
            "primarily",
            "structure",
        ]
        easier_markers = [
            "what color",
            "how many",
            "capital",
            "largest ocean",
            "first president",
            "square root",
        ]
        if any(marker in q_lower for marker in harder_markers):
            score += 10
        if any(marker in q_lower for marker in easier_markers):
            score -= 10

        if re.fullmatch(r"\d+", answer):
            score -= 5

        score = max(0, min(100, score))
        return score
