from sqlalchemy.orm import Session

from .models import AuditEvent


def record(db: Session, username: str, action: str, entity: str, entity_id: int | None, summary: str) -> None:
    """Add an audit entry. The caller commits, so the entry is saved together with the change."""
    db.add(AuditEvent(username=username or "system", action=action, entity=entity, entity_id=entity_id, summary=summary))
