"""Agent runtime exceptions."""


class ChatTurnCancelled(Exception):
    """Raised when the user requests stopping the current chat turn."""
