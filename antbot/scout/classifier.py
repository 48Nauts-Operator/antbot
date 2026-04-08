"""Document classifier — keyword scan first, optional LLM fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Default classification categories with keywords
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Finance": ["invoice", "receipt", "payment", "tax", "statement", "balance", "due", "amount", "billing", "credit", "debit"],
    "Contracts": ["agreement", "contract", "party", "hereby", "signature", "clause", "termination", "binding", "nda", "confidential"],
    "Technical": ["api", "endpoint", "schema", "architecture", "specification", "protocol", "interface", "documentation", "readme"],
    "Notes": ["notes", "todo", "meeting", "minutes", "agenda", "action items", "memo", "journal"],
    "Data": ["dataset", "export", "records", "rows", "columns", "csv", "data", "analytics", "report"],
    "Medical": ["patient", "diagnosis", "prescription", "lab", "blood", "medical", "health", "doctor"],
    "Travel": ["flight", "booking", "hotel", "itinerary", "boarding", "departure", "arrival", "reservation"],
    "Education": ["course", "certificate", "grade", "transcript", "university", "diploma", "lecture", "assignment"],
}

# LLM classification prompt
CLASSIFY_PROMPT = """Classify this document into exactly one category:
- Finance (invoices, receipts, tax, bank statements)
- Contracts (legal agreements, NDAs, terms)
- Technical (API docs, specs, architecture)
- Notes (personal notes, meeting notes, to-dos)
- Data (datasets, exports, raw data)
- Medical (health records, prescriptions, lab results)
- Travel (bookings, itineraries, boarding passes)
- Education (courses, certificates, transcripts)
- Other (doesn't fit above)

Document text (first 1000 chars):
{text}

Respond with ONLY the category name."""


@dataclass
class ClassifyResult:
    """Result of document classification."""
    category: str
    confidence: float  # 0.0 - 1.0
    method: str  # "keyword" | "llm" | "default"
    keywords_found: list[str] = field(default_factory=list)


class Classifier:
    """Two-pass document classifier: keyword scan → optional LLM fallback."""

    def __init__(
        self,
        categories: dict[str, list[str]] | None = None,
        llm_endpoint: str | None = None,
        llm_privacy: str = "private",
        confidence_threshold: float = 0.3,
    ) -> None:
        self._categories = categories or DEFAULT_CATEGORIES
        self._llm_endpoint = llm_endpoint
        self._llm_privacy = llm_privacy
        self._threshold = confidence_threshold

    def classify_text(self, text: str) -> ClassifyResult:
        """Classify document text using keyword scan."""
        text_lower = text.lower()
        scores: dict[str, tuple[float, list[str]]] = {}

        for category, keywords in self._categories.items():
            found = [kw for kw in keywords if kw in text_lower]
            if found:
                # Score = fraction of category keywords found, weighted by count
                score = len(found) / len(keywords)
                scores[category] = (score, found)

        if not scores:
            return ClassifyResult(category="Unsorted", confidence=0.0, method="default")

        # Pick the category with the highest score
        best_cat = max(scores, key=lambda k: scores[k][0])
        best_score, best_keywords = scores[best_cat]

        if best_score >= self._threshold:
            return ClassifyResult(
                category=best_cat,
                confidence=best_score,
                method="keyword",
                keywords_found=best_keywords,
            )

        # Below threshold — would need LLM, but for now return best guess
        return ClassifyResult(
            category=best_cat,
            confidence=best_score,
            method="keyword",
            keywords_found=best_keywords,
        )

    async def classify_text_llm(self, text: str) -> ClassifyResult:
        """Classify using LLM via NautRouter (optional, requires endpoint)."""
        if not self._llm_endpoint:
            return self.classify_text(text)  # fallback to keywords

        try:
            import httpx

            prompt = CLASSIFY_PROMPT.format(text=text[:1000])
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._llm_endpoint}/chat/completions",
                    headers={
                        "X-Agent-Id": "antbot-classifier",
                        "X-Privacy": self._llm_privacy,
                    },
                    json={
                        "model": "naut/eco",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 20,
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                category = data["choices"][0]["message"]["content"].strip()

                # Validate against known categories
                valid = list(self._categories.keys()) + ["Other"]
                if category not in valid:
                    # Try to match partially
                    for v in valid:
                        if v.lower() in category.lower():
                            category = v
                            break
                    else:
                        category = "Unsorted"

                return ClassifyResult(
                    category=category,
                    confidence=0.8,  # LLM confidence assumed high
                    method="llm",
                )

        except Exception as e:
            logger.warning("LLM classification failed, falling back to keywords: %s", e)
            return self.classify_text(text)

    def classify_file(self, path: str, text_preview: str = "") -> ClassifyResult:
        """Classify a file. Uses text_preview if provided, otherwise extension-based guess."""
        if text_preview:
            return self.classify_text(text_preview)

        # Extension-based fallback
        ext = os.path.splitext(path)[1].lower()
        ext_map = {
            ".pdf": "Unsorted",  # PDFs need content analysis
            ".csv": "Data",
            ".xlsx": "Data",
            ".docx": "Unsorted",  # Word docs need content
            ".md": "Notes",
            ".txt": "Notes",
        }
        category = ext_map.get(ext, "Unsorted")
        return ClassifyResult(category=category, confidence=0.5, method="default")
