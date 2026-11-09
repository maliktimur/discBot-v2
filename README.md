[README.md](https://github.com/user-attachments/files/34580010/README.md)
# 🎵 discBot-v2

A self-hosted Discord music bot built with **Python**, **discord.py**, **Wavelink**, and **Lavalink**. Play music from YouTube and SoundCloud, queue tracks and playlists, and control playback using Discord slash commands.

> **Status:** Personal project. The current implementation uses a single in-memory music queue and playback state shared across the bot process; it is best suited to a single active server/session rather than simultaneous independent guild playback.

## ✨ Features

- 🎶 **Music playback:** Search YouTube or SoundCloud, or submit a direct URL supported by your Lavalink configuration.
- 📋 **Queue and playlists:** Queue individual tracks or add tracks from a supported playlist URL.
- 🎛️ **Slash commands:** Play, pause, resume, skip, stop, and toggle repeat.
- 🔁 **Track repeat:** Loop the currently playing track until repeat is disabled or the track is skipped.
- ⏱️ **Automatic disconnection:** Leave the voice channel after 90 seconds of inactivity when the queue is empty; also disconnect when no human listeners remain.
- 🛠️ **Playback recovery:** Log track exceptions/stalls, notify the text channel about playback errors, and attempt to continue with the next track.
- 🌐 **Optional VPN monitoring:** Periodically check external connectivity and log changes in VPN/network availability.
- 🎨 **Colored console logs:** Readable INFO, WARNING, and ERROR output.

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
├── bot.py       # Bot commands, playback queue, events, and watchdog
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
| `/play` | Choose **YouTube**, **SoundCloud**, or **URL**, then provide a track name or link. Adds the result to the queue and starts playback if idle. |
| `/pause` | Pause the current track. |
| `/resume` | Resume paused playback. |
| `/skip` | Skip the current track and disable repeat. |
| `/repeat` | Toggle repeat for the current track. |
| `/stop` | Stop playback, clear the queue, and disconnect. |
| `/help` | Display available slash commands. |

**Example:** Run `/play`, select `YouTube` as the source, and enter a song title. For a direct video or playlist link, select `URL` instead.

> **Current behavior:** Although the code contains a `SearchView` UI class with three selection buttons, the active `/play` command currently queues the **first search result** automatically. It does not present those selection buttons.

## 🔊 Playback behavior

1. A user joins a voice channel and invokes `/play`.
2. The bot joins (or moves to) that user's voice channel.
3. Wavelink searches through the configured Lavalink node.
4. The selected track or playlist is appended to the in-memory queue.
5. When a track finishes, the next queued track starts automatically, unless repeat is active.
6. If playback ends and no tracks remain, a 90-second disconnect timer begins.
7. If all human users leave the voice channel, the bot clears playback state and disconnects.

**Important limitation:** Queue, current track, repeat mode, and disconnect timer are module-level globals, not per-guild state. Running the bot across multiple Discord servers simultaneously can cause interference. A future improvement would be to store playback state per guild.

## 🌐 Optional VPN setup

The original deployment routes bot/Lavalink traffic through a VPN using a Linux network namespace and OpenVPN. This is an **infrastructure choice**, not a requirement for Wavelink or Lavalink.

The bot also runs a connectivity watchdog that:

- Executes `curl` against Cloudflare's trace endpoint.
- Checks whether the response contains an IP field.
- Repeats the check every **30 seconds**.
- Logs changes in connectivity state and consecutive failures.

**Note:** This watchdog checks outbound connectivity; it does **not** prove that traffic is going through a VPN or automatically restart the VPN. The host needs `curl` installed for this check to work.

## 🧯 Troubleshooting

| Problem | What to check |
| --- | --- |
| Bot fails to start | Verify `token.txt` exists and contains a valid Discord bot token. |
| Lavalink connection fails | Confirm Lavalink is running and its host, port, and password match `config.py`. |
| Slash commands do not appear | Verify the bot was invited with `applications.commands` and check startup logs for sync errors. |
| YouTube searches or playback fail | Verify the Lavalink YouTube plugin and its source configuration; YouTube access can change independently of the bot. |
| SoundCloud searches fail | Confirm SoundCloud is enabled in Lavalink. |
| VPN watchdog logs failures | Check outbound connectivity and `curl`; the check alone does not identify the cause of a VPN outage. |
| Playback behaves unexpectedly across servers | The current implementation uses global queue and playback state. |

## 🛣️ Potential improvements

- Per-guild playback queues and repeat state
- A dedicated queue inspection command
- Configurable settings through environment variables
- Automated dependency management and tests
- Improved search-result selection UI
- More robust Lavalink reconnect and VPN health handling

## 📄 License

This project is licensed under the MIT License.
See the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 Timur Malik

Made by [@maliktimur](https://github.com/maliktimur).
