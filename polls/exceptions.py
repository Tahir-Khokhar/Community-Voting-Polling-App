"""Domain-specific exceptions raised by the voting flow."""


class VotingError(Exception):
    """Base class for all voting-related errors."""


class PollClosed(VotingError):
    """The poll has expired and no longer accepts votes."""


class AlreadyVoted(VotingError):
    """This voter has already cast a ballot on the poll."""


class InvalidVote(VotingError):
    """The submitted vote was malformed (missing choice, bad ranks, etc.)."""
