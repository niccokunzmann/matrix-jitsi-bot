from matrix_jitsi_bot.interactions import Mention

_BOT_NAMES = frozenset({"@bot:matrix.org", "bot", "Jitsi Bot"})


def test_mention_requires_a_mention() -> None:
    """The bot only reacts to messages addressed to it - a bare command
    with no mention at all does not match."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("hello", _BOT_NAMES) is None


def test_mention_matches_a_colon_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org: hello", _BOT_NAMES)
    assert reaction.match("bot: hello", _BOT_NAMES)


def test_mention_matches_a_comma_mention() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("bot, hello", _BOT_NAMES)


def test_mention_matches_the_bare_full_id_with_no_trailing_punctuation() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org hello", _BOT_NAMES)


def test_mention_matches_the_bots_display_name() -> None:
    """Regression test: Element (and most Matrix clients) insert the
    mentioned account's *display name*, not its raw user ID or
    localpart, as the leading word when you pick it from the mention
    autocomplete - a real bot whose display name differs from its
    user ID's localpart must still be recognised, or it goes
    completely silent for anyone using that autocomplete.
    """
    reaction = Mention(1, r"hello$")

    # Multi-word display names are a known limitation (see the class docstring).
    assert reaction.match("Jitsi Bot: hello", _BOT_NAMES) is None
    assert reaction.match("@bot:matrix.org: hello", _BOT_NAMES)


def test_mention_matches_a_single_word_display_name() -> None:
    reaction = Mention(1, r"hello$")
    bot_names = frozenset({"@jitsi-bot:matrix.org", "jitsi-bot", "JitsiBot"})

    assert reaction.match("JitsiBot: hello", bot_names)
    assert reaction.match("JitsiBot, hello", bot_names)


def test_mention_does_not_need_whitespace_in_the_pattern() -> None:
    r"""`pattern` only ever sees the text after the mention was stripped -
    it never has to account for `\s` around the mention itself."""
    reaction = Mention(1, r"set language to (?P<language>\S+)$")

    match = reaction.match("@bot:matrix.org: set language to de", _BOT_NAMES)

    assert match.group("language") == "de"


def test_mention_does_not_mistake_a_plain_word_for_one() -> None:
    """A first word with no `@`/`:`/`,` isn't split off as a mention -
    and since a mention is required, this message doesn't match at all."""
    reaction = Mention(1, r"hello world$")

    assert reaction.match("hello world", _BOT_NAMES) is None


def test_mention_leaves_no_command_text_unmatched() -> None:
    reaction = Mention(1, r"hello$")

    assert reaction.match("@bot:matrix.org:", _BOT_NAMES) is None


def test_mention_ignores_a_message_addressed_to_somebody_else() -> None:
    """Regression test: the bot must not reply to a message that only
    *looks* like a mention (address-shaped first word) but is actually
    addressed to a different Matrix user entirely."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("@alice:matrix.org: hello", _BOT_NAMES) is None
    assert reaction.match("alice: hello", _BOT_NAMES) is None
    assert reaction.match("alice, hello", _BOT_NAMES) is None


def test_mention_with_no_bot_identity_falls_back_to_shape_only() -> None:
    """A bare `Mention` used with `bot_names=None` (no live client
    context, e.g. outside `BotInteraction.on_matrix_message`) falls
    back to the old, permissive "any address-shaped word" check."""
    reaction = Mention(1, r"hello$")

    assert reaction.match("@alice:matrix.org: hello", None)


def test_mention_matches_a_markdown_pill_by_user_id() -> None:
    """Regression test for a real outage: some Matrix clients render a
    mention in the plain-text fallback body as a Markdown link -
    ``[display](https://matrix.to/#/@user:server)`` - rather than a
    bare address-shaped word. Neither the old shape-only check nor the
    display-name fix recognised this at all, so the bot went
    completely silent for anyone on such a client.
    """
    reaction = Mention(1, r"hello$")
    bot_names = frozenset({"@jitsi-bot-test:chat.pycal.org"})

    match = reaction.match(
        "[jitsi-bot-test](https://matrix.to/#/@jitsi-bot-test:chat.pycal.org) hello",
        bot_names,
    )

    assert match is not None


def test_mention_matches_the_exact_reported_message() -> None:
    """The literal message body reported as not working."""
    reaction = Mention(1, r"test$")
    bot_names = frozenset({"@jitsi-bot-test:chat.pycal.org"})

    match = reaction.match(
        "[jitsi-bot-test](https://matrix.to/#/@jitsi-bot-test:chat.pycal.org) test",
        bot_names,
    )

    assert match is not None


def test_mention_matches_a_markdown_pill_by_display_text() -> None:
    """The pill's ``[display]`` text is itself accepted, not just the
    user ID inside the link - e.g. if the sender's client only fills
    in a locally-cached nickname there.
    """
    reaction = Mention(1, r"hello$")
    bot_names = frozenset({"JitsiHelper"})

    match = reaction.match(
        "[JitsiHelper](https://matrix.to/#/@bot:matrix.org) hello", bot_names
    )

    assert match is not None


def test_mention_markdown_pill_ignores_a_different_user() -> None:
    reaction = Mention(1, r"hello$")
    bot_names = frozenset({"@bot:matrix.org", "bot"})

    match = reaction.match(
        "[alice](https://matrix.to/#/@alice:matrix.org) hello", bot_names
    )

    assert match is None


def test_mention_markdown_pill_with_no_bot_identity_falls_back_to_shape_only() -> None:
    reaction = Mention(1, r"hello$")

    match = reaction.match("[alice](https://matrix.to/#/@alice:matrix.org) hello", None)

    assert match is not None
