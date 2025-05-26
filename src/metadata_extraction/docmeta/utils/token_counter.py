import re
import tiktoken

# Default encoding for token counting
DEFAULT_ENCODING = "o200k_base"


def count_tokens(text_content: str, base: str = DEFAULT_ENCODING) -> int:
    """
    Count tokens in text.

    Args:
        text_content: Text to count tokens in
        base: Encoding to use (default: o200k_base)

    Returns:
        int: Token count, or 0 if text_content is empty or None.
    """
    if not text_content or not text_content.strip(): # Ensure stripped content is also checked
        return 0

    encoding = tiktoken.get_encoding(base)

    # Clean the text - remove excessive whitespace
    cleaned_text = re.sub(r'\s+', ' ', text_content).strip()
    return len(encoding.encode(cleaned_text))