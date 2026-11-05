"""Celery task: try queued messages again."""

from __future__ import annotations

from hubra.core.modules import per_tenant_job
from hubra.core.tasks import celery_app

from . import services


@celery_app.task(name="hubra_messengers.tasks.retry")
@per_tenant_job("messengers")
def retry() -> dict:
    from hubra.core.extensions import db

    done = services.retry()
    db.session.commit()
    return done
