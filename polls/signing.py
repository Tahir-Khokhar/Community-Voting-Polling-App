"""
Tamper-proof anonymous voter tokens built on Django's signing framework.

The goal: let an anonymous visitor vote exactly once on a poll, without an
account, while making it impossible to forge or reuse another voter's token.

How it works
------------
1. When an anonymous visitor opens a poll detail page we mint a *voter id* —
   a random opaque string — and sign it together with the poll id using
   ``django.core.signing.TimestampSigner``. The signed blob is the *token*.
2. The token is stored in a cookie scoped to the poll and sent back on vote.
3. On vote we unsign the token (verifying the signature + freshness) and use
   the embedded voter id as the ``Ballot.voter_token`` uniqueness key.
4. Because the id is signed by the server, a visitor cannot fabricate a new
   id to vote twice — they'd need the server's ``SECRET_KEY``.

The token is *not* a session id and carries no personal data: it is just
``{poll_id}:{random_id}`` signed and base64-encoded.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner


def get_signer() -> TimestampSigner:
    """A signer keyed off the project SECRET_KEY."""
    return TimestampSigner()


def mint_voter_token(poll_id) -> str:
    """
    Create a fresh, signed anonymous voter token for ``poll_id``.

    Returns a string safe to drop into a cookie or query parameter.
    """
    voter_id = secrets.token_hex(
        settings.POLL_SETTINGS["ANON_TOKEN_ID_LENGTH"] // 2
    )
    payload = f"{poll_id}:{voter_id}"
    return get_signer().sign(payload)


def verify_voter_token(token: str, poll_id) -> str | None:
    """
    Validate ``token`` against ``poll_id`` and return the embedded voter id.

    Returns ``None`` if the signature is bad, the token is expired, or the
    embedded poll id does not match the expected one.
    """
    if not token:
        return None
    signer = get_signer()
    try:
        payload = signer.unsign(
            token, max_age=settings.POLL_SETTINGS["ANON_TOKEN_MAX_AGE"]
        )
    except (BadSignature, SignatureExpired):
        return None

    if ":" not in payload:
        return None
    token_poll_id, voter_id = payload.split(":", 1)
    if str(token_poll_id) != str(poll_id):
        return None
    return voter_id


# Cookie name we use to remember an anonymous voter per poll.
def cookie_name(poll_id) -> str:
    return f"poll_voter_{poll_id}"
