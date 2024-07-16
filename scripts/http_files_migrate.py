#!/usr/bin/env girder-shell
# -*- coding: utf-8 -*-

"""Migrate HTTP(S) registered data to new format.

This script should be used to migrate registered HTTP(s) resources from the root of the Catalog
into folder hierarchy based on url path.
See https://github.com/whole-tale/girder_wholetale/pull/266

Example:

    $ ./http_files_migrate.py

"""

from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.user import User
from girder.utility.progress import ProgressContext
from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wholetale.utils import getOrCreateRootFolder
from girder.plugins.wholetale.constants import CATALOG_NAME
from girder.plugins.wholetale.lib.entity import Entity
from girder.plugins.wholetale.lib.http_provider import HTTPImportProvider


CAT_ROOT = getOrCreateRootFolder(CATALOG_NAME)
base_url = 'https://dev.nceas.ucsb.edu/knb/d1/mn/v2'


def migrate_item(item):
    _file = list(Item().childFiles(item))[0]
    url = _file['linkUrl']
    if url.startswith('https://dashboard.wholetale.org'):
        return 0
    creator = User().load(item['creatorId'], force=True)

    # register url
    entity = Entity(url.strip(), creator)
    provider = HTTPImportProvider()
    try:
        dataMap = provider.lookup(entity)
    except Exception:
        print("  -> Failed to resolve {} as HTTP".format(url))
        print("  -> item_id = {}".format(str(item["_id"])))
        return 0
    ds = dataMap.toDict()

    if not ds['name']:
        print("  -> Item has no name!!!")
        print(ds)
        return 0

    with ProgressContext(True, user=creator, title='Registering resources') as ctx:
        objType, new_item = provider.register(
            CAT_ROOT, 'folder', ctx, creator, dataMap, base_url=base_url
        )

    # find userData and replace with new id
    for user in User().find({'myData': item['_id']}):
        print(
            '  Updating {} in myData for user "{}"'.format(item['name'], user['login'])
        )
        user['myData'][user['myData'].index(item['_id'])] = new_item['_id']
        user = User().save(user)

    # find tale dataset and switch id
    for tale in Tale().find({'dataSet.itemId': str(item['_id'])}):
        print(
            '  Updating {} in dataSet of Tale: "{}"'.format(item['name'], tale['title'])
        )
        for i, ds in enumerate(tale['dataSet']):
            if ds['itemId'] == str(item['_id']):
                tale['dataSet'][i]['itemId'] = str(new_item['_id'])
                Tale().save(tale)

    return 1


migrated_items = 0
for item in Folder().childItems(CAT_ROOT):
    migrated_items += migrate_item(item)
    Item().remove(item)

for item in Item().find(
    {'meta.provider': 'HTTP', 'meta.identifier': {'$in': ["unknown", None]}}
):
    migrated_items += migrate_item(item)
    Item().remove(item)

print("TOTAL MIGRATED ITEMS = {}".format(migrated_items))
