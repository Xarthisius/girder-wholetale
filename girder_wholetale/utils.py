import os
import datetime
import pathlib
import six.moves.urllib as urllib

from girder.utility.model_importer import ModelImporter
from girder.models.notification import Notification
from girder.models.user import User
from girder.models.setting import Setting


NOTIFICATION_EXP_HOURS = 1
WT_EVENT_EXP_SECONDS = int(os.environ.get("GIRDER_WT_EVENT_EXP_SECONDS", 5))


def get_tale_dir_root(tale: dict, root_path_setting: str) -> pathlib.Path:
    root = Setting().get(root_path_setting)
    return pathlib.Path(root) / str(tale["_id"])[0:2] / str(tale["_id"])


def getOrCreateRootFolder(name, description=""):
    collection = ModelImporter.model("collection").createCollection(
        name, public=True, reuseExisting=True
    )
    folder = ModelImporter.model("folder").createFolder(
        collection,
        name,
        parentType="collection",
        public=True,
        reuseExisting=True,
        description=description,
    )
    return folder


def esc(value):
    """
    Escape a string so it can be used in a Solr query string
    :param value: The string that will be escaped
    :type value: str
    :return: The escaped string
    :rtype: str
    """
    return urllib.parse.quote_plus(value)


def notify_event(users, event, affectedIds):
    """
    Notify multiple users of a particular WT event
    :param users: Arrayof user IDs
    :param event: WT Event name
    :param affectedIds: Map of affected object Ids
    """
    data = {
        "event": event,
        "affectedResourceIds": affectedIds,
        "resourceName": "WT event",
    }

    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=WT_EVENT_EXP_SECONDS
    )

    for user_id in users:
        user = User().load(user_id, force=True)
        Notification().createNotification(
            type="wt_event", data=data, user=user, expires=expires
        )


def init_progress(resource, user, title, message, total):
    resource["jobCurrent"] = 0
    resource["jobId"] = None
    data = {
        "title": title,
        "total": total,
        "current": 0,
        "state": "active",
        "message": message,
        "estimateTime": False,
        "resource": resource,
        "resourceName": "WT custom resource",
    }

    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        hours=NOTIFICATION_EXP_HOURS
    )

    return Notification().createNotification(
        type="wt_progress", data=data, user=user, expires=expires
    )


def deep_get(dikt, path):
    """Get a value located in `path` from a nested dictionary.

    Use a string separated by periods as the path to access
    values in a nested dictionary:

    deep_get(data, "data.files.0") == data["data"]["files"][0]

    Taken from jupyter/repo2docker
    """
    value = dikt
    for component in path.split("."):
        if component.isdigit():
            value = value[int(component)]
        else:
            value = value[component]
    return value


def diff_access(access1, access2):
    """Diff two access lists to identify which users
    were added or removed.
    """
    existing = {str(user["id"]) for user in access1["users"]}
    new = {str(user["id"]) for user in access2["users"]}
    added = list(new - existing)
    removed = list(existing - new)
    return (added, removed)
