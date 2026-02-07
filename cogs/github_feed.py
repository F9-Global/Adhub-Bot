"""
GitHub webhook feed cog for AdHub Bot.
Receives GitHub events from the webhook server in bot.py and posts
formatted embeds to a configured Discord channel.
"""

import os
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context


# Embed colors per event type
COLORS = {
    "push": 0x2EA44F,       # GitHub green
    "pull_request": 0x6F42C1,  # Purple
    "create": 0x0969DA,     # Blue
    "delete": 0xCF222E,     # Red
    "issues": 0xE8A317,     # Orange
    "issue_comment": 0xE8A317,
    "release": 0xFFD700,    # Gold
    "star": 0xFFD700,
    "fork": 0x0969DA,
    "ping": 0x808080,       # Gray
}


class GitHubFeed(commands.Cog, name="github_feed"):
    def __init__(self, bot) -> None:
        self.bot = bot

    def _get_channel(self):
        channel_id = os.getenv("GITHUB_FEED_CHANNEL_ID")
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    async def process_event(self, event_type: str, payload: dict) -> None:
        """Called by the webhook server in bot.py when a GitHub event is received."""
        channel = self._get_channel()
        if not channel:
            self.bot.logger.warning("GITHUB_FEED_CHANNEL_ID not set or channel not found")
            return

        embed = None

        if event_type == "push":
            embed = self._build_push_embed(payload)
        elif event_type == "pull_request":
            embed = self._build_pr_embed(payload)
        elif event_type == "create":
            embed = self._build_create_embed(payload)
        elif event_type == "delete":
            embed = self._build_delete_embed(payload)
        elif event_type == "issues":
            embed = self._build_issue_embed(payload)
        elif event_type == "issue_comment":
            embed = self._build_comment_embed(payload)
        elif event_type == "release":
            embed = self._build_release_embed(payload)
        elif event_type == "ping":
            embed = discord.Embed(
                title="Webhook Connected",
                description=f"GitHub webhook successfully connected for **{payload.get('repository', {}).get('full_name', 'unknown')}**",
                color=COLORS["ping"],
            )
        else:
            self.bot.logger.info(f"Unhandled GitHub event: {event_type}")
            return

        if embed:
            # Add repo footer to all embeds
            repo = payload.get("repository", {})
            if repo:
                embed.set_footer(
                    text=repo.get("full_name", ""),
                    icon_url=repo.get("owner", {}).get("avatar_url", ""),
                )
            embed.timestamp = datetime.utcnow()
            await channel.send(embed=embed)

    def _build_push_embed(self, payload: dict) -> discord.Embed:
        commits = payload.get("commits", [])
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        pusher = payload.get("pusher", {}).get("name", "unknown")
        compare_url = payload.get("compare", "")

        commit_list = ""
        for c in commits[:10]:
            sha_short = c["id"][:7]
            msg = c["message"].split("\n")[0][:72]
            commit_list += f"[`{sha_short}`]({c['url']}) {msg}\n"

        if len(commits) > 10:
            commit_list += f"... and {len(commits) - 10} more commits\n"

        embed = discord.Embed(
            title=f"[{repo}:{branch}] {len(commits)} new commit{'s' if len(commits) != 1 else ''}",
            description=commit_list or "No commits",
            url=compare_url,
            color=COLORS["push"],
        )
        embed.set_author(
            name=pusher,
            icon_url=payload.get("sender", {}).get("avatar_url", ""),
        )
        return embed

    def _build_pr_embed(self, payload: dict) -> discord.Embed:
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {}).get("full_name", "unknown")
        user = pr.get("user", {})
        base = pr.get("base", {}).get("ref", "")
        head = pr.get("head", {}).get("ref", "")

        action_text = {
            "opened": "opened",
            "closed": "merged" if pr.get("merged") else "closed",
            "reopened": "reopened",
            "synchronize": "updated",
            "ready_for_review": "marked ready for review",
        }.get(action, action)

        color = COLORS["pull_request"]
        if action == "closed" and pr.get("merged"):
            color = 0x8957E5  # Merged purple

        embed = discord.Embed(
            title=f"[{repo}] Pull request #{pr.get('number', '?')} {action_text}",
            description=f"**{pr.get('title', '')}**\n`{head}` -> `{base}`\n\n{(pr.get('body') or '')[:300]}",
            url=pr.get("html_url", ""),
            color=color,
        )
        embed.set_author(
            name=user.get("login", "unknown"),
            icon_url=user.get("avatar_url", ""),
        )
        embed.add_field(name="Additions", value=f"+{pr.get('additions', 0)}", inline=True)
        embed.add_field(name="Deletions", value=f"-{pr.get('deletions', 0)}", inline=True)
        embed.add_field(name="Files", value=str(pr.get("changed_files", 0)), inline=True)
        return embed

    def _build_create_embed(self, payload: dict) -> discord.Embed:
        ref_type = payload.get("ref_type", "")  # branch or tag
        ref = payload.get("ref", "")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        sender = payload.get("sender", {})

        embed = discord.Embed(
            title=f"[{repo}] New {ref_type} created: `{ref}`",
            color=COLORS["create"],
        )
        embed.set_author(
            name=sender.get("login", "unknown"),
            icon_url=sender.get("avatar_url", ""),
        )
        return embed

    def _build_delete_embed(self, payload: dict) -> discord.Embed:
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        sender = payload.get("sender", {})

        embed = discord.Embed(
            title=f"[{repo}] {ref_type.capitalize()} deleted: `{ref}`",
            color=COLORS["delete"],
        )
        embed.set_author(
            name=sender.get("login", "unknown"),
            icon_url=sender.get("avatar_url", ""),
        )
        return embed

    def _build_issue_embed(self, payload: dict) -> discord.Embed:
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        repo = payload.get("repository", {}).get("full_name", "unknown")
        user = issue.get("user", {})

        embed = discord.Embed(
            title=f"[{repo}] Issue #{issue.get('number', '?')} {action}",
            description=f"**{issue.get('title', '')}**\n\n{(issue.get('body') or '')[:300]}",
            url=issue.get("html_url", ""),
            color=COLORS["issues"],
        )
        embed.set_author(
            name=user.get("login", "unknown"),
            icon_url=user.get("avatar_url", ""),
        )
        labels = [l["name"] for l in issue.get("labels", [])]
        if labels:
            embed.add_field(name="Labels", value=", ".join(labels), inline=True)
        return embed

    def _build_comment_embed(self, payload: dict) -> discord.Embed:
        action = payload.get("action", "")
        comment = payload.get("comment", {})
        issue = payload.get("issue", {})
        repo = payload.get("repository", {}).get("full_name", "unknown")
        user = comment.get("user", {})

        embed = discord.Embed(
            title=f"[{repo}] Comment on #{issue.get('number', '?')}: {issue.get('title', '')}",
            description=(comment.get("body") or "")[:500],
            url=comment.get("html_url", ""),
            color=COLORS["issue_comment"],
        )
        embed.set_author(
            name=user.get("login", "unknown"),
            icon_url=user.get("avatar_url", ""),
        )
        return embed

    def _build_release_embed(self, payload: dict) -> discord.Embed:
        action = payload.get("action", "")
        release = payload.get("release", {})
        repo = payload.get("repository", {}).get("full_name", "unknown")
        author = release.get("author", {})

        embed = discord.Embed(
            title=f"[{repo}] Release {release.get('tag_name', '')} {action}",
            description=f"**{release.get('name', '')}**\n\n{(release.get('body') or '')[:500]}",
            url=release.get("html_url", ""),
            color=COLORS["release"],
        )
        embed.set_author(
            name=author.get("login", "unknown"),
            icon_url=author.get("avatar_url", ""),
        )
        return embed

    @commands.hybrid_command(
        name="github-status",
        description="Show the latest GitHub activity summary.",
    )
    async def github_status(self, context: Context) -> None:
        """Show which channel is receiving GitHub events."""
        channel = self._get_channel()
        if channel:
            embed = discord.Embed(
                title="GitHub Feed Status",
                description=f"GitHub events are being posted to {channel.mention}",
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
