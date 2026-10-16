import hashlib
import json
import os
import tempfile

from dq_scoring.adapters.compute.spelling_dictionary import (
    SpellingDictionaryManager,
    tokenize_for_spelling,
)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_tokenize_for_spelling():
    text = "Thanh toán hoá đơn 123, ngày 01/01/2026! don't worry."
    tokens = tokenize_for_spelling(text)
    # Digits and punctuation should be discarded, internal apostrophe in don't preserved
    assert "123" not in tokens
    assert "01" not in tokens
    assert "don't" in tokens
    assert "thanh" in tokens
    assert "toán" in tokens
    assert "hoá" in tokens
    assert "đơn" in tokens
    assert "worry" in tokens


def test_spelling_dictionary_manager_and_evaluator():
    with tempfile.TemporaryDirectory() as td:
        # Create synthetic vi dict: "thanh", "toán", "chuyển", "khoản"
        vi_base = os.path.join(td, "vi")
        vi_aff = b"SET UTF-8\n"
        vi_dic = "4\nthanh\ntoán\nchuyển\nkhoản\n".encode()
        with open(vi_base + ".aff", "wb") as f:
            f.write(vi_aff)
        with open(vi_base + ".dic", "wb") as f:
            f.write(vi_dic)

        # Create synthetic en dict: "payment", "transfer", "valid"
        en_base = os.path.join(td, "en")
        en_aff = b"SET UTF-8\n"
        en_dic = b"3\npayment\ntransfer\nvalid\n"
        with open(en_base + ".aff", "wb") as f:
            f.write(en_aff)
        with open(en_base + ".dic", "wb") as f:
            f.write(en_dic)

        manifest = {
            "revision": "test-v1",
            "languages": {
                "vi": [{
                    "base_path": vi_base,
                    "aff_sha256": _hash(vi_aff),
                    "dic_sha256": _hash(vi_dic),
                }],
                "en": [{
                    "base_path": en_base,
                    "aff_sha256": _hash(en_aff),
                    "dic_sha256": _hash(en_dic),
                }],
            },
        }
        manifest_path = os.path.join(td, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        mgr = SpellingDictionaryManager(manifest_path)
        status = mgr.get_status()
        assert status["status"] == "CONFIGURED"
        assert status["revision"] == "test-v1"
        assert sorted(status["languages"]) == ["en", "vi"]

        evaluator = mgr.create_evaluator(
            revision="test-v1",
            language="vi-en",
            accepted_terms=["fintech"],
        )

        # Valid row with words in VI + EN + accepted_terms
        assert evaluator.evaluate("Thanh toán payment fintech") == "passed"

        # Row with typo
        assert evaluator.evaluate("Thanh toán paymnt") == "failed"

        # Missing / whitespace
        assert evaluator.evaluate(None) == "missing"
        assert evaluator.evaluate("   ") == "missing"

        # No lexical tokens -> not_applicable
        assert evaluator.evaluate("123?! --- @@@") == "not_applicable"


def test_spelling_dictionary_manager_checksum_mismatch():
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "en")
        with open(base + ".aff", "wb") as f:
            f.write(b"SET UTF-8\n")
        with open(base + ".dic", "wb") as f:
            f.write(b"1\nhello\n")
        manifest = {
            "revision": "mismatch-v1",
            "languages": {
                "en": [{
                    "base_path": base,
                    "aff_sha256": "bad_hash",
                    "dic_sha256": "bad_hash",
                }]
            },
        }
        manifest_path = os.path.join(td, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        mgr = SpellingDictionaryManager(manifest_path)
        status = mgr.get_status()
        assert status["status"] == "UNAVAILABLE"
        assert status["error_code"] == "CHECKSUM_MISMATCH"


def test_tokenizer_preserves_noncomposable_combining_marks():
    assert tokenize_for_spelling("a\u0338bc DON'T 123") == ["a\u0338bc", "don't"]
