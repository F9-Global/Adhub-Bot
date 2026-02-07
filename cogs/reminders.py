"""
Scheduled reminders cog for AdHub Bot.
Sends rebase digest at 12:00 PM and 6:00 PM UTC+8 with a compiled
summary of all GitHub activity since the last digest.

Schedule (fixed):
  12:00 PM UTC+8  =  04:00 UTC  =  11:00 PM EST (prev day)  =  8:00 PM PST (prev day)
   6:00 PM UTC+8  =  10:00 UTC  =   5:00 AM EST             =  2:00 AM PST
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
    time(hour=12, minute=0, tzinfo=TZ_UTC8),  # 12:00 PM UTC+8
    time(hour=18, minute=0, tzinfo=TZ_UTC8),  # 6:00 PM UTC+8
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
        """Check every minute if it's time to send a rebase digest."""
        now = datetime.now(TZ_UTC8)
        for rt in REMINDER_TIMES:
            if now.hour == rt.hour and now.minute == rt.minute:
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

    def _build_activity_digest(self, events: list[dict]) -> list[discord.Embed]:
        """Build digest embeds from buffered GitHub events."""
        if not events:
            return []

        embeds = []

        # ── Group pushes by user ──
        pushes_by_user = defaultdict(lambda: {"branches": set(), "commit_count": 0, "commits": []})
        prs = []
        branches_created = []
        branches_deleted = []
        issues_list = []
        releases = []
        other_events = []

        for e in events:
            etype = e["type"]
            if etype == "push":
                user = e.get("pusher", e["sender"])
                pushes_by_user[user]["branches"].add(e.get("branch", "unknown"))
                pushes_by_user[user]["commit_count"] += e.get("commit_count", 0)
                pushes_by_user[user]["commits"].extend(e.get("commits", []))
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
            else:
                other_events.append(e)

        # ── Push summary embed ──
        if pushes_by_user:
            desc = ""
            total_commits = 0
            for user, data in pushes_by_user.items():
                branches_str = ", ".join(f"`{b}`" for b in sorted(data["branches"]))
                desc += f"**{user}** — {data['commit_count']} commits on {branches_str}\n"

                # Show up to 5 commits per user
                for c in data["commits"][:5]:
                    desc += f"  [`{c['sha']}`]({c['url']}) {c['message']}\n"
                if len(data["commits"]) > 5:
                    desc += f"  ... and {len(data['commits']) - 5} more\n"
                desc += "\n"
                total_commits += data["commit_count"]

            push_embed = discord.Embed(
                title=f"Pushes — {total_commits} commits by {len(pushes_by_user)} dev{'s' if len(pushes_by_user) != 1 else ''}",
                description=desc[:4096],
                color=0x2EA44F,
            )
            embeds.append(push_embed)

        # ── PR summary embed ──
        if prs:
            desc = ""
            for pr in prs:
                action = pr.get("action", "")
                if action == "closed" and pr.get("merged"):
                    icon = "merged"
                elif action == "opened":
                    icon = "opened"
                elif action == "closed":
                    icon = "closed"
                else:
                    icon = action

                desc += (
                    f"[#{pr['pr_number']}]({pr['pr_url']}) **{pr['pr_title']}** "
                    f"({icon}) by {pr['sender']}\n"
                    f"  `{pr.get('head', '?')}` -> `{pr.get('base', '?')}` "
                    f"| +{pr.get('additions', 0)} -{pr.get('deletions', 0)} "
                    f"({pr.get('changed_files', 0)} files)\n\n"
                )

            pr_embed = discord.Embed(
                title=f"Pull Requests — {len(prs)} PR{'s' if len(prs) != 1 else ''}",
                description=desc[:4096],
                color=0x6F42C1,
            )
            embeds.append(pr_embed)

        # ── Branches created/deleted ──
        branch_lines = []
        for b in branches_created:
            branch_lines.append(f"+ `{b.get('ref', '?')}` created by {b['sender']}")
        for b in branches_deleted:
            branch_lines.append(f"- `{b.get('ref', '?')}` deleted by {b['sender']}")

        if branch_lines:
            branch_embed = discord.Embed(
                title=f"Branches — {len(branch_lines)} change{'s' if len(branch_lines) != 1 else ''}",
                description="\n".join(branch_lines)[:4096],
                color=0x0969DA,
            )
            embeds.append(branch_embed)

        # ── Issues ──
        if issues_list:
            desc = ""
            for iss in issues_list:
                desc += (
                    f"[#{iss['issue_number']}]({iss['issue_url']}) "
                    f"**{iss['issue_title']}** ({iss.get('action', '')}) "
                    f"by {iss['sender']}\n"
                )
            issue_embed = discord.Embed(
                title=f"Issues — {len(issues_list)}",
                description=desc[:4096],
                color=0xE8A317,
            )
            embeds.append(issue_embed)

        # ── Releases ──
        if releases:
            desc = ""
            for rel in releases:
                desc += (
                    f"[{rel.get('tag', '')}]({rel.get('release_url', '')}) "
                    f"**{rel.get('release_name', '')}** ({rel.get('action', '')}) "
                    f"by {rel['sender']}\n"
                )
            release_embed = discord.Embed(
                title=f"Releases — {len(releases)}",
                description=desc[:4096],
                color=0xFFD700,
            )
            embeds.append(release_embed)

        return embeds

    async def _send_rebase_digest(self, now: datetime) -> None:
        """Send the rebase digest: compiled activity + reminder."""
        channel = self._get_channel()
        if not channel:
            self.bot.logger.warning("REMINDERS_CHANNEL_ID not set or channel not found")
            return

        ping = self._get_ping()

        # Determine session label
        if now.hour == 12:
            session = "Midday"
            color = 0xE8A317  # Orange
            msg = "Lunch break rebase! Sync with `dev` before the afternoon push."
        else:
            session = "End of Day"
            color = 0xCF222E  # Red
            msg = "EOD rebase checkpoint! Sync with `dev` before wrapping up for the day."

        tz_display = self._build_timezone_string(now)

        # ── Drain the event buffer from github_feed cog ──
        github_cog = self.bot.get_cog("github_feed")
        events = []
        if github_cog:
            events = github_cog.drain_buffer()

        # ── Build the header embed ──
        header_desc = (
            f"**{msg}**\n\n"
            f"**Schedule across timezones:**\n{tz_display}\n\n"
        )

        if events:
            header_desc += f"**{len(events)} events** since last digest:\n"
        else:
            header_desc += "No GitHub activity since the last digest.\n"

        header_desc += (
            "\n```bash\n"
            "# From your feature branch:\n"
            "git fetch origin\n"
            "git rebase origin/dev\n"
            "# Resolve any conflicts, then:\n"
            "git push --force-with-lease\n"
            "```"
        )

        header_embed = discord.Embed(
            title=f"Rebase Digest — {session} ({now.strftime('%I:%M %p')} UTC+8)",
            description=header_desc,
            color=color,
        )
        header_embed.set_footer(text="Use /rebase-schedule to view schedule | /rebase-now to trigger manually")
        header_embed.timestamp = now

        # ── Build activity digest embeds ──
        activity_embeds = self._build_activity_digest(events)

        # ── Send everything (Discord allows up to 10 embeds per message) ──
        all_embeds = [header_embed] + activity_embeds[:9]  # Cap at 10 total
        await channel.send(content=ping, embeds=all_embeds)

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
        embed.set_footer(text="Reminders fire at 12:00 PM and 6:00 PM UTC+8 daily")
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

        activity_embeds = self._build_activity_digest(events)
        preview_header = discord.Embed(
            title=f"Activity Preview — {len(events)} events buffered",
            description="This is what will be included in the next rebase digest. Events are NOT cleared by this preview.",
            color=0x0969DA,
        )
        all_embeds = [preview_header] + activity_embeds[:9]
        await context.send(embeds=all_embeds, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Reminders(bot))
