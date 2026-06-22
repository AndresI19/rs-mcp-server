"""Unit tests for the shared wikitext-parsing helpers."""
from rs_mcp_server.tools._wiki_parsing import (
    clean_wikitext,
    find_template,
    parse_template_fields,
    titles_match,
)


class TestTitlesMatch:
    def test_case_and_whitespace_insensitive(self):
        assert titles_match("  Zulrah ", "zulrah")
        assert titles_match("Flow State", "FLOW STATE")

    def test_distinct_titles_do_not_match(self):
        assert not titles_match("Zulrah", "Vorkath")


class TestFindTemplate:
    def test_extracts_body(self):
        body = find_template("intro {{Infobox Monster|hp = 10}} outro", "Infobox Monster")
        assert body == "|hp = 10"

    def test_handles_nested_templates(self):
        # A nested {{...}} inside the body must not end the match early.
        wikitext = "{{Infobox Achievement|desc = kill {{plink|Jad}} once}}"
        body = find_template(wikitext, "Infobox Achievement")
        assert body == "|desc = kill {{plink|Jad}} once"

    def test_delimiter_guard_avoids_false_prefix_match(self):
        # "Infobox Achievement category" must not match "Infobox Achievement".
        wikitext = "{{Infobox Achievement category|x = 1}}"
        assert find_template(wikitext, "Infobox Achievement") is None

    def test_missing_template_returns_none(self):
        assert find_template("no templates here", "Infobox Monster") is None

    def test_unbalanced_braces_returns_none(self):
        assert find_template("{{Infobox Monster|hp = 10", "Infobox Monster") is None


class TestParseTemplateFields:
    def test_parses_keys_lowercased(self):
        # Real template bodies are newline-prefixed per field.
        fields = parse_template_fields("\n|Name = Zulrah\n|Combat Level = 725")
        assert fields == {"name": "Zulrah", "combat level": "725"}

    def test_pipe_inside_value_is_preserved(self):
        # A pipe inside a wikilink value is not a field boundary (split keys off "\n|").
        fields = parse_template_fields("\n|drop = [[Magic fang|fang]]")
        assert fields["drop"] == "[[Magic fang|fang]]"

    def test_empty_values_are_skipped(self):
        assert parse_template_fields("|empty = \n|set = yes") == {"set": "yes"}


class TestCleanWikitext:
    def test_strips_links_templates_and_tags(self):
        assert clean_wikitext("[[Zulrah|the snake]]") == "the snake"
        assert clean_wikitext("a {{template}} b") == "a b"  # spaces around removal collapsed
        assert clean_wikitext("<b>bold</b>") == "bold"

    def test_plain_text_unchanged(self):
        assert clean_wikitext("  just text  ") == "just text"

    def test_nested_template_fully_removed(self):
        # Regex '{{[^}]*}}' stopped at the first '}}' and left a stray '}}'; the
        # balanced walk removes the whole nested span.
        assert clean_wikitext("{{a|{{b|x}}}} tail") == "tail"
        assert clean_wikitext("Lvl {{x}} and {{y}} done") == "Lvl and done"

    def test_link_text_inside_unmatched_context_preserved(self):
        assert clean_wikitext("see [[Krystilia]] now") == "see Krystilia now"
