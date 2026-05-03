"""Unit tests for tools/quests.py parsing helpers (issue #18) and the get_quest_info tool (issue #28)."""
import pytest

from rs_mcp_server.tools.quests import (
    _clean_wikitext,
    _find_template,
    _format_from_content,
    _has_quest_template,
    _merged_fields,
    _parse_fields,
    _titles_match,
    get_quest_info,
)


# ── _find_template ────────────────────────────────────────────────────────────

class TestFindTemplate:
    def test_basic_extraction(self):
        body = _find_template("{{Infobox Quest\n|name = Test\n}}", "Infobox Quest")
        assert body is not None
        assert "name = Test" in body

    def test_missing_template_returns_none(self):
        assert _find_template("Plain prose, no templates here.", "Infobox Quest") is None

    def test_unbalanced_braces_returns_none(self):
        assert _find_template("{{Infobox Quest\n|name = Test", "Infobox Quest") is None

    def test_nested_templates_walked_correctly(self):
        body = _find_template(
            "{{Infobox Quest\n|requirements = {{plinkp|Item}}\n|x = y\n}}",
            "Infobox Quest",
        )
        assert body is not None
        assert "{{plinkp|Item}}" in body
        assert "x = y" in body

    def test_underscore_variant_matched(self):
        body = _find_template("{{Infobox_Quest\n|name = Test\n}}", "Infobox Quest")
        assert body is not None
        assert "name = Test" in body

    def test_case_insensitive_template_name(self):
        body = _find_template("{{INFOBOX QUEST\n|name = Test\n}}", "Infobox Quest")
        assert body is not None


# ── _parse_fields ─────────────────────────────────────────────────────────────

class TestParseFields:
    def test_basic_key_value(self):
        fields = _parse_fields("\n|name = Test\n|difficulty = Hard")
        assert fields["name"] == "Test"
        assert fields["difficulty"] == "Hard"

    def test_whitespace_tolerated_around_equals(self):
        fields = _parse_fields("\n|name=Test\n|difficulty   =   Hard")
        assert fields["name"] == "Test"
        assert fields["difficulty"] == "Hard"

    def test_empty_values_omitted(self):
        fields = _parse_fields("\n|name = Test\n|empty =\n|other = present")
        assert "name" in fields
        assert "empty" not in fields
        assert fields["other"] == "present"

    def test_multiline_values_preserved(self):
        fields = _parse_fields("\n|requirements = * line one\n* line two\n* line three\n|next = x")
        assert "* line one" in fields["requirements"]
        assert "* line two" in fields["requirements"]
        assert "* line three" in fields["requirements"]
        assert fields["next"] == "x"

    def test_nested_template_pipe_not_treated_as_field_separator(self):
        # The nested {{plinkp|Item}} contains a `|` but NOT preceded by \n,
        # so it must stay inside the requirements value
        fields = _parse_fields("\n|requirements = {{plinkp|Item}}\n|name = Test")
        assert fields["requirements"] == "{{plinkp|Item}}"
        assert fields["name"] == "Test"

    def test_field_without_equals_skipped(self):
        fields = _parse_fields("\n|valid = ok\n|orphan_no_equals\n|other = also_ok")
        assert fields["valid"] == "ok"
        assert "orphan_no_equals" not in fields
        assert fields["other"] == "also_ok"


# ── _merged_fields ────────────────────────────────────────────────────────────

class TestMergedFields:
    def test_merges_both_templates(self):
        wikitext = (
            "{{Infobox Quest\n|name = Test\n|members = No\n}}\n"
            "{{Quest details\n|difficulty = Hard\n|length = Long\n}}"
        )
        fields = _merged_fields(wikitext)
        assert fields["name"] == "Test"
        assert fields["members"] == "No"
        assert fields["difficulty"] == "Hard"
        assert fields["length"] == "Long"

    def test_quest_details_overrides_infobox_on_conflict(self):
        wikitext = (
            "{{Infobox Quest\n|difficulty = Easy\n}}\n"
            "{{Quest details\n|difficulty = Hard\n}}"
        )
        fields = _merged_fields(wikitext)
        assert fields["difficulty"] == "Hard"

    def test_no_templates_returns_empty_dict(self):
        assert _merged_fields("Plain prose only.") == {}


# ── _clean_wikitext ───────────────────────────────────────────────────────────

class TestCleanWikitext:
    def test_link_with_pipe(self):
        assert _clean_wikitext("[[Page|displayed]]") == "displayed"

    def test_link_without_pipe(self):
        assert _clean_wikitext("[[SimplePage]]") == "SimplePage"

    def test_bold_stripped(self):
        assert _clean_wikitext("'''bold text'''") == "bold text"

    def test_italic_stripped(self):
        assert _clean_wikitext("''italic''") == "italic"

    def test_br_to_newline(self):
        assert _clean_wikitext("line1<br>line2") == "line1\nline2"
        assert _clean_wikitext("line1<br/>line2") == "line1\nline2"
        assert _clean_wikitext("line1<br />line2") == "line1\nline2"

    def test_html_tags_stripped(self):
        assert _clean_wikitext("<span>visible</span>") == "visible"

    def test_skillreq_template_formatted(self):
        assert _clean_wikitext("{{Skillreq|Mining|45}}") == "Level 45 Mining"

    def test_scp_template_formatted(self):
        # OSRS uses {{SCP|Skill|Level|link=yes}} for skill requirements
        assert _clean_wikitext("{{SCP|Strength|50|link=yes}}") == "Level 50 Strength"

    def test_plinkp_template_formatted(self):
        assert _clean_wikitext("{{plinkp|Bronze sword}}") == "Bronze sword"
        assert _clean_wikitext("{{plink|Bronze sword}}") == "Bronze sword"

    def test_unknown_templates_removed(self):
        assert _clean_wikitext("foo {{unknown|args}} bar") == "foo  bar"

    def test_pure_markup_returns_empty(self):
        assert _clean_wikitext("'''''") == ""


# ── _titles_match ─────────────────────────────────────────────────────────────

class TestTitlesMatch:
    def test_exact_equal(self):
        assert _titles_match("Dragon Slayer", "Dragon Slayer")

    def test_case_insensitive(self):
        assert _titles_match("dragon slayer", "Dragon Slayer")
        assert _titles_match("DRAGON SLAYER", "Dragon Slayer")

    def test_whitespace_stripped(self):
        assert _titles_match("  Dragon Slayer  ", "Dragon Slayer")

    def test_different_returns_false(self):
        assert not _titles_match("Dragon Slayer", "Dragon Slayer I")

    def test_empty_strings_match(self):
        assert _titles_match("", "")


# ── _has_quest_template ───────────────────────────────────────────────────────

class TestHasQuestTemplate:
    def test_infobox_quest_present(self):
        assert _has_quest_template("{{Infobox Quest|name=x}}")

    def test_quest_details_present(self):
        assert _has_quest_template("{{Quest details|difficulty=Hard}}")

    def test_neither_present(self):
        assert not _has_quest_template("Just plain article text.")

    def test_other_template_not_a_quest(self):
        assert not _has_quest_template("{{Infobox Item|name=x}}")


# ── _format_from_content ──────────────────────────────────────────────────────

class TestFormatFromContent:
    def test_includes_title_url_label(self):
        wikitext = "{{Infobox Quest\n|difficulty = Hard\n|members = Yes\n}}"
        result = _format_from_content("Test Quest", "https://example/w/Test", "RS3", wikitext)
        assert "**Test Quest** (RS3 Wiki)" in result
        assert "https://example/w/Test" in result

    def test_difficulty_and_length_displayed(self):
        wikitext = "{{Infobox Quest\n|difficulty = Hard\n|length = Long\n}}"
        result = _format_from_content("Q", "u", "RS3", wikitext)
        assert "**Difficulty:** Hard" in result
        assert "**Length:** Long" in result

    def test_multiline_field_indented(self):
        wikitext = (
            "{{Infobox Quest\n|requirements = * level 50\n* level 60 cooking\n}}"
        )
        result = _format_from_content("Q", "u", "RS3", wikitext)
        assert "**Requirements:**" in result
        # Multi-line values get indented continuation
        assert "  * level 50" in result
        assert "  * level 60 cooking" in result

    def test_empty_fields_omitted(self):
        wikitext = "{{Infobox Quest\n|members = Yes\n}}"
        result = _format_from_content("Q", "u", "RS3", wikitext)
        assert "**Members:** Yes" in result
        # Difficulty wasn't provided, so it should not appear
        assert "Difficulty:" not in result


# ── get_quest_info end-to-end ─────────────────────────────────────────────────

def _quest_page(title: str, content: str) -> dict:
    return {
        "query": {
            "pages": [
                {
                    "title": title,
                    "revisions": [{"slots": {"main": {"content": content}}}],
                }
            ]
        }
    }


class TestGetQuestInfo:
    @pytest.mark.anyio
    async def test_direct_hit_returns_formatted_quest(self, monkeypatch):
        wikitext = (
            "{{Infobox Quest\n|difficulty = Novice\n|length = Short\n|members = No\n}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return _quest_page("Cook's Assistant", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.quests.http_get", fake_http_get)
        result = await get_quest_info("Cook's Assistant", "osrs")
        assert "**Cook's Assistant**" in result
        assert "OSRS Wiki" in result
        assert "**Difficulty:** Novice" in result

    @pytest.mark.anyio
    async def test_disambiguation_when_titles_dont_match(self, monkeypatch):
        wikitext = "{{Infobox Quest\n|difficulty = Easy\n}}"

        async def fake_http_get(url, params=None, timeout=10.0):
            # Returned page title differs from the queried name
            return _quest_page("Cook's Assistant", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.quests.http_get", fake_http_get)
        result = await get_quest_info("Cook's Helper", "osrs")
        assert result.startswith("Did you mean")
        assert "Cook's Assistant" in result

    @pytest.mark.anyio
    async def test_no_quest_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            # Empty pages on every call → direct fetch returns None, search returns None
            return {"query": {"pages": []}}

        monkeypatch.setattr("rs_mcp_server.tools.quests.http_get", fake_http_get)
        result = await get_quest_info("zzznotaquestzzz", "rs3")
        assert result.startswith("No quest found")
        assert "RS3" in result
