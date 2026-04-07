def has_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """
    Check if two time ranges overlap.
    Args are all in HH:mm format (24 hour).
    """

    return start1 < end2 and end1 > start2
