"""Bulk reads for one catalog response; never cached across users or requests."""
from collections import defaultdict

from .storage import db, all_admin_ids
from .tool_access import can_read


class CatalogSnapshot:
    def __init__(self, tools, viewer, taxonomy):
        database = db()
        self.tools = {tool['_id']: tool for tool in tools}
        self.taxonomy = {row['_id']: row for row in taxonomy}
        ids = list(self.tools)
        uid = viewer['id']
        managed = {tool['_id'] for tool in tools
                   if viewer['role'] == 'admin' or tool['owner'] == uid}
        # Only this viewer's decisions and the requests they can manage are read.
        query = {'$or': [{'tool': {'$in': ids}, 'user': uid},
                         {'tool': {'$in': list(managed)}}]}
        self.access_rows = list(database.access.find(query).sort([('updated', -1), ('_id', 1)])) if ids else []
        self.access = {row['tool']: row for row in self.access_rows if row['user'] == uid}
        self.subscriptions = {row['tool']: row for row in database.subscriptions.find(
            {'tool': {'$in': ids}, 'user': uid}, {'tool': 1, 'enabled': 1})} if ids else {}
        # Department rules must use the stored SSO department, not editable aliases
        # or the public profile. Preserve the same decision as mongo_api.allowed.
        profile = database.users.find_one({'_id': uid}, {'enabled': 1, 'dept': 1, 'dept_cd': 1}) \
            if any(tool.get('departmentGrants') for tool in tools) else None
        administrator = uid in all_admin_ids() if ids else False
        self.readable = {tool['_id'] for tool in tools if can_read(
            tool, uid, profile if tool.get('departmentGrants') else viewer,
            administrator=administrator,
            personal_grant=self.access.get(tool['_id'], {}).get('granted') is True)}
        self.feedback = defaultdict(list)
        names = {tool['owner'] for tool in tools}
        names.update(row['user'] for row in self.access_rows if row['tool'] in managed)
        if self.readable:
            for row in database.feedback.find({'tool': {'$in': list(self.readable)}}).sort('created', -1):
                self.feedback[row['tool']].append(row)
                names.add(row['user'])
                names.update(reply['user'] for reply in row.get('replies', []))
        self.users = {row['_id']: row for row in database.users.find(
            {'_id': {'$in': list(names)}}, {'name': 1})} if names else {}

    def name_of(self, uid):
        row = self.users.get(uid)
        return row['name'] if row else uid
