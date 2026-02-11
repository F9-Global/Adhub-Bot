"""
Conversational AI cog for AdHub Bot.
Responds to @mentions and replies in any channel using Claude,
with automatic GitHub activity context for dev-related questions.
"""

import collections
import os
from datetime import datetime, timezone, timedelta

import aiohttp
import anthropic
import discord
from discord.ext import commands
from discord.ext.commands import Context

REPO_NAME = "adhub"

SYSTEM_PROMPT = """You are AdHub Bot, the official Discord assistant for the AdHub development team.

PERSONALITY:
- Default mode: Funny, lively, witty. Use casual language, mild humor, dev jokes. You're the team's favorite bot. Think of yourself as the chaotic intern who somehow knows everything.
- Serious mode: When someone asks about deadlines, blockers, production issues, bugs, or anything clearly serious — switch to direct, helpful, professional tone. No jokes about real problems.
- You know you're in a dev team channel. Everyone here is a software developer working on the AdHub project.
- Keep replies concise. 1-3 short paragraphs max unless someone asks for detail.
- Use Discord markdown (bold, code blocks, bullet points).
- Never use @everyone or @here.
- You can reference Discord usernames when responding.

TEAM WORKFLOW:
- The team has scheduled rebase reminders at **12:00 AM (midnight)** and **6:00 PM**, both in UTC+8 (Philippine time).
- Before each rebase, warnings go out at T-30 minutes and T-10 minutes.
- At T-30: "Wrap up your work, push to dev within 20 minutes."
- At T-10: "Push to dev NOW."
- At T-0: A rebase digest is posted with all GitHub activity since the last digest.
- The rebase command is: `git fetch origin && git rebase origin/dev`
- Useful slash commands: /rebase-schedule, /rebase-now, /commit-summary, /activity-preview, /github-status

GITHUB CONTEXT:
- When you receive [GITHUB ACTIVITY] data, use it to answer questions about commits, pushes, PRs, branches, issues, and team activity.
- Summarize activity intelligently — group by person, highlight important changes, note patterns.
- If someone asks "who pushed today" or "what happened on dev" or similar, answer from the provided data naturally.
- If someone asks to summarize commits for a specific time window, use the commit data provided.
- When no GitHub data is available and someone asks, say you don't have recent data and suggest /commit-summary or /activity-preview.

GITHUB ISSUES & PRs:
- When you receive [GITHUB ISSUES] or [GITHUB PULL REQUESTS] data, use it to answer questions about open issues, PRs, review status, etc.
- Be helpful — if someone asks "what PRs are open" or "any issues assigned to me", answer from the data.

BOUNDARIES:
- Do not make up commit hashes, PR numbers, or team member names. Only reference what is in the provided data.
- If you don't know something, say so — but make it funny.
- You are NOT a general-purpose assistant. You are a dev team bot. Stay in character."""

GITHUB_KEYWORDS = [
    "commit", "push", "pushed", "merged", "merge", "pull request", "pr ",
    "branch", "deploy", "release", "repo", "github", "git ",
    "who pushed", "what happened", "activity", "changes", "diff",
    "what did", "who worked", "what's new", "whats new", "status",
    "commits", "pushes", "branches", "prs", "issues", "issue",
    "summarize", "summary", "recent", "today", "yesterday",
]


class Chat(commands.Cog, name="chat"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.client = None
        self.channel_histories: dict[int, collections.deque] = {}
        self.MAX_HISTORY = 10

    # ── History management ─────────────────────────────────────────

    def _get_history(self, channel_id: int) -> collections.deque:
        if channel_id not in self.channel_histories:
            self.channel_histories[channel_id] = collections.deque(maxlen=self.MAX_HISTORY)
        return self.channel_histories[channel_id]

    def _add_to_history(self, channel_id: int, role: str, content: str) -> None:
        history = self._get_history(channel_id)
        history.append({"role": role, "content": content})

    def _build_messages(self, channel_id: int) -> list[dict]:
        return list(self._get_history(channel_id))

    # ── GitHub context helpers ─────────────────────────────────────

    @staticmethod
    def _is_github_question(content: str) -> bool:
        lower = content.lower()
        return any(kw in lower for kw in GITHUB_KEYWORDS)

    async def _get_github_feed_context(self) -> str:
        """Get buffered GitHub events from the github_feed cog (non-destructive)."""
        github_cog = self.bot.get_cog("github_feed")
        if not github_cog:
            return ""

        events = github_cog.peek_buffer()
        if not events:
            return ""

        lines = []
        for e in events:
            if e["type"] == "push":
                commit_msgs = ", ".join(c["message"] for c in e.get("commits", [])[:5])
                lines.append(
                    f"[PUSH] {e.get('pusher', '?')} pushed {e.get('commit_count', 0)} "
                    f"commit(s) to {e.get('branch', '?')}: {commit_msgs}"
                )
            elif e["type"] == "pull_request":
                lines.append(
                    f"[PR] #{e.get('pr_number', 0)} {e.get('pr_title', '')} "
                    f"- {e.get('action', '?')} by {e.get('sender', '?')}"
                )
            elif e["type"] == "issues":
                lines.append(
                    f"[ISSUE] #{e.get('issue_number', 0)} {e.get('issue_title', '')} "
                    f"- {e.get('action', '?')} by {e.get('sender', '?')}"
                )
            elif e["type"] == "create":
                lines.append(f"[BRANCH CREATED] {e.get('ref', '?')} by {e.get('sender', '?')}")
            elif e["type"] == "delete":
                lines.append(f"[BRANCH DELETED] {e.get('ref', '?')} by {e.get('sender', '?')}")
            elif e["type"] == "release":
                lines.append(f"[RELEASE] {e.get('tag', '?')} - {e.get('action', '?')}")

        return "\n".join(lines)

    async def _fetch_recent_commits(self, hours: int = 24) -> str:
        """Fetch recent commits from GitHub API."""
        github_token = os.getenv("GITHUB_TOKEN")
        github_org = os.getenv("GITHUB_ORG")
        if not github_token or not github_org:
            return ""

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"https://api.github.com/repos/{github_org}/{REPO_NAME}/commits",
                    params={"since": cutoff_iso, "per_page": 30},
                ) as resp:
                    if resp.status != 200:
                        return ""
                    commits = await resp.json()
        except Exception:
            return ""

        if not commits:
            return ""

        lines = []
        for c in commits:
            author = c.get("commit", {}).get("author", {}).get("name", "Unknown")
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            sha = c.get("sha", "")[:7]
            date = c.get("commit", {}).get("author", {}).get("date", "")
            lines.append(f"{sha} {author}: {msg} ({date})")

        return "\n".join(lines[:30])

    async def _fetch_github_issues(self) -> str:
        """Fetch open issues from GitHub API."""
        github_token = os.getenv("GITHUB_TOKEN")
        github_org = os.getenv("GITHUB_ORG")
        if not github_token or not github_org:
            return ""

        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"https://api.github.com/repos/{github_org}/{REPO_NAME}/issues",
                    params={"state": "open", "per_page": 15},
                ) as resp:
                    if resp.status != 200:
                        return ""
                    issues = await resp.json()
        except Exception:
            return ""

        if not issues:
            return ""

        lines = []
        for i in issues:
            # GitHub API returns PRs as issues too — skip them
            if i.get("pull_request"):
                continue
            assignees = ", ".join(a["login"] for a in i.get("assignees", [])) or "unassigned"
            labels = ", ".join(l["name"] for l in i.get("labels", []))
            lines.append(
                f"#{i['number']} {i['title']} (assignees: {assignees})"
                + (f" [{labels}]" if labels else "")
            )

        return "\n".join(lines) if lines else ""

    async def _fetch_github_prs(self) -> str:
        """Fetch open pull requests from GitHub API."""
        github_token = os.getenv("GITHUB_TOKEN")
        github_org = os.getenv("GITHUB_ORG")
        if not github_token or not github_org:
            return ""

        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"https://api.github.com/repos/{github_org}/{REPO_NAME}/pulls",
                    params={"state": "open", "per_page": 15},
                ) as resp:
                    if resp.status != 200:
                        return ""
                    prs = await resp.json()
        except Exception:
            return ""

        if not prs:
            return ""

        lines = []
        for pr in prs:
            user = pr.get("user", {}).get("login", "?")
            lines.append(
                f"#{pr['number']} {pr['title']} by {user} "
                f"({pr.get('head', {}).get('ref', '?')} -> {pr.get('base', {}).get('ref', '?')})"
            )

        return "\n".join(lines)

    async def _build_github_context(self, content: str) -> str:
        """Combine GitHub data sources into a context block."""
        parts = []

        feed_data = await self._get_github_feed_context()
        if feed_data:
            parts.append(f"=== Recent GitHub Activity (from Discord feed) ===\n{feed_data}")

        commit_data = await self._fetch_recent_commits(hours=24)
        if commit_data:
            parts.append(f"=== Recent Commits (last 24h from GitHub API) ===\n{commit_data}")

        # Fetch issues/PRs if specifically asked
        lower = content.lower()
        if any(kw in lower for kw in ["issue", "issues", "bug", "bugs", "ticket"]):
            issues_data = await self._fetch_github_issues()
            if issues_data:
                parts.append(f"=== Open GitHub Issues ===\n{issues_data}")

        if any(kw in lower for kw in ["pr ", "prs", "pull request", "pull requests", "review"]):
            prs_data = await self._fetch_github_prs()
            if prs_data:
                parts.append(f"=== Open Pull Requests ===\n{prs_data}")

        if not parts:
            return "\n[No recent GitHub activity data available.]"

        return "\n\n".join(parts)

    # ── Claude API ─────────────────────────────────────────────────

    async def _get_claude_response(self, channel_id: int, github_context: str = "") -> str:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_key:
            return "I need an `ANTHROPIC_API_KEY` to chat. Ask an admin to set it up!"

        if self.client is None:
            self.client = anthropic.AsyncAnthropic(api_key=anthropic_key)

        # Inject current time so the bot has time awareness
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_utc8 = datetime.now(ZoneInfo("Asia/Manila"))
        now_utc = datetime.now(timezone.utc)

        # Calculate next rebase time
        rebase_hours = [0, 18]
        next_rebase = None
        for h in sorted(rebase_hours):
            candidate = now_utc8.replace(hour=h, minute=0, second=0, microsecond=0)
            if candidate > now_utc8:
                next_rebase = candidate
                break
        if next_rebase is None:
            # Next rebase is midnight tomorrow
            tomorrow = now_utc8 + timedelta(days=1)
            next_rebase = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

        time_until = next_rebase - now_utc8
        hours_until, remainder = divmod(int(time_until.total_seconds()), 3600)
        mins_until = remainder // 60

        time_block = (
            f"\n\n[CURRENT TIME]\n"
            f"UTC+8 (Philippine Time): {now_utc8.strftime('%A, %B %d, %Y %I:%M %p')}\n"
            f"UTC: {now_utc.strftime('%A, %B %d, %Y %I:%M %p')}\n"
            f"Next rebase: {next_rebase.strftime('%I:%M %p')} UTC+8 (in {hours_until}h {mins_until}m)"
        )

        system = SYSTEM_PROMPT + time_block
        if github_context:
            system += f"\n\n[GITHUB ACTIVITY]\n{github_context}"

        messages = self._build_messages(channel_id)
        if not messages:
            return "Nothing to respond to... awkward."

        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    # ── Message splitting for Discord 2000-char limit ──────────────

    @staticmethod
    def _split_message(text: str, limit: int = 2000) -> list[str]:
        chunks = []
        while len(text) > limit:
            split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks

    async def _send_response(self, message: discord.Message, response_text: str) -> None:
        if len(response_text) <= 2000:
            await message.reply(response_text, mention_author=False)
        else:
            chunks = self._split_message(response_text, 2000)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply(chunk, mention_author=False)
                else:
                    await message.channel.send(chunk)

        self._add_to_history(message.channel.id, "assistant", response_text)

    # ── Main listener ──────────────────────────────────────────────

    @commands.Cog.listener("on_message")
    async def on_chat_message(self, message: discord.Message) -> None:
        # Ignore bots
        if message.author == self.bot.user or message.author.bot:
            return

        # Only respond when @mentioned or replied to
        bot_mentioned = self.bot.user.mentioned_in(message) and not message.mention_everyone
        is_reply_to_bot = (
            message.reference is not None
            and message.reference.resolved is not None
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author == self.bot.user
        )
        if not bot_mentioned and not is_reply_to_bot:
            return

        # Don't steal prefix commands
        prefix = os.getenv("PREFIX", "!")
        clean = (
            message.content
            .replace(f"<@{self.bot.user.id}>", "")
            .replace(f"<@!{self.bot.user.id}>", "")
            .strip()
        )
        if clean.startswith(prefix):
            return

        # Store user message
        self._add_to_history(message.channel.id, "user", clean)

        # Fetch GitHub context if relevant
        github_context = ""
        if self._is_github_question(clean):
            github_context = await self._build_github_context(clean)

        # Call Claude with typing indicator
        async with message.channel.typing():
            try:
                response_text = await self._get_claude_response(
                    message.channel.id, github_context
                )
            except anthropic.APIError as e:
                response_text = f"Claude API hiccup: `{e.message}`"
                self.bot.logger.error(f"Chat cog Claude API error: {e}")
            except Exception as e:
                response_text = "Something broke in my brain. Try again in a sec."
                self.bot.logger.error(f"Chat cog error: {e}")

        await self._send_response(message, response_text)

    # ── Slash commands ─────────────────────────────────────────────

    @commands.hybrid_command(
        name="chat-clear",
        description="Clear the AI chat history for this channel.",
    )
    async def chat_clear(self, context: Context) -> None:
        channel_id = context.channel.id
        if channel_id in self.channel_histories:
            self.channel_histories[channel_id].clear()
        await context.send("Chat history cleared.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Chat(bot))
