"""A simple greeting script for the grace-code repository."""


def greet(name: str = "World") -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet())
