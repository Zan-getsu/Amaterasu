def get_version() -> str:
    """
    Returns the version details. Do not Interfere with this !

    :return: The version details in the format 'vMAJOR.MINOR.PATCH'
    :rtype: str
    """
    MAJOR = "1"
    MINOR = "2"
    PATCH = "1"
    return f"v{MAJOR}.{MINOR}.{PATCH}"


if __name__ == "__main__":
    print(get_version())
