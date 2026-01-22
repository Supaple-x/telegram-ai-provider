from config.settings import settings


def split_message(text: str, max_length: int = None) -> list[str]:
    """
    Split long message into parts that fit Telegram's limit.
    Tries to split at paragraph or sentence boundaries.
    """
    if max_length is None:
        max_length = settings.max_message_length

    if len(text) <= max_length:
        return [text]

    parts = []
    current = ""

    # Split by paragraphs first
    paragraphs = text.split("\n\n")

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_length:
            if current:
                current += "\n\n" + paragraph
            else:
                current = paragraph
        else:
            if current:
                parts.append(current)

            # If single paragraph is too long, split by sentences
            if len(paragraph) > max_length:
                sentences = paragraph.replace(". ", ".|").split("|")
                current = ""

                for sentence in sentences:
                    if len(current) + len(sentence) + 1 <= max_length:
                        if current:
                            current += " " + sentence
                        else:
                            current = sentence
                    else:
                        if current:
                            parts.append(current)
                        # If sentence still too long, hard split
                        if len(sentence) > max_length:
                            while sentence:
                                parts.append(sentence[:max_length])
                                sentence = sentence[max_length:]
                            current = ""
                        else:
                            current = sentence
            else:
                current = paragraph

    if current:
        parts.append(current)

    return parts
