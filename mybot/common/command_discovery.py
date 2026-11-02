from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from mybot.common.command_registry import collect_command_aliases
from mybot.common.help_registry import (
    HelpItem,
    collect_help_items,
    collect_public_command_names,
)


_SEARCH_TOKEN_PATTERN = re.compile(r"[\s/／@_\-—，。,:：；|｜【】\[\]（）()]+")


@dataclass(frozen=True)
class CommandSearchResult:
    text: str
    category: str
    command: str | None
    kind: str
    score: float


@dataclass(frozen=True)
class _SearchCandidate:
    text: str
    category: str
    command: str | None
    kind: str
    order: int


def _compact(value: str) -> str:
    return "".join(value.casefold().strip().split()).lstrip("/／@")


def _format_command_name(name: str) -> str:
    normalized = name.strip()
    return normalized if normalized.startswith("@") else f"/{normalized}"


def _command_from_help_item(item: HelpItem) -> str | None:
    text = item.text.strip()
    if not text:
        return None
    token = text.split(maxsplit=1)[0]
    if not token.startswith(("/", "／", "@")):
        return None
    return token.lstrip("/／") or None


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _candidate_score(keyword: str, candidate: _SearchCandidate) -> float:
    query = _compact(keyword)
    command = _compact(candidate.command or "")
    text = _compact(candidate.text)
    category = _compact(candidate.category)
    if not query:
        return 0.0

    if command and query == command:
        return 120.0
    if command and query in command:
        return 108.0 + min(8.0, len(query) / max(1, len(command)) * 8.0)
    if command and len(command) >= 2 and command in query:
        return 75.0 + len(command) / len(query) * 10.0
    if query in text:
        return 90.0
    if query in category:
        return 80.0

    tokens = [
        _compact(token)
        for token in _SEARCH_TOKEN_PATTERN.split(
            f"{candidate.category} {candidate.text}"
        )
        if _compact(token)
    ]
    command_fuzzy = _command_similarity(query, command) * 100.0
    text_fuzzy = max(
        (_similarity(query, token) for token in tokens),
        default=0.0,
    ) * 60.0
    return max(command_fuzzy, text_fuzzy)


def _public_search_candidates(
    group_id: str | int | None = None,
    user_id: str | int | None = None,
) -> tuple[_SearchCandidate, ...]:
    help_candidates: list[_SearchCandidate] = []
    primary_commands: set[str] = set()
    for _, _, item in collect_help_items(group_id, user_id):
        command = _command_from_help_item(item)
        if command:
            primary_commands.add(_compact(command))
        help_candidates.append(
            _SearchCandidate(
                text=item.text,
                category=item.category,
                command=command,
                kind="help",
                order=item.order,
            )
        )

    alias_candidates = [
        _SearchCandidate(
            text=_format_command_name(name),
            category="",
            command=name,
            kind="alias",
            order=999,
        )
        for name in collect_public_command_names(group_id, user_id)
        if _compact(name) not in primary_commands
    ]
    return tuple((*help_candidates, *alias_candidates))


def search_public_commands(
    keyword: str,
    *,
    group_id: str | int | None = None,
    user_id: str | int | None = None,
    limit: int = 5,
) -> tuple[CommandSearchResult, ...]:
    """Search public command entrances by command, alias, category, and help copy."""
    if limit <= 0 or not _compact(keyword):
        return ()

    ranked = []
    for candidate in _public_search_candidates(group_id, user_id):
        score = _candidate_score(keyword, candidate)
        if score < 32.0:
            continue
        ranked.append((score, candidate))

    ranked.sort(
        key=lambda row: (
            -row[0],
            0 if row[1].kind == "help" else 1,
            row[1].order,
            row[1].text.casefold(),
            row[1].text,
        )
    )

    results: list[CommandSearchResult] = []
    seen_text: set[str] = set()
    for score, candidate in ranked:
        normalized_text = candidate.text.casefold()
        if normalized_text in seen_text:
            continue
        seen_text.add(normalized_text)
        results.append(
            CommandSearchResult(
                text=candidate.text,
                category=candidate.category,
                command=candidate.command,
                kind=candidate.kind,
                score=score,
            )
        )
        if len(results) >= limit:
            break
    return tuple(results)


def _common_prefix_length(left: str, right: str) -> int:
    length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        length += 1
    return length


def _command_similarity(unknown: str, candidate: str) -> float:
    left = _compact(unknown)
    right = _compact(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    base = _similarity(left, right)
    shortest = min(len(left), len(right))
    prefix_bonus = _common_prefix_length(left, right) / shortest * 0.15
    suffix_bonus = _common_prefix_length(left[::-1], right[::-1]) / shortest * 0.05
    return min(1.0, base + prefix_bonus + suffix_bonus)


def suggest_public_commands(
    unknown_command: str,
    *,
    group_id: str | int | None = None,
    user_id: str | int | None = None,
    limit: int = 3,
    minimum_score: float = 0.52,
) -> tuple[str, ...]:
    """Return only public entrances close enough to a misspelled command."""
    if limit <= 0 or not _compact(unknown_command):
        return ()

    ranked = []
    for name in collect_public_command_names(group_id, user_id):
        if name.startswith("@"):
            continue
        score = _command_similarity(unknown_command, name)
        if score < minimum_score:
            continue
        ranked.append(
            (score, abs(len(_compact(name)) - len(_compact(unknown_command))), name)
        )

    ranked.sort(
        key=lambda row: (
            -row[0],
            row[1],
            len(row[2]),
            row[2].casefold(),
            row[2],
        )
    )
    return tuple(_format_command_name(name) for _, _, name in ranked[:limit])


def _explicit_command_body(message: str) -> str | None:
    text = message.lstrip()
    if not text.startswith(("/", "／")):
        return None
    while text.startswith(("/", "／")):
        text = text[1:].lstrip()
    return text or None


def extract_explicit_command(message: str) -> str | None:
    body = _explicit_command_body(message)
    if not body:
        return None
    return body.split(maxsplit=1)[0].strip() or None


def is_registered_explicit_command(message: str) -> bool:
    body = _explicit_command_body(message)
    if not body:
        return False
    normalized_body = body.casefold()
    for alias in sorted(collect_command_aliases(), key=len, reverse=True):
        normalized_alias = alias.casefold()
        if normalized_body == normalized_alias:
            return True
        if normalized_body.startswith(normalized_alias):
            rest = normalized_body[len(normalized_alias) :]
            if rest and rest[0].isspace():
                return True
    return False
