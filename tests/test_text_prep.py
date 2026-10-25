import pytest

from src.errors import TextRejected
from src.text_prep import prepare


def test_strips_emphasis_headings_and_list_markers():
    assert prepare("# Title\n- **one**\n- _two_", 100) == "Title one two"


def test_keeps_link_text_and_drops_the_url():
    assert prepare("See [the docs](https://example.com/a) now", 100) == "See the docs now"


def test_drops_fenced_code_and_keeps_inline_code_text():
    assert prepare("Run `ls` first.\n```py\nprint(1)\n```\nDone", 100) == "Run ls first. Done"


def test_keeps_underscores_inside_words_and_decimal_numbers():
    assert prepare("use my_var for 3.5 percent", 100) == "use my_var for 3.5 percent"


def test_empty_after_cleaning_is_rejected():
    with pytest.raises(TextRejected, match="no speakable text"):
        prepare("```\ncode only\n```", 100)


def test_too_long_is_rejected_with_the_limit_in_the_message():
    with pytest.raises(TextRejected, match="limit is 10"):
        prepare("x" * 11, 10)
