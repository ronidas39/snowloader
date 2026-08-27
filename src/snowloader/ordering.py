"""Sort key construction for paginated reads.

Offset pagination is only safe over a unique sort key. ServiceNow does not
guarantee a stable order inside a group of rows that tie on the sort column,
so a page boundary landing inside a tied group can return some rows twice and
skip others. The returned count still reconciles, which is what makes it
dangerous.

Everything here exists to guarantee that whatever a caller sorts by, the chain
sent to the instance ends in ``sys_id``.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from snowloader.exceptions import SnowConnectionError

#: Column ServiceNow sorts by when the caller expresses no preference.
DEFAULT_ORDER_BY = "sys_created_on"

#: The only column on any ServiceNow table guaranteed unique, which is what
#: makes it the tiebreak that turns offset paging deterministic.
UNIQUE_SORT_KEY = "sys_id"

_ORDER_PREFIXES = ("ORDERBYDESC", "ORDERBY")

OrderBy = str | Sequence[str] | None


def _to_clause(token: str) -> str:
    """Turn one caller token into a ServiceNow ORDERBY clause.

    A bare column name gets the prefix. A token that already carries one is
    forwarded untouched, which is how a descending sort is expressed.
    """
    stripped = token.strip()
    if stripped.startswith(_ORDER_PREFIXES):
        return stripped
    return f"ORDERBY{stripped}"


def _column_of(clause: str) -> str:
    """Return the column a clause sorts on, without its prefix."""
    for prefix in _ORDER_PREFIXES:
        if clause.startswith(prefix):
            return clause[len(prefix) :]
    return clause


def normalise_order_by(order_by: OrderBy) -> tuple[str, ...]:
    """Build the ORDERBY chain for a paginated request.

    The chain always ends in ``ORDERBYsys_id`` unless the caller already
    sorts on ``sys_id``, in which case it is already unique and nothing is
    appended.

    Args:
        order_by: A column name, a sequence of column names, a ready-made
            ServiceNow clause such as ``"ORDERBYDESCsys_created_on"``, or
            None to disable ordering entirely.

    Returns:
        Ordered tuple of ORDERBY clauses. Empty when ordering is disabled.

    Raises:
        SnowConnectionError: If order_by is an empty string or an empty
            sequence. Those read as mistakes rather than as an opt-out, and
            paginating without a sort key loses records, so they are refused
            instead of silently treated as None.

    Example:
        >>> normalise_order_by("sys_created_on")
        ('ORDERBYsys_created_on', 'ORDERBYsys_id')
        >>> normalise_order_by("sys_id")
        ('ORDERBYsys_id',)
        >>> normalise_order_by(None)
        ()
    """
    if order_by is None:
        return ()

    given = [order_by] if isinstance(order_by, str) else list(order_by)

    if not given:
        raise SnowConnectionError(
            "order_by must name at least one column.",
            detail=(
                "Pass a column name, a list of column names, or None to turn "
                "ordering off. An empty value is refused because paginating "
                "without a sort key silently loses records."
            ),
        )

    # A caller who already knows ServiceNow's encoding may hand over a whole
    # chain as one string. Splitting on the separator means the sys_id check
    # below sees each column, rather than treating the chain as one opaque
    # clause and appending a tiebreak that is already there.
    tokens: list[str] = []
    for entry in given:
        if not entry or not entry.strip():
            raise SnowConnectionError(
                "order_by must not contain an empty column name.",
                detail=f"Received {order_by!r}. Pass None to turn ordering off.",
            )
        tokens.extend(part for part in entry.split("^") if part.strip())

    clauses = [_to_clause(token) for token in tokens]

    if not any(_column_of(clause) == UNIQUE_SORT_KEY for clause in clauses):
        clauses.append(f"ORDERBY{UNIQUE_SORT_KEY}")

    return tuple(clauses)
