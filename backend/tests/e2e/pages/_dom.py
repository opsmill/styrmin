"""DOM-reading helpers shared by the Playwright page objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout

if TYPE_CHECKING:
    from playwright.async_api import Locator

# Runs in the browser: what an open dialog shows, plus which inputs block its
# submit. Native ``required`` validation and some field errors render no text.
_DESCRIBE_DIALOG_JS = """dialog => {
    const id = el => '#' + (el.id || el.name || el.tagName.toLowerCase());
    const inputs = [...dialog.querySelectorAll('input, textarea, select')]
        .filter(el => !['hidden', 'checkbox', 'radio'].includes(el.type));
    return {
        text: dialog.innerText.split('\\n').map(l => l.trim()).filter(Boolean),
        invalid: inputs.filter(el => !el.validity.valid)
            .map(el => `${id(el)} (${el.validationMessage})`),
        empty: inputs.filter(el => el.value === '').map(id),
    };
}"""


async def required_attr(locator: Locator, attr: str, *, context: str) -> str:
    """Read ``attr`` from ``locator`` and raise if absent or empty.

    Prevents a frontend test-hook removal from surfacing as a cryptic
    downstream assertion; the missing attribute is reported at the boundary.
    """
    value = await locator.get_attribute(attr)
    if not value:
        raise ScenarioActionError(
            f"{context} rendered without {attr} attribute "
            "(frontend test-hook may have been removed or renamed)"
        )
    return value


async def wait_for_dialog_open(dialog: Locator) -> None:
    """Wait for ``dialog`` to open and take keyboard focus.

    Base UI focuses a dialog's first focusable element one animation frame
    after it opens. ``fill()`` focuses its target and then types in a second
    step, so a fill that spans that frame types into the wrong field (#365).
    Call this before the first ``fill()`` in a dialog.
    """
    await dialog.wait_for()
    await expect(dialog.and_(dialog.page.locator(":focus-within"))).to_have_count(1)


async def submit_dialog(
    dialog: Locator, *, button: str, timeout: float = 30_000
) -> None:
    """Click ``button`` in ``dialog`` and wait for the dialog to close.

    The dialogs close only when their mutation succeeds. When one stays open,
    the raised error lists what it shows and which inputs block the submit.
    """
    await dialog.get_by_role("button", name=button, exact=True).click()
    try:
        await dialog.wait_for(state="hidden", timeout=timeout)
    except PlaywrightTimeoutError as exc:
        state = await dialog.evaluate(_DESCRIBE_DIALOG_JS, timeout=5_000)
        raise ScenarioTimeout(
            f"dialog still open {timeout / 1000:.0f}s after clicking {button!r}. "
            f"It shows: {' | '.join(state['text'])}. "
            f"Invalid inputs: {', '.join(state['invalid']) or 'none'}. "
            f"Empty inputs: {', '.join(state['empty']) or 'none'}."
        ) from exc
