from types import ModuleType

NUMBERED_ITEMS = ["1", "1A", *[str(number) for number in range(2, 16)]]


def build_blocks(parser_module: ModuleType, body: str):
    """Build normalized soup and leaf blocks from an HTML body."""
    soup = parser_module.normalize(f"<html><body>{body}</body></html>")
    return soup, parser_module.leaf_blocks(soup)


def build_numbered_body(gap: int = 0) -> str:
    """Build styled numbered Item headings with optional body gaps."""
    parts = []
    for index, item in enumerate(NUMBERED_ITEMS):
        weight = 700 if index == len(NUMBERED_ITEMS) - 1 else 800
        size = 10 if index == len(NUMBERED_ITEMS) - 1 else 12
        parts.append(
            f'<p style="font-weight: {weight}; font-size: {size}pt">Item {item}. Section {item}</p>'
        )
        parts.extend("<p>Body text</p>" for _ in range(gap))
    return "".join(parts)
