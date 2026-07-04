import re

class ContentCompressorService:
    @staticmethod
    def compress_email_body(body: str, max_chars: int = 4000) -> str:
        """
        Compresses an email body to reduce LLM token usage.
        - Removes quoted historical threads (lines starting with '>')
        - Removes generic signatures
        - Truncates to max_chars
        """
        if not body:
            return ""

        lines = body.split('\n')
        compressed_lines = []
        
        for line in lines:
            # Skip heavily quoted lines
            if line.strip().startswith('>'):
                continue
                
            # Stop if we hit a common signature or forwarding boundary
            lower_line = line.strip().lower()
            if lower_line in ["--", "-- ", "best,", "best regards,", "thanks,", "thank you,"] or lower_line.startswith("from: "):
                break
                
            if line.strip():
                compressed_lines.append(line.strip())

        compressed_text = " ".join(compressed_lines)
        
        # Collapse multiple spaces
        compressed_text = re.sub(r'\s+', ' ', compressed_text)
        
        if len(compressed_text) > max_chars:
            return compressed_text[:max_chars].rsplit(' ', 1)[0] + "..."
            
        return compressed_text
