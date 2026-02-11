"""
Commit Summary cog for AdHub Bot.
Fetches recent commits from the adhub repo and uses Claude (Anthropic API)
to generate a human-readable standup-style summary.
"""

import os
from datetime import datetime, timezone, timedelta

import aiohttp
import anthropic
import discord
from discord.ext import commands
from discord.ext.commands import Context

REPO_NAME = "adhub"


class CommitSummary(commands.Cog, name="commit_summary"):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="commit-summary",
        description="AI-powered summary of recent commits in adhub.",
    )
    async def commit_summary(
        self, context: Context, branch: str = None, hours: int = 24
    ) -> None:
        """Fetch recent commits from the adhub repo and summarize with Claude.

        :param branch: Branch to check (e.g. main, dev). Shows all branches if omitted.
        :param hours: How far back to look in hours (default 24).
        """
        # ── Validate env vars ──
        github_token = os.getenv("GITHUB_TOKEN")
        github_org = os.getenv("GITHUB_ORG")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")

        missing = []
        if not github_token:
            missing.append("`GITHUB_TOKEN`")
        if not github_org:
            missing.append("`GITHUB_ORG`")
        if not anthropic_key:
            missing.append("`ANTHROPIC_API_KEY`")

        if missing:
            embed = discord.Embed(
                title="Configuration Error",
                description=f"Missing environment variables: {', '.join(missing)}\nSet them in `.env` to use this command.",
                color=0xE02B2B,
            )
            await context.send(embed=embed, ephemeral=True)
            return

        await context.defer()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            all_commits = []
            async with aiohttp.ClientSession(headers=headers) as session:
                params = {"since": cutoff_iso, "per_page": 100}
                if branch:
                    params["sha"] = branch

                async with session.get(
                    f"https://api.github.com/repos/{github_org}/{REPO_NAME}/commits",
                    params=params,
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise Exception(f"GitHub API returned {resp.status}: {text[:200]}")
                    all_commits = await resp.json()

        except Exception as e:
            embed = discord.Embed(
                title="GitHub API Error",
                description=f"Failed to fetch commits: {e}",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
            return

        # ── No commits found ──
        branch_label = f"on `{branch}`" if branch else "across all branches"
        title = f"Commit Summary — {REPO_NAME} — Last {hours}h"

        if not all_commits:
            embed = discord.Embed(
                title=title,
                description=f"No commits found {branch_label} in this time window.",
                color=0xD97706,
            )
            embed.set_footer(text="Powered by Claude")
            await context.send(embed=embed)
            return

        # ── Format commits for Claude ──
        lines = []
        for c in all_commits:
            author = c.get("commit", {}).get("author", {}).get("name", "Unknown")
            message = c.get("commit", {}).get("message", "").split("\n")[0]
            sha = c.get("sha", "")[:7]
            date = c.get("commit", {}).get("author", {}).get("date", "")
            lines.append(f"{sha} {author}: {message} ({date})")

        commit_block = "\n".join(lines[:300])

        # ── Call Claude ──
        try:
            client = anthropic.AsyncAnthropic(api_key=anthropic_key)
            response = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Summarize these git commits from the '{REPO_NAME}' repo "
                            f"{'on branch ' + branch if branch else '(all branches)'} "
                            f"for a team standup. Group by contributor, highlight key changes, "
                            f"keep it concise.\n\n{commit_block}"
                        ),
                    }
                ],
            )
            summary = response.content[0].text
        except Exception as e:
            embed = discord.Embed(
                title="Claude API Error",
                description=f"Failed to generate summary: {e}",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
            return

        # ── Send embed to the channel where command was called ──
        embed = discord.Embed(
            title=title,
            description=summary[:4096],
            color=0xD97706,
        )
        if branch:
            embed.add_field(name="Branch", value=f"`{branch}`", inline=True)
        embed.add_field(name="Window", value=f"{hours}h", inline=True)
        embed.add_field(name="Commits", value=str(len(all_commits)), inline=True)
        embed.set_footer(text=f"{REPO_NAME} • Powered by Claude")
        embed.timestamp = datetime.now(timezone.utc)
        await context.channel.send(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(CommitSummary(bot))
