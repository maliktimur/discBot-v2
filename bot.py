import discord
import logging
import asyncio
import random
from discord.ext import commands
from typing import Literal
from discord import app_commands
from collections import deque
from dataclasses import dataclass, field
from config import *
from utils import is_url, ColorFormatter
import wavelink



intents = discord.Intents.all()
intents.messages = True
intents.members = True
intents.typing = True
intents.presences = True
#play_lock = asyncio.Lock()

handler = logging.StreamHandler() 
handler.setFormatter(ColorFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])

logger = logging.getLogger(__name__)

# Настройка бота
bot = commands.Bot(command_prefix='!', intents=intents)

# Independent playback state for each Discord guild.
@dataclass
class GuildState:
    queue: deque = field(default_factory=deque)
    repeat_mode: bool = False
    current_track: object = None
    disconnect_task: asyncio.Task | None = None
    track_ending: bool = False
    manual_stop: bool = False
    playback_text_channel: int | None = None
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Ignore stale track-end events after a manual skip/stop.
    ignored_ends: set = field(default_factory=set)


guild_states: dict[int, GuildState] = {}


def get_guild_state(guild_id: int) -> GuildState:
    return guild_states.setdefault(guild_id, GuildState())


def guild_label(guild: discord.Guild) -> str:
    """Readable guild name and ID for playback logs."""
    return f"{guild.name} ({guild.id})"


def cancel_disconnect_timer(state: GuildState):
    task = state.disconnect_task
    if task is not None and not task.done():
        task.cancel()
    state.disconnect_task = None


def reset_guild_state(state: GuildState):
    cancel_disconnect_timer(state)
    state.queue.clear()
    state.repeat_mode = False
    state.current_track = None


vpn_fail_count = 0
VPN_FAIL_LIMIT = 3
last_vpn_state = None

class SearchView(discord.ui.View):
    def __init__(self, interaction, results, timeout=30):
        super().__init__(timeout=timeout)

        self.interaction = interaction
        self.results = results

        for i, track in enumerate(results[:3]):
            button = discord.ui.Button(
                label=str(i + 1),
                style=discord.ButtonStyle.primary
            )

            button.callback = self.create_callback(i)
            self.add_item(button)

        cancel_button = discord.ui.Button(
            label="❌",
            style=discord.ButtonStyle.danger
        )

        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            # Только тот, кто запускал поиск, может выбрать трек
            if interaction.user.id != self.interaction.user.id:
                await interaction.response.send_message(
                    "❌ Это не ваш поиск.",
                    ephemeral=True
                )
                return

            track_obj = self.results[index]
            state = get_guild_state(interaction.guild.id)

            state.queue.append(track_obj)

            logging.info(
                f"🎵 [{guild_label(interaction.guild)}] Selected search result: {track_obj.title}"
            )

            logging.info(
                f"[{guild_label(interaction.guild)}] Queue length: {len(state.queue)}"
            )

            # Отключаем кнопки
            await interaction.response.edit_message(
                content=(
                    f"➕ Добавлено в очередь: "
                    f"**{track_obj.title}**"
                ),
                embed=None,
                view=None
            )

            player: wavelink.Player = interaction.guild.voice_client

            if player and not player.playing and not player.paused:
                await play_next(interaction.guild)

            self.stop()

        return callback

    async def cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Это не ваш поиск.",
                ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content="❌ Поиск отменён.",
            embed=None,
            view=None
        )

        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        try:
            await self.message.edit(view=self)
        except Exception:
            pass


async def is_vpn_alive():
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "3", "https://1.1.1.1/cdn-cgi/trace",
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return b"ip=" in stdout
    except:
        return False


async def vpn_iface_watchdog():
    global vpn_fail_count, last_vpn_state

    while True:
        try:
            is_up = await is_vpn_alive()

            # лог только при изменении состояния
            if last_vpn_state != is_up:
                last_vpn_state = is_up

                if is_up:
                    logging.info("✅ VPN OK")
                else:
                    logging.warning("❌ VPN DOWN")

            if is_up:
                vpn_fail_count = 0
            else:
                vpn_fail_count += 1
                logging.warning(f"⚠️ VPN FAIL {vpn_fail_count}")

            if vpn_fail_count >= VPN_FAIL_LIMIT:
                logging.error("❌ VPN DOWN HARD")

        except Exception as e:
            vpn_fail_count += 1
            logging.error(f"VPN watchdog error: {e}")

        await asyncio.sleep(30)


# Уведомление о готовности бота
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")

    if not wavelink.Pool.nodes:
        node = wavelink.Node(
            identifier="main",
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD,
        )

        await wavelink.Pool.connect(
            nodes=[node],
            client=bot,
        )

    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")

    if not getattr(bot, "vpn_watchdog_task", None) or bot.vpn_watchdog_task.done():
        bot.vpn_watchdog_task = asyncio.create_task(vpn_iface_watchdog())


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    logging.info(f"✅ Lavalink connected: {payload.node}")


@bot.event
async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload):
    logging.info("🎵 TRACK START [%s]: %s", guild_label(payload.player.guild) if payload.player and payload.player.guild else "unknown guild", payload.track.title)


@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player = payload.player
    if player is None or player.guild is None:
        return
    state = get_guild_state(player.guild.id)
    track = payload.track
    identifier = getattr(track, "identifier", None)
    # Stop and skip generate an end event. Never let it advance twice.
    if identifier is not None and identifier in state.ignored_ends:
        state.ignored_ends.discard(identifier)
        return
    if state.manual_stop or state.track_ending:
        return
    # A delayed event from a previous track must not affect the current one.
    current = state.current_track
    if current is not None and track is not None and getattr(current, "identifier", None) != identifier:
        logging.info("Ignoring stale track-end event in guild %s", guild_label(player.guild))
        return
    state.track_ending = True
    try:
        logging.info("⏹️ TRACK END [%s]: %s", guild_label(player.guild), track.title)
        if not state.repeat_mode:
            state.current_track = None
        await play_next(player.guild)
    finally:
        state.track_ending = False


async def send_playback_error(player, track):
    try:
        channel_id = get_guild_state(player.guild.id).playback_text_channel

        if channel_id is None:
            return

        channel = player.guild.get_channel(channel_id)

        if channel is None:
            return

        await channel.send(
            f"❌ Не удалось воспроизвести **{track.title}**.\n"
            f"YouTube не предоставил поток для воспроизведения этого видео."
        )

    except Exception:
        logging.exception("Failed to send playback error [%s]", guild_label(player.guild))



@bot.event
async def on_wavelink_track_exception(
    payload: wavelink.TrackExceptionEventPayload
):
    track = payload.track
    player = payload.player

    logging.error(
        f"❌ TRACK EXCEPTION [{guild_label(player.guild) if player and player.guild else 'unknown guild'}]: "
        f"{track.title}: {payload.exception}"
    )

    if player is not None:
        await send_playback_error(player, track)
        await play_next(player.guild)


@bot.event
async def on_wavelink_track_stuck(
    payload: wavelink.TrackStuckEventPayload
):
    logging.error(
        f"⚠️ TRACK STUCK [{guild_label(payload.player.guild) if payload.player and payload.player.guild else 'unknown guild'}]: "
        f"{payload.track.title}, "
        f"threshold={payload.threshold}"
    )

    if payload.player is not None:
        await play_next(payload.player.guild)


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    state = get_guild_state(guild.id)
    if member.id == bot.user.id:
        if before.channel and after.channel is None:
            logging.warning("🚪 Bot left voice in guild %s", guild_label(guild))
            reset_guild_state(state)
        return
    if member.bot:
        return
    voice_client = guild.voice_client
    if voice_client is None or not voice_client.connected:
        return
    channel = voice_client.channel
    if channel is None or (before.channel != channel and after.channel != channel):
        return
    await asyncio.sleep(2)
    if guild.voice_client is not voice_client or voice_client.channel != channel:
        return
    if not any(not m.bot for m in channel.members):
        logging.info("Voice channel empty in guild %s; disconnecting", guild_label(guild))
        state.manual_stop = True
        reset_guild_state(state)
        try:
            await voice_client.disconnect()
        finally:
            state.manual_stop = False


# Слэш-Функция для списка команд
@bot.tree.command(name="help", description="Список команд бота")
async def help_command(interaction: discord.Interaction):
    help_text = "Список команд:\n"
    for command in bot.tree.get_commands():
        help_text += f'/{command.name} - {command.description}\n'
    
    await interaction.response.send_message(help_text)


# Слэш-Функция для тестирования
@bot.tree.command(name="test", description="Узнать свой IQ")
async def test_command(interaction: discord.Interaction):
    await interaction.response.send_message(f"Твой IQ равен {random.randint(0, 150)}")


# Слэш-Функция для добавления музыки в очередь и воспроизведения
@bot.tree.command(
    name="play",
    description="Добавить музыку в очередь и воспроизвести"
)
@app_commands.describe(
    source="Источник для поиска",
    track="Название трека или ссылка"
)
async def play_command(
    interaction: discord.Interaction,
    source: Literal["YouTube", "SoundCloud", "URL"],
    track: str,
):
    await interaction.response.defer(thinking=True)

    state = get_guild_state(interaction.guild.id)
    state.playback_text_channel = interaction.channel.id
    cancel_disconnect_timer(state)

    if interaction.user.voice is None:
        await interaction.followup.send(
            "Вы должны быть в голосовом канале, чтобы использовать эту команду."
        )
        return

    voice_channel = interaction.user.voice.channel

    player: wavelink.Player = interaction.guild.voice_client

    # Подключаемся
    if player is None:
        logging.info(f"[{guild_label(interaction.guild)}] Connecting to {voice_channel.name}")

        player = await voice_channel.connect(
            cls=wavelink.Player
        )

        logging.info("[%s] Connected to voice", guild_label(interaction.guild))

    elif player.channel != voice_channel:
        await player.move_to(voice_channel)

    # ==========================================
    # ПРОВЕРКА И ОПРЕДЕЛЕНИЕ ИСТОЧНИКА
    # ==========================================

    if source == "URL":

        # Для URL пользователь обязан указать ссылку
        if not is_url(track):
            await interaction.followup.send(
                "❌ Вы выбрали источник **URL**, "
                "но не ввели корректную ссылку."
            )
            
            await play_next(interaction.guild)
            
            return

        query = track
        search_source = None

    else:

        # YouTube / SoundCloud должны использовать поиск,
        # а не прямую ссылку
        if is_url(track):
            await interaction.followup.send(
                f"❌ Вы выбрали источник **{source}**, "
                "но ввели ссылку.\n"
                "Пожалуйста, выберите источник **URL**, "
                "если хотите вставить ссылку."
            )

            await play_next(interaction.guild)

            return

        query = track

        if source == "YouTube":
            search_source = wavelink.TrackSource.YouTube

        elif source == "SoundCloud":
            search_source = wavelink.TrackSource.SoundCloud

    logging.info(
        f'[{guild_label(interaction.guild)}] Searching: "{query}" '
        f'(source={search_source})'
    )

    try:
        if search_source is None:
            results = await wavelink.Playable.search(query)
        else:
            results = await wavelink.Playable.search(
                query,
                source=search_source
            )

    except Exception as e:
        logging.exception("Search error [%s]", guild_label(interaction.guild))

        await interaction.followup.send(
            f"❌ Ошибка поиска: `{e}`"
        )

        await play_next(interaction.guild)
                
        return

    if not results:
        await interaction.followup.send(
            "❌ Ничего не найдено."
        )

        await play_next(interaction.guild)

        return

    # ==========================================
    # PLAYLIST
    # ==========================================

    if isinstance(results, wavelink.Playlist):

        tracks = results.tracks

        if not tracks:
            await interaction.followup.send(
                "❌ Плейлист пуст или недоступен."
            )

            await play_next(interaction.guild)

            return

        # Добавляем все треки плейлиста
        for track_obj in tracks:
            state.queue.append(track_obj)

        logging.info(
            f"📋 [{guild_label(interaction.guild)}] Playlist: {results.name}"
        )

        logging.info(
            f"📋 [{guild_label(interaction.guild)}] Added {len(tracks)} tracks"
        )

        logging.info(
            f"[{guild_label(interaction.guild)}] Queue length: {len(state.queue)}"
        )

        await interaction.followup.send(
            f"📋 Добавлен плейлист **{results.name}** "
            f"({len(tracks)} треков)"
        )

    # ==========================================
    # ОБЫЧНЫЙ ТРЕК
    # ==========================================

    else:

        # Для любого обычного результата
        # сразу берём первый найденный трек
        track_obj = results[0]

        state.queue.append(track_obj)

        logging.info(
            f"🎵 [{guild_label(interaction.guild)}] Added to queue: {track_obj.title}"
        )

        logging.info(
            f"[{guild_label(interaction.guild)}] Queue length: {len(state.queue)}"
        )

        await interaction.followup.send(
            f"➕ Добавлено в очередь: **{track_obj.title}**"
        )

    # ==========================================
    # START PLAYBACK
    # ==========================================

    if not player.playing and not player.paused:
        await play_next(interaction.guild)

# Start next track, serialized per guild to avoid two simultaneous starts.
async def play_next(guild):
    state = get_guild_state(guild.id)
    async with state.play_lock:
        player: wavelink.Player = guild.voice_client
        if player is None or not player.connected or state.manual_stop:
            return
        if player.playing or player.paused:
            return
        cancel_disconnect_timer(state)
        while True:
            if state.repeat_mode and state.current_track is not None:
                track = state.current_track
            elif state.queue:
                track = state.queue.popleft()
            else:
                state.current_track = None
                state.disconnect_task = asyncio.create_task(start_disconnect_timer(guild))
                logging.info("Queue empty in guild %s", guild_label(guild))
                return
            state.current_track = track
            try:
                logging.info("▶️ Playing [%s]: %s (remaining %s)", guild_label(guild), track.title, len(state.queue))
                await player.play(track)
                return
            except Exception:
                logging.exception("Playback failed in guild %s", guild_label(guild))
                state.current_track = None
                # A broken track should not repeat forever.
                state.repeat_mode = False


async def start_disconnect_timer(guild):
    state = get_guild_state(guild.id)
    try:
        await asyncio.sleep(90)
        player: wavelink.Player = guild.voice_client
        if (player and player.connected and not player.playing and not player.paused
                and not state.queue and not state.repeat_mode):
            state.manual_stop = True
            try:
                await player.disconnect()
                logging.info("Disconnected after idle timeout [%s]", guild_label(guild))
            finally:
                state.manual_stop = False
    except asyncio.CancelledError:
        pass
    finally:
        if state.disconnect_task is asyncio.current_task():
            state.disconnect_task = None


# Команда для остановки музыки и очистки очереди
@bot.tree.command(
    name="stop",
    description="Остановить музыку и очистить очередь"
)
async def stop_command(interaction: discord.Interaction):
    state = get_guild_state(interaction.guild.id)
    player: wavelink.Player = interaction.guild.voice_client
    state.manual_stop = True
    reset_guild_state(state)
    if player is None or not player.connected:
        state.manual_stop = False
        await interaction.response.send_message("⏹️ Бот уже не находится в голосовом канале.")
        return
    try:
        await player.disconnect()
    finally:
        state.manual_stop = False
    await interaction.response.send_message("⏹️ Воспроизведение остановлено и очередь очищена.")


# Функция для паузы музыки
@bot.tree.command(
    name="pause",
    description="Приостановить воспроизведение музыки"
)
async def pause_command(interaction: discord.Interaction):

    player: wavelink.Player = interaction.guild.voice_client

    if player is None:
        await interaction.response.send_message(
            "Бот не находится в голосовом канале."
        )
        return

    if not player.playing:
        await interaction.response.send_message(
            "Сейчас ничего не воспроизводится."
        )
        return

    await player.pause(True)

    await interaction.response.send_message(
        "⏸️ Воспроизведение приостановлено."
    )


# Команда для возобновления музыки
@bot.tree.command(
    name="resume",
    description="Возобновить воспроизведение музыки"
)
async def resume_command(interaction: discord.Interaction):

    player: wavelink.Player = interaction.guild.voice_client

    if player is None:
        await interaction.response.send_message(
            "Бот не находится в голосовом канале."
        )
        return

    if not player.paused:
        await interaction.response.send_message(
            "Сейчас ничего не приостановлено."
        )
        return

    await player.pause(False)

    await interaction.response.send_message(
        "▶️ Воспроизведение возобновлено."
    )

# Команда для пропуска трека
@bot.tree.command(
    name="skip",
    description="Пропустить текущий трек"
)
async def skip_command(interaction: discord.Interaction):
    state = get_guild_state(interaction.guild.id)
    player: wavelink.Player = interaction.guild.voice_client
    if player is None or not player.connected:
        await interaction.response.send_message("Бот не находится в голосовом канале.", ephemeral=True)
        return
    if not player.playing and not player.paused:
        await interaction.response.send_message("Сейчас ничего не воспроизводится.")
        return
    old_track = state.current_track
    state.repeat_mode = False
    state.current_track = None
    if old_track is not None:
        identifier = getattr(old_track, "identifier", None)
        if identifier is not None:
            state.ignored_ends.add(identifier)
    await interaction.response.send_message("⏭️ Трек пропущен.")
    await player.skip(force=True)
    await play_next(interaction.guild)


# Команда для включения/выключения повторения
@bot.tree.command(
    name="repeat",
    description="Включить или выключить повторение"
)
async def repeat_command(interaction: discord.Interaction):
    state = get_guild_state(interaction.guild.id)
    player: wavelink.Player = interaction.guild.voice_client
    if player is None or not player.connected:
        await interaction.response.send_message("Бот не находится в голосовом канале.")
        return
    state.repeat_mode = not state.repeat_mode
    if state.repeat_mode:
        await interaction.response.send_message("🔁 Режим повторения включен.")
    else:
        await interaction.response.send_message("➡️ Режим повторения выключен.")


# Запуск бота
bot.run(TOKEN)