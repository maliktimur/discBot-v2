# 🎵 discBot-v2

A self-hosted Discord music bot built with **Python**, **discord.py**, **Wavelink**, and **Lavalink**. Play music from YouTube and SoundCloud, queue tracks and playlists, and control playback with Discord slash commands.

> **Status:** Personal project. Supports **independent playback across multiple Discord servers (guilds)**, with a separate in-memory queue and playback state for each guild.

## ✨ Features

- 🎶 **Music playback:** Search YouTube or SoundCloud, or submit a direct URL supported by your Lavalink configuration.
- 🏘️ **Multi-server support:** Each Discord guild has its own queue, current track, repeat mode, and disconnect timer. Actions on one server do not modify another server's playback state.
- 📋 **Queue and playlists:** Queue individual tracks or add tracks from a supported playlist URL.
- 🎛️ **Slash commands:** Play, pause, resume, skip, stop, and toggle repeat.
- 🔁 **Track repeat:** Loop the currently playing track until repeat is disabled or the track is skipped.
- ⏱️ **Automatic disconnection:** Leave a guild's voice channel after 90 seconds of inactivity when its queue is empty; also disconnect when no human listeners remain.
- 🛠️ **Playback recovery:** Log track exceptions/stalls, notify the relevant guild's text channel about playback errors, and attempt to continue with the next track.
- 🌐 **Optional VPN monitoring:** Periodically check external connectivity and log changes in VPN/network availability.
- 🎨 **Colored console logs:** Readable INFO, WARNING, and ERROR output, with guild names and IDs in playback-related logs.

## 🧰 Tech stack

| Component | Purpose |
| --- | --- |
| Python 3.12 | Bot runtime (used in the original deployment) |
| [discord.py](https://discordpy.readthedocs.io/) | Discord client and slash commands |
| [Wavelink 3.x](https://wavelink.readthedocs.io/) | Lavalink integration |
| [Lavalink 4.x](https://lavalink.dev/) | Audio playback server |
| Java 21 | Lavalink runtime |
| [Lavalink YouTube plugin](https://github.com/lavalink-devs/youtube-source) | YouTube source support when configured |

## 📁 Project structure

```text
discBot-v2/
├── bot.py       # Commands, per-guild playback state, events, and watchdog
├── config.py    # Discord token loading and Lavalink connection settings
├── utils.py     # URL validation and colored logging
└── token.txt    # Your Discord bot token (create locally; never commit)
```

## 🚀 Getting started

### 1. Prerequisites

You will need:

- Python 3.12 (or a compatible Python version)
- A Discord application and bot token from the [Discord Developer Portal](https://discord.com/developers/applications)
- A running **Lavalink 4.x** server with the audio sources you intend to use enabled
- Java 21 to run Lavalink

Invite your bot to a server with the `bot` and `applications.commands` scopes and appropriate permissions to view channels, connect, speak, and send messages. The current code requests all gateway intents, including privileged intents; enable the required privileged intents in the Developer Portal or narrow the intents in `bot.py`.

### 2. Clone the repository

```bash
git clone https://github.com/maliktimur/discBot-v2.git
cd discBot-v2
```

### 3. Install Python dependencies

It is recommended to use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "discord.py>=2.6,<3" "wavelink>=3.5,<4"
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

> The repository currently does not include a `requirements.txt`. The commands above install the two external Python packages imported by the bot; pin tested versions for reproducible deployments.

### 4. Configure the Discord token

Create a `token.txt` file in the repository root and paste **only** your bot token into it:

```text
YOUR_DISCORD_BOT_TOKEN
```

`config.py` reads this file at startup. **Do not commit `token.txt` or share your token.** Add it to `.gitignore`:

```gitignore
token.txt
.venv/
__pycache__/
*.pyc
```

### 5. Configure Lavalink

Run Lavalink separately, following the [official Lavalink documentation](https://lavalink.dev/). Enable and configure the source plugins you need (including the YouTube plugin for YouTube searches). Ensure that the server's port and password match the settings in `config.py`:

```python
LAVALINK_HOST = "127.0.0.1"
LAVALINK_PORT = 2333
LAVALINK_PASSWORD = "YOUR_LAVALINK_PASSWORD"
```

The bot connects to Lavalink over HTTP. If Lavalink is on another machine, update the host and ensure the connection is securely restricted to trusted clients. Do not expose an unauthenticated Lavalink endpoint to the public internet.

### 6. Start the bot

Once Lavalink is running:

```bash
python bot.py
```

On startup, the bot connects to Lavalink and synchronizes its Discord slash commands. Command registration may take a little time to appear in Discord.

## 🎮 Commands

| Command | Description |
| --- | --- |
| `/play` | Choose **YouTube**, **SoundCloud**, or **URL**, then provide a track name or link. Adds the result to this guild's queue and starts playback if idle. |
| `/pause` | Pause playback in the current guild. |
| `/resume` | Resume paused playback in the current guild. |
| `/skip` | Skip the current guild's track and disable repeat for that guild. |
| `/repeat` | Toggle repeat for the current guild's track. |
| `/stop` | Stop playback, clear this guild's queue, and disconnect. |
| `/help` | Display available slash commands. |

**Example:** Run `/play`, select `YouTube` as the source, and enter a song title. For a direct video or playlist link, select `URL` instead.

> **Search behavior:** Although the code contains a `SearchView` UI class with three selection buttons, the active `/play` command queues the **first search result** automatically rather than presenting those buttons.

## 🔊 Playback behavior

1. A user joins a voice channel and invokes `/play`.
2. The bot joins (or moves to) that user's voice channel **within that guild**.
3. Wavelink searches through the configured Lavalink node.
4. The selected track or playlist is appended to **that guild's in-memory queue**.
5. When a track finishes, the next track from the same guild's queue starts automatically, unless repeat is active.
6. If playback ends and that guild has no tracks remaining, its own 90-second disconnect timer begins.
7. If all human users leave the voice channel, the bot clears that guild's playback state and disconnects from that channel.

### Independent guild state

The bot stores playback state in a dictionary keyed by Discord `guild_id`. Each guild has its own `GuildState`, including a `deque` for pending tracks, the current track, repeat settings, a disconnect task, playback flags, and the text channel used for error notifications. Guild-specific synchronization prevents competing playback operations from starting simultaneously.

For example, **Server A** can play a playlist with repeat enabled while **Server B** plays unrelated tracks with repeat disabled. `/skip` or `/stop` on one server does not clear the other server's queue.

> **Persistence:** Queues and playback state are stored **in memory only**. They are not restored after a bot restart. Multiple guilds can share the same Lavalink node, but their playback state is isolated in the bot.

### Guild-aware logging

Playback-related logs include the guild's display name and ID to make simultaneous sessions easier to debug. Example:

```text
🎵 [Music Server (123456789)] Added to queue: Example Track
▶️ Playing [Music Server (123456789)]: Example Track
```

## 🌐 Optional VPN setup

The original deployment routes bot/Lavalink traffic through a VPN using a Linux network namespace and OpenVPN. This is an **infrastructure choice**, not a requirement for Wavelink or Lavalink.

The bot also runs a connectivity watchdog that:

- Executes `curl` against Cloudflare's trace endpoint.
- Checks whether the response contains an IP field.
- Repeats the check every **30 seconds**.
- Logs changes in connectivity state and consecutive failures.

> **Note:** This watchdog checks outbound connectivity; it does **not** prove that traffic is going through a VPN or automatically restart the VPN. The host needs `curl` installed for this check to work.

## 🧯 Troubleshooting

| Problem | What to check |
| --- | --- |
| Bot fails to start | Verify `token.txt` exists and contains a valid Discord bot token. |
| Lavalink connection fails | Confirm Lavalink is running and its host, port, and password match `config.py`. |
| Slash commands do not appear | Verify the bot was invited with `applications.commands` and check startup logs for sync errors. |
| YouTube searches or playback fail | Verify the Lavalink YouTube plugin and its source configuration; YouTube access can change independently of the bot. |
| SoundCloud searches fail | Confirm SoundCloud is enabled in Lavalink. |
| VPN watchdog logs failures | Check outbound connectivity and `curl`; the check alone does not identify the cause of a VPN outage. |
| A guild's queue is empty after restart | Playback state is in memory and is not persisted across restarts. |
| Playback issue affects one server | Check logs for that guild's name and ID to isolate its events. |

## 🛣️ Potential improvements

- A dedicated `/queue` inspection command
- Persistent queues across bot restarts
- Configurable settings through environment variables
- Automated dependency management and tests
- Improved search-result selection UI
- More robust Lavalink reconnect and VPN health handling

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 Timur Malik

Made by [@maliktimur](https://github.com/maliktimur).
