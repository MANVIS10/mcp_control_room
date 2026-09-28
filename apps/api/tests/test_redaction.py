from app.redaction import MASK, preview, redact


def test_secret_keys_are_masked_at_any_depth():
    data = {"path": "notes.txt", "headers": {"Authorization": "Bearer abc123"}, "items": [{"api_key": "k-1"}]}
    assert redact(data) == {"path": "notes.txt", "headers": {"Authorization": MASK}, "items": [{"api_key": MASK}]}


def test_token_shaped_values_are_masked_even_under_innocent_keys():
    assert "ghp_" not in preview({"note": "use ghp_abcdefghijklmnop to push"})
    assert "abc.def" not in preview({"note": "header was Bearer abc.def"})


def test_long_previews_are_truncated():
    assert len(preview({"text": "x" * 1000})) == 300


def test_key_names_match_regardless_of_separators():
    data = {"X-Api-Key": "abc123", "api.key": "def456", "Auth-Token": "ghi789"}
    assert redact(data) == {"X-Api-Key": MASK, "api.key": MASK, "Auth-Token": MASK}
