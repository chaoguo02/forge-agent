"""Parse JSON from LLM text responses.

Claude Code pattern: native tool_use blocks exclusively, zero regex JSON extraction.
For non-Anthropic backends without native tool_use, this module provides a single
fallback JSON parser — consolidated from the 3 previously independent copies.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Strips ```json / ``` markers that some models wrap around structured output.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*")

# Fallback: find the first { or [ block in the response.
_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def parse_llm_json(raw: str, default: Any = None) -> Any:
    """Extract structured JSON from an LLM text response.

    1. Strip ```json / ``` fences
    2. Try json.loads()
    3. Fall back to regex extraction of the first JSON-like block
    4. Return *default* if all extraction fails
    """
    text = raw.strip()
    # Strip markdown code fences
    text = _JSON_FENCE_RE.sub("", text)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            return json.loads(match.group(1))
        return default
