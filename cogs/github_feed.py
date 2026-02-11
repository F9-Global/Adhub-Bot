"""
GitHub feed cog for AdHub Bot.
Listens for embeds posted by the official Discord GitHub integration
in the feed channel, parses them, and buffers events for the rebase
reminder digest.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands
from discord.ext.commands import Context


class GitHubFeed(commands.Cog, name="github_feed"):
    def __init__(self, bot) -> None:
        self.bot = bot
        # Event buffer for rebase digest - list of dicts
        self.event_buffer = []
        self._backfilled = False

    @commands.Cog.listener("on_ready")
    async def on_ready_backfill(self) -> None:
        """Backfill missed events from channel history on startup."""
        await self._backfill()

    @staticmethod
    def _last_rebase_time() -> datetime:
        """Calculate the most recent scheduled rebase time (12 PM or 6 PM UTC+8)."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Manila")
        now = datetime.now(tz)
        # Rebase times in UTC+8: 12:00, 18:00
        rebase_hours = [12, 18]

        for h in sorted(rebase_hours, reverse=True):
            candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if candidate <= now:
                return candidate.astimezone(timezone.utc)

        # Before 12 PM today — last rebase was 6 PM yesterday
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    async def _backfill(self) -> None:
        """Scan feed channel messages since last rebase and parse missed GitHub embeds."""
        if self._backfilled:
            return
        self._backfilled = True

        channel = self._get_channel()
        if not channel:
            return

        cutoff = self._last_rebase_time()
        count = 0
        self.bot.logger.info(f"Backfilling GitHub events since {cutoff.isoformat()}")

        async for message in channel.history(after=cutoff, limit=200, oldest_first=True):
            if not message.author.bot:
                continue
            if not message.embeds:
                continue
            for embed in message.embeds:
                record = self._parse_github_embed(embed)
                if record:
                    # Use the message timestamp instead of now
                    record["timestamp"] = message.created_at
                    self.event_buffer.append(record)
                    count += 1

        if count:
            self.bot.logger.info(f"Backfilled {count} GitHub events from channel history")

    def _get_channel(self):
        channel_id = os.getenv("GITHUB_FEED_CHANNEL_ID")
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    def drain_buffer(self) -> list[dict]:
        """Return all buffered events and clear the buffer."""
        events = self.event_buffer.copy()
        self.event_buffer.clear()
        return events

    def peek_buffer(self) -> list[dict]:
        """Return buffered events without clearing."""
        return self.event_buffer.copy()

    # ── Listen for GitHub integration embeds ───────────────────────

    @commands.Cog.listener("on_message")
    async def on_github_embed(self, message: discord.Message) -> None:
        """Parse embeds posted by the Discord GitHub integration."""
        channel_id = os.getenv("GITHUB_FEED_CHANNEL_ID")
        if not channel_id:
            return

        # Only listen in the feed channel
        if message.channel.id != int(channel_id):
            return

        # Only process bot/webhook messages (GitHub integration posts as an app)
        if not message.author.bot:
            return

        if not message.embeds:
            return

        for embed in message.embeds:
            record = self._parse_github_embed(embed)
            if record:
                self.event_buffer.append(record)
                self.bot.logger.info(
                    f"Buffered GitHub event: {record['type']} from {record.get('sender', 'unknown')}"
                )

    def _parse_github_embed(self, embed: discord.Embed) -> Optional[dict]:
        """Parse a Discord GitHub integration embed into a buffer record."""
        title = embed.title or ""
        description = embed.description or ""
        url = str(embed.url) if embed.url else ""
        author_name = embed.author.name if embed.author else "unknown"
        now = datetime.now(timezone.utc)

        # ── Push: "[repo:branch] N new commit(s)" ──
        push_match = re.match(r"\[(.+):(.+)\] (\d+) new commits?", title)
        if push_match:
            repo = push_match.group(1)
            branch = push_match.group(2)
            commit_count = int(push_match.group(3))

            # Parse commit lines from description: "`sha` message - author"
            commits = []
            for line in description.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Format: [`sha`](url) message - author
                # or simpler: `sha` message
                commit_match = re.match(
                    r"\[`([a-f0-9]+)`\]\(([^)]+)\)\s+(.+?)(?:\s+-\s+.+)?$", line
                )
                if commit_match:
                    commits.append({
                        "sha": commit_match.group(1),
                        "url": commit_match.group(2),
                        "message": commit_match.group(3).strip(),
                    })
                else:
                    # Fallback: plain text commit line
                    plain_match = re.match(r"`([a-f0-9]+)`\s+(.+?)(?:\s+-\s+.+)?$", line)
                    if plain_match:
                        commits.append({
                            "sha": plain_match.group(1),
                            "url": url,
                            "message": plain_match.group(2).strip(),
                        })

            return {
                "type": "push",
                "timestamp": now,
                "repo": repo,
                "sender": author_name,
                "branch": branch,
                "pusher": author_name,
                "commit_count": commit_count,
                "commits": commits[:15],
                "compare_url": url,
            }

        # ── Pull Request: title contains "pull request" ──
        pr_match = re.match(
            r"\[(.+)\] Pull request #(\d+)\s+(.+?):\s+(.+)", title, re.IGNORECASE
        )
        if pr_match:
            return {
                "type": "pull_request",
                "timestamp": now,
                "repo": pr_match.group(1),
                "sender": author_name,
                "action": pr_match.group(3).strip().lower(),
                "pr_number": int(pr_match.group(2)),
                "pr_title": pr_match.group(4).strip(),
                "pr_url": url,
                "head": "",
                "base": "",
                "merged": "merged" in title.lower(),
                "additions": 0,
                "deletions": 0,
                "changed_files": 0,
            }

        # Simpler PR pattern: "[repo] Pull request opened: #N title"
        pr_match2 = re.match(
            r"\[(.+)\] Pull request (\w+)\s*(?:#(\d+))?\s*(.*)", title, re.IGNORECASE
        )
        if pr_match2:
            pr_num_str = pr_match2.group(3) or "0"
            return {
                "type": "pull_request",
                "timestamp": now,
                "repo": pr_match2.group(1),
                "sender": author_name,
                "action": pr_match2.group(2).strip().lower(),
                "pr_number": int(pr_num_str),
                "pr_title": pr_match2.group(4).strip(),
                "pr_url": url,
                "head": "",
                "base": "",
                "merged": "merged" in title.lower(),
                "additions": 0,
                "deletions": 0,
                "changed_files": 0,
            }

        # ── Issue: title contains "Issue" ──
        issue_match = re.match(
            r"\[(.+)\] Issue #(\d+)\s+(.+?):\s+(.+)", title, re.IGNORECASE
        )
        if not issue_match:
            issue_match = re.match(
                r"\[(.+)\] Issue (\w+)\s*(?:#(\d+))?\s*(.*)", title, re.IGNORECASE
            )
            if issue_match:
                return {
                    "type": "issues",
                    "timestamp": now,
                    "repo": issue_match.group(1),
                    "sender": author_name,
                    "action": issue_match.group(2).strip().lower(),
                    "issue_number": int(issue_match.group(3) or 0),
                    "issue_title": issue_match.group(4).strip(),
                    "issue_url": url,
                }
        if issue_match:
            return {
                "type": "issues",
                "timestamp": now,
                "repo": issue_match.group(1),
                "sender": author_name,
                "action": issue_match.group(3).strip().lower(),
                "issue_number": int(issue_match.group(2)),
                "issue_title": issue_match.group(4).strip(),
                "issue_url": url,
            }

        # ── Create: title contains "created" ──
        create_match = re.match(
            r"\[(.+)\] New (\w+) created: `?(.+?)`?$", title, re.IGNORECASE
        )
        if create_match:
            return {
                "type": "create",
                "timestamp": now,
                "repo": create_match.group(1),
                "sender": author_name,
                "ref_type": create_match.group(2),
                "ref": create_match.group(3),
            }

        # ── Delete: title contains "deleted" ──
        delete_match = re.match(
            r"\[(.+)\] (\w+) deleted: `?(.+?)`?$", title, re.IGNORECASE
        )
        if delete_match:
            return {
                "type": "delete",
                "timestamp": now,
                "repo": delete_match.group(1),
                "sender": author_name,
                "ref_type": delete_match.group(2).lower(),
                "ref": delete_match.group(3),
            }

        # ── Release: title contains "Release" ──
        release_match = re.match(
            r"\[(.+)\] (?:New )?[Rr]elease (.+?)(?:\s+(published|created|drafted))?$",
            title,
        )
        if release_match:
            return {
                "type": "release",
                "timestamp": now,
                "repo": release_match.group(1),
                "sender": author_name,
                "tag": release_match.group(2).strip(),
                "release_name": release_match.group(2).strip(),
                "release_url": url,
                "action": release_match.group(3) or "published",
            }

        # Unknown embed — skip
        return None

    # ── Commands ───────────────────────────────────────────────────

    @commands.hybrid_command(
        name="github-status",
        description="Show the latest GitHub activity summary.",
    )
    async def github_status(self, context: Context) -> None:
        """Show which channel is receiving GitHub events and buffered event count."""
        channel = self._get_channel()
        buffered = len(self.event_buffer)
        if channel:
            embed = discord.Embed(
                title="GitHub Feed Status",
                description=(
                    f"GitHub events are being read from {channel.mention}\n"
                    f"**{buffered}** events buffered for next rebase digest"
                ),
                color=0x2EA44F,
            )
        else:
            embed = discord.Embed(
                title="GitHub Feed Status",
                description="GitHub feed channel is not configured. Set `GITHUB_FEED_CHANNEL_ID` in `.env`.",
                color=0xE02B2B,
            )
        await context.send(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(GitHubFeed(bot))
