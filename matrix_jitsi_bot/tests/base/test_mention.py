from matrix_jitsi_bot.interactions import Mention

_BOT = "@bot:matrix.org"


def test_mention_requires_a_mention() -> None:
    """The bot only reacts to messages addressed to it - a bare command
    with no mention at all does not match."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("hello", _BOT) is None


def test_mention_matches_a_colon_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org: hello", _BOT)
    assert reaction.match("bot: hello", _BOT)


def test_mention_matches_a_comma_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("bot, hello", _BOT)


def test_mention_matches_the_bare_full_id_with_no_trailing_punctuation() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org hello", _BOT)


def test_mention_does_not_need_whitespace_in_the_pattern() -> None:
    r"""`pattern` only ever sees the text after the mention was stripped -
    it never has to account for `\s` around the mention itself."""
    reaction = Mention(1, r"set language to (?P<language>\S+)$")

    match = reaction.match("@bot:matrix.org: set language to de", _BOT)

    assert match.group("language") == "de"


def test_mention_does_not_mistake_a_plain_word_for_one() -> None:
    """A first word with no `@`/`:`/`,` isn't split off as a mention -
    and since a mention is required, this message doesn't match at all."""
    reaction = Mention(1, r"hello world$")

    assert reaction.match("hello world", _BOT) is None


def test_mention_leaves_no_command_text_unmatched() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org:", _BOT) is None


def test_mention_ignores_a_message_addressed_to_somebody_else() -> None:
    """Regression test: the bot must not reply to a message that only
    *looks* like a mention (address-shaped first word) but is actually
    addressed to a different Matrix user entirely."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("@alice:matrix.org: hello", _BOT) is None
    assert reaction.match("alice: hello", _BOT) is None
    assert reaction.match("alice, hello", _BOT) is None


def test_mention_ignores_another_bot_with_the_same_localpart_elsewhere() -> None:
    """A full-ID mention for a different homeserver must not be
    mistaken for this bot, even if the localpart matches."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:other.org: hello", _BOT) is None


def test_mention_with_no_bot_identity_falls_back_to_shape_only() -> None:
    """A bare `Mention` used with `bot_user_id=None` (no live client
    context, e.g. outside `BotInteraction.on_matrix_message`) falls
    back to the old, permissive "any address-shaped word" check."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("@alice:matrix.org: hello", None)
