from matrix_jitsi_bot.interactions import RoomInteraction


def test_pause_requires_a_moderator(send_message) -> None:
    conv = send_message("@bot: pause tracking", sender="@user:example.org")

    result = RoomInteraction().react_to_matrix_message(conv)

    assert "only room moderators" in result.text
    assert conv.room.paused is False


def test_pause_by_a_moderator(send_message, make_moderator) -> None:
    conv = send_message("@bot: pause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = RoomInteraction().react_to_matrix_message(conv)

    assert result.text == "Tracking paused."
    conv.room.refresh_from_db()
    assert conv.room.paused is True


def test_pause_when_already_paused_gives_the_generic_paused_reply(
    send_message, make_moderator
) -> None:
    """A paused room "does not react to anything" (per the spec) - even
    a redundant "pause tracking" gets the generic paused reply, not a
    dedicated "already paused" one - see `react_while_paused`.
    """
    conv = send_message("@bot: pause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    conv.room.paused = True
    conv.room.save(update_fields=["paused"])

    result = RoomInteraction().react_to_matrix_message(conv)

    assert "This room is paused" in result.text


def test_unpause_by_a_moderator(send_message, make_moderator) -> None:
    conv = send_message("@bot: unpause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    conv.room.paused = True
    conv.room.save(update_fields=["paused"])

    result = RoomInteraction().react_to_matrix_message(conv)

    assert result.text == "Tracking resumed."
    conv.room.refresh_from_db()
    assert conv.room.paused is False


def test_unpause_when_not_paused(send_message, make_moderator) -> None:
    conv = send_message("@bot: unpause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = RoomInteraction().react_to_matrix_message(conv)

    assert result.text == "Tracking isn't paused."


def test_while_paused_blocks_other_commands(send_message, make_moderator) -> None:
    conv = send_message("@bot: pause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    interaction = RoomInteraction()
    interaction.react_to_matrix_message(conv)

    conv = send_message("@bot: leave", sender="@mod:example.org")
    result = interaction.react_to_matrix_message(conv)

    assert "paused" in result.text
    assert "unpause tracking" in result.text


def test_while_paused_still_allows_unpausing(send_message, make_moderator) -> None:
    conv = send_message("@bot: pause tracking", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    interaction = RoomInteraction()
    interaction.react_to_matrix_message(conv)

    conv = send_message("@bot: unpause tracking", sender="@mod:example.org")
    result = interaction.react_to_matrix_message(conv)

    assert result.text == "Tracking resumed."


def test_leave_requires_a_moderator(send_message) -> None:
    conv = send_message("@bot: leave", sender="@user:example.org")

    result = RoomInteraction().react_to_matrix_message(conv)

    assert "only room moderators" in result.text
    assert conv.room.should_leave is False


def test_leave_by_a_moderator_flags_the_room(send_message, make_moderator) -> None:
    conv = send_message("@bot: leave", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = RoomInteraction().react_to_matrix_message(conv)

    assert result.text == "Leaving this room now. Goodbye!"
    conv.room.refresh_from_db()
    assert conv.room.should_leave is True
