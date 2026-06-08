import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# Bot setup with slash command support
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────
#  Aternos helper (wraps python-aternos)
# ─────────────────────────────────────────────
class AternosManager:
    def __init__(self):
        self.client = None
        self.server = None

    def connect(self):
        """Log in to Aternos and select the first server."""
        try:
            from python_aternos import Client
            username = os.getenv("ATERNOS_USERNAME")
            password = os.getenv("ATERNOS_PASSWORD")
            server_name = os.getenv("ATERNOS_SERVER")  # optional filter

            if not username or not password:
                raise ValueError("ATERNOS_USERNAME and ATERNOS_PASSWORD must be set in .env")

            self.client = Client.from_credentials(username, password)
            servers = self.client.list_servers()

            if not servers:
                raise ValueError("No Aternos servers found for this account.")

            # Pick server by name, or default to first
            if server_name:
                matches = [s for s in servers if server_name.lower() in s.domain.lower()]
                self.server = matches[0] if matches else servers[0]
            else:
                self.server = servers[0]

            log.info(f"Connected to Aternos server: {self.server.domain}")
            return True, self.server.domain

        except Exception as e:
            log.error(f"Aternos connection error: {e}")
            return False, str(e)

    def get_status(self):
        """Return the current server status string."""
        try:
            if not self.server:
                ok, msg = self.connect()
                if not ok:
                    return "error", msg
            self.server.fetch()
            return self.server.status, self.server.domain
        except Exception as e:
            return "error", str(e)

    def start(self):
        try:
            if not self.server:
                ok, msg = self.connect()
                if not ok:
                    return False, msg
            status, domain = self.get_status()
            if status == "online":
                return False, "Server is already online!"
            if status in ("starting", "loading"):
                return False, f"Server is already {status}, please wait…"
            self.server.start()
            return True, domain
        except Exception as e:
            return False, str(e)

    def stop(self):
        try:
            if not self.server:
                ok, msg = self.connect()
                if not ok:
                    return False, msg
            status, domain = self.get_status()
            if status == "offline":
                return False, "Server is already offline."
            self.server.stop()
            return True, domain
        except Exception as e:
            return False, str(e)


aternos = AternosManager()


# ─────────────────────────────────────────────
#  Embeds
# ─────────────────────────────────────────────
STATUS_COLORS = {
    "online":   discord.Color.green(),
    "offline":  discord.Color.red(),
    "starting": discord.Color.orange(),
    "loading":  discord.Color.orange(),
    "stopping": discord.Color.orange(),
    "error":    discord.Color.dark_red(),
}

STATUS_EMOJIS = {
    "online":   "🟢",
    "offline":  "🔴",
    "starting": "🟡",
    "loading":  "🟡",
    "stopping": "🟠",
    "error":    "❌",
}

def make_embed(title: str, description: str, status: str = "offline") -> discord.Embed:
    color = STATUS_COLORS.get(status, discord.Color.blurple())
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Aternos Minecraft Bot • powered by discord.py")
    return embed


# ─────────────────────────────────────────────
#  Slash Commands
# ─────────────────────────────────────────────
@bot.tree.command(name="start", description="Start the Minecraft server on Aternos")
async def start_server(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    # Permission check — only allowed roles/users
    allowed_role = os.getenv("ALLOWED_ROLE_NAME")
    if allowed_role:
        role_names = [r.name for r in interaction.user.roles]
        if allowed_role not in role_names:
            embed = make_embed(
                "⛔ Access Denied",
                f"You need the **{allowed_role}** role to start the server.",
                "error"
            )
            await interaction.followup.send(embed=embed)
            return

    log.info(f"{interaction.user} requested server start")
    success, info = await asyncio.get_event_loop().run_in_executor(None, aternos.start)

    if success:
        embed = make_embed(
            "🚀 Server Starting!",
            f"**{info}** is now booting up.\n\n"
            "⏳ This usually takes **2–4 minutes**.\n"
            "Use `/status` to check when it's ready.",
            "starting"
        )
    else:
        embed = make_embed("⚠️ Couldn't Start Server", info, "error")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="stop", description="Stop the Minecraft server on Aternos")
async def stop_server(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    allowed_role = os.getenv("ALLOWED_ROLE_NAME")
    if allowed_role:
        role_names = [r.name for r in interaction.user.roles]
        if allowed_role not in role_names:
            embed = make_embed(
                "⛔ Access Denied",
                f"You need the **{allowed_role}** role to stop the server.",
                "error"
            )
            await interaction.followup.send(embed=embed)
            return

    log.info(f"{interaction.user} requested server stop")
    success, info = await asyncio.get_event_loop().run_in_executor(None, aternos.stop)

    if success:
        embed = make_embed(
            "🛑 Server Stopping",
            f"**{info}** is shutting down.\nSee you next time! 👋",
            "stopping"
        )
    else:
        embed = make_embed("⚠️ Couldn't Stop Server", info, "error")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="status", description="Check the current Minecraft server status")
async def server_status(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    status, domain = await asyncio.get_event_loop().run_in_executor(None, aternos.get_status)
    emoji = STATUS_EMOJIS.get(status, "❓")

    description = f"**Server:** `{domain}`\n**Status:** {emoji} `{status.upper()}`"

    if status == "online":
        description += f"\n\n✅ Server is live! Connect at:\n```{domain}```"
    elif status in ("starting", "loading"):
        description += "\n\n⏳ Server is warming up, hang tight…"
    elif status == "offline":
        description += "\n\nUse `/start` to launch the server."

    embed = make_embed(f"{emoji} Server Status", description, status)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="help", description="Show all available bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Minecraft Aternos Bot — Commands",
        color=discord.Color.blurple()
    )
    embed.add_field(name="/start",  value="Start the Minecraft server",       inline=False)
    embed.add_field(name="/stop",   value="Stop the Minecraft server",        inline=False)
    embed.add_field(name="/status", value="Check current server status",      inline=False)
    embed.add_field(name="/help",   value="Show this help message",           inline=False)
    embed.set_footer(text="Aternos Minecraft Bot • powered by discord.py")
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────
#  Background task: auto-status every 5 minutes
# ─────────────────────────────────────────────
@tasks.loop(minutes=5)
async def auto_status():
    channel_id = os.getenv("STATUS_CHANNEL_ID")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return
    status, domain = await asyncio.get_event_loop().run_in_executor(None, aternos.get_status)
    emoji = STATUS_EMOJIS.get(status, "❓")
    await channel.send(
        embed=make_embed(
            f"{emoji} Auto Status Update",
            f"**{domain}** — `{status.upper()}`",
            status
        )
    )


# ─────────────────────────────────────────────
#  Bot events
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        log.error(f"Failed to sync commands: {e}")

    # Pre-connect to Aternos
    ok, info = await asyncio.get_event_loop().run_in_executor(None, aternos.connect)
    if ok:
        log.info(f"Aternos pre-connected: {info}")
    else:
        log.warning(f"Aternos pre-connect failed: {info}")

    # Start auto-status loop if channel is configured
    if os.getenv("STATUS_CHANNEL_ID"):
        auto_status.start()

    await bot.change_presence(
        activity=discord.Game(name="Minecraft on Aternos 🎮")
    )


# ─────────────────────────────────────────────
#  Run
# ─────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in .env")
    bot.run(token)
