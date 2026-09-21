"""Text presentation helpers. Escapes untrusted text, then links bare URLs."""
import re

from markupsafe import Markup, escape

# Match http/https URLs up to the next whitespace or angle bracket.
_URL_RE = re.compile(r'https?://[^\s<]+')
# Punctuation that commonly follows a URL in prose but is not part of it.
_TRAILING = '.,;:!?)]}\'"、。，；：！？）】」』'


def linkify(text):
    """Return HTML with bare URLs turned into safe anchor tags.

    Everything is HTML-escaped first, so this is safe for untrusted note text.
    """
    if not text:
        return Markup('')
    parts = []
    last = 0
    for match in _URL_RE.finditer(text):
        parts.append(escape(text[last:match.start()]))
        url = match.group(0)
        trailing = ''
        while url and url[-1] in _TRAILING:
            trailing = url[-1] + trailing
            url = url[:-1]
        parts.append(
            Markup('<a href="{0}" target="_blank" rel="noopener noreferrer">{0}</a>').format(url)
        )
        parts.append(escape(trailing))
        last = match.end()
    parts.append(escape(text[last:]))
    return Markup('').join(parts)
