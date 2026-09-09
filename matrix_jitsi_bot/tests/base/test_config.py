from matrix_jitsi_bot.interactions import BotInteraction, Config
from matrix_jitsi_bot.interactions.base import CommandError, Mention


class Settings(BotInteraction):
    @Config(1, r"set language to (?P<language>\S+)$")
    def react_to_set_language(self, language: str) -> str:
        return f"Language set to {language}."


class FailableSettings(BotInteraction):
    @Config(1, r"do something$")
    def react_to_do_something(self) -> str:
        raise CommandError("nope, that failed")


class Query(BotInteraction):
    @Mention(1, r"ping$")
    def react_to_ping(self) -> str:
        return "pong"


def test_config_rejects_a_non_moderator(send_message) -> None:
    conv = send_message("@bot: set language to de", sender="@user:example.org")

    result = Settings().react_to_matrix_message(conv)

    assert "only room moderators" in result.text


def test_config_accepts_a_moderator(send_message, make_moderator) -> None:
    conv = send_message("@bot: set language to de", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = Settings().react_to_matrix_message(conv)

    assert result.text == "Language set to de."


def test_config_success_reacts_with_a_checkmark(send_message, make_moderator) -> None:
    conv = send_message("@bot: set language to de", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = Settings().react_to_matrix_message(conv)

    assert result.reaction == "✅"


def test_config_denied_reacts_with_a_cross(send_message) -> None:
    conv = send_message("@bot: set language to de", sender="@user:example.org")

    result = Settings().react_to_matrix_message(conv)

    assert result.reaction == "❌"


def test_config_command_error_reacts_with_a_cross_and_uses_its_message(
    send_message, make_moderator
) -> None:
    conv = send_message("@bot: do something", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = FailableSettings().react_to_matrix_message(conv)

    assert result.reaction == "❌"
    assert result.text == "nope, that failed"


def test_mention_gets_no_reaction(send_message) -> None:
    conv = send_message("@bot: ping")

    result = Query().react_to_matrix_message(conv)

    assert result.reaction == ""


def test_config_recheck_via_refresh_members_allows_a_just_promoted_sender(
    send_message,
) -> None:
    """A `Config` command whose sender isn't a moderator yet, per the
    bot's own (possibly stale) records, gets one more chance after
    `refresh_members` runs - see `Config.allowed`.
    """
    conv = send_message("@bot: set language to de", sender="@mod:example.org")
    interaction = Settings()

    def _refresh() -> None:
        from matrix_jitsi_bot.db.models import RoomMember

        RoomMember.objects.update_or_create(
            room=conv.room, user_id="@mod:example.org", defaults={"power_level": 50}
        )

    interaction.refresh_members = _refresh
    result = interaction.react_to_matrix_message(conv)

    assert result.text == "Language set to de."


def test_config_does_not_refresh_members_when_already_a_moderator(
    send_message, make_moderator
) -> None:
    conv = send_message("@bot: set language to de", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    interaction = Settings()

    def _refresh() -> None:
        raise AssertionError("should not need to refresh - already a moderator")

    interaction.refresh_members = _refresh

    result = interaction.react_to_matrix_message(conv)

    assert result.text == "Language set to de."


def test_config_still_denied_after_refresh_finds_no_promotion(send_message) -> None:
    conv = send_message("@bot: set language to de", sender="@user:example.org")
    interaction = Settings()
    interaction.refresh_members = lambda: None

    result = interaction.react_to_matrix_message(conv)

    assert "only room moderators" in result.text
