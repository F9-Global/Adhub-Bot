"""
Temporary test cog to preview digest designs and inject mock data.
Delete this file once you're done testing.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context


# Mock events based on real AdHub activity
MOCK_EVENTS = [
    {
        "type": "push",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=5),
        "repo": "AdhubOrg/adhub",
        "sender": "ferret9",
        "branch": "staging",
        "pusher": "ferret9",
        "commit_count": 1,
        "commits": [
            {
                "sha": "085e45a",
                "message": "fix(deploy): add uuid to production dependencies",
                "url": "https://github.com/AdhubOrg/adhub/commit/085e45a",
            }
        ],
        "compare_url": "https://github.com/AdhubOrg/adhub/compare/staging",
    },
    {
        "type": "push",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=4),
        "repo": "AdhubOrg/adhub",
        "sender": "ferret9",
        "branch": "staging",
        "pusher": "ferret9",
        "commit_count": 1,
        "commits": [
            {
                "sha": "4f8ae12",
                "message": "fix(deploy): always export Express router from index",
                "url": "https://github.com/AdhubOrg/adhub/commit/4f8ae12",
            }
        ],
        "compare_url": "https://github.com/AdhubOrg/adhub/compare/staging",
    },
    {
        "type": "push",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
        "repo": "AdhubOrg/adhub",
        "sender": "luceinrock",
        "branch": "dev",
        "pusher": "luceinrock",
        "commit_count": 3,
        "commits": [
            {
                "sha": "2d758f1",
                "message": "fix(identity): add address_hash to unique constraint",
                "url": "https://github.com/AdhubOrg/adhub/commit/2d758f1",
            },
            {
                "sha": "a1b2c3d",
                "message": "feat(auth): implement JWT refresh token rotation",
                "url": "https://github.com/AdhubOrg/adhub/commit/a1b2c3d",
            },
            {
                "sha": "e4f5g6h",
                "message": "test(auth): add refresh token edge cases",
                "url": "https://github.com/AdhubOrg/adhub/commit/e4f5g6h",
            },
        ],
        "compare_url": "https://github.com/AdhubOrg/adhub/compare/dev",
    },
    {
        "type": "push",
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=30),
        "repo": "AdhubOrg/adhub",
        "sender": "global-angelo",
        "branch": "dev",
        "pusher": "global-angelo",
        "commit_count": 2,
        "commits": [
            {
                "sha": "4c88d54",
                "message": "feat(server): register sprint 10-11 api routes",
                "url": "https://github.com/AdhubOrg/adhub/commit/4c88d54",
            },
            {
                "sha": "fb11adc",
                "message": "chore(env): update dev environment variables",
                "url": "https://github.com/AdhubOrg/adhub/commit/fb11adc",
            },
        ],
        "compare_url": "https://github.com/AdhubOrg/adhub/compare/dev",
    },
    {
        "type": "pull_request",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=2),
        "repo": "AdhubOrg/adhub",
        "sender": "ferret9",
        "action": "opened",
        "pr_number": 42,
        "pr_title": "fix(deploy): production dependency cleanup",
        "pr_url": "https://github.com/AdhubOrg/adhub/pull/42",
        "head": "staging",
        "base": "main",
        "merged": False,
        "additions": 15,
        "deletions": 3,
        "changed_files": 2,
    },
    {
        "type": "create",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=6),
        "repo": "AdhubOrg/adhub",
        "sender": "luceinrock",
        "ref_type": "branch",
        "ref": "fix/identity-constraint",
    },
    {
        "type": "issues",
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=3),
        "repo": "AdhubOrg/adhub",
        "sender": "ferret9",
        "action": "opened",
        "issue_number": 18,
        "issue_title": "UUID missing from production build",
        "issue_url": "https://github.com/AdhubOrg/adhub/issues/18",
    },
]


def _group_events(events):
    """Shared event grouping logic for all designs."""
    dev_pushes = defaultdict(lambda: {"commit_count": 0, "commits": []})
    other_pushes = defaultdict(lambda: {"branches": set(), "commit_count": 0})
    prs = []
    branches_created = []
    branches_deleted = []
    issues_list = []

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

    return dev_pushes, other_pushes, prs, branches_created, branches_deleted, issues_list


def build_design_1(events, now):
    """Design 1: Clean & Compact — single embed, block layout."""
    dev_pushes, other_pushes, prs, branches_created, branches_deleted, issues_list = _group_events(events)

    session = "Midday" if now.hour == 12 else "End of Day"
    color = 0xE8A317 if now.hour == 12 else 0xCF222E

    desc = "```git fetch origin && git rebase origin/dev```\n"

    # Dev commits
    if dev_pushes:
        total = sum(d["commit_count"] for d in dev_pushes.values())
        desc += f"**Commits to `dev`** ({total})\n"
        for user, data in dev_pushes.items():
            desc += f"> **{user}** pushed {data['commit_count']}\n"
            for c in data["commits"][:3]:
                desc += f"> `{c['sha']}` {c['message']}\n"
            if len(data["commits"]) > 3:
                desc += f"> *... +{len(data['commits']) - 3} more*\n"
        desc += "\n"

    # PRs
    if prs:
        desc += f"**Pull Requests** ({len(prs)})\n"
        for pr in prs:
            action = pr.get("action", "")
            if action == "closed" and pr.get("merged"):
                action = "merged"
            desc += f"> #{pr['pr_number']} {pr['pr_title']} (*{action}*)\n"
        desc += "\n"

    # Branches + Issues on one line each
    if branches_created or branches_deleted:
        items = [f"+ `{b.get('ref', '?')}`" for b in branches_created]
        items += [f"- `{b.get('ref', '?')}`" for b in branches_deleted]
        desc += f"**Branches** {' '.join(items)}\n"

    if issues_list:
        for iss in issues_list:
            desc += f"**Issue** #{iss['issue_number']} {iss['issue_title']} (*{iss.get('action', '')}*)\n"

    # Other branches — small text
    if other_pushes:
        total = sum(d["commit_count"] for d in other_pushes.values())
        parts = []
        for user, data in other_pushes.items():
            branches_str = ", ".join(sorted(data["branches"]))
            parts.append(f"{user}: {data['commit_count']} on {branches_str}")
        desc += f"\n-# Other branches ({total} commits): {' | '.join(parts)}"

    if not events:
        desc += "*No activity since last digest.*"

    embed = discord.Embed(
        title=f"Rebase — {session} ({now.strftime('%I:%M %p')} UTC+8)",
        description=desc[:4096],
        color=color,
    )
    embed.set_footer(text="/rebase-now \u2022 /rebase-schedule \u2022 /activity-preview")
    embed.timestamp = now
    return [embed]


def build_design_2(events, now):
    """Design 2: Field Cards — uses embed fields for clean grouping."""
    dev_pushes, other_pushes, prs, branches_created, branches_deleted, issues_list = _group_events(events)

    session = "Midday" if now.hour == 12 else "End of Day"
    color = 0xE8A317 if now.hour == 12 else 0xCF222E

    embed = discord.Embed(
        title=f"Rebase — {session}",
        description=(
            f"**{now.strftime('%I:%M %p')} UTC+8** \u2022 "
            f"Sync your branch with `dev`\n"
            f"```git fetch origin && git rebase origin/dev```"
        ),
        color=color,
    )

    # Dev commits field
    if dev_pushes:
        total = sum(d["commit_count"] for d in dev_pushes.values())
        val = ""
        for user, data in dev_pushes.items():
            val += f"**{user}** \u2014 {data['commit_count']}\n"
            for c in data["commits"][:3]:
                val += f"`{c['sha']}` {c['message']}\n"
            if len(data["commits"]) > 3:
                val += f"*+{len(data['commits']) - 3} more*\n"
        embed.add_field(
            name=f"\U0001f4e6 Commits to dev ({total})",
            value=val[:1024],
            inline=False,
        )

    # PRs field
    if prs:
        val = ""
        for pr in prs:
            action = pr.get("action", "")
            if action == "closed" and pr.get("merged"):
                action = "merged"
            val += f"#{pr['pr_number']} {pr['pr_title']} (*{action}*)\n"
        embed.add_field(
            name=f"\U0001f501 Pull Requests ({len(prs)})",
            value=val[:1024],
            inline=False,
        )

    # Branches + Issues as inline fields
    if branches_created or branches_deleted:
        val = ""
        for b in branches_created:
            val += f"\u2795 `{b.get('ref', '?')}`\n"
        for b in branches_deleted:
            val += f"\u2796 `{b.get('ref', '?')}`\n"
        embed.add_field(name="\U0001f33f Branches", value=val[:1024], inline=True)

    if issues_list:
        val = ""
        for iss in issues_list:
            val += f"#{iss['issue_number']} {iss['issue_title']}\n"
        embed.add_field(name="\U0001f41b Issues", value=val[:1024], inline=True)

    # Other branches — footer-style
    if other_pushes:
        total = sum(d["commit_count"] for d in other_pushes.values())
        parts = []
        for user, data in other_pushes.items():
            branches_str = ", ".join(sorted(data["branches"]))
            parts.append(f"{user}: {data['commit_count']} on {branches_str}")
        embed.add_field(
            name="Other branches",
            value=f"-# {' | '.join(parts)} ({total} commits)",
            inline=False,
        )

    if not events:
        embed.add_field(name="\u200b", value="*No activity since last digest.*", inline=False)

    embed.set_footer(text="/rebase-now \u2022 /rebase-schedule \u2022 /activity-preview")
    embed.timestamp = now
    return [embed]


def build_design_3(events, now):
    """Design 3: Bulletin Board — header embed + activity embed, visual separators."""
    dev_pushes, other_pushes, prs, branches_created, branches_deleted, issues_list = _group_events(events)

    session = "Midday" if now.hour == 12 else "End of Day"
    color = 0xE8A317 if now.hour == 12 else 0xCF222E
    accent = 0x2EA44F

    # Header embed
    dev_total = sum(d["commit_count"] for d in dev_pushes.values())
    other_total = sum(d["commit_count"] for d in other_pushes.values())
    stats = []
    if dev_total:
        stats.append(f"\U0001f4e6 {dev_total} commits")
    if prs:
        stats.append(f"\U0001f501 {len(prs)} PRs")
    if branches_created or branches_deleted:
        stats.append(f"\U0001f33f {len(branches_created) + len(branches_deleted)} branches")
    if issues_list:
        stats.append(f"\U0001f41b {len(issues_list)} issues")

    stats_line = " \u2022 ".join(stats) if stats else "No activity"
    header = discord.Embed(
        title=f"\U0001f514 Rebase — {session}",
        description=(
            f"**{now.strftime('%I:%M %p')} UTC+8**\n\n"
            f"{stats_line}\n\n"
            f"```git fetch origin && git rebase origin/dev```"
        ),
        color=color,
    )
    header.timestamp = now

    if not events:
        header.set_footer(text="/rebase-now \u2022 /rebase-schedule \u2022 /activity-preview")
        return [header]

    # Activity embed
    desc = ""

    if dev_pushes:
        desc += "\U0001f7e2 **dev**\n"
        for user, data in dev_pushes.items():
            desc += f"\u2514 **{user}** ({data['commit_count']} commits)\n"
            for c in data["commits"][:3]:
                desc += f"  \u2502 `{c['sha']}` {c['message']}\n"
            if len(data["commits"]) > 3:
                desc += f"  \u2502 *+{len(data['commits']) - 3} more*\n"
        desc += "\n"

    if prs:
        desc += "\U0001f7e3 **Pull Requests**\n"
        for pr in prs:
            action = pr.get("action", "")
            if action == "closed" and pr.get("merged"):
                action = "merged"
            desc += f"\u2514 #{pr['pr_number']} {pr['pr_title']} \u2014 *{action}*\n"
        desc += "\n"

    if branches_created or branches_deleted:
        desc += "\U0001f535 **Branches**\n"
        for b in branches_created:
            desc += f"\u2514 \u2795 `{b.get('ref', '?')}` by {b['sender']}\n"
        for b in branches_deleted:
            desc += f"\u2514 \u2796 `{b.get('ref', '?')}` by {b['sender']}\n"
        desc += "\n"

    if issues_list:
        desc += "\U0001f7e0 **Issues**\n"
        for iss in issues_list:
            desc += f"\u2514 #{iss['issue_number']} {iss['issue_title']} \u2014 *{iss.get('action', '')}*\n"
        desc += "\n"

    if other_pushes:
        total = sum(d["commit_count"] for d in other_pushes.values())
        parts = []
        for user, data in other_pushes.items():
            branches_str = ", ".join(sorted(data["branches"]))
            parts.append(f"{user}: {data['commit_count']} on {branches_str}")
        desc += f"-# Other branches: {' | '.join(parts)} ({total} commits)"

    activity = discord.Embed(
        description=desc[:4096],
        color=accent,
    )
    activity.set_footer(text="/rebase-now \u2022 /rebase-schedule \u2022 /activity-preview")
    return [header, activity]


DESIGNS = {
    1: build_design_1,
    2: build_design_2,
    3: build_design_3,
}


class TestDigest(commands.Cog, name="test_digest"):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="test-digest",
        description="Inject mock GitHub events and trigger a rebase digest for testing.",
    )
    @commands.has_permissions(manage_messages=True)
    async def test_digest(self, context: Context) -> None:
        """Inject mock events into the buffer, then trigger a digest."""
        github_cog = self.bot.get_cog("github_feed")
        if not github_cog:
            await context.send("GitHub feed cog is not loaded.", ephemeral=True)
            return

        github_cog.event_buffer.extend(MOCK_EVENTS)

        await context.send(
            f"Injected **{len(MOCK_EVENTS)}** mock events. Triggering digest now...",
            ephemeral=True,
        )

        reminders_cog = self.bot.get_cog("reminders")
        if reminders_cog:
            from datetime import datetime
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Manila"))
            await reminders_cog._send_rebase_digest(now, suppress_ping=True)
        else:
            await context.send("Reminders cog is not loaded.", ephemeral=True)

    @commands.hybrid_command(
        name="test-design",
        description="Preview a digest design (1, 2, or 3) with mock data.",
    )
    @app_commands.describe(design="Design number: 1 = Clean, 2 = Field Cards, 3 = Bulletin Board")
    @app_commands.choices(design=[
        app_commands.Choice(name="1 \u2014 Clean & Compact", value=1),
        app_commands.Choice(name="2 \u2014 Field Cards", value=2),
        app_commands.Choice(name="3 \u2014 Bulletin Board", value=3),
    ])
    async def test_design(self, context: Context, design: int) -> None:
        """Preview a specific digest design."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Manila"))
        builder = DESIGNS.get(design)
        if not builder:
            await context.send("Pick 1, 2, or 3.", ephemeral=True)
            return

        embeds = builder(MOCK_EVENTS, now)
        await context.send(
            content=f"**Design {design} preview:**",
            embeds=embeds,
        )


async def setup(bot) -> None:
    await bot.add_cog(TestDigest(bot))
