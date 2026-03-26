from config import MAX_BODY_TEXT


async def build_page_snapshot(page) -> dict:
    title = await page.title()
    body_text = await page.locator("body").inner_text()
    body_text = body_text[:MAX_BODY_TEXT]
    return {
        "title": title,
        "body_text": body_text,
        "links": [],
        "images": [],
    }
