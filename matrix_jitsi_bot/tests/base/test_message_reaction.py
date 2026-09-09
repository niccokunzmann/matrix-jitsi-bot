import pytest

from matrix_jitsi_bot.interactions import BotInteraction, MessageReaction, Skipped


class Greeter(BotInteraction):
    @MessageReaction(1, r"hello (?P<name>\w+)")
    def react_to_greeting(self, name: str) -> str:
        return f"Hello, {name}!"

    @MessageReaction(2, r"remember (?P<note>.+)")
    def react_to_remember(self, note: str):
        from matrix_jitsi_bot.db.models import CommandReply

        return CommandReply(text=f"Noted: {note}")

    @MessageReaction(3, r"ignore me")
    def react_to_ignore(self):
        return None

    @MessageReaction(4, r"skip me")
    def react_to_skip(self):
        return Skipped()

    @MessageReaction(5, r"skip me")
    def react_to_skip_fallback(self) -> str:
        return "caught by the fallback"


@pytest.fixture
def greeter() -> Greeter:
    return Greeter()


def test_plain_string_reply_becomes_a_command_reply(send_message, greeter) -> None:
    from matrix_jitsi_bot.db.models import CommandReply

    conv = send_message("hello world")

    result = greeter.react_to_matrix_message(conv)

    assert isinstance(result, CommandReply)
    assert result.text == "Hello, world!"


def test_no_handler_matches(send_message, greeter) -> None:
    conv = send_message("this matches nothing")

    assert greeter.react_to_matrix_message(conv) is None


def test_handler_returning_none_falls_through(send_message, greeter) -> None:
    conv = send_message("ignore me")

    assert greeter.react_to_matrix_message(conv) is None


def test_handler_returning_skipped_tries_the_next_reaction(
    send_message, greeter
) -> None:
    conv = send_message("skip me")

    result = greeter.react_to_matrix_message(conv)

    assert result.text == "caught by the fallback"


def test_reactions_are_ordered_by_id_not_declaration_order(send_message) -> None:
    class OutOfOrder(BotInteraction):
        @MessageReaction(2, r"hi$")
        def second(self) -> str:
            return "second"

        @MessageReaction(1, r"hi$")
        def first(self) -> str:
            return "first"

    interaction = OutOfOrder()

    assert [reaction.id for reaction in interaction.reactions] == [1, 2]

    conv = send_message("hi")
    assert interaction.react_to_matrix_message(conv).text == "first"


def test_whitespace_is_normalised_before_matching(send_message, greeter) -> None:
    conv = send_message("hello   \n  world\t")

    assert greeter.react_to_matrix_message(conv).text == "Hello, world!"


def test_command_reply_is_persisted(send_message, greeter) -> None:
    from matrix_jitsi_bot.db.models import CommandReply

    conv = send_message("remember buy milk", sender="@a:example.org")

    result = greeter.react_to_matrix_message(conv)

    assert isinstance(result, CommandReply)
    assert result.pk is not None
    assert result.sent is False
    saved = CommandReply.objects.get(pk=result.pk)
    assert saved.message.body == "remember buy milk"
    assert saved.message.sender == "@a:example.org"
    assert saved.text == "Noted: buy milk"


def test_conversation_without_messages_raises(greeter) -> None:
    from matrix_jitsi_bot.db.models import Conversation, Room

    room = Room.objects.create(room_id="!empty:example.org")
    conv = Conversation.objects.create(room=room)

    with pytest.raises(ValueError, match="no recorded messages"):
        greeter.react_to_matrix_message(conv)
