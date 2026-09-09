import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from matrix_jitsi_bot.bot import (
    MatrixJitsiBot,
    _register_room_on_invite,
    _sync_room_members,
)
from matrix_jitsi_bot.db.models import Room
from matrix_jitsi_bot.interactions import AllInteractions, BotInteraction
from matrix_jitsi_bot.matrix_login import LoginFailed


@pytest.fixture
def bot() -> MatrixJitsiBot:
    return MatrixJitsiBot()


@pytest.fixture
def fake_room():
    """A `nio` room stand-in for the event-callback tests below."""
    room = MagicMock(room_id="!room:example.org")
    room.name = (
        "Team chat"  # `name=` in the constructor sets the mock's own repr, not this
    )
    return room


@pytest.fixture
def fake_event():
    """A `nio` message/invite event stand-in for the event-callback tests below."""
    return MagicMock(
        sender="@a:example.org",
        body="hello",
        event_id="$evt1",
        server_timestamp=0,
        source={},
    )


@pytest.fixture
def fake_client():
    """A `niobot` client stand-in for the event-callback tests below."""
    client = MagicMock(user_id="@bot:example.org")
    client.send_message = AsyncMock()
    client.room_leave = AsyncMock()
    client.add_reaction = AsyncMock()
    return client


@pytest.fixture
def fake_account():
    """The `Account` the bot is running as, for the event-callback tests below."""
    from matrix_jitsi_bot.db.models import Account

    return Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )


def test_create_and_list_accounts_without_test(bot: MatrixJitsiBot) -> None:
    account, created = asyncio.run(
        bot.create_account(
            "@bot:example.org",
            homeserver="https://example.org",
            password="secret",
            test=False,
        )
    )
    assert created is True
    assert account.homeserver == "https://example.org"

    accounts = bot.list_accounts()
    assert [a.user_id for a in accounts] == ["@bot:example.org"]


def test_create_account_defaults_homeserver_from_user_id(bot: MatrixJitsiBot) -> None:
    account, _ = asyncio.run(
        bot.create_account("@bot:example.org", password="secret", test=False)
    )

    assert account.homeserver == "https://example.org"


def test_create_account_test_failure_does_not_save(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    async def _fail(**_kwargs):
        raise LoginFailed("401: bad credentials")

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _fail)

    with pytest.raises(LoginFailed):
        asyncio.run(
            bot.create_account(
                "@bot:example.org",
                homeserver="https://example.org",
                password="wrong",
                test=True,
            )
        )

    assert bot.list_accounts() == []


def test_set_account_password_updates_in_place(bot: MatrixJitsiBot) -> None:
    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")

    bot.set_account_password("@bot:example.org", "newsecret")

    assert Account.objects.get(user_id="@bot:example.org").password == "newsecret"


def test_get_account_missing_raises(bot: MatrixJitsiBot) -> None:
    from matrix_jitsi_bot.db.models import Account

    with pytest.raises(Account.DoesNotExist):
        bot.get_account("@nobody:example.org")


def test_sync_members_of_creates_and_marks_leave() -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    Room.sync_members_of(
        "!room:example.org", {"@a:example.org": None}, {}, lambda _uid: 50
    )

    room = Room.objects.get(room_id="!room:example.org")
    member = RoomMember.objects.get(room=room, user_id="@a:example.org")
    assert member.membership == "join"
    assert member.power_level == 50

    Room.sync_members_of("!room:example.org", {}, {}, lambda _uid: 0)
    member.refresh_from_db()
    assert member.membership == "leave"


def test_sync_members_of_tracks_invited_users() -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    Room.sync_members_of(
        "!room:example.org", {}, {"@invitee:example.org": None}, lambda _uid: 0
    )

    room = Room.objects.get(room_id="!room:example.org")
    member = RoomMember.objects.get(room=room, user_id="@invitee:example.org")
    assert member.membership == "invite"


def test_sync_members_instance_method() -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    room = Room.objects.create(room_id="!room:example.org")
    room.sync_members({"@a:example.org": None}, {}, lambda _uid: 50)

    member = RoomMember.objects.get(room=room, user_id="@a:example.org")
    assert member.membership == "join"
    assert member.power_level == 50


def test_forget_left_rooms_forgets_rooms_in_the_sync_leave_section(
    fake_account,
) -> None:
    """Being removed from a room - by someone else, unlike the bot's own
    `leave` command - should have the same cleanup effect: the `Room`
    row (and its configuration) is gone. Detected from the raw sync
    response, not a `nio.RoomMemberEvent` callback - see
    `_sync_room_members`'s docstring for why that doesn't work.
    """
    from matrix_jitsi_bot.bot import _forget_left_rooms

    Room.objects.create(room_id="!kicked:example.org", account=fake_account)
    Room.objects.create(room_id="!still-in:example.org", account=fake_account)
    response = MagicMock(rooms=MagicMock(leave={"!kicked:example.org": MagicMock()}))

    asyncio.run(_forget_left_rooms(response))

    assert not Room.objects.filter(room_id="!kicked:example.org").exists()
    assert Room.objects.filter(room_id="!still-in:example.org").exists()


def test_sync_room_members_syncs_normally_for_other_members(
    fake_room, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    Room.objects.create(room_id="!room:example.org")
    fake_room.users = {"@a:example.org": None}
    fake_room.invited_users = {}
    fake_room.power_levels.get_user_level.return_value = 0
    event = MagicMock(state_key="@a:example.org", membership="join")

    asyncio.run(_sync_room_members(fake_account, fake_room, event))

    room = Room.objects.get(room_id="!room:example.org")
    assert room.account == fake_account
    assert RoomMember.objects.filter(room=room, user_id="@a:example.org").exists()


def test_record_message_of_creates_room_and_conversation() -> None:
    from matrix_jitsi_bot.db.models import Message

    event = MagicMock(
        sender="@a:example.org",
        event_id="$evt1",
        body="hello",
        server_timestamp=0,
        source={},
    )

    conversation, message = Room.record_message_of("!room:example.org", event)

    assert conversation.room.room_id == "!room:example.org"
    assert message.event_id == "$evt1"
    assert Message.objects.filter(event_id="$evt1").exists()


def test_record_message_instance_method() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    event = MagicMock(
        sender="@a:example.org",
        event_id="$evt1",
        body="hello",
        server_timestamp=0,
        source={},
    )

    conversation, message = room.record_message(event)

    assert conversation.room == room
    assert message.body == "hello"


def test_is_flagged_to_leave_and_forget() -> None:
    Room.objects.create(room_id="!room:example.org", should_leave=True)

    assert Room.is_flagged_to_leave("!room:example.org") is True

    Room.forget("!room:example.org")

    assert not Room.objects.filter(room_id="!room:example.org").exists()


def test_is_flagged_to_leave_false_when_not_flagged() -> None:
    Room.objects.create(room_id="!room:example.org", should_leave=False)

    assert Room.is_flagged_to_leave("!room:example.org") is False


def test_react_to_message_processes_a_message_sent_while_the_bot_was_offline(
    fake_room, fake_client
) -> None:
    """Simulates a restart: `event.server_timestamp` predates "now"
    (standing in for niobot's own process-start time, which
    `on_matrix_message` deliberately doesn't consult - see its
    docstring) by a full day, as if sent while the bot was stopped.
    """
    import time

    from matrix_jitsi_bot.db.models import Message

    class Greeter(BotInteraction):
        def react_to_matrix_message(self, conversation):
            from matrix_jitsi_bot.db.models import CommandReply

            reply = CommandReply(text="hello", message=conversation.last_message)
            reply.save()
            return reply

    old_event = MagicMock(
        sender="@a:example.org",
        body="hello",
        event_id="$offline1",
        server_timestamp=int((time.time() - 86400) * 1000),
        source={},
    )

    asyncio.run(Greeter().on_matrix_message(fake_client, fake_room, old_event))

    assert Message.objects.filter(event_id="$offline1").exists()
    fake_client.send_message.assert_awaited_once()


def test_react_to_message_does_not_reprocess_an_already_recorded_event(
    fake_room, fake_client
) -> None:
    class Counter(BotInteraction):
        replies = 0

        def react_to_matrix_message(self, conversation):
            from matrix_jitsi_bot.db.models import CommandReply

            Counter.replies += 1
            reply = CommandReply(text="hello", message=conversation.last_message)
            reply.save()
            return reply

    event = MagicMock(
        sender="@a:example.org",
        body="hello",
        event_id="$dup1",
        server_timestamp=0,
        source={},
    )

    interaction = Counter()
    asyncio.run(interaction.on_matrix_message(fake_client, fake_room, event))
    asyncio.run(interaction.on_matrix_message(fake_client, fake_room, event))

    assert Counter.replies == 1
    fake_client.send_message.assert_awaited_once()


def test_react_to_message_survives_a_failing_interaction(
    fake_room, fake_event, fake_client
) -> None:
    class Boom(BotInteraction):
        def react_to_matrix_message(self, conversation):
            raise RuntimeError("boom")

    # Doesn't raise - the exception is caught and logged, not propagated.
    asyncio.run(Boom().on_matrix_message(fake_client, fake_room, fake_event))


def test_react_to_message_sends_a_command_reply(
    fake_room, fake_event, fake_client
) -> None:
    class Greeter(BotInteraction):
        def react_to_matrix_message(self, conversation):
            from matrix_jitsi_bot.db.models import CommandReply

            reply = CommandReply(text="hello", message=conversation.last_message)
            reply.save()
            return reply

    asyncio.run(Greeter().on_matrix_message(fake_client, fake_room, fake_event))

    fake_client.send_message.assert_awaited_once()


def test_react_to_message_does_not_propagate_a_recording_failure(
    fake_room, fake_event, fake_client, monkeypatch
) -> None:
    def _fail(*_args, **_kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr("matrix_jitsi_bot.db.models.room.Room.record_message_of", _fail)

    asyncio.run(BotInteraction().on_matrix_message(fake_client, fake_room, fake_event))


def test_bot_defaults_to_all_interactions(bot: MatrixJitsiBot) -> None:
    assert isinstance(bot.interaction, AllInteractions)


def test_bot_accepts_a_different_interaction() -> None:
    class Custom(BotInteraction):
        pass

    custom = Custom()
    bot = MatrixJitsiBot(custom)

    assert bot.interaction is custom


def test_leave_if_flagged_leaves_and_forgets_the_room(fake_client) -> None:
    from matrix_jitsi_bot.db.models import Room

    Room.objects.create(room_id="!room:example.org", should_leave=True)

    asyncio.run(MatrixJitsiBot.leave_if_flagged(fake_client, "!room:example.org"))

    fake_client.room_leave.assert_awaited_once_with("!room:example.org")
    assert not Room.objects.filter(room_id="!room:example.org").exists()


def test_leave_if_flagged_does_nothing_when_not_flagged(fake_client) -> None:
    from matrix_jitsi_bot.db.models import Room

    Room.objects.create(room_id="!room:example.org", should_leave=False)

    asyncio.run(MatrixJitsiBot.leave_if_flagged(fake_client, "!room:example.org"))

    fake_client.room_leave.assert_not_awaited()
    assert Room.objects.filter(room_id="!room:example.org").exists()


def test_register_room_on_invite_creates_a_room(
    fake_room, fake_client, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import Room

    event = MagicMock(state_key="@bot:example.org")

    asyncio.run(_register_room_on_invite(fake_client, fake_account, fake_room, event))

    assert Room.objects.filter(room_id="!room:example.org").exists()
    fake_client.room_leave.assert_not_awaited()
    fake_client.send_message.assert_awaited_once()
    assert "configured" in fake_client.send_message.await_args.args[1]


def test_register_room_on_invite_does_not_re_announce_an_existing_room(
    fake_room, fake_client, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import Room

    Room.objects.create(room_id="!room:example.org")
    event = MagicMock(state_key="@bot:example.org")

    asyncio.run(_register_room_on_invite(fake_client, fake_account, fake_room, event))

    fake_client.send_message.assert_not_awaited()


def test_register_room_on_invite_leaves_a_no_bot_room(
    fake_room, fake_client, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import Room

    fake_room.name = "Team chat (no-bot)"  # see fake_room's own note
    event = MagicMock(state_key="@bot:example.org")

    asyncio.run(_register_room_on_invite(fake_client, fake_account, fake_room, event))

    assert not Room.objects.filter(room_id="!room:example.org").exists()
    fake_client.room_leave.assert_awaited_once_with("!room:example.org")


def test_register_room_on_invite_ignores_other_invites(
    fake_room, fake_client, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import Room

    event = MagicMock(state_key="@someone-else:example.org")

    asyncio.run(_register_room_on_invite(fake_client, fake_account, fake_room, event))

    assert not Room.objects.filter(room_id="!room:example.org").exists()


def test_reconcile_joined_rooms_recreates_a_missing_room(
    fake_client, fake_account
) -> None:
    """The bot is already joined to a room (per the live client) but its
    `Room` row is missing - e.g. the database was reset - so it's
    recreated (bare, unconfigured) and announced.
    """
    fake_client.rooms = {"!already-joined:example.org": MagicMock()}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(fake_client, fake_account))

    assert Room.objects.filter(room_id="!already-joined:example.org").exists()
    fake_client.send_message.assert_awaited_once()
    assert "configured" in fake_client.send_message.await_args.args[1]


def test_reconcile_joined_rooms_does_not_touch_an_existing_room(
    fake_client, fake_account
) -> None:
    Room.objects.create(room_id="!already-configured:example.org", paused=True)
    fake_client.rooms = {"!already-configured:example.org": MagicMock()}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(fake_client, fake_account))

    room = Room.objects.get(room_id="!already-configured:example.org")
    assert room.paused is True
    fake_client.send_message.assert_not_awaited()


def test_reconcile_joined_rooms_forgets_a_room_no_longer_joined(
    fake_client, fake_account
) -> None:
    """The bot was removed from a room (kicked, banned, or otherwise)
    while this process wasn't running to see the live membership
    change - the next startup's reconciliation catches it instead, by
    comparing what's tagged to this account against what's actually
    still joined (`client.rooms`, from a fresh sync).
    """
    Room.objects.create(room_id="!no-longer-joined:example.org", account=fake_account)
    fake_client.rooms = {}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(fake_client, fake_account))

    assert not Room.objects.filter(room_id="!no-longer-joined:example.org").exists()


def test_reconcile_joined_rooms_does_not_forget_another_accounts_room(
    fake_client, fake_account
) -> None:
    from matrix_jitsi_bot.db.models import Account

    other_account = Account.objects.create(
        user_id="@other:example.org", homeserver="https://example.org"
    )
    Room.objects.create(room_id="!someone-elses:example.org", account=other_account)
    fake_client.rooms = {}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(fake_client, fake_account))

    assert Room.objects.filter(room_id="!someone-elses:example.org").exists()


def test_react_to_message_discards_an_unimportant_unaddressed_message(
    fake_room, fake_client
) -> None:
    from matrix_jitsi_bot.db.models import Message
    from matrix_jitsi_bot.interactions import BotInteraction

    event = MagicMock(
        sender="@a:example.org",
        body="just some chatter, not addressed to the bot",
        event_id="$evt1",
        server_timestamp=0,
        source={},
    )

    asyncio.run(BotInteraction().on_matrix_message(fake_client, fake_room, event))

    assert not Message.objects.filter(event_id="$evt1").exists()


def test_react_to_message_keeps_a_message_mentioning_the_bot(
    fake_room, fake_client
) -> None:
    from matrix_jitsi_bot.db.models import Message
    from matrix_jitsi_bot.interactions import BotInteraction

    event = MagicMock(
        sender="@a:example.org",
        body="hey @bot:example.org did you see this?",
        event_id="$evt1",
        server_timestamp=0,
        source={},
    )

    asyncio.run(BotInteraction().on_matrix_message(fake_client, fake_room, event))

    assert Message.objects.filter(event_id="$evt1").exists()


def test_react_to_message_keeps_a_replied_to_message(
    fake_room, fake_event, fake_client
) -> None:
    from matrix_jitsi_bot.db.models import Message
    from matrix_jitsi_bot.interactions import BotInteraction

    class Greeter(BotInteraction):
        def react_to_matrix_message(self, conversation):
            from matrix_jitsi_bot.db.models import CommandReply

            reply = CommandReply(text="hello", message=conversation.last_message)
            reply.save()
            return reply

    asyncio.run(Greeter().on_matrix_message(fake_client, fake_room, fake_event))

    assert Message.objects.filter(event_id=fake_event.event_id).exists()


def test_react_to_message_prunes_beyond_max_history(
    fake_room, fake_client, monkeypatch
) -> None:
    from matrix_jitsi_bot.db.models import Conversation, Message, Room
    from matrix_jitsi_bot.interactions import BotInteraction

    monkeypatch.setattr("django.conf.settings.MAX_CONVERSATION_MESSAGES", 3)

    room = Room.objects.create(room_id="!room:example.org")
    conversation = Conversation.objects.create(room=room)
    for i in range(3):
        Message.objects.create(
            conversation=conversation,
            sender="@bot:example.org",  # mentions itself - always kept
            event_id=f"$old{i}",
            body="hey @bot:example.org",
            server_timestamp="2020-01-01T00:00:00Z",
        )

    event = MagicMock(
        sender="@a:example.org",
        body="hey @bot:example.org",
        event_id="$new",
        server_timestamp=0,
        source={},
    )

    asyncio.run(BotInteraction().on_matrix_message(fake_client, fake_room, event))

    assert Message.objects.filter(conversation=conversation).count() == 3
    assert Message.objects.filter(event_id="$new").exists()
    assert not Message.objects.filter(event_id="$old0").exists()


def test_messages_for_opened_without_starts_is_the_plain_message() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_open=True
    )
    change = JitsiChange(opened=True, closed=False, starters=None, joined=[], left=[])

    assert change.messages_for(jitsi_room, tracked) == [
        "Conference https://meet.example.org/Room started"
    ]


def test_messages_for_opened_with_starts_combines_into_one_message() -> None:
    """A tracker wanting both `track_open` and `track_starts` gets one
    combined message, not two redundant ones about the same opening.
    """
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_open=True, track_starts=True
    )
    change = JitsiChange(
        opened=True, closed=False, starters=["Alice"], joined=[], left=[]
    )

    assert change.messages_for(jitsi_room, tracked) == [
        "Alice started the conference at https://meet.example.org/Room"
    ]


def test_messages_for_closed() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_close=True
    )
    change = JitsiChange(opened=False, closed=True, starters=None, joined=[], left=[])

    assert change.messages_for(jitsi_room, tracked) == [
        "Conference https://meet.example.org/Room ended"
    ]


def test_messages_for_joins_and_leaves() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_joins=True, track_leaves=True
    )
    change = JitsiChange(
        opened=False, closed=False, starters=None, joined=["Bob"], left=["Alice"]
    )

    assert change.messages_for(jitsi_room, tracked) == [
        "Bob joined https://meet.example.org/Room",
        "Alice left https://meet.example.org/Room",
    ]


def test_messages_for_nothing_tracked_is_empty() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_close=True
    )
    change = JitsiChange(opened=True, closed=False, starters=None, joined=[], left=[])

    assert change.messages_for(jitsi_room, tracked) == []


def test_trackers_of_open_change_only_needs_track_open() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    open_room = Room.objects.create(room_id="!open:example.org")
    TrackedJitsiRoom.objects.create(
        room=open_room, jitsi_room=jitsi_room, track_open=True
    )
    joins_room = Room.objects.create(room_id="!joins:example.org")
    TrackedJitsiRoom.objects.create(
        room=joins_room, jitsi_room=jitsi_room, track_joins=True
    )

    change = JitsiChange(opened=True, closed=False, starters=None, joined=[], left=[])
    trackers = jitsi_room.trackers_of(change)

    assert [t.room.room_id for t in trackers] == ["!open:example.org"]


def test_trackers_of_joins_only_notifies_trackers_wanting_joins() -> None:
    """A room tracking only joins must still hear about a join even
    though nothing opened or closed - joins/leaves are independent of
    the open/close flags.
    """
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    open_room = Room.objects.create(room_id="!open:example.org")
    TrackedJitsiRoom.objects.create(
        room=open_room, jitsi_room=jitsi_room, track_open=True
    )
    joins_room = Room.objects.create(room_id="!joins:example.org")
    TrackedJitsiRoom.objects.create(
        room=joins_room, jitsi_room=jitsi_room, track_joins=True
    )

    change = JitsiChange(
        opened=False, closed=False, starters=None, joined=["Alice"], left=[]
    )
    trackers = jitsi_room.trackers_of(change)

    assert [t.room.room_id for t in trackers] == ["!joins:example.org"]


def test_trackers_of_ignores_paused_rooms() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiChange

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    paused_room = Room.objects.create(room_id="!paused:example.org", paused=True)
    TrackedJitsiRoom.objects.create(
        room=paused_room, jitsi_room=jitsi_room, track_open=True
    )

    change = JitsiChange(opened=True, closed=False, starters=None, joined=[], left=[])
    trackers = jitsi_room.trackers_of(change)

    assert trackers == []


def test_poll_jitsi_rooms_once_checks_due_rooms_and_notifies(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiStatus

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_open=True, track_close=True
    )

    async def _fake_check(url, *, want_participants):
        # Only open/close is tracked here, so participants shouldn't be fetched.
        assert want_participants is False
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(bot.poll_jitsi_rooms_once(client))

    jitsi_room.refresh_from_db()
    assert jitsi_room.is_open is True
    client.send_message.assert_awaited_once_with(
        "!room:example.org", "Conference https://meet.example.org/Room started"
    )


def test_poll_jitsi_rooms_once_fetches_participants_only_on_the_opening_check(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from django.utils import timezone

    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiStatus

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_open=True, track_starts=True
    )

    calls = []

    async def _fake_check(url, *, want_participants):
        calls.append(want_participants)
        if want_participants:
            return JitsiStatus(is_open=True, participants=["Alice"])
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(bot.poll_jitsi_rooms_once(client))

    jitsi_room.refresh_from_db()
    jitsi_room.next_check_at = timezone.now()
    jitsi_room.save()
    asyncio.run(bot.poll_jitsi_rooms_once(client))

    # Fetched on the closed -> open transition, not on the following check
    # while it's still open - see `JitsiRoom.wants_participants_check`.
    assert calls == [True, False]


def test_poll_jitsi_rooms_once_skips_rooms_not_due(bot: MatrixJitsiBot) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from matrix_jitsi_bot.db.models import JitsiRoom

    JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        next_check_at=timezone.now() + timedelta(minutes=5),
    )

    # No mocked check_jitsi_room - would raise if this room were (wrongly) checked.
    asyncio.run(bot.poll_jitsi_rooms_once(AsyncMock()))


def test_poll_jitsi_rooms_once_survives_a_failing_check(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom

    JitsiRoom.objects.create(url="https://meet.example.org/Room")

    async def _boom(url, *, want_participants):
        raise RuntimeError("network is on fire")

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _boom)

    # Doesn't raise - the exception is caught and logged, not propagated.
    asyncio.run(bot.poll_jitsi_rooms_once(AsyncMock()))


def test_poll_jitsi_rooms_all_checks_a_room_not_due_yet(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    """Unlike `poll_jitsi_rooms_once`, `poll_jitsi_rooms_all` checks
    every tracked conference regardless of `next_check_at` - so a
    single `run --once` invocation can guarantee everything was
    actually queried.
    """
    from datetime import timedelta

    from django.utils import timezone

    from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiStatus

    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        next_check_at=timezone.now() + timedelta(minutes=5),
    )
    room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, track_open=True)

    calls = []

    async def _fake_check(url, *, want_participants):
        calls.append(url)
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    count = asyncio.run(bot.poll_jitsi_rooms_all(AsyncMock()))

    assert calls == ["https://meet.example.org/Room"]
    assert count == 1


def test_poll_jitsi_rooms_all_ignores_untracked_rooms(bot: MatrixJitsiBot) -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom

    JitsiRoom.objects.create(url="https://meet.example.org/Room")

    # No mocked check_jitsi_room - would raise if this room were (wrongly) checked.
    count = asyncio.run(bot.poll_jitsi_rooms_all(AsyncMock()))

    assert count == 0


def test_run_once_checks_every_tracked_room_and_returns_the_count(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    from matrix_jitsi_bot.db.models import Account, JitsiRoom, Room, TrackedJitsiRoom
    from matrix_jitsi_bot.jitsi import JitsiStatus

    Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org", password="secret"
    )
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, track_open=True)

    async def _fake_check(url, *, want_participants):
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    fake_client = AsyncMock()
    reconciled = asyncio.Event()
    reconciled.set()  # simulates the first sync having already completed

    def _build_client(self, account):
        return fake_client, reconciled

    async def _start_client(client, account):
        await asyncio.sleep(3600)  # simulates a sync loop that keeps running

    monkeypatch.setattr(MatrixJitsiBot, "_build_client", _build_client)
    monkeypatch.setattr(MatrixJitsiBot, "_start_client", staticmethod(_start_client))

    count = asyncio.run(bot.run_once("@bot:example.org"))

    assert count == 1


def test_run_once_propagates_a_client_failure_before_ready(
    bot: MatrixJitsiBot, monkeypatch
) -> None:
    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org", password="secret"
    )

    fake_client = AsyncMock()
    reconciled = asyncio.Event()  # never set - simulates never reaching first sync

    def _build_client(self, account):
        return fake_client, reconciled

    async def _start_client(client, account):
        raise RuntimeError("bad credentials")

    monkeypatch.setattr(MatrixJitsiBot, "_build_client", _build_client)
    monkeypatch.setattr(MatrixJitsiBot, "_start_client", staticmethod(_start_client))

    with pytest.raises(RuntimeError, match="bad credentials"):
        asyncio.run(bot.run_once("@bot:example.org"))
