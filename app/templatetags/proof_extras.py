from django import template

register = template.Library()


@register.filter
def middle_truncate(value, max_len=28):
    """Shorten a long string from the middle, keeping the tail (e.g. the file
    extension) visible: 'immatrikulations…_ws2025.pdf'. CSS text-overflow can
    only clip the end, which would hide the extension."""
    value = str(value)
    if len(value) <= max_len:
        return value
    keep = max_len - 1  # room for the ellipsis
    head = (keep + 1) // 2
    tail = keep - head
    return f"{value[:head]}…{value[-tail:]}"
