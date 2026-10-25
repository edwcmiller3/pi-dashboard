"""The surgical .env writer behind the admin config panel's Apply.

The single highest-impact failure here is dropping PROTON_ICS_URL (the calendar
secret shares .env), so the core assertion is byte-for-byte preservation of
every line the writer was not asked to touch.
"""

from __future__ import annotations

from app.envfile import EnvKey, with_values

# A realistic secret: the Proton URL carries `=`, `&` and a `#` fragment, so any
# writer that re-parses or re-serializes unrelated lines would mangle it.
_SECRET = (
    "PROTON_ICS_URL=https://calendar.proton.me/api/calendar/v1/url/AbC=="
    "/calendar.ics?CacheKey=x_y&PassphraseKey=a%2Bb#frag"
)

_ENV = f"""# Copy to .env and fill in.

# --- Calendar ---
{_SECRET}

HOST=127.0.0.1
THEME=
# Which UI design renders
LAYOUT=classic
ICON_PACK=weather-icons
"""


def _without(text: str, *prefixes: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.startswith(prefixes)]


def test_updates_only_the_requested_keys_in_place() -> None:
    out = with_values(_ENV, {"LAYOUT": "hud", "THEME": "nord"})
    assert "LAYOUT=hud" in out.splitlines()
    assert "THEME=nord" in out.splitlines()
    assert "ICON_PACK=weather-icons" in out.splitlines()
    # Same line count, same order: in-place, nothing appended.
    assert len(out.splitlines()) == len(_ENV.splitlines())
    assert out.splitlines().index("LAYOUT=hud") == _ENV.splitlines().index(
        "LAYOUT=classic"
    )


def test_preserves_the_secret_comments_and_order_byte_for_byte() -> None:
    out = with_values(_ENV, {"LAYOUT": "hud", "THEME": "nord", "ICON_PACK": "x"})
    assert _SECRET in out.splitlines()
    assert _without(out, "LAYOUT=", "THEME=", "ICON_PACK=") == _without(
        _ENV, "LAYOUT=", "THEME=", "ICON_PACK="
    )
    assert out.endswith("\n")


def test_no_values_is_an_exact_round_trip() -> None:
    assert with_values(_ENV, {}) == _ENV


def test_rewriting_the_current_values_is_an_exact_round_trip() -> None:
    same: dict[EnvKey, str] = {"LAYOUT": "classic", "THEME": "", "ICON_PACK": "weather-icons"}
    assert with_values(_ENV, same) == _ENV


def test_is_idempotent() -> None:
    once = with_values(_ENV, {"LAYOUT": "swiss-mono"})
    assert with_values(once, {"LAYOUT": "swiss-mono"}) == once


def test_appends_a_missing_key() -> None:
    out = with_values("PROTON_ICS_URL=s\n", {"ICON_PACK": "meteocons-flat"})
    assert out == "PROTON_ICS_URL=s\nICON_PACK=meteocons-flat\n"


def test_appends_after_a_final_line_with_no_newline() -> None:
    out = with_values("PROTON_ICS_URL=s", {"THEME": "nord"})
    assert out == "PROTON_ICS_URL=s\nTHEME=nord\n"


def test_appends_in_a_stable_key_order() -> None:
    out = with_values("", {"ICON_PACK": "p", "LAYOUT": "l", "THEME": "t"})
    assert out == "LAYOUT=l\nTHEME=t\nICON_PACK=p\n"


def test_key_match_is_case_insensitive_like_pydantic_settings() -> None:
    assert with_values("layout=classic\n", {"LAYOUT": "hud"}) == "layout=hud\n"


def test_handles_export_prefix_and_spacing() -> None:
    out = with_values("export LAYOUT = classic\n", {"LAYOUT": "hud"})
    assert out == "export LAYOUT = hud\n"


def test_replaces_a_quoted_value() -> None:
    assert with_values('THEME="nord"\n', {"THEME": "gruvbox"}) == "THEME=gruvbox\n"
    assert with_values("THEME='nord'\n", {"THEME": ""}) == "THEME=\n"


def test_keeps_an_inline_comment() -> None:
    out = with_values("LAYOUT=classic  # the default\n", {"LAYOUT": "hud"})
    assert out == "LAYOUT=hud  # the default\n"


def test_an_empty_value_before_a_comment_stays_separated_from_it() -> None:
    assert with_values("THEME=  # none\n", {"THEME": "nord"}) == "THEME= nord # none\n"


def test_leaves_commented_out_assignments_alone() -> None:
    out = with_values("#LAYOUT=hud\nLAYOUT=classic\n", {"LAYOUT": "swiss-mono"})
    assert out == "#LAYOUT=hud\nLAYOUT=swiss-mono\n"


def test_does_not_match_a_key_that_merely_shares_a_prefix() -> None:
    out = with_values("THEME_EXTRA=1\n", {"THEME": "nord"})
    assert out == "THEME_EXTRA=1\nTHEME=nord\n"


def test_updates_every_duplicate_so_the_last_one_still_wins() -> None:
    out = with_values("LAYOUT=a\nLAYOUT=b\n", {"LAYOUT": "hud"})
    assert out == "LAYOUT=hud\nLAYOUT=hud\n"


def test_preserves_crlf_line_endings() -> None:
    out = with_values("A=1\r\nLAYOUT=classic\r\n", {"LAYOUT": "hud"})
    assert out == "A=1\r\nLAYOUT=hud\r\n"
