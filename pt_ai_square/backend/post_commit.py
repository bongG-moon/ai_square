"""Durable follow-up effects stored with their authoritative document write."""
import secrets
import time
from dataclasses import dataclass

from flask import current_app
from pymongo.errors import PyMongoError

from .mongo_errors import mongo_diagnostic
from .storage import db


@dataclass(frozen=True)
class DeliveryResult:
    """Separate completed work from deferred work; counts are not booleans."""
    processed: int = 0
    pending: bool = False


def log_deferred(operation, error):
    """Log only classified diagnostics, never server messages or credentials."""
    diagnostic = mongo_diagnostic(error)
    current_app.logger.warning(
        'MongoDB follow-up deferred operation=%s diagnostic=%s mongo_code=%s reference=%s',
        operation, diagnostic['code'], diagnostic['mongo_code'], secrets.token_hex(6))


def audit_job(job_id, user, action, *, subscription=None):
    """Use a stable operation ID so a repeated drain cannot duplicate the audit."""
    job = {'_id': job_id, 'audit': {
        '_id': 'post-commit:' + job_id, 'user': user,
        'action': action, 'created': time.time(),
    }}
    if subscription is not None:
        job['subscription'] = subscription
    return job


def deliver_job(collection, document_id, job):
    """Deliver one legacy job; the caller owns error isolation and its budget."""
    subscription = job.get('subscription')
    from .permanent_delete import deletion_started
    if subscription and not deletion_started('tool', subscription['tool']):
        db().subscriptions.update_one(
            subscription, {'$setOnInsert': {'enabled': True}}, upsert=True)
    entry = job['audit']
    db().audit.update_one({'_id': entry['_id']}, {'$setOnInsert': entry}, upsert=True)
    if subscription:
        from .permanent_delete import cleanup_if_deleted
        cleanup_if_deleted('tool', subscription['tool'])
    collection.update_one({'_id': document_id},
                          {'$pull': {'postCommit': {'_id': job['_id']}}})


def drain(collection_name=None, document_id=None):
    """Bounded replay for legacy tools/settings queues written before outbox."""
    collections = ('tools', 'settings') if collection_name is None else (collection_name,)
    if any(name not in {'tools', 'settings'} for name in collections):
        raise ValueError('Unsupported post-commit collection')
    count = 0
    pending = False
    for name in collections:
        collection = db()[name]
        query = {'postCommit.0': {'$exists': True}}
        if document_id is not None:
            query['_id'] = document_id
        try:
            rows = list(collection.find(query, {'postCommit': 1}).limit(51))
        except PyMongoError as error:
            log_deferred('legacy-post-commit-scan', error)
            pending = True
            continue
        pending = len(rows) > 50 or pending
        for row in rows[:50]:
            jobs = row['postCommit']
            pending = len(jobs) > 50 or pending
            for job in jobs[:50]:
                try:
                    deliver_job(collection, row['_id'], job)
                    count += 1
                except PyMongoError as error:
                    log_deferred('legacy-post-commit-event', error)
                    pending = True
    return DeliveryResult(count, pending)


def followup_pending(operation, callback, *args):
    """Only secondary Mongo failures may defer; never wrap a primary mutation."""
    try:
        result = callback(*args)
    except PyMongoError as error:
        log_deferred(operation, error)
        return True
    return result.pending if isinstance(result, DeliveryResult) else False
