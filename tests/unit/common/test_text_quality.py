from dq_scoring.common.text_quality import (
    contains_control_characters,
    contains_mojibake,
    contains_replacement_character,
    evaluate_text_length,
)


def test_replacement_character_detection():
    assert not contains_replacement_character("Thanh toán hợp lệ?")
    assert contains_replacement_character("Thanh\ufffdtoán")
    assert not contains_replacement_character("Hello world 123 !@#$%^&*()")


def test_control_character_detection():
    # Valid strings with tab, LF, CR should pass
    assert not contains_control_characters("Line 1\nLine 2\rLine 3\tTabbed")
    # String with C0 SOH (\x01) should fail
    assert contains_control_characters("Thanh\u0001toán")
    # String with DEL (\x7f) should fail
    assert contains_control_characters("Test\x7f")
    # String with C1 control (\x80 to \x9f) should fail
    assert contains_control_characters("Test\x85")


def test_mojibake_detection():
    assert not contains_mojibake("Thanh toán hợp lệ")
    assert contains_mojibake("Thanh toÃ¡n")
    assert contains_mojibake("GiÃ¡")
    assert contains_mojibake("â€œquotedâ€")
    assert contains_mojibake("ðŸ’°")


def test_evaluate_text_length():
    text = "Thanh toán"  # 10 Unicode codepoints
    assert evaluate_text_length(text, min_length=5, max_length=15) is True
    assert evaluate_text_length(text, min_length=11, max_length=15) is False
    assert evaluate_text_length(text, min_length=1, max_length=9) is False
    assert evaluate_text_length(text, min_length=10, max_length=10) is True
    assert evaluate_text_length(text, min_length=5, max_length=None) is True
    assert evaluate_text_length(text, min_length=None, max_length=15) is True
