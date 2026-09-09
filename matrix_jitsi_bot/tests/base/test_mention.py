from matrix_jitsi_bot.interactions import Mention


def test_mention_requires_a_mention() -> None:
    """The bot only reacts to messages addressed to it - a bare command
    with no mention at all does not match."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("hello") is None


def test_mention_matches_a_colon_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org: hello")
    assert reaction.match("bot: hello")


def test_mention_matches_a_comma_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("bot, hello")


def test_mention_does_not_need_whitespace_in_the_pattern() -> None:
    r"""`pattern` only ever sees the text after the mention was stripped -
    it never has to account for `\s` around the mention itself."""
    reaction = Mention(1, r"set language to (?P<language>\S+)$")

    match = reaction.match("@bot:matrix.org: set language to de")

    assert match.group("language") == "de"


def test_mention_does_not_mistake_a_plain_word_for_one() -> None:
    """A first word with no `@`/`:`/`,` isn't split off as a mention -
    and since a mention is required, this message doesn't match at all."""
    reaction = Mention(1, r"hello world$")

    assert reaction.match("hello world") is None


def test_mention_leaves_no_command_text_unmatched() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org:") is None
