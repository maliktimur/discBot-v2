import discord
import logging
import asyncio
import random
from discord.ext import commands
from typing import Literal
from discord import app_commands
from collections import deque
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

# Очередь воспроизведения
music_queue = deque()
#ctx_queue = deque()
repeat_mode = False  # Переменная для отслеживания режима повторения
current_track = None
disconnect_task = None
track_ending = False
manual_stop = False
playback_text_channels = {}

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

            music_queue.append(track_obj)

            logging.info(
                f"🎵 Selected search result: {track_obj.title}"
            )

            logging.info(
                f"Queue length: {len(music_queue)}"
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

    asyncio.create_task(vpn_iface_watchdog())


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    logging.info(f"✅ Lavalink connected: {payload.node}")


@bot.event
async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload):
    logging.info(f"🎵 TRACK START: {payload.track.title}")


@bot.event
async def on_wavelink_track_end(
    payload: wavelink.TrackEndEventPayload
):
    global current_track
    global track_ending
    global manual_stop

    player = payload.player

    if player is None:
        return

    if track_ending:
        logging.warning(
            f"⚠️ Duplicate TRACK END ignored: {payload.track.title}"
        )
        return

    track_ending = True

    try:
        logging.info(
            f"⏹️ TRACK END: {payload.track.title}"
        )

        # /stop вызвал player.stop()
        # Поэтому НЕ запускаем play_next()
        if manual_stop:
            logging.info(
                "🛑 TRACK END caused by manual /stop - ignoring"
            )
            current_track = None
            return

        if repeat_mode:
            await play_next(player.guild)
        else:
            current_track = None
            await play_next(player.guild)

    finally:
        track_ending = False


async def send_playback_error(player, track):
    try:
        channel_id = playback_text_channels.get(player.guild.id)

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
        logging.exception("Failed to send playback error")



@bot.event
async def on_wavelink_track_exception(
    payload: wavelink.TrackExceptionEventPayload
):
    track = payload.track
    player = payload.player

    logging.error(
        f"❌ TRACK EXCEPTION: "
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
        f"⚠️ TRACK STUCK: "
        f"{payload.track.title}, "
        f"threshold={payload.threshold}"
    )

    if payload.player is not None:
        await play_next(payload.player.guild)


@bot.event
async def on_voice_state_update(member, before, after):
    voice_client = member.guild.voice_client
    if member == bot.user:
        # бот был в канале, но теперь нет
        if before.channel and after.channel is None:

            vc = member.guild.voice_client

            logging.warning("🚪 Bot left voice (state change detected)")

            # 👉 если ты НЕ вызывал disconnect сам
            if vc is None:
                logging.warning("⚠️ VoiceClient already gone (external disconnect)")

    if member.bot:
        return

    if voice_client is None or not voice_client.connected:
        return

    channel = voice_client.channel

    await asyncio.sleep(2)
    # Проверяем, остался ли в голосовом канале только бот
    if len([m for m in channel.members if not m.bot]) == 0:
        global current_track
        global repeat_mode
        

        current_track = None
        repeat_mode = False
        music_queue.clear()
        logging.info(f'Длина очереди: {len(music_queue)}(очищена, все отключились)')
        logging.info("Все пользователи покинули канал. Отключаюсь...")
        await voice_client.disconnect()


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

    playback_text_channels[interaction.guild.id] = interaction.channel.id

    global disconnect_task

    if disconnect_task and not disconnect_task.done():
        disconnect_task.cancel()
        disconnect_task = None
        logging.info("🛑 Disconnect timer cancelled")

    if interaction.user.voice is None:
        await interaction.followup.send(
            "Вы должны быть в голосовом канале, чтобы использовать эту команду."
        )
        return

    voice_channel = interaction.user.voice.channel

    player: wavelink.Player = interaction.guild.voice_client

    # Подключаемся
    if player is None:
        logging.info(f"Connecting to {voice_channel.name}")

        player = await voice_channel.connect(
            cls=wavelink.Player
        )

        logging.info("Connected to voice")

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
            return

        query = track

        if source == "YouTube":
            search_source = wavelink.TrackSource.YouTube

        elif source == "SoundCloud":
            search_source = wavelink.TrackSource.SoundCloud

    logging.info(
        f'Searching: "{query}" '
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
        logging.exception("Search error")

        await interaction.followup.send(
            f"❌ Ошибка поиска: `{e}`"
        )
        return

    if not results:
        await interaction.followup.send(
            "❌ Ничего не найдено."
        )
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
            return

        # Добавляем все треки плейлиста
        for track_obj in tracks:
            music_queue.append(track_obj)

        logging.info(
            f"📋 Playlist: {results.name}"
        )

        logging.info(
            f"📋 Added {len(tracks)} tracks"
        )

        logging.info(
            f"Queue length: {len(music_queue)}"
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

        music_queue.append(track_obj)

        logging.info(
            f"🎵 Added to queue: {track_obj.title}"
        )

        logging.info(
            f"Queue length: {len(music_queue)}"
        )

        await interaction.followup.send(
            f"➕ Добавлено в очередь: **{track_obj.title}**"
        )

    # ==========================================
    # START PLAYBACK
    # ==========================================

    if not player.playing and not player.paused:
        await play_next(interaction.guild)

# Функция для воспроизведения музыки
async def play_next(guild):
    global current_track
    global disconnect_task
     

    player: wavelink.Player = guild.voice_client

    if player is None or not player.connected:
        logging.warning("❌ Player is not connected")
        return

    if player.playing or player.paused:
        return

    if repeat_mode and current_track is not None:
        track = current_track
    else:
        if not music_queue:
            logging.info("Queue is empty")

            if disconnect_task is None or disconnect_task.done():
                disconnect_task = asyncio.create_task(
                    start_disconnect_timer(guild)
                )

            return

        track = music_queue.popleft()

    current_track = track

    logging.info(f"▶️ Playing: {track.title}")
    logging.info(f"Queue remaining: {len(music_queue)}")


    try:
        await player.play(track)

    except Exception as e:
        logging.exception(f"Playback error: {e}")

        current_track = None

        if music_queue:
            await play_next(guild)



# Функция для запуска таймера отключения
async def start_disconnect_timer(guild):
    global disconnect_task

    logging.info("DISCONNECT TIME STARTED")

    try:
        await asyncio.sleep(90)

        voice_client: wavelink.Player = guild.voice_client

        if (
            voice_client
            and not voice_client.playing
            and not voice_client.paused
            and not music_queue
            and not repeat_mode
        ):
            await voice_client.disconnect()
            logging.info(f"{bot.user.name} disconnected")

        else:
            logging.info(
                "Still playing or queue not empty, disconnection aborted"
            )

    except asyncio.CancelledError:
        logging.info("DISCONNECT TIMER CANCELLED")

    finally:
        disconnect_task = None


# Команда для остановки музыки и очистки очереди
@bot.tree.command(
    name="stop",
    description="Остановить музыку и очистить очередь"
)
async def stop_command(interaction: discord.Interaction):
    global current_track
    global repeat_mode
    global disconnect_task
    global manual_stop

    player: wavelink.Player = interaction.guild.voice_client

    if player is None or not player.connected:
        current_track = None
        repeat_mode = False
        music_queue.clear()

        if disconnect_task and not disconnect_task.done():
            disconnect_task.cancel()
            disconnect_task = None

        await interaction.response.send_message(
            "⏹️ Бот уже не находится в голосовом канале."
        )
        return

    # ВАЖНО:
    # TRACK END после player.stop() не должен запускать play_next()
    manual_stop = True

    repeat_mode = False
    current_track = None
    music_queue.clear()

    logging.info("🗑️ Queue cleared")

    if disconnect_task and not disconnect_task.done():
        disconnect_task.cancel()
        disconnect_task = None
        logging.info("🛑 Disconnect timer cancelled")

    if player.playing or player.paused:
        await player.stop()

    # Отключаемся сами
    await player.disconnect()

    # Сбрасываем флаг после disconnect
    manual_stop = False

    await interaction.response.send_message(
        "⏹️ Воспроизведение остановлено и очередь очищена."
    )


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
    global current_track
    global repeat_mode

    player: wavelink.Player = interaction.guild.voice_client

    if player is None:
        await interaction.response.send_message(
            "Бот не находится в голосовом канале.",
            ephemeral=True
        )
        return

    if not player.playing:
        await interaction.response.send_message(
            "Сейчас ничего не воспроизводится."
        )
        return

    if current_track is not None:
        logging.info(
            f"⏭️ Skipping: {current_track.title}"
        )

    # Skip должен действительно пропустить текущий трек
    repeat_mode = False
    current_track = None

    await player.stop()

    await interaction.response.send_message(
        "⏭️ Трек пропущен."
    )


# Команда для включения/выключения повторения
@bot.tree.command(
    name="repeat",
    description="Включить или выключить повторение"
)
async def repeat_command(interaction: discord.Interaction):
    global repeat_mode

    player: wavelink.Player = interaction.guild.voice_client

    if player is None:
        await interaction.response.send_message(
            "Бот не находится в голосовом канале."
        )
        return

    repeat_mode = not repeat_mode

    if repeat_mode:
        logging.info("🔁 Repeat mode: ON")

        await interaction.response.send_message(
            "🔁 Режим повторения включен."
        )
    else:
        logging.info("➡️ Repeat mode: OFF")

        await interaction.response.send_message(
            "➡️ Режим повторения выключен."
        )


# Запуск бота
bot.run(TOKEN)