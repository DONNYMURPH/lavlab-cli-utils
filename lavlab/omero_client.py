"""OMERO connection helpers.

Per the design: object lookups use the "dummy" group (-1) so objects are
visible across all groups the user belongs to; once a specific object is
being operated on, the connection is switched into that object's own group.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

import omero.sys
from omero.gateway import BlitzGateway

from lavlab.config import OmeroCreds

log = logging.getLogger(__name__)

ALL_GROUPS = -1


def connect(creds: OmeroCreds, retries: int = 5, base_delay: float = 1.0) -> BlitzGateway:
    """Connect to OMERO, retrying transient failures with exponential backoff."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            conn = BlitzGateway(
                creds.user, creds.password,
                host=creds.host, port=creds.port, secure=True,
            )
            if conn.connect():
                conn.SERVICE_OPTS.setOmeroGroup(ALL_GROUPS)
                return conn
            log.info("Failed to create OMERO session. Attempt %d/%d", attempt, retries)
            try:
                conn.close()
            except Exception:
                pass
        except Exception as exc:
            last_exc = exc
            log.info("Failed to create OMERO session. Attempt %d/%d: %s", attempt, retries, exc)

        if attempt < retries:
            time.sleep(base_delay * (2 ** (attempt - 1)) + random.random())

    raise RuntimeError(f"Failed to connect to OMERO after {retries} attempts") from last_exc


def switch_to_object_group(conn: BlitzGateway, obj) -> None:
    """Switch the connection's security context to the given object's own group."""
    group_id = obj.details.group.id.val
    conn.SERVICE_OPTS.setOmeroGroup(str(group_id))


def is_conn_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a transient OMERO/Ice connection failure."""
    name = type(exc).__name__
    msg = str(exc)
    return (
        "Ice" in name
        or "omero" in name.lower()
        or "connect" in msg.lower()
        or "timeout" in msg.lower()
        or "session" in msg.lower()
    )


def get_source_file_path(conn: BlitzGateway, image_id: int) -> Optional[str]:
    """Return the absolute server-side path of the primary file for an image.

    Uses the fileset -> usedFiles -> originalFile relationship so the path is
    always what OMERO recorded on import.
    """
    qs = conn.getQueryService()
    params = omero.sys.ParametersI()
    params.addId(image_id)
    files = qs.findAllByQuery(
        "select f from Image i "
        "join i.fileset fs "
        "join fs.usedFiles fe "
        "join fe.originalFile f "
        "where i.id = :id",
        params,
        conn.SERVICE_OPTS,
    )
    if not files:
        return None

    # Prefer the largest file -- that's the primary image file in a multi-file set.
    files.sort(key=lambda f: f.size.val if f.size is not None else 0, reverse=True)
    f = files[0]
    return "/OMERO/ManagedRepository/" + f.path.val + f.name.val


def iter_image_ids(conn: BlitzGateway, group_id: Optional[int] = None):
    """Yield image IDs to batch-process.

    If group_id is given, only that group's images are listed (and the
    connection stays scoped to that group). Otherwise all images visible
    across every group the user belongs to are listed (dummy group -1);
    callers must switch_to_object_group() before operating on each one.
    """
    if group_id is not None:
        conn.SERVICE_OPTS.setOmeroGroup(str(group_id))
    else:
        conn.SERVICE_OPTS.setOmeroGroup(ALL_GROUPS)

    for image in conn.getObjects("Image"):
        yield image.getId()
