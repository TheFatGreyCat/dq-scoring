"""Offline Hunspell spelling dictionary loader and evaluator using spylls."""

import hashlib
import json
import os
import tempfile
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from spylls.hunspell import Dictionary

MAX_DICTIONARY_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


def tokenize_for_spelling(text: str) -> list[str]:
    """Extract normalized word tokens (NFC, casefolded, punctuation/digits removed, apostrophes preserved)."""
    normalized = unicodedata.normalize("NFC", text).casefold()
    tokens = []
    word = []
    for index, character in enumerate(normalized):
        category = unicodedata.category(character)[0]
        internal_apostrophe = character == "'" and word and index + 1 < len(normalized) and unicodedata.category(normalized[index + 1])[0] == "L"
        if category == "L" or (category == "M" and word) or internal_apostrophe:
            word.append(character)
        elif word:
            tokens.append("".join(word))
            word.clear()
    if word:
        tokens.append("".join(word))
    return tokens


class SpellingEvaluator:
    """Evaluates text quality via Hunspell dictionary lookup and accepted terms."""

    def __init__(self, dictionaries: list[Dictionary], accepted_terms: list[str] | None = None) -> None:
        self._dictionaries = dictionaries
        self._accepted_terms = {
            unicodedata.normalize("NFC", t).casefold() for t in (accepted_terms or [])
        }
        self._cache: OrderedDict[str, bool] = OrderedDict()
        self._cache_capacity = 4096

    def evaluate(self, value: str | None) -> Literal["passed", "failed", "missing", "not_applicable"]:
        if value is None:
            return "missing"
        if not value.strip():
            return "missing"

        tokens = tokenize_for_spelling(value)
        if not tokens:
            return "not_applicable"

        for tok in tokens:
            if tok in self._accepted_terms:
                continue

            if tok in self._cache:
                is_known = self._cache[tok]
                self._cache.move_to_end(tok)
            else:
                is_known = any(d.lookup(tok) for d in self._dictionaries)
                if len(self._cache) >= self._cache_capacity:
                    self._cache.popitem(last=False)
                self._cache[tok] = is_known

            if not is_known:
                return "failed"

        return "passed"


class SpellingDictionaryManager:
    """Manages offline Hunspell dictionary manifest, checksum verification, and bundle construction."""

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        if manifest_path is None:
            manifest_path = os.getenv("DQ_TEXT_DICTIONARY_MANIFEST")
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._status = "UNAVAILABLE"
        self._revision: str | None = None
        self._languages: list[str] = []
        self._error_code: str | None = None
        self._manifest_data: dict[str, Any] = {}
        self._verified_files: dict[str, list[dict[str, Any]]] = {}

        self._load_and_verify()

    def _load_and_verify(self) -> None:
        if not self._manifest_path or not self._manifest_path.exists():
            self._status = "UNAVAILABLE"
            self._error_code = "TEXT_DICTIONARY_UNAVAILABLE"
            return

        try:
            with self._manifest_path.open("rb") as f:
                raw = f.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ValueError("Manifest exceeds limit")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TypeError("Manifest must be an object")
        except (OSError, ValueError, TypeError):
            self._status = "UNAVAILABLE"
            self._error_code = "MALFORMED_MANIFEST"
            return

        revision = data.get("revision")
        languages = data.get("languages", {})
        if not isinstance(revision, str) or not revision or not isinstance(languages, dict) or not languages or set(languages) - {"vi", "en"}:
            self._status = "UNAVAILABLE"
            self._error_code = "MALFORMED_MANIFEST"
            return

        total_bytes = 0
        verified: dict[str, list[dict[str, Any]]] = {}

        for lang, variants in languages.items():
            if not isinstance(variants, list) or not variants:
                self._status = "UNAVAILABLE"
                self._error_code = "MALFORMED_MANIFEST"
                return
            lang_files = []
            for item in variants:
                if not isinstance(item, dict):
                    self._error_code = "MALFORMED_MANIFEST"
                    return
                base_path = item.get("base_path")
                aff_sha = item.get("aff_sha256")
                dic_sha = item.get("dic_sha256")
                if not base_path or not aff_sha or not dic_sha:
                    self._status = "UNAVAILABLE"
                    self._error_code = "MALFORMED_MANIFEST"
                    return

                aff_file = Path(f"{base_path}.aff")
                dic_file = Path(f"{base_path}.dic")
                if not aff_file.exists() or not dic_file.exists():
                    self._status = "UNAVAILABLE"
                    self._error_code = "DICTIONARY_FILE_MISSING"
                    return

                try:
                    with aff_file.open("rb") as stream:
                        aff_bytes = stream.read(MAX_DICTIONARY_BYTES - total_bytes + 1)
                    total_bytes += len(aff_bytes)
                    if total_bytes > MAX_DICTIONARY_BYTES:
                        self._error_code = "DICTIONARY_TOO_LARGE"
                        return
                    with dic_file.open("rb") as stream:
                        dic_bytes = stream.read(MAX_DICTIONARY_BYTES - total_bytes + 1)
                    total_bytes += len(dic_bytes)
                    if total_bytes > MAX_DICTIONARY_BYTES:
                        self._error_code = "DICTIONARY_TOO_LARGE"
                        return
                except OSError:
                    self._error_code = "DICTIONARY_FILE_MISSING"
                    return

                if hashlib.sha256(aff_bytes).hexdigest() != aff_sha or hashlib.sha256(dic_bytes).hexdigest() != dic_sha:
                    self._status = "UNAVAILABLE"
                    self._error_code = "CHECKSUM_MISMATCH"
                    return

                lang_files.append({
                    "base_path": base_path,
                    "aff_sha256": aff_sha,
                    "dic_sha256": dic_sha,
                    "aff_bytes": aff_bytes,
                    "dic_bytes": dic_bytes,
                })
            verified[lang] = lang_files

        if total_bytes > 64 * 1024 * 1024:
            self._status = "UNAVAILABLE"
            self._error_code = "DICTIONARY_TOO_LARGE"
            return

        self._status = "CONFIGURED"
        self._revision = revision
        self._languages = sorted(verified.keys())
        self._error_code = None
        self._manifest_data = data
        self._verified_files = verified

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "revision": self._revision,
            "languages": self._languages,
            "error_code": self._error_code,
        }

    def get_bundle(self, revision: str, language: str) -> list[dict[str, Any]]:
        if self._status != "CONFIGURED" or self._revision != revision:
            raise ValueError(f"Dictionary revision '{revision}' is unavailable")

        langs = ["vi", "en"] if language == "vi-en" else [language]
        bundle: list[dict[str, Any]] = []
        for l in langs:
            if l not in self._verified_files:
                raise ValueError(f"Language '{l}' is not configured in manifest")
            bundle.extend(self._verified_files[l])
        return bundle

    def get_digests(self, revision: str, language: str) -> dict[str, list[dict[str, str]]]:
        self.get_bundle(revision, language)
        languages = ("vi", "en") if language == "vi-en" else (language,)
        return {lang: [{key: item[key] for key in ("aff_sha256", "dic_sha256")} for item in self._verified_files[lang]] for lang in languages}

    def create_evaluator(
        self,
        revision: str,
        language: str,
        accepted_terms: list[str] | None = None,
    ) -> SpellingEvaluator:
        bundle = self.get_bundle(revision, language)
        dictionaries: list[Dictionary] = []
        for item in bundle:
            # We can load directly from base_path since it exists locally
            d = Dictionary.from_files(item["base_path"])
            dictionaries.append(d)
        return SpellingEvaluator(dictionaries, accepted_terms)


def create_evaluator_from_bundle(
    bundle: list[dict[str, Any]],
    accepted_terms: list[str] | None = None,
) -> SpellingEvaluator:
    """Worker-side constructor: materializes broadcast bundle bytes into temp files for Dictionary.from_files."""
    dictionaries: list[Dictionary] = []
    with tempfile.TemporaryDirectory() as td:
        for idx, item in enumerate(bundle):
            base_name = os.path.join(td, f"dict_{idx}")
            with open(f"{base_name}.aff", "wb") as f:
                f.write(item["aff_bytes"])
            with open(f"{base_name}.dic", "wb") as f:
                f.write(item["dic_bytes"])
            d = Dictionary.from_files(base_name)
            dictionaries.append(d)
    return SpellingEvaluator(dictionaries, accepted_terms)
