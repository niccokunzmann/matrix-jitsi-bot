from matrix_jitsi_bot.db.models import Account, Conversation, Message, Room, RoomMember


def test_ensure_account_tags_an_untagged_room() -> None:
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    room = Room.objects.create(room_id="!room:example.org")

    room.ensure_account(account)

    assert room.account == account


def test_ensure_account_does_not_overwrite_an_existing_tag() -> None:
    original = Account.objects.create(
        user_id="@original:example.org", homeserver="https://example.org"
    )
    other = Account.objects.create(
        user_id="@other:example.org", homeserver="https://example.org"
    )
    room = Room.objects.create(room_id="!room:example.org", account=original)

    room.ensure_account(other)

    room.refresh_from_db()
    assert room.account == original


def test_ensure_account_is_a_no_op_for_none() -> None:
    room = Room.objects.create(room_id="!room:example.org")

    room.ensure_account(None)

    assert room.account is None


def test_forget_others_deletes_rooms_not_in_keep_list() -> None:
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    Room.objects.create(room_id="!keep:example.org", account=account)
    Room.objects.create(room_id="!gone:example.org", account=account)

    forgotten = Room.forget_others(account, ["!keep:example.org"])

    assert forgotten == ["!gone:example.org"]
    assert Room.objects.filter(room_id="!keep:example.org").exists()
    assert not Room.objects.filter(room_id="!gone:example.org").exists()


def test_forget_others_ignores_rooms_tagged_to_a_different_account() -> None:
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    other = Account.objects.create(
        user_id="@other:example.org", homeserver="https://example.org"
    )
    Room.objects.create(room_id="!not-mine:example.org", account=other)

    forgotten = Room.forget_others(account, [])

    assert forgotten == []
    assert Room.objects.filter(room_id="!not-mine:example.org").exists()


def test_forget_others_ignores_untagged_rooms() -> None:
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    Room.objects.create(room_id="!untagged:example.org")

    forgotten = Room.forget_others(account, [])

    assert forgotten == []
    assert Room.objects.filter(room_id="!untagged:example.org").exists()


def test_sanitized_body_collapses_whitespace() -> None:
    message = Message(body="hello   \n  world\t\tagain")
    assert message.sanitized_body == "hello world again"


def test_sanitized_body_strips_leading_trailing_whitespace() -> None:
    message = Message(body="  hi  ")
    assert message.sanitized_body == "hi"


def test_mentions_bot_true_when_user_id_appears_anywhere() -> None:
    message = Message(body="hey @bot:example.org, are you there?")
    assert message.mentions_bot("@bot:example.org") is True


def test_mentions_bot_false_when_absent() -> None:
    message = Message(body="just some chatter")
    assert message.mentions_bot("@bot:example.org") is False


def test_prune_deletes_unimportant_message() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    conversation = Conversation.objects.create(room=room)
    message = Message.objects.create(
        conversation=conversation,
        sender="@a:example.org",
        event_id="$1",
        body="chatter",
        server_timestamp="2020-01-01T00:00:00Z",
    )

    conversation.prune(message.id, important=False)

    assert not Message.objects.filter(id=message.id).exists()


def test_prune_keeps_important_message() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    conversation = Conversation.objects.create(room=room)
    message = Message.objects.create(
        conversation=conversation,
        sender="@a:example.org",
        event_id="$1",
        body="hey @bot:example.org",
        server_timestamp="2020-01-01T00:00:00Z",
    )

    conversation.prune(message.id, important=True)

    assert Message.objects.filter(id=message.id).exists()


def test_prune_trims_beyond_max_history(monkeypatch) -> None:
    monkeypatch.setattr("django.conf.settings.MAX_CONVERSATION_MESSAGES", 2)
    room = Room.objects.create(room_id="!room:example.org")
    conversation = Conversation.objects.create(room=room)
    messages = [
        Message.objects.create(
            conversation=conversation,
            sender="@bot:example.org",
            event_id=f"$old{i}",
            body="hey @bot:example.org",
            server_timestamp="2020-01-01T00:00:00Z",
        )
        for i in range(3)
    ]

    conversation.prune(messages[-1].id, important=True)

    assert Message.objects.filter(conversation=conversation).count() == 2
    assert not Message.objects.filter(id=messages[0].id).exists()


def test_room_is_moderator_true_at_threshold() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    assert room.is_moderator("@mod:example.org") is True


def test_room_is_moderator_false_below_threshold() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@user:example.org", power_level=0)

    assert room.is_moderator("@user:example.org") is False


def test_room_is_moderator_false_for_unknown_user() -> None:
    room = Room.objects.create(room_id="!room:example.org")

    assert room.is_moderator("@stranger:example.org") is False
