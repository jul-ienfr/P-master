from __future__ import annotations

import html
import re
from typing import Dict, Tuple

UI_PLAYER_NAME_TOKENS = {
    "passer",
    "passe",
    "mettre",
    "mettrela",
    "suivre",
    "miser",
    "mise",
    "parie",
    "parier",
    "relancer",
    "relance",
    "coucher",
    "jouer",
    "fold",
    "call",
    "check",
    "bet",
    "raise",
    "allin",
    "allincall",
    "fastfold",
}
PLACEHOLDER_PLAYER_NAME_RE = re.compile(r"^(?:seat|joueur)[_\\-\\s]*\\d+$", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
EDGE_NOISE_RE = re.compile(r"^[^\w]+|[^\w]+$")
MULTISPACE_RE = re.compile(r"\s+")
NUMERIC_LIKE_NAME_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
TRAILING_STACK_SUFFIX_RE = re.compile(r"^(.*?\S)\s+(\d{1,3}(?:[ .]\d{3})+|\d{4,})(?:[.,]\d+)?$")


def sanitize_player_name(candidate_name: str) -> str:
    value = html.unescape(str(candidate_name or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = HTML_TAG_RE.sub(" ", value)
    value = MULTISPACE_RE.sub(" ", value).strip()
    value = EDGE_NOISE_RE.sub("", value)
    trailing_stack_match = TRAILING_STACK_SUFFIX_RE.match(value)
    if trailing_stack_match:
        prefix = trailing_stack_match.group(1).strip()
        if any(char.isalpha() for char in prefix):
            value = prefix
    return value.strip()


def _is_near_ui_token(normalized_candidate: str) -> bool:
    if len(normalized_candidate) < 4:
        return False

    for ui_token in UI_PLAYER_NAME_TOKENS:
        normalized_ui = normalize_player_name_token(ui_token)
        if not normalized_ui:
            continue
        if normalized_candidate == normalized_ui:
            return True
        if abs(len(normalized_candidate) - len(normalized_ui)) > 1:
            continue

        mismatch_budget = 1
        i = 0
        j = 0
        mismatches = 0
        while i < len(normalized_candidate) and j < len(normalized_ui):
            if normalized_candidate[i] == normalized_ui[j]:
                i += 1
                j += 1
                continue
            mismatches += 1
            if mismatches > mismatch_budget:
                break
            if len(normalized_candidate) > len(normalized_ui):
                i += 1
            elif len(normalized_candidate) < len(normalized_ui):
                j += 1
            else:
                i += 1
                j += 1

        mismatches += (len(normalized_candidate) - i) + (len(normalized_ui) - j)
        if mismatches <= mismatch_budget:
            return True

    return False


def normalize_player_name_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", sanitize_player_name(value).lower())


def is_probable_ui_name(candidate_name: str) -> bool:
    stripped = sanitize_player_name(candidate_name)
    if not stripped:
        return True

    normalized = normalize_player_name_token(stripped)
    if not normalized:
        return True

    visible_chars = [char for char in stripped if not char.isspace()]
    if len(visible_chars) <= 1:
        return True

    if normalized in UI_PLAYER_NAME_TOKENS:
        return True
    if _is_near_ui_token(normalized):
        return True

    if "�" in stripped or "\ufffd" in stripped:
        return True

    if NUMERIC_LIKE_NAME_RE.fullmatch(stripped.replace(" ", "")):
        return True

    if visible_chars:
        allowed_chars = sum(char.isalnum() or char in "._-" for char in visible_chars)
        if (allowed_chars / len(visible_chars)) < 0.55:
            return True
        digit_like_chars = sum(char.isdigit() or char in "., " for char in visible_chars)
        if digit_like_chars / len(visible_chars) >= 0.7:
            return True

    raw_tokens = [token for token in stripped.split(" ") if token]
    normalized_tokens = [normalize_player_name_token(token) for token in raw_tokens]
    alpha_tokens = [token for token in normalized_tokens if token.isalpha()]
    short_alpha_tokens = [token for token in alpha_tokens if len(token) <= 2]
    single_letter_tokens = [token for token in alpha_tokens if len(token) == 1]

    if len(alpha_tokens) >= 3 and len(short_alpha_tokens) >= 2:
        return True
    if len(alpha_tokens) >= 2 and single_letter_tokens and len(short_alpha_tokens) >= 2:
        return True

    return False


def is_placeholder_player_name(candidate_name: str) -> bool:
    stripped = sanitize_player_name(candidate_name)
    if not stripped:
        return False

    normalized = normalize_player_name_token(stripped)
    if not normalized:
        return False

    return bool(
        PLACEHOLDER_PLAYER_NAME_RE.fullmatch(stripped)
        or re.fullmatch(r"(?:seat|joueur)\d+", normalized)
    )


def is_usable_player_name(candidate_name: str) -> bool:
    stripped = sanitize_player_name(candidate_name)
    if not stripped:
        return False
    if is_placeholder_player_name(stripped):
        return False
    return not is_probable_ui_name(stripped)


def resolve_player_name(
    seat_id: str,
    candidate_name: str,
    seat_cache: Dict[str, str],
) -> Tuple[str, str]:
    candidate = sanitize_player_name(candidate_name)
    cached = sanitize_player_name(seat_cache.get(seat_id) or "")

    if is_usable_player_name(candidate):
        seat_cache[seat_id] = candidate
        return candidate, "live_ocr"

    if is_usable_player_name(cached):
        return cached, "seat_cache"

    if candidate:
        return "", "discarded_ui_label"

    return "", "empty"
