from matrix_jitsi_bot.interactions import (
    AllInteractions,
    Config,
    HelpInteraction,
    Mention,
)


class _Query(HelpInteraction):
    @Mention(1, r"ping$", "Reply pong.", ["ping - replies pong"])
    def react_to_ping(self) -> str:
        return "pong"

    @Config(
        2,
        r"configure$",
        "Change a setting (moderators only).",
        ["configure - changes it"],
    )
    def react_to_configure(self) -> str:
        return "Configured."


def test_help_lists_visible_commands(send_message) -> None:
    conv = send_message("@bot: nonsense")

    result = _Query().react_to_matrix_message(conv)

    assert "ping - replies pong" in result.text
    assert "Change a setting" not in result.text  # moderator-only, sender isn't one


def test_help_shows_moderator_commands_to_a_moderator(
    send_message, make_moderator
) -> None:
    conv = send_message("@bot: nonsense", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = _Query().react_to_matrix_message(conv)

    assert "configure - changes it" in result.text


def test_help_links_to_docs_and_source(send_message) -> None:
    conv = send_message("@bot: nonsense")

    result = _Query().react_to_matrix_message(conv)

    assert "https://matrix-jitsi-bot.readthedocs.io" in result.text
    assert "https://github.com/niccokunzmann/matrix-jitsi-bot" in result.text


def test_help_via_all_interactions_lists_every_builtin_command(send_message) -> None:
    conv = send_message("@bot: nonsense")

    result = AllInteractions().react_to_matrix_message(conv)

    assert "hello" in result.text
    assert "status" in result.text
