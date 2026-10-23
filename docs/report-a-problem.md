# Report a problem

If email-tool does not work as it should, your assistant can tell us for you. You read
the report first, and nothing is sent until you agree.

## 1. Ask your assistant

Say what went wrong, in your own words, for example:

> Report a problem with email-tool: sending from my work mailbox fails since this morning.

## 2. Read the report

Your assistant shows you the report. It holds:

- what you said went wrong
- the versions of email-tool, your computer's system and Python
- the name of the app you use (for example Claude Desktop)
- how many mailboxes you have of each kind: Gmail, Outlook or other
- the last few errors email-tool recorded

Before you see it, email-tool removes email addresses, subjects, anything in quotes,
file paths in your home folder, IP addresses, server names other than Gmail's and
Microsoft's, and anything that looks like a password, token or key. Nothing is sent yet.

If you see anything you do not want to share, tell your assistant to stop, or to
describe the problem differently.

## 3. Choose how to send it

=== "By email"

    Say "email it". The report is sent from one of your own mailboxes to the email-tool
    maintainer (s.khan at alchlight.com), with a subject that starts with
    "email-tool problem report:".

    Your app first shows you the exact message: who it goes to, the subject and the whole
    text. Select **Accept** to send it or **Decline** to stop. If your app cannot show that
    question, nothing is sent: use GitHub instead.

=== "On GitHub"

    Say "give me the GitHub link". Open the link in your browser. It opens a new issue on
    GitHub with the report filled in. You need a free GitHub account.

    Read it once more, then submit it. The issue is public, so anyone can read it.

## What happens next

The maintainer reads the report and replies by email, or on the GitHub issue.

For a security problem, do not use either way: report it privately, as the
[security policy](https://github.com/skhan61/email-tool/blob/main/SECURITY.md) describes.
