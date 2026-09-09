from matrix_jitsi_bot.interactions import GreetingInteraction


def test_hello_needs_a_mention(send_message) -> None:
    """The bot only reacts to messages addressed to it."""
    conv = send_message("hello")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result is None


def test_hello_when_mentioned(send_message) -> None:
    conv = send_message("@bot:matrix.org: hello")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result.text == "Hello!"


def test_unrelated_message_is_ignored(send_message) -> None:
    conv = send_message("@bot:matrix.org: hello world")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result is None
