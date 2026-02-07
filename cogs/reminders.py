"""
Scheduled reminders cog for AdHub Bot.
Handles rebase reminders and other scheduled team notifications.
"""

import os
from datetime import datetime, time, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands import Context

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


def parse_reminder_times() -> list[time]:
    """Parse REBASE_REMINDER_TIMES env var into a list of time objects."""
    raw = os.getenv("REBASE_REMINDER_TIMES", "09:00,13:00,17:00")
    tz_name = os.getenv("REBASE_REMINDER_TIMEZONE", "America/New_York")
    tz = ZoneInfo(tz_name)
    times = []
    for t in raw.split(","):
        t = t.strip()
        if not t:
            continue
        parts = t.split(":")
        hours, minutes = int(parts[0]), int(parts[1])
        times.append(time(hour=hours, minute=minutes, tzinfo=tz))
    return times


class Reminders(commands.Cog, name="reminders"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.reminder_times = parse_reminder_times()

    async def cog_load(self) -> None:
        """Start the reminder loop when the cog loads."""
        self.rebase_reminder.start()

    async def cog_unload(self) -> None:
        """Stop the reminder loop when the cog unloads."""
        self.rebase_reminder.cancel()

    def _get_channel(self):
        channel_id = os.getenv("REMINDERS_CHANNEL_ID")
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    def _get_ping(self) -> str:
        """Get the role mention string for pinging the team."""
        role_id = os.getenv("REBASE_PING_ROLE_ID")
        if role_id:
            return f"<@&{role_id}>"
        return "@here"

    @tasks.loop(minutes=1.0)
    async def rebase_reminder(self) -> None:
        """Check every minute if it's time to send a rebase reminder."""
        tz_name = os.getenv("REBASE_REMINDER_TIMEZONE", "America/New_York")
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)

        for reminder_time in self.reminder_times:
            # Check if current time matches a reminder time (within the same minute)
            if now.hour == reminder_time.hour and now.minute == reminder_time.minute:
                await self._send_rebase_reminder(now)
                break  # Only send one reminder per minute

    @rebase_reminder.before_loop
    async def before_rebase_reminder(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_rebase_reminder(self, now: datetime) -> None:
        """Send the rebase reminder embed to the configured channel."""
        channel = self._get_channel()
        if not channel:
            self.bot.logger.warning("REMINDERS_CHANNEL_ID not set or channel not found")
            return

        ping = self._get_ping()
        time_str = now.strftime("%I:%M %p %Z")

        # Determine urgency based on time of day
        hour = now.hour
        if hour >= 16:
            urgency = "End of Day"
            color = 0xCF222E  # Red - EOD
            description = (
                "**EOD rebase checkpoint!** Make sure your branch is up to date "
                "with `dev` before wrapping up.\n\n"
            )
        elif hour >= 12:
            urgency = "Afternoon"
            color = 0xE8A317  # Orange - midday
            description = (
                "**Afternoon rebase check!** Good time to sync up with `dev` "
                "before the afternoon push.\n\n"
            )
        else:
            urgency = "Morning"
            color = 0x2EA44F  # Green - morning
            description = (
                "**Morning rebase reminder!** Start fresh - pull the latest "
                "`dev` before coding.\n\n"
            )

        description += (
            "```bash\n"
            "# From your feature branch:\n"
            "git fetch origin\n"
            "git rebase origin/dev\n"
            "# Resolve any conflicts, then:\n"
            "git push --force-with-lease\n"
            "```"
        )

        embed = discord.Embed(
            title=f"Rebase Reminder - {urgency} ({time_str})",
            description=description,
            color=color,
        )
        embed.add_field(
            name="Why rebase?",
            value="We're shipping fast. Rebasing often prevents painful merge conflicts later.",
            inline=False,
        )
        embed.set_footer(text="Use /rebase-schedule to view or change reminder times")
        embed.timestamp = now

        await channel.send(content=ping, embed=embed)

    @commands.hybrid_command(
        name="rebase-schedule",
        description="Show or update the rebase reminder schedule.",
    )
    async def rebase_schedule(self, context: Context) -> None:
        """Show the current rebase reminder schedule."""
        tz_name = os.getenv("REBASE_REMINDER_TIMEZONE", "America/New_York")
        times_str = "\n".join(
            [f"- **{t.strftime('%I:%M %p')}**" for t in self.reminder_times]
        )

        embed = discord.Embed(
            title="Rebase Reminder Schedule",
            description=(
                f"**Timezone:** {tz_name}\n"
                f"**Channel:** {self._get_channel().mention if self._get_channel() else 'Not configured'}\n"
                f"**Ping:** {self._get_ping()}\n\n"
                f"**Scheduled times:**\n{times_str}"
            ),
            color=0x2EA44F,
        )
        embed.set_footer(
            text="Edit REBASE_REMINDER_TIMES in .env to change (comma-separated HH:MM)"
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="rebase-now",
        description="Send a rebase reminder to the team right now.",
    )
    @commands.has_permissions(manage_messages=True)
    async def rebase_now(self, context: Context) -> None:
        """Manually trigger a rebase reminder."""
        tz_name = os.getenv("REBASE_REMINDER_TIMEZONE", "America/New_York")
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        await self._send_rebase_reminder(now)
        await context.send("Rebase reminder sent!", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Reminders(bot))
