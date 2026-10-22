"""The browser side of a sign-in, shared by the Microsoft and Google sign-ins.

Standard: Python's `webbrowser` module decides whether a graphical browser can open. When
it cannot, or the browser is on another computer, the user pastes back the loopback address
the browser ends on: the native-app redirect to http://localhost (RFC 8252 7.3), whose query
carries the one-time code.
Placement: browser.py; microsoft.py and google.py call it.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable


def browser_available() -> bool:
    """True when Python can open a graphical browser from here.

    A plain `GenericBrowser` is a console one (lynx, w3m) run in the foreground of the
    terminal, where Microsoft's and Google's sign-ins do not work; graphical ones are its
    subclasses.
    """
    try:
        browser: webbrowser.BaseBrowser = webbrowser.get()
    except webbrowser.Error:
        return False
    return type(browser) is not webbrowser.GenericBrowser


def pasted_address(
    provider: str, sign_in_address: str, redirect: str, show: Callable[[str], None], paste: Callable[[str], str]
) -> str:
    """Show the sign-in address, then return the address the browser ended on, as the user pasted it."""
    show(
        f"{provider} sign-in address. Open it in a browser on any computer, sign in and allow access:\n"
        f"{sign_in_address}\n"
    )
    answer: str = paste(
        f'The browser then shows "site can\'t be reached". Paste its whole address (it starts with {redirect}): '
    ).strip()
    if not answer.startswith(redirect.rstrip("/")) or "code=" not in answer:
        raise ValueError(f"that is not the address the browser ended on (it starts with {redirect}); nothing saved")
    return answer
