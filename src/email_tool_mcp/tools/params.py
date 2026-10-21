"""Tool parameter types; the SDK turns each `Annotated` description into the JSON schema.

Standard: `Annotated[..., pydantic.Field(...)]`, the parameter style the MCP Python SDK documents.
Placement: tools/params.py, shared by every tool module in tools/.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

MailboxName = Annotated[
    str,
    Field(description="Mailbox to use, as listed by list_mailboxes. Leave empty when only one is configured."),
]
Folder = Annotated[str, Field(description="Folder name as shown by list_folders, for example INBOX.")]
DraftsFolder = Annotated[str, Field(description="Drafts folder, for example '[Gmail]/Drafts' or 'INBOX.Drafts'.")]
Limit = Annotated[int, Field(description="How many messages to return, newest first.", ge=1, le=200)]
Uid = Annotated[int, Field(description="UID of the message, as shown in listings.")]
To = Annotated[str, Field(description="Comma-separated recipient addresses.")]
Cc = Annotated[str, Field(description="Comma-separated Cc addresses.")]
Subject = Annotated[str, Field(description="Subject line.")]
Body = Annotated[str, Field(description="Plain text body; the fallback when `html` is also given.")]
Html = Annotated[str, Field(description="Optional HTML body for links and formatting, sent alongside `body`.")]
