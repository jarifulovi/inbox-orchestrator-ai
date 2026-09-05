import re
import urllib.parse
import html2text
from email_reply_parser import EmailReplyParser
from typing import Optional


class LLMContentCompressorService:
    """
    Dedicated, generic LLM email content preprocessor.
    Cleans and compresses email text specifically for LLM context windows (summaries, drafts, task orchestration)
    without mutating stored database records or ML models.
    """

    @classmethod
    def compress_email_body(cls, body: str, max_chars: int = 4000) -> str:
        """
        Main generic compression pipeline for all LLM context preparation.
        Strips MSO/HTML, reply history, signatures, tracking link parameters, and footers.
        """
        if not body:
            return ""

        # Step 1: Strip MSO Outlook conditional blocks and HTML tags to clean markdown/text
        text = cls.strip_html_and_mso(body)

        # Step 2: Use EmailReplyParser to strip quoted replies and email signatures
        text = cls.strip_replies_and_signatures(text)

        # Step 3: Sanitize tracking links and strip long URL query parameters
        text = cls.sanitize_urls(text)

        # Step 4: Remove generic corporate legal disclaimers & footers
        text = cls.strip_disclaimers_and_footers(text)

        # Step 5: Collapse whitespace and apply max_chars character truncation
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > max_chars:
            return text[:max_chars].rsplit(' ', 1)[0] + "..."

        return text

    @staticmethod
    def strip_html_and_mso(html_content: str) -> str:
        """Strips Microsoft MSO conditional tags and converts HTML to clean text."""
        if not html_content:
            return ""

        # Strip MSO conditional comment blocks
        cleaned = re.sub(r'<!--\[if mso.*?<!\[endif\]-->', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)

        # Check if text contains HTML elements
        if "<html" in cleaned.lower() or "<div" in cleaned.lower() or "<table" in cleaned.lower() or "<p" in cleaned.lower():
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.ignore_tables = True
            h.ignore_emphasis = True
            h.body_width = 0
            text = h.handle(cleaned)
        else:
            text = cleaned

        return text

    @staticmethod
    def strip_replies_and_signatures(text: str) -> str:
        """Strips email reply chains, quoted history (>), and signatures using EmailReplyParser."""
        if not text:
            return ""
        # Use EmailReplyParser to extract visible text
        reply_parsed = EmailReplyParser.parse_reply(text)
        if reply_parsed and len(reply_parsed.strip()) > 20:
            text = reply_parsed

        # Additional fallback line filtering for quoted lines
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('>') or (stripped.startswith('On ') and stripped.endswith('wrote:')):
                continue
            lower_line = stripped.lower()
            if lower_line in ["--", "-- ", "best,", "best regards,", "thanks,", "thank you,"] or lower_line.startswith("from: "):
                break
            lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def sanitize_urls(text: str) -> str:
        """
        Sanitizes tracking URLs, strips long query params, and replaces tracking/unsubscribe links.
        """
        if not text:
            return ""

        def _clean_match(match):
            url = match.group(0)
            url_lower = url.lower()

            # Check if unsubscribe or tracking link
            if any(term in url_lower for term in ["unsubscribe", "iterable-links", "optout", "click.email", "mailchimp"]):
                return "[Unsubscribe Link]"

            try:
                parsed = urllib.parse.urlparse(url)
                # If query params are huge (>40 chars), strip parameters
                if len(parsed.query) > 40:
                    clean_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
                    return clean_url
            except Exception:
                pass

            if len(url) > 100:
                return url[:80] + "..."

            return url

        # Regex for HTTP/HTTPS URLs
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        return re.sub(url_pattern, _clean_match, text)

    @staticmethod
    def strip_disclaimers_and_footers(text: str) -> str:
        """Strips common legal disclaimers and boilerplate footers."""
        if not text:
            return ""

        disclaimer_patterns = [
            r'this email and any attachments are confidential.*',
            r'if you are not the intended recipient.*',
            r'this message contains confidential information.*',
            r'if you received this in error.*'
        ]

        cleaned = text
        for pattern in disclaimer_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)

        return cleaned


# Aliases for backward compatibility
LLMContentCompressor = LLMContentCompressorService
ContentCompressorService = LLMContentCompressorService
