"""Token estimator for memory injection budget.

Uses tiktoken (cl100k_base) when available; falls back to a fast 4-char-per-token
heuristic when tiktoken is unavailable.  The encoding is deliberately not configurable
— memory injection text is short enough that the exact encoding barely matters as long
as the budget is consistent.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TokenEstimator:
    """Count tokens in text using tiktoken with a fast heuristic fallback."""

    def __init__(self) -> None:
        self._enc = self._load_encoder()
        self._via_heuristic = self._enc is None

    @staticmethod
    def _load_encoder():
        try:
            import tiktoken
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            logger.debug("tiktoken unavailable; using heuristic token estimator")
            return None

    def count(self, text: str) -> int:
        """Return estimated token count for *text*."""
        if not text:
            return 0
        if self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:
                logger.debug("tiktoken encode failed; falling back to heuristic")
        # Heuristic: ~4 characters per token for English/code text
        return max(1, len(text) // 4)

    def header_overhead(self, record_count: int) -> int:
        """Estimated tokens for the injection header/footer for *record_count* records.

        Each injected memory adds a ### header line, a > reason line, the content,
        and a blank separator — roughly 25 tokens of formatting overhead per record
        plus a fixed 30 tokens for the section header.
        """
        if record_count <= 0:
            return 0
        return 30 + record_count * 25


# Module-level convenience
_estimator: TokenEstimator | None = None


def get_estimator() -> TokenEstimator:
    global _estimator
    if _estimator is None:
        _estimator = TokenEstimator()
    return _estimator


def count_tokens(text: str) -> int:
    return get_estimator().count(text)


def injection_overhead(record_count: int) -> int:
    return get_estimator().header_overhead(record_count)
