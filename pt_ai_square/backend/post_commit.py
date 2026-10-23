"""Durable follow-up effects stored with their authoritative document write."""
import secrets
import time

from flask import current_app
from pymongo.errors import PyMongoError

from .mongo_errors import mongo_diagnostic
from .storage import db


def audit_job(job_id, user, action, *, subscription=None):
    """Use a stable operation ID so a repeated drain cannot duplicate the audit."""
    job = {'_id': job_id, 'audit': {
        '_id': 'post-commit:' + job_id, 'user': user,
        'action': action, 'created': time.time(),
    }}
    if subscription is not None:
        job['subscription'] = subscription
    return job


def drain(collection_name=None, document_id=None):
    """Replay only the tools/settings maintenance queues; remove completed jobs."""
    collections = ('tools', 'settings') if collection_name is None else (collection_name,)
    if any(name not in {'tools', 'settings'} for name in collections):
        raise ValueError('Unsupported post-commit collection')
    count = 0
    for name in collections:
        collection = db()[name]
        query = {'postCommit.0': {'$exists': True}}
        if document_id is not None:
            query['_id'] = document_id
        for row in collection.find(query, {'postCommit': 1}):
            for job in row['postCommit']:
                subscription = job.get('subscription')
                if subscription:
                    # A delayed job must never re-enable a user's later opt-out.
                    db().subscriptions.update_one(
                        subscription, {'$setOnInsert': {'enabled': True}}, upsert=True)
                entry = job['audit']
                db().audit.update_one({'_id': entry['_id']}, {'$setOnInsert': entry}, upsert=True)
                # A crash or write error before this point leaves an idempotent job.
                collection.update_one({'_id': row['_id']},
                                      {'$pull': {'postCommit': {'_id': job['_id']}}})
                count += 1
    return count


def followup_pending(operation, callback, *args):
    """Only secondary Mongo failures may defer; never wrap a primary mutation."""
    try:
        callback(*args)
    except PyMongoError as error:
        diagnostic = mongo_diagnostic(error)
        current_app.logger.warning(
            'MongoDB follow-up deferred operation=%s diagnostic=%s mongo_code=%s reference=%s',
            operation, diagnostic['code'], diagnostic['mongo_code'], secrets.token_hex(6))
        return True
    return False
