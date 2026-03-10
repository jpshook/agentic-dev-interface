from adi.engine.frontmatter import parse_frontmatter_markdown, render_frontmatter_markdown


def test_frontmatter_round_trip_preserves_unknown_fields_and_body() -> None:
    frontmatter = {
        "id": "repo-1",
        "name": "sample",
        "unknown_flag": True,
        "nested": {"value": 3},
    }
    body = "# Title\n\nSome details.\n"

    text = render_frontmatter_markdown(frontmatter, body)
    parsed = parse_frontmatter_markdown(text)

    assert parsed.frontmatter == frontmatter
    assert parsed.body == body


def test_parse_without_frontmatter_returns_body_only() -> None:
    text = "# Plain Markdown\n"
    parsed = parse_frontmatter_markdown(text)
    assert parsed.frontmatter == {}
    assert parsed.body == text
