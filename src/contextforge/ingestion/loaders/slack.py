"""
ContextForge Slack Loader

Loads messages from Slack channels using the Slack API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from contextforge.config import settings
from contextforge.ingestion.loaders.base import (
    BaseLoader,
    DocumentContent,
    LoaderConfig,
    LoaderRegistry,
)


class SlackLoaderConfig(LoaderConfig):
    """Configuration for Slack loader."""

    max_messages: int = 10000
    include_threads: bool = True
    include_reactions: bool = False
    oldest_first: bool = False


@LoaderRegistry.register
class SlackLoader(BaseLoader):
    """Loader for Slack channel messages."""

    source_type = "slack"

    def __init__(self, config: SlackLoaderConfig | None = None):
        super().__init__(config or SlackLoaderConfig())
        self.bot_token = settings.SLACK_BOT_TOKEN
        self.app_token = settings.SLACK_APP_TOKEN
        self._client: AsyncWebClient | None = None

    @property
    def client(self) -> AsyncWebClient:
        """Get or create Slack client."""
        if self._client is None:
            self._client = AsyncWebClient(token=self.bot_token)
        return self._client

    def _format_message(self, message: dict[str, Any], users: dict[str, str]) -> str:
        """Format a Slack message for content."""
        user_id = message.get("user", "")
        username = users.get(user_id, user_id)
        text = message.get("text", "")
        ts = message.get("ts", "")

        # Convert timestamp to readable format
        try:
            dt = datetime.fromtimestamp(float(ts))
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            timestamp = ts

        # Handle message subtypes
        subtype = message.get("subtype", "")
        if subtype == "bot_message":
            username = message.get("username", "Bot")
        elif subtype == "message_changed":
            text = message.get("message", {}).get("text", text)

        # Format
        parts = [f"[{timestamp}] {username}:"]
        if text:
            parts.append(text)

        # Handle attachments
        for attachment in message.get("attachments", []):
            if attachment.get("text"):
                parts.append(attachment["text"])
            if attachment.get("fallback"):
                parts.append(attachment["fallback"])

        # Handle blocks
        for block in message.get("blocks", []):
            if block.get("type") == "section":
                for element in block.get("elements", []):
                    if element.get("type") == "mrkdwn":
                        parts.append(element.get("text", ""))

        return "\n".join(parts)

    async def _get_users(self) -> dict[str, str]:
        """Get user ID to name mapping."""
        users = {}
        cursor = None

        while True:
            response = await self.client.users_list(cursor=cursor, limit=200)
            for user in response.get("members", []):
                users[user["id"]] = user.get("real_name") or user.get("name") or user["id"]

            if not response.get("response_metadata", {}).get("next_cursor"):
                break
            cursor = response["response_metadata"]["next_cursor"]

        return users

    async def _get_channel_info(self, channel_id: str) -> dict[str, Any]:
        """Get channel information."""
        response = await self.client.conversations_info(channel=channel_id)
        return response.get("channel", {})

    async def load_channel(
        self,
        channel_id: str,
        *,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[DocumentContent]:
        """Load messages from a Slack channel."""
        users = await self._get_users()
        channel_info = await self._get_channel_info(channel_id)
        channel_name = channel_info.get("name", channel_id)

        count = 0
        max_count = limit or self.config.max_messages
        cursor = None

        while count < max_count:
            params = {
                "channel": channel_id,
                "limit": min(200, max_count - count),
            }
            if oldest:
                params["oldest"] = oldest
            if latest:
                params["latest"] = latest
            if cursor:
                params["cursor"] = cursor

            response = await self.client.conversations_history(**params)
            messages = response.get("messages", [])

            if not messages:
                break

            # Sort messages
            if self.config.oldest_first:
                messages = list(reversed(messages))

            for message in messages:
                if count >= max_count:
                    break

                try:
                    content = self._format_message(message, users)

                    metadata = {
                        "slack_channel_id": channel_id,
                        "slack_channel_name": channel_name,
                        "slack_message_ts": message.get("ts"),
                        "slack_user_id": message.get("user"),
                        "slack_username": users.get(message.get("user", ""), ""),
                        "slack_thread_ts": message.get("thread_ts"),
                        "slack_subtype": message.get("subtype"),
                        "slack_permalink": f"https://slack.com/archives/{channel_id}/p{message.get('ts', '').replace('.', '')}",
                    }

                    # Include thread replies if enabled
                    if self.config.include_threads and message.get("thread_ts") == message.get("ts"):
                        replies = await self._get_thread_replies(channel_id, message["ts"], users)
                        if replies:
                            content += "\n\n--- THREAD REPLIES ---\n" + "\n".join(replies)

                    yield DocumentContent(
                        content=content,
                        metadata=self._create_metadata(**metadata),
                        source_id=f"{channel_id}/{message.get('ts', '')}",
                        title=f"#{channel_name} - {message.get('ts', '')}",
                    )
                    count += 1
                except Exception as e:
                    yield DocumentContent(
                        content="",
                        metadata=self._create_metadata(
                            error=str(e),
                            slack_channel_id=channel_id,
                            slack_message_ts=message.get("ts"),
                        ),
                        source_id=f"{channel_id}/{message.get('ts', '')}",
                        title="Error",
                    )

            if not response.get("has_more"):
                break
            cursor = response.get("response_metadata", {}).get("next_cursor")

    async def _get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
        users: dict[str, str],
    ) -> list[str]:
        """Get thread replies."""
        replies = []
        cursor = None

        while True:
            response = await self.client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                cursor=cursor,
                limit=200,
            )

            for message in response.get("messages", [])[1:]:  # Skip parent message
                content = self._format_message(message, users)
                if content:
                    replies.append(content)

            if not response.get("has_more"):
                break
            cursor = response.get("response_metadata", {}).get("next_cursor")

        return replies

    async def load(self, source_id: str, **kwargs: Any) -> DocumentContent:
        """Load a single channel (returns first batch)."""
        # source_id is channel_id
        async for doc in self.load_channel(source_id, limit=1, **kwargs):
            return doc
        raise ValueError(f"No messages found in channel: {source_id}")

    async def load_many(self, source_ids: list[str], **kwargs: Any) -> AsyncIterator[DocumentContent]:
        """Load multiple channels."""
        for source_id in source_ids:
            async for doc in self.load_channel(source_id, **kwargs):
                yield doc

    async def validate_source(self, source_id: str) -> bool:
        """Validate Slack channel exists."""
        try:
            await self._get_channel_info(source_id)
            return True
        except Exception:
            return False

    async def load_user_conversations(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[DocumentContent]:
        """Load DM conversations with a user."""
        # Open DM channel
        response = await self.client.conversations_open(users=user_id)
        channel_id = response.get("channel", {}).get("id")

        if channel_id:
            async for doc in self.load_channel(channel_id, **kwargs):
                yield doc
