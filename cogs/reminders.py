"""
Scheduled reminders cog for AdHub Bot.
Sends rebase digest at 12:00 AM and 6:00 PM UTC+8 with a compiled
summary of all GitHub activity since the last digest.

Timeline per rebase:
  T-30  Heads up — wrap up your work
  T-10  Push to dev NOW
  T-0   Rebase digest — pull from dev, rebase feature branches

Schedule (fixed):
  12:00 AM UTC+8  (warnings at 11:30 PM, 11:50 PM)
   6:00 PM UTC+8  (warnings at  5:30 PM,  5:50 PM)
"""

import os
from collections import defaultdict
from datetime import datetime, time, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands import Context

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# UTC+8 timezone
TZ_UTC8 = ZoneInfo("Asia/Manila")

# Fixed rebase reminder times in UTC+8
REMINDER_TIMES = [
    time(hour=0, minute=0, tzinfo=TZ_UTC8),   # 12:00 AM UTC+8
    time(hour=18, minute=0, tzinfo=TZ_UTC8),   # 6:00 PM UTC+8
]

# Timezone display table for the embed
TIMEZONE_TABLE = {
    "UTC+8 (PH/SG/HK)": TZ_UTC8,
    "UTC": ZoneInfo("UTC"),
    "EST (US East)": ZoneInfo("America/New_York"),
    "PST (US West)": ZoneInfo("America/Los_Angeles"),
    "JST (Japan)": ZoneInfo("Asia/Tokyo"),
    "GMT (London)": ZoneInfo("Europe/London"),
}


class Reminders(commands.Cog, name="reminders"):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.rebase_reminder.start()

    async def cog_unload(self) -> None:
        self.rebase_reminder.cancel()

    def _get_channel(self):
        channel_id = os.getenv("REMINDERS_CHANNEL_ID")
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    def _get_ping(self) -> str:
        role_id = os.getenv("REBASE_PING_ROLE_ID")
        if role_id:
            return f"<@&{role_id}>"
        return "@here"

    @tasks.loop(minutes=1.0)
    async def rebase_reminder(self) -> None:
        """Check every minute for T-30 warning, T-10 push reminder, or T-0 rebase digest."""
        now = datetime.now(TZ_UTC8)
        current = now.hour * 60 + now.minute  # minutes since midnight

        for rt in REMINDER_TIMES:
            rebase_min = rt.hour * 60 + rt.minute
            rebase_time_str = rt.strftime("%I:%M %p")

            if current == rebase_min - 30:
                await self._send_warning(
                    title=f"Rebase in 30 minutes ({rebase_time_str} UTC+8)",
                    message="Wrap up what you're working on. Push to `dev` within the next 20 minutes.",
                    color=0x0969DA,  # Blue
                )
                break
            elif current == rebase_min - 10:
                await self._send_warning(
                    title=f"Push to dev NOW — Rebase in 10 minutes ({rebase_time_str} UTC+8)",
                    message=(
                        "Push your changes to `dev` before the rebase.\n"
                        "```git push origin dev```"
                    ),
                    color=0xE8A317,  # Orange
                )
                break
            elif current == rebase_min:
                await self._send_rebase_digest(now)
                break

    @rebase_reminder.before_loop
    async def before_rebase_reminder(self) -> None:
        await self.bot.wait_until_ready()

    def _build_timezone_string(self, utc8_time: datetime) -> str:
        """Build a multi-timezone display string for the embed."""
        lines = []
        for label, tz in TIMEZONE_TABLE.items():
            converted = utc8_time.astimezone(tz)
            lines.append(f"**{label}:** {converted.strftime('%I:%M %p %b %d')}")
        return "\n".join(lines)

    def _build_activity_summary(self, events: list[dict]) -> str:
        """Build a Design 1 (Clean & Compact) activity summary."""
        if not events:
            return ""

        # ── Group events ──
        dev_pushes = defaultdict(lambda: {"commit_count": 0, "commits": []})
        other_pushes = defaultdict(lambda: {"branches": set(), "commit_count": 0})
        prs = []
        branches_created = []
        branches_deleted = []
        issues_list = []
        releases = []

        for e in events:
            etype = e["type"]
            if etype == "push":
                user = e.get("pusher", e["sender"])
                branch = e.get("branch", "?")
                if branch == "dev":
                    dev_pushes[user]["commit_count"] += e.get("commit_count", 0)
                    dev_pushes[user]["commits"].extend(e.get("commits", []))
                else:
                    other_pushes[user]["branches"].add(branch)
                    other_pushes[user]["commit_count"] += e.get("commit_count", 0)
            elif etype == "pull_request":
                prs.append(e)
            elif etype == "create":
                branches_created.append(e)
            elif etype == "delete":
                branches_deleted.append(e)
            elif etype == "issues":
                issues_list.append(e)
            elif etype == "release":
                releases.append(e)

        desc = ""

        # ── Dev commits ──
        if dev_pushes:
            total = sum(d["commit_count"] for d in dev_pushes.values())
            desc += f"**Commits to `dev`** ({total})\n"
            for user, data in dev_pushes.items():
                desc += f"> **{user}** pushed {data['commit_count']}\n"
                for c in data["commits"][:3]:
                    desc += f"> `{c['sha']}` {c['message']}\n"
                if len(data["commits"]) > 3:
                    remaining = len(data["commits"]) - 3
                    desc += f"> *... +{remaining} more*\n"
            desc += "\n"

        # ── PRs ──
        if prs:
            desc += f"**Pull Requests** ({len(prs)})\n"
            for pr in prs:
                action = pr.get("action", "")
                if action == "closed" and pr.get("merged"):
                    action = "merged"
                desc += f"> #{pr['pr_number']} {pr['pr_title']} (*{action}*)\n"
            desc += "\n"

        # ── Branches ──
        if branches_created or branches_deleted:
            items = [f"+ `{b.get('ref', '?')}`" for b in branches_created]
            items += [f"- `{b.get('ref', '?')}`" for b in branches_deleted]
            desc += f"**Branches** {' '.join(items)}\n"

        # ── Issues ──
        if issues_list:
            for iss in issues_list:
                desc += f"**Issue** #{iss['issue_number']} {iss['issue_title']} (*{iss.get('action', '')}*)\n"

        # ── Releases ──
        if releases:
            for rel in releases:
                desc += f"**Release** {rel.get('tag', '?')} (*{rel.get('action', '')}*)\n"

        # ── Other branches — small text ──
        if other_pushes:
            total = sum(d["commit_count"] for d in other_pushes.values())
            parts = []
            for user, data in other_pushes.items():
                branches_str = ", ".join(sorted(data["branches"]))
                parts.append(f"{user}: {data['commit_count']} on {branches_str}")
            joiner = " | ".join(parts)
            desc += f"\n-# Other branches ({total} commits): {joiner}"

        return desc

    async def _send_warning(self, title: str, message: str, color: int, suppress_ping: bool = False) -> None:
        """Send a short warning embed to the reminders channel."""
        channel = self._get_channel()
        if not channel:
            return
        ping = None if suppress_ping else self._get_ping()
        embed = discord.Embed(title=title, description=message, color=color)
        await channel.send(content=ping, embed=embed)

    async def _send_rebase_digest(self, now: datetime, suppress_ping: bool = False) -> None:
        """Send the rebase digest as a single compact embed (Design 1)."""
        channel = self._get_channel()
        if not channel:
            self.bot.logger.warning("REMINDERS_CHANNEL_ID not set or channel not found")
            return

        ping = None if suppress_ping else self._get_ping()

        # Determine session label
        if now.hour == 0:
            session = "Midnight"
            color = 0xE8A317  # Orange
        else:
            session = "End of Day"
            color = 0xCF222E  # Red

        # ── Drain the event buffer from github_feed cog ──
        github_cog = self.bot.get_cog("github_feed")
        events = []
        if github_cog:
            events = github_cog.drain_buffer()

        # ── Build Design 1 embed ──
        desc = "```git fetch origin && git rebase origin/dev```\n"

        activity = self._build_activity_summary(events)
        if activity:
            desc += activity
        else:
            desc += "*No activity since last digest.*"

        embed = discord.Embed(
            title=f"Rebase — {session} ({now.strftime('%I:%M %p')} UTC+8)",
            description=desc[:4096],
            color=color,
        )
        embed.set_footer(text="/rebase-now \u2022 /rebase-schedule \u2022 /activity-preview")
        embed.timestamp = now

        await channel.send(content=ping, embeds=[embed])

    # ── Slash commands ──────────────────────────────────────────────

    @commands.hybrid_command(
        name="rebase-schedule",
        description="Show the rebase reminder schedule across timezones.",
    )
    async def rebase_schedule(self, context: Context) -> None:
        """Show the current rebase reminder schedule with timezone conversions."""
        now = datetime.now(TZ_UTC8)

        lines = []
        for rt in REMINDER_TIMES:
            # Build a full datetime for today at this reminder time
            dt = now.replace(hour=rt.hour, minute=rt.minute, second=0, microsecond=0)
            tz_parts = []
            for label, tz in TIMEZONE_TABLE.items():
                converted = dt.astimezone(tz)
                tz_parts.append(f"{label}: **{converted.strftime('%I:%M %p')}**")
            lines.append(f"**{rt.strftime('%I:%M %p')} UTC+8**\n" + " | ".join(tz_parts))

        channel = self._get_channel()
        github_cog = self.bot.get_cog("github_feed")
        buffered = len(github_cog.event_buffer) if github_cog else 0

        embed = discord.Embed(
            title="Rebase Reminder Schedule",
            description=(
                f"**Channel:** {channel.mention if channel else 'Not configured'}\n"
                f"**Ping:** {self._get_ping()}\n"
                f"**Buffered events:** {buffered} (will be included in next digest)\n\n"
                + "\n\n".join(lines)
            ),
            color=0x2EA44F,
        )
        embed.set_footer(text="Warnings at T-30 and T-10 | Rebase at 12:00 AM and 6:00 PM UTC+8")
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="rebase-now",
        description="Trigger a rebase digest right now with all buffered activity.",
    )
    @commands.has_permissions(manage_messages=True)
    async def rebase_now(self, context: Context) -> None:
        """Manually trigger a rebase digest with accumulated activity."""
        now = datetime.now(TZ_UTC8)
        await self._send_rebase_digest(now)
        await context.send("Rebase digest sent!", ephemeral=True)

    @commands.hybrid_command(
        name="activity-preview",
        description="Preview buffered GitHub activity without sending digest.",
    )
    async def activity_preview(self, context: Context) -> None:
        """Preview what the next rebase digest will contain."""
        github_cog = self.bot.get_cog("github_feed")
        if not github_cog:
            await context.send("GitHub feed cog not loaded.", ephemeral=True)
            return

        events = github_cog.peek_buffer()
        if not events:
            embed = discord.Embed(
                title="Activity Preview",
                description="No events buffered since last digest.",
                color=0x808080,
            )
            await context.send(embed=embed, ephemeral=True)
            return

        activity = self._build_activity_summary(events)
        embed = discord.Embed(
            title=f"Activity Preview — {len(events)} events buffered",
            description=activity or "No events.",
            color=0x0969DA,
        )
        embed.set_footer(text="Events are NOT cleared by this preview.")
        await context.send(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Reminders(bot))
