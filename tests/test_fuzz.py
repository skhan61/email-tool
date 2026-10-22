"""Fuzz tests: the CUI detector, recipient handling and IMAP search values under generated input.

Standard: Hypothesis property-based testing (the Python fuzzing OpenSSF Scorecard recognises):
each property holds for every input Hypothesis generates, including the shrunk edge cases.
Placement: tests/test_fuzz.py, beside the unit tests of cui.py, message_compose.py,
policy.py and imap_session.py.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from email_tool_mcp.cui import markings, message_markings, tag_lines
from email_tool_mcp.imap_session import text
from email_tool_mcp.message_compose import compose, envelope_recipients
from email_tool_mcp.policy import outside_domains

# Enough cases to find edge cases, few enough for every CI run; no deadline on slow runners.
FUZZ: settings = settings(max_examples=300, deadline=None)
INVISIBLE: list[str] = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad"]


@FUZZ
@given(st.text(), st.text(), st.text())
def test_the_detector_never_fails_on_any_text(subject: str, body: str, html: str) -> None:
    markings(subject, body)
    markings(subject, tag_lines(html))


@FUZZ
@given(st.text(), st.text())
def test_a_banner_line_is_found_whatever_surrounds_it(before: str, after: str) -> None:
    assert any(found.startswith("banner:") for found in markings("", f"{before}\nCUI\n{after}"))


@FUZZ
@given(st.lists(st.sampled_from(INVISIBLE), min_size=3, max_size=3))
def test_invisible_characters_cannot_hide_a_banner(hidden: list[str]) -> None:
    disguised: str = f"C{hidden[0]}U{hidden[1]}I{hidden[2]}"
    assert markings("", f"Hello\n{disguised}\nBody") != []


@FUZZ
@given(st.text(alphabet=st.characters(blacklist_characters="<>&"), max_size=40), st.sampled_from(["p", "div", "b"]))
def test_a_banner_in_html_is_found_whatever_surrounds_it(words: str, tag: str) -> None:
    html: str = f"<html><body><{tag}>{words}</{tag}><{tag}>CUI</{tag}><{tag}>{words}</{tag}></body></html>"
    try:
        message: EmailMessage = compose("me@example.com", "you@example.com", "Hello", "plain", "", html)
    except ValueError as refused:
        # Found by this test: a lone surrogate used to escape as a raw UnicodeEncodeError.
        assert "invalid text" in str(refused)
        return
    assert message_markings(message) != []


@FUZZ
@given(st.lists(st.emails(), max_size=6), st.lists(st.emails(), max_size=3))
def test_recipients_are_exactly_the_addresses_given(to: list[str], cc: list[str]) -> None:
    message: EmailMessage = compose("me@example.com", ", ".join(to), "s", "b", ", ".join(cc), "")
    delivered: list[str] = envelope_recipients(message)
    assert [address.lower() for address in delivered] == [address.lower() for address in to + cc]


@FUZZ
@given(st.text())
def test_a_header_value_with_a_line_break_never_reaches_the_message(value: str) -> None:
    try:
        message: EmailMessage = compose("me@example.com", value, value, "b", "", "")
    except ValueError:
        return
    assert all("\r" not in address and "\n" not in address for address in envelope_recipients(message))


@FUZZ
@given(st.lists(st.emails(), max_size=8), st.lists(st.sampled_from(["example.com", "agency.mil", "x.org"])))
def test_the_domain_allow_list_holds_for_any_recipients(recipients: list[str], allowed: list[str]) -> None:
    outside: list[str] = outside_domains(recipients, allowed)
    assert set(outside) <= set(recipients)
    for address in recipients:
        assert (address in outside) is (address.rpartition("@")[2].lower() not in allowed)


@FUZZ
@given(st.text())
def test_a_search_value_with_a_line_break_or_nul_is_refused(value: str) -> None:
    if any(character in value for character in "\r\n\0"):
        with pytest.raises(ValueError):
            text(value)
    else:
        assert isinstance(text(value), bytes)
