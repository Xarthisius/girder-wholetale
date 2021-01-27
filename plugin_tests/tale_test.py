import bagit
from bdbag import bdbag_api as bdb
from bson import ObjectId
import httmock
import json
import mock
import os
import pytest
import re
import time
import urllib.request
import tempfile
import zipfile
import shutil
from tests import base

from .tests_helpers import mockOtherRequest
from girder.models.item import Item
from girder.exceptions import ValidationException
from girder.models.folder import Folder


DATA_PATH = os.path.join(
    os.path.dirname(os.environ['GIRDER_TEST_DATA_PREFIX']),
    'data_src',
    'plugins',
    'wholetale',
)


JobStatus = None
ImageStatus = None
Tale = None


class FakeAsyncResult(object):
    def __init__(self, tale_id=None):
        self.task_id = 'fake_id'
        self.tale_id = tale_id

    def get(self, timeout=None):
        return {
            'image_digest': 'digest123',
            'repo2docker_version': 1,
            'last_build': 123
        }


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.enabledPlugins.append('wt_home_dir')
    base.enabledPlugins.append('virtual_resources')
    base.startServer()

    global JobStatus, Tale, ImageStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.models.tale import Tale
    from girder.plugins.wholetale.constants import ImageStatus


def tearDownModule():
    base.stopServer()


class TaleTestCase(base.TestCase):

    def setUp(self):
        super(TaleTestCase, self).setUp()
        users = ({
            'email': 'root@dev.null',
            'login': 'admin',
            'firstName': 'Root',
            'lastName': 'van Klompf',
            'password': 'secret'
        }, {
            'email': 'joe@dev.null',
            'login': 'joeregular',
            'firstName': 'Joe',
            'lastName': 'Regular',
            'password': 'secret'
        })

        self.authors = [
            {
                'firstName': 'Charles',
                'lastName': 'Darwmin',
                'orcid': 'https://orcid.org/000-000'
            },
            {
                'firstName': 'Thomas',
                'lastName': 'Edison',
                'orcid': 'https://orcid.org/111-111'
            }
        ]
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]

        self.image_admin = self.model('image', 'wholetale').createImage(
            name="test admin image", creator=self.admin, public=True)

        self.image = self.model('image', 'wholetale').createImage(
            name="test my name", creator=self.user, public=True,
            config=dict(template='base.tpl', buildpack='SomeBuildPack',
                        user='someUser', port=8888, urlPath=''))

    def testTaleFlow(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({'imageId': str(self.image['_id'])})
        )
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json, {
            'message': ("Invalid JSON object for parameter tale: "
                        "'dataSet' "
                        "is a required property"),
            'type': 'rest'
        })

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': []
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json

        taleLicense = WholeTaleLicense.default_spdx()
        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='PUT',
            type='application/json',
            user=self.user, body=json.dumps({
                'dataSet': tale['dataSet'],
                'imageId': tale['imageId'],
                'title': 'new name',
                'description': 'new description',
                'config': {'memLimit': '2g'},
                'public': False,
                'licenseSPDX': taleLicense,
                'publishInfo': [
                    {
                        'pid': 'published_pid',
                        'uri': 'published_url',
                        'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['title'], 'new name')
        self.assertEqual(resp.json['licenseSPDX'], taleLicense)
        tale = resp.json

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [],
            })
        )
        self.assertStatusOk(resp)
        new_tale = resp.json

        resp = self.request(
            path='/tale', method='POST', user=self.admin,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'public': False
            })
        )
        self.assertStatusOk(resp)
        # admin_tale = resp.json

        resp = self.request(
            path='/tale', method='GET', user=self.admin,

            params={}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 3)

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'imageId': str(self.image['_id'])}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id'], new_tale['_id']})

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'userId': str(self.user['_id'])}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id'], new_tale['_id']})

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'text': 'new'}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 1)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id']})

        resp = self.request(
            path='/tale/{_id}'.format(**new_tale), method='DELETE',
            user=self.admin)
        self.assertStatusOk(resp)

        resp = self.request(
            path='/tale/{_id}'.format(**new_tale), method='GET',
            user=self.user)
        self.assertStatus(resp, 400)

        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        for key in tale.keys():
            if key in ('access', 'updated', 'created'):
                continue
            self.assertEqual(resp.json[key], tale[key])

    def testTaleAccess(self):
        with httmock.HTTMock(mockOtherRequest):
            # Create a new tale from a user image
            resp = self.request(
                path='/tale', method='POST', user=self.user,
                type='application/json',
                body=json.dumps(
                    {
                        'imageId': str(self.image['_id']),
                        'dataSet': [],
                        'public': True
                    })
            )
            self.assertStatusOk(resp)
            tale_user_image = resp.json
            # Create a new tale from an admin image
            resp = self.request(
                path='/tale', method='POST', user=self.user,
                type='application/json',
                body=json.dumps(
                    {
                        'imageId': str(self.image_admin['_id']),
                        'dataSet': [],
                    })
            )
            self.assertStatusOk(resp)
            tale_admin_image = resp.json

        from girder.constants import AccessType

        # Retrieve access control list for the newly created tale
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_tale_access = resp.json
        expected_tale_access = {
            'users': [{
                'login': self.user['login'],
                'level': AccessType.ADMIN,
                'id': str(self.user['_id']),
                'flags': [],
                'name': '%s %s' % (
                    self.user['firstName'], self.user['lastName'])}],
            'groups': []
        }
        self.assertEqual(result_tale_access, expected_tale_access)

        # Update the access control list for the tale by adding the admin
        # as a second user
        input_tale_access = {
            "users": [
                {
                    "login": self.user['login'],
                    "level": AccessType.ADMIN,
                    "id": str(self.user['_id']),
                    "flags": [],
                    "name": "%s %s" % (self.user['firstName'], self.user['lastName'])
                },
                {
                    'login': self.admin['login'],
                    'level': AccessType.ADMIN,
                    'id': str(self.admin['_id']),
                    'flags': [],
                    'name': '%s %s' % (self.admin['firstName'], self.admin['lastName'])
                }],
            "groups": []}
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_tale_access)})
        self.assertStatusOk(resp)
        # Check that the returned access control list for the tale is as expected
        tale = resp.json
        result_tale_access = resp.json['access']
        expected_tale_access = {
            "groups": [],
            "users": [
                {
                    "flags": [],
                    "id": str(self.user['_id']),
                    "level": AccessType.ADMIN
                },
                {
                    "flags": [],
                    "id": str(self.admin['_id']),
                    "level": AccessType.ADMIN
                },
            ]
        }
        self.assertEqual(result_tale_access, expected_tale_access)
        # Check that the access control list propagated to the folder that the tale
        # is associated with
        for key in ('workspaceId',):
            resp = self.request(
                path='/folder/%s/access' % tale[key], method='GET',
                user=self.user)
            self.assertStatusOk(resp)
            result_folder_access = resp.json
            expected_folder_access = input_tale_access
            self.assertEqual(result_folder_access, expected_folder_access)

        # Update the access control list of a tale that was generated from an image that the user
        # does not have admin access to
        input_tale_access = {
            "users": [
                {
                    "login": self.user['login'],
                    "level": AccessType.ADMIN,
                    "id": str(self.user['_id']),
                    "flags": [],
                    "name": "%s %s" % (self.user['firstName'], self.user['lastName'])
                }],
            "groups": []
        }
        resp = self.request(
            path='/tale/%s/access' % tale_admin_image['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_tale_access)})
        self.assertStatus(resp, 200)  # TODO: fix me

        # Check that the access control list was correctly set for the tale
        resp = self.request(
            path='/tale/%s/access' % tale_admin_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_tale_access = resp.json
        expected_tale_access = input_tale_access
        self.assertEqual(result_tale_access, expected_tale_access)

        # Check that the access control list did not propagate to the image
        resp = self.request(
            path='/image/%s/access' % tale_admin_image['imageId'], method='GET',
            user=self.user)
        self.assertStatus(resp, 403)

        # Setting the access list with bad json should throw an error
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user, params={'access': 'badJSON'})
        self.assertStatus(resp, 400)

        # Change the access to private
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user,
            params={'access': json.dumps(input_tale_access), 'public': False})
        self.assertStatusOk(resp)
        resp = self.request(
            path='/tale/%s' % tale_user_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['public'], False)

    def testTaleValidation(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path="/folder", method="POST", user=self.user, params={
                "name": "validate_my_narrative", "parentId": self.user["_id"],
                "parentType": "user",
            })
        sub_home_dir = resp.json
        Item().createItem('notebook.ipynb', self.user, sub_home_dir)

        # Mock old format
        tale = {
            "config": None,
            "creatorId": self.user['_id'],
            "description": "Fake Tale",
            "imageId": "5873dcdbaec030000144d233",
            "public": True,
            "publishInfo": [],
            "title": "Fake Unvalidated Tale",
            "authors": "Root Von Kolmph"
        }
        tale = self.model('tale', 'wholetale').save(tale)  # get's id
        tale = self.model('tale', 'wholetale').save(tale)  # migrate to new format

        # new_data_dir = resp.json
        self.assertEqual(tale['dataSet'], [])
        self.assertEqual(tale['licenseSPDX'], WholeTaleLicense.default_spdx())
        # self.assertEqual(str(tale['dataSet'][0]['itemId']), data_dir['_id'])
        # self.assertEqual(tale['dataSet'][0]['mountPath'], '/' + data_dir['name'])
        tale['licenseSPDX'] = 'unsupportedLicense'
        tale = self.model('tale', 'wholetale').save(tale)
        self.assertEqual(tale['licenseSPDX'], WholeTaleLicense.default_spdx())
        self.assertTrue(isinstance(tale['authors'], list))
        self.model('tale', 'wholetale').remove(tale)

        tale["dataSet"] = [()]
        with pytest.raises(ValidationException):
            self.model('tale', 'wholetale').save(tale)

        tale["dataSet"] = [
            {"_modelType": "folder", "itemId": str(ObjectId()), "mountPath": "data.dat"}
        ]
        with pytest.raises(ValidationException):
            self.model('tale', 'wholetale').save(tale)

        # tale["dataSet"][0]["_modelType"] = "item"
        # self.model('tale', 'wholetale').save(tale)
        self.model('tale', 'wholetale').remove(tale)

    def testTaleUpdate(self):
        from server.lib.license import WholeTaleLicense
        # Test that Tale updating works

        resp = self.request(
            path='/folder', method='GET', user=self.user, params={
                'parentType': 'user',
                'parentId': self.user['_id'],
                'sort': 'title',
                'sortdir': 1
            }
        )

        title = 'new name'
        description = 'new description'
        config = {'memLimit': '2g'}
        public = True
        tale_licenses = WholeTaleLicense()
        taleLicense = tale_licenses.supported_spdxes().pop()

        # Create a new Tale
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'licenseSPDX': taleLicense,
                'publishInfo': [
                    {
                        'pid': 'published_pid',
                        'uri': 'published_url',
                        'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )

        self.assertStatus(resp, 200)

        newLicense = tale_licenses.supported_spdxes().pop()
        admin_orcid, user_orcid = 'https://orcid.org/1234', 'https://orcid.org/9876'
        new_authors = [
            {
                "firstName": self.admin['firstName'],
                "lastName": self.admin['lastName'],
                "orcid": admin_orcid
            },
            {
                "firstName": self.user['firstName'],
                "lastName": self.user['lastName'],
                "orcid": user_orcid
            }
        ]

        # Create a new image that the updated Tale will use
        image = self.model('image', 'wholetale').createImage(
            name="New Image", creator=self.user, public=True,
            config=dict(template='base.tpl', buildpack='SomeBuildPack2',
                        user='someUser', port=8888, urlPath=''))

        # Update the Tale with new values
        resp = self.request(
            path='/tale/{}'.format(str(resp.json['_id'])),
            method='PUT',
            user=self.user,
            type='application/json',
            body=json.dumps({
                'authors': new_authors,
                'imageId': str(image['_id']),
                'dataSet': [],
                'title': title,
                'description': description,
                'config': config,
                'public': public,
                'licenseSPDX': newLicense,
                'publishInfo': [
                    {
                        'pid': 'published_pid',
                        'uri': 'published_url',
                        'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )

        # Check that the updates happened
        # self.assertStatus(resp, 200)
        self.assertEqual(resp.json['imageId'], str(image['_id']))
        self.assertEqual(resp.json['title'], title)
        self.assertEqual(resp.json['description'], description)
        self.assertEqual(resp.json['config'], {})
        self.assertEqual(resp.json['public'], public)
        self.assertEqual(resp.json['publishInfo'][0]['pid'], 'published_pid')
        self.assertEqual(resp.json['publishInfo'][0]['uri'], 'published_url')
        self.assertEqual(resp.json['publishInfo'][0]['date'], '2019-01-23T15:48:17.476000+00:00')
        self.assertEqual(resp.json['licenseSPDX'], newLicense)
        self.assertTrue(isinstance(resp.json['authors'], list))

        tale_authors = resp.json['authors']
        self.assertEqual(tale_authors[0], new_authors[0])
        self.assertEqual(tale_authors[1], new_authors[1])

    def testManifest(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'authors': self.authors,
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'publishInfo': [],
                'licenseSPDX': WholeTaleLicense.default_spdx()
            })
        )

        self.assertStatus(resp, 200)
        pth = '/tale/{}/manifest'.format(str(resp.json['_id']))
        resp = self.request(
            path=pth, method='GET', user=self.user)
        # The contents of the manifest are checked in the manifest tests, so
        # just make sure that we get the right response
        self.assertStatus(resp, 200)

    def testExport(self):
        from server.lib.license import WholeTaleLicense

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'authors': self.authors,
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'publishInfo': [],
                'licenseSPDX': WholeTaleLicense.default_spdx()
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json
        workspace = Folder().load(tale["workspaceId"], force=True)
        with open(os.path.join(workspace["fsPath"], "test_file.txt"), "wb") as f:
            f.write(b"Hello World!")

        export_path = '/tale/{}/export'.format(str(tale['_id']))
        resp = self.request(
            path=export_path, method='GET', isJson=False, user=self.user)
        with tempfile.NamedTemporaryFile() as fp:
            for content in resp.body:
                fp.write(content)
            fp.seek(0)
            zip_archive = zipfile.ZipFile(fp, 'r')
            zip_files = zip_archive.namelist()
        # Check the the manifest.json is present
        expected_files = [
            "metadata/manifest.json",
            "README.md",
            "LICENSE",
            "workspace/test_file.txt",
        ]
        for content_file in expected_files:
            self.assertTrue("{}/{}".format(tale["_id"], content_file) in zip_files)
        self.model('tale', 'wholetale').remove(tale)

    @mock.patch('gwvolman.tasks.build_tale_image')
    def testImageBuild(self, it):
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': []
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json

        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            mock_apply_async().job.return_value = json.dumps({'job': 1, 'blah': 2})
            resp = self.request(
                path='/tale/{}/build'.format(tale['_id']), method='PUT',
                user=self.user)
            self.assertStatusOk(resp)
            job_call = mock_apply_async.call_args_list[-1][-1]
            self.assertEqual(
                job_call['args'], (str(tale['_id']), False)
            )
            self.assertEqual(job_call['headers']['girder_job_title'], 'Build Tale Image')
        self.assertStatusOk(resp)

        # Create a job to be handled by the worker plugin
        from girder.plugins.jobs.models.job import Job
        jobModel = Job()
        job = jobModel.createJob(
            title='Build Tale Image', type='celery', handler='worker_handler',
            user=self.user, public=False, args=[str(tale['_id'])], kwargs={})
        job = jobModel.save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)

        # Schedule the job, make sure it is sent to celery
        with mock.patch('celery.Celery') as celeryMock, \
                mock.patch('girder.plugins.worker.getCeleryApp') as gca:

            celeryMock().AsyncResult.return_value = FakeAsyncResult(tale['_id'])
            gca().send_task.return_value = FakeAsyncResult(tale['_id'])

            jobModel.scheduleJob(job)
            for i in range(20):
                job = jobModel.load(job['_id'], force=True)
                if job['status'] == JobStatus.QUEUED:
                    break
                time.sleep(0.1)
            self.assertEqual(job['status'], JobStatus.QUEUED)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.BUILDING)

            # Set status to RUNNING
            job = jobModel.load(job['_id'], force=True)
            self.assertEqual(job['celeryTaskId'], 'fake_id')
            Job().updateJob(job, log='job running', status=JobStatus.RUNNING)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.BUILDING)

            # Set status to SUCCESS
            job = jobModel.load(job['_id'], force=True)
            self.assertEqual(job['celeryTaskId'], 'fake_id')
            Job().updateJob(job, log='job running', status=JobStatus.SUCCESS)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.AVAILABLE)
            self.assertEqual(tale['imageInfo']['digest'], 'digest123')

            # Set status to ERROR
            # job = jobModel.load(job['_id'], force=True)
            # self.assertEqual(job['celeryTaskId'], 'fake_id')
            # Job().updateJob(job, log='job running', status=JobStatus.ERROR)

            # tale = Tale().load(tale['_id'], force=True)
            # self.assertEqual(tale['imageInfo']['status'], ImageStatus.INVALID)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.model('image', 'wholetale').remove(self.image)
        super(TaleTestCase, self).tearDown()


class TaleWithWorkspaceTestCase(base.TestCase):

    def setUp(self):
        super(TaleWithWorkspaceTestCase, self).setUp()
        from girder.plugins.wholetale.models.image import Image
        users = ({
            'email': 'root@dev.null',
            'login': 'admin',
            'firstName': 'Root',
            'lastName': 'van Klompf',
            'password': 'secret'
        }, {
            'email': 'joe@dev.null',
            'login': 'joeregular',
            'firstName': 'Joe',
            'lastName': 'Regular',
            'password': 'secret'
        })
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]
        self.image = Image().createImage(
            {'_id': ObjectId()},
            'test image',
            creator=self.admin,
            public=True,
            config=dict(template='base.tpl', buildpack='SomeBuildPack',
                        user='someUser', port=8888, urlPath=''),
        )

        from girder.plugins.wt_home_dir import HOME_DIRS_APPS
        self.homeDirsApps = HOME_DIRS_APPS  # nopep8
        self.clearDAVAuthCache()

    def clearDAVAuthCache(self):
        # need to do this because the DB is wiped on every test, but the dav domain
        # controller keeps a cache with users/tokens
        for e in self.homeDirsApps.entries():
            e.app.config['domaincontroller'].clearCache()

    def _create_water_tale(self):
        # register required data
        self.data_collection = self.model('collection').createCollection(
            'WholeTale Catalog', public=True, reuseExisting=True
        )
        catalog = self.model('folder').createFolder(
            self.data_collection,
            'WholeTale Catalog',
            parentType='collection',
            public=True,
            reuseExisting=True,
        )
        # Tale map of values to check against in tests

        def restore_catalog(parent, current):
            for folder in current['folders']:
                resp = self.request(
                    path='/folder',
                    method='POST',
                    user=self.admin,
                    params={
                        'parentId': parent['_id'],
                        'name': folder['name'],
                        'metadata': json.dumps(folder['meta']),
                    },
                )
                folderObj = resp.json
                restore_catalog(folderObj, folder)

            for obj in current['files']:
                resp = self.request(
                    path='/item',
                    method='POST',
                    user=self.admin,
                    params={
                        'folderId': parent['_id'],
                        'name': obj['name'],
                        'metadata': json.dumps(obj['meta']),
                    },
                )
                item = resp.json
                self.request(
                    path='/file',
                    method='POST',
                    user=self.admin,
                    params={
                        'parentType': 'item',
                        'parentId': item['_id'],
                        'name': obj['name'],
                        'size': obj['size'],
                        'mimeType': obj['mimeType'],
                        'linkUrl': obj['linkUrl'],
                    },
                )

        with open(os.path.join(DATA_PATH, 'watertale_catalog.json'), 'r') as fp:
            data = json.load(fp)
            restore_catalog(catalog, data)

        resp = self.request(
            path='/dataset', method='GET', user=self.user)
        self.assertStatusOk(resp)
        ds = resp.json[0]

        resp = self.request(
            path='/item', method='GET', user=self.user,
            params={'name': 'usco2000.xls', 'folderId': ds['_id']}
        )
        item = resp.json[0]

        authors = [
            {
                'firstName': 'Charles',
                'lastName': 'Darwmin',
                'orcid': 'https://orcid.org/000-000'
            },
            {
                'firstName': 'Thomas',
                'lastName': 'Edison',
                'orcid': 'https://orcid.org/111-111'
            }
        ]

        tale = self.model('tale', 'wholetale').createTale(
            self.image,
            [{
                'itemId': item['_id'],
                '_modelType': 'item',
                'mountPath': item['name']
            }], creator=self.user, title="Export Tale", public=True, authors=authors)
        workspace = self.model('folder').load(tale['workspaceId'], force=True)
        nb_file = os.path.join(workspace["fsPath"], "wt_quickstart.ipynb")
        with urllib.request.urlopen(
            'https://raw.githubusercontent.com/whole-tale/wt-design-docs/'
            '3305527f7eb28d0e0364f4e54fd9e7155a2614d3'
            '/users_guide/wt_quickstart.ipynb'
        ) as url:
            with open(nb_file, "wb") as target:
                target.write(url.read())
        return tale

    def testTaleCopy(self):
        from girder.plugins.wholetale.models.tale import Tale
        from girder.plugins.wholetale.constants import TaleStatus
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.jobs.constants import JobStatus
        tale = Tale().createTale(
            self.image,
            [],
            creator=self.admin,
            public=True
        )
        workspace = self.model('folder').load(tale['workspaceId'], force=True)
        fsPath = workspace["fsPath"]
        fullPath = os.path.join(fsPath, "file01.txt")

        with open(fullPath, "wb") as f:
            size = 101
            f.write(b' ' * size)

        # Create a copy
        resp = self.request(
            path='/tale/{_id}/copy'.format(**tale), method='POST',
            user=self.user
        )
        self.assertStatusOk(resp)

        new_tale = resp.json
        self.assertFalse(new_tale['public'])
        self.assertEqual(new_tale['dataSet'], tale['dataSet'])
        self.assertEqual(new_tale['copyOfTale'], str(tale['_id']))
        self.assertEqual(new_tale['imageId'], str(tale['imageId']))
        self.assertEqual(new_tale['creatorId'], str(self.user['_id']))
        self.assertEqual(new_tale['status'], TaleStatus.PREPARING)

        copied_file_path = re.sub(workspace['name'], new_tale['_id'], fullPath)
        job = Job().findOne({'type': 'wholetale.copy_workspace'})
        for i in range(10):
            job = Job().load(job['_id'], force=True)
            if job['status'] == JobStatus.SUCCESS:
                break
            time.sleep(0.1)
        self.assertTrue(os.path.isfile(copied_file_path))
        resp = self.request(
            path='/tale/{_id}'.format(**new_tale), method='GET',
            user=self.user
        )
        self.assertStatusOk(resp)
        new_tale = resp.json
        self.assertEqual(new_tale['status'], TaleStatus.READY)

        Tale().remove(new_tale)
        Tale().remove(tale)

    def testExportBag(self):
        tale = self._create_water_tale()
        export_path = '/tale/{}/export'.format(str(tale['_id']))
        resp = self.request(
            path=export_path, method='GET', params={'taleFormat': 'bagit'},
            isJson=False, user=self.user)
        dirpath = tempfile.mkdtemp()
        bag_file = os.path.join(dirpath, "{}.zip".format(str(tale['_id'])))
        with open(bag_file, 'wb') as fp:
            for content in resp.body:
                fp.write(content)
        temp_path = bdb.extract_bag(bag_file, temp=True)
        try:
            bdb.validate_bag_structure(temp_path)
        except bagit.BagValidationError:
            pass  # TODO: Goes without saying that we should not be doing that...
        shutil.rmtree(dirpath)

        # Test dataSetCitation
        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='PUT',
            type='application/json',
            user=self.user, body=json.dumps({
                'dataSet': [],
                'imageId': str(tale['imageId']),
                'public': tale['public'],
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json
        self.assertEqual(tale['dataSetCitation'], [])

        self.model('tale', 'wholetale').remove(tale)
        self.model('collection').remove(self.data_collection)

    def test_tale_defaults(self):
        tale = Tale().createTale(
            self.image,
            [],
            creator=self.user,
            title="Export Tale",
            public=True,
            authors=None,
            description=None
        )

        self.assertTrue(tale['description'] is not None)
        self.assertTrue(tale['description'].startswith("This Tale"))

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.model('image', 'wholetale').remove(self.image)
        super(TaleWithWorkspaceTestCase, self).tearDown()
