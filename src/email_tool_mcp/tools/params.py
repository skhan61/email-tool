"""Tool parameter types; the SDK turns each `Annotated` description into the JSON schema.

Standard: `Annotated[..., pydantic.Field(...)]`, the parameter style the MCP Python SDK documents.
Placement: tools/params.py, shared by every tool module in tools/.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from pydantic import Field

from email_tool_mcp.problem_report import DESCRIPTION_LIMIT, REPORT_LIMIT

MailboxName: TypeAlias = Annotated[
    str,
    Field(description="Mailbox to use, as listed by list_mailboxes. Leave empty when only one is configured."),
]
Folder: TypeAlias = Annotated[str, Field(description="Folder name as shown by list_folders, for example INBOX.")]
DraftsFolder: TypeAlias = Annotated[
    str, Field(description="Drafts folder, for example '[Gmail]/Drafts' or 'INBOX.Drafts'.")
]
Limit: TypeAlias = Annotated[int, Field(description="How many messages to return, newest first.", ge=1, le=200)]
Uid: TypeAlias = Annotated[int, Field(description="UID of the message, as shown in listings.")]
To: TypeAlias = Annotated[str, Field(description="Comma-separated recipient addresses.")]
Cc: TypeAlias = Annotated[str, Field(description="Comma-separated Cc addresses.")]
Subject: TypeAlias = Annotated[str, Field(description="Subject line.")]
Body: TypeAlias = Annotated[str, Field(description="Plain text body; the fallback when `html` is also given.")]
InReplyToUid: TypeAlias = Annotated[
    int,
    Field(
        description="UID of the message this one answers, so it joins that conversation. 0 when it is not a reply.",
        ge=0,
    ),
]
InReplyToFolder: TypeAlias = Annotated[str, Field(description="Folder holding the message named by in_reply_to_uid.")]
Html: TypeAlias = Annotated[
    str, Field(description="Optional HTML body for links and formatting, sent alongside `body`.")
]
Attachments: TypeAlias = Annotated[
    list[str] | None,
    Field(description="Paths of files to attach, from any folder the user named. Up to 25 MB in total."),
]
ConfirmSensitive: TypeAlias = Annotated[
    str,
    Field(
        description=(
            "The code from an earlier refusal that named sensitive attachments or a risky place to save. "
            "Pass it only after the user, in this conversation, agreed to go ahead. Leave empty otherwise."
        )
    ),
]
Index: TypeAlias = Annotated[
    int, Field(description="Number of the attachment, as listed by get_email (1 for the first).", ge=1)
]
Directory: TypeAlias = Annotated[
    str, Field(description="Folder to save into, as the user named it; created if missing.")
]
ProblemDescription: TypeAlias = Annotated[
    str,
    Field(
        description=(
            "What went wrong, in the user's own words, in one to three sentences. Never include message text, "
            "subjects, addresses or passwords."
        ),
        max_length=DESCRIPTION_LIMIT,
    ),
]
Report: TypeAlias = Annotated[
    str,
    Field(
        description="The report exactly as report_problem returned it and the user read it.", max_length=REPORT_LIMIT
    ),
]
