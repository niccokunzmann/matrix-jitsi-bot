from matrix_jitsi_bot.interactions import Mention, MessageReaction


def test_message_reaction_matches_plain_pattern() -> None:
    reaction = MessageReaction(r"hello$")

    assert reaction.match("hello")
    assert reaction.match("@bot:matrix.org: hello") is None


def test_mention_matches_without_a_mention() -> None:
    reaction = Mention(r"hello$")

    assert reaction.match("hello")


def test_mention_strips_a_colon_mention() -> None:
    reaction = Mention(r"hello$")

    assert reaction.match("@bot:matrix.org: hello")
    assert reaction.match("bot: hello")


def test_mention_strips_a_comma_mention() -> None:
    reaction = Mention(r"hello$")

    assert reaction.match("bot, hello")


def test_mention_does_not_need_whitespace_in_the_pattern() -> None:
    """`pattern` matches the same whether or not there was a mention to strip."""
    reaction = Mention(r"set language to (?P<language>\S+)$")

    with_mention = reaction.match("@bot:matrix.org: set language to de")
    without_mention = reaction.match("set language to de")

    assert with_mention.group("language") == "de"
    assert without_mention.group("language") == "de"


def test_mention_does_not_mistake_a_plain_word_for_one() -> None:
    """A first word with no `@`/`:`/`,` isn't split off as a mention."""
    reaction = Mention(r"hello world$")

    assert reaction.match("hello world")


def test_mention_leaves_no_command_text_unmatched() -> None:
    reaction = Mention(r"hello$")

    assert reaction.match("@bot:matrix.org:") is None
