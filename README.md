# Matrix Jitsi Bot

Report the status of Jitsi conferences to Matrix chat rooms. 

## Idea

These are the bases for this bot:

- [inspect-jitsi] - check the status of a Jitsi conference
- [nio-bot] - interface with matrix

Behaviour:

1. Invite the bot to a chat room.
2. Configure the bot inside the chat room.

| Command | Description | Response |
| ------- | ----------- | -------- |
| `@<bot name> list languages` | List all languages the bot speaks | A list of languages |
| `@<bot name> set language to <lang>` | Set the language of the chat bot | The chatbot changes its language to that language |
| `@<bot name> track status of <link to jitsi conference> | Track the conference status (open/closed) | When the conference opens or closes, the bot writes a message into the chat. |
| `@<bot name> track status with participants of <link to jitsi conference> | Track the conference status (open/closed) and report who is in it when it opens. | When the conference opens or closes, the bot writes a message into the chat, including who is in it. |

[inspect-jitsi]: https://pypi.org/project/inspect-jitsi/
